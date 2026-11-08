"""CON-45 reproducible demo using a fresh signed CON-44 HTTP sandbox receipt."""
from __future__ import annotations

import json
import tempfile
from pathlib import Path

from tools.x402.common import Context
from tools.x402.demo import FINANCIAL_TABLES, fixtures, run_demo
from .ledger import EconomicLedger
from .x402_reconciliation import X402EconomicStore

ROOT = Path(__file__).resolve().parents[2]


def run_reconciliation_demo() -> dict:
    source = run_demo(include_artifacts=True)
    receipt = source["signed_receipt"]
    context = Context.fixture()
    agents = fixtures(context)
    matrix = json.loads((ROOT / "evidence/con36/verified-matrix.json").read_text())
    workorder_signatures = {item["transaction_signature"] for item in matrix["receipts"]}
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "economic-ledger.sqlite"
        ledger = EconomicLedger(path)
        try:
            before = {table: ledger._conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                      for table in FINANCIAL_TABLES}
            store = X402EconomicStore(ledger, context, source["facilitator_pubkey"], agents.get)
            try:
                first, inserted = store.import_sandbox_receipt(receipt)
                second, duplicate = store.import_sandbox_receipt(receipt)
                client_view = store.agent_view(receipt["client_agent_account"], receipt["payer"])
                provider_view = store.agent_view(receipt["provider_agent_account"], receipt["recipient"])
                evidence = store.inspect_and_record(receipt["payment_id"],
                    receipt["client_agent_account"], receipt["payer"], None)
                event_count = len(store.events(receipt["payment_id"],
                                               receipt["client_agent_account"], receipt["payer"]))
                effect_count = store.db.execute("SELECT COUNT(*) FROM x402_verified_effects").fetchone()[0]
            finally:
                store.close()
        finally:
            ledger.close()
        ledger = EconomicLedger(path)
        try:
            store = X402EconomicStore(ledger, context, source["facilitator_pubkey"], agents.get)
            try:
                recovered = store.get(receipt["payment_id"], receipt["client_agent_account"],
                                      receipt["payer"])
                history = store.events(receipt["payment_id"], receipt["client_agent_account"],
                                       receipt["payer"])
                after = {table: ledger._conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                         for table in FINANCIAL_TABLES}
            finally:
                store.close()
        finally:
            ledger.close()
    report = {
        "X402_SANDBOX_IMPORTED": inserted and first["provenance"] == "SANDBOX_SIMULATION",
        "RECEIPT_VERIFIED": first["facilitator_pubkey"] == source["facilitator_pubkey"],
        "IDEMPOTENCY_VERIFIED": not duplicate and first == second,
        "SQLITE_RESTART_VERIFIED": recovered == first and len(history) == event_count,
        "WORKORDER_DOUBLE_COUNT": receipt["transaction_signature"] in workorder_signatures,
        "WORKORDER_EVIDENCE_COMPARED": len(workorder_signatures),
        "SANDBOX_RECOGNIZED_REVENUE": int(provider_view["realized_revenue_base_units_str"]),
        "LIVE_RPC_X402_SETTLEMENT_VERIFIED": False,
        "INSUFFICIENT_DATA_HANDLED": evidence["status"] == "INSUFFICIENT_DATA",
        "ONCHAIN_TRANSACTIONS_SENT": 0,
        "FINANCIAL_TABLES_UNCHANGED": before == after and effect_count == 0,
        "network": first["network"], "genesis_hash": first["genesis_hash"],
        "asset": first["asset"], "receipt_id": first["receipt_id"],
        "payment_id": first["payment_id"],
        "sandbox_receivable_base_units_str": provider_view["sandbox_receivable_base_units_str"],
        "sandbox_payable_base_units_str": client_view["sandbox_payable_base_units_str"],
        "difference_report": [{"payment_id": first["payment_id"],
            "code": evidence["reason"], "amount_base_units_str": first["amount_base_units"],
            "realized_revenue_base_units_str": "0", "realized_expense_base_units_str": "0"}],
        "provenance": "OFFLINE_FIXTURE"}
    assert (report["X402_SANDBOX_IMPORTED"] and report["RECEIPT_VERIFIED"] and
            report["IDEMPOTENCY_VERIFIED"] and report["SQLITE_RESTART_VERIFIED"] and
            not report["WORKORDER_DOUBLE_COUNT"] and report["WORKORDER_EVIDENCE_COMPARED"] > 0 and
            report["SANDBOX_RECOGNIZED_REVENUE"] == 0 and report["INSUFFICIENT_DATA_HANDLED"] and
            report["FINANCIAL_TABLES_UNCHANGED"])
    return report


if __name__ == "__main__":
    print(json.dumps(run_reconciliation_demo(), sort_keys=True))
