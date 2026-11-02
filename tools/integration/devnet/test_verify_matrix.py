"""Offline integrity checks for the public CON-36 Devnet evidence inventory."""
from __future__ import annotations

import hashlib
import io
import json
import unittest
from unittest.mock import patch
import urllib.error

from tools.integration.devnet.verify_matrix import EVIDENCE, report_rows
from tools.economic_ledger.spl_reconciler import RpcError, SolanaRpcClient


class MatrixEvidenceTests(unittest.TestCase):
    def test_complete_matrix_and_expected_finalized_rejections(self) -> None:
        rows = report_rows()
        self.assertEqual(len(rows), 7)
        failures = [(scenario["scenario"], event["anchor_error_code"])
                    for scenario, report in rows for event in report["events"]
                    if event["state"] == "FINALIZED_REJECTED"]
        self.assertEqual(failures, [
            ("E2E-01-full", "SettlementNotVerified"),
            ("E2E-04-invalid-shared", "SettlementInvalidCreatorRefund"),
            ("E2E-06-invalid-mint", "InvalidTokenMint"),
            ("E2E-07-wrong-beneficiary", "SettlementInvalidBeneficiary"),
        ])
        self.assertTrue(all(row["state"] == "FINALIZED" for _, report in rows
                            for row in report["events"] if row["phase"] == "settle"))

    def test_transaction_manifests_bind_reported_instructions_and_spending(self) -> None:
        for scenario, report in report_rows():
            for event in report["events"]:
                file = EVIDENCE / event["manifest_file"].removeprefix("evidence/con36/")
                plan = json.loads(file.read_text())
                body = {key: value for key, value in plan.items() if key != "manifest_id"}
                digest = hashlib.sha256(json.dumps(body, separators=(",", ":"),
                                                   ensure_ascii=False).encode()).hexdigest()
                self.assertEqual(plan["manifest_id"], digest)
                self.assertEqual(event["manifest_id"], digest)
                self.assertEqual(plan["work_order_pda"], scenario["work_order_pda"])
                self.assertEqual(plan["phase"], event["phase"])
                self.assertLessEqual(event["fee_lamports"], plan["max_fee_lamports"])
                self.assertLessEqual(plan["max_fee_lamports"], 20_000)
                self.assertEqual(plan["max_payer_debit_lamports"],
                                 plan["max_fee_lamports"] + plan["max_rent_lamports"])

    def test_public_rpc_rate_limit_retries_but_transport_failure_stays_closed(self) -> None:
        rpc = SolanaRpcClient("https://api.devnet.solana.com")
        rate_limit = urllib.error.HTTPError(rpc.rpc_url, 429, "rate limited", {}, None)
        response = io.BytesIO(b'{"jsonrpc":"2.0","result":"devnet-genesis"}')
        with patch("tools.economic_ledger.spl_reconciler.urllib.request.urlopen",
                   side_effect=[rate_limit, response]) as request, \
             patch("tools.economic_ledger.spl_reconciler.time.sleep") as sleep:
            self.assertEqual(rpc.get_genesis_hash(), "devnet-genesis")
            self.assertEqual(request.call_count, 2)
            sleep.assert_called_once()
        with patch("tools.economic_ledger.spl_reconciler.urllib.request.urlopen",
                   side_effect=urllib.error.URLError("offline")) as request:
            with self.assertRaises(RpcError):
                rpc.get_genesis_hash()
            self.assertEqual(request.call_count, 1)


if __name__ == "__main__":
    unittest.main()
