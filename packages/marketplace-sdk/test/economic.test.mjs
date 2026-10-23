import test from 'node:test';
import assert from 'node:assert/strict';
import { MarketplaceClient } from '../dist/index.js';

const AGENT = 'DcusvnYAdFFKzNDVzUkUvmgZ9fDhzszeRR5Fj8F5dMbB';
const OWNER = '8rPDpYsLZxNBm8Q8GKSKki8Ag6dodkasedhUT9x3Ec1D';
const MINT = 'EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v';

test('SDK solvency preserves exact base-unit strings and signed headers', async () => {
  let requestedUrl = '';
  let requestedHeaders = {};
  const assessment = {
    assessment_id: 'a1', agent_account: AGENT, network: 'solana:localnet',
    genesis_hash: 'HP9XKTusRPGC78EFDpR9xdEq6simL2vqyDdrMvn6Vacg',
    program_id: 'CeA1P1NSuPLUH31KsT4j3pZeBsknQZ3NSC6GUAqcsCLy', token_mint: MINT,
    window_start: 100, window_end: 200, calculated_at: 200,
    methodology_version: 'conatus-solvency-v1', threshold_config_version: 'thresholds-v1',
    conatus_ratio: '1.50000000', operating_margin: '0.33333333',
    operating_surplus_base_units_str: '6000000000000000000',
    available_liquidity_base_units_str: '6000000000000000000',
    total_reserved_base_units_str: '0', accrued_liabilities_base_units_str: '0',
    reserve_target_base_units_str: '0', reserve_gap_base_units_str: '0',
    eligible_liquid_capital_base_units_str: '6000000000000000000', runway_days: '15.00000000',
    sustainability_class: 'STABLE', calculation_status: 'VALID', data_coverage_status: 'COMPLETE',
    input_revenue_count: 1, input_expense_count: 1,
    verified_revenue_base_units_str: '18000000000000000000',
    verified_opex_base_units_str: '12000000000000000000',
    exclusion_reasons: [], evidence_references: [{ kind: 'movement', id: 'm1', evidence_hash: 'h1' }],
    input_hash: 'hash', provenance: 'VERIFIED_LEDGER',
    net_worth_verified_base_units_str: null, provisional_book_value_base_units_str: null,
  };
  const client = new MarketplaceClient({
    baseUrl: 'http://127.0.0.1:8787',
    fetchImpl: async (url, init) => {
      requestedUrl = String(url); requestedHeaders = init.headers;
      return new Response(JSON.stringify({ data: [assessment], meta: {
        program_id: 'CeA1P1NSuPLUH31KsT4j3pZeBsknQZ3NSC6GUAqcsCLy', commitment: 'confirmed',
        chain_now_unix: 200, atomic_snapshot: false, read_only: true,
        matching_engine: 'rust-epic-3.1', rpc_context_slots: {},
      } }), { status: 200 });
    },
  });
  const response = await client.getAgentSolvency(AGENT, { window: 30, mint: MINT },
    { authHeaders: { 'X-Signature': 'signed' } });
  assert.equal(response.data[0].verified_revenue_base_units_str, '18000000000000000000');
  assert.equal(response.data[0].conatus_ratio, '1.50000000');
  assert.match(requestedUrl, /window=30/);
  assert.equal(requestedHeaders['X-Signature'], 'signed');
});

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
              genesis_hash: 'HP9XKTusRPGC78EFDpR9xdEq6simL2vqyDdrMvn6Vacg',
              program_id: 'CeA1P1NSuPLUH31KsT4j3pZeBsknQZ3NSC6GUAqcsCLy',
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

test('SDK: listAgentCosts, listAgentReserves, and getAgentEconomicSummary', async () => {
  let capturedCostUrl = '';
  let capturedReserveUrl = '';
  let capturedSummaryUrl = '';
  const signedHeaders = [];

  const client = new MarketplaceClient({
    baseUrl: 'http://127.0.0.1:8787',
    fetchImpl: async (url, init) => {
      const u = url.toString();
      signedHeaders.push(init.headers);
      if (u.includes('/costs')) {
        capturedCostUrl = u;
        return new Response(
          JSON.stringify({
            data: [
              {
                cost_id: 'cost-1',
                idempotency_key: 'idemp-c1',
                agent_id: '11'.repeat(32),
                agent_account: AGENT,
                owner_pubkey: OWNER,
                category: 'ENERGY_FUEL',
                cost_nature: 'REALIZED',
                economic_period: '2026-10',
                network: 'solana:localnet',
                genesis_hash: 'HP9XKTusRPGC78EFDpR9xdEq6simL2vqyDdrMvn6Vacg',
                program_id: 'CeA1P1NSuPLUH31KsT4j3pZeBsknQZ3NSC6GUAqcsCLy',
                token_mint: MINT,
                amount_base_units: 350000,
                amount_str: '350000',
                status: 'PROVISIONAL',
                provenance_source: 'MANUAL_ENTRY',
                created_at: 1000,
                incurred_at: 1000,
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
      }
      if (u.includes('/reserves')) {
        capturedReserveUrl = u;
        return new Response(
          JSON.stringify({
            data: [
              {
                reserve_id: 'res-1',
                idempotency_key: 'idemp-r1',
                agent_id: '11'.repeat(32),
                agent_account: AGENT,
                owner_pubkey: OWNER,
                reserve_type: 'MAINTENANCE',
                network: 'solana:localnet',
                genesis_hash: 'HP9XKTusRPGC78EFDpR9xdEq6simL2vqyDdrMvn6Vacg',
                program_id: 'CeA1P1NSuPLUH31KsT4j3pZeBsknQZ3NSC6GUAqcsCLy',
                token_mint: MINT,
                target_amount_base_units: 5000000,
                target_amount_str: '5000000',
                current_reserved_base_units: 3000000,
                current_reserved_str: '3000000',
                status: 'ACTIVE',
                created_at: 1000,
                updated_at: 1000,
                metadata: {},
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
      }
      if (u.includes('/economic-summary')) {
        capturedSummaryUrl = u;
        return new Response(
          JSON.stringify({
            data: [
              {
                agent_account: AGENT,
                network: 'solana:localnet',
                genesis_hash: 'HP9XKTusRPGC78EFDpR9xdEq6simL2vqyDdrMvn6Vacg',
                program_id: 'CeA1P1NSuPLUH31KsT4j3pZeBsknQZ3NSC6GUAqcsCLy',
                token_mint: MINT,
                total_income_reconciled: 9007199254740992,
                total_income_provisional: 0,
                total_expenses_realized: 350000,
                total_obligations_accrued: 200000,
                total_estimated_costs: 500000,
                total_capital_reserved: 3000000,
                available_balance: 6650000,
                total_effective_balance: 9650000,
                total_income_reconciled_str: '9007199254740993',
                total_income_provisional_str: '0',
                total_expenses_realized_str: '350000',
                total_obligations_accrued_str: '200000',
                total_estimated_costs_str: '500000',
                total_capital_reserved_str: '3000000',
                available_balance_str: '6650000',
                total_effective_balance_str: '9650000',
                costs_by_category: { ENERGY_FUEL: 350000 },
                reserves_by_type: { MAINTENANCE: 3000000 },
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
      }
      throw new Error(`Unexpected url: ${u}`);
    },
  });

  const authHeaders = { 'X-Signer-Pubkey': OWNER, 'X-Timestamp': '1000', 'X-Signature': 'signed' };
  const costs = await client.listAgentCosts(AGENT, { category: 'ENERGY_FUEL' }, { authHeaders });
  assert.equal(costs.data.length, 1);
  assert.equal(costs.data[0].category, 'ENERGY_FUEL');
  assert.match(capturedCostUrl, /category=ENERGY_FUEL/);

  const reserves = await client.listAgentReserves(AGENT, { reserve_type: 'MAINTENANCE' }, { authHeaders });
  assert.equal(reserves.data.length, 1);
  assert.equal(reserves.data[0].current_reserved_base_units, 3000000);
  assert.match(capturedReserveUrl, /reserve_type=MAINTENANCE/);

  const summary = await client.getAgentEconomicSummary(AGENT, { mint: MINT }, { authHeaders });
  assert.equal(summary.data.length, 1);
  assert.equal(summary.data[0].available_balance, 6650000);
  assert.equal(summary.data[0].total_capital_reserved, 3000000);
  assert.equal(summary.data[0].total_income_reconciled, null);
  assert.equal(summary.data[0].total_income_reconciled_str, '9007199254740993');
  assert.deepEqual(signedHeaders.map((headers) => headers['X-Signature']), ['signed', 'signed', 'signed']);
  assert.match(capturedSummaryUrl, /mint=EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v/);
});

test('SDK rejects mismatched exact monetary fields and missing context', async () => {
  const base = {
    agent_account: AGENT, network: 'solana:localnet',
    genesis_hash: 'HP9XKTusRPGC78EFDpR9xdEq6simL2vqyDdrMvn6Vacg',
    program_id: 'CeA1P1NSuPLUH31KsT4j3pZeBsknQZ3NSC6GUAqcsCLy', token_mint: MINT,
    reconciled_balance: 5, reconciled_balance_str: '6',
    provisional_balance: 0, provisional_balance_str: '0',
    reserved_balance: 0, reserved_balance_str: '0',
    total_effective_balance: 5, total_effective_balance_str: '5', movement_count: 1,
  };
  const meta = {
    program_id: base.program_id, commitment: 'confirmed', chain_now_unix: 1000,
    atomic_snapshot: false, read_only: true, matching_engine: 'rust-epic-3.1', rpc_context_slots: {},
  };
  const client = (row) => new MarketplaceClient({
    baseUrl: 'http://127.0.0.1:8787',
    fetchImpl: async () => new Response(JSON.stringify({ data: [row], meta }), { status: 200 }),
  });
  await assert.rejects(client(base).getAgentBalances(AGENT), /Mismatched reconciled_balance/);
  await assert.rejects(client({ ...base, reconciled_balance_str: '5', genesis_hash: undefined })
    .getAgentBalances(AGENT), /Invalid genesis_hash/);
});
