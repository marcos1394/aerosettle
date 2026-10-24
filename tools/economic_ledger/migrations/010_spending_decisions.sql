-- CON-28: advisory evaluations only; no financial ledger or reserve changes.
CREATE TABLE spending_proposals (
    proposal_id TEXT PRIMARY KEY,
    idempotency_key TEXT NOT NULL UNIQUE,
    nonce TEXT NOT NULL UNIQUE,
    proposal_hash TEXT NOT NULL,
    agent_account TEXT NOT NULL,
    agent_id TEXT NOT NULL,
    owner_pubkey TEXT NOT NULL,
    requester_pubkey TEXT NOT NULL,
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
    requested_at INTEGER NOT NULL,
    payload_json TEXT NOT NULL
);
CREATE INDEX idx_spending_proposals_agent ON spending_proposals(agent_account, requested_at DESC);

CREATE TABLE spending_decisions (
    decision_id TEXT PRIMARY KEY,
    proposal_id TEXT NOT NULL UNIQUE REFERENCES spending_proposals(proposal_id) ON DELETE RESTRICT,
    decision TEXT NOT NULL CHECK(decision IN ('ALLOW', 'DENY', 'REQUIRE_APPROVAL')),
    policy_id TEXT,
    policy_version INTEGER,
    policy_hash TEXT,
    decision_json TEXT NOT NULL,
    economic_snapshot_hash TEXT NOT NULL,
    economic_snapshot_json TEXT NOT NULL,
    evaluated_at INTEGER NOT NULL,
    expires_at INTEGER NOT NULL,
    decision_engine_version TEXT NOT NULL,
    is_executable INTEGER NOT NULL CHECK(is_executable = 0)
);
CREATE INDEX idx_spending_decisions_time ON spending_decisions(evaluated_at DESC);

CREATE TABLE spending_budget_claims (
    decision_id TEXT PRIMARY KEY REFERENCES spending_decisions(decision_id) ON DELETE RESTRICT,
    proposal_id TEXT NOT NULL UNIQUE REFERENCES spending_proposals(proposal_id) ON DELETE RESTRICT,
    agent_account TEXT NOT NULL,
    network TEXT NOT NULL,
    genesis_hash TEXT NOT NULL,
    program_id TEXT NOT NULL,
    token_mint TEXT NOT NULL,
    policy_id TEXT NOT NULL,
    policy_version INTEGER NOT NULL,
    day_start_utc INTEGER NOT NULL,
    amount_base_units_str TEXT NOT NULL CHECK(
        length(amount_base_units_str) BETWEEN 1 AND 20 AND
        amount_base_units_str NOT GLOB '*[^0-9]*' AND amount_base_units_str != '0' AND
        substr(amount_base_units_str, 1, 1) != '0' AND
        (length(amount_base_units_str) < 20 OR amount_base_units_str <= '18446744073709551615')),
    expires_at INTEGER NOT NULL,
    FOREIGN KEY(policy_id, policy_version) REFERENCES agent_budget_policy_versions(policy_id, version) ON DELETE RESTRICT
);
CREATE INDEX idx_spending_claim_capacity ON spending_budget_claims(
    agent_account, network, genesis_hash, program_id, token_mint,
    policy_id, policy_version, day_start_utc, expires_at
);

CREATE TRIGGER immutable_spending_proposals_update BEFORE UPDATE ON spending_proposals
BEGIN SELECT RAISE(ABORT, 'spending proposals are immutable'); END;
CREATE TRIGGER immutable_spending_proposals_delete BEFORE DELETE ON spending_proposals
BEGIN SELECT RAISE(ABORT, 'spending proposals are immutable'); END;
CREATE TRIGGER immutable_spending_decisions_update BEFORE UPDATE ON spending_decisions
BEGIN SELECT RAISE(ABORT, 'spending decisions are immutable'); END;
CREATE TRIGGER immutable_spending_decisions_delete BEFORE DELETE ON spending_decisions
BEGIN SELECT RAISE(ABORT, 'spending decisions are immutable'); END;
CREATE TRIGGER immutable_spending_claims_update BEFORE UPDATE ON spending_budget_claims
BEGIN SELECT RAISE(ABORT, 'spending claims are immutable'); END;
CREATE TRIGGER immutable_spending_claims_delete BEFORE DELETE ON spending_budget_claims
BEGIN SELECT RAISE(ABORT, 'spending claims are immutable'); END;
