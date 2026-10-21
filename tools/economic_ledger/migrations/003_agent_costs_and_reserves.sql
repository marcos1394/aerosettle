-- CON-24: Agent Costs and Economic Reserves Schema
-- Version: 003
-- Name: agent_costs_and_reserves

-- 1. Upgrade economic_movements nature check to support PROVISION, INTERNAL_TRANSFER, and CAPITAL_INVESTMENT
CREATE TABLE new_economic_movements (
    movement_id TEXT PRIMARY KEY,
    journal_entry_id TEXT REFERENCES journal_entries(journal_entry_id) ON DELETE RESTRICT,
    idempotency_key TEXT UNIQUE NOT NULL,
    agent_id TEXT NOT NULL,
    agent_account TEXT NOT NULL,
    owner_pubkey TEXT NOT NULL,
    work_order_account TEXT,
    work_order_id TEXT,
    network TEXT NOT NULL,
    genesis_hash TEXT NOT NULL,
    program_id TEXT NOT NULL,
    token_mint TEXT NOT NULL,
    amount_base_units TEXT NOT NULL CHECK(amount_base_units >= 0),
    amount_str TEXT NOT NULL,
    nature TEXT NOT NULL CHECK(nature IN ('INCOME', 'EXPENSE', 'RESERVE', 'ADJUSTMENT', 'PROVISION', 'INTERNAL_TRANSFER', 'CAPITAL_INVESTMENT')),
    status TEXT NOT NULL CHECK(status IN ('PROVISIONAL', 'RECONCILED', 'REVERTED')),
    provenance_source TEXT NOT NULL CHECK(provenance_source IN ('ONCHAIN_VERIFIED', 'EXTERNAL_VERIFIED', 'SIMULATED', 'MANUAL_ENTRY', 'SETTLEMENT_EVENT')),
    evidence_hash TEXT,
    attestation_id TEXT,
    tx_signature TEXT,
    external_ref TEXT,
    registered_at INTEGER NOT NULL,
    observed_at INTEGER NOT NULL,
    reversal_of_movement_id TEXT REFERENCES economic_movements(movement_id) ON DELETE RESTRICT,
    metadata_json TEXT
);

INSERT INTO new_economic_movements (
    movement_id, journal_entry_id, idempotency_key, agent_id, agent_account,
    owner_pubkey, work_order_account, work_order_id, network, genesis_hash,
    program_id, token_mint, amount_base_units, amount_str, nature, status,
    provenance_source, evidence_hash, attestation_id, tx_signature,
    external_ref, registered_at, observed_at, reversal_of_movement_id, metadata_json
)
SELECT
    movement_id, journal_entry_id, idempotency_key, agent_id, agent_account,
    owner_pubkey, work_order_account, work_order_id, network, genesis_hash,
    program_id, token_mint, amount_base_units, amount_str, nature, status,
    provenance_source, evidence_hash, attestation_id, tx_signature,
    external_ref, registered_at, observed_at, reversal_of_movement_id, metadata_json
FROM economic_movements;

DROP TABLE economic_movements;
ALTER TABLE new_economic_movements RENAME TO economic_movements;

CREATE INDEX IF NOT EXISTS idx_movements_agent ON economic_movements(agent_account, registered_at DESC);
CREATE INDEX IF NOT EXISTS idx_movements_mint_net ON economic_movements(network, token_mint);
CREATE INDEX IF NOT EXISTS idx_movements_nature ON economic_movements(nature);
CREATE INDEX IF NOT EXISTS idx_movements_status ON economic_movements(status);
CREATE INDEX IF NOT EXISTS idx_movements_wo ON economic_movements(work_order_account);
CREATE INDEX IF NOT EXISTS idx_movements_reversal ON economic_movements(reversal_of_movement_id);

-- 2. Agent Costs Table
CREATE TABLE IF NOT EXISTS agent_costs (
    cost_id TEXT PRIMARY KEY,
    idempotency_key TEXT UNIQUE NOT NULL,
    agent_id TEXT NOT NULL,
    agent_account TEXT NOT NULL,
    owner_pubkey TEXT NOT NULL,
    category TEXT NOT NULL CHECK(category IN ('ENERGY_FUEL', 'MAINTENANCE', 'CONNECTIVITY_COMPUTE', 'SUBSCRIPTIONS', 'INSURANCE', 'DEPRECIATION_REPLACEMENT', 'OTHER')),
    cost_nature TEXT NOT NULL CHECK(cost_nature IN ('REALIZED', 'ESTIMATED', 'ACCRUED_LIABILITY')),
    economic_period TEXT NOT NULL,
    network TEXT NOT NULL,
    token_mint TEXT NOT NULL,
    amount_base_units TEXT NOT NULL CHECK(amount_base_units >= 0),
    amount_str TEXT NOT NULL,
    status TEXT NOT NULL CHECK(status IN ('PROVISIONAL', 'RECONCILED', 'EXTERNAL_VERIFIED', 'REVERTED')),
    provenance_source TEXT NOT NULL CHECK(provenance_source IN ('ONCHAIN_VERIFIED', 'EXTERNAL_VERIFIED', 'SIMULATED', 'MANUAL_ENTRY', 'SETTLEMENT_EVENT')),
    evidence_hash TEXT,
    evidence_url TEXT,
    attestation_id TEXT,
    description TEXT,
    journal_entry_id TEXT REFERENCES journal_entries(journal_entry_id) ON DELETE RESTRICT,
    movement_id TEXT REFERENCES economic_movements(movement_id) ON DELETE RESTRICT,
    reversal_of_cost_id TEXT REFERENCES agent_costs(cost_id) ON DELETE RESTRICT,
    created_at INTEGER NOT NULL,
    incurred_at INTEGER NOT NULL,
    metadata_json TEXT
);

CREATE INDEX IF NOT EXISTS idx_costs_agent ON agent_costs(agent_account, incurred_at DESC);
CREATE INDEX IF NOT EXISTS idx_costs_category ON agent_costs(agent_account, category);
CREATE INDEX IF NOT EXISTS idx_costs_period ON agent_costs(agent_account, economic_period);
CREATE INDEX IF NOT EXISTS idx_costs_nature ON agent_costs(cost_nature);
CREATE INDEX IF NOT EXISTS idx_costs_status ON agent_costs(status);
CREATE INDEX IF NOT EXISTS idx_costs_mint_net ON agent_costs(network, token_mint);
CREATE INDEX IF NOT EXISTS idx_costs_reversal ON agent_costs(reversal_of_cost_id);

-- 3. Agent Reserves Table
CREATE TABLE IF NOT EXISTS agent_reserves (
    reserve_id TEXT PRIMARY KEY,
    idempotency_key TEXT UNIQUE NOT NULL,
    agent_id TEXT NOT NULL,
    agent_account TEXT NOT NULL,
    owner_pubkey TEXT NOT NULL,
    reserve_type TEXT NOT NULL CHECK(reserve_type IN ('MAINTENANCE', 'HARDWARE_REPLACEMENT', 'OPERATIONAL_CONTINUITY', 'CONTINGENCY')),
    network TEXT NOT NULL,
    token_mint TEXT NOT NULL,
    target_amount_base_units TEXT NOT NULL CHECK(target_amount_base_units >= 0),
    current_reserved_base_units TEXT NOT NULL CHECK(current_reserved_base_units >= 0),
    status TEXT NOT NULL CHECK(status IN ('ACTIVE', 'DEPLETED', 'CLOSED')),
    created_at INTEGER NOT NULL,
    updated_at INTEGER NOT NULL,
    description TEXT,
    metadata_json TEXT
);

CREATE INDEX IF NOT EXISTS idx_reserves_agent ON agent_reserves(agent_account, reserve_type);
CREATE INDEX IF NOT EXISTS idx_reserves_mint_net ON agent_reserves(network, token_mint);
CREATE INDEX IF NOT EXISTS idx_reserves_status ON agent_reserves(status);

-- 4. Reserve Transactions Table (Audit Ledger)
CREATE TABLE IF NOT EXISTS reserve_transactions (
    transaction_id TEXT PRIMARY KEY,
    reserve_id TEXT NOT NULL REFERENCES agent_reserves(reserve_id) ON DELETE RESTRICT,
    idempotency_key TEXT UNIQUE NOT NULL,
    action TEXT NOT NULL CHECK(action IN ('ALLOCATE', 'CONSUME', 'RELEASE')),
    amount_base_units TEXT NOT NULL CHECK(amount_base_units > 0),
    associated_cost_id TEXT REFERENCES agent_costs(cost_id) ON DELETE RESTRICT,
    journal_entry_id TEXT REFERENCES journal_entries(journal_entry_id) ON DELETE RESTRICT,
    movement_id TEXT REFERENCES economic_movements(movement_id) ON DELETE RESTRICT,
    created_at INTEGER NOT NULL,
    metadata_json TEXT
);

CREATE INDEX IF NOT EXISTS idx_reserve_tx_reserve ON reserve_transactions(reserve_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_reserve_tx_cost ON reserve_transactions(associated_cost_id);
