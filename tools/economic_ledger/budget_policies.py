"""CON-27: owner-authorized, versioned off-chain budget policy administration.

This module configures limits only. It never writes movements, reserves, journal
entries, escrow or Solana accounts. Spending decisions belong to CON-28.
"""
from __future__ import annotations

import hashlib
import json
import re
import threading
import time
from typing import Any

from cryptography.hazmat.primitives.asymmetric import ed25519

from .ledger import EconomicLedger, validate_monetary_context
from .models import LedgerValidationError

MAX_U64 = (1 << 64) - 1
DOMAIN = "conatus:budget-policy-mutation:v1"
STATUSES = {"DRAFT", "ACTIVE", "PAUSED", "REVOKED"}
ACTIONS = {"CREATE", "UPDATE", "ACTIVATE", "PAUSE", "RESUME", "REVOKE"}
CONTROL_FIELDS = {"expected_version", "idempotency_key", "nonce", "revision_reason"}
CONFIG_FIELDS = {"network", "genesis_hash", "program_id", "asset_rules",
                 "allowed_recipients", "valid_from", "expires_at"}


class PolicyError(Exception):
    def __init__(self, status: int, code: str, message: str):
        super().__init__(message)
        self.status = status
        self.code = code


def canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, ensure_ascii=False,
                      separators=(",", ":"), allow_nan=False).encode("utf-8")


def digest(value: Any) -> str:
    return hashlib.sha256(canonical(value)).hexdigest()


def pubkey(value: Any, field: str) -> str:
    if not isinstance(value, str) or len(value) > 50:
        raise PolicyError(400, "INVALID_PUBKEY", f"{field} must be a Solana public key")
    try:
        from tools.discovery.agent_discovery import b58decode
        if len(b58decode(value, 32)) != 32:
            raise ValueError("incorrect key length")
    except Exception as exc:
        raise PolicyError(400, "INVALID_PUBKEY", f"{field} must be a Solana public key") from exc
    return value


def amount(value: Any, field: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"(0|[1-9][0-9]*)", value) or int(value) > MAX_U64:
        raise PolicyError(400, "INVALID_AMOUNT", f"{field} must be an exact unsigned u64 decimal string")
    return value


def normalized_config(body: dict[str, Any]) -> dict[str, Any]:
    if set(body) - (CONTROL_FIELDS | CONFIG_FIELDS) or not CONFIG_FIELDS.issubset(body):
        raise PolicyError(400, "INVALID_POLICY", "Missing or unknown policy configuration fields")
    network, genesis, program = body["network"], body["genesis_hash"], body["program_id"]
    if not all(isinstance(x, str) and x and x != "PENDING_RESOLUTION" for x in (network, genesis, program)):
        raise PolicyError(400, "INVALID_CONTEXT", "Complete resolved monetary context is required")
    pubkey(genesis, "genesis_hash")
    pubkey(program, "program_id")
    rules = body["asset_rules"]
    recipients = body["allowed_recipients"]
    if not isinstance(rules, list) or not rules or not isinstance(recipients, list):
        raise PolicyError(400, "INVALID_POLICY", "Explicit asset rules and recipient list are required")
    normalized_rules: list[dict[str, Any]] = []
    seen_mints: set[str] = set()
    rule_fields = {"token_mint", "max_per_operation_base_units_str",
                   "max_daily_spend_base_units_str", "minimum_reserve_base_units_str", "enabled"}
    for item in rules:
        if not isinstance(item, dict) or set(item) != rule_fields or type(item["enabled"]) is not bool:
            raise PolicyError(400, "INVALID_RULE", "Asset rule has missing or unknown fields")
        mint = pubkey(item["token_mint"], "token_mint")
        if mint in seen_mints:
            raise PolicyError(400, "DUPLICATE_ASSET", "Duplicate token mint")
        seen_mints.add(mint)
        try:
            resolved = validate_monetary_context(network=network, genesis_hash=genesis,
                                                  program_id=program, token_mint=mint)
        except LedgerValidationError as exc:
            raise PolicyError(422, "INVALID_CONTEXT", str(exc)) from exc
        if resolved[:3] != (network, genesis, program):
            raise PolicyError(422, "INVALID_CONTEXT", "Monetary context changed during validation")
        normalized_rules.append({
            "token_mint": mint,
            "max_per_operation_base_units_str": amount(item["max_per_operation_base_units_str"], "max_per_operation"),
            "max_daily_spend_base_units_str": amount(item["max_daily_spend_base_units_str"], "max_daily_spend"),
            "minimum_reserve_base_units_str": amount(item["minimum_reserve_base_units_str"], "minimum_reserve"),
            "enabled": item["enabled"],
        })
    normalized_recipients = [pubkey(x, "recipient") for x in recipients]
    if len(set(normalized_recipients)) != len(normalized_recipients):
        raise PolicyError(400, "DUPLICATE_RECIPIENT", "Duplicate recipient")
    start, end = body["valid_from"], body["expires_at"]
    if type(start) is not int or type(end) is not int or start < 0 or end <= start:
        raise PolicyError(422, "INVALID_VALIDITY", "expires_at must be later than valid_from")
    return {
        "network": network, "genesis_hash": genesis, "program_id": program,
        "asset_rules": sorted(normalized_rules, key=lambda r: r["token_mint"]),
        "allowed_recipients": sorted(normalized_recipients),
        "valid_from": start, "expires_at": end,
    }


def validate_control(body: Any, action: str) -> tuple[int, str, str, str | None]:
    if not isinstance(body, dict) or set(body) - (CONTROL_FIELDS | (CONFIG_FIELDS if action in {"CREATE", "UPDATE"} else set())):
        raise PolicyError(400, "INVALID_BODY", "Unknown mutation fields")
    required = {"expected_version", "idempotency_key", "nonce"}
    if not required.issubset(body):
        raise PolicyError(400, "INVALID_BODY", "Missing mutation control fields")
    version, key, nonce, reason = (body["expected_version"], body["idempotency_key"],
                                   body["nonce"], body.get("revision_reason"))
    if type(version) is not int or version < 0:
        raise PolicyError(400, "INVALID_VERSION", "expected_version must be a nonnegative integer")
    if not isinstance(key, str) or not re.fullmatch(r"[A-Za-z0-9._:-]{8,128}", key):
        raise PolicyError(400, "INVALID_IDEMPOTENCY_KEY", "Invalid idempotency key")
    if not isinstance(nonce, str) or not re.fullmatch(r"[A-Za-z0-9._:-]{16,128}", nonce):
        raise PolicyError(400, "INVALID_NONCE", "Invalid nonce")
    if reason is not None and (not isinstance(reason, str) or len(reason) > 500):
        raise PolicyError(400, "INVALID_REASON", "Invalid revision reason")
    if action not in {"CREATE", "UPDATE"} and set(body) - CONTROL_FIELDS:
        raise PolicyError(400, "INVALID_BODY", "Lifecycle mutation may not change configuration")
    return version, key, nonce, reason


def mutation_message(timestamp: int, account: str, owner: str, method: str,
                     path: str, body: dict[str, Any]) -> bytes:
    return (f"{DOMAIN}:{timestamp}:{account}:{owner}:{method}:{path}:"
            f"{digest(body)}:{body['nonce']}:{body['idempotency_key']}:"
            f"{body['expected_version']}").encode("utf-8")


def verify_mutation(agent: dict[str, Any], method: str, path: str,
                    body: dict[str, Any], headers: Any, now: int | None = None) -> str:
    h = {str(k).lower(): str(v) for k, v in headers.items()} if headers else {}
    signer, timestamp, signature = (h.get("x-signer-pubkey"), h.get("x-timestamp"),
                                     h.get("x-signature"))
    if not signer or not timestamp or not signature:
        raise PolicyError(401, "UNAUTHORIZED", "Signed mutation headers are required")
    try:
        pubkey(signer, "signer")
    except PolicyError as exc:
        raise PolicyError(401, "INVALID_PUBKEY", "Invalid mutation signer") from exc
    try:
        ts = int(timestamp)
        if abs((int(time.time()) if now is None else now) - ts) > 300:
            raise PolicyError(401, "EXPIRED_CREDENTIALS", "Mutation signature has expired")
        from tools.discovery.agent_discovery import b58decode
        signature_bytes = b58decode(signature, 64)
        key_bytes = b58decode(signer, 32)
        ed25519.Ed25519PublicKey.from_public_bytes(key_bytes).verify(
            signature_bytes, mutation_message(ts, agent["agent_account"], signer, method, path, body))
    except PolicyError:
        raise
    except Exception as exc:
        raise PolicyError(401, "INVALID_SIGNATURE", "Mutation Ed25519 signature is invalid") from exc
    if signer != agent.get("owner"):
        raise PolicyError(403, "FORBIDDEN", "Signer is not the current AgentAccount owner")
    return signer


class BudgetPolicyStore:
    """SQLite backed administrator. Each mutation inserts one immutable version."""

    def __init__(self, ledger: EconomicLedger):
        self.ledger = ledger
        self.conn = ledger._conn
        self._lock = threading.RLock()

    @staticmethod
    def policy_id(account: str, network: str, genesis: str, program: str) -> str:
        return "bp_" + hashlib.sha256(canonical([account, network, genesis, program])).hexdigest()[:32]

    def _policy_row(self, account: str):
        return self.conn.execute("SELECT * FROM agent_budget_policies WHERE agent_account = ?", (account,)).fetchone()

    def _require_identity(self, agent: dict[str, Any], policy: Any, actor: str | None = None) -> None:
        """Keep every version scoped to the exact registered AgentAccount identity."""
        if policy is None or not all((
            policy["agent_account"] == agent.get("agent_account"),
            policy["agent_id"] == agent.get("agent_id"),
            policy["owner_pubkey"] == agent.get("owner"),
            actor is None or actor == policy["owner_pubkey"],
            bool(policy["network"] and policy["genesis_hash"] and policy["program_id"]),
            policy["policy_id"] == self.policy_id(
                policy["agent_account"], policy["network"],
                policy["genesis_hash"], policy["program_id"]),
        )):
            raise PolicyError(404, "POLICY_NOT_FOUND", "Policy not found for current AgentAccount identity")

    def _version(self, policy_id: str, version: int) -> dict[str, Any]:
        p = self.conn.execute("SELECT * FROM agent_budget_policies WHERE policy_id = ?", (policy_id,)).fetchone()
        v = self.conn.execute("SELECT * FROM agent_budget_policy_versions WHERE policy_id = ? AND version = ?",
                              (policy_id, version)).fetchone()
        if p is None or v is None:
            raise PolicyError(404, "POLICY_NOT_FOUND", "Policy version not found")
        rules = self.conn.execute(
            "SELECT * FROM agent_budget_policy_asset_rules WHERE policy_id = ? AND version = ? ORDER BY token_mint",
            (policy_id, version)).fetchall()
        recipients = self.conn.execute(
            "SELECT recipient_pubkey FROM agent_budget_policy_recipients WHERE policy_id = ? AND version = ? ORDER BY recipient_pubkey",
            (policy_id, version)).fetchall()
        result = {
            "policy_id": policy_id, "agent_account": p["agent_account"], "agent_id": p["agent_id"],
            "owner_pubkey": p["owner_pubkey"], "network": p["network"],
            "genesis_hash": p["genesis_hash"], "program_id": p["program_id"],
            "version": version, "status": v["status"],
            "effective_status": "EXPIRED" if v["status"] == "ACTIVE" and v["expires_at"] <= int(time.time()) else v["status"],
            "asset_rules": [{key: (bool(r[key]) if key == "enabled" else r[key]) for key in
                             ("token_mint", "max_per_operation_base_units_str", "max_daily_spend_base_units_str",
                              "minimum_reserve_base_units_str", "enabled")} for r in rules],
            "allowed_recipients": [r["recipient_pubkey"] for r in recipients],
            "valid_from": v["valid_from"], "expires_at": v["expires_at"],
            "created_at": v["created_at"], "created_by": v["created_by"],
            "revision_reason": v["revision_reason"], "policy_hash": v["policy_hash"],
            "idempotency_key": v["idempotency_key"], "action": v["action"],
            "is_currently_valid": v["status"] == "ACTIVE" and v["valid_from"] <= int(time.time()) < v["expires_at"],
        }
        return result

    def current(self, agent: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            p = self._policy_row(agent["agent_account"])
            self._require_identity(agent, p)
            return self._version(p["policy_id"], p["current_version"])

    def history(self, agent: dict[str, Any]) -> list[dict[str, Any]]:
        with self._lock:
            p = self._policy_row(agent["agent_account"])
            self._require_identity(agent, p)
            rows = self.conn.execute("SELECT version FROM agent_budget_policy_versions WHERE policy_id = ? ORDER BY version DESC",
                                     (p["policy_id"],)).fetchall()
            return [self._version(p["policy_id"], r["version"]) for r in rows]

    def version(self, agent: dict[str, Any], version: int) -> dict[str, Any]:
        with self._lock:
            p = self._policy_row(agent["agent_account"])
            self._require_identity(agent, p)
            return self._version(p["policy_id"], version)

    def mutate(self, agent: dict[str, Any], action: str, body: dict[str, Any],
               actor: str) -> tuple[dict[str, Any], bool]:
        if action not in ACTIONS or actor != agent.get("owner"):
            raise PolicyError(403, "FORBIDDEN", "Current owner is required")
        expected, idem, nonce, reason = validate_control(body, action)
        config = normalized_config(body) if action in {"CREATE", "UPDATE"} else None
        request_hash = digest({"action": action, "agent_account": agent["agent_account"], "body": body})
        with self._lock:
            self.conn.execute("BEGIN IMMEDIATE")
            try:
                p = self._policy_row(agent["agent_account"])
                if p is not None:
                    self._require_identity(agent, p, actor)
                previous = self.conn.execute(
                    "SELECT policy_id, version, request_hash FROM agent_budget_policy_versions WHERE idempotency_key = ?",
                    (idem,)).fetchone()
                if previous:
                    if (p is None or previous["policy_id"] != p["policy_id"] or
                            (config is not None and
                             (config["network"], config["genesis_hash"], config["program_id"]) !=
                             (p["network"], p["genesis_hash"], p["program_id"]))):
                        raise PolicyError(409, "IDEMPOTENCY_CONFLICT", "Idempotency key is not valid for this policy")
                    if previous["request_hash"] != request_hash:
                        raise PolicyError(409, "IDEMPOTENCY_CONFLICT", "Idempotency key reused with different request")
                    prior_version = self._version(previous["policy_id"], previous["version"])
                    self.conn.execute("COMMIT")
                    return prior_version, False
                if self.conn.execute("SELECT 1 FROM agent_budget_policy_versions WHERE nonce = ?", (nonce,)).fetchone():
                    raise PolicyError(409, "NONCE_REPLAY", "Mutation nonce was already used")
                if action == "CREATE":
                    if p or expected != 0:
                        raise PolicyError(409, "VERSION_CONFLICT", "Policy already exists or expected version is not zero")
                    assert config is not None
                    policy_id = self.policy_id(agent["agent_account"], config["network"],
                                               config["genesis_hash"], config["program_id"])
                    current_version, status = 0, "DRAFT"
                    self.conn.execute(
                        "INSERT INTO agent_budget_policies VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                        (policy_id, agent["agent_account"], agent["agent_id"], actor,
                         config["network"], config["genesis_hash"], config["program_id"], 1))
                else:
                    if p is None:
                        raise PolicyError(404, "POLICY_NOT_FOUND", "Policy not found")
                    policy_id, current_version = p["policy_id"], p["current_version"]
                    if expected != current_version:
                        raise PolicyError(409, "VERSION_CONFLICT", "Current policy version has changed")
                    old = self._version(policy_id, current_version)
                    status = old["status"]
                    if status == "REVOKED":
                        raise PolicyError(422, "REVOKED_POLICY", "Revoked policy is final")
                    if action == "UPDATE":
                        assert config is not None
                        if (config["network"], config["genesis_hash"], config["program_id"]) != (
                            p["network"], p["genesis_hash"], p["program_id"]):
                            raise PolicyError(422, "CONTEXT_CHANGE", "Policy monetary context cannot change")
                        if old["effective_status"] == "EXPIRED":
                            status = "DRAFT"
                    else:
                        config = {k: old[k] for k in CONFIG_FIELDS}
                        transitions = {"ACTIVATE": ("DRAFT", "ACTIVE"), "PAUSE": ("ACTIVE", "PAUSED"),
                                       "RESUME": ("PAUSED", "ACTIVE"),
                                       "REVOKE": (("DRAFT", "ACTIVE", "PAUSED"), "REVOKED")}
                        source, target = transitions[action]
                        if status not in (source if isinstance(source, tuple) else (source,)):
                            raise PolicyError(422, "INVALID_TRANSITION", f"Cannot {action} from {status}")
                        if action in {"ACTIVATE", "RESUME"} and config["expires_at"] <= int(time.time()):
                            raise PolicyError(422, "EXPIRED_POLICY", "Expired policy cannot become active")
                        status = target
                assert config is not None
                version = current_version + 1
                payload = {
                    "policy_id": policy_id, "agent_account": agent["agent_account"],
                    "agent_id": agent["agent_id"], "owner_pubkey": actor,
                    "version": version, "status": status, **config,
                }
                policy_hash = digest(payload)
                now = int(time.time())
                self.conn.execute(
                    "INSERT INTO agent_budget_policy_versions VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (policy_id, version, status, config["valid_from"], config["expires_at"],
                     now, actor, reason, policy_hash, request_hash, idem, nonce, action))
                for rule in config["asset_rules"]:
                    self.conn.execute(
                        "INSERT INTO agent_budget_policy_asset_rules VALUES (?, ?, ?, ?, ?, ?, ?)",
                        (policy_id, version, rule["token_mint"], rule["max_per_operation_base_units_str"],
                         rule["max_daily_spend_base_units_str"], rule["minimum_reserve_base_units_str"],
                         int(rule["enabled"])))
                for recipient in config["allowed_recipients"]:
                    self.conn.execute("INSERT INTO agent_budget_policy_recipients VALUES (?, ?, ?)",
                                      (policy_id, version, recipient))
                if action != "CREATE":
                    self.conn.execute("UPDATE agent_budget_policies SET current_version = ? WHERE policy_id = ? AND current_version = ?",
                                      (version, policy_id, current_version))
                    if self.conn.execute("SELECT changes()").fetchone()[0] != 1:
                        raise PolicyError(409, "VERSION_CONFLICT", "Concurrent policy update")
                self.conn.execute("COMMIT")
            except Exception:
                self.conn.execute("ROLLBACK")
                raise
        return self._version(policy_id, version), True

    def reserve_comparison(self, policy: dict[str, Any]) -> list[dict[str, Any]]:
        account = policy["agent_account"]
        result = []
        for rule in policy["asset_rules"]:
            scope = dict(network=policy["network"], genesis_hash=policy["genesis_hash"],
                         program_id=policy["program_id"], token_mint=rule["token_mint"])
            reserves = self.ledger.list_reserves(account, **scope)
            reserved = sum(int(r.current_reserved_base_units) for r in reserves if r.status.value == "ACTIVE")
            summaries = self.ledger.get_economic_summary(account, **scope)
            summary = summaries[0] if len(summaries) == 1 else None
            minimum = int(rule["minimum_reserve_base_units_str"])
            result.append({
                "token_mint": rule["token_mint"],
                "policy_minimum_reserve_base_units_str": str(minimum),
                "accounting_reserved_base_units_str": str(reserved),
                "reserve_shortfall_base_units_str": str(max(0, minimum - reserved)),
                "ledger_available_balance_str": summary.available_balance_str if summary else None,
                "ledger_accrued_obligations_base_units_str": summary.total_obligations_accrued_str if summary else None,
                "policy_target_is_not_locked_funds": True,
            })
        return result
