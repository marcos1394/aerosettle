import test from 'node:test';
import assert from 'node:assert/strict';
import { execFileSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import { MarketplaceClient, spendingApprovalMessage } from '../dist/index.js';

const ACCOUNT = 'DcusvnYAdFFKzNDVzUkUvmgZ9fDhzszeRR5Fj8F5dMbB';
const OWNER = '8rPDpYsLZxNBm8Q8GKSKki8Ag6dodkasedhUT9x3Ec1D';
const PROGRAM = 'CeA1P1NSuPLUH31KsT4j3pZeBsknQZ3NSC6GUAqcsCLy';
const MINT = 'EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v';
const ROOT = `/v1/agents/${ACCOUNT}/spending-approvals`;
const APPROVAL_ID = `sa_${'a'.repeat(32)}`;
const body = {
  agent_account: ACCOUNT, agent_id: '11'.repeat(32), owner_pubkey: OWNER,
  proposal_id: 'proposal-00000001', proposal_hash: 'b'.repeat(64),
  decision_id: `sd_${'c'.repeat(32)}`, decision_hash: 'd'.repeat(64),
  policy_id: `bp_${'e'.repeat(32)}`, policy_version: 2, policy_hash: 'f'.repeat(64),
  network: 'solana:localnet', genesis_hash: 'HP9XKTusRPGC78EFDpR9xdEq6simL2vqyDdrMvn6Vacg',
  program_id: PROGRAM, token_mint: MINT, recipient_pubkey: OWNER,
  amount_base_units_str: '9007199254740993', economic_snapshot_hash: '1'.repeat(64),
  action: 'OPEN', issued_at: 1000, expires_at: 1100,
  nonce: 'approval-nonce-00000001', idempotency_key: 'approval-idem-00000001', reason: '',
};
const approval = {
  approval_id: APPROVAL_ID, proposal_id: body.proposal_id, decision_id: body.decision_id,
  agent_account: ACCOUNT, agent_id: body.agent_id, owner_pubkey: OWNER,
  network: body.network, genesis_hash: body.genesis_hash, program_id: PROGRAM,
  token_mint: MINT, recipient_pubkey: OWNER, amount_base_units_str: body.amount_base_units_str,
  proposal_hash: body.proposal_hash, decision_hash: body.decision_hash,
  economic_snapshot_hash: body.economic_snapshot_hash, policy_id: body.policy_id,
  policy_version: 2, policy_hash: body.policy_hash, approval_status: 'PENDING_REVIEW',
  effective_status: 'PENDING_REVIEW', approved_by: null, approved_at: null,
  expires_at: 1100, created_at: 1000, last_event_id: 'ae_1',
  financial_eligibility: 'NOT_EXECUTION_ELIGIBLE', is_currently_applicable: false,
  is_executable: false,
};
const meta = (read_only) => ({ program_id: PROGRAM, commitment: 'confirmed', chain_now_unix: 1000,
  rpc_context_slots: {}, atomic_snapshot: false, read_only, matching_engine: 'rust-epic-3.1' });

test('TypeScript approval challenge matches Python canonical Ed25519 message bytes', async () => {
  const script = `import json,sys\nfrom tools.economic_ledger.spending_approvals import canonical_approval_message\nb=json.loads(sys.stdin.read())\nprint(canonical_approval_message(1000,b['agent_account'],b['owner_pubkey'],'POST','${ROOT}',b).decode())`;
  const expected = execFileSync('python3', ['-c', script], {
    cwd: fileURLToPath(new URL('../../../', import.meta.url)), input: JSON.stringify(body), encoding: 'utf8',
  }).trim();
  const actual = new TextDecoder().decode(await spendingApprovalMessage(ACCOUNT, OWNER, ROOT, 1000, body));
  assert.equal(actual, expected);
  assert.notEqual(actual, new TextDecoder().decode(await spendingApprovalMessage(ACCOUNT, OWNER, ROOT, 1000,
    { ...body, amount_base_units_str: '9007199254740994' })));
  await assert.rejects(spendingApprovalMessage(ACCOUNT, OWNER, ROOT, 1000, { ...body, action: 'REVOKE' }), /action/);
  await assert.rejects(spendingApprovalMessage(ACCOUNT, OWNER, ROOT, 1000,
    { ...body, amount_base_units_str: '18446744073709551616' }), /amount_base_units_str/);
});

test('SDK routes exact consent payloads and rejects unsigned or executable responses', async () => {
  const calls = [];
  const client = new MarketplaceClient({ baseUrl: 'http://127.0.0.1:8787', fetchImpl: async (url, options) => {
    calls.push({ url: String(url), method: options.method, headers: options.headers, body: options.body });
    const route = String(url);
    const data = route.endsWith('/context/' + body.decision_id) ? {
      ...Object.fromEntries(Object.keys(body).filter((key) => !['action', 'issued_at', 'expires_at', 'nonce', 'idempotency_key', 'reason'].includes(key))
        .map((key) => [key, body[key]])), approval_id: APPROVAL_ID,
      proposal: { amount_base_units_str: body.amount_base_units_str },
      decision: { decision_id: body.decision_id, proposal_id: body.proposal_id,
        agent_account: ACCOUNT, network: body.network, genesis_hash: body.genesis_hash,
        program_id: PROGRAM, token_mint: MINT, economic_evidence_status: 'UNVERIFIED',
        economic_snapshot_hash: body.economic_snapshot_hash, decision_engine_version: 'v1',
        decision: 'REQUIRE_APPROVAL', policy_id: body.policy_id, policy_hash: body.policy_hash,
        policy_version: 2, evaluated_at: 1000, expires_at: 1100, daily_window_start_utc: 0,
        daily_window_end_utc: 86400, requested_amount_base_units_str: body.amount_base_units_str,
        daily_limit_base_units_str: null, daily_used_base_units_str: null,
        daily_committed_base_units_str: null, daily_remaining_base_units_str: null,
        minimum_reserve_base_units_str: null, accounting_reserved_base_units_str: null,
        available_liquidity_base_units_str: null, accrued_obligations_base_units_str: null,
        reason_codes: [], reason_details: [], is_executable: false, historical: false,
        is_currently_applicable: false },
    } : route.endsWith('/history') ? [] : options.method === 'GET' && route.endsWith(ROOT) ? [approval] : approval;
    return new Response(JSON.stringify({ data, meta: meta(options.method === 'GET') }),
      { status: options.method === 'POST' ? 201 : 200 });
  } });
  const options = { authHeaders: { 'X-Signer-Pubkey': OWNER, 'X-Timestamp': '1000', 'X-Signature': 'signed' } };
  const context = await client.getSpendingApprovalContext(ACCOUNT, body.decision_id, options);
  assert.equal(context.data.amount_base_units_str, body.amount_base_units_str);
  assert.equal((await client.createSpendingApprovalReview(ACCOUNT, body, options)).data.is_executable, false);
  assert.equal((await client.listAgentSpendingApprovals(ACCOUNT, options)).data.length, 1);
  assert.equal((await client.getAgentSpendingApproval(ACCOUNT, APPROVAL_ID, options)).data.approval_id, APPROVAL_ID);
  assert.equal((await client.getSpendingApprovalHistory(ACCOUNT, APPROVAL_ID, options)).data.length, 0);
  assert.equal(JSON.parse(calls[1].body).amount_base_units_str, '9007199254740993');
  assert.equal(calls[1].headers['X-Signature'], 'signed');
  await assert.rejects(client.createSpendingApprovalReview(ACCOUNT, body, { authHeaders: {} }), /Signed policy/);
  const unsafe = new MarketplaceClient({ baseUrl: 'http://127.0.0.1:8787', fetchImpl: async () =>
    new Response(JSON.stringify({ data: { ...approval, is_executable: true }, meta: meta(false) }), { status: 201 }) });
  await assert.rejects(unsafe.createSpendingApprovalReview(ACCOUNT, body, options), /cannot execute/);
});
