"""Bounded, read-only-on-chain Devnet WorkOrder settlement ingestion.

Only the local Economic Ledger SQLite file is writable. No signing or Solana
transaction submission API is imported here.
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import sqlite3
import sys
import time
from typing import Any

from tools.deployment import devnet, test_mint
from tools.economic_ledger.ledger import EconomicLedger
from tools.economic_ledger.models import MovementStatus
from tools.economic_ledger.spl_reconciler import (
    DEFAULT_TOKEN_PROGRAM, DEFAULT_PROTOCOL_CONFIG, EvidenceSourceKind, RpcError, SolanaRpcClient,
    SplSettlementReconciler, SETTLE_WORK_ORDER_DISCRIMINATOR, b58decode,
    build_financial_effect_id, decode_work_order_account, derive_work_order_pda,
    extract_account_bytes,
)

ROOT = Path(__file__).resolve().parents[2]
NETWORK = "solana:devnet"
GENESIS = "EtWTRABZaYq6iMfeYKouRu166VU2xqa1wcaWoxPkrZBG"
PROGRAM = "CeA1P1NSuPLUH31KsT4j3pZeBsknQZ3NSC6GUAqcsCLy"
MINT = "HpfaV9oRuTN1b3ktDKvJoWqUWFZ1o9VFmhejxxqQ1vyh"
RPC_URL = "https://api.devnet.solana.com"


class IngestionError(RuntimeError):
    pass


class IngestionGap(IngestionError):
    pass


class PendingFinality(IngestionGap):
    pass


class UnavailableHistory(IngestionGap):
    pass


class IngestionIntegrityError(IngestionError):
    pass


@dataclass(frozen=True)
class Scope:
    work_order: str
    min_slot: int
    max_slot: int | None = None

    def __post_init__(self) -> None:
        b58decode(self.work_order, 32)
        if self.min_slot < 0 or self.max_slot is not None and self.max_slot < self.min_slot:
            raise ValueError("Invalid bounded slot interval")

    @property
    def label(self) -> str:
        return f"work_order:{self.work_order}:{self.min_slot}:{self.max_slot if self.max_slot is not None else '*'}"

    @property
    def scope_id(self) -> str:
        body = f"{NETWORK}|{GENESIS}|{PROGRAM}|{MINT}|{self.label}"
        return hashlib.sha256(body.encode()).hexdigest()


class _DeploymentRpcAdapter:
    def __init__(self, rpc: SolanaRpcClient) -> None:
        self.rpc = rpc

    def call(self, method: str, params: list | None = None) -> Any:
        return self.rpc._call(method, params)


def preflight(rpc: SolanaRpcClient) -> dict[str, Any]:
    """Recheck approved program bytes and mint configuration using real RPC."""
    if type(rpc) is not SolanaRpcClient or rpc.rpc_url != RPC_URL:
        raise IngestionError("LIVE_RPC ingestion requires the official Devnet RPC client")
    config = devnet.load_json(ROOT / "tools/deployment/devnet.json")
    adapter = _DeploymentRpcAdapter(rpc)
    observed = devnet.inspect_program(config, adapter)
    if not observed["exists"] or observed["program_id"] != PROGRAM:
        raise IngestionError("Approved Devnet program unavailable")
    binary = (ROOT / "evidence/con35/artifacts/aerosettle.so").read_bytes()
    if not devnet.binary_matches_deployed(adapter, observed["program_data_address"], binary):
        raise IngestionError("On-chain SBF differs from approved CON-35 artifact")
    mint_plan = devnet.load_json(ROOT / "evidence/con35/test-mint.json")
    mint_evidence = devnet.load_json(ROOT / "evidence/con35/test-mint-verified.json")
    verified = test_mint.verify(mint_plan, adapter, mint_evidence["creation_signature"])
    if (verified != mint_evidence or verified["mint_pubkey"] != MINT or
            verified["token_program"] != DEFAULT_TOKEN_PROGRAM or
            verified["decimals"] != 6 or rpc.get_genesis_hash() != GENESIS):
        raise IngestionError("Approved test mint or Devnet genesis changed")
    return {"network": NETWORK, "genesis_hash": GENESIS, "program_id": PROGRAM,
            "program_data_address": observed["program_data_address"],
            "upgrade_authority": observed["upgrade_authority_pubkey"],
            "mint": MINT, "mint_authority": verified["mint_authority_pubkey"],
            "decimals": 6, "token_program": DEFAULT_TOKEN_PROGRAM}


def validate_scope(rpc: SolanaRpcClient, scope: Scope) -> None:
    value = rpc.get_account_info(scope.work_order, commitment="finalized")
    if not value or value.get("owner") != PROGRAM:
        raise IngestionIntegrityError("WorkOrder account missing or wrong program owner")
    try:
        order = decode_work_order_account(extract_account_bytes(value))
        pda, _ = derive_work_order_pda(order["protocol_config"], order["creator"],
                                       order["work_order_id"], PROGRAM)
    except (ValueError, KeyError) as exc:
        raise IngestionIntegrityError("Malformed WorkOrder account") from exc
    if (pda != scope.work_order or
            order["protocol_config"] != DEFAULT_PROTOCOL_CONFIG or
            order["token_mint"] != MINT or order["token_program"] != DEFAULT_TOKEN_PROGRAM or
            order["protocol_version"] != 1):
        raise IngestionIntegrityError("WorkOrder PDA, mint or token program changed")


def _entries(rpc: SolanaRpcClient, address: str, *, before: str | None,
             limit: int) -> list[dict]:
    options: dict[str, Any] = {"limit": limit, "commitment": "finalized"}
    if before:
        options["before"] = before
    rows = rpc._call("getSignaturesForAddress", [address, options])
    if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
        raise IngestionGap("Malformed signature page")
    return rows


def discover(rpc: SolanaRpcClient, scope: Scope, anchor: str | None = None,
             *, page_size: int = 100, max_pages: int = 5,
             max_signatures: int = 500) -> list[dict]:
    """Return complete new finalized history, oldest first, or raise without cursor advancement."""
    if not 1 <= page_size <= 1000 or not 1 <= max_pages <= 20 or not 1 <= max_signatures <= 1000:
        raise ValueError("Discovery bounds exceeded")
    rows: list[dict] = []
    seen: set[str] = set()
    before = None
    head = None
    previous_slot = None
    complete = False
    for _ in range(max_pages):
        page = _entries(rpc, scope.work_order, before=before, limit=page_size)
        if head is None and page:
            head = page[0].get("signature")
        if not page:
            complete = anchor is None
            break
        for row in page:
            signature, slot = row.get("signature"), row.get("slot")
            if (not isinstance(signature, str) or not isinstance(slot, int) or slot <= 0 or
                    signature in seen or previous_slot is not None and slot > previous_slot):
                raise IngestionGap("Duplicate, malformed or unordered signature page")
            seen.add(signature)
            previous_slot = slot
            if signature == anchor:
                complete = True
                break
            if slot < scope.min_slot:
                if anchor is not None:
                    raise IngestionGap("Checkpoint signature absent before lower slot bound")
                complete = True
                break
            if scope.max_slot is None or slot <= scope.max_slot:
                rows.append({"signature": signature, "slot": slot})
                if len(rows) > max_signatures:
                    raise IngestionGap("Signature limit reached before complete page")
        if complete:
            break
        before = page[-1]["signature"]
        if len(page) < page_size:
            complete = anchor is None
            break
    if not complete:
        raise IngestionGap("Pagination incomplete or checkpoint signature unavailable")
    fresh = _entries(rpc, scope.work_order, before=None, limit=1)
    if (fresh[0]["signature"] if fresh else None) != head:
        raise IngestionGap("New signatures appeared while paginating; repeat discovery")
    return list(reversed(rows))


def _settlement_indices(tx: dict, program_id: str) -> list[int]:
    message = tx.get("transaction", {}).get("message", {})
    keys = message.get("accountKeys", [])
    keys = [key.get("pubkey") if isinstance(key, dict) else key for key in keys]
    result = []
    for index, ix in enumerate(message.get("instructions", [])):
        if not isinstance(ix, dict):
            raise IngestionIntegrityError("Malformed outer instruction")
        program_index = ix.get("programIdIndex")
        if type(program_index) is not int or not 0 <= program_index < len(keys):
            raise IngestionIntegrityError("Invalid instruction program index")
        if keys[program_index] != program_id:
            continue
        try:
            data = b58decode(ix["data"])
        except (KeyError, ValueError, TypeError) as exc:
            raise IngestionIntegrityError("Malformed Anchor instruction data") from exc
        if data[:8] == SETTLE_WORK_ORDER_DISCRIMINATOR:
            result.append(index)
    return result


class DevnetIngestor:
    def __init__(self, db_path: Path, rpc: SolanaRpcClient | None = None) -> None:
        self.rpc = rpc or SolanaRpcClient(RPC_URL, timeout=20, min_interval=0.3)
        if type(self.rpc) is not SolanaRpcClient or self.rpc.rpc_url != RPC_URL:
            raise IngestionError("Mock or foreign RPC cannot declare LIVE_RPC")
        self.reconciler = SplSettlementReconciler(
            rpc_client=self.rpc, expected_network=NETWORK,
            expected_genesis_hash=GENESIS, expected_program_id=PROGRAM)
        self.ledger = EconomicLedger(db_path=db_path,
                                     reconciliation_verifier=self.reconciler)
        self.db = self.ledger._conn
        self._preflight_done = False

    def close(self) -> None:
        self.ledger.close()

    def _checkpoint(self, scope: Scope) -> sqlite3.Row:
        self.db.execute("""INSERT OR IGNORE INTO ingestion_checkpoints
            (scope_id,network,genesis_hash,program_id,token_mint,ingestion_scope,
             work_order_account,min_slot,max_slot,checkpoint_status)
             VALUES (?,?,?,?,?,?,?,?,?,'READY')""",
            (scope.scope_id, NETWORK, GENESIS, PROGRAM, MINT, scope.label,
             scope.work_order, scope.min_slot, scope.max_slot))
        row = self.db.execute("SELECT * FROM ingestion_checkpoints WHERE scope_id=?",
                              (scope.scope_id,)).fetchone()
        if not row or any((row[key] != value for key, value in (
                ("network", NETWORK), ("genesis_hash", GENESIS),
                ("program_id", PROGRAM), ("token_mint", MINT),
                ("ingestion_scope", scope.label), ("work_order_account", scope.work_order),
                ("min_slot", scope.min_slot), ("max_slot", scope.max_slot),
                ("cursor_version", 1)))):
            raise IngestionIntegrityError("Checkpoint identity or version mismatch")
        return row

    def _incident(self, scope: Scope, signature: str | None, slot: int | None,
                  category: str, detail: str, status: str = "GAP",
                  observation_status: str = "INSUFFICIENT_DATA") -> None:
        now = int(time.time())
        self.db.execute("BEGIN IMMEDIATE")
        try:
            self.db.execute("""INSERT INTO ingestion_incidents
                (scope_id,signature,slot,error_category,detail,observed_at)
                VALUES (?,?,?,?,?,?)""",
                (scope.scope_id, signature, slot, category, detail[:500], now))
            if signature and slot:
                old = self.db.execute("""SELECT attempt_count FROM ingestion_observations
                    WHERE scope_id=? AND signature=?""", (scope.scope_id, signature)).fetchone()
                prior = self.db.execute("""SELECT processing_status FROM ingestion_observations
                    WHERE scope_id=? AND signature=?""", (scope.scope_id, signature)).fetchone()
                if not prior or prior[0] != "RECONCILED":
                    self.db.execute("""INSERT INTO ingestion_observations
                    (scope_id,signature,slot,processing_status,error_category,attempt_count,updated_at)
                    VALUES (?,?,?,?,?,?,?) ON CONFLICT(scope_id,signature) DO UPDATE SET
                    processing_status=excluded.processing_status,
                    error_category=excluded.error_category,
                    attempt_count=excluded.attempt_count,updated_at=excluded.updated_at""",
                    (scope.scope_id, signature, slot, observation_status, category,
                     (old[0] if old else 0) + 1, now))
            self.db.execute("UPDATE ingestion_checkpoints SET checkpoint_status=? WHERE scope_id=?",
                            (status, scope.scope_id))
            self.db.execute("COMMIT")
        except Exception:
            self.db.execute("ROLLBACK")
            raise

    def _store(self, scope: Scope, signature: str, slot: int, status: str,
               receipt: Any = None, movement: Any = None,
               category: str | None = None, lag_seconds: int | None = None) -> bool:
        now = int(time.time())
        duplicate = False
        self.db.execute("BEGIN IMMEDIATE")
        try:
            if receipt:
                for kind, destination, amount, effect_id, movement_id in (
                    ("operator_payout", receipt.operator_token_account,
                     receipt.operator_payout, receipt.effect_id, movement.movement_id),
                    ("creator_refund", receipt.creator_refund_token_account,
                     receipt.creator_refund,
                     build_financial_effect_id(
                         network=NETWORK, genesis_hash=GENESIS,
                         tx_signature=signature,
                         instruction_index=receipt.instruction_index,
                         destination=receipt.creator_refund_token_account,
                         mint=MINT) + ":creator_refund", None),
                ):
                    values = (NETWORK, GENESIS, signature, receipt.instruction_index,
                              kind, destination, MINT, effect_id, receipt.work_order_account,
                              receipt.agent_account, receipt.owner_pubkey, amount,
                              receipt.evidence_hash, movement_id)
                    old = self.db.execute("""SELECT effect_id,work_order_account,
                        agent_account,owner_pubkey,amount_base_units,evidence_hash,movement_id
                        FROM ingestion_effects WHERE network=? AND genesis_hash=? AND
                        transaction_signature=? AND instruction_index=? AND effect_kind=? AND
                        destination_account=? AND token_mint=?""", values[:7]).fetchone()
                    if old:
                        duplicate = True
                        if tuple(old) != (effect_id, receipt.work_order_account,
                                          receipt.agent_account, receipt.owner_pubkey,
                                          amount, receipt.evidence_hash, movement_id):
                            raise IngestionIntegrityError("Economic identity has conflicting amount or evidence")
                    else:
                        self.db.execute("""INSERT INTO ingestion_effects
                            (network,genesis_hash,transaction_signature,instruction_index,
                             effect_kind,destination_account,token_mint,effect_id,
                             work_order_account,agent_account,owner_pubkey,amount_base_units,
                             evidence_hash,movement_id,created_at)
                             VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""", values + (now,))
            old_observation = self.db.execute("""SELECT slot,processing_status,evidence_hash,attempt_count
                FROM ingestion_observations WHERE scope_id=? AND signature=?""",
                (scope.scope_id, signature)).fetchone()
            duplicate = duplicate or bool(old_observation and
                                          old_observation[1] != "DISCOVERED")
            evidence_hash = receipt.evidence_hash if receipt else None
            if old_observation and (old_observation[0] != slot or
                    old_observation[1] in ("RECONCILED", "FINALIZED") and
                    (old_observation[1] != status or old_observation[2] != evidence_hash)):
                raise IngestionIntegrityError("Previously observed signature changed")
            self.db.execute("""INSERT INTO ingestion_observations
                (scope_id,signature,slot,processing_status,error_category,attempt_count,
                 event_count,evidence_hash,finalization_lag_seconds,updated_at)
                 VALUES (?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(scope_id,signature) DO UPDATE SET
                processing_status=excluded.processing_status,error_category=excluded.error_category,
                attempt_count=excluded.attempt_count,event_count=excluded.event_count,
                evidence_hash=excluded.evidence_hash,
                finalization_lag_seconds=excluded.finalization_lag_seconds,
                updated_at=excluded.updated_at""",
                (scope.scope_id, signature, slot, status, category,
                 (old_observation[3] if old_observation else 0) + 1,
                 2 if receipt else 0, evidence_hash, lag_seconds, now))
            checkpoint = self.db.execute("""SELECT last_finalized_slot FROM ingestion_checkpoints
                WHERE scope_id=?""", (scope.scope_id,)).fetchone()
            if checkpoint[0] is None or slot >= checkpoint[0]:
                self.db.execute("""UPDATE ingestion_checkpoints SET
                    last_processed_signature=?,last_finalized_slot=?,
                    last_successful_sync=?,checkpoint_status='READY' WHERE scope_id=?""",
                    (signature, slot, now, scope.scope_id))
            self.db.execute("COMMIT")
        except Exception:
            self.db.execute("ROLLBACK")
            raise
        return duplicate

    def _stage_discovered(self, scope: Scope, items: list[dict]) -> None:
        now = int(time.time())
        self.db.execute("BEGIN IMMEDIATE")
        try:
            for item in items:
                self.db.execute("""INSERT OR IGNORE INTO ingestion_observations
                    (scope_id,signature,slot,processing_status,attempt_count,updated_at)
                    VALUES (?,?,?,'DISCOVERED',1,?)""",
                    (scope.scope_id, item["signature"], item["slot"], now))
            self.db.execute("COMMIT")
        except Exception:
            self.db.execute("ROLLBACK")
            raise

    def _log_observation(self, scope: Scope, item: dict, status: str,
                         *, duplicate: bool = False, category: str | None = None) -> None:
        observation = self.db.execute("""SELECT attempt_count,event_count FROM
            ingestion_observations WHERE scope_id=? AND signature=?""",
            (scope.scope_id, item["signature"])).fetchone()
        checkpoint = self.db.execute("""SELECT last_processed_signature,checkpoint_status
            FROM ingestion_checkpoints WHERE scope_id=?""", (scope.scope_id,)).fetchone()
        print(json.dumps({"ingestion_scope": scope.label, "network": NETWORK,
            "slot": item["slot"], "signature": item["signature"],
            "processing_status": status, "attempt_count": observation[0],
            "event_count": observation[1], "duplicate": duplicate,
            "reconciliation_status": status if status == "RECONCILED" else None,
            "error_category": category,
            "checkpoint": {"last_processed_signature": checkpoint[0],
                           "status": checkpoint[1]}}), file=sys.stderr, flush=True)

    def _process(self, scope: Scope, item: dict) -> tuple[str, bool]:
        signature, slot = item["signature"], item["slot"]
        status = self.rpc.get_signature_status(signature)
        if status is None or status.get("confirmationStatus") != "finalized":
            raise PendingFinality("Signature is not finalized")
        if status.get("slot") != slot:
            raise IngestionIntegrityError("Discovery and status slots disagree")
        tx = self.rpc.get_transaction(signature, commitment="finalized")
        if tx is None:
            raise UnavailableHistory("Finalized signature has no retrievable transaction")
        if (tx.get("slot") != slot or
                tx.get("transaction", {}).get("signatures", [None])[0] != signature or
                not isinstance(tx.get("meta"), dict)):
            raise IngestionIntegrityError("Transaction, signature or slot inconsistent")
        if status.get("err") != tx["meta"].get("err"):
            raise IngestionIntegrityError("Transaction and status errors disagree")
        block_time = tx.get("blockTime")
        lag_seconds = max(0, int(time.time()) - block_time) if type(block_time) is int else None
        if tx["meta"]["err"] is not None:
            duplicate = self._store(scope, signature, slot, "UNVERIFIABLE",
                                    category="TRANSACTION_FAILED", lag_seconds=lag_seconds)
            return "UNVERIFIABLE", duplicate
        indices = _settlement_indices(tx, PROGRAM)
        if not indices:
            duplicate = self._store(scope, signature, slot, "FINALIZED", lag_seconds=lag_seconds)
            return "FINALIZED", duplicate
        if len(indices) != 1:
            raise IngestionIntegrityError("Multiple settlement instructions are ambiguous")
        block = self.rpc._call("getBlock", [slot, {"encoding": "json",
            "transactionDetails": "signatures", "rewards": False,
            "maxSupportedTransactionVersion": 0}])
        if not isinstance(block, dict) or signature not in block.get("signatures", []):
            raise IngestionGap("Finalized settlement absent from its block")
        receipt = self.reconciler.verify_settlement_transaction(
            signature, expected_work_order=scope.work_order,
            expected_mint=MINT, require_finalized=True)
        if (receipt.evidence_source != EvidenceSourceKind.LIVE_RPC.value or
                receipt.commitment != "finalized" or receipt.slot != slot or
                receipt.instruction_index != indices[0]):
            raise IngestionIntegrityError("Verified receipt does not match discovered settlement")
        movement, checked = self.reconciler.reconcile_settlement(
            self.ledger, tx_signature=signature, work_order_account=scope.work_order,
            agent_account=receipt.agent_account, owner_pubkey=receipt.owner_pubkey,
            source_kind=EvidenceSourceKind.LIVE_RPC)
        if (movement.status != MovementStatus.RECONCILED or
                checked.evidence_hash != receipt.evidence_hash or
                movement.evidence_hash != receipt.evidence_hash):
            raise IngestionIntegrityError("Ledger and finalized receipt disagree")
        duplicate = self._store(scope, signature, slot, "RECONCILED", receipt, movement,
                                lag_seconds=lag_seconds)
        return "RECONCILED", duplicate

    def sync(self, scope: Scope, *, replay: bool = False, page_size: int = 100,
             max_pages: int = 5, max_signatures: int = 500) -> dict:
        checkpoint = self._checkpoint(scope)
        metrics = {key: 0 for key in ("discovered", "finalized", "reconciled",
                                      "duplicates", "rpc_errors", "gaps", "differences")}
        try:
            if not self._preflight_done:
                preflight(self.rpc)
                self._preflight_done = True
            validate_scope(self.rpc, scope)
        except Exception as exc:
            metrics["rpc_errors" if isinstance(exc, RpcError) else "differences"] += 1
            self._incident(scope, None, None, "PREFLIGHT",
                           f"{type(exc).__name__}: {exc}", "INCOMPLETE")
            return self.report(scope, metrics)
        anchor = None if replay else checkpoint["last_processed_signature"]
        try:
            items = discover(self.rpc, scope, anchor, page_size=page_size,
                             max_pages=max_pages, max_signatures=max_signatures)
        except (IngestionGap, RpcError) as exc:
            metrics["gaps" if isinstance(exc, IngestionGap) else "rpc_errors"] += 1
            self._incident(scope, None, None, type(exc).__name__, str(exc), "INCOMPLETE")
            return self.report(scope, metrics)
        metrics["discovered"] = len(items)
        self._stage_discovered(scope, items)
        for item in items:
            try:
                outcome, duplicate = self._process(scope, item)
                metrics["duplicates"] += int(duplicate)
                if outcome == "RECONCILED":
                    metrics["reconciled"] += 1
                else:
                    metrics["finalized"] += 1
                self._log_observation(scope, item, outcome, duplicate=duplicate)
            except Exception as exc:
                category = ("RPC_ERROR" if isinstance(exc, RpcError) else
                            "GAP" if isinstance(exc, IngestionGap) else
                            "ECONOMIC_DIFFERENCE")
                metrics["rpc_errors" if category == "RPC_ERROR" else
                        "gaps" if category == "GAP" else "differences"] += 1
                observation_status = ("PENDING_FINALITY" if isinstance(exc, PendingFinality)
                    else "UNVERIFIABLE" if isinstance(exc, IngestionIntegrityError)
                    else "INSUFFICIENT_DATA")
                self._incident(scope, item["signature"], item["slot"], category,
                               f"{type(exc).__name__}: {exc}",
                               observation_status=observation_status)
                self._log_observation(scope, item, observation_status, category=category)
                break
        if not items:
            self.db.execute("""UPDATE ingestion_checkpoints SET
                last_successful_sync=?,checkpoint_status='READY' WHERE scope_id=?""",
                (int(time.time()), scope.scope_id))
        return self.report(scope, metrics)

    def report(self, scope: Scope, metrics: dict | None = None) -> dict:
        checkpoint = self.db.execute("SELECT * FROM ingestion_checkpoints WHERE scope_id=?",
                                     (scope.scope_id,)).fetchone()
        observations = self.db.execute("""SELECT signature,slot,processing_status,
            error_category,attempt_count,event_count,evidence_hash,finalization_lag_seconds
            FROM ingestion_observations
            WHERE scope_id=? ORDER BY slot,signature""", (scope.scope_id,)).fetchall()
        lag = self.db.execute("""SELECT max(finalization_lag_seconds)
            FROM ingestion_observations WHERE scope_id=?""", (scope.scope_id,)).fetchone()[0]
        effects = self.db.execute("""SELECT e.effect_kind,e.transaction_signature,
            e.instruction_index,e.destination_account,e.amount_base_units,e.evidence_hash,
            e.movement_id FROM ingestion_effects e JOIN ingestion_observations o
            ON o.signature=e.transaction_signature AND o.scope_id=?
            WHERE e.work_order_account=? ORDER BY e.transaction_signature,e.effect_kind""",
            (scope.scope_id, scope.work_order)).fetchall()
        incidents = self.db.execute("""SELECT signature,slot,error_category,detail,observed_at
            FROM ingestion_incidents WHERE scope_id=? ORDER BY incident_id""",
            (scope.scope_id,)).fetchall()
        return {"scope_id": scope.scope_id, "ingestion_scope": scope.label,
                "network": NETWORK, "genesis_hash": GENESIS, "program_id": PROGRAM,
                "mint": MINT, "checkpoint": dict(checkpoint) if checkpoint else None,
                "metrics": metrics or {},
                "max_finalization_lag_seconds": lag,
                "observations": [dict(row) for row in observations],
                "effects": [dict(row) for row in effects],
                "incidents": [dict(row) for row in incidents]}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("inspect", "backfill", "reconcile", "resume", "report"))
    parser.add_argument("--work-order", action="append", required=True)
    parser.add_argument("--from-slot", type=int, required=True)
    parser.add_argument("--to-slot", type=int)
    parser.add_argument("--page-size", type=int, default=100)
    parser.add_argument("--max-pages", type=int, default=5)
    parser.add_argument("--max-signatures", type=int, default=500)
    parser.add_argument("--db", type=Path, default=ROOT / "target/con37/devnet-ledger.sqlite")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    scopes = [Scope(work_order, args.from_slot, args.to_slot)
              for work_order in args.work_order]
    if len(scopes) != len({scope.scope_id for scope in scopes}):
        parser.error("Repeated WorkOrder scope")
    if args.mode == "inspect":
        rpc = SolanaRpcClient(RPC_URL, timeout=20, min_interval=0.3)
        identity = preflight(rpc)
        previews = []
        for scope in scopes:
            validate_scope(rpc, scope)
            previews.append({"scope": scope.label,
                "signatures": discover(rpc, scope, None, page_size=args.page_size,
                    max_pages=args.max_pages, max_signatures=args.max_signatures)})
        result = {"identity": identity, "scopes": previews}
    else:
        if args.mode == "report":
            if not args.db.is_file():
                parser.error("Report database does not exist")
            db = sqlite3.connect(args.db.resolve().as_uri() + "?mode=ro", uri=True)
            db.row_factory = sqlite3.Row
            try:
                ingestor = object.__new__(DevnetIngestor)
                ingestor.db = db
                result = {"scopes": [ingestor.report(scope) for scope in scopes]}
            finally:
                db.close()
        else:
            ingestor = DevnetIngestor(args.db)
            try:
                result = {"scopes": [ingestor.sync(scope,
                    replay=args.mode in ("backfill", "reconcile"),
                    page_size=args.page_size, max_pages=args.max_pages,
                    max_signatures=args.max_signatures) for scope in scopes]}
            finally:
                ingestor.close()
    rendered = json.dumps(result, sort_keys=True, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered)
    print(rendered, end="")


if __name__ == "__main__":
    main()
