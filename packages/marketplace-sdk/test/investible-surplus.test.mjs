import test from 'node:test';
import assert from 'node:assert/strict';
import { MarketplaceClient } from '../dist/index.js';

const AGENT = 'DcusvnYAdFFKzNDVzUkUvmgZ9fDhzszeRR5Fj8F5dMbB';
const OWNER = '8rPDpYsLZxNBm8Q8GKSKki8Ag6dodkasedhUT9x3Ec1D';
const GENESIS = 'HP9XKTusRPGC78EFDpR9xdEq6simL2vqyDdrMvn6Vacg';
const PROGRAM = 'CeA1P1NSuPLUH31KsT4j3pZeBsknQZ3NSC6GUAqcsCLy';
const MINT = 'EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v';
const filters = { network: 'solana:localnet', genesis_hash: GENESIS, program_id: PROGRAM,
  token_mint: MINT, scenario: 'STRESS', horizon_days: 90 };
const assessment = {
  assessment_id: 'is_' + '1'.repeat(32), assessment_version: 1,
  methodology_version: 'conatus:investible-surplus:v1',
  agent_account: AGENT, agent_id: '11'.repeat(32), owner_pubkey: OWNER,
  ...filters, continuity_horizon_days: 90, assessed_at: 1000, data_as_of: 1000,
  window_start: 900, window_end: 1000,
  scenario_assumptions: { opex_multiplier_bps: 15000, liquidity_haircut_bps: 1500,
    additional_liability_buffer_base_units_str: '0', continuity_horizon_days: 90,
    opex_window_estimation_assumed: false },
  treasury_available_base_units_str: '9007199254740993', restricted_capital_base_units_str: '0',
  accounting_reserved_base_units_str: '0', accrued_obligations_base_units_str: '0',
  unfunded_policy_reserve_base_units_str: '0', pending_commitments_base_units_str: '0',
  operational_buffer_base_units_str: '0', liquidity_haircut_base_units_str: '1',
  estimated_investible_surplus_base_units_str: '9007199254740992',
  verified_investible_surplus_base_units_str: null,
  calculation_status: 'ESTIMATED', provenance: 'HISTORICAL_UNVERIFIED',
  exclusion_reasons: ['productive_ownership_and_coverage_not_verified'], evidence_references: [],
  solvency_context: null,
  deductions: [{ component: 'ACCOUNTING_RESERVE', amount_base_units_str: '0', source: 'agent_reserves',
    reference_ids: [], already_reflected_in_treasury: true, applied_to_surplus: false, reason: 'already reflected' }],
  policy_id: 'bp_1', policy_version: 1, policy_hash: 'a'.repeat(64),
  economic_snapshot_hash: 'b'.repeat(64), assessment_hash: 'c'.repeat(64), is_executable: false,
};
const meta = { program_id: PROGRAM, commitment: 'confirmed', chain_now_unix: 1000,
  rpc_context_slots: {}, atomic_snapshot: false, read_only: true, matching_engine: 'rust-epic-3.1' };

test('SDK sends exact monetary context and retains u64 precision', async () => {
  let url = ''; let headers = {};
  const client = new MarketplaceClient({ baseUrl: 'http://127.0.0.1:8787', fetchImpl: async (input, init) => {
    url = String(input); headers = init.headers;
    return new Response(JSON.stringify({ data: assessment, meta }));
  } });
  const result = await client.getAgentInvestibleSurplus(AGENT, filters,
    { authHeaders: { 'X-Signature': 'signed' } });
  assert.equal(result.data.treasury_available_base_units_str, '9007199254740993');
  assert.equal(result.data.verified_investible_surplus_base_units_str, null);
  assert.match(url, /scenario=STRESS/);
  assert.match(url, /horizon_days=90/);
  assert.match(url, /genesis_hash=/);
  assert.equal(headers['X-Signature'], 'signed');
});

test('SDK rejects false confirmed capital and executable assessments', async () => {
  for (const changed of [
    { verified_investible_surplus_base_units_str: '123' },
    { is_executable: true },
    { treasury_available_base_units_str: 1000 },
    { estimated_investible_surplus_base_units_str: '18446744073709551616' },
  ]) {
    const client = new MarketplaceClient({ baseUrl: 'http://127.0.0.1:8787', fetchImpl: async () =>
      new Response(JSON.stringify({ data: { ...assessment, ...changed }, meta })) });
    await assert.rejects(client.getAgentInvestibleSurplus(AGENT, filters));
  }
});
