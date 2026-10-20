import test from 'node:test';
import assert from 'node:assert/strict';
import { MarketplaceClient } from '../dist/index.js';

const AGENT = 'DcusvnYAdFFKzNDVzUkUvmgZ9fDhzszeRR5Fj8F5dMbB';
const OWNER = '8rPDpYsLZxNBm8Q8GKSKki8Ag6dodkasedhUT9x3Ec1D';
const MINT = 'EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v';

test('SDK: listEconomicMovements sends filters and auth headers', async () => {
  let capturedUrl = '';
  let capturedHeaders = {};

  const client = new MarketplaceClient({
    baseUrl: 'http://127.0.0.1:8787',
    fetchImpl: async (url, init) => {
      capturedUrl = url.toString();
      capturedHeaders = init.headers || {};
      return new Response(
        JSON.stringify({
          data: [
            {
              movement_id: 'mov-123',
              idempotency_key: 'idemp-123',
              agent_id: '11'.repeat(32),
              agent_account: AGENT,
              owner_pubkey: OWNER,
              network: 'solana:localnet',
              genesis_hash: 'HP9XKTusRPGC78EFDpR9xdEq6simL2vqyDdrMvn6Vacg',
              program_id: 'CeA1P1NSuPLUH31KsT4j3pZeBsknQZ3NSC6GUAqcsCLy',
              token_mint: MINT,
              amount_base_units: 5000000,
              amount_str: '5000000',
              nature: 'INCOME',
              status: 'RECONCILED',
              provenance_source: 'ONCHAIN_VERIFIED',
              registered_at: 1000,
              observed_at: 1000,
              metadata: {},
            },
          ],
          count: 1,
          total_count: 1,
          page: { limit: 50, has_more: false, next_cursor: null },
          meta: {
            program_id: 'CeA1P1NSuPLUH31KsT4j3pZeBsknQZ3NSC6GUAqcsCLy',
            commitment: 'confirmed',
            chain_now_unix: 1000,
            atomic_snapshot: false,
            read_only: true,
            matching_engine: 'rust-epic-3.1',
            rpc_context_slots: {},
          },
        }),
        { status: 200, headers: { 'Content-Type': 'application/json' } }
      );
    },
  });

  const res = await client.listEconomicMovements(
    AGENT,
    { nature: 'INCOME', status: 'RECONCILED' },
    { ownerPubkey: OWNER }
  );

  assert.equal(res.data.length, 1);
  assert.equal(res.data[0].movement_id, 'mov-123');
  assert.equal(capturedHeaders['X-Owner-Pubkey'], OWNER);
  assert.match(capturedUrl, /\/v1\/agents\/DcusvnYAdFFKzNDVzUkUvmgZ9fDhzszeRR5Fj8F5dMbB\/economic-movements/);
  assert.match(capturedUrl, /nature=INCOME/);
  assert.match(capturedUrl, /status=RECONCILED/);
});

test('SDK: getAgentBalances returns strictly partitioned balances', async () => {
  const client = new MarketplaceClient({
    baseUrl: 'http://127.0.0.1:8787',
    fetchImpl: async () => {
      return new Response(
        JSON.stringify({
          data: [
            {
              agent_account: AGENT,
              network: 'solana:localnet',
              token_mint: MINT,
              reconciled_balance: 7000000,
              provisional_balance: 1500000,
              reserved_balance: 500000,
              reconciled_balance_str: '7000000',
              provisional_balance_str: '1500000',
              reserved_balance_str: '500000',
              total_effective_balance: 8500000,
              total_effective_balance_str: '8500000',
              movement_count: 3,
            },
          ],
          meta: {
            program_id: 'CeA1P1NSuPLUH31KsT4j3pZeBsknQZ3NSC6GUAqcsCLy',
            commitment: 'confirmed',
            chain_now_unix: 1000,
            atomic_snapshot: false,
            read_only: true,
            matching_engine: 'rust-epic-3.1',
            rpc_context_slots: {},
          },
        }),
        { status: 200, headers: { 'Content-Type': 'application/json' } }
      );
    },
  });

  const res = await client.getAgentBalances(AGENT, { mint: MINT }, { ownerPubkey: OWNER });
  assert.equal(res.data.length, 1);
  assert.equal(res.data[0].reconciled_balance, 7000000);
  assert.equal(res.data[0].total_effective_balance, 8500000);
});

test('SDK: recordEconomicMovement posts JSON body and auth headers', async () => {
  let capturedBody = '';

  const client = new MarketplaceClient({
    baseUrl: 'http://127.0.0.1:8787',
    fetchImpl: async (url, init) => {
      capturedBody = init.body;
      return new Response(
        JSON.stringify({
          data: {
            movement_id: 'mov-new-1',
            idempotency_key: 'idemp-new-1',
            agent_id: '11'.repeat(32),
            agent_account: AGENT,
            owner_pubkey: OWNER,
            network: 'solana:localnet',
            genesis_hash: 'HP9XKTusRPGC78EFDpR9xdEq6simL2vqyDdrMvn6Vacg',
            program_id: 'CeA1P1NSuPLUH31KsT4j3pZeBsknQZ3NSC6GUAqcsCLy',
            token_mint: MINT,
            amount_base_units: 1200000,
            amount_str: '1200000',
            nature: 'EXPENSE',
            status: 'RECONCILED',
            provenance_source: 'MANUAL_ENTRY',
            registered_at: 1000,
            observed_at: 1000,
            metadata: {},
          },
          meta: {
            program_id: 'CeA1P1NSuPLUH31KsT4j3pZeBsknQZ3NSC6GUAqcsCLy',
            commitment: 'confirmed',
            chain_now_unix: 1000,
            atomic_snapshot: false,
            read_only: true,
            matching_engine: 'rust-epic-3.1',
            rpc_context_slots: {},
          },
        }),
        { status: 201, headers: { 'Content-Type': 'application/json' } }
      );
    },
  });

  const res = await client.recordEconomicMovement(
    {
      idempotency_key: 'idemp-new-1',
      agent_account: AGENT,
      token_mint: MINT,
      amount_base_units: 1200000,
      nature: 'EXPENSE',
    },
    { ownerPubkey: OWNER }
  );

  assert.equal(res.data.movement_id, 'mov-new-1');
  const parsedBody = JSON.parse(capturedBody);
  assert.equal(parsedBody.idempotency_key, 'idemp-new-1');
  assert.equal(parsedBody.amount_base_units, 1200000);
});
