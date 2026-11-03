"""Persistent provider circuit breaker and bounded Devnet RPC instrumentation."""
from __future__ import annotations

import threading
import time

from tools.economic_ledger.devnet_ingestion import GENESIS, NETWORK, RPC_URL
from tools.economic_ledger.spl_reconciler import RpcError, SolanaRpcClient
from .store import OperationalStore


class CircuitOpen(RpcError):
    pass


class RequestLimit(RpcError):
    pass


class ProviderController:
    def __init__(self, store: OperationalStore, *, provider_id: str = "official-devnet",
                 max_requests_per_minute: int = 120, max_concurrency: int = 2,
                 failure_threshold: int = 3, cooldown_seconds: int = 30,
                 clock=None) -> None:
        if (max_requests_per_minute < 1 or max_concurrency < 1 or
                failure_threshold < 1 or cooldown_seconds < 1):
            raise ValueError("Invalid RPC control limits")
        self.store = store
        self.provider_id = provider_id
        self.max_requests_per_minute = max_requests_per_minute
        self.failure_threshold = failure_threshold
        self.cooldown_seconds = cooldown_seconds
        self.clock = clock or (lambda: int(time.time()))
        self.semaphore = threading.BoundedSemaphore(max_concurrency)
        self.store.provider(provider_id, NETWORK, GENESIS)

    def before_call(self) -> None:
        if not self.semaphore.acquire(blocking=False):
            self.store.sample("rpc_concurrency_rejected", 1, "calls", self.provider_id)
            raise RequestLimit("RPC concurrency limit reached")
        try:
            now = self.clock()
            with self.store.transaction() as db:
                row = db.execute("SELECT * FROM provider_health WHERE provider_id=?",
                                 (self.provider_id,)).fetchone()
                state = row["state"]
                if state == "OPEN":
                    if now < row["opened_until"]:
                        raise CircuitOpen("RPC circuit open")
                    state = "HALF_OPEN"
                if state == "HALF_OPEN" and row["half_open_lease_until"] > now:
                    raise CircuitOpen("RPC half-open probe already in progress")
                window = row["window_started_at"]
                count = row["requests_in_window"]
                if now - window >= 60:
                    window, count = now, 0
                if count >= self.max_requests_per_minute:
                    raise RequestLimit("RPC request budget exhausted")
                db.execute("""UPDATE provider_health SET state=?,half_open_lease_until=?,
                    window_started_at=?,requests_in_window=?,updated_at=? WHERE provider_id=?""",
                    (state, now + self.cooldown_seconds if state == "HALF_OPEN" else 0,
                     window, count + 1, now, self.provider_id))
        except (CircuitOpen, RequestLimit) as exc:
            self.semaphore.release()
            self.store.sample("rpc_circuit_rejected" if isinstance(exc, CircuitOpen)
                              else "rpc_rate_rejected", 1, "calls", self.provider_id)
            raise
        except Exception:
            self.semaphore.release()
            raise

    def after_call(self, success: bool, error_code: str | None) -> None:
        try:
            now = self.clock()
            with self.store.transaction() as db:
                row = db.execute("SELECT state,consecutive_failures FROM provider_health WHERE provider_id=?",
                                 (self.provider_id,)).fetchone()
                if success:
                    db.execute("""UPDATE provider_health SET state='CLOSED',
                        consecutive_failures=0,opened_until=0,half_open_lease_until=0,
                        last_success_at=?,last_error_code=NULL,updated_at=?
                        WHERE provider_id=?""", (now, now, self.provider_id))
                else:
                    failures = row["consecutive_failures"] + 1
                    opening = row["state"] == "HALF_OPEN" or failures >= self.failure_threshold
                    db.execute("""UPDATE provider_health SET state=?,
                        consecutive_failures=?,opened_until=?,half_open_lease_until=0,
                        last_error_code=?,updated_at=? WHERE provider_id=?""",
                        ("OPEN" if opening else "CLOSED", failures,
                         now + self.cooldown_seconds if opening else 0,
                         error_code or "RPC_ERROR", now, self.provider_id))
        finally:
            self.semaphore.release()

    def state(self) -> dict:
        return self.store.provider(self.provider_id, NETWORK, GENESIS)


class RpcObserver:
    def __init__(self, store: OperationalStore, provider_id: str = "official-devnet") -> None:
        self.store = store
        self.provider_id = provider_id

    def __call__(self, method: str, elapsed_ms: float, success: bool,
                 error_code: str | None, counters: dict[str, int]) -> None:
        # Method names are an allowlisted RPC vocabulary; never persist params or URLs.
        if method not in {"getGenesisHash", "getAccountInfo", "getBalance", "getSlot",
                          "getSignaturesForAddress", "getSignatureStatuses",
                          "getTransaction", "getBlock", "getTokenAccountBalance"}:
            method = "other_rpc"
        for metric, value, unit in (
            ("rpc_duration_ms", elapsed_ms, "ms"),
            ("rpc_requests_total", 1, "calls"),
            ("rpc_http_429_count", counters["http_429"], "attempts"),
            ("rpc_http_5xx_count", counters["http_5xx"], "attempts"),
            ("rpc_timeout_count", counters["timeouts"], "attempts"),
            ("rpc_retry_count", counters["retries"], "attempts"),
            ("rpc_failure_count", 0 if success else 1, "calls"),
        ):
            self.store.sample(metric, value, unit, self.provider_id,
                              correlation_id=method)


def monitored_client(store: OperationalStore, controller: ProviderController,
                     *, timeout: float = 20, retry_budget: int = 2,
                     min_interval: float = 0.3) -> SolanaRpcClient:
    if not 0 <= retry_budget <= 5 or timeout <= 0 or min_interval < 0:
        raise ValueError("Invalid bounded RPC retry or timeout configuration")
    return SolanaRpcClient(RPC_URL, timeout=timeout, min_interval=min_interval,
        max_attempts=retry_budget + 1, request_gate=controller,
        request_observer=RpcObserver(store, controller.provider_id))
