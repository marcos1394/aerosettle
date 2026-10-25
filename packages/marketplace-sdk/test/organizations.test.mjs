import test from 'node:test';
import assert from 'node:assert/strict';
import { execFileSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import { MarketplaceClient, organizationMutationMessage, organizationReadMessage } from '../dist/index.js';

const OWNER = '8rPDpYsLZxNBm8Q8GKSKki8Ag6dodkasedhUT9x3Ec1D';
const PROGRAM = 'CeA1P1NSuPLUH31KsT4j3pZeBsknQZ3NSC6GUAqcsCLy';
const ID = 'org_' + 'a'.repeat(32);
const body = { organization_id: ID, actor_pubkey: OWNER, target_type: 'ORGANIZATION',
  target_id: ID, action: 'CREATE', role_id: 'OWNER', permission_scope: 'organization',
  payload: { owner_pubkey: OWNER, organization_name: 'Fleet One', organization_slug: 'fleet-one',
    description: 'Test', organization_type: 'COLLECTIVE', jurisdiction: 'MX' },
  expected_version: 0, issued_at: 1000, expires_at: 1300,
  nonce: 'organization-nonce-1', idempotency_key: 'organization-idem-1' };
const org = { organization_id: ID, organization_name: 'Fleet One', organization_slug: 'fleet-one',
  description: 'Test', organization_type: 'COLLECTIVE', founder_pubkey: OWNER, owner_pubkey: OWNER,
  legal_representative_pubkey: null, legal_representative_status: 'UNVERIFIED',
  jurisdiction: 'MX', legal_entity_name: '', legal_entity_verification_status: 'UNVERIFIED',
  organization_status: 'ACTIVE', created_at: 1000, updated_at: 1000, version: 1,
  is_financial_authority: false, is_device_signing_authority: false };
const meta = read_only => ({ program_id: PROGRAM, commitment: 'confirmed', chain_now_unix: 1000,
  rpc_context_slots: {}, atomic_snapshot: false, read_only, matching_engine: 'rust-epic-3.1' });
const headers = { 'X-Signer-Pubkey': OWNER, 'X-Timestamp': '1000', 'X-Signature': 'signed' };

test('organization admin and read challenges match Python and bind exact action and route', async () => {
  const path = '/v1/organizations';
  const message = new TextDecoder().decode(await organizationMutationMessage('POST', path, body));
  const script = `import json,sys\nfrom tools.organizations.signatures import mutation_message\nb=json.loads(sys.stdin.read())\nprint(mutation_message('POST','/v1/organizations',b).decode())`;
  const expected = execFileSync('python3', ['-c', script], {
    cwd: fileURLToPath(new URL('../../../', import.meta.url)), input: JSON.stringify(body), encoding: 'utf8',
  }).trim();
  assert.equal(message, expected);
  assert.notEqual(message, new TextDecoder().decode(await organizationMutationMessage('POST', path,
    { ...body, action: 'UPDATE_METADATA' }).catch(() => new Uint8Array())));
  const read = new TextDecoder().decode(organizationReadMessage(`/v1/organizations/${ID}`, OWNER, 1000));
  assert.equal(read, `conatus:organization-read:v1:1000:${OWNER}:/v1/organizations/${ID}`);
});

test('organization API methods require signatures and reject claimed financial authority', async () => {
  const calls = [];
  const client = new MarketplaceClient({ baseUrl: 'http://127.0.0.1:8787', fetchImpl: async (url, init) => {
    calls.push([String(url), init.method, init.headers]);
    return new Response(JSON.stringify({ data: init.method === 'POST' ? org :
      String(url).endsWith('/v1/organizations') ? [{ organization: org, permissions: ['organization.read'] }] :
      { organization: org, permissions: ['organization.read'] }, meta: meta(init.method === 'GET') }));
  } });
  await client.createOrganization(body, { authHeaders: headers });
  const list = await client.listMyOrganizations({ authHeaders: headers });
  assert.equal(list.data[0].organization.owner_pubkey, OWNER);
  assert.deepEqual(calls.map(item => item[1]), ['POST', 'GET']);
  assert.ok(calls.every(item => item[2]['X-Signature'] === 'signed'));
  await assert.rejects(client.createOrganization(body, { authHeaders: {} }), /Signed policy mutation headers/);
  const unsafe = new MarketplaceClient({ baseUrl: 'http://127.0.0.1:8787', fetchImpl: async () =>
    new Response(JSON.stringify({ data: { ...org, is_financial_authority: true }, meta: meta(false) })) });
  await assert.rejects(unsafe.createOrganization(body, { authHeaders: headers }), /unverified authority/);
  const unsafeRoles = new MarketplaceClient({ baseUrl: 'http://127.0.0.1:8787', fetchImpl: async () =>
    new Response(JSON.stringify({ data: { catalog: { OWNER: ['treasury.transfer'] },
      assignments: { [OWNER]: 'OWNER' } }, meta: meta(true) })) });
  await assert.rejects(unsafeRoles.getOrganizationSection(ID, 'roles', { authHeaders: headers }),
    /Unsafe organization role catalog/);
  const unsafeDelegation = new MarketplaceClient({ baseUrl: 'http://127.0.0.1:8787', fetchImpl: async () =>
    new Response(JSON.stringify({ data: [{ permission: 'wallet.sign_transaction' }], meta: meta(true) })) });
  await assert.rejects(unsafeDelegation.getOrganizationSection(ID, 'delegations', { authHeaders: headers }),
    /Unsafe organization delegation/);
});
