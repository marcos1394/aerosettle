"""Offline A2A task demo: official Python SDK requester and Node.js JSON-RPC executor."""
from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import os
from pathlib import Path
import socket
import tempfile
import time

from a2a.client import ClientConfig, ClientFactory
from a2a.types import AgentCard, CancelTaskRequest, GetTaskRequest, Message, Role, SendMessageRequest, TaskState
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from google.protobuf.json_format import ParseDict
import httpx
import uvicorn

from tools.a2a.task_server import create_app
from tools.a2a.task_store import OfflineWorkOrders, TaskLedger
from tools.mcp.security import TokenVerifier


FIXTURE = Path(__file__).parent / "fixtures/task-workorders.json"
NODE = Path(__file__).parent / "demo_task_node.cjs"
AUDIENCE = "conatus-a2a-tasks"


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _token(key: Ed25519PrivateKey, subject: str, scopes: list[str], *, tenant="tenant-a",
           organization="org-a") -> str:
    now = int(time.time())
    header = _b64(b'{"alg":"EdDSA","typ":"JWT"}')
    claims = {"iss": "con41-demo", "aud": AUDIENCE, "resource": AUDIENCE,
              "sub": subject, "client_id": "con41-demo-client", "tenant_id": tenant,
              "organization_id": organization, "scope": scopes, "iat": now,
              "exp": now + 300, "jti": "con41-demo-" + subject}
    payload = _b64(json.dumps(claims, sort_keys=True).encode())
    return header + "." + payload + "." + _b64(key.sign((header + "." + payload).encode()))


def _port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


async def _serve(ledger: TaskLedger, key: Ed25519PrivateKey):
    port = _port()
    base = f"http://127.0.0.1:{port}"
    app, card = create_app(ledger, TokenVerifier(key.public_key().public_bytes_raw(),
                            issuer="con41-demo", audience=AUDIENCE), base_url=base)
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port,
                                          log_level="critical", access_log=False))
    running = asyncio.create_task(server.serve())
    for _ in range(100):
        if server.started:
            return server, running, base, card
        await asyncio.sleep(.02)
    raise RuntimeError("A2A_SERVER_START_FAILED")


async def _node(base: str, token: str, task_id: str, context_id: str,
                state: str, idem: str) -> dict:
    env = {**os.environ, "CON41_TASK_URL": base + "/a2a/task-rpc",
           "CON41_TOKEN": token, "CON41_TASK_ID": task_id,
           "CON41_CONTEXT_ID": context_id, "CON41_STATE": state,
           "CON41_IDEMPOTENCY_KEY": idem}
    process = await asyncio.create_subprocess_exec("node", str(NODE), env=env,
                         stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
    stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=10)
    if process.returncode:
        raise RuntimeError("NODE_A2A_FAILED:" + stderr.decode()[:100])
    return json.loads(stdout)


async def run() -> dict:
    with tempfile.TemporaryDirectory(prefix="con41-demo-") as directory:
        db = Path(directory) / "tasks.sqlite"
        ledger = TaskLedger(db, OfflineWorkOrders(FIXTURE))
        key = Ed25519PrivateKey.generate()
        requester_token = _token(key, "fixture-owner-a",
                                 ["tasks:write", "tasks:read", "tasks:cancel"])
        executor_token = _token(key, "fixture-signer-a", ["tasks:execute", "tasks:read"])
        server, running, base, card = await _serve(ledger, key)
        try:
            async with httpx.AsyncClient(base_url=base,
                    headers={"Authorization": "Bearer " + requester_token}) as http:
                discovered = ParseDict((await http.get("/a2a/task-card.json")).json(),
                                       AgentCard(), ignore_unknown_fields=False)
                if discovered.supported_interfaces[0].protocol_binding != "JSONRPC" or \
                        discovered.skills[0].id != "conatus.task.coordinate":
                    raise AssertionError("TASK_INTERFACE_NEGOTIATION_FAILED")
                client = ClientFactory(ClientConfig(httpx_client=http, streaming=False)).create(discovered)
                message = Message(message_id="request-1", role=Role.ROLE_USER)
                message.parts.add(text="Produce a small JSON report")
                message.metadata.update({"conatus": {
                    "work_order_pda": "FixtureWorkOrderA", "idempotency_key": "create-1",
                    "expires_at": int(time.time()) + 240}})
                created = [event async for event in client.send_message(
                    SendMessageRequest(message=message))][0].task
                replay = [event async for event in client.send_message(
                    SendMessageRequest(message=message))][0].task
                if replay.id != created.id or created.status.state != TaskState.TASK_STATE_SUBMITTED:
                    raise AssertionError("CREATE_OR_IDEMPOTENCY_FAILED")
                task_id, context_id = created.id, created.context_id
            working = await _node(base, executor_token, task_id, context_id,
                                  "WORKING", "working-1")
            partial = await _node(base, executor_token, task_id, context_id,
                                  "INPUT_REQUIRED", "partial-1")
            if working["state"] != "TASK_STATE_WORKING" or partial["artifact_count"] != 1:
                raise AssertionError("HETEROGENEOUS_PROGRESS_FAILED")
        finally:
            server.should_exit = True
            await running
            ledger.close()

        # A fresh server process state uses the same SQLite database; the Node participant
        # is also a new process on every call.
        ledger = TaskLedger(db, OfflineWorkOrders(FIXTURE))
        server, running, base, card = await _serve(ledger, key)
        try:
            resumed = await _node(base, executor_token, task_id, context_id,
                                  "WORKING", "resume-1")
            completed = await _node(base, executor_token, task_id, context_id,
                                    "COMPLETED", "complete-1")
            async with httpx.AsyncClient(base_url=base,
                    headers={"Authorization": "Bearer " + requester_token}) as http:
                discovered = ParseDict((await http.get("/a2a/task-card.json")).json(),
                                       AgentCard(), ignore_unknown_fields=False)
                client = ClientFactory(ClientConfig(httpx_client=http, streaming=False)).create(discovered)
                final = await client.get_task(GetTaskRequest(id=task_id))
                no_scope = await http.post("/a2a/task-rpc", json={"jsonrpc": "2.0", "id": 2,
                    "method": "GetTask", "params": {"id": task_id}},
                    headers={"A2A-Version": "1.0", "Authorization": "Bearer " +
                        _token(key, "fixture-owner-a", ["tasks:write"])})
                cross_tenant = await http.post("/a2a/task-rpc", json={"jsonrpc": "2.0",
                    "id": 3, "method": "GetTask", "params": {"id": task_id}},
                    headers={"A2A-Version": "1.0", "Authorization": "Bearer " +
                        _token(key, "fixture-owner-a", ["tasks:read"], tenant="tenant-b")})
                if "error" not in no_scope.json() or "error" not in cross_tenant.json():
                    raise AssertionError("AUTHORIZATION_FAILED")
            if (resumed["state"] != "TASK_STATE_WORKING" or
                    completed["state"] != "TASK_STATE_COMPLETED" or
                    final.status.state != TaskState.TASK_STATE_COMPLETED or
                    final.metadata["conatus"]["work_order_status"] != "Open" or
                    not final.metadata["conatus"]["fixture_escrow_funded"] or
                    final.metadata["conatus"]["settlement_verified"]):
                raise AssertionError("TASK_WORKORDER_BOUNDARY_FAILED")
            artifact = final.artifacts[0]
            content_hash = hashlib.sha256(artifact.parts[0].raw).hexdigest()
            if content_hash != artifact.metadata["content_hash"]:
                raise AssertionError("ARTIFACT_HASH_FAILED")
            owner_b_token = _token(key, "fixture-owner-b",
                                   ["tasks:write", "tasks:read", "tasks:cancel"],
                                   tenant="tenant-b", organization="org-b")
            async with httpx.AsyncClient(base_url=base,
                    headers={"Authorization": "Bearer " + owner_b_token}) as http:
                client_b = ClientFactory(ClientConfig(httpx_client=http, streaming=False)).create(discovered)
                cancellation_message = Message(message_id="cancel-request", role=Role.ROLE_USER)
                cancellation_message.parts.add(text="Cancel this request before execution")
                cancellation_message.metadata.update({"conatus": {
                    "work_order_pda": "FixtureWorkOrderB", "idempotency_key": "cancel-create",
                    "expires_at": int(time.time()) + 240}})
                cancel_task = [event async for event in client_b.send_message(
                    SendMessageRequest(message=cancellation_message))][0].task
                canceled = await client_b.cancel_task(CancelTaskRequest(id=cancel_task.id))
                if canceled.status.state != TaskState.TASK_STATE_CANCELED:
                    raise AssertionError("CANCELLATION_FAILED")
            events = ledger.conn.execute("SELECT COUNT(*) FROM a2a_events WHERE task_id=?",
                                         (task_id,)).fetchone()[0]
            return {"A2A_TASK_E2E_VERIFIED": True, "DEVNET_WORKORDER_E2E_VERIFIED": False,
                    "OFFLINE_FIXTURE": True, "official_python_sdk_client": True,
                    "independent_node_jsonrpc_client": True, "task_id": task_id,
                    "task_status": "COMPLETED", "work_order_status": "Open",
                    "fixture_escrow_funded": True,
                    "settlement_verified": False, "artifact_sha256": content_hash,
                    "event_count": events, "sqlite_restart_verified": True,
                    "cancellation_verified": True,
                    "idempotency_verified": True, "cross_tenant_denied": True,
                    "no_scope_denied": True, "funds_transferred": False}
        finally:
            server.should_exit = True
            await running
            ledger.close()


if __name__ == "__main__":
    print(json.dumps(asyncio.run(run()), sort_keys=True))
