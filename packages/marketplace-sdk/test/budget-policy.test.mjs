import test from 'node:test';
import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import {
  MarketplaceClient, MarketplaceApiError, budgetPolicyMutationMessage,
} from '../dist/index.js';

const ACCOUNT = 'DcusvnYAdFFKzNDVzUkUvmgZ9fDhzszeRR5Fj8F5dMbB';
const OWNER = '8rPDpYsLZxNBm8Q8GKSKki8Ag6dodkasedhUT9x3Ec1D';
const PROGRAM = 'CeA1P1NSuPLUH31KsT4j3pZeBsknQZ3NSC6GUAqcsCLy';
const MINT = 'EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v';
const PATH = `/v1/agents/${ACCOUNT}/budget-policy`;
const headers = { 'X-Signer-Pubkey': OWNER, 'X-Timestamp': '1000', 'X-Signature': 'signed' };
const body = {
  expected_version: 0, idempotency_key: 'policy-idempotency-1',
  nonce: 'policy-nonce-unique-1', network: 'solana:localnet',
  genesis_hash: 'HP9XKTusRPGC78EFDpR9xdEq6simL2vqyDdrMvn6Vacg',
  program_id: PROGRAM, valid_from: 1000, expires_at: 2000,
  asset_rules: [{
    token_mint: MINT, max_per_operation_base_units_str: '9007199254740993',
    max_daily_spend_base_units_str: '18446744073709551615',
    minimum_reserve_base_units_str: '0', enabled: true,
  }],
  allowed_recipients: [],
};
const policy = {
  policy_id: 'bp_test', agent_account: ACCOUNT, agent_id: '11'.repeat(32),
  owner_pubkey: OWNER, network: body.network, genesis_hash: body.genesis_hash,
  program_id: PROGRAM, version: 1, status: 'DRAFT', effective_status: 'DRAFT',
  asset_rules: body.asset_rules, allowed_recipients: [],
  valid_from: 1000, expires_at: 2000, created_at: 1000, created_by: OWNER,
  revision_reason: null, policy_hash: 'a'.repeat(64), idempotency_key: body.idempotency_key,
  action: 'CREATE', is_currently_valid: false,
  reserve_comparison: [{
    token_mint: MINT, policy_minimum_reserve_base_units_str: '0',
    accounting_reserved_base_units_str: '0', reserve_shortfall_base_units_str: '0',
    ledger_available_balance_str: null, ledger_accrued_obligations_base_units_str: null,
    policy_target_is_not_locked_funds: true,
  }],
};
const meta = (read_only) => ({
  program_id: PROGRAM, commitment: 'confirmed', chain_now_unix: 1000,
  rpc_context_slots: {}, atomic_snapshot: false, read_only,
  matching_engine: 'rust-epic-3.1',
});

test('policy mutation challenge binds canonical body, method, route and expected version', async () => {
  const timestamp = 1000;
  const message = new TextDecoder().decode(await budgetPolicyMutationMessage(
    'POST', ACCOUNT, PATH, OWNER, timestamp, body));
  const canonical = (value) => Array.isArray(value) ? `[${value.map(canonical).join(',')}]`
    : value && typeof value === 'object'
      ? `{${Object.keys(value).sort().map((key) => `${JSON.stringify(key)}:${canonical(value[key])}`).join(',')}}`
      : JSON.stringify(value);
  const hash = createHash('sha256').update(canonical(body)).digest('hex');
  assert.equal(message, `conatus:budget-policy-mutation:v1:1000:${ACCOUNT}:${OWNER}:POST:${PATH}:${hash}:${body.nonce}:${body.idempotency_key}:0`);
  assert.notEqual(message, new TextDecoder().decode(await budgetPolicyMutationMessage(
    'PUT', ACCOUNT, PATH, OWNER, timestamp, body)));
});

test('typed policy API sends signed create/update/action and preserves exact u64 strings', async () => {
  const calls = [];
  const client = new MarketplaceClient({
    baseUrl: 'http://127.0.0.1:8787',
    fetchImpl: async (url, options) => {
      calls.push({ url: String(url), method: options.method, headers: options.headers, body: options.body });
      return new Response(JSON.stringify({ data: policy, meta: meta(options.method === 'GET') }),
        { status: options.method === 'POST' ? 201 : 200 });
    },
  });
  const options = { authHeaders: headers };
  const created = await client.createAgentBudgetPolicy(ACCOUNT, body, options);
  assert.equal(created.data.asset_rules[0].max_per_operation_base_units_str, '9007199254740993');
  assert.equal(created.meta.read_only, false);
  await client.updateAgentBudgetPolicy(ACCOUNT, { ...body, expected_version: 1 }, options);
  await client.pauseAgentBudgetPolicy(ACCOUNT, { expected_version: 1, idempotency_key: 'pause-key', nonce: 'pause-nonce-unique' }, options);
  const current = await client.getAgentBudgetPolicy(ACCOUNT, options);
  assert.equal(current.data.policy_hash, policy.policy_hash);
  assert.deepEqual(calls.map((call) => call.method), ['POST', 'PUT', 'POST', 'GET']);
  assert.ok(calls.every((call) => call.headers['X-Signature'] === 'signed'));
  assert.match(calls[2].url, /\/budget-policy\/pause$/);
  assert.equal(JSON.parse(calls[0].body).asset_rules[0].max_daily_spend_base_units_str, '18446744073709551615');
});

test('unsigned mutations and 409 version conflicts fail closed', async () => {
  const client = new MarketplaceClient({
    baseUrl: 'http://127.0.0.1:8787',
    fetchImpl: async () => new Response(JSON.stringify({
      error: { code: 'VERSION_CONFLICT', message: 'Current policy version has changed' },
    }), { status: 409 }),
  });
  await assert.rejects(client.createAgentBudgetPolicy(ACCOUNT, body, { authHeaders: {} }), /Signed policy mutation headers/);
  await assert.rejects(client.createAgentBudgetPolicy(ACCOUNT, body, { authHeaders: headers }),
    (error) => error instanceof MarketplaceApiError && error.status === 409 && error.code === 'VERSION_CONFLICT');
});
