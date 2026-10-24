-- CON-29: off-chain owner consent; append-only, with no economic ledger writes.
CREATE TABLE spending_approvals (
    approval_id TEXT PRIMARY KEY,
    proposal_id TEXT NOT NULL UNIQUE REFERENCES spending_proposals(proposal_id) ON DELETE RESTRICT,
    decision_id TEXT NOT NULL UNIQUE REFERENCES spending_decisions(decision_id) ON DELETE RESTRICT,
    agent_account TEXT NOT NULL,
    agent_id TEXT NOT NULL,
    owner_pubkey TEXT NOT NULL,
    network TEXT NOT NULL,
    genesis_hash TEXT NOT NULL,
    program_id TEXT NOT NULL,
    token_mint TEXT NOT NULL,
    recipient_pubkey TEXT NOT NULL,
    amount_base_units_str TEXT NOT NULL CHECK(
        length(amount_base_units_str) BETWEEN 1 AND 20 AND
        amount_base_units_str NOT GLOB '*[^0-9]*' AND
        (amount_base_units_str = '0' OR substr(amount_base_units_str, 1, 1) != '0') AND
        (length(amount_base_units_str) < 20 OR amount_base_units_str <= '18446744073709551615')),
    proposal_hash TEXT NOT NULL,
    decision_hash TEXT NOT NULL,
    economic_snapshot_hash TEXT NOT NULL,
    policy_id TEXT NOT NULL,
    policy_version INTEGER NOT NULL CHECK(policy_version > 0),
    policy_hash TEXT NOT NULL,
    created_at INTEGER NOT NULL CHECK(created_at >= 0),
    expires_at INTEGER NOT NULL CHECK(expires_at > created_at),
    FOREIGN KEY(policy_id, policy_version) REFERENCES agent_budget_policy_versions(policy_id, version) ON DELETE RESTRICT
);
CREATE INDEX idx_spending_approvals_scope ON spending_approvals(agent_account, agent_id, owner_pubkey, created_at DESC);

CREATE TABLE spending_approval_events (
    event_id TEXT PRIMARY KEY,
    approval_id TEXT NOT NULL REFERENCES spending_approvals(approval_id) ON DELETE RESTRICT,
    proposal_id TEXT NOT NULL REFERENCES spending_proposals(proposal_id) ON DELETE RESTRICT,
    decision_id TEXT NOT NULL REFERENCES spending_decisions(decision_id) ON DELETE RESTRICT,
    action TEXT NOT NULL CHECK(action IN ('OPEN', 'APPROVE', 'REJECT', 'REVOKE')),
    actor_pubkey TEXT NOT NULL,
    policy_id TEXT NOT NULL,
    policy_version INTEGER NOT NULL,
    policy_hash TEXT NOT NULL,
    proposal_hash TEXT NOT NULL,
    decision_hash TEXT NOT NULL,
    occurred_at INTEGER NOT NULL CHECK(occurred_at >= 0),
    reason TEXT NOT NULL,
    signature TEXT NOT NULL,
    signature_message_hash TEXT NOT NULL,
    signature_message TEXT NOT NULL,
    signed_body_json TEXT NOT NULL,
    idempotency_key TEXT NOT NULL UNIQUE,
    nonce TEXT NOT NULL UNIQUE,
    event_hash TEXT NOT NULL,
    previous_event_hash TEXT,
    body_hash TEXT NOT NULL,
    FOREIGN KEY(policy_id, policy_version) REFERENCES agent_budget_policy_versions(policy_id, version) ON DELETE RESTRICT
);
CREATE INDEX idx_spending_approval_events_history ON spending_approval_events(approval_id, occurred_at, event_id);

CREATE TRIGGER immutable_spending_approvals_update BEFORE UPDATE ON spending_approvals
BEGIN SELECT RAISE(ABORT, 'spending approvals are immutable'); END;
CREATE TRIGGER immutable_spending_approvals_delete BEFORE DELETE ON spending_approvals
BEGIN SELECT RAISE(ABORT, 'spending approvals are immutable'); END;
CREATE TRIGGER immutable_spending_approval_events_update BEFORE UPDATE ON spending_approval_events
BEGIN SELECT RAISE(ABORT, 'spending approval events are immutable'); END;
CREATE TRIGGER immutable_spending_approval_events_delete BEFORE DELETE ON spending_approval_events
BEGIN SELECT RAISE(ABORT, 'spending approval events are immutable'); END;
