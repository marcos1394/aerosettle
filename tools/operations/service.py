"""Devnet health, readiness, metric collection, and rule evaluation."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sqlite3
import time
from typing import Any

from tools.deployment import devnet, test_mint
from tools.economic_ledger.devnet_ingestion import (
    GENESIS, MINT, NETWORK, PROGRAM, ROOT, RPC_URL, _DeploymentRpcAdapter,
)
from tools.economic_ledger.spl_reconciler import (
    DEFAULT_PROTOCOL_CONFIG, DEFAULT_TOKEN_PROGRAM, SolanaRpcClient,
    b58encode, extract_account_bytes,
)
from .store import OperationalStore, digest
from .structured_logs import correlation_id

CONFIG = ROOT / "tools/operations/devnet.json"


def load_config(path: Path = CONFIG) -> dict:
    value = json.loads(path.read_text())
    if (value.get("network") != NETWORK or value.get("genesis_hash") != GENESIS or
            value.get("program_id") != PROGRAM or value.get("mint") != MINT or
            value.get("rpc_url") != RPC_URL or
            value.get("provider_id") != "official-devnet"):
        raise ValueError("Observability configuration has incompatible Devnet identity")
    for key in ("low_balance_lamports", "checkpoint_stall_seconds",
                "sample_retention_seconds"):
        if type(value.get(key)) is not int or value[key] <= 0:
            raise ValueError(f"Invalid {key} configuration")
    rpc = value.get("rpc")
    if not isinstance(rpc, dict) or any(type(rpc.get(key)) is not int or rpc[key] <= 0
        for key in ("max_requests_per_minute", "max_concurrency", "failure_threshold",
                    "cooldown_seconds", "timeout_seconds")) or \
            type(rpc.get("retry_budget")) is not int or not 0 <= rpc["retry_budget"] <= 5 or \
            type(rpc.get("min_interval_seconds")) not in (int, float) or \
            rpc["min_interval_seconds"] < 0:
        raise ValueError("Invalid bounded RPC configuration")
    if not isinstance(value.get("rules"), list):
        raise ValueError("Missing alert rules")
    if not isinstance(value.get("active_scope_ids"), list) or any(
            not isinstance(item, str) or len(item) != 64 or
            any(char not in "0123456789abcdef" for char in item)
            for item in value["active_scope_ids"]):
        raise ValueError("Invalid active ingestion scopes")
    return value


def install_rules(store: OperationalStore, config: dict) -> None:
    for rule in config["rules"]:
        store.put_rule(rule)


def percentile(values: list[float], fraction: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = max(0, (len(ordered) * fraction).__ceil__() - 1)
    return ordered[index]


def _record(store: OperationalStore, name: str, value: int | float | None,
            unit: str, scope: str, quality: str = "OBSERVED") -> dict:
    store.sample(name, value, unit, scope, quality=quality)
    return {"value": value, "unit": unit, "quality": quality}


def inspect_security(rpc: SolanaRpcClient, store: OperationalStore,
                     config: dict) -> dict[str, dict]:
    """Read-only RPC checks. Every mismatch is named; no transaction body is logged."""
    if type(rpc) is not SolanaRpcClient or rpc.rpc_url != RPC_URL:
        raise ValueError("Only the approved official Devnet RPC is allowed")
    result: dict[str, dict] = {}

    def check(name: str, action) -> Any:
        try:
            value = action()
            result[name] = {"status": "MATCH", "quality": "OBSERVED"}
            _record(store, name + "_mismatch", 0, "boolean", "devnet")
            return value
        except Exception as exc:
            mismatch = isinstance(exc, devnet.DeploymentError)
            authority_only = (name == "program" and mismatch and
                              "Unrecognized upgrade authority" in str(exc))
            result[name] = {"status": "INSUFFICIENT_DATA" if authority_only else
                            "MISMATCH" if mismatch else
                            "MISMATCH_OR_UNAVAILABLE",
                            "quality": "INSUFFICIENT_DATA" if authority_only else
                                       "OBSERVED" if mismatch else "INSUFFICIENT_DATA"}
            _record(store, name + "_mismatch", None if authority_only else
                    1 if mismatch else None,
                    "boolean", "devnet",
                    "INSUFFICIENT_DATA" if authority_only else
                    "OBSERVED" if mismatch else "INSUFFICIENT_DATA")
            if authority_only:
                result["upgrade_authority"] = {"status": "MISMATCH",
                                               "quality": "OBSERVED"}
                _record(store, "upgrade_authority_mismatch", 1,
                        "boolean", "devnet")
            return None

    genesis = check("genesis", lambda: rpc.get_genesis_hash())
    if genesis is not None and genesis != GENESIS:
        result["genesis"] = {"status": "MISMATCH", "quality": "OBSERVED"}
        _record(store, "genesis_mismatch", 1, "boolean", "devnet")
    if genesis != GENESIS:
        for name in ("program", "programdata", "upgrade_authority", "mint",
                     "protocol_config", "test_wallet"):
            result[name] = {"status": "INSUFFICIENT_DATA",
                            "quality": "INSUFFICIENT_DATA"}
            _record(store, name + "_mismatch", None, "boolean", "devnet",
                    "INSUFFICIENT_DATA")
        return result
    deployment_config = devnet.load_json(ROOT / "tools/deployment/devnet.json")
    adapter = _DeploymentRpcAdapter(rpc)
    program = check("program", lambda: devnet.inspect_program(deployment_config, adapter))
    if program is not None and not program.get("exists"):
        result["program"] = {"status": "MISMATCH", "quality": "OBSERVED"}
        _record(store, "program_mismatch", 1, "boolean", "devnet")
        program = None
    if program is not None:
        binary = (ROOT / "evidence/con35/artifacts/aerosettle.so").read_bytes()
        matched = check("programdata", lambda: devnet.binary_matches_deployed(
            adapter, program["program_data_address"], binary))
        if matched is False:
            result["programdata"] = {"status": "MISMATCH", "quality": "OBSERVED"}
            _record(store, "programdata_mismatch", 1, "boolean", "devnet")
    else:
        # inspect_program includes canonical ProgramData and upgrade-authority checks.
        if "upgrade_authority" not in result:
            result["upgrade_authority"] = {"status": "MISMATCH_OR_UNAVAILABLE",
                                           "quality": "INSUFFICIENT_DATA"}
            _record(store, "upgrade_authority_mismatch", None, "boolean", "devnet",
                    "INSUFFICIENT_DATA")
    if program is not None:
        authority_bad = program["upgrade_authority_pubkey"] != deployment_config["upgrade_authority_pubkey"]
        result["upgrade_authority"] = {"status": "MISMATCH" if authority_bad else "MATCH",
                                       "quality": "OBSERVED"}
        _record(store, "upgrade_authority_mismatch", int(authority_bad),
                "boolean", "devnet")

    mint_plan = devnet.load_json(ROOT / "evidence/con35/test-mint.json")
    mint_evidence = devnet.load_json(ROOT / "evidence/con35/test-mint-verified.json")
    verified = check("mint", lambda: test_mint.verify(
        mint_plan, adapter, mint_evidence["creation_signature"]))
    if verified is not None:
        bad = (verified != mint_evidence or verified["mint_pubkey"] != MINT or
               verified["token_program"] != DEFAULT_TOKEN_PROGRAM or
               verified["decimals"] != 6)
        if bad:
            result["mint"] = {"status": "MISMATCH", "quality": "OBSERVED"}
            _record(store, "mint_mismatch", 1, "boolean", "devnet")

    def protocol() -> bool:
        value = rpc.get_account_info(DEFAULT_PROTOCOL_CONFIG, commitment="finalized")
        if not value or value.get("owner") != PROGRAM:
            return False
        raw = extract_account_bytes(value)
        evidence = json.loads((ROOT / "evidence/con36/protocol-config-verified.json").read_text())
        return (len(raw) == 155 and
                raw[:8] == hashlib.sha256(b"account:ProtocolConfig").digest()[:8] and
                raw[8] == 1 and b58encode(raw[9:41]) == deployment_config["protocol_admin_pubkey"] and
                raw[41:73].hex() == evidence["network_id_hex"] and
                b58encode(raw[73:105]) == PROGRAM and
                raw[105:137].hex() == evidence["protocol_deployment_id_hex"] and
                raw[137] == 255 and raw[146] == 0)
    protocol_ok = check("protocol_config", protocol)
    if protocol_ok is False:
        result["protocol_config"] = {"status": "MISMATCH", "quality": "OBSERVED"}
        _record(store, "protocol_config_mismatch", 1, "boolean", "devnet")

    def balance() -> int:
        result = rpc._call("getBalance", [deployment_config["fee_payer_pubkey"],
                                           {"commitment": "finalized"}])
        amount = result.get("value") if isinstance(result, dict) else None
        if type(amount) is not int or amount < 0:
            raise ValueError("Invalid test wallet balance response")
        return amount
    lamports = check("test_wallet", balance)
    if lamports is not None:
        result["test_wallet"]["balance_lamports"] = lamports
        _record(store, "test_wallet_balance_lamports", lamports, "lamports", "devnet")
        result["test_wallet"]["status"] = (
            "LOW_BALANCE" if lamports < config["low_balance_lamports"] else "MATCH")
    return result


def collect_ledger(store: OperationalStore, path: Path, *, now: int | None = None,
                   config: dict | None = None) -> dict:
    """Read the CON-37 ledger with SQLite mode=ro; never mutate economic rows."""
    timestamp = int(time.time()) if now is None else now
    config = config or load_config()
    if not path.is_file():
        _record(store, "ledger_available", 0, "boolean", "devnet")
        return {"status": "INSUFFICIENT_DATA", "reason": "Ledger database absent"}
    try:
        db = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)
        db.row_factory = sqlite3.Row
        try:
            if db.execute("PRAGMA quick_check").fetchone()[0] != "ok" or \
                    not db.execute("SELECT 1 FROM schema_migrations WHERE version=12").fetchone():
                raise ValueError("Ledger schema or integrity mismatch")
            checkpoints = [dict(row) for row in db.execute(
                "SELECT * FROM ingestion_checkpoints ORDER BY scope_id")]
            counts = dict(db.execute("""SELECT processing_status,count(*) FROM ingestion_observations
                GROUP BY processing_status""").fetchall())
            movements = db.execute("""SELECT count(*) FROM economic_movements
                WHERE status='RECONCILED' AND network=? AND genesis_hash=?""",
                (NETWORK, GENESIS)).fetchone()[0]
            effects = db.execute("SELECT count(*) FROM ingestion_effects WHERE network=? AND genesis_hash=?",
                                 (NETWORK, GENESIS)).fetchone()[0]
            incidents = db.execute("SELECT count(*) FROM ingestion_incidents").fetchone()[0]
            differences = db.execute("""SELECT count(*) FROM ingestion_incidents
                WHERE error_category='ECONOMIC_DIFFERENCE'""").fetchone()[0]
            gaps = db.execute("""SELECT count(*) FROM ingestion_incidents
                WHERE error_category IN ('GAP','IngestionGap','UnavailableHistory','RPC_ERROR')""").fetchone()[0]
            anchor_rows = db.execute("""SELECT error_category,count(*) FROM ingestion_observations
                WHERE error_category LIKE 'ANCHOR_%' GROUP BY error_category""").fetchall()
            failed_transactions = db.execute("""SELECT count(*) FROM ingestion_observations
                WHERE processing_status='UNVERIFIABLE' AND
                (error_category='TRANSACTION_FAILED' OR error_category LIKE 'ANCHOR_%')""").fetchone()[0]
            source_incidents = [dict(row) for row in db.execute("""SELECT
                c.ingestion_scope,i.signature,i.slot,i.error_category,i.observed_at
                FROM ingestion_incidents i JOIN ingestion_checkpoints c ON c.scope_id=i.scope_id
                ORDER BY i.incident_id""")]
            lags = [row[0] for row in db.execute("""SELECT finalization_lag_seconds
                FROM ingestion_observations WHERE finalization_lag_seconds IS NOT NULL""")]
            replay_estimate = db.execute("""SELECT coalesce(sum(max(attempt_count-2,0)),0)
                FROM ingestion_observations WHERE processing_status='RECONCILED'""").fetchone()[0]
            duplicate_effects = db.execute("""SELECT count(*) FROM (
                SELECT network,genesis_hash,transaction_signature,instruction_index,
                       effect_kind,destination_account,token_mint
                FROM ingestion_effects GROUP BY network,genesis_hash,transaction_signature,
                    instruction_index,effect_kind,destination_account,token_mint
                HAVING count(*)>1)""").fetchone()[0]
            oldest_backlog = db.execute("""SELECT min(updated_at) FROM ingestion_observations
                WHERE processing_status IN ('DISCOVERED','PENDING_FINALITY',
                    'INSUFFICIENT_DATA')""").fetchone()[0]
        finally:
            db.close()
    except (sqlite3.Error, ValueError):
        _record(store, "ledger_available", 0, "boolean", "devnet")
        return {"status": "INSUFFICIENT_DATA", "reason": "Ledger SQLite unavailable or invalid"}
    _record(store, "ledger_available", 1, "boolean", "devnet")
    metrics = {
        "signatures_discovered": _record(store, "signatures_discovered",
            sum(counts.values()), "transactions", "devnet"),
        "transactions_finalized": _record(store, "transactions_finalized",
            counts.get("FINALIZED", 0) + counts.get("RECONCILED", 0) +
            failed_transactions, "transactions", "devnet"),
        "transactions_failed": _record(store, "transactions_failed",
            failed_transactions, "transactions", "devnet"),
        "transactions_pending_finality": _record(store, "transactions_pending_finality",
            counts.get("PENDING_FINALITY", 0), "transactions", "devnet"),
        "movements_reconciled": _record(store, "movements_reconciled", movements,
            "movements", "devnet"),
        "economic_effects": _record(store, "economic_effects", effects,
            "effects", "devnet"),
        "ingestion_incidents": _record(store, "ingestion_incidents", incidents,
            "incidents", "devnet"),
        "economic_difference_count": _record(store, "economic_difference_count",
            differences, "incidents", "devnet"),
        "rpc_gap_count": _record(store, "rpc_gap_count", gaps, "incidents", "devnet"),
        "known_backlog_count": _record(store, "known_backlog_count",
            sum(counts.get(key, 0) for key in
                ("DISCOVERED", "PENDING_FINALITY", "INSUFFICIENT_DATA")),
            "transactions", "devnet"),
        "known_backlog_age_seconds": _record(store, "known_backlog_age_seconds",
            max(0, timestamp - oldest_backlog) if oldest_backlog is not None else 0,
            "seconds", "devnet"),
        "replay_attempts_estimate": _record(store, "replay_attempts_estimate",
            replay_estimate, "attempts", "devnet", "ESTIMATED"),
        "duplicate_attempts_estimate": _record(store, "duplicate_attempts_estimate",
            replay_estimate, "attempts", "devnet", "ESTIMATED"),
        "duplicate_effect_count": _record(store, "duplicate_effect_count",
            duplicate_effects, "effects", "devnet"),
        "reconciliation_error_count": _record(store, "reconciliation_error_count",
            differences, "incidents", "devnet"),
        "historical_recovery_seconds": _record(store, "historical_recovery_seconds",
            None, "seconds", "devnet", "INSUFFICIENT_DATA"),
        "block_to_ingest_p95_seconds": _record(store, "block_to_ingest_p95_seconds",
            percentile(lags, .95), "seconds", "devnet",
            "ESTIMATED" if lags else "INSUFFICIENT_DATA"),
    }
    active = [row for row in checkpoints if row["scope_id"] in
              config["active_scope_ids"]]
    last = max((row["last_successful_sync"] or 0 for row in checkpoints), default=0)
    complete_active = bool(config["active_scope_ids"]) and \
        len(active) == len(config["active_scope_ids"])
    stall = int(any(not row["last_successful_sync"] or timestamp -
                    row["last_successful_sync"] > config["checkpoint_stall_seconds"]
                    for row in active)) if complete_active else None
    metrics["checkpoint_stalled_count"] = _record(store, "checkpoint_stalled_count",
        stall, "checkpoints", "devnet",
        "OBSERVED" if stall is not None else "INSUFFICIENT_DATA")
    metrics["last_checkpoint_success_epoch"] = _record(store,
        "last_checkpoint_success_epoch", last if last else None, "epoch_seconds",
        "devnet", "OBSERVED" if last else "INSUFFICIENT_DATA")
    for code, count in anchor_rows:
        metrics[code] = _record(store, code.lower(), count, "transactions", "devnet")
    return {"status": "OBSERVED", "metrics": metrics,
            "checkpoint_count": len(checkpoints),
            "source_incidents": [{**row, "correlation_id": correlation_id(
                row["ingestion_scope"], row["signature"])} for row in source_incidents],
            "checkpoint_statuses": {row["scope_id"]: row["checkpoint_status"]
                                    for row in checkpoints}}


def collect_rpc(store: OperationalStore, provider_id: str = "official-devnet",
                *, window_seconds: int = 3600, now: int | None = None) -> dict:
    timestamp = int(time.time()) if now is None else now
    since = timestamp - window_seconds
    names = ("rpc_duration_ms", "rpc_requests_total", "rpc_http_429_count",
             "rpc_http_5xx_count", "rpc_timeout_count", "rpc_retry_count",
             "rpc_failure_count", "rpc_circuit_rejected", "rpc_rate_rejected")
    rows = {name: store.latest(name, provider_id, since) for name in names}
    durations = [row["value"] for row in rows["rpc_duration_ms"] if row["quality"] == "OBSERVED"]
    count = len(rows["rpc_requests_total"])
    return {"window_seconds": window_seconds, "sample_count": count,
            "quality": "OBSERVED" if count else "INSUFFICIENT_DATA",
            "latency_ms": {f"p{p}": percentile(durations, p / 100)
                           for p in (50, 95, 99)},
            "requests_total": count,
            "http_429": sum(row["value"] for row in rows["rpc_http_429_count"]),
            "http_5xx": sum(row["value"] for row in rows["rpc_http_5xx_count"]),
            "timeouts": sum(row["value"] for row in rows["rpc_timeout_count"]),
            "retries": sum(row["value"] for row in rows["rpc_retry_count"]),
            "failures": sum(row["value"] for row in rows["rpc_failure_count"]),
            "circuit_rejected": sum(row["value"] for row in rows["rpc_circuit_rejected"]),
            "rate_rejected": sum(row["value"] for row in rows["rpc_rate_rejected"]),
            "availability_fraction": 1 - sum(row["value"] for row in
                rows["rpc_failure_count"]) / count if count else None}


def publish_rpc_summary(store: OperationalStore, *, window_seconds: int = 300) -> dict:
    summary = collect_rpc(store, window_seconds=window_seconds)
    quality = "OBSERVED" if summary["sample_count"] >= 5 else "INSUFFICIENT_DATA"
    _record(store, "rpc_error_fraction",
            1 - summary["availability_fraction"] if quality == "OBSERVED" else None,
            "fraction", "official-devnet", quality)
    _record(store, "rpc_p95_ms",
            summary["latency_ms"]["p95"] if quality == "OBSERVED" else None,
            "ms", "official-devnet", quality)
    _record(store, "rpc_429_window_count",
            summary["http_429"] if quality == "OBSERVED" else None,
            "attempts", "official-devnet", quality)
    return summary


def evaluate_alerts(store: OperationalStore, *, scopes: tuple[str, ...] =
                    ("devnet", "official-devnet"), now: int | None = None) -> list[dict]:
    timestamp = int(time.time()) if now is None else now
    outcomes = []
    for rule in store.rules():
        for scope in scopes:
            all_rows = store.latest(rule["metric"], scope,
                                    timestamp - rule["window_seconds"])
            rows = [row for row in all_rows if row["quality"] == "OBSERVED"]
            if (not all_rows or all_rows[-1]["quality"] != "OBSERVED" or
                    len(rows) < rule["min_samples"]):
                outcomes.append({"rule_id": rule["rule_id"], "scope": scope,
                                 "status": "INSUFFICIENT_DATA"})
                continue
            value = rows[-1]["value"]
            threshold = rule["threshold"]
            triggered = {"GT": value > threshold, "GTE": value >= threshold,
                         "LT": value < threshold, "LTE": value <= threshold}[rule["comparison"]]
            evidence = digest([rule["rule_id"], scope, rows[-1]["sample_id"], value])
            store.transition_alert(rule, scope, value, evidence, triggered, now=timestamp)
            outcomes.append({"rule_id": rule["rule_id"], "scope": scope,
                             "status": "TRIGGERED" if triggered else "CLEAR",
                             "value": value})
    return outcomes


def health() -> dict:
    return {"status": "HEALTHY", "component": "devnet-operations",
            "checks": {"process": "RESPONSIVE"}}


def readiness(store: OperationalStore, rpc: SolanaRpcClient, config: dict,
              ledger_path: Path) -> dict:
    checks: dict[str, str] = {}
    try:
        store.validate_schema()
        if store.db.execute("PRAGMA quick_check").fetchone()[0] != "ok":
            raise ValueError("SQLite integrity check failed")
        checks["operational_sqlite"] = "MATCH"
    except Exception:
        checks["operational_sqlite"] = "FAILED"
    identity = inspect_security(rpc, store, config)
    provider = store.provider("official-devnet", NETWORK, GENESIS)
    checks["circuit_breaker"] = provider["state"]
    checks.update({name: item["status"] for name, item in identity.items()})
    ledger = collect_ledger(store, ledger_path, config=config)
    checks["economic_ledger"] = "MATCH" if ledger["status"] == "OBSERVED" else "FAILED"
    if ledger["status"] == "OBSERVED":
        checks["checkpoints"] = ("MATCH" if ledger["checkpoint_count"] and all(
            state == "READY" for state in ledger["checkpoint_statuses"].values())
            else "MISSING_OR_GAP")
    critical = ("genesis", "program", "programdata", "upgrade_authority",
                "mint", "protocol_config", "economic_ledger", "checkpoints")
    if checks["operational_sqlite"] != "MATCH":
        status = "UNHEALTHY"
    elif provider["state"] != "CLOSED" or any(checks.get(key) != "MATCH" for key in critical):
        status = "NOT_READY"
    elif checks["test_wallet"] != "MATCH":
        status = "DEGRADED"
    else:
        status = "HEALTHY"
    _record(store, "readiness_success", 1 if status in ("HEALTHY", "DEGRADED")
            else 0, "boolean", "devnet")
    return {"status": status, "checks": checks,
            "network": NETWORK, "genesis_hash": GENESIS, "program_id": PROGRAM}


def operational_report(store: OperationalStore, ledger_path: Path,
                       *, window_seconds: int = 3600) -> dict:
    rpc = collect_rpc(store, window_seconds=window_seconds)
    readiness_rows = [row for row in store.latest("readiness_success", "devnet",
        int(time.time()) - window_seconds) if row["quality"] == "OBSERVED"]
    readiness_fraction = (sum(row["value"] for row in readiness_rows) /
                          len(readiness_rows)) if len(readiness_rows) >= 20 else None
    rpc_p95 = rpc["latency_ms"]["p95"] if rpc["sample_count"] >= 20 else None
    open_alerts = [row for row in store.alerts() if row["state"] != "RESOLVED"]
    return {"health": health(), "provider": store.provider("official-devnet", NETWORK, GENESIS),
            "rpc": rpc,
            "ledger": collect_ledger(store, ledger_path),
            "open_operational_incident_count": len(open_alerts),
            "alerts": store.alerts(), "incidents": store.incidents(),
            "slo": {"window_seconds": window_seconds, "minimum_samples": 20,
                    "readiness_99pct": {"target": .99, "observed": readiness_fraction,
                       "status": "OBSERVED" if readiness_fraction is not None else
                                 "INSUFFICIENT_DATA"},
                    "rpc_p95_under_2s": {"target_ms": 2000,
                       "observed_ms": rpc_p95,
                       "status": "OBSERVED" if rpc_p95 is not None else
                                 "INSUFFICIENT_DATA"},
                    "index_lag_p95_under_5m": {"target_seconds": 300,
                        "observed_seconds": None, "status": "INSUFFICIENT_DATA"},
                    "zero_duplicate_movements": {"target": 0,
                        "observed": None, "status": "INSUFFICIENT_DATA"},
                    "critical_alert_within_60s": {"target_seconds": 60,
                        "observed_seconds": None, "status": "INSUFFICIENT_DATA"}}}
