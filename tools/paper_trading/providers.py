"""Read-only paper market sources; no broker or exchange order interface exists."""
from __future__ import annotations

from typing import Protocol

FIXTURE_VERSION = "conatus:paper-fixtures:v1"
NETWORK_ENABLED = False


class PaperMarketDataProvider(Protocol):
    def get_instruments(self, context: dict) -> list[dict]: ...
    def get_quote(self, instrument_id: str, context: dict) -> dict: ...
    def get_liquidity_snapshot(self, instrument_id: str, context: dict) -> dict: ...
    def get_fee_schedule(self, instrument_id: str, context: dict) -> dict: ...


class SandboxConnectorContract(PaperMarketDataProvider, Protocol):
    """Future read-only sandbox source. No order placement capability."""


class DeterministicFixtureProvider:
    provider_id = FIXTURE_VERSION
    provider_mode = "OFFLINE_FIXTURE"
    data_provenance = "FIXTURE"

    def get_instruments(self, context: dict) -> list[dict]:
        quote = context["treasury_token_mint"]
        return [
            {"instrument_id": "fixture:spot:compute-credit:alpha", "instrument_type": "SPOT",
             "display_symbol": "PAPER", "trading_base_asset": "PAPER_COMPUTE_UNIT",
             "trading_quote_currency": quote, "venue": "FIXTURE_ALPHA", "risk_category": "HIGH",
             "settlement_assumptions": "No settlement; local mathematical fill only"},
            {"instrument_id": "fixture:spot:compute-credit:beta", "instrument_type": "SPOT",
             "display_symbol": "PAPER", "trading_base_asset": "PAPER_COMPUTE_UNIT",
             "trading_quote_currency": quote, "venue": "FIXTURE_BETA", "risk_category": "HIGH",
             "settlement_assumptions": "No settlement; local mathematical fill only"},
        ]

    def get_quote(self, instrument_id: str, context: dict) -> dict:
        instrument = next((item for item in self.get_instruments(context)
                           if item["instrument_id"] == instrument_id), None)
        if instrument is None:
            raise ValueError("Unknown paper instrument")
        return {**instrument, "price_numerator_str": "100" if instrument["venue"] == "FIXTURE_ALPHA" else "105",
                "price_denominator_str": "1", "market_timestamp": context["simulation_timestamp"],
                "snapshot_version": FIXTURE_VERSION, "data_provenance": "FIXTURE"}

    def get_liquidity_snapshot(self, instrument_id: str, context: dict) -> dict:
        self.get_quote(instrument_id, context)
        return {"available_quantity_base_units_str": "1000", "liquidity_source": FIXTURE_VERSION}

    def get_fee_schedule(self, instrument_id: str, context: dict) -> dict:
        self.get_quote(instrument_id, context)
        return {"fee_bps": 100, "spread_bps": 0, "slippage_bps": 50,
                "cost_source": FIXTURE_VERSION}


class LocalPaperExecutionAdapter:
    """Delegates to the pure engine; does not import network, wallet or ledger code."""

    def simulate_fill(self, request: dict, market: dict, costs: dict,
                      risk_policy: dict, portfolio: dict) -> dict:
        from .simulator import simulate_paper_execution
        return simulate_paper_execution(request, market, costs, risk_policy, portfolio)
