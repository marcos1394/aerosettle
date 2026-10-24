-- CON-27: versioned off-chain policy configuration. No accounting table is modified.
CREATE TABLE agent_budget_policies (
    policy_id TEXT PRIMARY KEY,
    agent_account TEXT NOT NULL UNIQUE,
    agent_id TEXT NOT NULL,
    owner_pubkey TEXT NOT NULL,
    network TEXT NOT NULL,
    genesis_hash TEXT NOT NULL,
    program_id TEXT NOT NULL,
    current_version INTEGER NOT NULL CHECK(current_version >= 1)
);

CREATE INDEX idx_budget_policies_agent ON agent_budget_policies(agent_account);
CREATE INDEX idx_budget_policies_owner ON agent_budget_policies(owner_pubkey, agent_account);

CREATE TABLE agent_budget_policy_versions (
    policy_id TEXT NOT NULL REFERENCES agent_budget_policies(policy_id) ON DELETE RESTRICT,
    version INTEGER NOT NULL CHECK(version >= 1),
    status TEXT NOT NULL CHECK(status IN ('DRAFT', 'ACTIVE', 'PAUSED', 'REVOKED')),
    valid_from INTEGER NOT NULL CHECK(valid_from >= 0),
    expires_at INTEGER NOT NULL CHECK(expires_at > valid_from),
    created_at INTEGER NOT NULL,
    created_by TEXT NOT NULL,
    revision_reason TEXT,
    policy_hash TEXT NOT NULL,
    request_hash TEXT NOT NULL,
    idempotency_key TEXT NOT NULL UNIQUE,
    nonce TEXT NOT NULL UNIQUE,
    action TEXT NOT NULL CHECK(action IN ('CREATE', 'UPDATE', 'ACTIVATE', 'PAUSE', 'RESUME', 'REVOKE')),
    PRIMARY KEY(policy_id, version)
);

CREATE INDEX idx_budget_versions_latest ON agent_budget_policy_versions(policy_id, version DESC);

CREATE TABLE agent_budget_policy_asset_rules (
    policy_id TEXT NOT NULL,
    version INTEGER NOT NULL,
    token_mint TEXT NOT NULL,
    max_per_operation_base_units_str TEXT NOT NULL,
    max_daily_spend_base_units_str TEXT NOT NULL,
    minimum_reserve_base_units_str TEXT NOT NULL,
    enabled INTEGER NOT NULL CHECK(enabled IN (0, 1)),
    PRIMARY KEY(policy_id, version, token_mint),
    FOREIGN KEY(policy_id, version) REFERENCES agent_budget_policy_versions(policy_id, version) ON DELETE RESTRICT
);

CREATE TABLE agent_budget_policy_recipients (
    policy_id TEXT NOT NULL,
    version INTEGER NOT NULL,
    recipient_pubkey TEXT NOT NULL,
    PRIMARY KEY(policy_id, version, recipient_pubkey),
    FOREIGN KEY(policy_id, version) REFERENCES agent_budget_policy_versions(policy_id, version) ON DELETE RESTRICT
);

-- Historical policy content is append-only, even for direct SQLite clients.
CREATE TRIGGER immutable_budget_policy_identity BEFORE UPDATE ON agent_budget_policies
WHEN NEW.policy_id != OLD.policy_id OR NEW.agent_account != OLD.agent_account OR
     NEW.agent_id != OLD.agent_id OR NEW.owner_pubkey != OLD.owner_pubkey OR
     NEW.network != OLD.network OR NEW.genesis_hash != OLD.genesis_hash OR
     NEW.program_id != OLD.program_id
BEGIN SELECT RAISE(ABORT, 'budget policy identity is immutable'); END;
CREATE TRIGGER immutable_budget_policy_delete BEFORE DELETE ON agent_budget_policies
BEGIN SELECT RAISE(ABORT, 'budget policy history cannot be deleted'); END;
CREATE TRIGGER immutable_budget_versions_update BEFORE UPDATE ON agent_budget_policy_versions
BEGIN SELECT RAISE(ABORT, 'budget policy versions are immutable'); END;
CREATE TRIGGER immutable_budget_versions_delete BEFORE DELETE ON agent_budget_policy_versions
BEGIN SELECT RAISE(ABORT, 'budget policy versions are immutable'); END;
CREATE TRIGGER immutable_budget_rules_update BEFORE UPDATE ON agent_budget_policy_asset_rules
BEGIN SELECT RAISE(ABORT, 'budget policy rules are immutable'); END;
CREATE TRIGGER immutable_budget_rules_delete BEFORE DELETE ON agent_budget_policy_asset_rules
BEGIN SELECT RAISE(ABORT, 'budget policy rules are immutable'); END;
CREATE TRIGGER immutable_budget_recipients_update BEFORE UPDATE ON agent_budget_policy_recipients
BEGIN SELECT RAISE(ABORT, 'budget policy recipients are immutable'); END;
CREATE TRIGGER immutable_budget_recipients_delete BEFORE DELETE ON agent_budget_policy_recipients
BEGIN SELECT RAISE(ABORT, 'budget policy recipients are immutable'); END;
