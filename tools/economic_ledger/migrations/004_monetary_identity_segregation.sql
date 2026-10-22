-- CON-24: Monetary Identity Segregation Schema Migration
-- Version: 004
-- Name: monetary_identity_segregation

-- 1. Segregate Agent Costs by full monetary identity: network + genesis_hash + program_id + token_mint
ALTER TABLE agent_costs ADD COLUMN genesis_hash TEXT;
ALTER TABLE agent_costs ADD COLUMN program_id TEXT;

-- Backfill costs from associated economic movements where available
UPDATE agent_costs
SET genesis_hash = (SELECT em.genesis_hash FROM economic_movements em WHERE em.movement_id = agent_costs.movement_id),
    program_id = (SELECT em.program_id FROM economic_movements em WHERE em.movement_id = agent_costs.movement_id)
WHERE movement_id IS NOT NULL AND EXISTS (SELECT 1 FROM economic_movements em WHERE em.movement_id = agent_costs.movement_id);

-- 2. Segregate Agent Reserves by full monetary identity: network + genesis_hash + program_id + token_mint
ALTER TABLE agent_reserves ADD COLUMN genesis_hash TEXT;
ALTER TABLE agent_reserves ADD COLUMN program_id TEXT;

-- Backfill reserves from associated reserve transactions and economic movements where available
UPDATE agent_reserves
SET genesis_hash = (
    SELECT em.genesis_hash
    FROM reserve_transactions rt
    JOIN economic_movements em ON rt.movement_id = em.movement_id
    WHERE rt.reserve_id = agent_reserves.reserve_id
    LIMIT 1
),
program_id = (
    SELECT em.program_id
    FROM reserve_transactions rt
    JOIN economic_movements em ON rt.movement_id = em.movement_id
    WHERE rt.reserve_id = agent_reserves.reserve_id
    LIMIT 1
)
WHERE EXISTS (
    SELECT 1
    FROM reserve_transactions rt
    JOIN economic_movements em ON rt.movement_id = em.movement_id
    WHERE rt.reserve_id = agent_reserves.reserve_id
);

-- 3. Resolve remaining records by verified public cluster network context only
-- Devnet (well-known public cluster)
UPDATE agent_costs SET genesis_hash = 'EtWTRABZaYq6iMfeYKouRu166VU2xqa1wcaWoxPkrZBG', program_id = 'CeA1P1NSuPLUH31KsT4j3pZeBsknQZ3NSC6GUAqcsCLy'
WHERE genesis_hash IS NULL AND network IN ('solana:devnet', 'devnet');

UPDATE agent_reserves SET genesis_hash = 'EtWTRABZaYq6iMfeYKouRu166VU2xqa1wcaWoxPkrZBG', program_id = 'CeA1P1NSuPLUH31KsT4j3pZeBsknQZ3NSC6GUAqcsCLy'
WHERE genesis_hash IS NULL AND network IN ('solana:devnet', 'devnet');

-- Mainnet (well-known public cluster)
UPDATE agent_costs SET genesis_hash = '5eykt4UsFv8P8NJdTREpY1vzqKqZKvdpKuc147dw2N9d', program_id = 'CeA1P1NSuPLUH31KsT4j3pZeBsknQZ3NSC6GUAqcsCLy'
WHERE genesis_hash IS NULL AND network IN ('solana:mainnet-beta', 'mainnet-beta', 'mainnet');

UPDATE agent_reserves SET genesis_hash = '5eykt4UsFv8P8NJdTREpY1vzqKqZKvdpKuc147dw2N9d', program_id = 'CeA1P1NSuPLUH31KsT4j3pZeBsknQZ3NSC6GUAqcsCLy'
WHERE genesis_hash IS NULL AND network IN ('solana:mainnet-beta', 'mainnet-beta', 'mainnet');

-- 4. Localnet without linked movement/evidence, and unknown networks must remain PENDING_RESOLUTION
-- They must never be arbitrarily attributed to a default genesis hash.
UPDATE agent_costs SET genesis_hash = 'PENDING_RESOLUTION', program_id = 'PENDING_RESOLUTION'
WHERE genesis_hash IS NULL;

UPDATE agent_reserves SET genesis_hash = 'PENDING_RESOLUTION', program_id = 'PENDING_RESOLUTION'
WHERE genesis_hash IS NULL;

-- 5. Composite Indexes for fast exact lookups under complete monetary context
CREATE INDEX IF NOT EXISTS idx_costs_monetary_ctx ON agent_costs(agent_account, network, genesis_hash, program_id, token_mint);
CREATE INDEX IF NOT EXISTS idx_reserves_monetary_ctx ON agent_reserves(agent_account, network, genesis_hash, program_id, token_mint);
