-- CON-45: x402 evidence belongs to the Economic Ledger, never to sandbox settlement accounting.
CREATE TABLE x402_payments (
    schema_version INTEGER NOT NULL CHECK(schema_version = 1),
    payment_id TEXT PRIMARY KEY,
    receipt_id TEXT NOT NULL UNIQUE,
    requirements_hash TEXT NOT NULL UNIQUE,
    payload_hash TEXT NOT NULL UNIQUE,
    receipt_hash TEXT NOT NULL,
    receipt_json TEXT NOT NULL,
    facilitator_pubkey TEXT NOT NULL,
    facilitator_id TEXT NOT NULL,
    resource_id TEXT NOT NULL,
    resource_url TEXT NOT NULL,
    client_agent_account TEXT NOT NULL,
    client_agent_id TEXT NOT NULL,
    client_owner_pubkey TEXT NOT NULL,
    provider_agent_account TEXT NOT NULL,
    provider_agent_id TEXT NOT NULL,
    provider_owner_pubkey TEXT NOT NULL,
    payer TEXT NOT NULL,
    recipient TEXT NOT NULL,
    network TEXT NOT NULL,
    genesis_hash TEXT NOT NULL,
    program_id TEXT NOT NULL,
    asset TEXT NOT NULL,
    token_program TEXT NOT NULL,
    decimals INTEGER NOT NULL CHECK(decimals BETWEEN 0 AND 9),
    amount_base_units TEXT NOT NULL,
    provenance TEXT NOT NULL CHECK(provenance = 'SANDBOX_SIMULATION'),
    finality TEXT NOT NULL CHECK(finality = 'UNVERIFIED'),
    reconciliation_status TEXT NOT NULL CHECK(reconciliation_status = 'INSUFFICIENT_DATA'),
    transaction_signature TEXT CHECK(transaction_signature IS NULL),
    instruction_index INTEGER CHECK(instruction_index IS NULL),
    record_hash TEXT NOT NULL,
    created_at INTEGER NOT NULL
);
CREATE INDEX idx_x402_payments_client ON x402_payments(client_agent_account, client_owner_pubkey, network, asset);
CREATE INDEX idx_x402_payments_provider ON x402_payments(provider_agent_account, provider_owner_pubkey, network, asset);

CREATE TABLE x402_events (
    schema_version INTEGER NOT NULL CHECK(schema_version = 1),
    event_id TEXT PRIMARY KEY,
    payment_id TEXT NOT NULL REFERENCES x402_payments(payment_id) ON DELETE RESTRICT,
    event_type TEXT NOT NULL CHECK(event_type IN
      ('RESOURCE_REQUESTED', 'PAYMENT_REQUIREMENTS_RECEIVED', 'AUTHORIZATION_EVALUATED',
       'FACILITATOR_VERIFIED', 'SETTLEMENT_ATTEMPTED', 'RECEIPT_IMPORTED',
       'DUPLICATE_RECEIVED', 'RPC_EVIDENCE_CHECKED', 'FINALITY_CONFIRMED',
       'RECONCILIATION_DIFFERENCE', 'REFUND_OBSERVED')),
    status TEXT NOT NULL CHECK(status IN
      ('SANDBOX_SIMULATION', 'PENDING', 'REJECTED', 'INSUFFICIENT_DATA',
       'LIVE_RPC', 'FINALIZED', 'RECONCILED')),
    detail_code TEXT NOT NULL,
    event_hash TEXT NOT NULL,
    created_at INTEGER NOT NULL,
    UNIQUE(payment_id, event_type, detail_code)
);
CREATE INDEX idx_x402_events_payment ON x402_events(payment_id, created_at);

-- Reserved for independently verified CON-96 effects. CON-45 never inserts here.
-- The canonical effect identity is scoped to chain, instruction, kind, agent and asset.
CREATE TABLE x402_verified_effects (
    effect_id TEXT PRIMARY KEY,
    payment_id TEXT NOT NULL REFERENCES x402_payments(payment_id) ON DELETE RESTRICT,
    network TEXT NOT NULL,
    genesis_hash TEXT NOT NULL,
    transaction_signature TEXT NOT NULL,
    instruction_index INTEGER NOT NULL CHECK(instruction_index >= 0),
    effect_type TEXT NOT NULL CHECK(effect_type IN
      ('X402_PAYMENT', 'RESOURCE_REVENUE', 'FACILITATOR_FEE', 'NETWORK_FEE',
       'PROVIDER_PAYOUT', 'PAYER_COST', 'REFUND', 'ECONOMIC_ADJUSTMENT')),
    agent_account TEXT NOT NULL,
    owner_pubkey TEXT NOT NULL,
    asset TEXT NOT NULL,
    token_program TEXT NOT NULL,
    recipient TEXT NOT NULL,
    amount_base_units TEXT NOT NULL,
    evidence_hash TEXT NOT NULL,
    movement_id TEXT REFERENCES economic_movements(movement_id) ON DELETE RESTRICT,
    UNIQUE(network, genesis_hash, transaction_signature, instruction_index,
           effect_type, agent_account, asset)
);
