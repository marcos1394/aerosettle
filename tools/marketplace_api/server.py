#!/usr/bin/env python3
"""AeroSettle Marketplace API: read-only local HTTP service."""
from __future__ import annotations

import argparse
import json
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools" / "discovery"))

import agent_discovery as discovery
import rust_matching
import cursor_pagination
import openapi_spec

from tools.economic_ledger.auth import AuthError, verify_request_auth
from tools.economic_ledger.budget_policies import (
    BudgetPolicyStore, PolicyError, validate_control, verify_mutation,
)
from tools.economic_ledger.ledger import EconomicLedger
from tools.economic_ledger.spending_decisions import (
    DecisionError, SpendingDecisionStore, SpendingProposal, verify_evaluation,
)
from tools.economic_ledger.spending_approvals import (
    ApprovalError, SpendingApprovalStore, validate_mutation, verify_approval,
)
from tools.economic_ledger.solvency import assess_agent, assessment_history, methodology, save_assessment
from tools.economic_ledger.investible_surplus import (
    SurplusError, assess_agent_surplus, methodology as surplus_methodology,
)
from tools.economic_ledger.models import (
    LedgerValidationError,
    MovementNature,
    MovementStatus,
    ProvenanceSource,
)
from tools.paper_trading.providers import DeterministicFixtureProvider
from tools.paper_trading.simulator import METHODOLOGY_VERSION as PAPER_METHODOLOGY_VERSION, PaperError, SHOCKS
from tools.paper_trading.store import PaperSimulationStore, verify_paper_signature
from tools.organizations.signatures import OrganizationError, ORG_ID, verify_mutation as verify_organization_mutation, verify_read as verify_organization_read
from tools.organizations.store import OrganizationStore, READ_PERMISSION, _fresh_agent
from tools.governance.signatures import GovernanceError, verify_mutation as verify_governance_mutation
from tools.governance.store import GovernanceStore

_DEFAULT_LEDGER: EconomicLedger | None = None
_POLICY_STORE_INIT_LOCK = threading.Lock()


def get_ledger(provider=None) -> EconomicLedger:
    global _DEFAULT_LEDGER
    if provider is not None and hasattr(provider, "ledger") and provider.ledger is not None:
        return provider.ledger
    if _DEFAULT_LEDGER is None:
        _DEFAULT_LEDGER = EconomicLedger()
    return _DEFAULT_LEDGER


def get_policy_store(provider=None) -> BudgetPolicyStore:
    ledger = get_ledger(provider)
    with _POLICY_STORE_INIT_LOCK:
        if not hasattr(ledger, "_budget_policy_store"):
            ledger._budget_policy_store = BudgetPolicyStore(ledger)
    return ledger._budget_policy_store


def get_spending_store(provider=None) -> SpendingDecisionStore:
    ledger = get_ledger(provider)
    policy_store = get_policy_store(provider)
    with _POLICY_STORE_INIT_LOCK:
        if not hasattr(ledger, "_spending_decision_store"):
            ledger._spending_decision_store = SpendingDecisionStore(ledger, policy_store)
    return ledger._spending_decision_store


def get_approval_store(provider=None) -> SpendingApprovalStore:
    ledger = get_ledger(provider)
    policy_store = get_policy_store(provider)
    spending_store = get_spending_store(provider)
    with _POLICY_STORE_INIT_LOCK:
        if not hasattr(ledger, "_spending_approval_store"):
            ledger._spending_approval_store = SpendingApprovalStore(ledger, policy_store, spending_store)
    return ledger._spending_approval_store


def get_paper_store(provider=None) -> PaperSimulationStore:
    ledger = get_ledger(provider)
    with _POLICY_STORE_INIT_LOCK:
        if not hasattr(ledger, "_paper_simulation_store"):
            paper_path = ledger.db_path.with_name("paper_trading.sqlite") if ledger.db_path else ":memory:"
            ledger._paper_simulation_store = PaperSimulationStore(paper_path)
    return ledger._paper_simulation_store


def get_organization_store(provider=None) -> OrganizationStore:
    ledger = get_ledger(provider)
    with _POLICY_STORE_INIT_LOCK:
        return get_organization_store_unlocked(ledger, provider)


def get_governance_store(provider=None) -> GovernanceStore:
    ledger = get_ledger(provider)
    with _POLICY_STORE_INIT_LOCK:
        if not hasattr(ledger, "_governance_store"):
            ledger._governance_store = GovernanceStore(get_organization_store_unlocked(ledger, provider))
    return ledger._governance_store


def get_organization_store_unlocked(ledger, provider) -> OrganizationStore:
    if not hasattr(ledger, "_organization_store"):
        path = ledger.db_path.with_name("organizations.sqlite") if ledger.db_path else ":memory:"
        def current_snapshot():
            return {**provider.snapshot(), "network": "localnet", "genesis_hash": provider.health()}
        ledger._organization_store = OrganizationStore(path, current_snapshot)
    return ledger._organization_store


def governance_read_route(url: str, provider, headers: dict | None) -> tuple[int, dict]:
    parts = urlsplit(url)
    pieces = [piece for piece in parts.path.split("/") if piece]
    if parts.query or parts.fragment or len(pieces) < 4 or not ORG_ID.fullmatch(pieces[2]):
        raise ApiError(404, "NOT_FOUND", "Unknown governance route")
    try:
        actor = verify_organization_read(parts.path, headers)
        section = "overview" if len(pieces) == 4 else pieces[4] if len(pieces) == 5 else None
        proposal_id = None
        if len(pieces) == 6 and pieces[4] == "proposals":
            section, proposal_id = "proposal", pieces[5]
        elif len(pieces) == 7 and pieces[4] == "proposals" and pieces[6] == "votes":
            section, proposal_id = "votes", pieces[5]
        if section not in {"overview", "bylaws", "proposals", "proposal", "votes", "disputes",
                           "distributions", "audit-events"}:
            raise GovernanceError(404, "NOT_FOUND", "Unknown governance resource")
        data = get_governance_store(provider).read(pieces[2], actor, section, proposal_id)
    except OrganizationError as exc:
        raise ApiError(exc.status, exc.code, str(exc)) from exc
    return 200, {"data": data, "meta": metadata(provider.snapshot())}


def governance_mutation_route(url: str, provider, headers: dict, body: dict) -> tuple[int, dict]:
    parts = urlsplit(url)
    pieces = [piece for piece in parts.path.split("/") if piece]
    if (parts.query or parts.fragment or len(pieces) != 5 or pieces[3:] != ["governance", "actions"] or
            not ORG_ID.fullmatch(pieces[2])):
        raise ApiError(405, "METHOD_NOT_ALLOWED", "Only signed governance actions are supported")
    try:
        actor, message, signature = verify_governance_mutation(parts.path, body, headers)
        data, created = get_governance_store(provider).mutate(body, signature, message, actor)
    except (OrganizationError, ValueError) as exc:
        if isinstance(exc, OrganizationError):
            raise ApiError(exc.status, exc.code, str(exc)) from exc
        raise ApiError(422, "INVALID_GOVERNANCE_RULE", str(exc)) from exc
    meta = metadata(provider.snapshot())
    meta["read_only"] = False
    return (201 if created else 200), {"data": data, "meta": meta}


def organization_read_route(url: str, provider, headers: dict | None) -> tuple[int, dict]:
    parts = urlsplit(url)
    pieces = [piece for piece in parts.path.split("/") if piece]
    if parts.query or parts.fragment:
        raise ApiError(400, "INVALID_QUERY", "Organization reads do not accept query parameters")
    try:
        actor = verify_organization_read(parts.path, headers)
        if len(pieces) == 2:
            data = get_organization_store(provider).list_for(actor)
        elif len(pieces) == 4 and pieces[2] == "agent-registration":
            require_pubkey(pieces[3])
            data = _fresh_agent(lambda: {**provider.snapshot(), "network": "localnet",
                "genesis_hash": provider.health()}, pieces[3])
            if data is None:
                raise OrganizationError(404, "NOT_FOUND", "Agent registration unavailable")
        elif len(pieces) in (3, 4) and ORG_ID.fullmatch(pieces[2]):
            section = pieces[3] if len(pieces) == 4 else None
            if section is not None and section not in READ_PERMISSION:
                raise OrganizationError(404, "NOT_FOUND", "Unknown organization resource")
            data = get_organization_store(provider).read(pieces[2], actor, section)
        else:
            raise OrganizationError(404, "NOT_FOUND", "Unknown organization resource")
    except OrganizationError as exc:
        raise ApiError(exc.status, exc.code, str(exc)) from exc
    return 200, {"data": data, "meta": metadata(provider.snapshot())}


def organization_mutation_route(method: str, url: str, provider, headers: dict,
                                body: dict) -> tuple[int, dict]:
    parts = urlsplit(url)
    pieces = [piece for piece in parts.path.split("/") if piece]
    if (method != "POST" or parts.query or parts.fragment or
            not (pieces == ["v1", "organizations"] or
                 len(pieces) == 4 and pieces[:2] == ["v1", "organizations"] and
                 pieces[3] == "actions" and ORG_ID.fullmatch(pieces[2]))):
        raise ApiError(405, "METHOD_NOT_ALLOWED", "Only signed organization POST is supported")
    try:
        actor, message = verify_organization_mutation(method, parts.path, body, headers)
        signature = next((str(value) for key, value in headers.items() if str(key).lower() == "x-signature"), "")
        result, created = get_organization_store(provider).mutate(body, signature, message, actor)
    except OrganizationError as exc:
        raise ApiError(exc.status, exc.code, str(exc)) from exc
    meta = metadata(provider.snapshot())
    meta["read_only"] = False
    return (201 if created else 200), {"data": result, "meta": meta}


def authorize_agent_access(agent: dict, headers: dict | None, agent_account: str | None = None) -> str:
    """Enforce authentic Ed25519 cryptographic authorization for agent economic access."""
    acc = agent_account or agent.get("agent_account", "")
    try:
        return verify_request_auth(headers, agent, acc)
    except AuthError as exc:
        raise ApiError(exc.status, exc.code, str(exc)) from exc


def authorize_evaluation_read(agent: dict, headers: dict | None, account: str) -> str:
    signer = {str(k).lower(): str(v) for k, v in headers.items()}.get("x-signer-pubkey") if headers else None
    if not agent.get("owner"):
        raise ApiError(403, "FORBIDDEN", "Current owner is unavailable")
    if signer and signer not in (agent["owner"], agent.get("signing_authority")):
        raise ApiError(403, "FORBIDDEN", "Requester is not authorized for this agent")
    try:
        return verify_request_auth(headers, {"owner": signer}, account)
    except AuthError as exc:
        raise ApiError(exc.status, exc.code, str(exc)) from exc

PROGRAM_ID = "CeA1P1NSuPLUH31KsT4j3pZeBsknQZ3NSC6GUAqcsCLy"
GENESIS = "HP9XKTusRPGC78EFDpR9xdEq6simL2vqyDdrMvn6Vacg"

STATUSES = frozenset({
    "Draft", "Open", "Claimed",
    "Submitted", "Verified", "Settled",
})


class ApiError(Exception):
    def __init__(self, status: int, code: str, message: str):
        super().__init__(message)
        self.status = status
        self.code = code


def require_pubkey(value: str) -> None:
    try:
        if len(value) > 50:
            raise ValueError("too long")
        discovery.b58decode(value, 32)
    except (discovery.DiscoveryError, ValueError) as exc:
        raise ApiError(
            400,
            "INVALID_PUBKEY",
            "Expected a canonical Solana pubkey",
        ) from exc


def metadata(snapshot: dict) -> dict:
    return {
        "program_id": snapshot["program_id"],
        "commitment": snapshot["commitment"],
        "chain_now_unix": snapshot["now_unix"],
        "rpc_context_slots": snapshot["rpc_context_slots"],
        "atomic_snapshot": False,
        "read_only": True,
        "matching_engine": "rust-epic-3.1",
        "matching_authority": "claim_work_order on-chain",
    }


def projected_agent(agent: dict) -> dict:
    return {
        **agent,
        "capabilities": str(agent["capabilities"]),
    }


def discoverable(order: dict, snapshot: dict) -> bool:
    return (
        not snapshot["protocol_paused"]
        and order["is_open"]
        and snapshot["now_unix"] < order["execution_deadline"]
    )


def projected_order(order: dict, snapshot: dict) -> dict:
    return {
        **order,
        "required_capabilities": str(
            order["required_capabilities"]
        ),
        "discoverable": discoverable(order, snapshot),
    }


def rejection(
    order: dict,
    agent: dict,
    snapshot: dict,
) -> dict | None:
    """Mirror the EPIC 3.1 eligibility predicate."""
    if snapshot["protocol_paused"]:
        return {"code": "PROTOCOL_PAUSED"}

    if not order["is_open"]:
        return {"code": "WORK_ORDER_NOT_OPEN"}

    if snapshot["now_unix"] >= order["execution_deadline"]:
        return {"code": "EXECUTION_DEADLINE_REACHED"}

    if order["protocol_config"] != agent["protocol_config"]:
        return {"code": "DIFFERENT_PROTOCOL"}

    if not agent["active"]:
        return {"code": "AGENT_INACTIVE"}

    missing = (
        order["required_capabilities"]
        & ~agent["capabilities"]
    )

    if missing:
        return {
            "code": "MISSING_CAPABILITIES",
            "missing_mask": str(missing),
        }

    return None


def decision_set(order: dict, snapshot: dict, matcher) -> dict:
    """Use Rust matching, cross-check against Discovery, fail closed."""
    result = matcher(order, snapshot)

    rejections = result["rejections_by_agent"]
    shortlisted = result["eligible_agent_accounts"]

    lookup = {
        agent["agent_account"]: agent
        for agent in snapshot["agents"]
    }

    if (
        len(lookup) != len(snapshot["agents"])
        or set(rejections) != set(lookup)
        or len(set(shortlisted)) != len(shortlisted)
        or any(
            account not in lookup
            for account in shortlisted
        )
        or set(shortlisted) != {
            account
            for account, reason in rejections.items()
            if reason is None
        }
    ):
        raise ApiError(
            502,
            "INVALID_RUST_MATCHING",
            "Rust matching response is inconsistent",
        )

    expected = snapshot["eligible_agents_by_order"].get(
        order["work_order_account"], []
    )

    if sorted(shortlisted) != sorted(expected):
        raise ApiError(
            502,
            "MATCHING_MISMATCH",
            "Rust and Discovery matching disagree",
        )

    return {
        "eligible_agents": [
            projected_agent(lookup[account])
            for account in shortlisted
        ],
        "evaluations": [
            {
                "agent_account": agent["agent_account"],
                "eligible":
                    rejections[agent["agent_account"]] is None,
                "rejection":
                    rejections[agent["agent_account"]],
            }
            for agent in snapshot["agents"]
        ],
    }



def capability_mask(value):
    if value is None:
        return None

    if (
        not isinstance(value, str)
        or not value
        or len(value) > 20
        or (
            value != "0"
            and (
                not value.isascii()
                or not value.isdecimal()
                or value.startswith("0")
            )
        )
    ):
        raise ApiError(
            400, "INVALID_CAPABILITIES",
            "Expected an unsigned decimal u64 mask",
        )

    mask = int(value)

    if mask > (1 << 64) - 1:
        raise ApiError(
            400, "INVALID_CAPABILITIES",
            "Capability mask exceeds u64",
        )

    return mask


def paged_collection(items, key, query, scope):
    try:
        return cursor_pagination.paginate(
            items,
            key,
            limit=query.get("limit"),
            cursor=query.get("cursor"),
            scope=scope,
        )
    except cursor_pagination.CursorError as exc:
        raise ApiError(
            exc.status, exc.code, str(exc)
        ) from exc


def arguments(
    raw_query: str,
    allowed: set[str],
) -> dict[str, str]:
    try:
        values = parse_qs(
            raw_query,
            keep_blank_values=True,
            strict_parsing=True,
        )
    except ValueError as exc:
        raise ApiError(
            400, "INVALID_QUERY", "Malformed query string"
        ) from exc

    if (
        set(values) - allowed
        or any(len(items) != 1 for items in values.values())
    ):
        raise ApiError(
            400,
            "INVALID_QUERY",
            "Unexpected or duplicate query parameters",
        )

    return {
        key: entries[0]
        for key, entries in values.items()
    }


def route(url: str, provider, headers: dict | None = None) -> tuple[int, dict]:
    if len(url) > 2048:
        raise ApiError(
            414, "URI_TOO_LONG", "Request URI too long"
        )

    parts = urlsplit(url)

    if parts.fragment:
        raise ApiError(
            400, "INVALID_QUERY", "Fragments not allowed"
        )

    pieces = [
        piece for piece in parts.path.split("/")
        if piece
    ]

    if pieces == ["openapi.json"]:
        arguments(parts.query, set())
        return 200, openapi_spec.build()

    if pieces == ["health"]:
        arguments(parts.query, set())
        return 200, {
            "status": "ok",
            "service": "aerosettle-marketplace",
            "genesis": provider.health(),
        }

    if len(pieces) < 2 or pieces[0] != "v1":
        raise ApiError(404, "NOT_FOUND", "Unknown route")

    entity = pieces[1]

    if entity not in {
        "agents", "work-orders", "marketplace", "economic-movements", "costs", "reserves", "paper-trading", "organizations"
    }:
        raise ApiError(404, "NOT_FOUND", "Unknown resource")

    if entity == "organizations":
        if len(pieces) >= 4 and pieces[3] == "governance":
            return governance_read_route(url, provider, headers)
        return organization_read_route(url, provider, headers)

    if entity == "paper-trading":
        if len(pieces) != 3:
            raise ApiError(404, "NOT_FOUND", "Unknown paper route")
        if pieces[2] == "methodology":
            arguments(parts.query, set())
            return 200, {"data": {"methodology_version": PAPER_METHODOLOGY_VERSION,
                "provider_mode": "OFFLINE_FIXTURE", "network_enabled": False,
                "scenario_shocks": SHOCKS, "is_paper": True, "is_executable": False,
                "real_capital_authorized": False}, "meta": metadata(provider.snapshot())}
        if pieces[2] == "instruments":
            query = arguments(parts.query, {"treasury_token_mint"})
            if not query.get("treasury_token_mint"):
                raise ApiError(400, "INCOMPLETE_CONTEXT", "Explicit paper quote mint is required")
            require_pubkey(query["treasury_token_mint"])
            data = DeterministicFixtureProvider().get_instruments({"treasury_token_mint": query["treasury_token_mint"]})
            return 200, {"data": data, "meta": metadata(provider.snapshot())}
        raise ApiError(404, "NOT_FOUND", "Unknown paper route")

    allowed = (
        {
            "status", "discoverable",
            "required_capabilities_all",
            "limit", "cursor",
        }
        if entity == "work-orders" and len(pieces) == 2
        else set()
    )

    if entity == "agents" and len(pieces) == 2:
        allowed = {
            "status", "active",
            "capabilities_all",
            "limit", "cursor",
        }
    elif entity == "agents" and len(pieces) == 4 and pieces[3] == "economic-movements":
        allowed = {
            "nature", "status", "mint", "network",
            "from_ts", "to_ts", "limit", "cursor",
        }
    elif entity == "agents" and len(pieces) == 4 and pieces[3] == "balances":
        allowed = {"mint", "network", "genesis", "genesis_hash", "program_id"}
    elif entity == "agents" and len(pieces) == 4 and pieces[3] == "costs":
        allowed = {
            "category", "cost_nature", "period", "status",
            "mint", "network", "genesis", "genesis_hash", "program_id", "provenance_source",
            "from_ts", "to_ts", "limit", "cursor",
        }
    elif entity == "agents" and len(pieces) == 4 and pieces[3] == "reserves":
        allowed = {"reserve_type", "status", "mint", "network", "genesis", "genesis_hash", "program_id"}
    elif entity == "agents" and len(pieces) == 4 and pieces[3] == "economic-summary":
        allowed = {"mint", "network", "period", "genesis", "genesis_hash", "program_id"}
    elif entity == "agents" and len(pieces) in (4, 5) and pieces[3] == "solvency":
        allowed = {"mint", "token_mint", "network", "genesis", "genesis_hash", "program_id",
                   "window", "from_ts", "to_ts", "consolidated", "limit"}
    elif entity == "agents" and len(pieces) == 4 and pieces[3] == "investible-surplus":
        allowed = {"network", "genesis_hash", "program_id", "token_mint", "scenario", "horizon_days"}
    elif entity == "agents" and len(pieces) in (4, 5) and pieces[3] == "paper-simulations":
        allowed = set()

    query = arguments(parts.query, allowed)

    if (
        entity == "marketplace" and len(pieces) != 2
    ) or len(pieces) > 6:
        raise ApiError(404, "NOT_FOUND", "Unknown route")

    if len(pieces) == 4 and not (
        (entity == "work-orders" and pieces[3] == "matches")
        or (entity == "agents" and pieces[3] in ("economic-movements", "balances", "costs", "reserves", "economic-summary", "solvency", "budget-policy", "spending-evaluations", "spending-approvals", "investible-surplus", "paper-simulations"))
    ):
        raise ApiError(404, "NOT_FOUND", "Unknown route")
    if len(pieces) == 5 and (entity != "agents" or
       (pieces[3] == "solvency" and pieces[4] not in ("history", "methodology")) or
       (pieces[3] == "investible-surplus" and pieces[4] != "methodology") or
       pieces[3] not in ("solvency", "budget-policy", "spending-evaluations", "spending-approvals", "investible-surplus", "paper-simulations")):
        raise ApiError(404, "NOT_FOUND", "Unknown route")
    if len(pieces) == 6 and (entity != "agents" or pieces[3] != "spending-approvals" or
                             pieces[5] != "history" and pieces[4] != "context"):
        raise ApiError(404, "NOT_FOUND", "Unknown route")

    if len(pieces) >= 3 and entity not in ("economic-movements", "costs", "reserves"):
        require_pubkey(pieces[2])

    snapshot = provider.snapshot()
    meta = metadata(snapshot)

    if entity == "marketplace":
        if (
            len(snapshot["agents"])
            + len(snapshot["work_orders"])
            > 200
        ):
            raise ApiError(
                413,
                "RESULT_TOO_LARGE",
                "Use paginated collection endpoints",
            )

        return 200, {
            "data": {
                "protocol_config": snapshot["protocol_config"],
                "paused": snapshot["protocol_paused"],
                "agents": [
                    projected_agent(a)
                    for a in snapshot["agents"]
                ],
                "work_orders": [
                    projected_order(o, snapshot)
                    for o in snapshot["work_orders"]
                ],
                "eligible_agents_by_order": {
                    order["work_order_account"]: [
                        agent["agent_account"]
                        for agent in decision_set(
                            order, snapshot, provider.match
                        )["eligible_agents"]
                    ]
                    for order in snapshot["work_orders"]
                    if discoverable(order, snapshot)
                },
            },
            "meta": meta,
        }

    if entity == "agents":
        if len(pieces) == 2:
            status = query.get("status")

            valid = {
                "Active", "OwnerSuspended",
                "AdminSuspended", "Revoked",
            }

            if status is not None and status not in valid:
                raise ApiError(
                    400, "INVALID_STATUS", "Unknown agent status"
                )

            active = query.get("active")

            if active not in (None, "true", "false"):
                raise ApiError(
                    400,
                    "INVALID_QUERY",
                    "active must be true or false",
                )

            mask = capability_mask(
                query.get("capabilities_all")
            )

            agents = [
                projected_agent(a)
                for a in snapshot["agents"]
                if (
                    status is None
                    or a["status"] == status
                )
                and (
                    active is None
                    or a["active"] == (active == "true")
                )
                and (
                    mask is None
                    or (int(a["capabilities"]) & mask) == mask
                )
            ]

            result = paged_collection(
                agents,
                "agent_account",
                query,
                {
                    "endpoint": "agents",
                    "status": status,
                    "active": active,
                    "capabilities_all": mask,
                },
            )

            return 200, {
                **result,
                "meta": meta,
            }

        agent = next(
            (
                a for a in snapshot["agents"]
                if a["agent_account"] == pieces[2]
            ),
            None,
        )

        if agent is None:
            raise ApiError(
                404,
                "AGENT_NOT_FOUND",
                "Agent not registered in current snapshot",
            )

        if len(pieces) >= 4 and pieces[3] == "paper-simulations":
            authorize_agent_access(agent, headers, pieces[2])
            try:
                store = get_paper_store(provider)
                data = store.list(agent) if len(pieces) == 4 else store.get(agent, pieces[4])
            except PaperError as exc:
                raise ApiError(exc.status, exc.code, str(exc)) from exc
            return 200, {"data": data, "meta": meta}

        if len(pieces) >= 4 and pieces[3] == "spending-evaluations":
            authorize_evaluation_read(agent, headers, pieces[2])
            store = get_spending_store(provider)
            try:
                data = store.list(agent) if len(pieces) == 4 else store.get(agent, pieces[4])
            except DecisionError as exc:
                raise ApiError(exc.status, exc.code, str(exc)) from exc
            return 200, {"data": data, "meta": meta}

        if len(pieces) >= 4 and pieces[3] == "spending-approvals":
            authorize_agent_access(agent, headers, pieces[2])
            store = get_approval_store(provider)
            try:
                if len(pieces) == 4:
                    data = store.list(agent)
                elif len(pieces) == 5:
                    data = store.get(agent, pieces[4])
                elif pieces[4] == "context":
                    data = store.context(agent, pieces[5])
                else:
                    data = store.history(agent, pieces[4])
            except ApprovalError as exc:
                raise ApiError(exc.status, exc.code, str(exc)) from exc
            return 200, {"data": data, "meta": meta}

        if pieces[3:4] == ["investible-surplus"]:
            authorize_agent_access(agent, headers, pieces[2])
            if len(pieces) == 5:
                return 200, {"data": surplus_methodology(), "meta": meta}
            needed = ("network", "genesis_hash", "program_id", "token_mint")
            if any(not query.get(key) for key in needed):
                raise ApiError(400, "INCOMPLETE_CONTEXT", "Explicit network, genesis, program and mint are required")
            scenario = query.get("scenario", "BASE")
            horizon = query.get("horizon_days", "30")
            if scenario not in ("BASE", "CONSERVATIVE", "STRESS") or horizon not in ("7", "30", "90"):
                raise ApiError(400, "INVALID_SCENARIO", "Expected BASE, CONSERVATIVE or STRESS and 7, 30 or 90 days")
            try:
                result = assess_agent_surplus(get_ledger(provider), get_policy_store(provider), agent,
                    network=query["network"], genesis_hash=query["genesis_hash"],
                    program_id=query["program_id"], token_mint=query["token_mint"],
                    scenario=scenario, horizon_days=int(horizon))
            except SurplusError as exc:
                raise ApiError(exc.status, exc.code, str(exc)) from exc
            latest_agent = next((item for item in provider.snapshot()["agents"]
                                 if item["agent_account"] == pieces[2]), None)
            if latest_agent is None or any(latest_agent.get(key) != agent.get(key)
                                           for key in ("agent_account", "agent_id", "owner")):
                raise ApiError(409, "IDENTITY_CHANGED", "Agent identity changed during assessment")
            return 200, {"data": result, "meta": meta}

        if len(pieces) >= 4 and pieces[3] == "budget-policy":
            authorize_agent_access(agent, headers, pieces[2])
            store = get_policy_store(provider)
            try:
                if len(pieces) == 4:
                    data = store.current(agent)
                    data["reserve_comparison"] = store.reserve_comparison(data)
                elif pieces[4] == "history":
                    data = store.history(agent)
                else:
                    if not pieces[4].isascii() or not pieces[4].isdecimal() or int(pieces[4]) < 1:
                        raise ApiError(400, "INVALID_VERSION", "Expected positive policy version")
                    data = store.version(agent, int(pieces[4]))
            except PolicyError as exc:
                raise ApiError(exc.status, exc.code, str(exc)) from exc
            return 200, {"data": data, "meta": meta}

        if len(pieces) == 4 and pieces[3] == "economic-movements":
            authorize_agent_access(agent, headers, pieces[2])

            from_ts = int(query["from_ts"]) if "from_ts" in query else None
            to_ts = int(query["to_ts"]) if "to_ts" in query else None
            limit = int(query.get("limit", 50))
            cursor = query.get("cursor")

            ledger = get_ledger(provider)
            try:
                movements, next_cursor = ledger.list_movements(
                    pieces[2],
                    nature=query.get("nature"),
                    status=query.get("status"),
                    token_mint=query.get("mint"),
                    network=query.get("network"),
                    from_ts=from_ts,
                    to_ts=to_ts,
                    limit=limit,
                    cursor=cursor,
                )
            except LedgerValidationError as exc:
                raise ApiError(400, "INVALID_QUERY", str(exc)) from exc

            return 200, {
                "data": [m.to_dict() for m in movements],
                "page": {
                    "limit": limit,
                    "has_more": next_cursor is not None,
                    "next_cursor": next_cursor,
                },
                "meta": meta,
            }

        if len(pieces) == 4 and pieces[3] == "balances":
            authorize_agent_access(agent, headers, pieces[2])

            ledger = get_ledger(provider)
            balances = ledger.get_balances(
                pieces[2],
                network=query.get("network"),
                genesis_hash=query.get("genesis") or query.get("genesis_hash"),
                program_id=query.get("program_id"),
                token_mint=query.get("mint"),
            )
            return 200, {
                "data": [b.to_dict() for b in balances],
                "meta": meta,
            }

        if len(pieces) == 4 and pieces[3] == "costs":
            authorize_agent_access(agent, headers, pieces[2])

            from_ts = int(query["from_ts"]) if "from_ts" in query else None
            to_ts = int(query["to_ts"]) if "to_ts" in query else None
            limit = int(query.get("limit", 50))
            cursor = query.get("cursor")

            ledger = get_ledger(provider)
            try:
                costs, next_cursor = ledger.list_costs(
                    pieces[2],
                    category=query.get("category"),
                    cost_nature=query.get("cost_nature"),
                    economic_period=query.get("period"),
                    status=query.get("status"),
                    token_mint=query.get("mint"),
                    network=query.get("network"),
                    genesis_hash=query.get("genesis") or query.get("genesis_hash"),
                    program_id=query.get("program_id"),
                    provenance_source=query.get("provenance_source"),
                    from_ts=from_ts,
                    to_ts=to_ts,
                    limit=limit,
                    cursor=cursor,
                )
            except LedgerValidationError as exc:
                raise ApiError(400, "INVALID_QUERY", str(exc)) from exc

            return 200, {
                "data": [c.to_dict() for c in costs],
                "page": {
                    "limit": limit,
                    "has_more": next_cursor is not None,
                    "next_cursor": next_cursor,
                },
                "meta": meta,
            }

        if len(pieces) == 4 and pieces[3] == "reserves":
            authorize_agent_access(agent, headers, pieces[2])

            ledger = get_ledger(provider)
            reserves = ledger.list_reserves(
                pieces[2],
                reserve_type=query.get("reserve_type"),
                status=query.get("status"),
                network=query.get("network"),
                genesis_hash=query.get("genesis") or query.get("genesis_hash"),
                program_id=query.get("program_id"),
                token_mint=query.get("mint"),
            )
            return 200, {
                "data": [r.to_dict() for r in reserves],
                "meta": meta,
            }

        if len(pieces) == 4 and pieces[3] == "economic-summary":
            authorize_agent_access(agent, headers, pieces[2])

            ledger = get_ledger(provider)
            summaries = ledger.get_economic_summary(
                pieces[2],
                network=query.get("network"),
                genesis_hash=query.get("genesis") or query.get("genesis_hash"),
                program_id=query.get("program_id"),
                token_mint=query.get("mint"),
                economic_period=query.get("period"),
            )
            return 200, {
                "data": [s.to_dict() for s in summaries],
                "meta": meta,
            }

        if pieces[3:4] == ["solvency"]:
            authorize_agent_access(agent, headers, pieces[2])
            if len(pieces) == 5 and pieces[4] not in ("history", "methodology"):
                raise ApiError(404, "NOT_FOUND", "Unknown solvency route")
            ledger = get_ledger(provider)
            scope = dict(network=query.get("network"), genesis_hash=query.get("genesis") or query.get("genesis_hash"),
                         program_id=query.get("program_id"), token_mint=query.get("mint") or query.get("token_mint"))
            if len(pieces) == 5 and pieces[4] == "methodology":
                return 200, {"data": methodology(), "meta": meta}
            if len(pieces) == 5:
                try:
                    limit = int(query.get("limit", "50"))
                    data = assessment_history(ledger, pieces[2], limit=limit, **scope)
                except (ValueError, LedgerValidationError) as exc:
                    raise ApiError(400, "INVALID_SOLVENCY_QUERY", str(exc)) from exc
                return 200, {"data": data, "meta": meta}
            try:
                window = int(query.get("window", "30"))
                from_ts = int(query["from_ts"]) if "from_ts" in query else None
                to_ts = int(query["to_ts"]) if "to_ts" in query else None
                consolidated = query.get("consolidated", "false")
                if consolidated not in ("true", "false"):
                    raise ValueError("consolidated must be true or false")
                data = assess_agent(ledger, pieces[2], window=window, from_ts=from_ts,
                                    to_ts=to_ts, consolidated=consolidated == "true", **scope)
                for assessment in data:
                    if assessment["calculation_status"] != "MIXED_ASSET_CONTEXT":
                        save_assessment(ledger, assessment)
            except (ValueError, LedgerValidationError) as exc:
                raise ApiError(400, "INVALID_SOLVENCY_QUERY", str(exc)) from exc
            return 200, {"data": data, "meta": meta}

        return 200, {
            "data": projected_agent(agent),
            "meta": meta,
        }

    if entity == "costs":
        if len(pieces) == 3:
            cost_id = pieces[2]
            ledger = get_ledger(provider)
            cost = ledger.get_cost(cost_id)
            if cost is None:
                raise ApiError(404, "COST_NOT_FOUND", "Cost not found")

            agent = next(
                (a for a in snapshot["agents"] if a["agent_account"] == cost.agent_account),
                None,
            )
            authorize_agent_access(agent or {"owner": cost.owner_pubkey}, headers, cost.agent_account)

            return 200, {
                "data": cost.to_dict(),
                "meta": meta,
            }
        raise ApiError(404, "NOT_FOUND", "Unknown route")

    if entity == "reserves":
        if len(pieces) == 3:
            reserve_id = pieces[2]
            ledger = get_ledger(provider)
            reserve = ledger.get_reserve(reserve_id)
            if reserve is None:
                raise ApiError(404, "RESERVE_NOT_FOUND", "Reserve not found")

            agent = next(
                (a for a in snapshot["agents"] if a["agent_account"] == reserve.agent_account),
                None,
            )
            authorize_agent_access(agent or {"owner": reserve.owner_pubkey}, headers, reserve.agent_account)

            return 200, {
                "data": reserve.to_dict(),
                "meta": meta,
            }
        raise ApiError(404, "NOT_FOUND", "Unknown route")

    if entity == "economic-movements":
        if len(pieces) == 3:
            movement_id = pieces[2]
            ledger = get_ledger(provider)
            movement = ledger.get_movement(movement_id)
            if movement is None:
                raise ApiError(404, "MOVEMENT_NOT_FOUND", "Economic movement not found")

            agent = next(
                (a for a in snapshot["agents"] if a["agent_account"] == movement.agent_account),
                None,
            )
            authorize_agent_access(agent or {"owner": movement.owner_pubkey}, headers, movement.agent_account)

            return 200, {
                "data": movement.to_dict(),
                "meta": meta,
            }
        raise ApiError(404, "NOT_FOUND", "Unknown route")

    if len(pieces) == 2:
        status = query.get("status")

        if status is not None and status not in STATUSES:
            raise ApiError(
                400,
                "INVALID_STATUS",
                "Unknown work-order status",
            )

        available = query.get("discoverable")

        if available is not None and available not in (
            "true", "false"
        ):
            raise ApiError(
                400,
                "INVALID_QUERY",
                "discoverable must be true or false",
            )

        required_mask = capability_mask(
            query.get("required_capabilities_all")
        )

        orders = [
            projected_order(o, snapshot)
            for o in snapshot["work_orders"]
            if (
                status is None or o["status"] == status
            )
            and (
                available is None
                or discoverable(o, snapshot)
                == (available == "true")
            )
            and (
                required_mask is None
                or (
                    int(o["required_capabilities"])
                    & required_mask
                ) == required_mask
            )
        ]

        result = paged_collection(
            orders,
            "work_order_account",
            query,
            {
                "endpoint": "work-orders",
                "status": status,
                "discoverable": available,
                "required_capabilities_all": required_mask,
            },
        )

        return 200, {
            **result,
            "meta": meta,
        }

    order = next(
        (
            o for o in snapshot["work_orders"]
            if o["work_order_account"] == pieces[2]
        ),
        None,
    )

    if order is None:
        raise ApiError(
            404,
            "WORK_ORDER_NOT_FOUND",
            "WorkOrder not registered in current snapshot",
        )

    if len(pieces) == 3:
        return 200, {
            "data": projected_order(order, snapshot),
            "meta": meta,
        }

    return 200, {
        "data": {
            "work_order": projected_order(order, snapshot),
            **decision_set(order, snapshot, provider.match),
        },
        "meta": meta,
    }


def policy_mutation_route(method: str, url: str, provider, headers, body: dict) -> tuple[int, dict]:
    parts = urlsplit(url)
    pieces = [part for part in parts.path.split("/") if part]
    if parts.query or parts.fragment or len(pieces) not in (4, 5) or pieces[:2] != ["v1", "agents"] or pieces[3] != "budget-policy":
        raise ApiError(405, "METHOD_NOT_ALLOWED", "Only budget policy administration may mutate")
    require_pubkey(pieces[2])
    action = None
    if len(pieces) == 4:
        action = "CREATE" if method == "POST" else "UPDATE" if method == "PUT" else None
    elif method == "POST":
        action = {"activate": "ACTIVATE", "pause": "PAUSE", "resume": "RESUME", "revoke": "REVOKE"}.get(pieces[4])
    if action is None:
        raise ApiError(405, "METHOD_NOT_ALLOWED", "Unsupported policy mutation")
    snapshot = provider.snapshot()
    agent = next((item for item in snapshot["agents"] if item["agent_account"] == pieces[2]), None)
    if agent is None:
        raise ApiError(404, "AGENT_NOT_FOUND", "Agent not registered in current snapshot")
    try:
        validate_control(body, action)
        actor = verify_mutation(agent, method, parts.path, body, headers)
        latest = provider.snapshot()
        latest_agent = next((item for item in latest["agents"] if item["agent_account"] == pieces[2]), None)
        if latest_agent is None or latest_agent.get("owner") != actor or latest_agent.get("agent_id") != agent.get("agent_id"):
            raise PolicyError(403, "OWNER_CHANGED", "Agent identity or owner changed before mutation")
        data, created = get_policy_store(provider).mutate(agent, action, body, actor)
    except PolicyError as exc:
        raise ApiError(exc.status, exc.code, str(exc)) from exc
    out_meta = metadata(snapshot)
    out_meta["read_only"] = False
    return (201 if created and action == "CREATE" else 200), {"data": data, "meta": out_meta}


def spending_evaluation_route(method: str, url: str, provider, headers, body: dict) -> tuple[int, dict]:
    parts = urlsplit(url)
    pieces = [part for part in parts.path.split("/") if part]
    if (method != "POST" or parts.query or parts.fragment or len(pieces) != 4 or
            pieces[:2] != ["v1", "agents"] or pieces[3] != "spending-evaluations"):
        raise ApiError(405, "METHOD_NOT_ALLOWED", "Only signed spending evaluations may be submitted")
    require_pubkey(pieces[2])
    snapshot = provider.snapshot()
    agent = next((item for item in snapshot["agents"] if item["agent_account"] == pieces[2]), None)
    if agent is None:
        raise ApiError(404, "AGENT_NOT_FOUND", "Agent not registered in current snapshot")
    try:
        SpendingProposal.parse(body)
        requester = verify_evaluation(agent, method, parts.path, body, headers)
        latest = provider.snapshot()
        latest_agent = next((item for item in latest["agents"] if item["agent_account"] == pieces[2]), None)
        if (latest_agent is None or latest_agent.get("owner") != agent.get("owner") or
                latest_agent.get("agent_id") != agent.get("agent_id") or
                latest_agent.get("signing_authority") != agent.get("signing_authority")):
            raise DecisionError(403, "AGENT_IDENTITY_MISMATCH", "Agent identity changed before evaluation")
        def current_agent():
            fresh = provider.snapshot()
            return next((item for item in fresh["agents"] if item["agent_account"] == pieces[2]), None)
        data, created = get_spending_store(provider).evaluate(
            agent, body, requester, identity_supplier=current_agent)
    except (DecisionError, PolicyError) as exc:
        raise ApiError(exc.status, exc.code, str(exc)) from exc
    out_meta = metadata(latest)
    out_meta["read_only"] = False
    return (201 if created else 200), {"data": data, "meta": out_meta}


def spending_approval_route(method: str, url: str, provider, headers, body: dict) -> tuple[int, dict]:
    parts = urlsplit(url)
    pieces = [part for part in parts.path.split("/") if part]
    if method != "POST" or parts.query or parts.fragment or pieces[:2] != ["v1", "agents"] or len(pieces) not in (4, 6):
        raise ApiError(405, "METHOD_NOT_ALLOWED", "Only signed owner approval actions are supported")
    if pieces[3] != "spending-approvals":
        raise ApiError(405, "METHOD_NOT_ALLOWED", "Unsupported approval route")
    action = "OPEN" if len(pieces) == 4 else {"approve": "APPROVE", "reject": "REJECT", "revoke": "REVOKE"}.get(pieces[5])
    if action is None:
        raise ApiError(405, "METHOD_NOT_ALLOWED", "Unsupported approval action")
    require_pubkey(pieces[2])
    snapshot = provider.snapshot()
    agent = next((item for item in snapshot["agents"] if item["agent_account"] == pieces[2]), None)
    if agent is None:
        raise ApiError(404, "AGENT_NOT_FOUND", "Agent not registered in current snapshot")
    try:
        validate_mutation(body, action)
        actor, signature, message_hash = verify_approval(agent, method, parts.path, body, headers)
        latest = provider.snapshot()
        latest_agent = next((item for item in latest["agents"] if item["agent_account"] == pieces[2]), None)
        if (latest_agent is None or latest_agent.get("owner") != actor or
                latest_agent.get("agent_id") != agent.get("agent_id")):
            raise ApprovalError(403, "OWNER_CHANGED", "Agent identity changed before approval")
        def current_agent():
            fresh = provider.snapshot()
            return next((item for item in fresh["agents"] if item["agent_account"] == pieces[2]), None)
        store = get_approval_store(provider)
        if len(pieces) == 6:
            expected = store.context(agent, body["decision_id"])["approval_id"]
            if pieces[4] != expected:
                raise ApprovalError(404, "APPROVAL_NOT_FOUND", "Approval not found")
        data, created = store.mutate(agent, action, body, actor, signature, message_hash,
                                     identity_supplier=current_agent)
    except ApprovalError as exc:
        raise ApiError(exc.status, exc.code, str(exc)) from exc
    out_meta = metadata(latest)
    out_meta["read_only"] = False
    return (201 if created and action == "OPEN" else 200), {"data": data, "meta": out_meta}


def paper_simulation_route(method: str, url: str, provider, headers, body: dict) -> tuple[int, dict]:
    parts = urlsplit(url)
    pieces = [part for part in parts.path.split("/") if part]
    if (method != "POST" or parts.query or parts.fragment or len(pieces) != 4 or
            pieces[:2] != ["v1", "agents"] or pieces[3] != "paper-simulations"):
        raise ApiError(405, "METHOD_NOT_ALLOWED", "Only signed paper simulation POST is supported")
    require_pubkey(pieces[2])
    snapshot = provider.snapshot()
    agent = next((item for item in snapshot["agents"] if item["agent_account"] == pieces[2]), None)
    if agent is None:
        raise ApiError(404, "AGENT_NOT_FOUND", "Agent not registered in current snapshot")
    try:
        actor = verify_paper_signature(agent, parts.path, body, headers)
        policy = get_policy_store(provider).current(agent)
        now = int(time.time())
        if (policy["status"] != "ACTIVE" or now < policy["valid_from"] or
                now >= policy["expires_at"] or
                (body["network"], body["genesis_hash"], body["program_id"]) !=
                (policy["network"], policy["genesis_hash"], policy["program_id"]) or
                body["treasury_token_mint"] not in [rule["token_mint"] for rule in policy["asset_rules"]
                                                     if rule["enabled"]]):
            raise PaperError(409, "POLICY_CONTEXT_CONFLICT", "Current policy context is not active for this paper scenario")
        def current_agent():
            fresh = provider.snapshot()
            return next((item for item in fresh["agents"] if item["agent_account"] == pieces[2]), None)
        data, created = get_paper_store(provider).run(agent, body, actor, identity_supplier=current_agent)
    except (PaperError, PolicyError) as exc:
        raise ApiError(exc.status, exc.code, str(exc)) from exc
    out_meta = metadata(provider.snapshot())
    out_meta["read_only"] = False
    return (201 if created else 200), {"data": data, "meta": out_meta}


class LiveProvider:
    def __init__(
        self,
        rpc_url: str,
        idl_path: Path,
        commitment: str,
        expected_genesis: str,
    ):
        self.rpc = discovery.Rpc(rpc_url, timeout=10)

        self.idl = discovery.Idl(
            json.loads(idl_path.read_text())
        )

        self.idl.validate_marketplace_contract()

        if self.idl.address != PROGRAM_ID:
            raise ApiError(
                503, "WRONG_PROGRAM", "IDL program ID mismatch"
            )

        self.commitment = commitment
        self.expected_genesis = expected_genesis
        self.matcher = rust_matching.RustMatcher(
            ROOT / "target/debug/examples/marketplace_match_bridge"
        )
        if not self.matcher.executable.is_file():
            raise ApiError(
                503, "RUST_MATCHER_MISSING",
                "Build the Rust matching bridge before starting API",
            )
        self.ledger = EconomicLedger()

    def match(self, order, snapshot):
        return self.matcher(order, snapshot)

    def health(self) -> str:
        observed = self.rpc.call(
            "getGenesisHash", []
        )

        if observed != self.expected_genesis:
            raise ApiError(
                503,
                "WRONG_GENESIS",
                "RPC is not the expected localnet ledger",
            )

        return observed

    def snapshot(self) -> dict:
        self.health()

        return discovery.discover(
            self.rpc,
            self.idl,
            self.commitment,
        )


def handler_for(provider):
    class Handler(BaseHTTPRequestHandler):
        def respond(
            self,
            status: int,
            content: dict,
            extra: dict | None = None,
        ):
            raw = json.dumps(
                content,
                ensure_ascii=False,
                separators=(",", ":"),
            ).encode("utf-8")

            self.send_response(status)

            self.send_header(
                "Content-Type",
                "application/json; charset=utf-8",
            )
            self.send_header(
                "Content-Length", str(len(raw))
            )
            self.send_header(
                "Cache-Control", "no-store"
            )
            self.send_header(
                "X-Content-Type-Options", "nosniff"
            )

            if extra:
                for name, value in extra.items():
                    self.send_header(name, value)

            self.end_headers()
            self.wfile.write(raw)

        def do_GET(self):
            try:
                status, body = route(
                    self.path, provider, headers=self.headers
                )
                self.respond(status, body)

            except ApiError as exc:
                self.respond(
                    exc.status,
                    {
                        "error": {
                            "code": exc.code,
                            "message": str(exc),
                        }
                    },
                )

            except (
                rust_matching.RustMatchingError,
                discovery.DiscoveryError,
                OSError,
                ValueError,
                KeyError,
                TypeError,
                IndexError,
            ) as exc:
                print(
                    f"Marketplace upstream error: {exc}",
                    file=sys.stderr,
                )

                self.respond(
                    502,
                    {
                        "error": {
                            "code": "UPSTREAM_ERROR",
                            "message":
                                "RPC or account validation failed",
                        }
                    },
                )

        def do_POST(self):
            self.policy_write("POST")

        def do_PUT(self):
            self.policy_write("PUT")

        def policy_write(self, method: str):
            parts = urlsplit(self.path)
            route_parts = [item for item in parts.path.split("/") if item]
            policy_path = (len(route_parts) in (4, 5) and route_parts[:2] == ["v1", "agents"]
                           and route_parts[3] == "budget-policy")
            evaluation_path = (method == "POST" and len(route_parts) == 4 and
                               route_parts[:2] == ["v1", "agents"] and route_parts[3] == "spending-evaluations")
            approval_path = (method == "POST" and len(route_parts) in (4, 6) and
                             route_parts[:2] == ["v1", "agents"] and route_parts[3] == "spending-approvals")
            paper_path = (method == "POST" and len(route_parts) == 4 and
                          route_parts[:2] == ["v1", "agents"] and route_parts[3] == "paper-simulations")
            organization_path = (method == "POST" and route_parts[:2] == ["v1", "organizations"] and
                                 (len(route_parts) == 2 or len(route_parts) == 4 and route_parts[3] == "actions"))
            governance_path = (method == "POST" and len(route_parts) == 5 and
                               route_parts[:2] == ["v1", "organizations"] and
                               route_parts[3:] == ["governance", "actions"])
            if not policy_path and not evaluation_path and not approval_path and not paper_path and not organization_path and not governance_path:
                self.unsupported()
                return
            try:
                length = self.headers.get("Content-Length")
                if length is None or not length.isdecimal() or int(length) > 65536:
                    raise ApiError(400, "INVALID_BODY", "JSON body length is required and must be <= 65536 bytes")
                raw = self.rfile.read(int(length))
                def unique_pairs(pairs):
                    value = {}
                    for key, item in pairs:
                        if key in value:
                            raise ValueError("Duplicate JSON property")
                        value[key] = item
                    return value
                try:
                    body = json.loads(raw.decode("utf-8"), object_pairs_hook=unique_pairs)
                except (UnicodeError, ValueError) as exc:
                    raise ApiError(400, "INVALID_BODY", "Expected unique-key JSON object") from exc
                if not isinstance(body, dict):
                    raise ApiError(400, "INVALID_BODY", "Expected JSON object")
                if evaluation_path:
                    status, response = spending_evaluation_route(method, self.path, provider, self.headers, body)
                elif approval_path:
                    status, response = spending_approval_route(method, self.path, provider, self.headers, body)
                elif paper_path:
                    status, response = paper_simulation_route(method, self.path, provider, self.headers, body)
                elif organization_path:
                    status, response = organization_mutation_route(method, self.path, provider, self.headers, body)
                elif governance_path:
                    status, response = governance_mutation_route(self.path, provider, self.headers, body)
                else:
                    status, response = policy_mutation_route(method, self.path, provider, self.headers, body)
                self.respond(status, response)
            except ApiError as exc:
                self.respond(exc.status, {"error": {"code": exc.code, "message": str(exc)}})
            except Exception as exc:
                print(f"Policy mutation error: {exc}", file=sys.stderr)
                self.respond(500, {"error": {"code": "POLICY_WRITE_ERROR", "message": "Policy mutation failed"}})

        def unsupported(self):
            self.respond(
                405,
                {
                    "error": {
                        "code": "METHOD_NOT_ALLOWED",
                        "message": "Read-only: GET only. Ingestion of economic movements must be performed via trusted internal services.",
                    }
                },
                {"Allow": "GET"},
            )

        do_PATCH = do_DELETE = do_OPTIONS = unsupported

        def log_message(self, fmt, *args):
            print(
                "marketplace-api:",
                fmt % args,
                file=sys.stderr,
            )

    return Handler


def main():
    parser = argparse.ArgumentParser(
        description=__doc__
    )

    parser.add_argument(
        "--rpc-url",
        default="http://127.0.0.1:8899",
    )
    parser.add_argument(
        "--idl",
        type=Path,
        default=ROOT / "target/idl/aerosettle.discovery.json",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8787,
    )
    parser.add_argument(
        "--commitment",
        choices=["confirmed", "finalized"],
        default="confirmed",
    )
    parser.add_argument(
        "--genesis",
        default=GENESIS,
    )

    args = parser.parse_args()

    if not 1 <= args.port <= 65535:
        parser.error("port must be 1..65535")

    provider = LiveProvider(
        args.rpc_url,
        args.idl,
        args.commitment,
        args.genesis,
    )

    provider.health()

    server = ThreadingHTTPServer(
        ("127.0.0.1", args.port),
        handler_for(provider),
    )

    print(
        "AeroSettle Marketplace API: "
        f"http://127.0.0.1:{args.port} (GET only)",
        flush=True,
    )

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nAPI stopped", flush=True)
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
