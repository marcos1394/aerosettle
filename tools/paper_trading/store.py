"""Separate immutable SQLite journal and owner-signed paper simulation orchestrator."""
from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import threading
import time
from pathlib import Path
from typing import Callable

from cryptography.hazmat.primitives.asymmetric import ed25519

from tools.discovery.agent_discovery import b58decode
from tools.economic_ledger.budget_policies import canonical, digest

from .providers import DeterministicFixtureProvider, LocalPaperExecutionAdapter
from .simulator import METHODOLOGY_VERSION, SHOCKS, PaperError, amount, compare_productive_alternatives

DOMAIN = "conatus:paper-simulation:v1"
REQUEST_FIELDS = frozenset({
    "agent_account", "agent_id", "owner_pubkey", "network", "genesis_hash", "program_id",
    "treasury_token_mint", "trading_quote_currency", "paper_budget_base_units_str",
    "funding_source", "scenario_id", "scenario_kind", "scenario", "instrument_id", "side",
    "quantity_base_units_str", "require_full_fill", "holding_period_days",
    "productive_alternatives", "simulation_timestamp", "nonce", "idempotency_key",
})


def paper_simulation_message(timestamp: int, agent_account: str, owner: str,
                             path: str, body: dict) -> bytes:
    if path != f"/v1/agents/{agent_account}/paper-simulations":
        raise PaperError(400, "INVALID_PATH", "Paper mutation path is fixed")
    budget_hash = hashlib.sha256(body["paper_budget_base_units_str"].encode("ascii")).hexdigest()
    return (f"{DOMAIN}:{timestamp}:{agent_account}:{body['agent_id']}:{owner}:POST:{path}:"
            f"{digest(body)}:{body['scenario_id']}:{budget_hash}:"
            f"{body['nonce']}:{body['idempotency_key']}").encode("utf-8")


def verify_paper_signature(agent: dict, path: str, body: dict, headers: dict,
                           *, now: int | None = None) -> str:
    at = int(time.time()) if now is None else now
    if not isinstance(body, dict) or set(body) != REQUEST_FIELDS:
        raise PaperError(400, "INVALID_REQUEST", "Exact paper simulation fields are required")
    owner = agent.get("owner")
    if (body["agent_account"], body["agent_id"], body["owner_pubkey"]) != (
            agent.get("agent_account"), agent.get("agent_id"), owner):
        raise PaperError(403, "IDENTITY_MISMATCH", "Current agent owner and identity are required")
    for key, minimum in (("nonce", 16), ("idempotency_key", 8), ("scenario_id", 1)):
        if not isinstance(body[key], str) or not re.fullmatch(rf"[A-Za-z0-9._:-]{{{minimum},128}}", body[key]):
            raise PaperError(400, "INVALID_REQUEST", f"Invalid {key}")
    if not body["scenario_id"].startswith("paper_"):
        raise PaperError(400, "INVALID_REQUEST", "Paper scenario identifiers must start with paper_")
    amount(body["paper_budget_base_units_str"], "paper budget", positive=True)
    if type(body["simulation_timestamp"]) is not int or abs(at - body["simulation_timestamp"]) > 300:
        raise PaperError(401, "EXPIRED_CREDENTIALS", "Paper signature timestamp is stale")
    hdr = {str(key).lower(): str(value) for key, value in headers.items()}
    if hdr.get("x-signer-pubkey") != owner or hdr.get("x-timestamp") != str(body["simulation_timestamp"]):
        raise PaperError(401, "INVALID_SIGNATURE", "Current owner paper signature is required")
    try:
        message = paper_simulation_message(body["simulation_timestamp"], body["agent_account"],
                                           owner, path, body)
        ed25519.Ed25519PublicKey.from_public_bytes(b58decode(owner, 32)).verify(
            b58decode(hdr["x-signature"], 64), message)
    except Exception as exc:
        raise PaperError(401, "INVALID_SIGNATURE", "Invalid owner Ed25519 paper signature") from exc
    return owner


class PaperSimulationStore:
    """This database has no references to EconomicLedger or financial tables."""

    def __init__(self, path: str | Path, provider=None):
        if str(path) != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(path), check_same_thread=False, isolation_level=None)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys=ON")
        self._lock = threading.RLock()
        self.provider = provider or DeterministicFixtureProvider()
        self.execution = LocalPaperExecutionAdapter()
        self.conn.executescript("""
            CREATE TABLE IF NOT EXISTS paper_simulation_runs (
                simulation_id TEXT PRIMARY KEY CHECK(substr(simulation_id,1,10)='paper_sim_'),
                agent_account TEXT NOT NULL, agent_id TEXT NOT NULL, owner_pubkey TEXT NOT NULL,
                network TEXT NOT NULL, genesis_hash TEXT NOT NULL, program_id TEXT NOT NULL,
                treasury_token_mint TEXT NOT NULL, trading_quote_currency TEXT NOT NULL,
                idempotency_key TEXT NOT NULL UNIQUE, nonce TEXT NOT NULL UNIQUE,
                request_hash TEXT NOT NULL, request_json TEXT NOT NULL,
                market_snapshot_hash TEXT NOT NULL, market_snapshot_json TEXT NOT NULL,
                result_hash TEXT NOT NULL, result_json TEXT NOT NULL,
                methodology_version TEXT NOT NULL, created_at INTEGER NOT NULL
            );
            CREATE INDEX IF NOT EXISTS paper_runs_scope ON paper_simulation_runs(agent_account,agent_id,owner_pubkey,created_at);
            CREATE TRIGGER IF NOT EXISTS immutable_paper_runs_update BEFORE UPDATE ON paper_simulation_runs
            BEGIN SELECT RAISE(ABORT,'paper history is immutable'); END;
            CREATE TRIGGER IF NOT EXISTS immutable_paper_runs_delete BEFORE DELETE ON paper_simulation_runs
            BEGIN SELECT RAISE(ABORT,'paper history is immutable'); END;
        """)

    def close(self) -> None:
        self.conn.close()

    def instruments(self, context: dict) -> list[dict]:
        return self.provider.get_instruments(context)

    @staticmethod
    def _identity(agent: dict, row: sqlite3.Row) -> None:
        if any(row[field] != agent.get(agent_field) for field, agent_field in
               (("agent_account", "agent_account"), ("agent_id", "agent_id"), ("owner_pubkey", "owner"))):
            raise PaperError(404, "SIMULATION_NOT_FOUND", "Paper simulation not found for current identity")

    def _read(self, agent: dict, row: sqlite3.Row) -> dict:
        self._identity(agent, row)
        try:
            result = json.loads(row["result_json"])
            request = json.loads(row["request_json"])
            market = json.loads(row["market_snapshot_json"])
            if (digest(result) != row["result_hash"] or digest(request) != row["request_hash"] or
                    digest(market) != row["market_snapshot_hash"] or
                    result["simulation_id"] != row["simulation_id"] or
                    result["is_paper"] is not True or result["is_executable"] is not False or
                    result["real_capital_authorized"] is not False):
                raise ValueError("Paper journal mismatch")
        except (KeyError, ValueError, TypeError) as exc:
            raise PaperError(409, "PAPER_INTEGRITY_CONFLICT", "Paper simulation history is inconsistent") from exc
        return result

    def get(self, agent: dict, simulation_id: str) -> dict:
        with self._lock:
            row = self.conn.execute("SELECT * FROM paper_simulation_runs WHERE simulation_id=?", (simulation_id,)).fetchone()
            if row is None:
                raise PaperError(404, "SIMULATION_NOT_FOUND", "Paper simulation not found")
            return self._read(agent, row)

    def list(self, agent: dict) -> list[dict]:
        with self._lock:
            rows = self.conn.execute(
                "SELECT * FROM paper_simulation_runs WHERE agent_account=? AND agent_id=? AND owner_pubkey=? "
                "ORDER BY created_at DESC,simulation_id DESC LIMIT 100",
                (agent["agent_account"], agent["agent_id"], agent["owner"])).fetchall()
            return [self._read(agent, row) for row in rows]

    def run(self, agent: dict, body: dict, actor: str,
            identity_supplier: Callable[[], dict | None] | None = None) -> tuple[dict, bool]:
        if actor != agent.get("owner") or body.get("owner_pubkey") != actor:
            raise PaperError(403, "FORBIDDEN", "Only current owner may run private paper simulations")
        if (body.get("funding_source") != "MANUAL_PAPER_ALLOCATION" or
                body.get("scenario") not in SHOCKS or body.get("scenario_kind") not in
                ("FINANCIAL_SPOT", "PRODUCTIVE_COMPARISON") or
                body.get("side") not in ("BUY", "SELL") or type(body.get("require_full_fill")) is not bool or
                not isinstance(body.get("scenario_id"), str) or
                not body["scenario_id"].startswith("paper_")):
            raise PaperError(400, "INVALID_REQUEST", "Unsupported paper scenario or funding source")
        amount(body.get("paper_budget_base_units_str"), "paper budget", positive=True)
        amount(body.get("quantity_base_units_str"), "paper quantity", positive=True)
        with self._lock:
            self.conn.execute("BEGIN IMMEDIATE")
            try:
                previous = self.conn.execute(
                    "SELECT * FROM paper_simulation_runs WHERE idempotency_key=? OR nonce=?",
                    (body["idempotency_key"], body["nonce"])).fetchone()
                if identity_supplier is not None:
                    live = identity_supplier()
                    if live is None or any(live.get(key) != agent.get(key)
                                           for key in ("agent_account", "agent_id", "owner")):
                        raise PaperError(403, "IDENTITY_CHANGED", "Agent owner or identity changed")
                if previous is not None:
                    self._identity(agent, previous)
                    if (previous["idempotency_key"] != body["idempotency_key"] or
                            previous["nonce"] != body["nonce"] or previous["request_hash"] != digest(body)):
                        raise PaperError(409, "IDEMPOTENCY_CONFLICT", "Paper request identifier was reused")
                    result = self._read(agent, previous)
                    self.conn.execute("COMMIT")
                    return result, False
                if body["trading_quote_currency"] != body["treasury_token_mint"]:
                    raise PaperError(422, "CURRENCY_CONVERSION_REQUIRED", "No automatic FX conversion is available")
                context = {**body, "simulation_timestamp": body["simulation_timestamp"]}
                alternatives = body["productive_alternatives"]
                if not isinstance(alternatives, list) or len(alternatives) > 8:
                    raise PaperError(400, "INVALID_PRODUCTIVE_SCENARIO", "At most eight alternatives are allowed")
                if any(item.get("currency_or_token_mint") != body["treasury_token_mint"]
                       for item in alternatives if isinstance(item, dict)):
                    raise PaperError(422, "MIXED_CURRENCY", "Productive alternatives need exact paper currency")
                productive = compare_productive_alternatives(
                    body["paper_budget_base_units_str"], body["holding_period_days"], alternatives)
                market = {}
                costs = {}
                if body["scenario_kind"] == "FINANCIAL_SPOT":
                    try:
                        quote = self.provider.get_quote(body["instrument_id"], context)
                        liquidity = self.provider.get_liquidity_snapshot(body["instrument_id"], context)
                        costs = self.provider.get_fee_schedule(body["instrument_id"], context)
                    except ValueError as exc:
                        raise PaperError(422, "UNKNOWN_PAPER_INSTRUMENT", "Unknown offline paper instrument") from exc
                    market = {**quote, **liquidity, "provider_id": self.provider.provider_id,
                              "provider_mode": self.provider.provider_mode}
                    policy = {"max_paper_allocation_base_units_str": "18446744073709551615",
                              "max_position_allocation_bps": 10000, "max_single_trade_bps": 10000,
                              "max_daily_paper_turnover_bps": 10000, "max_simulated_loss_budget_bps": 10000,
                              "allowed_instruments": [item["instrument_id"] for item in self.provider.get_instruments(context)],
                              "allowed_quote_currencies": [body["treasury_token_mint"]],
                              "max_quote_age_seconds": 300}
                    fill = self.execution.simulate_fill(body, market, costs, policy,
                        {"cash_base_units_str": body["paper_budget_base_units_str"],
                         "position_quantity_base_units_str": "0", "daily_turnover_base_units_str": "0"})
                elif body["scenario_kind"] == "PRODUCTIVE_COMPARISON":
                    fill = {"status": "SIMULATED", "fill_status": None, "reason_codes": [],
                            "remaining_paper_budget_base_units_str": body["paper_budget_base_units_str"],
                            "is_paper": True, "is_executable": False, "real_capital_authorized": False}
                else:
                    raise PaperError(400, "INVALID_SCENARIO", "Unknown paper scenario kind")
                result = {**fill, "simulation_id": "paper_sim_" + digest([body["agent_account"],
                    body["idempotency_key"], digest(body)])[:32], "scenario_id": body["scenario_id"],
                    "agent_account": body["agent_account"], "agent_id": body["agent_id"],
                    "owner_pubkey": actor, "network": body["network"],
                    "genesis_hash": body["genesis_hash"], "program_id": body["program_id"],
                    "treasury_token_mint": body["treasury_token_mint"],
                    "trading_quote_currency": body["trading_quote_currency"],
                    "paper_budget_base_units_str": body["paper_budget_base_units_str"],
                    "funding_source": body["funding_source"],
                    "scenario": body["scenario"], "scenario_kind": body["scenario_kind"],
                    "productive_alternatives": productive,
                    "market_snapshot": market, "execution_cost_snapshot": costs,
                    "input_snapshot_hash": digest(body), "market_snapshot_hash": digest(market),
                    "provider_id": self.provider.provider_id, "provider_mode": self.provider.provider_mode,
                    "data_provenance": self.provider.data_provenance if market else "USER_SUPPLIED_ASSUMPTION",
                    "simulation_timestamp": body["simulation_timestamp"],
                    "methodology_version": METHODOLOGY_VERSION,
                    "is_paper": True, "is_executable": False, "real_capital_authorized": False}
                result["result_hash"] = digest(result)
                self.conn.execute("INSERT INTO paper_simulation_runs VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (result["simulation_id"], body["agent_account"], body["agent_id"], actor,
                     body["network"], body["genesis_hash"], body["program_id"],
                     body["treasury_token_mint"], body["trading_quote_currency"],
                     body["idempotency_key"], body["nonce"], digest(body),
                     canonical(body).decode("utf-8"), digest(market), canonical(market).decode("utf-8"),
                     digest(result), canonical(result).decode("utf-8"), METHODOLOGY_VERSION,
                     body["simulation_timestamp"]))
                self.conn.execute("COMMIT")
                return result, True
            except Exception:
                self.conn.execute("ROLLBACK")
                raise
