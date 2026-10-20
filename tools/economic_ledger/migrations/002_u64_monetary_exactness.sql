-- CON-22: Upgrade monetary fields to TEXT for u64 exactness and allow 0 base units for audit events
-- Version: 002
-- Name: u64_monetary_exactness

-- 1. Upgrade ledger_entries
CREATE TABLE new_ledger_entries (
    entry_id TEXT PRIMARY KEY,
    journal_entry_id TEXT NOT NULL REFERENCES journal_entries(journal_entry_id) ON DELETE RESTRICT,
    agent_account TEXT,
    account_name TEXT NOT NULL,
    entry_type TEXT NOT NULL CHECK(entry_type IN ('DEBIT', 'CREDIT')),
    amount_base_units TEXT NOT NULL CHECK(amount_base_units >= 0),
    created_at INTEGER NOT NULL
);

INSERT INTO new_ledger_entries (entry_id, journal_entry_id, agent_account, account_name, entry_type, amount_base_units, created_at)
SELECT entry_id, journal_entry_id, agent_account, account_name, entry_type, CAST(amount_base_units AS TEXT), created_at
FROM ledger_entries;

DROP TABLE ledger_entries;
ALTER TABLE new_ledger_entries RENAME TO ledger_entries;
CREATE INDEX IF NOT EXISTS idx_ledger_journal ON ledger_entries(journal_entry_id);

-- 2. Upgrade economic_movements
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
    nature TEXT NOT NULL CHECK(nature IN ('INCOME', 'EXPENSE', 'RESERVE', 'ADJUSTMENT')),
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
    program_id, token_mint, CAST(amount_base_units AS TEXT), amount_str, nature, status,
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
