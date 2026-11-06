"""Persistent autonomy policy; checked before every tool call."""
from __future__ import annotations

from dataclasses import dataclass
import json
import time

from tools.mcp.security import Principal, TokenVerifier
from .audit import RuntimeStore
from .models import RuntimeDenied, canonical
from .models import FORBIDDEN
from .tool_registry import RISK, ToolSpec


@dataclass(frozen=True)
class Identity:
    agent_id: str
    owner_id: str
    tenant_id: str
    organization_id: str
    agent_type: str = "ANALYST"


class PolicyGate:
    def __init__(self, store: RuntimeStore, admin_verifier: TokenVerifier):
        self.store = store
        self.admin_verifier = admin_verifier

    def _admin(self, identity: Identity, token: str, scope: str = "runtime:admin") -> None:
        principal = self.admin_verifier.verify(token)
        if (principal.audience != "conatus-agent-runtime-admin" or
                principal.subject != identity.owner_id or
                principal.tenant_id != identity.tenant_id or
                principal.organization_id != identity.organization_id or
                scope not in principal.scopes):
            raise RuntimeDenied("ADMIN_DENIED")

    def put(self, identity: Identity, *, admin_token: str, allowed_tools: set[str],
            scopes: set[str], max_steps: int = 8, max_calls: int = 8,
            max_duration_ms: int = 15000, max_compute_units: int = 100,
            max_llm_tokens: int = 0, max_risk: str = "LOW",
            expires_at: int | None = None, environment: str = "offline") -> dict:
        self._admin(identity, admin_token)
        if max_risk not in RISK or environment not in {"offline", "devnet-read-only"}:
            raise RuntimeDenied("POLICY_DENIED")
        if (not allowed_tools or allowed_tools & FORBIDDEN or
                not 1 <= max_steps <= 20 or not 1 <= max_calls <= 100 or
                not 1 <= max_duration_ms <= 60000 or not 1 <= max_compute_units <= 10000 or
                not 0 <= max_llm_tokens <= 100000):
            raise RuntimeDenied("INVALID_POLICY")
        expiry = expires_at or int(time.time()) + 3600
        if expiry <= int(time.time()) or expiry > int(time.time()) + 86400:
            raise RuntimeDenied("INVALID_POLICY")
        values = {"agent_id": identity.agent_id, "owner_id": identity.owner_id,
                  "tenant_id": identity.tenant_id, "organization_id": identity.organization_id,
                  "agent_type": identity.agent_type, "allowed_tools": sorted(allowed_tools),
                  "scopes": sorted(scopes), "max_steps": max_steps, "max_calls": max_calls,
                  "max_duration_ms": max_duration_ms, "max_compute_units": max_compute_units,
                  "max_llm_tokens": max_llm_tokens, "max_risk": max_risk,
                  "expires_at": expiry, "environment": environment}
        canonical(values)
        with self.store.lock:
            self.store.conn.execute("BEGIN IMMEDIATE")
            try:
                prior = self.store.conn.execute("SELECT * FROM runtime_policies WHERE agent_id=?",
                                                (identity.agent_id,)).fetchone()
                if prior and any(prior[k] != getattr(identity, k) for k in
                                 ("owner_id", "tenant_id", "organization_id")):
                    raise RuntimeDenied("POLICY_IDENTITY_CONFLICT")
                version = prior["version"] + 1 if prior else 1
                policy_hash = self.store.seal({**values, "version": version})
                self.store.conn.execute("INSERT INTO runtime_policies VALUES (?,?,?,?,?,?,?,0) "
                    "ON CONFLICT(agent_id) DO UPDATE SET version=excluded.version,"
                    "policy_hash=excluded.policy_hash,policy_json=excluded.policy_json,revoked=0",
                    (identity.agent_id, identity.owner_id, identity.tenant_id,
                     identity.organization_id, version, policy_hash,
                     json.dumps(values, sort_keys=True)))
                self.store.conn.execute("COMMIT")
                return {**values, "version": version, "policy_hash": policy_hash}
            except Exception:
                self.store.conn.execute("ROLLBACK")
                raise

    def current(self, identity: Identity) -> dict:
        with self.store.lock:
            row = self.store.conn.execute("SELECT * FROM runtime_policies WHERE agent_id=?",
                                          (identity.agent_id,)).fetchone()
            if (row is None or row["revoked"] or any(row[k] != getattr(identity, k) for k in
                ("owner_id", "tenant_id", "organization_id"))):
                raise RuntimeDenied("POLICY_DENIED")
            policy = json.loads(row["policy_json"])
            if (self.store.seal({**policy, "version": row["version"]}) != row["policy_hash"] or
                    int(time.time()) >= policy["expires_at"]):
                raise RuntimeDenied("POLICY_DENIED")
            return {**policy, "version": row["version"], "policy_hash": row["policy_hash"]}

    def revoke(self, identity: Identity, *, admin_token: str) -> None:
        self._admin(identity, admin_token)
        with self.store.lock:
            self.store.conn.execute("UPDATE runtime_policies SET revoked=1 WHERE agent_id=? "
                "AND owner_id=? AND tenant_id=? AND organization_id=?",
                (identity.agent_id, identity.owner_id, identity.tenant_id, identity.organization_id))

    def switch(self, name: str, enabled: bool, *, admin_token: str, identity: Identity) -> None:
        self._admin(identity, admin_token, "runtime:globaladmin" if name == "global"
                    else "runtime:admin")
        if name not in {"global", "agent:" + identity.agent_id}:
            raise RuntimeDenied("POLICY_DENIED")
        with self.store.lock:
            self.store.conn.execute("INSERT INTO runtime_controls VALUES (?,?) "
                "ON CONFLICT(name) DO UPDATE SET enabled=excluded.enabled", (name, int(enabled)))

    def suspended(self, tool_id: str, enabled: bool, *, admin_token: str,
                  identity: Identity) -> None:
        self._admin(identity, admin_token)
        with self.store.lock:
            self.store.conn.execute("INSERT INTO runtime_controls VALUES (?,?) "
                "ON CONFLICT(name) DO UPDATE SET enabled=excluded.enabled",
                ("tool:" + identity.agent_id + ":" + tool_id, int(enabled)))

    def check(self, identity: Identity, principal: Principal, token_exp: int,
              spec: ToolSpec, *, expected_hash: str, calls: int, tool_calls: int,
              elapsed_ms: int, compute_used: int, environment: str) -> str:
        policy = self.current(identity)
        if policy["policy_hash"] != expected_hash:
            raise RuntimeDenied("POLICY_CHANGED")
        if token_exp <= int(time.time()) or principal.expires_at <= int(time.time()):
            raise RuntimeDenied("TOKEN_EXPIRED")
        if (principal.subject != identity.owner_id or principal.tenant_id != identity.tenant_id or
                principal.organization_id != identity.organization_id or
                principal.audience != "conatus-agent-runtime"):
            raise RuntimeDenied("IDENTITY_MISMATCH")
        if (spec.tool_id not in policy["allowed_tools"] or
                not spec.required_scopes.issubset(principal.scopes & set(policy["scopes"])) or
                identity.agent_type not in spec.allowed_agent_types or
                RISK[spec.risk_level] > RISK[policy["max_risk"]] or
                calls >= policy["max_calls"] or tool_calls >= spec.max_calls or
                elapsed_ms >= policy["max_duration_ms"] or
                compute_used >= policy["max_compute_units"] or
                environment != policy["environment"]):
            raise RuntimeDenied("POLICY_DENIED")
        self.check_active(identity, expected_hash, spec.tool_id)
        return "ALLOW"

    def check_active(self, identity: Identity, expected_hash: str,
                     tool_id: str | None = None) -> None:
        if self.current(identity)["policy_hash"] != expected_hash:
            raise RuntimeDenied("POLICY_CHANGED")
        keys = ["global", "agent:" + identity.agent_id]
        if tool_id is not None:
            keys.append("tool:" + identity.agent_id + ":" + tool_id)
        with self.store.lock:
            for key in keys:
                row = self.store.conn.execute("SELECT enabled FROM runtime_controls WHERE name=?",
                                              (key,)).fetchone()
                if row and row["enabled"]:
                    raise RuntimeDenied("KILL_SWITCH")
