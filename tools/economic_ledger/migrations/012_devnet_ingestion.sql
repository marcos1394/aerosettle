-- CON-37: read-only Devnet ingestion journal. Historical ledger rows are untouched.
CREATE TABLE ingestion_checkpoints (
    scope_id TEXT PRIMARY KEY,
    network TEXT NOT NULL,
    genesis_hash TEXT NOT NULL,
    program_id TEXT NOT NULL,
    token_mint TEXT NOT NULL,
    ingestion_scope TEXT NOT NULL,
    work_order_account TEXT NOT NULL,
    min_slot INTEGER NOT NULL CHECK(min_slot >= 0),
    max_slot INTEGER CHECK(max_slot IS NULL OR max_slot >= min_slot),
    last_processed_signature TEXT,
    last_finalized_slot INTEGER,
    last_successful_sync INTEGER,
    cursor_version INTEGER NOT NULL DEFAULT 1 CHECK(cursor_version = 1),
    checkpoint_status TEXT NOT NULL CHECK(checkpoint_status IN ('READY', 'INCOMPLETE', 'GAP')),
    UNIQUE(network, genesis_hash, program_id, token_mint, ingestion_scope)
);

CREATE TABLE ingestion_observations (
    scope_id TEXT NOT NULL REFERENCES ingestion_checkpoints(scope_id) ON DELETE RESTRICT,
    signature TEXT NOT NULL,
    slot INTEGER NOT NULL CHECK(slot > 0),
    processing_status TEXT NOT NULL CHECK(processing_status IN
        ('DISCOVERED', 'PENDING_FINALITY', 'FINALIZED', 'UNVERIFIABLE',
         'INSUFFICIENT_DATA', 'RECONCILED')),
    error_category TEXT,
    attempt_count INTEGER NOT NULL CHECK(attempt_count > 0),
    event_count INTEGER NOT NULL DEFAULT 0 CHECK(event_count >= 0),
    evidence_hash TEXT,
    finalization_lag_seconds INTEGER CHECK(finalization_lag_seconds IS NULL OR finalization_lag_seconds >= 0),
    updated_at INTEGER NOT NULL,
    PRIMARY KEY(scope_id, signature)
);

CREATE TABLE ingestion_effects (
    network TEXT NOT NULL,
    genesis_hash TEXT NOT NULL,
    transaction_signature TEXT NOT NULL,
    instruction_index INTEGER NOT NULL CHECK(instruction_index >= 0),
    effect_kind TEXT NOT NULL CHECK(effect_kind IN ('operator_payout', 'creator_refund')),
    destination_account TEXT NOT NULL,
    token_mint TEXT NOT NULL,
    effect_id TEXT NOT NULL UNIQUE,
    work_order_account TEXT NOT NULL,
    agent_account TEXT NOT NULL,
    owner_pubkey TEXT NOT NULL,
    amount_base_units INTEGER NOT NULL CHECK(amount_base_units >= 0),
    evidence_hash TEXT NOT NULL,
    movement_id TEXT REFERENCES economic_movements(movement_id) ON DELETE RESTRICT,
    created_at INTEGER NOT NULL,
    PRIMARY KEY(network, genesis_hash, transaction_signature, instruction_index,
                effect_kind, destination_account, token_mint)
);
CREATE INDEX idx_ingestion_effects_scope ON ingestion_effects(work_order_account, transaction_signature);

CREATE TABLE ingestion_incidents (
    incident_id INTEGER PRIMARY KEY AUTOINCREMENT,
    scope_id TEXT NOT NULL REFERENCES ingestion_checkpoints(scope_id) ON DELETE RESTRICT,
    signature TEXT,
    slot INTEGER,
    error_category TEXT NOT NULL,
    detail TEXT NOT NULL,
    observed_at INTEGER NOT NULL
);
CREATE INDEX idx_ingestion_incidents_scope ON ingestion_incidents(scope_id, observed_at);
