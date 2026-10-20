-- CON-22: Persistent Economic Ledger Schema
-- Version: 001
-- Name: initial_economic_ledger

CREATE TABLE IF NOT EXISTS schema_migrations (
    version INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    applied_at INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS journal_entries (
    journal_entry_id TEXT PRIMARY KEY,
    idempotency_key TEXT UNIQUE NOT NULL,
    network TEXT NOT NULL,
    genesis_hash TEXT NOT NULL,
    program_id TEXT NOT NULL,
    token_mint TEXT NOT NULL,
    description TEXT NOT NULL,
    tx_signature TEXT,
    work_order_account TEXT,
    status TEXT NOT NULL CHECK(status IN ('PROVISIONAL', 'RECONCILED', 'REVERTED')),
    created_at INTEGER NOT NULL,
    observed_at INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS ledger_entries (
    entry_id TEXT PRIMARY KEY,
    journal_entry_id TEXT NOT NULL REFERENCES journal_entries(journal_entry_id) ON DELETE RESTRICT,
    agent_account TEXT,
    account_name TEXT NOT NULL,
    entry_type TEXT NOT NULL CHECK(entry_type IN ('DEBIT', 'CREDIT')),
    amount_base_units INTEGER NOT NULL CHECK(amount_base_units > 0),
    created_at INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS economic_movements (
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
    amount_base_units INTEGER NOT NULL CHECK(amount_base_units > 0),
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

CREATE INDEX IF NOT EXISTS idx_movements_agent ON economic_movements(agent_account, registered_at DESC);
CREATE INDEX IF NOT EXISTS idx_movements_mint_net ON economic_movements(network, token_mint);
CREATE INDEX IF NOT EXISTS idx_movements_nature ON economic_movements(nature);
CREATE INDEX IF NOT EXISTS idx_movements_status ON economic_movements(status);
CREATE INDEX IF NOT EXISTS idx_movements_wo ON economic_movements(work_order_account);
CREATE INDEX IF NOT EXISTS idx_movements_reversal ON economic_movements(reversal_of_movement_id);
CREATE INDEX IF NOT EXISTS idx_ledger_journal ON ledger_entries(journal_entry_id);
