import test from 'node:test';
import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { MarketplaceClient, MarketplaceApiError, spendingEvaluationMessage } from '../dist/index.js';

const ACCOUNT = 'DcusvnYAdFFKzNDVzUkUvmgZ9fDhzszeRR5Fj8F5dMbB';
const OWNER = '8rPDpYsLZxNBm8Q8GKSKki8Ag6dodkasedhUT9x3Ec1D';
const PROGRAM = 'CeA1P1NSuPLUH31KsT4j3pZeBsknQZ3NSC6GUAqcsCLy';
const MINT = 'EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v';
const PATH = `/v1/agents/${ACCOUNT}/spending-evaluations`;
const body = {
  proposal_id: 'proposal-00000001', idempotency_key: 'spend-idem-00000001',
  nonce: 'spend-nonce-00000001-unique', agent_account: ACCOUNT,
  agent_id: '11'.repeat(32), requester_pubkey: OWNER, network: 'solana:localnet',
  genesis_hash: 'HP9XKTusRPGC78EFDpR9xdEq6simL2vqyDdrMvn6Vacg',
  program_id: PROGRAM, token_mint: MINT, recipient_pubkey: OWNER,
  amount_base_units_str: '9007199254740993', purpose: 'Fuel', requested_at: 1000,
  expected_policy_id: `bp_${'a'.repeat(32)}`, expected_policy_version: 2,
  expected_policy_hash: 'b'.repeat(64), metadata: {},
};
const decision = {
  decision_id: `sd_${'c'.repeat(32)}`, proposal_id: body.proposal_id, agent_account: ACCOUNT,
  decision: 'REQUIRE_APPROVAL', reason_codes: ['ECONOMIC_SOURCE_UNVERIFIED'],
  reason_details: [{ code: 'ECONOMIC_SOURCE_UNVERIFIED' }],
  policy_id: body.expected_policy_id, policy_version: 2, policy_hash: body.expected_policy_hash,
  network: body.network, genesis_hash: body.genesis_hash, program_id: PROGRAM, token_mint: MINT,
  requested_amount_base_units_str: body.amount_base_units_str,
  daily_window_start_utc: 0, daily_window_end_utc: 86400,
  daily_limit_base_units_str: '18446744073709551615', daily_used_base_units_str: '0',
  daily_committed_base_units_str: '0', daily_remaining_base_units_str: '18446744073709551615',
  minimum_reserve_base_units_str: '0', accounting_reserved_base_units_str: '0',
  available_liquidity_base_units_str: null, accrued_obligations_base_units_str: null,
  economic_evidence_status: 'UNVERIFIED', economic_snapshot_hash: 'd'.repeat(64),
  evaluated_at: 1000, expires_at: 1300, decision_engine_version: 'conatus.spending-decision.v1',
  is_executable: false, historical: false, is_currently_applicable: false,
};
const meta = (read_only) => ({ program_id: PROGRAM, commitment: 'confirmed', chain_now_unix: 1000,
  rpc_context_slots: {}, atomic_snapshot: false, read_only, matching_engine: 'rust-epic-3.1' });

test('signed evaluation challenge binds exact canonical proposal and expected policy', async () => {
  const canonical = (value) => Array.isArray(value) ? `[${value.map(canonical).join(',')}]`
    : value && typeof value === 'object'
      ? `{${Object.keys(value).sort().map((key) => `${JSON.stringify(key)}:${canonical(value[key])}`).join(',')}}`
      : JSON.stringify(value);
  const hash = createHash('sha256').update(canonical(body)).digest('hex');
  const challenge = new TextDecoder().decode(await spendingEvaluationMessage(ACCOUNT, OWNER, 1000, body));
  assert.equal(challenge, `conatus:spending-evaluation:v1:1000:${ACCOUNT}:${OWNER}:POST:${PATH}:${hash}:${body.nonce}:${body.idempotency_key}:${body.expected_policy_id}:2:${body.expected_policy_hash}`);
  assert.notEqual(challenge, new TextDecoder().decode(await spendingEvaluationMessage(ACCOUNT, OWNER, 1000,
    { ...body, purpose: 'Tampered' })));
});

test('SDK preserves exact amounts and parses non executable decision', async () => {
  const calls = [];
  const client = new MarketplaceClient({ baseUrl: 'http://127.0.0.1:8787', fetchImpl: async (url, options) => {
    calls.push({ url: String(url), method: options.method, headers: options.headers, body: options.body });
    const data = options.method === 'POST' ? decision : String(url).endsWith('/spending-evaluations') ? [decision] : decision;
    return new Response(JSON.stringify({ data, meta: meta(options.method === 'GET') }),
      { status: options.method === 'POST' ? 201 : 200 });
  } });
  const options = { authHeaders: { 'X-Signer-Pubkey': OWNER, 'X-Timestamp': '1000', 'X-Signature': 'signed' } };
  const created = await client.evaluateAgentSpending(ACCOUNT, body, options);
  assert.equal(created.data.requested_amount_base_units_str, '9007199254740993');
  assert.equal(created.data.is_executable, false);
  assert.equal((await client.listAgentSpendingEvaluations(ACCOUNT, options)).data.length, 1);
  assert.equal((await client.getAgentSpendingEvaluation(ACCOUNT, decision.decision_id, options)).data.decision_id, decision.decision_id);
  assert.deepEqual(calls.map((call) => call.method), ['POST', 'GET', 'GET']);
  assert.equal(JSON.parse(calls[0].body).amount_base_units_str, body.amount_base_units_str);
  assert.equal(calls[0].headers['X-Signature'], 'signed');
});

test('SDK rejects unsigned requests, invalid amounts, executable responses and 409', async () => {
  const client = new MarketplaceClient({ baseUrl: 'http://127.0.0.1:8787', fetchImpl: async () =>
    new Response(JSON.stringify({ error: { code: 'IDEMPOTENCY_CONFLICT', message: 'conflict' } }), { status: 409 }) });
  await assert.rejects(client.evaluateAgentSpending(ACCOUNT, body, { authHeaders: {} }), /Signed policy mutation headers/);
  await assert.rejects(client.evaluateAgentSpending(ACCOUNT, { ...body, amount_base_units_str: '18446744073709551616' },
    { authHeaders: { 'X-Signer-Pubkey': OWNER, 'X-Timestamp': '1000', 'X-Signature': 'signed' } }), /amount_base_units_str/);
  await assert.rejects(client.evaluateAgentSpending(ACCOUNT, body,
    { authHeaders: { 'X-Signer-Pubkey': OWNER, 'X-Timestamp': '1000', 'X-Signature': 'signed' } }),
  (error) => error instanceof MarketplaceApiError && error.status === 409);
  const unsafe = new MarketplaceClient({ baseUrl: 'http://127.0.0.1:8787', fetchImpl: async () =>
    new Response(JSON.stringify({ data: { ...decision, is_executable: true }, meta: meta(false) }), { status: 201 }) });
  await assert.rejects(unsafe.evaluateAgentSpending(ACCOUNT, body,
    { authHeaders: { 'X-Signer-Pubkey': OWNER, 'X-Timestamp': '1000', 'X-Signature': 'signed' } }), /cannot be executable/);
});
