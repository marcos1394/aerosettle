import assert from 'node:assert/strict';
import test from 'node:test';
import { DEVNET_MANIFEST } from './environments.ts';
import { fetchIndex, fetchReady } from '../devnet/index.ts';

const expires = new Date(Date.now() + 60_000).toISOString();
const hash = 'a'.repeat(64);
const ready = { status: 'ready', genesis: DEVNET_MANIFEST.genesis_hash,
  program_id: DEVNET_MANIFEST.program_id, source: 'RELEASE_BOUND_RPC_SNAPSHOT',
  snapshot_sha256: hash, expires_at: expires };
const provenance = { genesis_hash: DEVNET_MANIFEST.genesis_hash,
  program_id: DEVNET_MANIFEST.program_id, idl_sha256: DEVNET_MANIFEST.idl_sha256,
  binary_sha256: '6cf3412c55c38e91b2ba0039aea24d58782c5db0d18759ffdab1c88788cdc3a2',
  mint: DEVNET_MANIFEST.token_mint, token_program: DEVNET_MANIFEST.token_program, mint_decimals: 6,
  snapshot_sha256: hash, expires_at: expires, provenance: 'RELEASE_BOUND_RPC_SNAPSHOT' };
const answer = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status });

test('browser binds same-origin ready and both account pages to one release snapshot', async () => {
  const fetcher = async (url: URL | RequestInfo) => {
    const path = String(url);
    if (path.endsWith('/ready')) return answer(ready);
    if (path.includes('/agents')) return answer({ data: { items: [{ agent_account: 'agent' }],
      total: 1, next_cursor: null }, provenance, advisory_only: true,
      is_financial_authority: false, is_executable: false });
    return answer({ data: { items: [], total: 0, next_cursor: null }, provenance,
      advisory_only: true, is_financial_authority: false, is_executable: false });
  };
  const verified = await fetchReady(fetcher as typeof fetch);
  const index = await fetchIndex(verified, fetcher as typeof fetch);
  assert.equal(index.agentCount, 1);
  assert.equal(index.workorderCount, 0);
});

test('browser rejects stale and forged snapshot provenance', async () => {
  await assert.rejects(fetchReady(async () => answer({ ...ready,
    expires_at: '2020-01-01T00:00:00Z' }) as Response), /API_IDENTITY_MISMATCH/);
  const forged = async () => answer({ data: { items: [], total: 0 },
    provenance: { ...provenance, snapshot_sha256: 'b'.repeat(64) },
    advisory_only: true, is_financial_authority: false, is_executable: false });
  await assert.rejects(fetchIndex(ready, forged as typeof fetch), /INDEX_PROVENANCE_INVALID/);
});
