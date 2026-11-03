"""Isolated signed-card catalogue; current AgentAccount is rechecked on every read."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sqlite3
import threading
import time

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from tools.discovery.agent_discovery import (DiscoveryError, Idl,
    b58decode, find_program_address, discover)
from tools.deployment.devnet import Rpc
from tools.operations.structured_logs import correlation_id, emit, new_trace_id
from .cards import (CardError, b64, canonical, identity_params, unb64,
                    validate_card, verify_conatus_card)
from .trust import (GENESIS_HASH, NETWORK, PROGRAM_ID, RPC_URL,
    verify_approved_identity, verify_live_program)


class DiscoveryIdentitySource:
    """Reuse CON-18/21 IDL/PDA validation at finalized commitment."""
    def __init__(self, rpc_url: str, idl_path: Path):
        self.idl_path = Path(idl_path)
        self.idl = Idl(verify_approved_identity(self.idl_path, rpc_url))
        if self.idl.address != PROGRAM_ID:
            raise CardError("INVALID_TRUST_POLICY")
        self.rpc = Rpc(rpc_url)

    def __call__(self, agent_account: str) -> dict | None:
        verify_approved_identity(self.idl_path, self.rpc.url)
        if self.idl.address != PROGRAM_ID or self.rpc.url != RPC_URL:
            raise CardError("INVALID_TRUST_POLICY")
        if self.rpc.call("getGenesisHash", []) != GENESIS_HASH:
            raise CardError("INVALID_NETWORK")
        verify_live_program(self.rpc)
        snapshot = discover(self.rpc, self.idl, commitment="finalized")
        if (snapshot.get("program_id") != PROGRAM_ID or
                snapshot.get("protocol_config") !=
                find_program_address([b"protocol_config"], PROGRAM_ID) or
                snapshot.get("commitment") != "finalized"):
            raise CardError("INVALID_IDENTITY")
        if snapshot["protocol_paused"]:
            return None
        genesis = self.rpc.call("getGenesisHash", [])
        verify_approved_identity(self.idl_path, self.rpc.url)
        verify_live_program(self.rpc)
        if genesis != GENESIS_HASH:
            raise CardError("INVALID_NETWORK")
        matches = [item for item in snapshot["agents"]
                   if item["agent_account"] == agent_account]
        if len(matches) != 1:
            return None
        return {**matches[0], "network": NETWORK, "genesis_hash": GENESIS_HASH,
                "program_id": PROGRAM_ID}


class CardCatalog:
    def __init__(self, path: Path, identity_source, *, organization_check=None,
                 operational_store=None):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.identity_source = identity_source
        self.organization_check = organization_check
        self.operational_store = operational_store
        self.lock = threading.RLock()
        self.db = sqlite3.connect(self.path, isolation_level=None,
                                  check_same_thread=False, timeout=10)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA foreign_keys=ON")
        self.db.execute("""CREATE TABLE IF NOT EXISTS cards (
            card_id TEXT PRIMARY KEY, agent_account TEXT NOT NULL UNIQUE,
            card_version INTEGER NOT NULL, owner_pubkey TEXT NOT NULL,
            publisher_id TEXT NOT NULL, endpoint_domain TEXT NOT NULL UNIQUE,
            card_json TEXT NOT NULL, card_sha256 TEXT NOT NULL,
            status TEXT NOT NULL CHECK(status IN ('PUBLISHED','REVOKED')),
            expires_at INTEGER NOT NULL, updated_at INTEGER NOT NULL)""")
        self.db.execute("""CREATE TABLE IF NOT EXISTS card_history (
            card_id TEXT NOT NULL, card_version INTEGER NOT NULL,
            event TEXT NOT NULL CHECK(event IN ('PUBLISHED','SUPERSEDED','REVOKED')),
            card_sha256 TEXT NOT NULL, observed_at INTEGER NOT NULL,
            PRIMARY KEY(card_id,card_version,event))""")
        if self.db.execute("PRAGMA quick_check").fetchone()[0] != "ok" or \
                self.db.execute("PRAGMA foreign_key_check").fetchone():
            raise CardError("CATALOG_INTEGRITY")

    def close(self) -> None:
        self.db.close()

    def _metric(self, name: str, value: int = 1) -> None:
        if self.operational_store is not None:
            try:
                self.operational_store.sample(name, value, "cards", "a2a")
            except Exception:
                pass

    def _fresh(self, account: str) -> dict:
        fresh = self.identity_source(account)
        if not isinstance(fresh, dict):
            raise CardError("INVALID_IDENTITY")
        return fresh

    def publish(self, card: dict, *, now: int | None = None) -> dict:
        timestamp = int(time.time()) if now is None else now
        try:
            normalized = validate_card(card)
            params = identity_params(normalized)
            account = params["agentAccount"]
            verified = verify_conatus_card(normalized, self._fresh(account), now=timestamp,
                                           organization_check=self.organization_check)
            sha = hashlib.sha256(canonical(normalized)).hexdigest()
            with self.lock:
                self.db.execute("BEGIN IMMEDIATE")
                try:
                    old = self.db.execute("SELECT * FROM cards WHERE agent_account=?",
                                          (account,)).fetchone()
                    if old and (verified["card_version"] <= old["card_version"] or
                                verified["card_id"] != old["card_id"] or
                                verified["endpoint_domain"] != old["endpoint_domain"]):
                        raise CardError("STALE_CARD")
                    # Revalidate against the current account while holding the write lock.
                    verify_conatus_card(normalized, self._fresh(account), now=timestamp,
                                        organization_check=self.organization_check)
                    if old:
                        self.db.execute("INSERT INTO card_history VALUES (?,?,?,?,?)",
                            (old["card_id"], old["card_version"], "SUPERSEDED",
                             old["card_sha256"], timestamp))
                    self.db.execute("""INSERT INTO cards VALUES (?,?,?,?,?,?,?,?,?,?,?)
                        ON CONFLICT(card_id) DO UPDATE SET
                        agent_account=excluded.agent_account,
                        card_version=excluded.card_version,
                        owner_pubkey=excluded.owner_pubkey,
                        publisher_id=excluded.publisher_id,
                        endpoint_domain=excluded.endpoint_domain,
                        card_json=excluded.card_json,
                        card_sha256=excluded.card_sha256,
                        status=excluded.status,expires_at=excluded.expires_at,
                        updated_at=excluded.updated_at""",
                        (verified["card_id"], account, verified["card_version"],
                         verified["owner_pubkey"], verified["publisher_id"],
                         verified["endpoint_domain"], json.dumps(normalized, sort_keys=True),
                         sha, "PUBLISHED", int(verified["expires_at"]), timestamp))
                    self.db.execute("INSERT INTO card_history VALUES (?,?,?,?,?)",
                        (verified["card_id"], verified["card_version"], "PUBLISHED", sha,
                         timestamp))
                    self.db.execute("COMMIT")
                except BaseException:
                    self.db.execute("ROLLBACK")
                    raise
            self._metric("a2a_cards_published")
            emit("INFO", "a2a_catalog", "publish", agent_id=verified["agent_id"],
                 card_id=verified["card_id"], card_version=str(verified["card_version"]),
                 publisher_id=verified["publisher_id"], discovery_source="conatus",
                 correlation_id=correlation_id(verified["agent_account"], verified["card_id"]),
                 trace_id=new_trace_id(), verification_status=verified["status"],
                 schema_version="1.0", status="PUBLISHED")
            return verified
        except (CardError, KeyError, sqlite3.Error) as exc:
            self._metric("a2a_cards_rejected")
            if isinstance(exc, CardError):
                if exc.code == "INVALID_SIGNATURE":
                    self._metric("a2a_invalid_signatures")
                raise
            raise CardError("CATALOG_INTEGRITY") from exc

    def _row(self, row: sqlite3.Row | None, now: int) -> dict | None:
        if row is None or row["status"] != "PUBLISHED" or now >= row["expires_at"]:
            return None
        try:
            card = json.loads(row["card_json"])
            if hashlib.sha256(canonical(card)).hexdigest() != row["card_sha256"]:
                raise CardError("CATALOG_INTEGRITY")
            result = verify_conatus_card(card, self._fresh(row["agent_account"]),
                                          now=now, organization_check=self.organization_check)
            if (result["card_id"] != row["card_id"] or
                    result["card_version"] != row["card_version"] or
                    result["owner_pubkey"] != row["owner_pubkey"] or
                    result["publisher_id"] != row["publisher_id"] or
                    result["endpoint_domain"] != row["endpoint_domain"]):
                raise CardError("CATALOG_INTEGRITY")
            self._metric("a2a_cards_validated")
            return card
        except (CardError, DiscoveryError, OSError, TimeoutError, ValueError, KeyError):
            self._metric("a2a_cards_rejected")
            return None

    def get(self, card_id: str, *, now: int | None = None) -> dict | None:
        timestamp = int(time.time()) if now is None else now
        with self.lock:
            row = self.db.execute("SELECT * FROM cards WHERE card_id=?", (card_id,)).fetchone()
            return self._row(row, timestamp)

    def by_domain(self, domain: str, *, now: int | None = None) -> dict | None:
        timestamp = int(time.time()) if now is None else now
        with self.lock:
            row = self.db.execute("SELECT * FROM cards WHERE endpoint_domain=?",
                                  (domain.lower(),)).fetchone()
            return self._row(row, timestamp)

    def search(self, *, skill: str | None = None, category: str | None = None,
               modality: str | None = None, capability: str | None = None,
               version: str | None = None, agent_id: str | None = None,
               organization_id: str | None = None, now: int | None = None) -> list[dict]:
        timestamp = int(time.time()) if now is None else now
        with self.lock:
            rows = self.db.execute("SELECT * FROM cards ORDER BY card_id LIMIT 1000").fetchall()
            cards = [card for row in rows if (card := self._row(row, timestamp)) is not None]
        result = []
        for card in cards:
            params = identity_params(card)
            ids = {item["id"] for item in card["skills"]}
            tags = {tag for item in card["skills"] for tag in item["tags"]}
            if (skill and skill not in ids or category and category not in tags or
                    capability and "conatus." + capability not in ids or
                    modality and modality not in card["defaultInputModes"] +
                       card["defaultOutputModes"] or
                    version and all(item["protocolVersion"] != version for item in
                                    card["supportedInterfaces"]) or
                    agent_id and params["agentId"] != agent_id or
                    organization_id and params["organizationId"] != organization_id):
                continue
            result.append(card)
        return result

    def verify(self, card_id: str, *, now: int | None = None) -> dict:
        card = self.get(card_id, now=now)
        if card is None:
            raise CardError("UNTRUSTED_CARD")
        params = identity_params(card)
        return verify_conatus_card(card, self._fresh(params["agentAccount"]),
                                   now=now, organization_check=self.organization_check)

    def revoke(self, card_id: str, owner_signature: str, *, now: int | None = None) -> None:
        timestamp = int(time.time()) if now is None else now
        with self.lock:
            self.db.execute("BEGIN IMMEDIATE")
            try:
                row = self.db.execute("SELECT * FROM cards WHERE card_id=?", (card_id,)).fetchone()
                if row is None or self._row(row, timestamp) is None:
                    raise CardError("UNTRUSTED_CARD")
                message = (f"CONATUS-A2A-REVOKE-v1\n{card_id}\n{row['card_version']}\n"
                           f"{row['owner_pubkey']}").encode()
                try:
                    Ed25519PublicKey.from_public_bytes(b58decode(row["owner_pubkey"], 32)).verify(
                        unb64(owner_signature), message)
                except (InvalidSignature, ValueError) as exc:
                    raise CardError("INVALID_SIGNATURE") from exc
                self.db.execute("UPDATE cards SET status='REVOKED',updated_at=? WHERE card_id=?",
                                (timestamp, card_id))
                self.db.execute("INSERT INTO card_history VALUES (?,?,?,?,?)",
                    (card_id, row["card_version"], "REVOKED", row["card_sha256"], timestamp))
                self.db.execute("COMMIT")
            except BaseException:
                self.db.execute("ROLLBACK")
                raise
