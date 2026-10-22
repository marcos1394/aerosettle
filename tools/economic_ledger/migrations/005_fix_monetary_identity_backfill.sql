-- CON-24: Corrective Monetary Identity Backfill Migration
-- Version: 005
-- Name: fix_monetary_identity_backfill

-- 1. Re-align Agent Reserves from authentic underlying transactions and movements (preserve verified identities)
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
      AND (agent_reserves.genesis_hash != em.genesis_hash OR agent_reserves.program_id != em.program_id)
);

-- 2. Re-align Agent Costs from authentic underlying economic movements (preserve verified identities)
UPDATE agent_costs
SET genesis_hash = (SELECT em.genesis_hash FROM economic_movements em WHERE em.movement_id = agent_costs.movement_id),
    program_id = (SELECT em.program_id FROM economic_movements em WHERE em.movement_id = agent_costs.movement_id)
WHERE movement_id IS NOT NULL AND EXISTS (
    SELECT 1 FROM economic_movements em
    WHERE em.movement_id = agent_costs.movement_id
      AND (agent_costs.genesis_hash != em.genesis_hash OR agent_costs.program_id != em.program_id)
);

-- 3. Fix unlinked Devnet records that were mistakenly defaulted to Localnet genesis
UPDATE agent_reserves
SET genesis_hash = 'EtWTRABZaYq6iMfeYKouRu166VU2xqa1wcaWoxPkrZBG',
    program_id = 'CeA1P1NSuPLUH31KsT4j3pZeBsknQZ3NSC6GUAqcsCLy'
WHERE network IN ('solana:devnet', 'devnet')
  AND (genesis_hash IS NULL OR genesis_hash = 'HP9XKTusRPGC78EFDpR9xdEq6simL2vqyDdrMvn6Vacg')
  AND NOT EXISTS (
      SELECT 1 FROM reserve_transactions rt
      JOIN economic_movements em ON rt.movement_id = em.movement_id
      WHERE rt.reserve_id = agent_reserves.reserve_id
  );

UPDATE agent_costs
SET genesis_hash = 'EtWTRABZaYq6iMfeYKouRu166VU2xqa1wcaWoxPkrZBG',
    program_id = 'CeA1P1NSuPLUH31KsT4j3pZeBsknQZ3NSC6GUAqcsCLy'
WHERE network IN ('solana:devnet', 'devnet')
  AND (genesis_hash IS NULL OR genesis_hash = 'HP9XKTusRPGC78EFDpR9xdEq6simL2vqyDdrMvn6Vacg')
  AND (movement_id IS NULL OR NOT EXISTS (SELECT 1 FROM economic_movements em WHERE em.movement_id = agent_costs.movement_id));

-- 4. Fix unlinked Mainnet records that were mistakenly defaulted to Localnet genesis
UPDATE agent_reserves
SET genesis_hash = '5eykt4UsFv8P8NJdTREpY1vzqKqZKvdpKuc147dw2N9d',
    program_id = 'CeA1P1NSuPLUH31KsT4j3pZeBsknQZ3NSC6GUAqcsCLy'
WHERE network IN ('solana:mainnet-beta', 'mainnet-beta', 'mainnet')
  AND (genesis_hash IS NULL OR genesis_hash = 'HP9XKTusRPGC78EFDpR9xdEq6simL2vqyDdrMvn6Vacg')
  AND NOT EXISTS (
      SELECT 1 FROM reserve_transactions rt
      JOIN economic_movements em ON rt.movement_id = em.movement_id
      WHERE rt.reserve_id = agent_reserves.reserve_id
  );

UPDATE agent_costs
SET genesis_hash = '5eykt4UsFv8P8NJdTREpY1vzqKqZKvdpKuc147dw2N9d',
    program_id = 'CeA1P1NSuPLUH31KsT4j3pZeBsknQZ3NSC6GUAqcsCLy'
WHERE network IN ('solana:mainnet-beta', 'mainnet-beta', 'mainnet')
  AND (genesis_hash IS NULL OR genesis_hash = 'HP9XKTusRPGC78EFDpR9xdEq6simL2vqyDdrMvn6Vacg')
  AND (movement_id IS NULL OR NOT EXISTS (SELECT 1 FROM economic_movements em WHERE em.movement_id = agent_costs.movement_id));

-- 5. Correct unlinked Localnet records and unknown network records without verified movements:
-- They must NEVER be arbitrarily attributed to a default genesis hash; keep them as PENDING_RESOLUTION.
UPDATE agent_reserves
SET genesis_hash = 'PENDING_RESOLUTION',
    program_id = 'PENDING_RESOLUTION'
WHERE (network IN ('solana:localnet', 'localnet') OR network NOT IN ('solana:devnet', 'devnet', 'solana:mainnet-beta', 'mainnet-beta', 'mainnet'))
  AND NOT EXISTS (
      SELECT 1 FROM reserve_transactions rt
      JOIN economic_movements em ON rt.movement_id = em.movement_id
      WHERE rt.reserve_id = agent_reserves.reserve_id
  );

UPDATE agent_costs
SET genesis_hash = 'PENDING_RESOLUTION',
    program_id = 'PENDING_RESOLUTION'
WHERE (network IN ('solana:localnet', 'localnet') OR network NOT IN ('solana:devnet', 'devnet', 'solana:mainnet-beta', 'mainnet-beta', 'mainnet'))
  AND (movement_id IS NULL OR NOT EXISTS (SELECT 1 FROM economic_movements em WHERE em.movement_id = agent_costs.movement_id));

-- 6. Ensure indexes are present
CREATE INDEX IF NOT EXISTS idx_costs_monetary_ctx ON agent_costs(agent_account, network, genesis_hash, program_id, token_mint);
CREATE INDEX IF NOT EXISTS idx_reserves_monetary_ctx ON agent_reserves(agent_account, network, genesis_hash, program_id, token_mint);
