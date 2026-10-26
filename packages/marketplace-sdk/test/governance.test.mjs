import test from 'node:test';
import assert from 'node:assert/strict';
import { execFileSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import { MarketplaceClient, governanceMutationMessage } from '../dist/index.js';

const ID = 'org_' + 'a'.repeat(32);
const OWNER = '8rPDpYsLZxNBm8Q8GKSKki8Ag6dodkasedhUT9x3Ec1D';
const path = `/v1/organizations/${ID}/governance/actions`;
const body = { organization_id: ID, proposal_id: '', actor_pubkey: OWNER,
  action: 'CREATE_BYLAWS', bylaws_version: 0, bylaws_hash: '', electorate_snapshot_hash: '',
  payload: { bylaws: { title: 'Charter', quorum_bps: 5000 } }, expected_version: 0,
  issued_at: 1000, expires_at: 1300, nonce: 'governance-nonce-1', idempotency_key: 'governance-idem-1' };
const meta = read_only => ({ program_id: OWNER, commitment: 'confirmed', chain_now_unix: 1000,
  rpc_context_slots: {}, atomic_snapshot: false, read_only, matching_engine: 'rust-epic-3.1' });
const headers = { 'X-Signer-Pubkey': OWNER, 'X-Timestamp': '1000', 'X-Signature': 'signed' };

test('governance challenge matches Python and binds exact vote payload', async () => {
  const message = new TextDecoder().decode(await governanceMutationMessage('POST', path, body));
  const script = `import json,sys\nfrom tools.governance.signatures import mutation_message\nb=json.loads(sys.stdin.read())\nprint(mutation_message('POST','/v1/organizations/${ID}/governance/actions',b).decode())`;
  const expected = execFileSync('python3', ['-c', script], {
    cwd: fileURLToPath(new URL('../../../', import.meta.url)), input: JSON.stringify(body), encoding: 'utf8',
  }).trim();
  assert.equal(message, expected);
  const changed = new TextDecoder().decode(await governanceMutationMessage('POST', path,
    { ...body, payload: { bylaws: { title: 'Charter', quorum_bps: 9000 } } }));
  assert.notEqual(message, changed);
  await assert.rejects(governanceMutationMessage('POST', path + '/wrong', body), /route|context/);
});

test('governance SDK rejects execution claims and requires signed headers', async () => {
  const client = new MarketplaceClient({ baseUrl: 'http://127.0.0.1:8787', fetchImpl: async () =>
    new Response(JSON.stringify({ data: { organization_id: ID, governance_version: 0,
      current_bylaws: null, proposal_count: 0, is_executable: false }, meta: meta(true) })) });
  const overview = await client.getGovernanceSection(ID, '', { authHeaders: headers });
  assert.equal(overview.data.governance_version, 0);
  await assert.rejects(client.getGovernanceSection(ID, '', { authHeaders: {} }), /Signed policy mutation headers/);
  const unsafe = new MarketplaceClient({ baseUrl: 'http://127.0.0.1:8787', fetchImpl: async () =>
    new Response(JSON.stringify({ data: { is_executable: true, funds_transferred: true }, meta: meta(false) })) });
  await assert.rejects(unsafe.applyGovernanceAction(ID, body, { authHeaders: headers }), /financial execution authority/);
});
