"""CON-32 signature, audit, RBAC, lifecycle, concurrency and ownership boundaries."""
import copy
import sqlite3
import tempfile
import threading
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest import mock

from cryptography.hazmat.primitives.asymmetric import ed25519
from tools.discovery.agent_discovery import b58encode

from tools.organizations.rbac import evaluate_organization_permission
from tools.organizations.signatures import OrganizationError, digest, mutation_message, read_message, verify_mutation, verify_read
from tools.organizations.store import OrganizationStore

KEYS = [ed25519.Ed25519PrivateKey.from_private_bytes(bytes([n])*32) for n in (1, 2, 3, 4, 5)]
WALLETS = [b58encode(key.public_key().public_bytes_raw()) for key in KEYS]
ORG = "org_" + "a"*32
AGENT = WALLETS[4]


def request(action="CREATE", actor=0, version=0, target_type="ORGANIZATION", target_id=ORG,
            payload=None, nonce=None):
    now = int(time.time())
    return {"organization_id": ORG, "actor_pubkey": WALLETS[actor], "target_type": target_type,
        "target_id": target_id, "action": action,
        "role_id": "OWNER" if action == "CREATE" else "", "permission_scope": "organization",
        "payload": payload if payload is not None else ({"owner_pubkey": WALLETS[0],
            "organization_name": "Fleet One", "organization_slug": "fleet-one",
            "organization_type": "COLLECTIVE", "description": "Test", "jurisdiction": "MX"} if action == "CREATE" else {}),
        "expected_version": version, "issued_at": now, "expires_at": now+300,
        "nonce": nonce or f"nonce-{now}-{version}-{action}-{target_id}",
        "idempotency_key": f"idem-{now}-{version}-{action}-{target_id}"}


def signed(body, actor=0):
    path = "/v1/organizations" if body["action"] == "CREATE" else f"/v1/organizations/{ORG}/actions"
    message = mutation_message("POST", path, body)
    sig = b58encode(KEYS[actor].sign(message))
    headers = {"X-Signer-Pubkey": WALLETS[actor], "X-Timestamp": str(body["issued_at"]),
               "X-Signature": sig}
    return path, message, sig, headers


class OrganizationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.registration = {"agent_account": AGENT, "agent_id": "11"*32,
            "agent_owner_pubkey": WALLETS[2], "network": "localnet", "genesis_hash": WALLETS[3],
            "program_id": WALLETS[4], "agent_status": "Active", "active": True}
        def snapshot():
            return {"network": "localnet", "genesis_hash": WALLETS[3], "program_id": WALLETS[4],
                "agents": [{"agent_account": AGENT, "agent_id": "11"*32,
                    "owner": self.registration["agent_owner_pubkey"], "status": self.registration["agent_status"],
                    "active": self.registration["active"]}]}
        self.snapshot = snapshot
        self.store = OrganizationStore(Path(self.tmp.name)/"organizations.sqlite", snapshot)
        self.change()

    def tearDown(self):
        self.store.close()
        self.tmp.cleanup()

    def change(self, action="CREATE", actor=0, target_type="ORGANIZATION", target_id=ORG,
               payload=None, body=None):
        if body is None:
            version = self.store._load(ORG)[0]
            body = request(action, actor, version["organization"]["version"] if version else 0,
                           target_type, target_id, payload)
        path, message, signature, headers = signed(body, actor)
        verify_mutation("POST", path, body, headers)
        return self.store.mutate(body, signature, message, WALLETS[actor]), body, headers

    def invite_human(self, actor=1, role="MEMBER"):
        inv = "inv_" + format(actor, "032x")
        self.change("INVITE_HUMAN", target_type="INVITATION", target_id=inv,
            payload={"subject_pubkey": WALLETS[actor], "role_id": role,
                "valid_from": int(time.time()), "expires_at": int(time.time())+1000})
        return inv

    def test_create_signatures_read_and_replay(self):
        created = self.store.read(ORG, WALLETS[0])
        self.assertEqual(created["organization"]["owner_pubkey"], WALLETS[0])
        self.assertFalse(created["organization"]["is_financial_authority"])
        path, msg, sig, hdr = signed(request())
        self.assertEqual(verify_read(f"/v1/organizations/{ORG}", {
            "X-Signer-Pubkey": WALLETS[0], "X-Timestamp": str(int(time.time())),
            "X-Signature": b58encode(KEYS[0].sign(read_message(
                f"/v1/organizations/{ORG}", WALLETS[0], int(time.time()))))}), WALLETS[0])
        with self.assertRaises(OrganizationError): verify_read(f"/v1/organizations/{ORG}", {})
        for altered in ({**request(), "organization_id": "org_"+"b"*32},
                        {**request(), "payload": {"owner_pubkey": WALLETS[1]}}):
            with self.assertRaises(OrganizationError): verify_mutation("POST", path, altered, hdr)
        old = request()
        old["issued_at"] -= 1000
        with self.assertRaises(OrganizationError): verify_mutation("POST", path, old, hdr)
        with self.assertRaises(OrganizationError): verify_mutation("POST", path+"/wrong", request(), hdr)

    def test_human_invite_consent_roles_suspension_and_reinvite(self):
        inv = self.invite_human(1, "ADMIN")
        self.assertEqual(len(self.store.read(ORG, WALLETS[1], "invitations")), 1)
        with self.assertRaises(OrganizationError): self.store.read(ORG, WALLETS[1], "members")
        with self.assertRaises(OrganizationError): self.change("ACCEPT_HUMAN", 2, "INVITATION", inv)
        self.change("ACCEPT_HUMAN", 1, "INVITATION", inv)
        with self.assertRaises(OrganizationError): self.change("INVITE_HUMAN", 1, "INVITATION",
            "inv_"+"9"*32, {"subject_pubkey": WALLETS[2], "role_id": "OWNER",
                                "valid_from": int(time.time()), "expires_at": int(time.time())+1000})
        with self.assertRaises(OrganizationError): self.change("SUSPEND_MEMBER", 1, "MEMBER", WALLETS[0])
        self.change("SUSPEND_MEMBER", target_type="MEMBER", target_id=WALLETS[1])
        with self.assertRaises(OrganizationError): self.store.read(ORG, WALLETS[1])
        self.change("REINSTATE_MEMBER", target_type="MEMBER", target_id=WALLETS[1])
        self.change("REMOVE_MEMBER", target_type="MEMBER", target_id=WALLETS[1])
        with self.assertRaises(OrganizationError): self.store.read(ORG, WALLETS[1])
        new_inv = "inv_"+"a"*32
        self.change("INVITE_HUMAN", target_type="INVITATION", target_id=new_inv,
                    payload={"subject_pubkey": WALLETS[1], "role_id": "VIEWER",
                             "valid_from": int(time.time()), "expires_at": int(time.time())+1000})
        self.change("ACCEPT_HUMAN", 1, "INVITATION", new_inv)
        self.assertEqual(self.store.read(ORG, WALLETS[1], "permissions")["effective_role"], "VIEWER")

    def test_delegation_scope_and_revocation(self):
        for actor in (1, 2):
            inv = self.invite_human(actor)
            self.change("ACCEPT_HUMAN", actor, "INVITATION", inv)
        delegation = "del_"+"a"*32
        now = int(time.time())
        self.change("CREATE_DELEGATION", target_type="DELEGATION", target_id=delegation,
            payload={"delegate_pubkey": WALLETS[1], "permission": "members.suspend",
                     "resource_scope": WALLETS[2], "valid_from": now, "expires_at": now+500})
        state = self.store._load(ORG)[0]
        self.assertEqual(evaluate_organization_permission(state["organization"], WALLETS[1],
            state["members"], state["roles"], state["delegations"], "members.suspend",
            WALLETS[2], now)["decision"], "ALLOW")
        self.assertEqual(evaluate_organization_permission(state["organization"], WALLETS[1],
            state["members"], state["roles"], state["delegations"], "members.suspend",
            WALLETS[3], now)["decision"], "DENY")
        self.change("SUSPEND_MEMBER", 1, "MEMBER", WALLETS[2])
        self.change("REVOKE_DELEGATION", target_type="DELEGATION", target_id=delegation)
        with self.assertRaises(OrganizationError): self.change("SUSPEND_MEMBER", 1, "MEMBER", WALLETS[2])
        with self.assertRaises(OrganizationError): self.change("ASSIGN_ROLE", 1, "MEMBER", WALLETS[1],
            {"role_id": "OWNER"})

    def test_agent_consent_owner_change_and_status(self):
        inv = "inv_"+"f"*32
        now = int(time.time())
        self.change("INVITE_AGENT", target_type="INVITATION", target_id=inv,
            payload={"agent_account": AGENT, "registration": copy.deepcopy(self.registration),
                     "valid_from": now, "expires_at": now+1000})
        consent = {"agent_account": AGENT, "registration_snapshot_hash": digest(self.registration)}
        with self.assertRaises(OrganizationError): self.change("ACCEPT_AGENT", 1, "INVITATION", inv, consent)
        self.change("ACCEPT_AGENT", 2, "INVITATION", inv, consent)
        self.assertEqual(self.store.read(ORG, WALLETS[0], "agents")[0]["effective_status"], "ACTIVE")
        self.registration["agent_owner_pubkey"] = WALLETS[3]
        with self.assertRaises(OrganizationError): self.store.read(ORG, WALLETS[2])
        self.assertEqual(self.store.read(ORG, WALLETS[0], "agents")[0]["effective_status"], "REVIEW_REQUIRED")
        self.registration["agent_status"] = "Revoked"
        self.assertEqual(self.store.read(ORG, WALLETS[0], "agents")[0]["effective_status"], "REVIEW_REQUIRED")

    def test_audit_tamper_immutable_restart_and_concurrency(self):
        inv = self.invite_human()
        with self.assertRaises(sqlite3.DatabaseError):
            self.store.conn.execute("UPDATE organization_events SET event_hash='x' WHERE version=1")
        with self.assertRaises(sqlite3.DatabaseError):
            self.store.conn.execute("DELETE FROM organization_events WHERE version=1")
        self.store.close()
        self.store = OrganizationStore(Path(self.tmp.name)/"organizations.sqlite", self.snapshot)
        self.assertEqual(len(self.store.read(ORG, WALLETS[0], "audit-events")), 2)
        now = int(time.time())
        body = request("UPDATE_METADATA", version=2, payload={"description": "new"}, nonce="concurrent-nonce-123456")
        def retry(_):
            try:
                return self.change(body=body)[0][1]
            except OrganizationError as exc:
                return exc.code
        with ThreadPoolExecutor(max_workers=10) as pool:
            results = list(pool.map(retry, range(10)))
        self.assertEqual(results.count(True), 1)
        self.assertEqual(results.count(False), 9)
        self.assertEqual(len(self.store.read(ORG, WALLETS[0], "audit-events")), 3)
        with mock.patch.object(self.store, "_load", wraps=self.store._load):
            with self.assertRaises(OrganizationError): self.change("UPDATE_METADATA", payload={"owner_pubkey": WALLETS[1]})

    def test_agent_owner_changes_before_acceptance_need_new_signed_invitation(self):
        now = int(time.time())
        first = "inv_"+"b"*32
        old = copy.deepcopy(self.registration)
        self.change("INVITE_AGENT", target_type="INVITATION", target_id=first,
            payload={"agent_account": AGENT, "registration": old,
                     "valid_from": now, "expires_at": now+1000})
        self.registration["agent_owner_pubkey"] = WALLETS[3]
        with self.assertRaises(OrganizationError): self.store.read(ORG, WALLETS[2])
        with self.assertRaises(OrganizationError) as changed:
            self.change("ACCEPT_AGENT", 2, "INVITATION", first,
                        {"agent_account": AGENT, "registration_snapshot_hash": digest(old)})
        self.assertEqual(changed.exception.code, "AGENT_IDENTITY_CHANGED")
        # The previous signed invitation remains historical; the new owner cannot reuse it.
        with self.assertRaises(OrganizationError):
            self.change("ACCEPT_AGENT", 3, "INVITATION", first,
                        {"agent_account": AGENT, "registration_snapshot_hash": digest(old)})
        second = "inv_"+"c"*32
        self.change("INVITE_AGENT", target_type="INVITATION", target_id=second,
            payload={"agent_account": AGENT, "registration": copy.deepcopy(self.registration),
                     "valid_from": now, "expires_at": now+1000})
        self.change("ACCEPT_AGENT", 3, "INVITATION", second,
                    {"agent_account": AGENT, "registration_snapshot_hash": digest(self.registration)})
        self.assertEqual(self.store.read(ORG, WALLETS[0], "agents")[0]["consented_by"], WALLETS[3])

    def test_expired_delegation_suspended_delegator_and_unknown_permission_deny(self):
        for actor in (1, 2):
            inv = self.invite_human(actor)
            self.change("ACCEPT_HUMAN", actor, "INVITATION", inv)
        now = int(time.time())
        delegation = "del_"+"b"*32
        self.change("CREATE_DELEGATION", target_type="DELEGATION", target_id=delegation,
            payload={"delegate_pubkey": WALLETS[1], "permission": "members.suspend",
                     "resource_scope": WALLETS[2], "valid_from": now, "expires_at": now+10})
        state = self.store._load(ORG)[0]
        evaluate = lambda permission, at: evaluate_organization_permission(state["organization"], WALLETS[1],
            state["members"], state["roles"], state["delegations"], permission, WALLETS[2], at)
        self.assertEqual(evaluate("members.suspend", now)["decision"], "ALLOW")
        self.assertEqual(evaluate("members.suspend", now+11)["decision"], "DENY")
        self.assertEqual(evaluate("treasury.withdraw", now)["reason_codes"], ["UNKNOWN_PERMISSION"])
        self.change("SUSPEND_MEMBER", target_type="MEMBER", target_id=WALLETS[1])
        state = self.store._load(ORG)[0]
        self.assertEqual(evaluate_organization_permission(state["organization"], WALLETS[1],
            state["members"], state["roles"], state["delegations"], "members.suspend", WALLETS[2], now)["decision"], "DENY")

    def test_truncated_or_rewritten_signed_history_is_rejected(self):
        self.invite_human()
        self.store.conn.execute("DROP TRIGGER immutable_org_events_delete")
        self.store.conn.execute("DELETE FROM organization_events WHERE version=2")
        with self.assertRaises(OrganizationError) as truncated:
            self.store.read(ORG, WALLETS[0], "audit-events")
        self.assertEqual(truncated.exception.code, "AUDIT_INTEGRITY_CONFLICT")
        self.store.conn.execute("DROP TRIGGER immutable_org_events_update")
        self.store.conn.execute("UPDATE organization_events SET signature='altered' WHERE version=1")
        with self.assertRaises(OrganizationError) as forged:
            self.store.read(ORG, WALLETS[0])
        self.assertEqual(forged.exception.code, "AUDIT_INTEGRITY_CONFLICT")

    def test_stale_version_reused_nonce_and_root_recovery(self):
        original = request("UPDATE_METADATA", version=1, payload={"description": "first"},
                           nonce="stale-nonce-123456")
        original["idempotency_key"] = "stale-idempotency-123456"
        self.change("UPDATE_METADATA", payload={"description": "second"})
        with self.assertRaises(OrganizationError) as stale:
            self.change(body=original)
        self.assertEqual(stale.exception.code, "VERSION_CONFLICT")
        with self.assertRaises(OrganizationError) as reused:
            changed = {**original, "expected_version": 2, "idempotency_key": "different-idempotency-0001"}
            self.change(body=changed)
            self.change(body={**changed, "payload": {"description": "other"},
                              "idempotency_key": "different-idempotency-0002"})
        self.assertEqual(reused.exception.code, "IDEMPOTENCY_CONFLICT")
        self.change("UPDATE_METADATA", payload={"organization_status": "SUSPENDED"})
        self.assertEqual(self.store.read(ORG, WALLETS[0])["organization"]["organization_status"], "SUSPENDED")
        with self.assertRaises(OrganizationError): self.store.read(ORG, WALLETS[1])
        self.change("UPDATE_METADATA", payload={"organization_status": "ACTIVE"})
        self.assertEqual(self.store.read(ORG, WALLETS[0])["organization"]["organization_status"], "ACTIVE")

    def test_suspended_inviter_cannot_activate_pending_membership(self):
        first = self.invite_human(1, "ADMIN")
        self.change("ACCEPT_HUMAN", 1, "INVITATION", first)
        now = int(time.time())
        self.change("CREATE_DELEGATION", target_type="DELEGATION", target_id="del_"+"e"*32,
            payload={"delegate_pubkey": WALLETS[1], "permission": "members.invite",
                     "resource_scope": "organization", "valid_from": now, "expires_at": now+1000})
        second = "inv_"+"e"*32
        self.change("INVITE_HUMAN", 1, "INVITATION", second,
            {"subject_pubkey": WALLETS[2], "role_id": "MEMBER", "valid_from": now,
             "expires_at": now+900})
        self.change("SUSPEND_MEMBER", target_type="MEMBER", target_id=WALLETS[1])
        with self.assertRaises(OrganizationError) as denied:
            self.change("ACCEPT_HUMAN", 2, "INVITATION", second)
        self.assertEqual(denied.exception.code, "FORBIDDEN")

    def test_two_organizations_never_mix_memberships_or_roles(self):
        other_id = "org_"+"b"*32
        other = request("CREATE", actor=2)
        other["organization_id"] = other_id
        other["target_id"] = other_id
        other["nonce"] = "other-org-nonce-123456"
        other["idempotency_key"] = "other-org-idem-123456"
        other["payload"] = {**other["payload"], "owner_pubkey": WALLETS[2],
                            "organization_slug": "fleet-two"}
        path, message, signature, headers = signed(other, 2)
        verify_mutation("POST", path, other, headers)
        self.store.mutate(other, signature, message, WALLETS[2])
        self.assertEqual(self.store.read(other_id, WALLETS[2])["organization"]["owner_pubkey"], WALLETS[2])
        with self.assertRaises(OrganizationError): self.store.read(other_id, WALLETS[0])
        with self.assertRaises(OrganizationError): self.store.read(ORG, WALLETS[2])
        self.assertEqual(len(self.store.list_for(WALLETS[0])), 1)
        self.assertEqual(len(self.store.list_for(WALLETS[2])), 1)

    def test_two_simultaneous_invitations_cannot_duplicate_member(self):
        now = int(time.time())
        first = request("INVITE_HUMAN", version=1, target_type="INVITATION", target_id="inv_"+"4"*32,
            payload={"subject_pubkey": WALLETS[1], "role_id": "MEMBER",
                     "valid_from": now, "expires_at": now+1000})
        second = request("INVITE_HUMAN", version=1, target_type="INVITATION", target_id="inv_"+"5"*32,
            payload={"subject_pubkey": WALLETS[1], "role_id": "MEMBER",
                     "valid_from": now, "expires_at": now+1000})
        def submit(body):
            try:
                return self.change(body=body)[0][1]
            except OrganizationError as exc:
                return exc.code
        with ThreadPoolExecutor(max_workers=2) as pool:
            result = list(pool.map(submit, (first, second)))
        self.assertEqual(result.count(True), 1)
        self.assertEqual(len(self.store.read(ORG, WALLETS[0], "invitations")), 1)

    def test_unknown_payload_permissions_and_role_escalation_fail_closed(self):
        with self.assertRaises(OrganizationError) as unknown:
            self.change("INVITE_HUMAN", target_type="INVITATION", target_id="inv_"+"8"*32,
                payload={"subject_pubkey": WALLETS[1], "role_id": "MEMBER",
                         "valid_from": int(time.time()), "expires_at": int(time.time())+1000,
                         "proposed_permissions": ["treasury.withdraw"]})
        self.assertEqual(unknown.exception.code, "INVALID_BODY")
        with self.assertRaises(OrganizationError) as root:
            self.change("INVITE_HUMAN", target_type="INVITATION", target_id="inv_"+"9"*32,
                payload={"subject_pubkey": WALLETS[1], "role_id": "OWNER",
                         "valid_from": int(time.time()), "expires_at": int(time.time())+1000})
        self.assertEqual(root.exception.code, "INVALID_ROLE")

    def test_declared_representative_needs_own_signature_and_stays_unverified(self):
        # A separate organization demonstrates the declaration before the representative consents.
        other_id = "org_"+"c"*32
        creation = request("CREATE", actor=0)
        creation.update({"organization_id": other_id, "target_id": other_id,
                         "nonce": "representative-nonce-123456",
                         "idempotency_key": "representative-idem-123456"})
        creation["payload"] = {**creation["payload"], "organization_slug": "fleet-three",
                               "legal_representative_pubkey": WALLETS[1]}
        _, message, signature, _ = signed(creation)
        self.store.mutate(creation, signature, message, WALLETS[0])
        pending = self.store.read(other_id, WALLETS[0])["organization"]
        self.assertEqual(pending["legal_representative_status"], "PENDING_VERIFICATION")
        now = int(time.time())
        invitation = {**request("INVITE_HUMAN", version=1, target_type="INVITATION",
            target_id="inv_"+"d"*32, payload={"subject_pubkey": WALLETS[1],
                "role_id": "LEGAL_REPRESENTATIVE", "valid_from": now, "expires_at": now+1000}),
            "organization_id": other_id, "nonce": "representative-invite-nonce",
            "idempotency_key": "representative-invite-idem"}
        message = mutation_message("POST", f"/v1/organizations/{other_id}/actions", invitation)
        self.store.mutate(invitation, b58encode(KEYS[0].sign(message)), message, WALLETS[0])
        acceptance = {**request("ACCEPT_HUMAN", actor=1, version=2, target_type="INVITATION",
            target_id=invitation["target_id"]), "organization_id": other_id,
            "nonce": "representative-accept-nonce", "idempotency_key": "representative-accept-idem"}
        message = mutation_message("POST", f"/v1/organizations/{other_id}/actions", acceptance)
        self.store.mutate(acceptance, b58encode(KEYS[1].sign(message)), message, WALLETS[1])
        after = self.store.read(other_id, WALLETS[0])["organization"]
        self.assertEqual(after["legal_representative_status"], "UNVERIFIED")
        self.assertEqual(after["legal_entity_verification_status"], "UNVERIFIED")


if __name__ == "__main__":
    unittest.main()
