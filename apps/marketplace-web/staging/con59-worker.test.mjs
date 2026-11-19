import test from 'node:test';
import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { readFileSync } from 'node:fs';

const template = readFileSync(new URL('./con59-worker.mjs', import.meta.url), 'utf8');
const now = Date.parse('2026-11-17T12:00:00Z');
const base = {
  schema_version: 1,
  metadata: {
    network: 'solana:devnet', genesis_hash: 'EtWTRABZaYq6iMfeYKouRu166VU2xqa1wcaWoxPkrZBG',
    program_id: 'CeA1P1NSuPLUH31KsT4j3pZeBsknQZ3NSC6GUAqcsCLy',
    idl_sha256: 'a6e436aa1c6468b4f518b742e40a2664e38dcdf7bc1419e53e1624444888e15d',
    binary_sha256: '6cf3412c55c38e91b2ba0039aea24d58782c5db0d18759ffdab1c88788cdc3a2',
    deployment_id: '06c7dfa7528460969a5ca1e8bd001f9c9f1f1f0df3d69fe36649e413e0b14ae6',
    mint: 'HpfaV9oRuTN1b3ktDKvJoWqUWFZ1o9VFmhejxxqQ1vyh',
    token_program: 'TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA',
    mint_authority: '4om6LcFXaZ2Wtbn3P2ZvvyqssXFQs1xjNmE2Fnj7mRHa', mint_decimals: 6,
    source_rpc: 'https://api.devnet.solana.com', commitment: 'finalized',
    provenance: 'RELEASE_BOUND_RPC_SNAPSHOT', atomic_snapshot: false,
    slot_min: 100, slot_max: 101, observed_slot: 102,
    generated_at: '2026-11-17T11:00:00Z', expires_at: '2026-11-18T11:00:00Z',
    agent_count: 2, work_order_count: 1,
  },
  agents: [
    { agent_account: '11111111111111111111111111111111', status: 'Active' },
    { agent_account: '22222222222222222222222222222222', status: 'Revoked' },
  ],
  work_orders: [{ work_order_account: '33333333333333333333333333333333', status: 'Open' }],
};
async function worker(value = base, alterHash = false) {
  const raw = JSON.stringify(value);
  const hash = createHash('sha256').update(raw).digest('hex');
  const source = template.replaceAll('__SNAPSHOT_JSON__', JSON.stringify(raw))
    .replaceAll('__SNAPSHOT_SHA256__', alterHash ? '0'.repeat(64) : hash);
  return import(`data:text/javascript;base64,${Buffer.from(source).toString('base64')}`);
}
function request(path, method = 'GET', origin) {
  return new Request(`https://conatus-devnet-staging.pages.dev${path}`, {
    method, headers: origin ? { Origin: origin } : {},
  });
}

test('Pages API serves only bounded verified snapshot data and opaque pagination', async () => {
  const { handle } = await worker();
  const ready = await handle(request('/api/ready'), now);
  assert.equal(ready.status, 200);
  assert.equal(ready.headers.get('strict-transport-security'), 'max-age=31536000');
  assert.match(ready.headers.get('content-security-policy'), /default-src 'none'/);
  assert.equal((await ready.json()).source, 'RELEASE_BOUND_RPC_SNAPSHOT');
  const first = await handle(request('/api/v1/agents?limit=1'), now);
  const body = await first.json();
  assert.equal(body.data.total, 2);
  assert.equal(body.data.items.length, 1);
  assert.equal(body.is_financial_authority, false);
  assert.equal(body.is_executable, false);
  assert.equal(body.provenance.commitment, 'finalized');
  const second = await handle(request(`/api/v1/agents?limit=1&cursor=${body.data.next_cursor}`), now);
  assert.equal((await second.json()).data.items[0].status, 'Revoked');
  const empty = await handle(request('/api/v1/agents?status=OwnerSuspended'), now);
  assert.equal((await empty.json()).data.total, 0);
  assert.equal((await handle(request('/api/v1/workorders'), now)).status, 200);
  assert.equal((await handle(request('/api/v1/network'), now)).status, 200);
  assert.equal((await handle(request('/api/v1/program'), now)).status, 200);
  assert.equal((await handle(request('/api/v1/agents/11111111111111111111111111111111'), now)).status, 200);
});

test('expiry, hash tampering, identity mismatch and invalid requests fail closed', async () => {
  const { handle } = await worker();
  assert.equal((await handle(request('/api/ready'), Date.parse(base.metadata.expires_at))).status, 503);
  assert.equal((await handle(request('/api/v1/agents'), Date.parse(base.metadata.expires_at))).status, 503);
  assert.equal((await handle(request('/api/v1/agents', 'POST'), now)).status, 405);
  assert.equal((await handle(request('/api/v1/agents', 'GET', 'https://evil.example'), now)).status, 403);
  assert.equal((await handle(request('/api/v1/agents?limit=51'), now)).status, 400);
  assert.equal((await handle(request('/api/v1/agents?cursor=fake'), now)).status, 400);
  assert.equal((await handle(request('/api/v1/agents?status=garbage'), now)).status, 400);
  assert.equal((await handle(request('/api/rpc'), now)).status, 404);
  const corrupt = await worker(base, true);
  assert.equal((await corrupt.handle(request('/api/ready'), now)).status, 503);
  const wrongNetwork = await worker({ ...base, metadata: { ...base.metadata,
    genesis_hash: 'wrong' } });
  assert.equal((await wrongNetwork.handle(request('/api/ready'), now)).status, 503);
});
