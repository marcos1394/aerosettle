"""Read adapters for verified Devnet discovery and explicitly offline fixtures."""
from __future__ import annotations

import copy
import json
from pathlib import Path

from tools.a2a.catalog import CardCatalog
from tools.a2a.trust import (APPROVED_IDL, GENESIS_HASH, NETWORK, PROGRAM_ID,
                              RPC_URL, verify_approved_identity, verify_live_program)
from tools.deployment.devnet import Rpc
from tools.discovery.agent_discovery import Idl, discover
from tools.economic_ledger.spl_reconciler import SplSettlementReconciler
from .security import Denied


class FixtureBackend:
    """Offline test data only. Fixture provenance cannot become LIVE_RPC."""
    def __init__(self, path: Path):
        payload = json.loads(Path(path).read_text())
        if payload.get("evidence_source") != "OFFLINE_FIXTURE":
            raise Denied("UNTRUSTED_SOURCE")
        self.data = payload

    def snapshot(self) -> dict:
        return copy.deepcopy(self.data)

    def card(self, card_id: str) -> dict | None:
        return next((copy.deepcopy(c) for c in self.data.get("cards", [])
                     if c.get("card_id") == card_id), None)

    def evidence(self, order: dict) -> dict | None:
        item = next((copy.deepcopy(e) for e in self.data.get("evidence", [])
                     if e.get("work_order_pda") == order.get("work_order_account")), None)
        if item and (item.get("evidence_source") != "OFFLINE_FIXTURE" or
                     item.get("verification_status") == "VERIFIED" or
                     item.get("commitment") == "finalized"):
            raise Denied("UNTRUSTED_EVIDENCE")
        return item


class DevnetBackend:
    """Pinned CON-35 identity; every read rechecks the live program and genesis."""
    def __init__(self, catalog: CardCatalog | None = None,
                 access_index: Path | None = None):
        self.catalog = catalog
        self.access_index = Path(access_index) if access_index else None
        self.idl = Idl(verify_approved_identity(APPROVED_IDL, RPC_URL))
        self.rpc = Rpc(RPC_URL)

    def snapshot(self) -> dict:
        verify_approved_identity(APPROVED_IDL, RPC_URL)
        if self.rpc.call("getGenesisHash", []) != GENESIS_HASH:
            raise Denied("INVALID_NETWORK")
        verify_live_program(self.rpc)
        value = discover(self.rpc, self.idl, commitment="finalized")
        verify_approved_identity(APPROVED_IDL, RPC_URL)
        verify_live_program(self.rpc)
        if (self.rpc.call("getGenesisHash", []) != GENESIS_HASH or
                value.get("program_id") != PROGRAM_ID or
                value.get("commitment") != "finalized"):
            raise Denied("INVALID_NETWORK")
        access = {}
        if self.access_index:
            try:
                payload = json.loads(self.access_index.read_text())
                if (payload.get("network") != NETWORK or
                        payload.get("genesis_hash") != GENESIS_HASH or
                        payload.get("program_id") != PROGRAM_ID or
                        not isinstance(payload.get("access"), dict)):
                    raise Denied("UNTRUSTED_ACCESS_INDEX")
                by_id = {o["work_order_account"]: o for o in value["work_orders"]}
                for oid, binding in payload["access"].items():
                    order = by_id.get(oid)
                    if not order or not isinstance(binding, dict) or \
                            binding.get("owner") != order["creator"] or \
                            not all(isinstance(binding.get(k), str) and binding[k]
                                    for k in ("tenant_id", "organization_id")):
                        raise Denied("UNTRUSTED_ACCESS_INDEX")
                    access[oid] = {k: binding[k] for k in
                                   ("owner", "tenant_id", "organization_id")}
                    if binding.get("settlement_signature"):
                        if order["status"] != "Settled":
                            raise Denied("UNTRUSTED_ACCESS_INDEX")
                        order["settlement_signature"] = binding["settlement_signature"]
            except (OSError, ValueError, TypeError, KeyError) as exc:
                raise Denied("UNTRUSTED_ACCESS_INDEX") from exc
        return {**value, "network": NETWORK, "genesis_hash": GENESIS_HASH,
                "evidence_source": "LIVE_DEVNET_READ_ONLY", "access": access}

    def card(self, card_id: str) -> dict | None:
        self.snapshot()
        return self.catalog.get(card_id) if self.catalog else None

    def evidence(self, order: dict) -> dict | None:
        signature = order.get("settlement_signature")
        if not signature:
            return None
        self.snapshot()
        receipt = SplSettlementReconciler(
            rpc_url=RPC_URL, expected_network=NETWORK,
            expected_genesis_hash=GENESIS_HASH,
            expected_program_id=PROGRAM_ID).verify_settlement_transaction(
                signature, expected_work_order=order["work_order_account"])
        result = receipt.to_dict()
        if (result.get("evidence_source") != "LIVE_RPC" or
                result.get("commitment") != "finalized"):
            raise Denied("UNTRUSTED_EVIDENCE")
        return {"network": result["network"], "genesis_hash": result["genesis_hash"],
                "program_id": result["program_id"],
                "work_order_pda": result["work_order_account"],
                "transaction_signature": result["tx_signature"], "slot": result["slot"],
                "commitment": result["commitment"],
                "evidence_source": "LIVE_RPC", "verification_status": "VERIFIED",
                "evidence_hash": result["evidence_hash"]}
