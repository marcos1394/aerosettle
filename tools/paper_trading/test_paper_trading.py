"""CON-31 exact arithmetic, paper isolation, signatures and persistence."""
import concurrent.futures
import hashlib
import os
import tempfile
import time
import unittest
from pathlib import Path

from cryptography.hazmat.primitives.asymmetric import ed25519

from tools.discovery.agent_discovery import b58encode
from tools.economic_ledger.ledger import EconomicLedger
from tools.economic_ledger.test_budget_policies import AGENT, AGENT_RECORD, MINT, MINT_TWO, OTHER, OWNER, SECRET
from tools.paper_trading.providers import DeterministicFixtureProvider, NETWORK_ENABLED
from tools.paper_trading.simulator import PaperError, compare_productive_alternatives, simulate_paper_execution
from tools.paper_trading.store import PaperSimulationStore, paper_simulation_message, verify_paper_signature


def body(**changes):
    value = {"agent_account": AGENT, "agent_id": AGENT_RECORD["agent_id"],
             "owner_pubkey": OWNER, "network": "solana:localnet", "genesis_hash": AGENT,
             "program_id": OTHER, "treasury_token_mint": MINT, "trading_quote_currency": MINT,
             "paper_budget_base_units_str": "1000", "funding_source": "MANUAL_PAPER_ALLOCATION",
             "scenario_id": "paper_base_1", "scenario_kind": "FINANCIAL_SPOT", "scenario": "BASE",
             "instrument_id": "fixture:spot:compute-credit:alpha", "side": "BUY",
             "quantity_base_units_str": "10", "require_full_fill": False, "holding_period_days": 30,
             "productive_alternatives": [], "simulation_timestamp": int(time.time()),
             "nonce": "paper-nonce-00000001", "idempotency_key": "paper-idem-00000001"}
    value.update(changes)
    return value


def signed(value):
    path = f"/v1/agents/{AGENT}/paper-simulations"
    message = paper_simulation_message(value["simulation_timestamp"], AGENT, OWNER, path, value)
    signature = b58encode(ed25519.Ed25519PrivateKey.from_private_bytes(SECRET).sign(message))
    return {"X-Signer-Pubkey": OWNER, "X-Timestamp": str(value["simulation_timestamp"]),
            "X-Signature": signature}


def pure_inputs(value=None):
    request = value or body()
    provider = DeterministicFixtureProvider()
    market = {**provider.get_quote(request["instrument_id"], request),
              **provider.get_liquidity_snapshot(request["instrument_id"], request)}
    costs = provider.get_fee_schedule(request["instrument_id"], request)
    policy = {"max_paper_allocation_base_units_str": "18446744073709551615",
              "max_position_allocation_bps": 10000, "max_single_trade_bps": 10000,
              "max_daily_paper_turnover_bps": 10000, "max_simulated_loss_budget_bps": 10000,
              "allowed_instruments": [request["instrument_id"]],
              "allowed_quote_currencies": [MINT], "max_quote_age_seconds": 300}
    portfolio = {"cash_base_units_str": request["paper_budget_base_units_str"],
                 "position_quantity_base_units_str": "0", "daily_turnover_base_units_str": "0"}
    return request, market, costs, policy, portfolio


class PurePaperTests(unittest.TestCase):
    def test_exact_partial_fill_and_no_negative_budget(self):
        args = pure_inputs()
        result = simulate_paper_execution(*args)
        self.assertEqual(result["fill_status"], "PARTIALLY_FILLED_SIMULATED")
        self.assertEqual(result["filled_quantity_base_units_str"], "9")
        self.assertEqual(result["entry_total_base_units_str"], "914")
        self.assertEqual(result["remaining_paper_budget_base_units_str"], "86")
        self.assertFalse(result["real_capital_authorized"])
        self.assertEqual(result, simulate_paper_execution(*args))
        args[0]["require_full_fill"] = True
        self.assertEqual(simulate_paper_execution(*args)["fill_status"], "REJECTED_SIMULATED")

    def test_shocks_costs_liquidity_and_market_age(self):
        baseline = simulate_paper_execution(*pure_inputs(body(quantity_base_units_str="4")))
        downside = simulate_paper_execution(*pure_inputs(body(quantity_base_units_str="4", scenario="DOWNSIDE")))
        stress = simulate_paper_execution(*pure_inputs(body(quantity_base_units_str="4", scenario="STRESS")))
        self.assertGreaterEqual(int(stress["hypothetical_loss_base_units_str"]),
                                int(downside["hypothetical_loss_base_units_str"]))
        self.assertGreaterEqual(int(downside["hypothetical_loss_base_units_str"]),
                                int(baseline["hypothetical_loss_base_units_str"]))
        self.assertEqual(downside["scenario_parameters"]["price_change_bps"], -1000)
        self.assertEqual(stress["scenario_parameters"]["price_change_bps"], -3000)
        self.assertEqual(stress["scenario_parameters"]["liquidity_reduction_bps"], 5000)
        self.assertGreater(int(stress["hypothetical_exit_fee_base_units_str"]), 0)
        self.assertGreater(int(stress["hypothetical_exit_spread_base_units_str"]), 0)
        self.assertGreater(int(stress["hypothetical_exit_slippage_base_units_str"]), 0)
        args = pure_inputs()
        args[1]["market_timestamp"] -= 301
        self.assertEqual(simulate_paper_execution(*args)["fill_status"], "STALE_QUOTE")
        args = pure_inputs()
        args[1]["available_quantity_base_units_str"] = "2"
        self.assertEqual(simulate_paper_execution(*args)["filled_quantity_base_units_str"], "2")

    def test_rejects_leverage_short_currency_unknown_prices_and_u64(self):
        args = pure_inputs()
        args[3]["allow_leverage"] = True
        with self.assertRaises(PaperError): simulate_paper_execution(*args)
        args = pure_inputs(body(side="SELL"))
        self.assertEqual(simulate_paper_execution(*args)["reason_codes"], ["NO_SHORT_SELLING"])
        args = pure_inputs(body(trading_quote_currency=OTHER))
        self.assertEqual(simulate_paper_execution(*args)["status"], "INVALID_CONTEXT")
        args = pure_inputs()
        args[1]["price_numerator_str"] = "0"
        with self.assertRaises(PaperError): simulate_paper_execution(*args)
        args = pure_inputs(body(paper_budget_base_units_str=str(2**64)))
        with self.assertRaises(PaperError): simulate_paper_execution(*args)
        args = pure_inputs(body(paper_budget_base_units_str=str(2**64 - 1), quantity_base_units_str="1"))
        self.assertEqual(simulate_paper_execution(*args)["fill_status"], "FILLED_SIMULATED")
        args = pure_inputs()
        args[3]["allowed_instruments"] = []
        self.assertEqual(simulate_paper_execution(*args)["status"], "INVALID_CONTEXT")
        args = pure_inputs(body(funding_source="CON30_HYPOTHETICAL_SCENARIO"))
        with self.assertRaises(PaperError): simulate_paper_execution(*args)
        args = pure_inputs(body(quantity_base_units_str="4", scenario="STRESS"))
        args[3]["max_simulated_loss_budget_bps"] = 1
        self.assertEqual(simulate_paper_execution(*args)["reason_codes"], ["SIMULATED_LOSS_BUDGET"])

    def test_productive_comparison_preserves_cash_and_never_infers_revenue(self):
        hardware = {"scenario_id": "hardware", "resource_type": "HARDWARE",
                    "initial_cost_base_units_str": "400", "operating_cost_base_units_str": "20",
                    "maintenance_cost_base_units_str": "10", "useful_life_days": 365,
                    "estimated_utilization_bps": 5000, "capacity_change_bps": 2000,
                    "currency_or_token_mint": MINT, "evidence_provenance": "USER_SUPPLIED_ASSUMPTION"}
        replacement = {**hardware, "scenario_id": "replacement", "resource_type": "REPLACEMENT",
                       "initial_cost_base_units_str": "300", "maintenance_cost_base_units_str": "5"}
        result = compare_productive_alternatives("1000", 30, [hardware, replacement])
        self.assertEqual(result[0]["remaining_paper_budget_base_units_str"], "1000")
        self.assertEqual(result[1]["total_paper_cost_base_units_str"], "430")
        self.assertEqual(result[1]["payback_status"], "INSUFFICIENT_ASSUMPTIONS")
        self.assertIsNone(result[1]["payback_days"])


class PaperJournalTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / "paper_trading.sqlite"
        self.store = PaperSimulationStore(self.path)

    def tearDown(self):
        self.store.close()
        self.temp.cleanup()

    def test_owner_signature_replay_identity_restart_and_offline_environment(self):
        request = body()
        headers = signed(request)
        self.assertEqual(verify_paper_signature(AGENT_RECORD, f"/v1/agents/{AGENT}/paper-simulations",
                                                request, headers), OWNER)
        with self.assertRaises(PaperError):
            verify_paper_signature(AGENT_RECORD, f"/v1/agents/{AGENT}/paper-simulations",
                                   {**request, "paper_budget_base_units_str": "1001"}, headers)
        with self.assertRaises(PaperError):
            verify_paper_signature({**AGENT_RECORD, "owner": OTHER},
                                   f"/v1/agents/{AGENT}/paper-simulations", request, headers)
        self.assertFalse(NETWORK_ENABLED)
        original = os.environ.get("APCA_API_BASE_URL")
        try:
            os.environ["APCA_API_BASE_URL"] = "https://api.alpaca.markets"
            result, created = self.store.run(AGENT_RECORD, request, OWNER)
        finally:
            if original is None: os.environ.pop("APCA_API_BASE_URL", None)
            else: os.environ["APCA_API_BASE_URL"] = original
        self.assertTrue(created)
        self.assertTrue(result["is_paper"])
        self.assertEqual(result["provider_mode"], "OFFLINE_FIXTURE")
        self.assertEqual(result["data_provenance"], "FIXTURE")
        self.store.close()
        self.store = PaperSimulationStore(self.path)
        self.assertEqual(self.store.get(AGENT_RECORD, result["simulation_id"]), result)
        self.assertEqual(self.store.list(AGENT_RECORD)[0]["real_capital_authorized"], False)
        for changed in ({**AGENT_RECORD, "owner": OTHER}, {**AGENT_RECORD, "agent_id": "22" * 32}):
            with self.assertRaises(PaperError): self.store.get(changed, result["simulation_id"])
            self.assertEqual(self.store.list(changed), [])

    def test_ten_concurrent_idempotent_retries_and_conflicting_nonce(self):
        request = body()
        with concurrent.futures.ThreadPoolExecutor(max_workers=10) as pool:
            outcomes = list(pool.map(lambda _: self.store.run(AGENT_RECORD, request, OWNER), range(10)))
        self.assertEqual(sum(created for _, created in outcomes), 1)
        self.assertEqual(len(self.store.list(AGENT_RECORD)), 1)
        with self.assertRaises(PaperError) as conflict:
            self.store.run(AGENT_RECORD, {**request, "scenario": "STRESS",
                                          "idempotency_key": "paper-idem-different"}, OWNER)
        self.assertEqual(conflict.exception.code, "IDEMPOTENCY_CONFLICT")

    def test_agent_owner_network_mint_and_market_identity_are_separate(self):
        first = body(quantity_base_units_str="1")
        second_agent = {"agent_account": MINT_TWO, "agent_id": "22" * 32, "owner": OTHER}
        second = body(agent_account=MINT_TWO, agent_id=second_agent["agent_id"],
                      owner_pubkey=OTHER, network="solana:devnet", genesis_hash=OTHER,
                      treasury_token_mint=MINT_TWO, trading_quote_currency=MINT_TWO,
                      idempotency_key="paper-idem-00000002", nonce="paper-nonce-00000002",
                      instrument_id="fixture:spot:compute-credit:beta", quantity_base_units_str="1")
        one = self.store.run(AGENT_RECORD, first, OWNER)[0]
        two = self.store.run(second_agent, second, OTHER)[0]
        self.assertNotEqual(one["market_snapshot_hash"], two["market_snapshot_hash"])
        self.assertEqual([item["simulation_id"] for item in self.store.list(AGENT_RECORD)], [one["simulation_id"]])
        self.assertEqual([item["simulation_id"] for item in self.store.list(second_agent)], [two["simulation_id"]])
        with self.assertRaises(PaperError): self.store.get(AGENT_RECORD, two["simulation_id"])
        with self.assertRaises(PaperError): self.store.get(second_agent, one["simulation_id"])

    def test_productive_result_and_untrusted_live_url_fail_closed(self):
        request = body(scenario_kind="PRODUCTIVE_COMPARISON", productive_alternatives=[{
            "scenario_id": "hardware", "resource_type": "HARDWARE",
            "initial_cost_base_units_str": "400", "operating_cost_base_units_str": "20",
            "maintenance_cost_base_units_str": "10", "useful_life_days": 365,
            "estimated_utilization_bps": 5000, "capacity_change_bps": 2000,
            "currency_or_token_mint": MINT, "evidence_provenance": "USER_SUPPLIED_ASSUMPTION"}])
        result = self.store.run(AGENT_RECORD, request, OWNER)[0]
        self.assertEqual(result["productive_alternatives"][1]["payback_status"], "INSUFFICIENT_ASSUMPTIONS")
        self.assertIsNone(result["fill_status"])
        with self.assertRaises(PaperError):
            verify_paper_signature(AGENT_RECORD, f"/v1/agents/{AGENT}/paper-simulations",
                {**request, "broker_url": "https://api.alpaca.markets"}, signed(request))

    def test_economic_tables_remain_byte_identical(self):
        ledger = EconomicLedger(Path(self.temp.name) / "economic.sqlite")
        tables = ("economic_movements", "journal_entries", "ledger_entries", "agent_costs",
                  "agent_reserves", "reserve_transactions", "spending_proposals", "spending_decisions",
                  "spending_budget_claims", "spending_approvals", "spending_approval_events")
        def fingerprint():
            return {table: hashlib.sha256(repr([tuple(row) for row in ledger._conn.execute(
                f"SELECT * FROM {table} ORDER BY rowid")]).encode()).hexdigest() for table in tables}
        before = fingerprint()
        self.store.run(AGENT_RECORD, body(), OWNER)
        self.assertEqual(before, fingerprint())
        ledger.close()


if __name__ == "__main__":
    unittest.main()
