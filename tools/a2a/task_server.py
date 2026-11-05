"""Official A2A 1.0 JSON-RPC task transport, isolated from card discovery and finance."""
from __future__ import annotations

import base64
import json
from pathlib import Path
import time

from a2a.server.request_handlers import RequestHandler
from a2a.server.routes.jsonrpc_routes import create_jsonrpc_routes
from a2a.types import (AgentCard, CancelTaskRequest, GetTaskRequest, ListTasksRequest,
                       ListTasksResponse, Message, SendMessageRequest, Task)
from a2a.utils.errors import InvalidParamsError, TaskNotFoundError, UnsupportedOperationError
from google.protobuf.json_format import MessageToDict, ParseDict
from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Route

from tools.a2a.task_store import OfflineWorkOrders, TaskDenied, TaskLedger
from tools.mcp.security import AuthBoundary, CURRENT, Denied, RateLimiter, TokenVerifier
from tools.operations.structured_logs import emit


TASK_BINDING = "JSONRPC"
TASK_PATH = "/a2a/task-rpc"


def task_card(base_url: str) -> AgentCard:
    """Separate task card; never changes CON-39 discovery-only cards."""
    return ParseDict({
        "name": "Conatus Offline Task Executor",
        "description": "A2A task coordination over an explicit offline WorkOrder fixture.",
        "supportedInterfaces": [{"url": base_url.rstrip("/") + TASK_PATH,
                                 "protocolBinding": TASK_BINDING, "protocolVersion": "1.0"}],
        "version": "1.0.0", "capabilities": {"streaming": False,
             "pushNotifications": False,
             "extensions": [{"uri": "https://github.com/marcos1394/aerosettle/a2a/extensions/conatus-task/v1",
                             "required": False,
                             "params": {"evidenceSource": "OFFLINE_FIXTURE",
                                        "isFinancialAuthority": False}}]},
        "securitySchemes": {"ConatusBearer": {"httpAuthSecurityScheme": {
            "scheme": "bearer", "bearerFormat": "JWT"}}},
        "securityRequirements": [{"schemes": {"ConatusBearer": []}}],
        "defaultInputModes": ["text/plain", "application/json"],
        "defaultOutputModes": ["text/plain", "application/json"],
        "skills": [{"id": "conatus.task.coordinate", "name": "Coordinate task",
                    "description": "Coordinate an offline A2A task; no financial authority.",
                    "tags": ["conatus", "offline", "task"]}],
    }, AgentCard(), ignore_unknown_fields=False)


def _meta(message: Message) -> dict:
    value = MessageToDict(message.metadata)
    if not isinstance(value, dict) or set(value) != {"conatus"} or not isinstance(value["conatus"], dict):
        raise TaskDenied("INVALID_REQUEST")
    return value["conatus"]


class TaskHandler(RequestHandler):
    def __init__(self, ledger: TaskLedger, card: AgentCard):
        self.ledger, self.card = ledger, card
        self.rate = RateLimiter(limit=60)

    def _convert(self, exc: TaskDenied):
        try:
            emit("WARNING", "a2a_tasks", "authorization", error_category=exc.code,
                 authorization_result="DENIED")
            if self.ledger.operational_store is not None:
                name = ("a2a_correlation_errors" if exc.code in
                        ("RESOURCE_NOT_FOUND", "INTEGRITY_CONFLICT", "UNVERIFIABLE") else
                        "a2a_authorization_errors")
                self.ledger.operational_store.sample(name, 1, "events", "a2a-tasks")
        except Exception:
            pass
        if exc.code == "RESOURCE_NOT_FOUND":
            raise TaskNotFoundError(message="RESOURCE_NOT_FOUND") from exc
        raise InvalidParamsError(message=exc.code) from exc

    @staticmethod
    def _tenant(params) -> None:
        if params.tenant and params.tenant != CURRENT.get().tenant_id:
            raise TaskDenied("RESOURCE_NOT_FOUND")

    async def on_message_send(self, params: SendMessageRequest, context) -> Task:
        try:
            self._tenant(params)
            self.rate.check("SendMessage", params.message.task_id or "new")
            if params.configuration.HasField("task_push_notification_config"):
                raise TaskDenied("PUSH_NOT_SUPPORTED")
            message = params.message
            meta = _meta(message)
            principal = CURRENT.get()
            if message.role == 1:
                if set(meta) != ({"work_order_pda", "idempotency_key", "expires_at"}
                                 if not message.task_id else {"idempotency_key"}):
                    raise TaskDenied("INVALID_REQUEST")
                if not message.task_id:
                    if not isinstance(meta["work_order_pda"], str):
                        raise TaskDenied("INVALID_REQUEST")
                    expiry = meta["expires_at"]
                    if (isinstance(expiry, bool) or not isinstance(expiry, (int, float)) or
                            int(expiry) != expiry or expiry < 0 or expiry > 2**53):
                        raise TaskDenied("INVALID_REQUEST")
                    return self.ledger.create(principal, message,
                                              work_order_pda=meta["work_order_pda"],
                                              idempotency_key=meta["idempotency_key"],
                                              expires_at=int(expiry))
                return self.ledger.requester_message(principal, message,
                                                     idempotency_key=meta["idempotency_key"])
            if message.role == 2:
                if set(meta) != {"state", "idempotency_key"} or not message.task_id:
                    raise TaskDenied("INVALID_REQUEST")
                if not isinstance(meta["state"], str):
                    raise TaskDenied("INVALID_REQUEST")
                artifact = None
                text_message = Message()
                text_message.CopyFrom(message)
                raw_parts = [part for part in text_message.parts
                             if part.WhichOneof("content") == "raw"]
                if len(raw_parts) > 1:
                    raise TaskDenied("INVALID_ARTIFACT")
                if raw_parts:
                    artifact = (raw_parts[0].media_type, bytes(raw_parts[0].raw))
                    parts = [part for part in text_message.parts
                             if part.WhichOneof("content") != "raw"]
                    text_message.ClearField("parts")
                    text_message.parts.extend(parts)
                return self.ledger.executor_update(principal, message.task_id,
                                                   state=meta["state"],
                                                   idempotency_key=meta["idempotency_key"],
                                                   message=text_message if text_message.parts else None,
                                                   artifact=artifact)
            raise TaskDenied("INVALID_MESSAGE")
        except Denied as exc:
            self._convert(TaskDenied(exc.code))
        except TaskDenied as exc:
            self._convert(exc)

    async def on_get_task(self, params: GetTaskRequest, context) -> Task:
        try:
            self._tenant(params)
            if params.history_length < 0:
                raise TaskDenied("INVALID_REQUEST")
            self.rate.check("GetTask", params.id)
            task = self.ledger.get(CURRENT.get(), params.id)
            if params.history_length > 0:
                history = list(task.history)[-params.history_length:]
                task.ClearField("history")
                task.history.extend(history)
            return task
        except Denied as exc:
            self._convert(TaskDenied(exc.code))
        except TaskDenied as exc:
            self._convert(exc)

    async def on_list_tasks(self, params: ListTasksRequest, context) -> ListTasksResponse:
        try:
            self._tenant(params)
            self.rate.check("ListTasks", "all")
            if (params.context_id or params.status or params.page_size > 2 or
                    params.history_length < 0 or params.history_length > 2):
                raise TaskDenied("UNSUPPORTED_FILTER")
            tasks, cursor, total = self.ledger.list_page(CURRENT.get(),
                limit=params.page_size or 2, cursor=params.page_token)
            for task in tasks:
                history = list(task.history)[-params.history_length:] if params.history_length else []
                task.ClearField("history")
                task.history.extend(history)
            result = ListTasksResponse(page_size=len(tasks), total_size=total,
                                       next_page_token=cursor)
            result.tasks.extend(tasks)
            return result
        except Denied as exc:
            self._convert(TaskDenied(exc.code))
        except TaskDenied as exc:
            self._convert(exc)

    async def on_cancel_task(self, params: CancelTaskRequest, context) -> Task:
        try:
            self._tenant(params)
            self.rate.check("CancelTask", params.id)
            return self.ledger.cancel(CURRENT.get(), params.id)
        except Denied as exc:
            self._convert(TaskDenied(exc.code))
        except TaskDenied as exc:
            self._convert(exc)

    async def on_message_send_stream(self, params, context):
        raise UnsupportedOperationError(message="STREAMING_NOT_SUPPORTED")
        yield

    async def on_subscribe_to_task(self, params, context):
        raise UnsupportedOperationError(message="STREAMING_NOT_SUPPORTED")
        yield

    async def on_create_task_push_notification_config(self, params, context):
        raise UnsupportedOperationError(message="PUSH_NOT_SUPPORTED")

    async def on_get_task_push_notification_config(self, params, context):
        raise UnsupportedOperationError(message="PUSH_NOT_SUPPORTED")

    async def on_list_task_push_notification_configs(self, params, context):
        raise UnsupportedOperationError(message="PUSH_NOT_SUPPORTED")

    async def on_delete_task_push_notification_config(self, params, context):
        raise UnsupportedOperationError(message="PUSH_NOT_SUPPORTED")

    async def on_get_extended_agent_card(self, params, context):
        raise UnsupportedOperationError(message="EXTENDED_CARD_NOT_SUPPORTED")


class BodyLimit:
    def __init__(self, app, limit: int = 98304):
        self.app, self.limit = app, limit

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        size = 0
        async def bounded_receive():
            nonlocal size
            message = await receive()
            if message["type"] == "http.request":
                size += len(message.get("body", b""))
                if size > self.limit:
                    raise ValueError("BODY_TOO_LARGE")
            return message
        if any(k.lower() == b"content-length" and v.isdigit() and int(v) > self.limit
               for k, v in scope.get("headers", [])):
            body = b'{"error":"BODY_TOO_LARGE"}'
            await send({"type": "http.response.start", "status": 413,
                        "headers": [(b"content-type", b"application/json"),
                                    (b"content-length", str(len(body)).encode())]})
            await send({"type": "http.response.body", "body": body})
            return
        try:
            await self.app(scope, bounded_receive, send)
        except ValueError as exc:
            if str(exc) != "BODY_TOO_LARGE":
                raise
            body = b'{"error":"BODY_TOO_LARGE"}'
            await send({"type": "http.response.start", "status": 413,
                        "headers": [(b"content-type", b"application/json"),
                                    (b"content-length", str(len(body)).encode())]})
            await send({"type": "http.response.body", "body": body})


def create_app(ledger: TaskLedger, verifier: TokenVerifier, *,
               base_url: str = "http://127.0.0.1:8765"):
    """Local fixture server. No external listener or Devnet mode is provided."""
    from urllib.parse import urlsplit
    parsed = urlsplit(base_url)
    if parsed.scheme != "http" or parsed.hostname not in ("127.0.0.1", "localhost") or parsed.path:
        raise ValueError("LOOPBACK_ONLY")
    card = task_card(base_url)
    handler = TaskHandler(ledger, card)

    async def get_card(request):
        return JSONResponse(MessageToDict(card))

    routes = [Route("/a2a/task-card.json", get_card, methods=["GET"])]
    routes += create_jsonrpc_routes(handler, TASK_PATH)
    app = Starlette(routes=routes)
    host = parsed.netloc
    return AuthBoundary(BodyLimit(app), verifier, hosts=frozenset({host})), card


def main() -> None:
    import argparse
    import uvicorn
    parser = argparse.ArgumentParser(description="CON-41 offline A2A task server")
    parser.add_argument("--db", required=True)
    parser.add_argument("--fixture", type=Path, required=True)
    parser.add_argument("--issuer-public-key", type=Path, required=True)
    parser.add_argument("--issuer", required=True)
    parser.add_argument("--operations-db", type=Path)
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    if args.port < 1024 or args.port > 65535:
        parser.error("invalid port")
    operations = None
    if args.operations_db:
        from tools.operations.store import OperationalStore
        operations = OperationalStore(args.operations_db)
    ledger = TaskLedger(args.db, OfflineWorkOrders(args.fixture), operations)
    verifier = TokenVerifier(args.issuer_public_key.read_bytes(), issuer=args.issuer,
                             audience="conatus-a2a-tasks")
    app, _ = create_app(ledger, verifier, base_url=f"http://127.0.0.1:{args.port}")
    uvicorn.run(app, host="127.0.0.1", port=args.port)


if __name__ == "__main__":
    main()
