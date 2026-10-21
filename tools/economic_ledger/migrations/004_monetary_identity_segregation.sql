-- CON-24: Monetary Identity Segregation Schema Migration
-- Version: 004
-- Name: monetary_identity_segregation

-- 1. Segregate Agent Costs by full monetary identity: network + genesis_hash + program_id + token_mint
ALTER TABLE agent_costs ADD COLUMN genesis_hash TEXT NOT NULL DEFAULT 'HP9XKTusRPGC78EFDpR9xdEq6simL2vqyDdrMvn6Vacg';
ALTER TABLE agent_costs ADD COLUMN program_id TEXT NOT NULL DEFAULT 'CeA1P1NSuPLUH31KsT4j3pZeBsknQZ3NSC6GUAqcsCLy';

-- Backfill from associated economic movements where available
UPDATE agent_costs
SET genesis_hash = (SELECT em.genesis_hash FROM economic_movements em WHERE em.movement_id = agent_costs.movement_id),
    program_id = (SELECT em.program_id FROM economic_movements em WHERE em.movement_id = agent_costs.movement_id)
WHERE movement_id IS NOT NULL;

-- 2. Segregate Agent Reserves by full monetary identity: network + genesis_hash + program_id + token_mint
ALTER TABLE agent_reserves ADD COLUMN genesis_hash TEXT NOT NULL DEFAULT 'HP9XKTusRPGC78EFDpR9xdEq6simL2vqyDdrMvn6Vacg';
ALTER TABLE agent_reserves ADD COLUMN program_id TEXT NOT NULL DEFAULT 'CeA1P1NSuPLUH31KsT4j3pZeBsknQZ3NSC6GUAqcsCLy';

-- 3. Composite Indexes for fast exact lookups under complete monetary context
CREATE INDEX IF NOT EXISTS idx_costs_monetary_ctx ON agent_costs(agent_account, network, genesis_hash, program_id, token_mint);
CREATE INDEX IF NOT EXISTS idx_reserves_monetary_ctx ON agent_reserves(agent_account, network, genesis_hash, program_id, token_mint);
