"""CON-30: deterministic, advisory surplus assessment and read-only ledger adapter.

All monetary inputs are exact unsigned decimal strings. The pure function has no
clock, database, RPC, or mutable state. Ledger accounting is never rewritten.
"""
from __future__ import annotations

import json
import re
import time
from typing import Any

from .budget_policies import BudgetPolicyStore, PolicyError, digest
from .ledger import EconomicLedger
from .solvency import assess_agent as assess_solvency

METHODOLOGY_VERSION = "conatus:investible-surplus:v1"
MAX_U64 = (1 << 64) - 1
FRESHNESS_SECONDS = 86400
SCENARIOS = {
    "BASE": {"opex_multiplier_bps": 10000, "liquidity_haircut_bps": 0,
             "additional_liability_buffer_base_units_str": "0"},
    "CONSERVATIVE": {"opex_multiplier_bps": 12500, "liquidity_haircut_bps": 500,
                     "additional_liability_buffer_base_units_str": "0"},
    "STRESS": {"opex_multiplier_bps": 15000, "liquidity_haircut_bps": 1500,
               "additional_liability_buffer_base_units_str": "0"},
}
PRODUCTION_PROVENANCES = {"LIVE_RPC", "EXTERNAL_ATTESTED", "LIVE_RPC_AND_EXTERNAL_ATTESTED"}


class SurplusError(Exception):
    def __init__(self, status: int, code: str, message: str):
        super().__init__(message)
        self.status, self.code = status, code


def _amount(value: Any, name: str, *, optional: bool = False) -> int | None:
    if value is None and optional:
        return None
    if not isinstance(value, str) or not re.fullmatch(r"(0|[1-9][0-9]*)", value) or int(value) > MAX_U64:
        raise SurplusError(400, "INVALID_AMOUNT", f"{name} must be an exact unsigned u64 string")
    return int(value)


def _ceil_div(numerator: int, denominator: int) -> int:
    return (numerator + denominator - 1) // denominator


def methodology() -> dict[str, Any]:
    return {
        "methodology_version": METHODOLOGY_VERSION, "freshness_seconds": FRESHNESS_SECONDS,
        "horizons_days": [7, 30, 90], "scenarios": SCENARIOS,
        "treasury_source": "Reconciled debits less all credits in ASSET:TREASURY, floored at zero (CON-24)",
        "reserve_rule": "Existing reserves are already outside treasury; only an unfunded policy target is deducted",
        "continuity_rule": "Observed realized cash OPEX / observed days, rounded up; scenario multiplier also rounds up",
        "overlap_rule": "Liability, claim and continuity overlaps must be resolved before a numerical surplus is reported",
        "verification_rule": "Productive capital needs authenticated ownership, complete economic coverage and productive provenance",
        "disclaimer": "Advisory assessment only; no investment executed or capital availability guaranteed",
    }


def assess_investible_surplus(
    monetary_context: dict[str, str], treasury: dict[str, Any], reserves: dict[str, Any],
    liabilities: dict[str, Any], commitments: dict[str, Any], policy: dict[str, Any],
    operating_costs: dict[str, Any], scenario: dict[str, Any], assessed_at: int,
) -> dict[str, Any]:
    """Calculate one segregated context. Missing evidence never becomes a zero balance."""
    required = ("agent_account", "agent_id", "owner_pubkey", "network", "genesis_hash", "program_id", "token_mint")
    if any(not isinstance(monetary_context.get(k), str) or not monetary_context[k] or
           monetary_context[k] == "PENDING_RESOLUTION" for k in required):
        raise SurplusError(422, "MIXED_ASSET_CONTEXT", "A complete resolved monetary identity is required")
    if type(assessed_at) is not int or assessed_at < 0:
        raise SurplusError(400, "INVALID_TIME", "assessed_at must be Unix seconds")
    name, horizon = scenario.get("name"), scenario.get("continuity_horizon_days")
    if name not in SCENARIOS or type(horizon) is not int or horizon not in (7, 30, 90):
        raise SurplusError(400, "INVALID_SCENARIO", "Scenario and horizon must be explicit")
    assumptions = {**SCENARIOS[name], "continuity_horizon_days": horizon,
                   "opex_window_estimation_assumed": operating_costs.get("explicit_estimation_assumption") is True}
    available = _amount(treasury.get("available_base_units_str"), "treasury", optional=True)
    existing = _amount(reserves.get("accounting_reserved_base_units_str"), "accounting reserve", optional=True)
    eligible = _amount(reserves.get("eligible_policy_reserve_base_units_str"), "eligible reserve", optional=True)
    required_reserve = _amount(policy.get("minimum_reserve_base_units_str"), "policy reserve", optional=True)
    obligation = _amount(liabilities.get("outstanding_base_units_str"), "outstanding obligations", optional=True)
    claim = _amount(commitments.get("pending_base_units_str"), "pending commitments", optional=True)
    cash_opex = _amount(operating_costs.get("observed_cash_opex_base_units_str"), "observed cash OPEX", optional=True)
    other = _amount(treasury.get("other_restrictions_base_units_str", "0"), "other restrictions")
    days = operating_costs.get("observed_days")
    if days is not None and (type(days) is not int or days <= 0 or days > 365):
        raise SurplusError(400, "INVALID_WINDOW", "Observed window must be 1–365 days")
    if existing is not None and eligible is not None and eligible > existing:
        raise SurplusError(422, "INVALID_RESERVES", "Eligible reserve exceeds total reserve")
    if not all(type(x) is bool for x in (
            liabilities.get("not_reflected_in_treasury"), commitments.get("independent_of_ledger_costs"),
            operating_costs.get("independent_of_liabilities"))):
        raise SurplusError(400, "UNKNOWN_OVERLAP", "Explicit non-overlap evidence is required")
    data_as_of = treasury.get("data_as_of")
    if data_as_of is not None and (type(data_as_of) is not int or data_as_of > assessed_at or data_as_of < 0):
        raise SurplusError(400, "INVALID_TIME", "Invalid treasury observation time")
    provenance = treasury.get("provenance", "HISTORICAL_UNVERIFIED")
    if provenance not in PRODUCTION_PROVENANCES | {"HISTORICAL_FIXTURE", "SYNTHETIC_TEST", "HISTORICAL_UNVERIFIED"}:
        raise SurplusError(400, "INVALID_PROVENANCE", "Unknown treasury provenance")
    references = sorted(set(str(x) for x in (
        treasury.get("evidence_references", []) + reserves.get("evidence_references", []) +
        liabilities.get("evidence_references", []) + commitments.get("evidence_references", []) +
        operating_costs.get("evidence_references", []))))
    missing = []
    for label, value in (("treasury", available), ("accounting_reserves", existing),
                         ("eligible_reserves", eligible), ("policy_reserve", required_reserve),
                         ("obligations", obligation), ("commitments", claim), ("cash_opex", cash_opex),
                         ("observed_days", days)):
        if value is None:
            missing.append(label)
    if data_as_of is None:
        missing.append("treasury_observation_time")
    if (policy.get("status", "ACTIVE") != "ACTIVE" or
            policy.get("valid_from", 0) > assessed_at or
            policy.get("expires_at", assessed_at + 1) <= assessed_at):
        missing.append("policy_inactive_or_expired")
    if obligation and not liabilities["not_reflected_in_treasury"]:
        missing.append("obligation_treasury_overlap")
    if claim and not commitments["independent_of_ledger_costs"]:
        missing.append("claim_cost_overlap")
    if cash_opex and obligation and not operating_costs["independent_of_liabilities"]:
        missing.append("continuity_liability_overlap")
    if cash_opex == 0 and not operating_costs.get("coverage_complete", False):
        missing.append("zero_opex_coverage")
    elif cash_opex is not None and not operating_costs.get("coverage_complete", False) and not operating_costs.get("explicit_estimation_assumption", False):
        missing.append("opex_window_coverage")
    reserve_relation = policy.get("reserve_continuity_relation", "UNKNOWN")
    if reserve_relation not in ("INDEPENDENT", "SAME_PURPOSE", "UNKNOWN"):
        raise SurplusError(400, "INVALID_POLICY", "Unknown reserve/continuity relationship")
    stale = data_as_of is not None and assessed_at - data_as_of > FRESHNESS_SECONDS
    reserve_gap = max(0, required_reserve - eligible) if required_reserve is not None and eligible is not None else None
    # Reserve balances are already outside treasury. This is informational, never subtracted.
    haircut = available * assumptions["liquidity_haircut_bps"] // 10000 if available is not None else None
    projected = (_ceil_div(cash_opex * horizon * assumptions["opex_multiplier_bps"], days * 10000)
                 if cash_opex is not None and days else None)
    if projected is not None and projected > MAX_U64:
        raise SurplusError(422, "AMOUNT_OVERFLOW", "Projected continuity buffer exceeds u64")
    if projected and required_reserve and reserve_relation == "UNKNOWN":
        missing.append("reserve_continuity_overlap_unknown")
    # Only an explicit SAME_PURPOSE classification permits netting the target.
    continuity = (projected if reserve_relation == "INDEPENDENT" else
                  max(0, projected - max(required_reserve, eligible))) if (
                      projected is not None and required_reserve is not None and eligible is not None) else None
    extra_liability = int(assumptions["additional_liability_buffer_base_units_str"])
    deductions = [
        {"component": "ACCOUNTING_RESERVE", "amount_base_units_str": str(existing) if existing is not None else None,
         "source": "agent_reserves", "reference_ids": reserves.get("evidence_references", []),
         "already_reflected_in_treasury": True, "applied_to_surplus": False,
         "reason": "Allocated reserve left ASSET:TREASURY"},
        {"component": "ACCRUED_OBLIGATIONS", "amount_base_units_str": str(obligation) if obligation is not None else None,
         "source": "agent_costs", "reference_ids": liabilities.get("evidence_references", []),
         "already_reflected_in_treasury": not liabilities["not_reflected_in_treasury"],
         "applied_to_surplus": bool(obligation and liabilities["not_reflected_in_treasury"]),
         "reason": "Unpaid accrued liability"},
        {"component": "UNFUNDED_POLICY_RESERVE", "amount_base_units_str": str(reserve_gap) if reserve_gap is not None else None,
         "source": "CON-27 policy", "reference_ids": [policy.get("policy_id", "")],
         "already_reflected_in_treasury": False, "applied_to_surplus": bool(reserve_gap),
         "reason": "Only the gap above eligible existing reserve"},
        {"component": "PENDING_COMMITMENTS", "amount_base_units_str": str(claim) if claim is not None else None,
         "source": "CON-28 claims", "reference_ids": commitments.get("evidence_references", []),
         "already_reflected_in_treasury": False, "applied_to_surplus": bool(claim),
         "reason": "Administrative claim, not payment or legal liability"},
        {"component": "OPERATIONAL_CONTINUITY", "amount_base_units_str": str(continuity) if continuity is not None else None,
         "source": "realized cash OPEX", "reference_ids": operating_costs.get("evidence_references", []),
         "already_reflected_in_treasury": False, "applied_to_surplus": bool(continuity),
         "reason": "Projected horizon net of policy target only when its purpose is explicitly the same"},
        {"component": "LIQUIDITY_HAIRCUT", "amount_base_units_str": str(haircut) if haircut is not None else None,
         "source": "scenario assumption", "reference_ids": [],
         "already_reflected_in_treasury": False, "applied_to_surplus": bool(haircut),
         "reason": "Scenario haircut, not a market forecast"},
        {"component": "OTHER_RESTRICTIONS", "amount_base_units_str": str(other),
         "source": "documented restrictions", "reference_ids": treasury.get("restriction_references", []),
         "already_reflected_in_treasury": False, "applied_to_surplus": bool(other),
         "reason": "Explicit independent restrictions"},
    ]
    if stale:
        status = "STALE_DATA"
    elif missing:
        status = "INSUFFICIENT_DATA"
    elif (provenance in PRODUCTION_PROVENANCES and treasury.get("ownership_verified") is True and
          all(source.get("coverage_complete") is True and source.get("authenticated") is True
              for source in (treasury, reserves, liabilities, commitments, operating_costs)) and
          policy.get("authenticated") is True):
        status = "VERIFIED"
    else:
        status = "ESTIMATED"
    estimated = (str(max(0, available - obligation - reserve_gap - claim - continuity - haircut - other - extra_liability))
                 if status in ("ESTIMATED", "VERIFIED") else None)
    snapshot = {"context": monetary_context, "treasury": treasury, "reserves": reserves,
                "liabilities": liabilities, "commitments": commitments, "policy": policy,
                "operating_costs": operating_costs, "scenario": scenario, "assessed_at": assessed_at}
    snapshot_hash = digest(snapshot)
    result = {
        "assessment_version": 1, "methodology_version": METHODOLOGY_VERSION,
        **{key: monetary_context[key] for key in required},
        "assessed_at": assessed_at, "data_as_of": data_as_of,
        "window_start": operating_costs.get("window_start"), "window_end": operating_costs.get("window_end"),
        "scenario": name, "continuity_horizon_days": horizon, "scenario_assumptions": assumptions,
        "treasury_available_base_units_str": str(available) if available is not None else None,
        "restricted_capital_base_units_str": str(other),
        "accounting_reserved_base_units_str": str(existing) if existing is not None else None,
        "accrued_obligations_base_units_str": str(obligation) if obligation is not None else None,
        "unfunded_policy_reserve_base_units_str": str(reserve_gap) if reserve_gap is not None else None,
        "pending_commitments_base_units_str": str(claim) if claim is not None else None,
        "operational_buffer_base_units_str": str(continuity) if continuity is not None else None,
        "liquidity_haircut_base_units_str": str(haircut) if haircut is not None else None,
        "estimated_investible_surplus_base_units_str": estimated,
        "verified_investible_surplus_base_units_str": estimated if status == "VERIFIED" else None,
        "calculation_status": status, "provenance": provenance,
        "exclusion_reasons": missing + (["treasury_observation_stale"] if stale else []) +
                             ([] if status == "VERIFIED" else ["productive_ownership_and_coverage_not_verified"]),
        "evidence_references": references, "deductions": deductions,
        "policy_id": policy.get("policy_id"), "policy_version": policy.get("version"),
        "policy_hash": policy.get("policy_hash"),
        "economic_snapshot_hash": snapshot_hash, "is_executable": False,
        "solvency_context": operating_costs.get("solvency_context"),
    }
    result["assessment_hash"] = digest(result)
    result["assessment_id"] = "is_" + result["assessment_hash"][:32]
    return result


def assess_agent_surplus(ledger: EconomicLedger, policies: BudgetPolicyStore, agent: dict[str, Any], *,
                         network: str, genesis_hash: str, program_id: str, token_mint: str,
                         scenario: str = "BASE", horizon_days: int = 30,
                         now: int | None = None) -> dict[str, Any]:
    """Read a single owner-scoped ledger partition without mutating any source table."""
    instant = int(time.time()) if now is None else now
    if any(not isinstance(x, str) or not x or x == "PENDING_RESOLUTION" for x in
           (network, genesis_hash, program_id, token_mint)):
        raise SurplusError(422, "MIXED_ASSET_CONTEXT", "Complete monetary context is required")
    try:
        current = policies.current(agent)
    except PolicyError as exc:
        raise SurplusError(404, "POLICY_NOT_FOUND", "Current identity has no accessible policy") from exc
    if (current["network"], current["genesis_hash"], current["program_id"]) != (network, genesis_hash, program_id):
        raise SurplusError(422, "MIXED_ASSET_CONTEXT", "Policy monetary context differs")
    rule = next((item for item in current["asset_rules"] if item["token_mint"] == token_mint), None)
    if rule is None:
        raise SurplusError(422, "MIXED_ASSET_CONTEXT", "Mint is absent from current policy")
    scope = (agent["agent_account"], agent["agent_id"], agent["owner"], network, genesis_hash, program_id, token_mint)
    context = dict(zip(("agent_account", "agent_id", "owner_pubkey", "network", "genesis_hash", "program_id", "token_mint"), scope))
    summaries = ledger.get_economic_summary(agent["agent_account"], network=network,
        genesis_hash=genesis_hash, program_id=program_id, token_mint=token_mint)
    summary = summaries[0] if len(summaries) == 1 else None
    conn = ledger._conn
    base = (agent["agent_account"], network, genesis_hash, program_id, token_mint)
    for table in ("economic_movements", "agent_costs", "agent_reserves"):
        mixed = conn.execute(
            f"SELECT 1 FROM {table} WHERE agent_account=? AND network=? AND genesis_hash=? "
            "AND program_id=? AND token_mint=? AND (agent_id!=? OR owner_pubkey!=?) LIMIT 1",
            (*base, agent["agent_id"], agent["owner"])).fetchone()
        if mixed is not None:
            raise SurplusError(409, "IDENTITY_CONFLICT", "Historical economic identity differs from current agent")
    reserves = conn.execute(
        "SELECT reserve_id, reserve_type, current_reserved_base_units FROM agent_reserves "
        "WHERE agent_account=? AND network=? AND genesis_hash=? AND program_id=? AND token_mint=? "
        "AND agent_id=? AND owner_pubkey=? AND status='ACTIVE'", (*base, agent["agent_id"], agent["owner"])).fetchall()
    existing = sum(int(r["current_reserved_base_units"]) for r in reserves)
    eligible = sum(int(r["current_reserved_base_units"]) for r in reserves
                   if r["reserve_type"] == "OPERATIONAL_CONTINUITY")
    start = instant - 30 * 86400
    costs = conn.execute(
        "SELECT cost_id, movement_id, cost_nature, category, amount_base_units, status, incurred_at, evidence_lineage "
        "FROM agent_costs WHERE agent_account=? AND network=? AND genesis_hash=? AND program_id=? "
        "AND token_mint=? AND agent_id=? AND owner_pubkey=? AND incurred_at<?",
        (*base, agent["agent_id"], agent["owner"], instant)).fetchall()
    realized_ids: set[str] = set()
    realized = 0
    any_realized = False
    for row in costs:
        if row["status"] == "REVERTED":
            continue
        if row["cost_nature"] == "REALIZED" and row["status"] == "RECONCILED":
            any_realized = True
        if (row["cost_nature"] == "REALIZED" and row["category"] != "DEPRECIATION_REPLACEMENT" and
              row["incurred_at"] >= start and
              row["status"] == "RECONCILED" and row["cost_id"] not in realized_ids):
            realized += int(row["amount_base_units"])
            realized_ids.add(row["cost_id"])
    liability_rows = conn.execute(
        "SELECT le.entry_type, le.amount_base_units FROM ledger_entries le "
        "JOIN journal_entries je ON je.journal_entry_id=le.journal_entry_id "
        "WHERE le.agent_account=? AND je.network=? AND je.genesis_hash=? AND je.program_id=? "
        "AND je.token_mint=? AND le.account_name='LIABILITY:ACCRUED_EXPENSES'",
        base).fetchall()
    obligations = sum(int(r["amount_base_units"]) * (1 if r["entry_type"] == "CREDIT" else -1)
                      for r in liability_rows)
    if obligations < 0:
        raise SurplusError(409, "LEDGER_INTEGRITY_CONFLICT", "Accrued liability ledger is inconsistent")
    # The ledger has no generic claim-to-paid-cost settlement link. If both exist,
    # the arithmetic is withheld until their independence can be established.
    day_start = instant - instant % 86400
    claims = conn.execute(
        "SELECT c.decision_id, c.proposal_id, c.amount_base_units_str, p.owner_pubkey, p.agent_id, "
        "d.decision_json, d.decision FROM spending_budget_claims c "
        "JOIN spending_proposals p ON p.proposal_id=c.proposal_id "
        "JOIN spending_decisions d ON d.decision_id=c.decision_id "
        "WHERE c.agent_account=? AND c.network=? AND c.genesis_hash=? AND c.program_id=? AND c.token_mint=? "
        "AND c.policy_id=? AND c.policy_version=? AND c.day_start_utc=? AND c.expires_at>?",
        (*base, current["policy_id"], current["version"], day_start, instant)).fetchall()
    valid_claims = []
    synthetic_claim = False
    for row in claims:
        if row["owner_pubkey"] != agent["owner"] or row["agent_id"] != agent["agent_id"]:
            continue
        try:
            decision = json.loads(row["decision_json"])
            if row["decision"] != "ALLOW" or decision["decision"] != "ALLOW":
                raise ValueError("Claim has no ALLOW decision")
        except (ValueError, KeyError, TypeError) as exc:
            raise SurplusError(409, "CLAIM_INTEGRITY_CONFLICT", "Stored claim decision is inconsistent") from exc
        last_approval = conn.execute(
            "SELECT e.action FROM spending_approval_events e JOIN spending_approvals a "
            "ON a.approval_id=e.approval_id WHERE a.decision_id=? ORDER BY e.rowid DESC LIMIT 1",
            (row["decision_id"],)).fetchone()
        if last_approval is None or last_approval["action"] not in ("REVOKE", "REJECT"):
            valid_claims.append(row)
            synthetic_claim |= decision.get("economic_evidence_status") == "SYNTHETIC_TEST"
    last_row = conn.execute(
        "SELECT max(observed_at) FROM economic_movements WHERE agent_account=? AND network=? "
        "AND genesis_hash=? AND program_id=? AND token_mint=? AND agent_id=? AND owner_pubkey=? AND observed_at<?",
        (*base, agent["agent_id"], agent["owner"], instant)).fetchone()
    latest = last_row[0] if last_row and last_row[0] is not None else None
    if costs:
        latest = max(latest or 0, max(r["incurred_at"] for r in costs))
    source_lineages = {r["evidence_lineage"] for r in costs}
    source_lineages.update(r[0] for r in conn.execute(
        "SELECT evidence_lineage FROM economic_movements WHERE agent_account=? AND network=? "
        "AND genesis_hash=? AND program_id=? AND token_mint=? AND agent_id=? AND owner_pubkey=?",
        (*base, agent["agent_id"], agent["owner"])).fetchall())
    if synthetic_claim:
        source_lineages.add("SYNTHETIC_TEST")
    provenance = ("SYNTHETIC_TEST" if "SYNTHETIC_TEST" in source_lineages else
                  "HISTORICAL_FIXTURE" if "HISTORICAL_FIXTURE" in source_lineages else
                  "HISTORICAL_UNVERIFIED")
    treasury = {"available_base_units_str": summary.available_balance_str if summary else None,
                "other_restrictions_base_units_str": "0", "data_as_of": latest,
                "provenance": provenance, "ownership_verified": False,
                "coverage_complete": False, "evidence_references": []}
    reservation = {"accounting_reserved_base_units_str": str(existing),
                   "eligible_policy_reserve_base_units_str": str(eligible),
                   "evidence_references": [r["reserve_id"] for r in reserves]}
    liability = {"outstanding_base_units_str": str(obligations), "not_reflected_in_treasury": True,
                 "coverage_complete": False,
                 "evidence_references": [r["cost_id"] for r in costs if r["cost_nature"] == "ACCRUED_LIABILITY" and r["status"] != "REVERTED"]}
    commitment = {"pending_base_units_str": str(sum(int(r["amount_base_units_str"]) for r in valid_claims)),
                  "independent_of_ledger_costs": not (valid_claims and any_realized),
                  "coverage_complete": False,
                  "evidence_references": [r["decision_id"] for r in valid_claims]}
    operating = {"observed_cash_opex_base_units_str": str(realized) if realized_ids else None,
                 "observed_days": 30, "window_start": start, "window_end": instant,
                 "independent_of_liabilities": not (any_realized and obligations),
                 "coverage_complete": False, "evidence_references": sorted(realized_ids)}
    solvency_rows = assess_solvency(ledger, agent["agent_account"], network=network,
        genesis_hash=genesis_hash, program_id=program_id, token_mint=token_mint,
        window=30, now=instant)
    solvency = solvency_rows[0] if len(solvency_rows) == 1 else None
    if solvency is not None:
        operating["solvency_context"] = {
            "assessment_id": solvency.get("assessment_id"),
            "calculation_status": solvency.get("calculation_status"),
            "conatus_ratio": solvency.get("conatus_ratio"),
            "operating_margin": solvency.get("operating_margin"),
            "runway_days": solvency.get("runway_days"),
            "provenance": solvency.get("provenance"),
        }
        operating["coverage_complete"] = (solvency.get("calculation_status") == "VALID" and
                                          solvency.get("data_coverage_status") == "COMPLETE")
        if (operating["coverage_complete"] and not realized_ids and
                solvency.get("verified_opex_base_units_str") == "0"):
            operating["observed_cash_opex_base_units_str"] = "0"
        if solvency.get("assessment_id"):
            operating["evidence_references"].append(solvency["assessment_id"])
    return assess_investible_surplus(context, treasury, reservation, liability, commitment,
        {"policy_id": current["policy_id"], "version": current["version"],
         "policy_hash": current["policy_hash"],
         "status": current["status"], "valid_from": current["valid_from"],
         "expires_at": current["expires_at"],
         "reserve_continuity_relation": "UNKNOWN",
         "minimum_reserve_base_units_str": rule["minimum_reserve_base_units_str"]},
        operating, {"name": scenario, "continuity_horizon_days": horizon_days}, instant)
