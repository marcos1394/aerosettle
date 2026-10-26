"""Pure integer governance tally and hypothetical distribution calculations."""
from __future__ import annotations


class GovernanceRuleError(ValueError):
    pass


PROPOSAL_TYPES = frozenset({"BYLAWS_AMENDMENT", "MEMBERSHIP_RULE_CHANGE", "OPERATIONAL_POLICY",
    "RESOURCE_ALLOCATION_PROPOSAL", "ECONOMIC_DISTRIBUTION_POLICY", "RESERVE_POLICY_PROPOSAL",
    "DISPUTE_RESOLUTION", "OTHER_NON_FINANCIAL"})


def _integer(value, name: str, minimum: int = 0, maximum: int = 2**64 - 1) -> int:
    if type(value) is not int or not minimum <= value <= maximum:
        raise GovernanceRuleError(f"Invalid {name}")
    return value


def validate_bylaws(value: dict) -> dict:
    if not isinstance(value, dict):
        raise GovernanceRuleError("Bylaws must be an object")
    required = {"title", "purpose", "eligible_voter_roles", "proposal_roles", "proposal_permissions",
                "distribution_policy_id", "quorum_bps",
                "approval_threshold_bps", "voting_period_seconds", "minimum_voting_period_seconds",
                "dispute_window_seconds", "vote_weighting_rule"}
    if set(value) != required:
        raise GovernanceRuleError("Exact bylaws fields are required")
    if not isinstance(value["title"], str) or not 1 <= len(value["title"].strip()) <= 120:
        raise GovernanceRuleError("Invalid title")
    if not isinstance(value["purpose"], str) or not 1 <= len(value["purpose"].strip()) <= 1000:
        raise GovernanceRuleError("Invalid purpose")
    roles = value["eligible_voter_roles"]
    proposer_roles = value["proposal_roles"]
    permissions = value["proposal_permissions"]
    if (not isinstance(roles, list) or not roles or "OWNER" not in roles or
            any(not isinstance(role, str) for role in roles) or
            len(roles) != len(set(roles)) or
            any(role not in {"OWNER", "LEGAL_REPRESENTATIVE", "ADMIN", "OPERATOR", "MEMBER", "AUDITOR", "VIEWER"}
                for role in roles)):
        raise GovernanceRuleError("Invalid eligible roles")
    if (not isinstance(proposer_roles, list) or not proposer_roles or "OWNER" not in proposer_roles or
            any(not isinstance(role, str) for role in proposer_roles) or
            len(proposer_roles) != len(set(proposer_roles)) or
            any(role not in {"OWNER", "LEGAL_REPRESENTATIVE", "ADMIN", "OPERATOR", "MEMBER", "AUDITOR", "VIEWER"}
                for role in proposer_roles)):
        raise GovernanceRuleError("Invalid proposer roles")
    if (not isinstance(permissions, list) or "BYLAWS_AMENDMENT" not in permissions or
            len(permissions) != len(set(map(str, permissions))) or
            any(not isinstance(item, str) or item not in PROPOSAL_TYPES for item in permissions)):
        raise GovernanceRuleError("Invalid proposal permissions")
    policy_id = value["distribution_policy_id"]
    if policy_id is not None:
        import re
        if not isinstance(policy_id, str) or not re.fullmatch(r"gpol_[0-9a-f]{32}", policy_id):
            raise GovernanceRuleError("Invalid distribution policy identifier")
    _integer(value["quorum_bps"], "quorum", 1, 10000)
    _integer(value["approval_threshold_bps"], "approval threshold", 5001, 10000)
    minimum = _integer(value["minimum_voting_period_seconds"], "minimum voting period", 60, 30*86400)
    period = _integer(value["voting_period_seconds"], "voting period", minimum, 30*86400)
    _integer(value["dispute_window_seconds"], "dispute window", 60, 30*86400)
    if value["vote_weighting_rule"] != "ONE_ELIGIBLE_WALLET_ONE_VOTE":
        raise GovernanceRuleError("Unsupported vote weighting rule")
    return {**value, "eligible_voter_roles": sorted(roles), "proposal_roles": sorted(proposer_roles),
            "proposal_permissions": sorted(permissions),
            "voting_period_seconds": period}


def electorate_from_organization(state: dict, bylaws: dict, at: int) -> dict[str, int]:
    if state["organization"]["organization_status"] != "ACTIVE":
        raise GovernanceRuleError("Organization is inactive")
    allowed = set(bylaws["eligible_voter_roles"])
    return {wallet: 1 for wallet, member in state["members"].items()
            if member["status"] == "ACTIVE" and member["valid_from"] <= at < member["expires_at"]
            and state["roles"].get(wallet, member["role_id"]) in allowed}


def evaluate_governance_proposal(proposal: dict, bylaws: dict, electorate: dict[str, int],
                                 votes: dict[str, dict], evaluated_at: int) -> dict:
    """ABSTAIN counts for quorum but not the YES+NO approval denominator; ties fail."""
    total = sum(_integer(weight, "voter weight", 1) for weight in electorate.values())
    yes = no = abstain = invalid = 0
    for wallet, vote in votes.items():
        if wallet not in electorate or vote.get("choice") not in ("YES", "NO", "ABSTAIN"):
            invalid += 1
            continue
        if vote["choice"] == "YES":
            yes += electorate[wallet]
        elif vote["choice"] == "NO":
            no += electorate[wallet]
        else:
            abstain += electorate[wallet]
    participating = yes + no + abstain
    quorum = total > 0 and participating*10000 >= total*bylaws["quorum_bps"]
    approved = quorum and yes > no and yes + no > 0 and yes*10000 >= (yes+no)*bylaws["approval_threshold_bps"]
    return {"proposal_id": proposal["proposal_id"], "eligible_weight": total,
            "participating_weight": participating, "yes_weight": yes, "no_weight": no,
            "abstain_weight": abstain, "invalid_vote_count": invalid,
            "quorum_met": quorum, "approval_threshold_met": approved,
            "outcome": "ACCEPTED" if approved else "REJECTED",
            "evaluated_at": evaluated_at, "is_executable": False}


def validate_distribution_policy(value: dict) -> dict:
    if not isinstance(value, dict) or set(value) != {"mint", "participant_shares_bps", "reserve_share_bps",
                                                  "cost_allocation_method"}:
        raise GovernanceRuleError("Exact distribution policy fields required")
    shares = value["participant_shares_bps"]
    if not isinstance(shares, dict) or not shares or len(shares) > 100:
        raise GovernanceRuleError("Invalid participants")
    from tools.organizations.signatures import pubkey
    for participant, bps in shares.items():
        pubkey(participant)
        _integer(bps, "participant share", 0, 10000)
    _integer(value["reserve_share_bps"], "reserve share", 0, 10000)
    if sum(shares.values()) + value["reserve_share_bps"] != 10000:
        raise GovernanceRuleError("Shares and reserve must total 10000 bps")
    pubkey(value["mint"])
    if value["cost_allocation_method"] != "DECLARATIVE_ONLY":
        raise GovernanceRuleError("Cost allocation may only be declarative")
    return value


def simulate_organization_distribution(hypothetical_pool: dict, policy: dict,
                                       assumptions: dict | None = None) -> dict:
    if not isinstance(policy, dict) or policy.get("is_executable") is not False:
        raise GovernanceRuleError("A non-executable declarative policy is required")
    validate_distribution_policy({key: policy.get(key) for key in
        ("mint", "participant_shares_bps", "reserve_share_bps", "cost_allocation_method")})
    if (assumptions is not None and (not isinstance(assumptions, dict) or
            set(assumptions) - {"description", "scenario_name"} or
            any(not isinstance(value, str) or len(value) > 500 for value in assumptions.values()))):
        raise GovernanceRuleError("Only bounded textual assumptions are supported")
    if not isinstance(hypothetical_pool, dict) or set(hypothetical_pool) != {
            "organization_id", "mint", "amount_base_units", "provenance"}:
        raise GovernanceRuleError("Exact hypothetical pool fields required")
    if hypothetical_pool["provenance"] not in ("SYNTHETIC_POOL", "HYPOTHETICAL_DISTRIBUTION"):
        raise GovernanceRuleError("Only hypothetical pools are supported")
    if hypothetical_pool["organization_id"] != policy["organization_id"] or hypothetical_pool["mint"] != policy["mint"]:
        raise GovernanceRuleError("Pool organization or mint differs from policy")
    amount = _integer(hypothetical_pool["amount_base_units"], "pool amount")
    shares = policy["participant_shares_bps"]
    names = sorted(shares)
    allocations = {name: amount * shares[name] // 10000 for name in names}
    reserve = amount * policy["reserve_share_bps"] // 10000
    remainder = amount - reserve - sum(allocations.values())
    # Conservatively retain indivisible base units in the hypothetical reserve.
    reserve += remainder
    return {"organization_id": policy["organization_id"], "distribution_policy_id": policy["distribution_policy_id"],
            "mint": policy["mint"], "pool_provenance": hypothetical_pool["provenance"],
            "pool_amount_base_units": amount, "participant_allocations_base_units": allocations,
            "reserve_base_units": reserve, "rounding_remainder_to_reserve": remainder,
            "assumptions": assumptions or {}, "is_simulation": True, "is_executable": False,
            "funds_transferred": False}
