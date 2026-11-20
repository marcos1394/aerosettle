import assert from 'node:assert/strict';
import test from 'node:test';
import { DEVNET_MANIFEST } from './environments.ts';
import { fetchIndex, fetchReady, fetchRecord } from '../devnet/index.ts';
import { parseAgent, parseCatalog, parseWorkOrder, capabilityBits, explorerUrl,
  filterAgents, filterWorkOrders } from '../devnet/catalog.ts';

const expires = new Date(Date.now() + 60_000).toISOString();
const generated = new Date(Date.now() - 60_000).toISOString();
const hash = 'a'.repeat(64);
const ready = { status: 'ready', genesis: DEVNET_MANIFEST.genesis_hash,
  program_id: DEVNET_MANIFEST.program_id, source: 'RELEASE_BOUND_RPC_SNAPSHOT',
  snapshot_sha256: hash, expires_at: expires };
const provenance = { network: 'solana:devnet', genesis_hash: DEVNET_MANIFEST.genesis_hash,
  program_id: DEVNET_MANIFEST.program_id, idl_sha256: DEVNET_MANIFEST.idl_sha256,
  binary_sha256: '6cf3412c55c38e91b2ba0039aea24d58782c5db0d18759ffdab1c88788cdc3a2',
  deployment_id: '06c7dfa7528460969a5ca1e8bd001f9c9f1f1f0df3d69fe36649e413e0b14ae6',
  mint: DEVNET_MANIFEST.token_mint, mint_authority: '4om6LcFXaZ2Wtbn3P2ZvvyqssXFQs1xjNmE2Fnj7mRHa',
  token_program: DEVNET_MANIFEST.token_program, mint_decimals: 6,
  snapshot_sha256: hash, generated_at: generated, expires_at: expires,
  commitment: 'finalized', slot_min: 100, slot_max: 101, observed_slot: 102,
  provider: 'official-devnet', provenance: 'RELEASE_BOUND_RPC_SNAPSHOT' };
const agent = { agent_account: 'A'.repeat(32), agent_id: 'a'.repeat(64),
  owner: 'B'.repeat(32), signing_authority: 'C'.repeat(32),
  protocol_config: 'D'.repeat(32), capabilities: 33, active: true, status: 'Active' };
const order = { work_order_account: 'E'.repeat(32), work_order_id: 'b'.repeat(64),
  creator: 'B'.repeat(32), protocol_config: 'D'.repeat(32),
  token_mint: DEVNET_MANIFEST.token_mint, token_program: DEVNET_MANIFEST.token_program,
  required_capabilities: 33, execution_deadline: 1794600303, is_open: false, status: 'Settled' };
const answer = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status });
const page = (items: unknown[], meta = provenance, next_cursor: string | null = null,
  total = items.length) => answer({ data: { items, total, next_cursor }, provenance: meta,
  advisory_only: true, is_financial_authority: false, is_executable: false });

test('browser binds both account pages and typed records to one finalized release snapshot', async () => {
  const fetcher = async (url: URL | RequestInfo) => {
    const path = String(url);
    if (path.endsWith('/ready')) return answer(ready);
    if (path.includes('/agents/')) return answer({ data: agent, provenance,
      advisory_only: true, is_financial_authority: false, is_executable: false });
    if (path.includes('/agents')) return page([agent]);
    return page([order]);
  };
  const verified = await fetchReady(fetcher as typeof fetch);
  const index = await fetchIndex(verified, fetcher as typeof fetch);
  const catalog = parseCatalog(index);
  assert.equal(catalog.agents.length, 1);
  assert.equal(catalog.workorders.length, 1);
  assert.equal(catalog.agents[0].provenance, 'ONCHAIN_VERIFIED');
  assert.deepEqual(capabilityBits(catalog.agents[0].capabilities), [0, 5]);
  assert.match(explorerUrl(catalog.agents[0].agent_account), /cluster=devnet$/);
  assert.deepEqual(parseAgent(await fetchRecord('agents', agent.agent_account,
    ready, index.provenance, fetcher as typeof fetch)), catalog.agents[0]);
});

test('browser consumes all bounded pages without silently truncating', async () => {
  const calls: string[] = [];
  const fetcher = async (url: URL | RequestInfo) => {
    const path = String(url); calls.push(path);
    if (path.includes('/agents') && !path.includes('cursor=')) return page([agent], provenance, 'page-2', 2);
    if (path.includes('/agents')) return page([{ ...agent, agent_account: 'F'.repeat(32) }], provenance, null, 2);
    return page([]);
  };
  const result = await fetchIndex(ready, fetcher as typeof fetch);
  assert.equal(result.agentCount, 2);
  assert.equal(result.agents.length, 2);
  assert.equal(calls.filter((value) => value.includes('/agents')).length, 2);
});

test('browser rejects stale, forged and cross-network snapshot provenance', async () => {
  await assert.rejects(fetchReady(async () => answer({ ...ready,
    expires_at: '2020-01-01T00:00:00Z' }) as Response), /API_IDENTITY_MISMATCH/);
  for (const change of [
    { snapshot_sha256: 'b'.repeat(64) }, { network: 'solana:mainnet' },
    { program_id: 'F'.repeat(32) }, { idl_sha256: 'f'.repeat(64) },
    { commitment: 'confirmed' }, { slot_max: 103 }, { mint_decimals: 9 },
  ]) {
    const forged = async () => page([], { ...provenance, ...change });
    await assert.rejects(fetchIndex(ready, forged as typeof fetch), /INDEX_PROVENANCE_INVALID/);
  }
  const crossPage = async (url: URL | RequestInfo) => page([], String(url).includes('/workorders')
    ? { ...provenance, slot_min: 99 } : provenance);
  await assert.rejects(fetchIndex(ready, crossPage as typeof fetch), /INDEX_PROVENANCE_INVALID/);
});

test('browser rejects incomplete pagination and unverified record fields', async () => {
  const incomplete = async (url: URL | RequestInfo) => String(url).includes('/agents')
    ? page([agent], provenance, null, 2) : page([]);
  await assert.rejects(fetchIndex(ready, incomplete as typeof fetch), /INDEX_PAGINATION_INCOMPLETE/);
  assert.throws(() => parseAgent({ ...agent, owner: 'invalid' }), /AGENT_RECORD_INVALID/);
  assert.throws(() => parseWorkOrder({ ...order, token_mint: 'F'.repeat(32) }), /WORKORDER_RECORD_INVALID/);
  assert.throws(() => parseWorkOrder({ ...order, required_capabilities: 65536 }), /WORKORDER_RECORD_INVALID/);
  assert.throws(() => explorerUrl('https://evil.example'), /INVALID_PUBKEY/);
  const stripped = parseAgent({ ...agent, name: 'Kestrel-7', income: 999999 });
  assert.equal('name' in stripped, false);
  assert.equal('income' in stripped, false);
  const duplicate = { agents: [agent, agent], workorders: [], agentCount: 2,
    workorderCount: 0, snapshotSha: hash, expiresAt: expires, provenance };
  assert.throws(() => parseCatalog(duplicate as Parameters<typeof parseCatalog>[0]),
    /INDEX_RECORD_INVALID/);
});

test('expired public API returns no current catalog and detail mismatch fails closed', async () => {
  const stale = await fetchReady(async () => answer({ status: 'stale',
    reason: 'SNAPSHOT_EXPIRED', expires_at: '2020-01-01T00:00:00Z' }, 503) as Response);
  assert.equal(stale.status, 'stale');
  await assert.rejects(fetchIndex(stale), /INDEX_NOT_READY/);
  const detail = async () => answer({ data: { ...agent, agent_account: 'F'.repeat(32) },
    provenance, advisory_only: true, is_financial_authority: false, is_executable: false });
  await assert.rejects(fetchRecord('agents', agent.agent_account, ready,
    provenance as Parameters<typeof fetchRecord>[3], detail as typeof fetch), /INDEX_RECORD_INVALID/);
});

test('verified catalog filters, sorting and pagination inputs use only published fields', () => {
  const first = parseAgent(agent);
  const second = parseAgent({ ...agent, agent_account: 'F'.repeat(32),
    owner: 'G'.repeat(32), capabilities: 2, status: 'OwnerSuspended' });
  assert.deepEqual(filterAgents([second, first], '', '', '', 'address'), [first, second]);
  assert.deepEqual(filterAgents([first, second], 'g'.repeat(32), '', '', 'address'), [second]);
  assert.deepEqual(filterAgents([first, second], '', 'Active', '', 'address'), [first]);
  assert.deepEqual(filterAgents([first, second], '', '', '1', 'address'), [second]);
  assert.deepEqual(filterAgents([first, second], '', '', '', 'address-desc'), [second, first]);
  const firstOrder = parseWorkOrder(order);
  const secondOrder = parseWorkOrder({ ...order, work_order_account: 'F'.repeat(32),
    creator: 'G'.repeat(32), required_capabilities: 2, execution_deadline: 1,
    status: 'Open' });
  assert.deepEqual(filterWorkOrders([firstOrder, secondOrder], '', '', '', 'deadline'),
    [secondOrder, firstOrder]);
  assert.deepEqual(filterWorkOrders([firstOrder, secondOrder], '', 'Settled', '', 'address'),
    [firstOrder]);
  assert.deepEqual(filterWorkOrders([firstOrder, secondOrder], '', '', '1', 'address'),
    [secondOrder]);
  assert.deepEqual(filterWorkOrders([firstOrder, secondOrder], 'g'.repeat(32), '', '', 'address'),
    [secondOrder]);
});
