"""Pure, deny-by-default organizational permission evaluation."""
from __future__ import annotations

PERMISSIONS = frozenset({
    "organization.read", "organization.update_metadata", "members.read", "members.invite",
    "members.suspend", "members.reinstate", "members.remove", "roles.read", "roles.assign",
    "roles.revoke", "delegations.create", "delegations.revoke", "delegations.read",
    "agents.read_membership", "agents.invite", "agents.remove_membership", "audit.read",
})
READ = frozenset({"organization.read", "members.read", "roles.read", "delegations.read",
                  "agents.read_membership"})
ROLES = {
    "OWNER": PERMISSIONS,
    "LEGAL_REPRESENTATIVE": READ | {"audit.read"},
    "ADMIN": READ | {"audit.read"},
    "OPERATOR": {"organization.read", "agents.read_membership", "members.read"},
    "MEMBER": {"organization.read"},
    "AUDITOR": {"organization.read", "audit.read"},
    "VIEWER": {"organization.read"},
}


def _active(member: dict | None, at: int) -> bool:
    return bool(member and member.get("status") == "ACTIVE" and
                member.get("valid_from", 0) <= at < member.get("expires_at", 0))


def evaluate_organization_permission(organization: dict, actor: str, memberships: dict,
                                     role_assignments: dict, delegations: dict,
                                     permission: str, target: str, evaluated_at: int) -> dict:
    """No I/O or clock. Delegations have depth one and depend on the delegator's base role."""
    org_id = organization.get("organization_id", "")
    member = memberships.get(actor)
    role = role_assignments.get(actor, member.get("role_id") if member else None)
    reasons = []
    effective = set()
    if permission not in PERMISSIONS:
        reasons.append("UNKNOWN_PERMISSION")
    elif organization.get("organization_status") != "ACTIVE":
        reasons.append("ORGANIZATION_INACTIVE")
    elif not _active(member, evaluated_at):
        reasons.append("MEMBERSHIP_INACTIVE")
    elif role not in ROLES:
        reasons.append("ROLE_UNKNOWN_OR_REVOKED")
    else:
        effective.update(ROLES[role])
        for delegation in delegations.values():
            if (delegation.get("delegate_pubkey") != actor or delegation.get("status") != "ACTIVE" or
                    not delegation.get("valid_from", 0) <= evaluated_at < delegation.get("expires_at", 0) or
                    delegation.get("resource_scope") not in (target, "organization") or
                    delegation.get("permission") not in PERMISSIONS):
                continue
            delegator = delegation["delegator_pubkey"]
            origin = memberships.get(delegator)
            origin_role = role_assignments.get(delegator, origin.get("role_id") if origin else None)
            if _active(origin, evaluated_at) and delegation["permission"] in ROLES.get(origin_role, ()):
                effective.add(delegation["permission"])
        if permission not in effective:
            reasons.append("PERMISSION_NOT_GRANTED")
    return {"decision": "DENY" if reasons else "ALLOW", "reason_codes": reasons,
            "organization_id": org_id, "actor_pubkey": actor,
            "requested_permission": permission, "target_resource": target,
            "effective_role": role, "effective_permissions": sorted(effective),
            "evaluated_at": evaluated_at, "membership_version": organization.get("version", 0),
            "is_financial_authority": False, "is_device_signing_authority": False}
