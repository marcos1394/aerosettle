"""CON-25: deterministic, read-only economic assessment over the existing ledger.

Windows are UTC Unix seconds [start, end). Income uses observed_at (economic
origin), costs use incurred_at. Reconciliation/attestation may occur later;
an assessment uses the verification state visible when it is calculated.
Only realized, attested operating costs are OPEX here. Accruals, estimates,
reserve movements, depreciation and CAPEX are separate. No FX is performed.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
import time
from dataclasses import dataclass
from decimal import Decimal, ROUND_DOWN, localcontext
from typing import Any, Callable

from .ledger import (
    EconomicLedger,
    IsolatedTestAttestationVerifier,
    IsolatedTestReconcilerVerifier,
    CoverageVerifier,
    DEFAULT_TRUSTED_COVERAGE_AUTHORITIES,
)
from .models import LedgerValidationError

METHODOLOGY_VERSION = "conatus-solvency-v1"
DEFAULT_THRESHOLDS = {"version": "conatus-thresholds-v1", "stable": "1", "thriving": "1.6"}
STATUSES = {"VALID", "INSUFFICIENT_DATA", "UNDEFINED_RATIO", "STALE_DATA", "MIXED_ASSET_CONTEXT", "ERROR"}


def _hash(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _ratio(numerator: int, denominator: int) -> str | None:
    if denominator == 0:
        return None
    with localcontext() as ctx:
        ctx.prec = 80
        value = (Decimal(numerator) / Decimal(denominator)).quantize(Decimal("0.00000001"), rounding=ROUND_DOWN)
    return format(value, "f")


def calculate_side_data_digest(
    ledger: EconomicLedger,
    agent_account: str,
    context: tuple[str, str, str, str] | dict[str, str],
    side: str,
    window_start: int,
    window_end: int,
) -> tuple[str, list[dict[str, Any]]]:
    """Calculate canonical deterministic data digest over relevant economic records for a window.

    Examines both eligible and excluded records (provisional, unverified, accruals, reversals)
    to detect any modification, late-arriving evidence, or tampering.
    """
    if isinstance(context, tuple):
        net, gen, prog, mint = context
    else:
        net = context["network"]
        gen = context["genesis_hash"]
        prog = context["program_id"]
        mint = context["token_mint"]

    scope = (agent_account, net, gen, prog, mint, window_start, window_end)
    canonical_records: list[dict[str, Any]] = []

    if side == "REVENUE":
        rows = ledger._conn.execute("""
            SELECT movement_id, idempotency_key, amount_base_units, nature,
                   observed_at, registered_at, status, provenance_source,
                   evidence_hash, tx_signature, external_ref, reversal_of_movement_id,
                   metadata_json
            FROM economic_movements
            WHERE agent_account=? AND network=? AND genesis_hash=? AND program_id=? AND token_mint=?
              AND nature='INCOME' AND observed_at>=? AND observed_at<?
            ORDER BY movement_id ASC
        """, scope).fetchall()

        for r in rows:
            meta = {}
            if r["metadata_json"]:
                try:
                    meta = json.loads(r["metadata_json"])
                except Exception:
                    meta = {"raw": str(r["metadata_json"])}

            canonical_records.append({
                "record_type": "movement",
                "movement_id": str(r["movement_id"]),
                "idempotency_key": str(r["idempotency_key"]),
                "amount_base_units": str(r["amount_base_units"]),
                "nature": str(r["nature"]),
                "observed_at": int(r["observed_at"]),
                "registered_at": int(r["registered_at"]),
                "status": str(r["status"]),
                "provenance_source": str(r["provenance_source"]),
                "evidence_hash": str(r["evidence_hash"] or ""),
                "tx_signature": str(r["tx_signature"] or ""),
                "external_ref": str(r["external_ref"] or ""),
                "reversal_of_movement_id": str(r["reversal_of_movement_id"] or ""),
                "metadata": meta,
            })

    elif side == "OPEX":
        rows = ledger._conn.execute("""
            SELECT cost_id, idempotency_key, movement_id, amount_base_units, category,
                   cost_nature, economic_period, incurred_at, created_at, status,
                   provenance_source, evidence_hash, attestation_id, reversal_of_cost_id,
                   metadata_json
            FROM agent_costs
            WHERE agent_account=? AND network=? AND genesis_hash=? AND program_id=? AND token_mint=?
              AND incurred_at>=? AND incurred_at<?
            ORDER BY cost_id ASC
        """, scope).fetchall()

        for r in rows:
            meta = {}
            if r["metadata_json"]:
                try:
                    meta = json.loads(r["metadata_json"])
                except Exception:
                    meta = {"raw": str(r["metadata_json"])}

            backing_status = ""
            backing_reversal = ""
            if r["movement_id"]:
                mov = ledger._conn.execute(
                    "SELECT status, reversal_of_movement_id FROM economic_movements WHERE movement_id = ?",
                    (r["movement_id"],)
                ).fetchone()
                if mov:
                    backing_status = str(mov["status"])
                    backing_reversal = str(mov["reversal_of_movement_id"] or "")

            canonical_records.append({
                "record_type": "cost",
                "cost_id": str(r["cost_id"]),
                "idempotency_key": str(r["idempotency_key"]),
                "movement_id": str(r["movement_id"] or ""),
                "amount_base_units": str(r["amount_base_units"]),
                "category": str(r["category"]),
                "cost_nature": str(r["cost_nature"]),
                "economic_period": str(r["economic_period"] or ""),
                "incurred_at": int(r["incurred_at"]),
                "created_at": int(r["created_at"]),
                "status": str(r["status"]),
                "provenance_source": str(r["provenance_source"]),
                "evidence_hash": str(r["evidence_hash"] or ""),
                "attestation_id": str(r["attestation_id"] or ""),
                "reversal_of_cost_id": str(r["reversal_of_cost_id"] or ""),
                "backing_movement_status": backing_status,
                "backing_movement_reversal": backing_reversal,
                "metadata": meta,
            })
    else:
        raise LedgerValidationError(f"Invalid side '{side}'; expected REVENUE or OPEX")

    payload = {
        "protocol": "conatus-solvency-data-digest-v1",
        "scope": {
            "agent_account": agent_account,
            "network": net,
            "genesis_hash": gen,
            "program_id": prog,
            "token_mint": mint,
            "side": side,
            "window_start": window_start,
            "window_end": window_end,
        },
        "record_count": len(canonical_records),
        "records": canonical_records,
    }
    canonical_json = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    data_digest = hashlib.sha256(canonical_json.encode("utf-8")).hexdigest()
    return data_digest, canonical_records


def methodology(thresholds: dict[str, str] | None = None) -> dict[str, Any]:
    config = thresholds or DEFAULT_THRESHOLDS
    return {
        "methodology_version": METHODOLOGY_VERSION,
        "threshold_config_version": config["version"],
        "thresholds": {"stable": config["stable"], "thriving": config["thriving"]},
        "window_semantics": "UTC Unix seconds [window_start, window_end)",
        "revenue_timestamp": "economic_movements.observed_at; verification state at calculation",
        "opex_timestamp": "agent_costs.incurred_at; REALIZED costs with verified attestation",
        "zero_coverage": "Both revenue and OPEX require exact-window independently verified completeness attestations, including for zero",
        "ratio": "verified realized income / verified realized operating expenses",
        "runway": "max(0, conservative treasury cash - outstanding obligations) / (verified realized cash OPEX / window days)",
        "precision": "base-unit integers; ratios truncated to 8 decimal places",
        "freshness_seconds": 7 * 86400,
        "exclusions": ["provisional", "reverted", "estimated", "accrued from OPEX", "depreciation", "reserve", "CAPEX"],
    }


def record_coverage(
    ledger: EconomicLedger, *, agent_account: str, network: str, genesis_hash: str,
    program_id: str, token_mint: str, side: str, window_start: int, window_end: int,
    evidence_hash: str, verifier_id: str,
    verifier: CoverageVerifier | None = None,
    data_digest: str | None = None,
    provenance_type: str = "SYNTHETIC_TEST",
    authority_pubkey: str | None = None,
    signature: str | None = None,
    verified_at: int | None = None,
    expires_at: int | None = None,
) -> str:
    """Trusted internal ingestion only. No public HTTP write route or test bypass.

    The supplied verifier must independently authenticate completeness of the
    named ledger source for the exact context and window, including true zeros.
    Arbitrary callables are strictly rejected; verifier must implement CoverageVerifier protocol.
    """
    if side not in ("REVENUE", "OPEX") or not 0 <= window_start < window_end:
        raise LedgerValidationError("Invalid coverage side or window")
    if not evidence_hash or not verifier_id:
        raise LedgerValidationError("Coverage needs verifier_id and evidence_hash")

    if verifier is not None:
        if callable(verifier) and not isinstance(verifier, CoverageVerifier):
            raise LedgerValidationError("Coverage verifier must implement CoverageVerifier protocol; arbitrary callables are not allowed")
        eff_verifier = verifier
    else:
        eff_verifier = getattr(ledger, "_coverage_verifier", None)

    if eff_verifier is None:
        raise LedgerValidationError("Coverage needs a configured CoverageVerifier")

    # Compute canonical data digest of the window from the ledger
    context = (network, genesis_hash, program_id, token_mint)
    calc_digest, _ = calculate_side_data_digest(ledger, agent_account, context, side, window_start, window_end)
    if data_digest is not None and data_digest != calc_digest:
        raise LedgerValidationError(f"Provided data_digest '{data_digest}' does not match canonical ledger digest '{calc_digest}'")
    eff_digest = calc_digest

    valid_provenances = {"LIVE_RPC", "EXTERNAL_ATTESTED", "HISTORICAL_FIXTURE", "SYNTHETIC_TEST"}
    if provenance_type not in valid_provenances:
        raise LedgerValidationError(f"Invalid provenance_type '{provenance_type}'; expected one of {valid_provenances}")

    v_time = int(time.time()) if verified_at is None else verified_at

    # Authenticate and verify via CoverageVerifier
    if not eff_verifier.verify_coverage(
        agent_account=agent_account,
        network=network,
        genesis_hash=genesis_hash,
        program_id=program_id,
        token_mint=token_mint,
        side=side,
        window_start=window_start,
        window_end=window_end,
        data_digest=eff_digest,
        evidence_hash=evidence_hash,
        verifier_id=verifier_id,
        provenance_type=provenance_type,
        signature=signature,
        authority_pubkey=authority_pubkey,
        expires_at=expires_at,
        verified_at=v_time,
    ):
        raise LedgerValidationError("Coverage verification failed")

    scope = dict(agent_account=agent_account, network=network, genesis_hash=genesis_hash,
                 program_id=program_id, token_mint=token_mint, side=side,
                 window_start=window_start, window_end=window_end, evidence_hash=evidence_hash,
                 verifier_id=verifier_id, data_digest=eff_digest, provenance_type=provenance_type,
                 expires_at=expires_at)
    coverage_id = _hash(scope)
    ledger._conn.execute(
        """INSERT OR IGNORE INTO solvency_coverage (
            coverage_id, agent_account, network, genesis_hash, program_id, token_mint,
            side, window_start, window_end, evidence_hash, verifier_id, verified_at,
            data_digest, provenance_type, authority_pubkey, signature, expires_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (coverage_id, agent_account, network, genesis_hash, program_id, token_mint,
         side, window_start, window_end, evidence_hash, verifier_id, v_time,
         eff_digest, provenance_type, authority_pubkey, signature, expires_at)
    )
    return coverage_id


def _contexts(ledger: EconomicLedger, agent: str, filters: dict[str, str | None]) -> list[tuple[str, str, str, str]]:
    rows = ledger._conn.execute("""
        SELECT network, genesis_hash, program_id, token_mint FROM economic_movements WHERE agent_account = ?
        UNION SELECT network, genesis_hash, program_id, token_mint FROM agent_costs WHERE agent_account = ?
        UNION SELECT network, genesis_hash, program_id, token_mint FROM agent_reserves WHERE agent_account = ?
        UNION SELECT network, genesis_hash, program_id, token_mint FROM solvency_coverage WHERE agent_account = ?
    """, (agent,) * 4).fetchall()
    return sorted(tuple(r) for r in rows if all(v != "PENDING_RESOLUTION" for v in tuple(r))
                  and all(not filters[k] or r[k] == filters[k] for k in filters))


def assess_agent(
    ledger: EconomicLedger, agent_account: str, *, network: str | None = None,
    genesis_hash: str | None = None, program_id: str | None = None,
    token_mint: str | None = None, window: int = 30, from_ts: int | None = None,
    to_ts: int | None = None, now: int | None = None,
    thresholds: dict[str, str] | None = None, consolidated: bool = False,
) -> list[dict[str, Any]]:
    """Return one assessment per complete monetary identity; never aggregate mints.

    `now` is injectable to reproduce a calculation; no RPC is contacted.
    """
    instant = int(time.time()) if now is None else now
    if window not in (7, 30, 90) or ((from_ts is None) != (to_ts is None)):
        raise LedgerValidationError("Window must be 7, 30 or 90 days, or a custom from_ts/to_ts pair")
    end = instant if to_ts is None else to_ts
    start = end - window * 86400 if from_ts is None else from_ts
    if not isinstance(start, int) or not isinstance(end, int) or start < 0 or end <= start or end > instant:
        raise LedgerValidationError("Invalid UTC window")
    config = thresholds or DEFAULT_THRESHOLDS
    if not config.get("version") or Decimal(config["stable"]) < 0 or Decimal(config["thriving"]) <= Decimal(config["stable"]):
        raise LedgerValidationError("Invalid threshold configuration")
    filters = dict(network=network, genesis_hash=genesis_hash, program_id=program_id, token_mint=token_mint)
    contexts = _contexts(ledger, agent_account, filters)
    if not contexts and all(filters.values()):
        contexts = [(network, genesis_hash, program_id, token_mint)]  # type: ignore[list-item]
    if consolidated and len(contexts) > 1:
        return [{"calculation_status": "MIXED_ASSET_CONTEXT", "sustainability_class": "UNDETERMINED",
                 "conatus_ratio": None, "window_start": start, "window_end": end,
                 "contexts": [dict(zip(("network", "genesis_hash", "program_id", "token_mint"), c)) for c in contexts]}]
    results = []
    for context in contexts:
        try:
            results.append(_assess_context(ledger, agent_account, context, start, end, instant, config))
        except (sqlite3.DatabaseError, ValueError, KeyError, TypeError, LedgerValidationError) as exc:
            net, gen, prog, mint = context
            failure_code = type(exc).__name__
            input_hash = _hash(["ERROR", failure_code, agent_account, context, start, end])
            results.append({
                "assessment_id": input_hash, "agent_account": agent_account, "network": net,
                "genesis_hash": gen, "program_id": prog, "token_mint": mint,
                "window_start": start, "window_end": end, "calculated_at": instant,
                "methodology_version": METHODOLOGY_VERSION,
                "threshold_config_version": config["version"],
                "conatus_ratio": None, "operating_margin": None,
                "operating_surplus_base_units_str": None,
                "available_liquidity_base_units_str": None,
                "total_reserved_base_units_str": None,
                "accrued_liabilities_base_units_str": None,
                "reserve_target_base_units_str": None,
                "reserve_gap_base_units_str": None,
                "reserve_sufficiency": "UNKNOWN", "eligible_liquid_capital_base_units_str": None,
                "runway_days": None, "sustainability_class": "UNDETERMINED",
                "calculation_status": "ERROR", "data_coverage_status": "UNKNOWN",
                "input_revenue_count": 0, "input_expense_count": 0,
                "verified_revenue_base_units_str": None, "verified_opex_base_units_str": None,
                "exclusion_reasons": [f"processing_error:{failure_code}"], "evidence_references": [],
                "input_hash": input_hash, "provenance": "LEDGER_INTEGRITY_ERROR",
                "net_worth_verified_base_units_str": None,
                "provisional_book_value_base_units_str": None,
            })
    return results


def _assess_context(ledger: EconomicLedger, agent: str, context: tuple[str, str, str, str],
                    start: int, end: int, now: int, config: dict[str, str]) -> dict[str, Any]:
    net, gen, prog, mint = context
    scope = (agent, net, gen, prog, mint)
    revenue_rows = ledger._conn.execute("""
        SELECT movement_id, amount_base_units, observed_at, registered_at, status,
               provenance_source, evidence_hash, metadata_json FROM economic_movements
        WHERE agent_account=? AND network=? AND genesis_hash=? AND program_id=? AND token_mint=?
          AND nature='INCOME' AND observed_at>=? AND observed_at<? ORDER BY movement_id
    """, scope + (start, end)).fetchall()
    cost_rows = ledger._conn.execute("""
        SELECT cost_id, movement_id, amount_base_units, incurred_at, created_at, category,
               cost_nature, status, provenance_source, evidence_hash, attestation_id
        FROM agent_costs WHERE agent_account=? AND network=? AND genesis_hash=? AND program_id=?
          AND token_mint=? AND incurred_at>=? AND incurred_at<? ORDER BY cost_id
    """, scope + (start, end)).fetchall()
    cov_rows = ledger._conn.execute("""
        SELECT coverage_id, side, verified_at, evidence_hash, verifier_id,
               data_digest, provenance_type, authority_pubkey, signature, expires_at
        FROM solvency_coverage
        WHERE agent_account=? AND network=? AND genesis_hash=? AND program_id=? AND token_mint=?
          AND window_start=? AND window_end=? ORDER BY verified_at DESC, rowid DESC
    """, scope + (start, end)).fetchall()

    # Deterministic canonical data digests of the relevant economic records
    current_rev_digest, _ = calculate_side_data_digest(ledger, agent, context, "REVENUE", start, end)
    current_opex_digest, _ = calculate_side_data_digest(ledger, agent, context, "OPEX", start, end)

    revenue = [r for r in revenue_rows if r["status"] == "RECONCILED" and r["evidence_hash"]
               and r["provenance_source"] in ("ONCHAIN_VERIFIED", "SETTLEMENT_EVENT")
               and json.loads(r["metadata_json"] or "{}").get("reconciliation")]
    expenses = [r for r in cost_rows if r["cost_nature"] == "REALIZED"
                and r["category"] != "DEPRECIATION_REPLACEMENT" and r["status"] == "RECONCILED"
                and r["provenance_source"] == "EXTERNAL_VERIFIED" and r["attestation_id"]
                and r["evidence_hash"] and r["movement_id"]]
    # Verify that a cost's backing movement has not been reverted independently.
    if expenses:
        ids = [r["movement_id"] for r in expenses]
        placeholders = ",".join("?" for _ in ids)
        valid_ids = {r["movement_id"] for r in ledger._conn.execute(
            f"SELECT movement_id FROM economic_movements WHERE movement_id IN ({placeholders}) AND status='RECONCILED'", ids)}
        expenses = [r for r in expenses if r["movement_id"] in valid_ids]
    rev_sum = sum(int(r["amount_base_units"]) for r in revenue)
    exp_sum = sum(int(r["amount_base_units"]) for r in expenses)
    excluded = []
    if any(r["status"] == "PROVISIONAL" for r in revenue_rows): excluded.append("provisional_revenue")
    if any(r["status"] == "PROVISIONAL" or r["cost_nature"] == "ESTIMATED" for r in cost_rows): excluded.append("unverified_or_estimated_cost")
    if any(r["cost_nature"] == "ACCRUED_LIABILITY" for r in cost_rows): excluded.append("accrual_separate_from_realized_opex")
    if any(r["category"] == "DEPRECIATION_REPLACEMENT" for r in cost_rows): excluded.append("noncash_depreciation")
    if len(revenue) < len([r for r in revenue_rows if r["status"] != "REVERTED"]): excluded.append("revenue_evidence_incomplete")
    if len(expenses) < len([r for r in cost_rows if r["cost_nature"] == "REALIZED" and r["category"] != "DEPRECIATION_REPLACEMENT" and r["status"] != "REVERTED"]): excluded.append("expense_evidence_incomplete")

    # Cryptographic revalidation and selection across candidates
    active_verifier = getattr(ledger, "_coverage_verifier", None)
    trusted_authorities = getattr(ledger, "_trusted_coverage_authorities", set())
    if active_verifier and hasattr(active_verifier, "trusted_authorities"):
        trusted_authorities = trusted_authorities | set(active_verifier.trusted_authorities)

    coverage = {}
    side_digest = {
        "REVENUE": current_rev_digest,
        "OPEX": current_opex_digest,
    }

    if not trusted_authorities:
        excluded.append("no_trusted_coverage_authorities_configured")

    for side in ("REVENUE", "OPEX"):
        expected_digest = side_digest[side]
        candidates = [r for r in cov_rows if r["side"] == side]
        valid_selected = None

        if not candidates:
            excluded.append(f"{side.lower()}_coverage_missing")
            continue

        for r in candidates:
            # Check authority
            if not trusted_authorities or r["verifier_id"] not in trusted_authorities:
                continue
            # Check revocation
            if active_verifier and hasattr(active_verifier, "is_authority_revoked"):
                if active_verifier.is_authority_revoked(r["verifier_id"]):
                    continue
            # Check digest presence & match
            if not r["data_digest"] or r["provenance_type"] == "HISTORICAL_UNVERIFIED":
                continue
            if r["data_digest"] != expected_digest:
                continue
            # Check expiration
            if r["expires_at"] is not None and now > r["expires_at"]:
                continue

            # Cryptographic and protocol verification against active verifier
            if active_verifier:
                try:
                    is_valid = active_verifier.verify_coverage(
                        agent_account=agent,
                        network=net,
                        genesis_hash=gen,
                        program_id=prog,
                        token_mint=mint,
                        side=side,
                        window_start=start,
                        window_end=end,
                        data_digest=r["data_digest"],
                        evidence_hash=r["evidence_hash"],
                        verifier_id=r["verifier_id"],
                        provenance_type=r["provenance_type"],
                        signature=r["signature"],
                        authority_pubkey=r["authority_pubkey"],
                        expires_at=r["expires_at"],
                        verified_at=r["verified_at"],
                        now=now,
                    )
                except Exception:
                    is_valid = False
                if not is_valid:
                    continue

            # Candidate passed all validity, freshness, revocation and crypto checks
            valid_selected = r
            break

        if valid_selected is not None:
            coverage[side] = valid_selected
        else:
            # Diagnose reason for exclusion
            if any(r["provenance_type"] == "HISTORICAL_UNVERIFIED" or not r["data_digest"] for r in candidates):
                excluded.append(f"{side.lower()}_coverage_missing_verifiable_digest")
            elif any(r["data_digest"] != expected_digest for r in candidates):
                excluded.append(f"{side.lower()}_coverage_digest_mismatch")
            elif any(active_verifier and hasattr(active_verifier, "is_authority_revoked") and active_verifier.is_authority_revoked(r["verifier_id"]) for r in candidates):
                excluded.append(f"{side.lower()}_coverage_authority_revoked")
            elif any(r["expires_at"] is not None and now > r["expires_at"] for r in candidates):
                excluded.append(f"{side.lower()}_coverage_expired")
            elif any(r["verifier_id"] not in trusted_authorities for r in candidates):
                excluded.append(f"untrusted_coverage_authority:{candidates[0]['verifier_id']}")
            else:
                excluded.append(f"{side.lower()}_coverage_verification_failed")

    revenue_complete = bool(coverage.get("REVENUE") is not None)
    expense_complete = bool(coverage.get("OPEX") is not None)

    if excluded and any(x in excluded for x in (
        "provisional_revenue", "unverified_or_estimated_cost",
        "revenue_evidence_incomplete", "expense_evidence_incomplete",
        "revenue_coverage_digest_mismatch", "opex_coverage_digest_mismatch",
        "revenue_coverage_missing_verifiable_digest", "opex_coverage_missing_verifiable_digest",
        "no_trusted_coverage_authorities_configured",
        "revenue_coverage_verification_failed", "opex_coverage_verification_failed",
        "revenue_coverage_authority_revoked", "opex_coverage_authority_revoked",
        "revenue_coverage_expired", "opex_coverage_expired",
    )):
        status = "INSUFFICIENT_DATA"
    elif not revenue_complete or not expense_complete:
        status = "INSUFFICIENT_DATA"
    elif end >= now - 1 and max([r["observed_at"] for r in revenue] + [r["incurred_at"] for r in expenses]
                                   + [r["verified_at"] for r in cov_rows], default=0) < now - 7 * 86400:
        status = "STALE_DATA"
    elif exp_sum == 0:
        status = "UNDEFINED_RATIO"
    else:
        status = "VALID"
    summaries = ledger.get_economic_summary(agent, network=net, genesis_hash=gen, program_id=prog, token_mint=mint)
    summary = summaries[0] if summaries else None
    available = summary.available_balance if summary else None
    reserved = summary.total_capital_reserved if summary else None
    liabilities = summary.total_obligations_accrued if summary else None
    reserve_rows = ledger._conn.execute("""SELECT reserve_id, target_amount_base_units FROM agent_reserves
        WHERE agent_account=? AND network=? AND genesis_hash=? AND program_id=? AND token_mint=?
          AND status IN ('ACTIVE', 'DEPLETED')""", scope).fetchall()
    target = sum(int(r["target_amount_base_units"]) for r in reserve_rows)
    eligible = max(0, available - liabilities) if available is not None and liabilities is not None else None
    ratio = _ratio(rev_sum, exp_sum) if status == "VALID" else None
    margin = _ratio(rev_sum - exp_sum, rev_sum) if status == "VALID" and rev_sum else None
    runway = _ratio(eligible * (end - start), exp_sum * 86400) if status == "VALID" and eligible is not None else None
    classification = "UNDETERMINED"
    if ratio is not None:
        raw_ratio = Decimal(rev_sum) / Decimal(exp_sum)
        classification = "THRIVING" if raw_ratio >= Decimal(config["thriving"]) else "STABLE" if raw_ratio >= Decimal(config["stable"]) else "AT_RISK"
    active_covs = [c for c in (coverage.get("REVENUE"), coverage.get("OPEX")) if c is not None]
    refs = ([{"kind": "movement", "id": r["movement_id"], "evidence_hash": r["evidence_hash"]} for r in revenue]
            + [{"kind": "cost", "id": r["cost_id"], "evidence_hash": r["evidence_hash"]} for r in expenses]
            + [{"kind": "coverage", "id": r["coverage_id"], "evidence_hash": r["evidence_hash"]} for r in active_covs])
    refs = sorted(refs, key=lambda r: (r["kind"], r["id"]))
    sources = sorted({json.loads(r["metadata_json"] or "{}").get("evidence_source", "UNSPECIFIED_RECONCILER")
                      for r in revenue_rows if r in revenue})
    if expenses:
        sources.append("EXTERNAL_COST_ATTESTATION")

    # Persistent provenance determination independent of in-memory classes
    cov_provenances = {r["provenance_type"] for r in active_covs}
    movement_sources = set()
    for r in revenue:
        source = r["provenance_source"]
        meta_src = json.loads(r["metadata_json"] or "{}").get("evidence_source")
        if meta_src:
            movement_sources.add(meta_src)
        else:
            movement_sources.add(source)
    expense_sources = {r["provenance_source"] for r in expenses}
    all_markers = cov_provenances | movement_sources | expense_sources

    if "SYNTHETIC_TEST" in all_markers or "TEST_VERIFIER_FIXTURE" in all_markers:
        provenance = "SYNTHETIC_TEST"
    elif "HISTORICAL_FIXTURE" in all_markers:
        provenance = "HISTORICAL_FIXTURE"
    elif ("LIVE_RPC" in all_markers or "ONCHAIN_VERIFIED" in all_markers or "SETTLEMENT_EVENT" in all_markers) and all(s in ("LIVE_RPC", "EXTERNAL_VERIFIED", "EXTERNAL_ATTESTED", "ONCHAIN_VERIFIED", "SETTLEMENT_EVENT") for s in all_markers):
        if any(s in ("EXTERNAL_VERIFIED", "EXTERNAL_ATTESTED") for s in all_markers):
            provenance = "LIVE_RPC_AND_EXTERNAL_ATTESTED"
        else:
            provenance = "LIVE_RPC"
    elif all_markers and all(s in ("EXTERNAL_VERIFIED", "EXTERNAL_ATTESTED") for s in all_markers):
        provenance = "EXTERNAL_ATTESTED"
    else:
        provenance = "HISTORICAL_UNVERIFIED"

    input_hash = _hash({"refs": refs, "sources": sources, "status": status, "revenue": str(rev_sum), "opex": str(exp_sum),
                        "cash": str(available), "reserved": str(reserved), "liabilities": str(liabilities)})
    assessment_id = _hash([METHODOLOGY_VERSION, config, scope, start, end, input_hash])
    return {
        "assessment_id": assessment_id, "agent_account": agent, "network": net, "genesis_hash": gen,
        "program_id": prog, "token_mint": mint, "window_start": start, "window_end": end,
        "calculated_at": now, "methodology_version": METHODOLOGY_VERSION,
        "threshold_config_version": config["version"], "conatus_ratio": ratio,
        "operating_margin": margin, "operating_surplus_base_units_str": str(rev_sum - exp_sum) if status == "VALID" else None,
        "available_liquidity_base_units_str": str(available) if available is not None else None,
        "total_reserved_base_units_str": str(reserved) if reserved is not None else None,
        "accrued_liabilities_base_units_str": str(liabilities) if liabilities is not None else None,
        "reserve_target_base_units_str": str(target) if reserve_rows else None,
        "reserve_gap_base_units_str": str(max(0, target - (reserved or 0))) if reserve_rows else None,
        "reserve_sufficiency": ("UNCONFIGURED" if not reserve_rows else
                                "SUFFICIENT" if reserved is not None and reserved >= target else "INSUFFICIENT"),
        "eligible_liquid_capital_base_units_str": str(eligible) if eligible is not None else None,
        "runway_days": runway, "sustainability_class": classification, "calculation_status": status,
        "data_coverage_status": "COMPLETE" if revenue_complete and expense_complete and status not in ("INSUFFICIENT_DATA", "ERROR") else "INCOMPLETE",
        "input_revenue_count": len(revenue), "input_expense_count": len(expenses),
        "verified_revenue_base_units_str": str(rev_sum), "verified_opex_base_units_str": str(exp_sum),
        "exclusion_reasons": sorted(set(excluded)), "evidence_references": refs,
        "input_hash": input_hash, "provenance": provenance, "provenance_type": provenance,
        "revenue_data_digest": current_rev_digest, "opex_data_digest": current_opex_digest,
        "input_evidence_sources": sources,
        "cash_policy": "reconciled treasury debits less all treasury credits; conservative ledger balance",
        "net_worth_verified_base_units_str": None,
        "provisional_book_value_base_units_str": str(summary.total_effective_balance) if summary else None,
    }


def save_assessment(ledger: EconomicLedger, assessment: dict[str, Any]) -> None:
    """Store an immutable result snapshot; never duplicate source ledger amounts in tables."""
    if assessment.get("calculation_status") == "MIXED_ASSET_CONTEXT":
        raise LedgerValidationError("A mixed context cannot be saved as an agent assessment")
    prov = assessment.get("provenance_type") or assessment.get("provenance") or "HISTORICAL_UNVERIFIED"
    ledger._conn.execute("""
        INSERT OR IGNORE INTO agent_solvency_assessments (
            assessment_id, agent_account, network, genesis_hash, program_id, token_mint,
            window_start, window_end, calculated_at, methodology_version,
            threshold_config_version, input_hash, provenance_type, result_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, tuple(assessment[k] for k in ("assessment_id", "agent_account", "network", "genesis_hash",
                                       "program_id", "token_mint", "window_start", "window_end", "calculated_at",
                                       "methodology_version", "threshold_config_version", "input_hash"))
        + (prov, json.dumps(assessment, sort_keys=True)))


def assessment_history(ledger: EconomicLedger, agent_account: str, *, network: str | None = None,
                       genesis_hash: str | None = None, program_id: str | None = None,
                       token_mint: str | None = None, limit: int = 50) -> list[dict[str, Any]]:
    if not 1 <= limit <= 100:
        raise LedgerValidationError("limit must be 1..100")
    filters = {"network": network, "genesis_hash": genesis_hash, "program_id": program_id, "token_mint": token_mint}
    conditions = ["agent_account=?"]
    values: list[Any] = [agent_account]
    for key, value in filters.items():
        if value:
            conditions.append(f"{key}=?")
            values.append(value)
    rows = ledger._conn.execute(f"SELECT result_json FROM agent_solvency_assessments WHERE {' AND '.join(conditions)} ORDER BY calculated_at DESC, assessment_id DESC LIMIT ?", values + [limit]).fetchall()
    return [json.loads(r["result_json"]) for r in rows]
