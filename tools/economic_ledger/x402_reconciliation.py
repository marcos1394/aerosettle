"""CON-45: immutable x402 evidence journal in the Economic Ledger.

Only signed CON-44 sandbox receipts can be imported. There is deliberately no
financial posting API until CON-96 supplies independently verified SVM evidence.
"""
from __future__ import annotations

import json
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any, Callable

from tools.x402.common import Context, NETWORK, SandboxError, amount, digest, local_url, pubkey
from tools.x402.facilitator import verify_receipt
from tools.discovery.agent_discovery import b58decode
from .ledger import EconomicLedger
from .spl_reconciler import SolanaRpcClient

OFFICIAL_DEVNET_RPC = "https://api.devnet.solana.com"


class X402IntegrityError(ValueError):
    """A receipt, identity, stored row, or economic effect conflicts with prior evidence."""


def canonical_effect_id(*, network: str, genesis_hash: str, payment_id: str,
                        transaction_signature: str, instruction_index: int,
                        effect_type: str, agent_account: str, asset: str) -> str:
    """Reserved identity for a future CON-96 verified effect; never for a sandbox row."""
    if (not transaction_signature or type(instruction_index) is not int or instruction_index < 0 or
            not payment_id or not effect_type or network != NETWORK):
        raise X402IntegrityError("INVALID_EFFECT_IDENTITY")
    for key in (genesis_hash, agent_account, asset):
        pubkey(key)
    return "xe_" + digest([network, genesis_hash, payment_id, transaction_signature,
                            instruction_index, effect_type, agent_account, asset])


class X402EconomicStore:
    def __init__(self, ledger: EconomicLedger, context: Context,
                 facilitator_pubkey: str, agent_supplier: Callable[[str], dict | None]):
        if type(ledger) is not EconomicLedger or type(context) is not Context:
            raise X402IntegrityError("UNTRUSTED_LEDGER_OR_CONTEXT")
        self.ledger, self.context = ledger, context
        self.facilitator_pubkey = pubkey(facilitator_pubkey)
        self.agent_supplier = agent_supplier
        self._lock = threading.RLock()
        self._owns_connection = ledger.db_path is not None
        self.db = (sqlite3.connect(str(ledger.db_path), isolation_level=None,
                                   check_same_thread=False, timeout=15)
                   if self._owns_connection else ledger._conn)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA foreign_keys=ON")
        self.db.execute("PRAGMA busy_timeout=10000")

    def close(self) -> None:
        if self._owns_connection:
            self.db.close()

    def _agent(self, account: str) -> dict:
        try:
            agent = self.agent_supplier(account)
        except Exception as exc:
            raise X402IntegrityError("AGENT_IDENTITY_UNAVAILABLE") from exc
        if (not isinstance(agent, dict) or agent.get("agent_account") != account or
                not isinstance(agent.get("agent_id"), str) or not agent["agent_id"] or
                not isinstance(agent.get("owner"), str) or
                agent.get("network") != "solana:devnet" or
                agent.get("genesis_hash") != self.context.genesis_hash or
                agent.get("program_id") != self.context.program_id):
            raise X402IntegrityError("AGENT_IDENTITY_MISMATCH")
        pubkey(account); pubkey(agent["owner"])
        return agent

    @staticmethod
    def _check_row(row: sqlite3.Row) -> dict:
        data = dict(row)
        saved_hash = data.pop("record_hash")
        if digest(data) != saved_hash:
            raise X402IntegrityError("STORED_RECEIPT_INTEGRITY_CONFLICT")
        data["record_hash"] = saved_hash
        try:
            receipt_hash = digest(json.loads(data["receipt_json"]))
        except Exception as exc:
            raise X402IntegrityError("STORED_RECEIPT_INTEGRITY_CONFLICT") from exc
        if receipt_hash != data["receipt_hash"]:
            raise X402IntegrityError("STORED_RECEIPT_INTEGRITY_CONFLICT")
        return data

    @staticmethod
    def _event(payment_id: str, event_type: str, status: str,
               detail_code: str, created_at: int) -> dict:
        base = {"schema_version": 1,
                "event_id": "xev_" + digest([payment_id, event_type, detail_code])[:40],
                "payment_id": payment_id, "event_type": event_type,
                "status": status, "detail_code": detail_code, "created_at": created_at}
        return {**base, "event_hash": digest(base)}

    def _insert_event(self, event: dict) -> None:
        if event["status"] not in {"SANDBOX_SIMULATION", "PENDING", "REJECTED", "INSUFFICIENT_DATA"}:
            raise X402IntegrityError("UNVERIFIED_EVENT_STATUS")
        prior = self.db.execute("SELECT * FROM x402_events WHERE event_id=?",
                                (event["event_id"],)).fetchone()
        if prior:
            old = dict(prior)
            if (old["event_hash"] != digest({k: v for k, v in old.items() if k != "event_hash"}) or
                    any(old[key] != event[key] for key in
                        ("schema_version", "event_id", "payment_id", "event_type", "status", "detail_code"))):
                raise X402IntegrityError("EVENT_INTEGRITY_CONFLICT")
            return
        self.db.execute("INSERT INTO x402_events (schema_version,event_id,payment_id,event_type,status,detail_code,event_hash,created_at) "
                        "VALUES (:schema_version,:event_id,:payment_id,:event_type,:status,:detail_code,:event_hash,:created_at)", event)

    def import_sandbox_receipt(self, receipt: dict) -> tuple[dict, bool]:
        """Verify an authentic CON-44 receipt, then record audit evidence only.

        The receipt is checked against an independently configured facilitator key,
        pinned network/mint, and *current* agent/owner identities before dedupe.
        """
        if not isinstance(receipt, dict):
            raise X402IntegrityError("INVALID_RECEIPT")
        try:
            required_keys = ("payment_id", "receipt_id", "resource_id", "resource_url",
                "client_agent_account", "provider_agent_account", "payer", "recipient",
                "network", "genesis_hash", "program_id", "asset", "amount_base_units_str",
                "payment_requirements_hash", "payment_payload_hash", "facilitator_id",
                "created_at", "evidence_source", "settlement_status", "facilitator_signature")
            if any(key not in receipt for key in required_keys):
                raise X402IntegrityError("INVALID_RECEIPT")
            if (receipt["network"] != NETWORK or receipt["genesis_hash"] != self.context.genesis_hash or
                    receipt["program_id"] != self.context.program_id or
                    receipt["asset"] != self.context.asset or
                    receipt["facilitator_id"] != "conatus-local-sandbox" or
                    type(receipt["created_at"]) is not int):
                raise X402IntegrityError("UNTRUSTED_RECEIPT_CONTEXT")
            local_url(receipt["resource_url"], "/premium-resource")
            amount(receipt["amount_base_units_str"])
            client = self._agent(receipt["client_agent_account"])
            provider = self._agent(receipt["provider_agent_account"])
            if (client["owner"] != receipt["payer"] or provider["owner"] != receipt["recipient"] or
                    client["agent_account"] == provider["agent_account"]):
                raise X402IntegrityError("AGENT_OWNER_MISMATCH")
            terms = {"paymentId": receipt["payment_id"], "resourceId": receipt["resource_id"],
                "resourceUrl": receipt["resource_url"],
                "clientAgentAccount": receipt["client_agent_account"],
                "providerAgentAccount": receipt["provider_agent_account"],
                "payTo": receipt["recipient"], "network": receipt["network"],
                "genesisHash": receipt["genesis_hash"], "programId": receipt["program_id"],
                "asset": receipt["asset"], "amount": receipt["amount_base_units_str"],
                "requirementsHash": receipt["payment_requirements_hash"],
                "facilitatorId": receipt["facilitator_id"],
                "expiresAt": receipt["created_at"] + 60}
            verify_receipt(receipt, self.facilitator_pubkey, terms,
                           receipt["payment_payload_hash"])
            record = {"schema_version": 1, "payment_id": receipt["payment_id"],
                "receipt_id": receipt["receipt_id"],
                "requirements_hash": receipt["payment_requirements_hash"],
                "payload_hash": receipt["payment_payload_hash"],
                "receipt_hash": digest(receipt),
                "receipt_json": json.dumps(receipt, sort_keys=True, separators=(",", ":")),
                "facilitator_pubkey": self.facilitator_pubkey,
                "facilitator_id": receipt["facilitator_id"],
                "resource_id": receipt["resource_id"], "resource_url": receipt["resource_url"],
                "client_agent_account": client["agent_account"], "client_agent_id": client["agent_id"],
                "client_owner_pubkey": client["owner"],
                "provider_agent_account": provider["agent_account"],
                "provider_agent_id": provider["agent_id"],
                "provider_owner_pubkey": provider["owner"],
                "payer": receipt["payer"], "recipient": receipt["recipient"],
                "network": NETWORK, "genesis_hash": self.context.genesis_hash,
                "program_id": self.context.program_id, "asset": self.context.asset,
                "token_program": self.context.token_program, "decimals": self.context.decimals,
                "amount_base_units": receipt["amount_base_units_str"],
                "provenance": "SANDBOX_SIMULATION", "finality": "UNVERIFIED",
                "reconciliation_status": "INSUFFICIENT_DATA",
                "transaction_signature": None, "instruction_index": None,
                "created_at": receipt["created_at"]}
        except (SandboxError, TypeError, ValueError, KeyError) as exc:
            if isinstance(exc, X402IntegrityError):
                raise
            raise X402IntegrityError("INVALID_OR_UNTRUSTED_RECEIPT") from exc
        row = {**record, "record_hash": digest(record)}
        with self._lock:
            self.db.execute("BEGIN IMMEDIATE")
            try:
                collisions = self.db.execute("SELECT * FROM x402_payments WHERE payment_id=? OR receipt_id=? "
                    "OR requirements_hash=? OR payload_hash=?",
                    (row["payment_id"], row["receipt_id"], row["requirements_hash"],
                     row["payload_hash"])).fetchall()
                if collisions:
                    if len(collisions) != 1 or self._check_row(collisions[0]) != row:
                        raise X402IntegrityError("PAYMENT_IDENTITY_CONFLICT")
                    self._insert_event(self._event(row["payment_id"], "DUPLICATE_RECEIVED",
                        "SANDBOX_SIMULATION", "EXACT_RETRY", int(time.time())))
                    inserted = False
                else:
                    columns = list(row)
                    self.db.execute(f"INSERT INTO x402_payments ({','.join(columns)}) "
                                    f"VALUES ({','.join('?' for _ in columns)})",
                                    tuple(row[key] for key in columns))
                    self._insert_event(self._event(row["payment_id"], "RECEIPT_IMPORTED",
                        "SANDBOX_SIMULATION", "SIGNED_SANDBOX_RECEIPT", int(time.time())))
                    inserted = True
                self.db.execute("COMMIT")
                return row, inserted
            except sqlite3.IntegrityError as exc:
                self.db.execute("ROLLBACK")
                raise X402IntegrityError("PAYMENT_IDENTITY_CONFLICT") from exc
            except Exception:
                self.db.execute("ROLLBACK")
                raise

    def _authorized_row(self, payment_id: str, agent_account: str, owner_pubkey: str) -> dict:
        agent = self._agent(agent_account)
        if agent["owner"] != owner_pubkey:
            raise X402IntegrityError("AGENT_IDENTITY_MISMATCH")
        row = self.db.execute("SELECT * FROM x402_payments WHERE payment_id=? AND "
            "((client_agent_account=? AND client_owner_pubkey=? AND client_agent_id=?) OR "
            "(provider_agent_account=? AND provider_owner_pubkey=? AND provider_agent_id=?))",
            (payment_id, agent_account, owner_pubkey, agent["agent_id"],
             agent_account, owner_pubkey, agent["agent_id"])).fetchone()
        if row is None:
            raise X402IntegrityError("PAYMENT_NOT_FOUND")
        checked = self._check_row(row)
        self.import_sandbox_receipt_read_only(checked)
        return checked

    def import_sandbox_receipt_read_only(self, row: dict) -> None:
        """Recheck stored signature and current identities without mutating audit state."""
        receipt = json.loads(row["receipt_json"])
        if row["facilitator_pubkey"] != self.facilitator_pubkey:
            raise X402IntegrityError("FACILITATOR_IDENTITY_CHANGED")
        if (row["schema_version"] != 1 or
                row["network"] != NETWORK or row["genesis_hash"] != self.context.genesis_hash or
                row["program_id"] != self.context.program_id or row["asset"] != self.context.asset or
                row["token_program"] != self.context.token_program or
                row["decimals"] != self.context.decimals or
                row["provenance"] != "SANDBOX_SIMULATION" or
                row["finality"] != "UNVERIFIED" or
                row["reconciliation_status"] != "INSUFFICIENT_DATA" or
                row["transaction_signature"] is not None or row["instruction_index"] is not None):
            raise X402IntegrityError("STORED_RECEIPT_CONTEXT_CONFLICT")
        mapping = {"payment_id": "payment_id", "receipt_id": "receipt_id",
            "requirements_hash": "payment_requirements_hash",
            "payload_hash": "payment_payload_hash", "facilitator_id": "facilitator_id",
            "resource_id": "resource_id", "resource_url": "resource_url",
            "client_agent_account": "client_agent_account",
            "provider_agent_account": "provider_agent_account", "payer": "payer",
            "recipient": "recipient", "network": "network", "genesis_hash": "genesis_hash",
            "program_id": "program_id", "asset": "asset",
            "amount_base_units": "amount_base_units_str", "created_at": "created_at"}
        if any(row[column] != receipt.get(field) for column, field in mapping.items()):
            raise X402IntegrityError("STORED_RECEIPT_CONTEXT_CONFLICT")
        for account_key, owner_key, id_key in (("client_agent_account", "client_owner_pubkey", "client_agent_id"),
                                               ("provider_agent_account", "provider_owner_pubkey", "provider_agent_id")):
            agent = self._agent(row[account_key])
            if (agent["owner"], agent["agent_id"]) != (row[owner_key], row[id_key]):
                raise X402IntegrityError("AGENT_IDENTITY_MISMATCH")
        if (row["payer"] != row["client_owner_pubkey"] or
                row["recipient"] != row["provider_owner_pubkey"]):
            raise X402IntegrityError("STORED_RECEIPT_CONTEXT_CONFLICT")
        terms = {"paymentId": row["payment_id"], "resourceId": row["resource_id"],
            "resourceUrl": row["resource_url"], "clientAgentAccount": row["client_agent_account"],
            "providerAgentAccount": row["provider_agent_account"], "payTo": row["recipient"],
            "network": row["network"], "genesisHash": row["genesis_hash"],
            "programId": row["program_id"], "asset": row["asset"],
            "amount": row["amount_base_units"], "requirementsHash": row["requirements_hash"],
            "facilitatorId": row["facilitator_id"], "expiresAt": row["created_at"] + 60}
        try:
            verify_receipt(receipt, self.facilitator_pubkey, terms, row["payload_hash"])
        except SandboxError as exc:
            raise X402IntegrityError("STORED_RECEIPT_SIGNATURE_INVALID") from exc

    def get(self, payment_id: str, agent_account: str, owner_pubkey: str) -> dict:
        with self._lock:
            return self._authorized_row(payment_id, agent_account, owner_pubkey)

    def events(self, payment_id: str, agent_account: str, owner_pubkey: str) -> list[dict]:
        with self._lock:
            self._authorized_row(payment_id, agent_account, owner_pubkey)
            rows = self.db.execute("SELECT * FROM x402_events WHERE payment_id=? ORDER BY created_at,event_id",
                                   (payment_id,)).fetchall()
            result = []
            for row in rows:
                item = dict(row)
                if (item["schema_version"] != 1 or
                        item["status"] not in {"SANDBOX_SIMULATION", "PENDING", "REJECTED", "INSUFFICIENT_DATA"} or
                        item["event_hash"] != digest({k: v for k, v in item.items() if k != "event_hash"})):
                    raise X402IntegrityError("EVENT_INTEGRITY_CONFLICT")
                result.append(item)
            return result

    def workorder_collision(self, transaction_signature: str, instruction_index: int) -> bool:
        """Read-only cross-check for future CON-96 correlation; does not post a movement."""
        if not transaction_signature or type(instruction_index) is not int or instruction_index < 0:
            raise X402IntegrityError("INVALID_EFFECT_IDENTITY")
        return bool(self.db.execute("SELECT 1 FROM ingestion_effects WHERE network=? AND genesis_hash=? "
            "AND transaction_signature=? AND instruction_index=? UNION SELECT 1 FROM economic_movements "
            "WHERE network IN ('devnet','solana:devnet',?) AND genesis_hash=? AND tx_signature=? "
            "AND work_order_account IS NOT NULL LIMIT 1",
            (NETWORK, self.context.genesis_hash, transaction_signature, instruction_index,
             NETWORK, self.context.genesis_hash, transaction_signature)).fetchone())

    def inspect_rpc(self, payment_id: str, agent_account: str, owner_pubkey: str,
                    transaction_signature: str | None, rpc: Any = None) -> dict:
        """Read-only CON-96 seam: no RPC assertion promotes a sandbox receipt.

        Strictly inspect actual Devnet RPC if configured. Even a finalized transfer
        remains uncorrelated until CON-96 provides signed SVM exact evidence.
        """
        row = self.get(payment_id, agent_account, owner_pubkey)
        outcome = {"status": "INSUFFICIENT_DATA", "finality": "UNVERIFIED",
                   "reconciliation_status": "INSUFFICIENT_DATA",
                   "transaction_signature": transaction_signature,
                   "reason": "CON96_EVIDENCE_UNAVAILABLE"}
        if not transaction_signature:
            return outcome
        try:
            b58decode(transaction_signature, 64)  # format check only; never proof of transfer
        except Exception:
            outcome["reason"] = "INVALID_SIGNATURE_FORMAT"
            return outcome
        if type(rpc) is not SolanaRpcClient or rpc.rpc_url != OFFICIAL_DEVNET_RPC:
            outcome["reason"] = "UNTRUSTED_RPC"
            return outcome
        try:
            if rpc.get_genesis_hash() != self.context.genesis_hash:
                outcome["reason"] = "GENESIS_MISMATCH"
                return outcome
            status = rpc.get_signature_status(transaction_signature)
            if not status:
                outcome["reason"] = "SIGNATURE_NOT_FOUND"
                return outcome
            if status.get("err") is not None:
                outcome["status"] = "REJECTED"
                outcome["reason"] = "TRANSACTION_REJECTED"
                return outcome
            if status.get("confirmationStatus") != "finalized":
                outcome["status"] = "PENDING"
                outcome["reason"] = "AWAITING_FINALITY"
                return outcome
            tx = rpc.get_transaction(transaction_signature, commitment="finalized")
            if not isinstance(tx, dict):
                outcome["reason"] = "TRANSACTION_UNAVAILABLE"
                return outcome
            meta = tx.get("meta")
            if (not isinstance(meta, dict) or meta.get("err") is not None or
                    type(tx.get("slot")) is not int or tx["slot"] != status.get("slot") or
                    type(meta.get("fee")) is not int or meta["fee"] < 0 or
                    not isinstance(meta.get("preTokenBalances"), list) or
                    not isinstance(meta.get("postTokenBalances"), list)):
                outcome["reason"] = "TRANSACTION_INTEGRITY_INCOMPLETE"
                return outcome
            signatures = ((tx.get("transaction") or {}).get("signatures") or [])
            if transaction_signature not in signatures:
                outcome["reason"] = "TRANSACTION_SIGNATURE_MISMATCH"
                return outcome
            message = ((tx.get("transaction") or {}).get("message") or {})
            keys = message.get("accountKeys")
            if not isinstance(keys, list):
                outcome["reason"] = "TRANSACTION_ACCOUNTS_MISSING"
                return outcome
            keys = [key if isinstance(key, str) else key.get("pubkey")
                    if isinstance(key, dict) else None for key in keys]
            if any(not isinstance(key, str) for key in keys):
                outcome["reason"] = "TRANSACTION_ACCOUNTS_MISSING"
                return outcome
            balances = {}
            for stage, records in (("pre", meta["preTokenBalances"]),
                                   ("post", meta["postTokenBalances"])):
                for item in records:
                    if not isinstance(item, dict):
                        outcome["reason"] = "INVALID_TOKEN_BALANCES"
                        return outcome
                    index = item.get("accountIndex")
                    if type(index) is not int or index < 0 or index >= len(keys):
                        outcome["reason"] = "INVALID_TOKEN_BALANCES"
                        return outcome
                    if item.get("mint") != row["asset"]:
                        continue
                    ui = item.get("uiTokenAmount") or {}
                    raw = ui.get("amount")
                    if (item.get("programId") != row["token_program"] or
                            type(ui.get("decimals")) is not int or
                            ui["decimals"] != row["decimals"] or
                            not isinstance(raw, str) or not raw.isdigit() or
                            not isinstance(item.get("owner"), str)):
                        outcome["reason"] = "TOKEN_CONTEXT_MISMATCH"
                        return outcome
                    balances.setdefault(index, {"owner": item["owner"], "pre": 0, "post": 0})
                    if balances[index]["owner"] != item["owner"]:
                        outcome["reason"] = "TOKEN_OWNER_MISMATCH"
                        return outcome
                    balances[index][stage] = int(raw)
            payer_delta = sum(v["post"] - v["pre"] for v in balances.values()
                              if v["owner"] == row["payer"])
            recipient_delta = sum(v["post"] - v["pre"] for v in balances.values()
                                  if v["owner"] == row["recipient"])
            if payer_delta != -int(row["amount_base_units"]) or recipient_delta != int(row["amount_base_units"]):
                outcome["reason"] = "TOKEN_BALANCE_DELTA_MISMATCH"
                return outcome
            for index, balance in balances.items():
                if balance["pre"] == balance["post"]:
                    continue
                account = rpc.get_account_info(keys[index], commitment="finalized")
                if not isinstance(account, dict) or account.get("owner") != row["token_program"]:
                    outcome["reason"] = "TOKEN_ACCOUNT_PROGRAM_MISMATCH"
                    return outcome
            outcome["reason"] = "CON96_RECEIPT_AND_SPL_EFFECT_CORRELATION_REQUIRED"
            return outcome
        except Exception:
            outcome["reason"] = "RPC_UNAVAILABLE_OR_HISTORY_PRUNED"
            return outcome

    def inspect_and_record(self, payment_id: str, agent_account: str,
                           owner_pubkey: str, transaction_signature: str | None,
                           rpc: Any = None) -> dict:
        """Persist a fail-closed inspection and difference; never post a financial effect."""
        outcome = self.inspect_rpc(payment_id, agent_account, owner_pubkey,
                                   transaction_signature, rpc)
        with self._lock:
            self.db.execute("BEGIN IMMEDIATE")
            try:
                for kind in ("RPC_EVIDENCE_CHECKED", "RECONCILIATION_DIFFERENCE"):
                    self._insert_event(self._event(payment_id, kind,
                        outcome["status"] if kind == "RPC_EVIDENCE_CHECKED" else "INSUFFICIENT_DATA",
                        outcome["reason"], int(time.time())))
                self.db.execute("COMMIT")
            except Exception:
                self.db.execute("ROLLBACK")
                raise
        return outcome

    def agent_view(self, agent_account: str, owner_pubkey: str) -> dict:
        """Exact integer audit totals. Realized income, expense and profit remain zero."""
        agent = self._agent(agent_account)
        if agent["owner"] != owner_pubkey:
            raise X402IntegrityError("AGENT_IDENTITY_MISMATCH")
        with self._lock:
            stale = self.db.execute("SELECT 1 FROM x402_payments WHERE "
                "(client_agent_account=? AND (client_owner_pubkey<>? OR client_agent_id<>?)) OR "
                "(provider_agent_account=? AND (provider_owner_pubkey<>? OR provider_agent_id<>?)) LIMIT 1",
                (agent_account, owner_pubkey, agent["agent_id"],
                 agent_account, owner_pubkey, agent["agent_id"])).fetchone()
            if stale:
                raise X402IntegrityError("AGENT_IDENTITY_MISMATCH")
            rows = self.db.execute("SELECT * FROM x402_payments WHERE "
                "(client_agent_account=? AND client_owner_pubkey=? AND client_agent_id=?) OR "
                "(provider_agent_account=? AND provider_owner_pubkey=? AND provider_agent_id=?) "
                "ORDER BY created_at,payment_id",
                (agent_account, owner_pubkey, agent["agent_id"],
                 agent_account, owner_pubkey, agent["agent_id"])).fetchall()
            checked = [self._check_row(row) for row in rows]
            for row in checked:
                self.import_sandbox_receipt_read_only(row)
            received = sum(int(row["amount_base_units"]) for row in checked
                           if row["provider_agent_account"] == agent_account)
            paid = sum(int(row["amount_base_units"]) for row in checked
                       if row["client_agent_account"] == agent_account)
            return {"agent_account": agent_account, "agent_id": agent["agent_id"],
                "owner_pubkey": owner_pubkey, "network": NETWORK,
                "genesis_hash": self.context.genesis_hash, "asset": self.context.asset,
                "token_program": self.context.token_program,
                "sandbox_receipts": len(checked),
                "sandbox_receivable_base_units_str": str(received),
                "sandbox_payable_base_units_str": str(paid),
                "pending_events": len(checked),
                "realized_revenue_base_units_str": "0",
                "realized_expense_base_units_str": "0",
                "verified_network_fee_lamports_str": "0",
                "verified_facilitator_fee_base_units_str": "0",
                "verified_refund_base_units_str": "0",
                "realized_profit_base_units_str": None,
                "reconciliation_status": "INSUFFICIENT_DATA",
                "difference_code": "CON96_EVIDENCE_UNAVAILABLE" if checked else None}
