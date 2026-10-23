-- CON-25: coverage attestations and immutable calculation snapshots only.
CREATE TABLE IF NOT EXISTS solvency_coverage (
    coverage_id TEXT PRIMARY KEY,
    agent_account TEXT NOT NULL,
    network TEXT NOT NULL,
    genesis_hash TEXT NOT NULL,
    program_id TEXT NOT NULL,
    token_mint TEXT NOT NULL,
    side TEXT NOT NULL CHECK(side IN ('REVENUE', 'OPEX')),
    window_start INTEGER NOT NULL,
    window_end INTEGER NOT NULL CHECK(window_end > window_start),
    evidence_hash TEXT NOT NULL,
    verifier_id TEXT NOT NULL,
    verified_at INTEGER NOT NULL,
    UNIQUE(agent_account, network, genesis_hash, program_id, token_mint, side, window_start, window_end, evidence_hash)
);
CREATE INDEX IF NOT EXISTS idx_solvency_coverage_scope ON solvency_coverage(agent_account, network, genesis_hash, program_id, token_mint, side, window_start, window_end);

CREATE TABLE IF NOT EXISTS agent_solvency_assessments (
    assessment_id TEXT PRIMARY KEY,
    agent_account TEXT NOT NULL,
    network TEXT NOT NULL,
    genesis_hash TEXT NOT NULL,
    program_id TEXT NOT NULL,
    token_mint TEXT NOT NULL,
    window_start INTEGER NOT NULL,
    window_end INTEGER NOT NULL,
    calculated_at INTEGER NOT NULL,
    methodology_version TEXT NOT NULL,
    threshold_config_version TEXT NOT NULL,
    input_hash TEXT NOT NULL,
    result_json TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_solvency_history ON agent_solvency_assessments(agent_account, network, genesis_hash, program_id, token_mint, calculated_at DESC);
