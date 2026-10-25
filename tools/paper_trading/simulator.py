"""Pure exact-integer CON-31 paper execution and productive alternatives."""
from __future__ import annotations

import re
from typing import Any

MAX_U64 = 2**64 - 1
METHODOLOGY_VERSION = "conatus:paper-simulation:v1"
SHOCKS = {
    "BASE": {"price_change_bps": 0, "spread_change_bps": 0, "slippage_change_bps": 0,
             "liquidity_reduction_bps": 0, "fee_change_bps": 0},
    "DOWNSIDE": {"price_change_bps": -1000, "spread_change_bps": 50, "slippage_change_bps": 50,
                 "liquidity_reduction_bps": 2500, "fee_change_bps": 25},
    "STRESS": {"price_change_bps": -3000, "spread_change_bps": 150, "slippage_change_bps": 150,
               "liquidity_reduction_bps": 5000, "fee_change_bps": 50},
}


class PaperError(Exception):
    def __init__(self, status: int, code: str, message: str):
        super().__init__(message)
        self.status, self.code = status, code


def amount(value: Any, name: str, *, positive: bool = False) -> int:
    if (not isinstance(value, str) or not re.fullmatch(r"(0|[1-9][0-9]*)", value) or
            int(value) > MAX_U64 or positive and value == "0"):
        raise PaperError(400, "INVALID_AMOUNT", f"{name} must be an exact u64 decimal string")
    return int(value)


def bps(value: Any, name: str, maximum: int = 10000) -> int:
    if type(value) is not int or not 0 <= value <= maximum:
        raise PaperError(400, "INVALID_BPS", f"{name} must be an integer 0–{maximum}")
    return value


def ceil_div(a: int, b: int) -> int:
    return (a + b - 1) // b


def _rejected(code: str, request: dict, market: dict, *, status: str = "RISK_REJECTED") -> dict:
    return {"status": status, "fill_status": "REJECTED_SIMULATED",
            "reason_codes": [code], "filled_quantity_base_units_str": "0",
            "entry_total_base_units_str": "0", "remaining_paper_budget_base_units_str":
            request["paper_budget_base_units_str"], "hypothetical_net_result_base_units_str": None,
            "is_paper": True, "is_executable": False, "real_capital_authorized": False,
            "market_timestamp": market.get("market_timestamp")}


def simulate_paper_execution(request: dict, market: dict, costs: dict,
                             risk_policy: dict, simulated_portfolio: dict) -> dict:
    """Return a hypothetical fill; no I/O, clock, wallet, account or order dependency."""
    if any(request.get(k) in (None, "", "PENDING_RESOLUTION") for k in
           ("agent_account", "agent_id", "owner_pubkey", "network", "genesis_hash",
            "program_id", "treasury_token_mint", "trading_quote_currency")):
        raise PaperError(422, "INVALID_CONTEXT", "Complete exact paper context is required")
    if request.get("funding_source") != "MANUAL_PAPER_ALLOCATION":
        raise PaperError(400, "INVALID_FUNDING_SOURCE", "Only explicit manual paper funding is enabled")
    if request.get("scenario") not in SHOCKS or request.get("side") not in ("BUY", "SELL"):
        raise PaperError(400, "INVALID_SCENARIO", "Only spot BUY/SELL and declared shocks are supported")
    if request.get("scenario_kind") != "FINANCIAL_SPOT" or market.get("instrument_type") != "SPOT":
        raise PaperError(400, "INVALID_INSTRUMENT", "Only unlevered spot fixtures are supported")
    if any(request.get(flag) is True or risk_policy.get(flag) is True for flag in
           ("allow_leverage", "allow_derivatives", "allow_short_selling", "allow_borrowing")):
        raise PaperError(400, "PROHIBITED_RISK", "Leverage, derivatives, shorting and borrowing are disabled")
    if market.get("data_provenance") not in ("FIXTURE", "SANDBOX_DATA", "HISTORICAL_MARKET_DATA"):
        raise PaperError(422, "INVALID_PROVENANCE", "Market source must be identified")
    if (market.get("instrument_id") != request.get("instrument_id") or
            market.get("trading_quote_currency") != request["trading_quote_currency"] or
            market["trading_quote_currency"] != request["treasury_token_mint"] or
            request["instrument_id"] not in risk_policy.get("allowed_instruments", []) or
            request["trading_quote_currency"] not in risk_policy.get("allowed_quote_currencies", [])):
        return _rejected("INSTRUMENT_OR_CURRENCY_NOT_ALLOWED", request, market, status="INVALID_CONTEXT")
    at, observed = request.get("simulation_timestamp"), market.get("market_timestamp")
    if type(at) is not int or type(observed) is not int or observed > at:
        raise PaperError(400, "INVALID_TIMESTAMP", "Explicit valid simulation and market times are required")
    if at - observed > risk_policy.get("max_quote_age_seconds", 300):
        return _rejected("STALE_QUOTE", request, market, status="STALE_MARKET_DATA") | {
            "fill_status": "STALE_QUOTE"}
    horizon = request.get("holding_period_days")
    if type(horizon) is not int or horizon not in (7, 30, 90):
        raise PaperError(400, "INVALID_HORIZON", "Horizon must be 7, 30 or 90 days")
    budget = amount(request.get("paper_budget_base_units_str"), "paper budget", positive=True)
    cash = amount(simulated_portfolio.get("cash_base_units_str"), "paper cash")
    if cash > budget:
        raise PaperError(422, "PORTFOLIO_INTEGRITY", "Paper cash exceeds paper allocation")
    quantity = amount(request.get("quantity_base_units_str"), "paper quantity", positive=True)
    numerator = amount(market.get("price_numerator_str"), "price numerator", positive=True)
    denominator = amount(market.get("price_denominator_str"), "price denominator", positive=True)
    liquidity = amount(market.get("available_quantity_base_units_str"), "paper liquidity")
    fee = bps(costs.get("fee_bps"), "fee")
    spread = bps(costs.get("spread_bps"), "spread")
    slippage = bps(costs.get("slippage_bps"), "slippage")
    max_allocation = amount(risk_policy.get("max_paper_allocation_base_units_str"), "risk allocation", positive=True)
    position_limit = bps(risk_policy.get("max_position_allocation_bps"), "position limit")
    trade_limit = bps(risk_policy.get("max_single_trade_bps"), "trade limit")
    turnover_limit = bps(risk_policy.get("max_daily_paper_turnover_bps"), "turnover limit")
    bps(risk_policy.get("max_simulated_loss_budget_bps"), "loss budget")
    if budget > max_allocation:
        return _rejected("PAPER_ALLOCATION_LIMIT", request, market)
    shock = SHOCKS[request["scenario"]]
    available_liquidity = liquidity * (10000 - shock["liquidity_reduction_bps"]) // 10000
    if request["side"] == "SELL":
        held = amount(simulated_portfolio.get("position_quantity_base_units_str", "0"), "paper holdings")
        if quantity > held:
            return _rejected("NO_SHORT_SELLING", request, market)
    if request.get("require_full_fill") is True and quantity > available_liquidity:
        return _rejected("INSUFFICIENT_LIQUIDITY", request, market, status="INSUFFICIENT_DATA") | {
            "fill_status": "INSUFFICIENT_LIQUIDITY"}

    def quote_for(units: int) -> tuple[int, int, int, int, int]:
        gross = ceil_div(units * numerator, denominator) if request["side"] == "BUY" else units * numerator // denominator
        spread_cost = ceil_div(gross * spread, 10000)
        slip_cost = ceil_div(gross * slippage, 10000)
        fee_cost = ceil_div(gross * fee, 10000)
        total = gross + spread_cost + slip_cost + fee_cost if request["side"] == "BUY" else max(0, gross - spread_cost - slip_cost - fee_cost)
        return gross, spread_cost, slip_cost, fee_cost, total

    max_units = min(quantity, available_liquidity)
    if request["side"] == "BUY":
        position_value = amount(simulated_portfolio.get("position_value_base_units_str", "0"), "paper position")
        limit = min(cash, budget * trade_limit // 10000,
                    max(0, budget * position_limit // 10000 - position_value),
                    budget * turnover_limit // 10000)
        used = amount(simulated_portfolio.get("daily_turnover_base_units_str", "0"), "paper turnover")
        limit = min(limit, max(0, budget * turnover_limit // 10000 - used))
        lo, hi = 0, max_units
        while lo < hi:
            mid = (lo + hi + 1) // 2
            if quote_for(mid)[4] <= limit:
                lo = mid
            else:
                hi = mid - 1
        max_units = lo
        if request.get("require_full_fill") is True and max_units < quantity:
            return _rejected("PAPER_BUDGET_OR_RISK_LIMIT", request, market)
    if max_units == 0:
        return _rejected("PAPER_BUDGET_OR_LIQUIDITY", request, market)
    gross, spread_cost, slip_cost, fee_cost, total = quote_for(max_units)
    if any(v > MAX_U64 for v in (gross, spread_cost, slip_cost, fee_cost, total)):
        raise PaperError(422, "AMOUNT_OVERFLOW", "Paper calculation exceeds u64")
    if request["side"] == "BUY":
        remaining = cash - total
        stressed_gross = max_units * numerator * (10000 + shock["price_change_bps"]) // (denominator * 10000)
        exit_spread = ceil_div(stressed_gross * (spread + shock["spread_change_bps"]), 10000)
        exit_slip = ceil_div(stressed_gross * (slippage + shock["slippage_change_bps"]), 10000)
        exit_fee = ceil_div(stressed_gross * (fee + shock["fee_change_bps"]), 10000)
        exit_proceeds = max(0, stressed_gross - exit_spread - exit_slip - exit_fee)
        pnl = exit_proceeds - total
        if max(0, -pnl) > budget * risk_policy["max_simulated_loss_budget_bps"] // 10000:
            return _rejected("SIMULATED_LOSS_BUDGET", request, market)
    else:
        remaining = cash + total
        if remaining > MAX_U64:
            raise PaperError(422, "AMOUNT_OVERFLOW", "Paper cash exceeds u64")
        exit_proceeds, pnl = total, None
        exit_spread = exit_slip = exit_fee = 0
    return {"status": "SIMULATED", "fill_status": "FILLED_SIMULATED" if max_units == quantity else
            "PARTIALLY_FILLED_SIMULATED", "reason_codes": [],
            "filled_quantity_base_units_str": str(max_units), "reference_value_base_units_str": str(gross),
            "entry_spread_base_units_str": str(spread_cost), "entry_slippage_base_units_str": str(slip_cost),
            "entry_fee_base_units_str": str(fee_cost), "entry_total_base_units_str": str(total),
            "hypothetical_exit_spread_base_units_str": str(exit_spread),
            "hypothetical_exit_slippage_base_units_str": str(exit_slip),
            "hypothetical_exit_fee_base_units_str": str(exit_fee),
            "hypothetical_exit_proceeds_base_units_str": str(exit_proceeds),
            "hypothetical_net_result_base_units_str": str(pnl) if pnl is not None else None,
            "hypothetical_loss_base_units_str": str(max(0, -pnl)) if pnl is not None else None,
            "remaining_paper_budget_base_units_str": str(remaining),
            "committed_budget_bps": ceil_div(total * 10000, budget) if request["side"] == "BUY" else 0,
            "scenario_parameters": shock, "market_timestamp": observed,
            "is_paper": True, "is_executable": False, "real_capital_authorized": False}


def compare_productive_alternatives(paper_budget_base_units_str: str, horizon_days: int,
                                    alternatives: list[dict]) -> list[dict]:
    """Compare explicit productive cash assumptions; capacity is never treated as revenue."""
    budget = amount(paper_budget_base_units_str, "paper budget", positive=True)
    if horizon_days not in (7, 30, 90) or type(horizon_days) is not int:
        raise PaperError(400, "INVALID_HORIZON", "Invalid productive horizon")
    output = [{"scenario_id": "PRESERVE_LIQUIDITY", "status": "SIMULATED",
               "initial_cost_base_units_str": "0", "recurring_cost_base_units_str": "0",
               "total_paper_cost_base_units_str": "0", "remaining_paper_budget_base_units_str": str(budget),
               "hypothetical_capacity_change_bps": 0, "payback_days": None,
               "assumptions": ["No allocation; cash remains fictitious"]}]
    for item in alternatives:
        if not isinstance(item, dict) or item.get("resource_type") not in ("HARDWARE", "REPLACEMENT", "MAINTENANCE", "CAPACITY"):
            raise PaperError(400, "INVALID_PRODUCTIVE_SCENARIO", "Unknown productive resource")
        initial = amount(item.get("initial_cost_base_units_str"), "initial cost")
        operating = amount(item.get("operating_cost_base_units_str"), "operating cost")
        maintenance = amount(item.get("maintenance_cost_base_units_str"), "maintenance cost")
        residual = amount(item.get("residual_value_assumption_base_units_str", "0"), "residual assumption")
        life, utilization, capacity = item.get("useful_life_days"), item.get("estimated_utilization_bps"), item.get("capacity_change_bps")
        if type(life) is not int or life <= 0 or life > 36500:
            raise PaperError(400, "INVALID_PRODUCTIVE_SCENARIO", "Useful life must be explicit")
        bps(utilization, "utilization")
        if type(capacity) is not int or not -10000 <= capacity <= 10000:
            raise PaperError(400, "INVALID_PRODUCTIVE_SCENARIO", "Capacity change must be bounded")
        if item.get("currency_or_token_mint") is None or item.get("evidence_provenance") not in ("USER_SUPPLIED_ASSUMPTION", "FIXTURE"):
            raise PaperError(400, "INVALID_PRODUCTIVE_SCENARIO", "Currency and provenance are required")
        recurring = ceil_div((operating + maintenance) * horizon_days, 30)
        total = initial + recurring
        if total > MAX_U64 or residual > initial:
            raise PaperError(422, "AMOUNT_OVERFLOW", "Productive cash assumptions exceed bounds")
        benefit_raw = item.get("assumed_monthly_cash_benefit_base_units_str")
        benefit = amount(benefit_raw, "cash benefit") if benefit_raw is not None else None
        net_monthly = benefit - operating - maintenance if benefit is not None else None
        payback = ceil_div(initial * 30, net_monthly) if net_monthly and net_monthly > 0 else None
        output.append({"scenario_id": item.get("scenario_id"),
                       "resource_type": item["resource_type"],
                       "status": "SIMULATED" if total <= budget else "RISK_REJECTED",
                       "initial_cost_base_units_str": str(initial),
                       "recurring_cost_base_units_str": str(recurring),
                       "total_paper_cost_base_units_str": str(total),
                       "remaining_paper_budget_base_units_str": str(max(0, budget - total)),
                       "hypothetical_capacity_change_bps": capacity * utilization // 10000,
                       "payback_days": payback, "payback_status": "SIMULATED" if payback is not None else "INSUFFICIENT_ASSUMPTIONS",
                       "assumptions": ["All values are explicit hypothetical inputs; no revenue is inferred from capacity"],
                       "currency_or_token_mint": item["currency_or_token_mint"],
                       "evidence_provenance": item["evidence_provenance"]})
    return output
