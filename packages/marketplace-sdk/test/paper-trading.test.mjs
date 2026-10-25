import test from 'node:test';
import assert from 'node:assert/strict';
import { execFileSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import { MarketplaceClient, paperSimulationMessage } from '../dist/index.js';

const AGENT = 'DcusvnYAdFFKzNDVzUkUvmgZ9fDhzszeRR5Fj8F5dMbB';
const OWNER = '8rPDpYsLZxNBm8Q8GKSKki8Ag6dodkasedhUT9x3Ec1D';
const MINT = 'EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v';
const PROGRAM = 'CeA1P1NSuPLUH31KsT4j3pZeBsknQZ3NSC6GUAqcsCLy';
const request = { agent_account: AGENT, agent_id: '11'.repeat(32), owner_pubkey: OWNER,
  network: 'solana:localnet', genesis_hash: AGENT, program_id: PROGRAM,
  treasury_token_mint: MINT, trading_quote_currency: MINT, paper_budget_base_units_str: '9007199254740993',
  funding_source: 'MANUAL_PAPER_ALLOCATION', scenario_id: 'paper_example', scenario_kind: 'FINANCIAL_SPOT',
  scenario: 'STRESS', instrument_id: 'fixture:spot:compute-credit:alpha', side: 'BUY',
  quantity_base_units_str: '9', require_full_fill: false, holding_period_days: 30,
  productive_alternatives: [], simulation_timestamp: 1000, nonce: 'paper-nonce-00000001',
  idempotency_key: 'paper-idem-00000001' };
const result = { simulation_id: 'paper_sim_' + '1'.repeat(32), scenario_id: 'paper_example', status: 'SIMULATED',
  fill_status: 'FILLED_SIMULATED', agent_account: AGENT, agent_id: request.agent_id, owner_pubkey: OWNER,
  network: request.network, genesis_hash: request.genesis_hash, program_id: PROGRAM,
  treasury_token_mint: MINT, trading_quote_currency: MINT, paper_budget_base_units_str: request.paper_budget_base_units_str,
  remaining_paper_budget_base_units_str: '9007199254740079', entry_total_base_units_str: '914',
  filled_quantity_base_units_str: '9', hypothetical_loss_base_units_str: '200',
  entry_fee_base_units_str: '9', entry_spread_base_units_str: '0', entry_slippage_base_units_str: '5',
  hypothetical_net_result_base_units_str: '-200', productive_alternatives: [],
  market_snapshot: { price_numerator_str: '100', price_denominator_str: '1',
    available_quantity_base_units_str: '1000' },
  execution_cost_snapshot: { fee_bps: 100, spread_bps: 0, slippage_bps: 50 },
  funding_source: 'MANUAL_PAPER_ALLOCATION', scenario: 'STRESS', scenario_kind: 'FINANCIAL_SPOT',
  input_snapshot_hash: 'a'.repeat(64), market_snapshot_hash: 'b'.repeat(64), result_hash: 'c'.repeat(64),
  provider_id: 'conatus:paper-fixtures:v1', provider_mode: 'OFFLINE_FIXTURE', data_provenance: 'FIXTURE',
  simulation_timestamp: 1000, methodology_version: 'conatus:paper-simulation:v1',
  is_paper: true, is_executable: false, real_capital_authorized: false };
const meta = { program_id: PROGRAM, commitment: 'confirmed', chain_now_unix: 1000,
  rpc_context_slots: {}, atomic_snapshot: false, read_only: false, matching_engine: 'rust-epic-3.1' };

test('paper signature binds budget, scenario, body and route', async () => {
  const one = await paperSimulationMessage(AGENT, OWNER, 1000, request);
  const script = `import json,sys\nfrom tools.paper_trading.store import paper_simulation_message\nb=json.loads(sys.stdin.read())\nprint(paper_simulation_message(1000,b['agent_account'],b['owner_pubkey'],'/v1/agents/${AGENT}/paper-simulations',b).decode())`;
  const expected = execFileSync('python3', ['-c', script], {
    cwd: fileURLToPath(new URL('../../../', import.meta.url)), input: JSON.stringify(request), encoding: 'utf8',
  }).trim();
  assert.equal(new TextDecoder().decode(one), expected);
  const changed = await paperSimulationMessage(AGENT, OWNER, 1000,
    { ...request, paper_budget_base_units_str: '9007199254740994' });
  assert.notDeepEqual(one, changed);
  assert.match(new TextDecoder().decode(one), /^conatus:paper-simulation:v1:1000:/);
});

test('SDK preserves exact paper amounts and rejects executable or live-labelled results', async () => {
  let path = ''; let headers = {};
  const client = new MarketplaceClient({ baseUrl: 'http://127.0.0.1:8787', fetchImpl: async (input, init) => {
    path = String(input); headers = init.headers;
    return new Response(JSON.stringify({ data: result, meta }));
  } });
  const response = await client.runAgentPaperSimulation(AGENT, request,
    { authHeaders: { 'X-Signer-Pubkey': OWNER, 'X-Timestamp': '1000', 'X-Signature': 'signed' } });
  assert.equal(response.data.paper_budget_base_units_str, '9007199254740993');
  assert.match(path, /paper-simulations/);
  assert.equal(headers['X-Signature'], 'signed');
  for (const change of [{ is_paper: false }, { is_executable: true },
    { real_capital_authorized: true }, { provider_mode: 'LIVE_BROKER' },
    { data_provenance: 'LIVE_RPC' }, { remaining_paper_budget_base_units_str: 100 }]) {
    const rejected = new MarketplaceClient({ baseUrl: 'http://127.0.0.1:8787', fetchImpl: async () =>
      new Response(JSON.stringify({ data: { ...result, ...change }, meta })) });
    await assert.rejects(rejected.runAgentPaperSimulation(AGENT, request,
      { authHeaders: { 'X-Signer-Pubkey': OWNER, 'X-Timestamp': '1000', 'X-Signature': 'signed' } }));
  }
});
