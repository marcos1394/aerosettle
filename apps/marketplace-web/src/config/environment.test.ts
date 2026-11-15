import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';
import { PublicKey } from '@solana/web3.js';
import { CAPABILITIES, requireCapability } from './capabilities.ts';
import { DEVNET_MANIFEST, LOCALNET_MANIFEST, selectEnvironment } from './environments.ts';
import { verifyManifest } from './manifest.ts';
import { VerificationSession } from './session.ts';
import { assertEndpointBinding, createRpc, verifyEnvironment, type Rpc } from './verify.ts';

const devnetIdl = readFileSync(new URL('../../public/idl/devnet-idl.json', import.meta.url), 'utf8');
const localnetIdl = readFileSync(new URL('../../public/idl/localnet-idl.json', import.meta.url), 'utf8');
const loader = 'BPFLoaderUpgradeab1e11111111111111111111111';
function fixture(environment: 'DEVNET' | 'LOCALNET', overrides: Record<string, unknown> = {}) {
  const manifest = environment === 'DEVNET' ? DEVNET_MANIFEST : LOCALNET_MANIFEST;
  const programData = new Uint8Array(45);
  programData[0] = 3;
  programData[12] = 1;
  programData.set(new PublicKey('DdHrtAxE5SwcVQUgoKRzoWatZ5yw9UdtBQnRwBizPK2D').toBytes(), 13);
  const program = new Uint8Array(36);
  program[0] = 2;
  program.set(new PublicKey('7kYZxnujXJ9sKGhG9CbDwThJECb693WvvqVFHGmNSsrr').toBytes(), 4);
  const mint = new Uint8Array(82);
  mint[0] = 1;
  mint.set(new PublicKey('4om6LcFXaZ2Wtbn3P2ZvvyqssXFQs1xjNmE2Fnj7mRHa').toBytes(), 4);
  mint[44] = 6;
  mint[45] = 1;
  const account = (data: Uint8Array, owner: string, executable = false) =>
    ({ value: { data: [Buffer.from(data).toString('base64'), 'base64'], owner, executable } });
  const rpc: Rpc = async (method, params) => {
    if (method === 'getGenesisHash') return overrides.genesis ?? manifest.genesis_hash;
    if (method !== 'getAccountInfo') throw new Error('UNEXPECTED_METHOD');
    if (params[0] === manifest.program_id) return overrides.program ?? account(program, loader, true);
    if (params[0] === manifest.token_mint) return overrides.mint ?? account(mint, manifest.token_program);
    if (params[0] === '7kYZxnujXJ9sKGhG9CbDwThJECb693WvvqVFHGmNSsrr')
      return overrides.programData ?? account(programData, loader);
    return { value: null };
  };
  return { manifest, rpc, idl: environment === 'DEVNET' ? devnetIdl : localnetIdl,
    api: async () => ({ status: 'ok', genesis: manifest.genesis_hash,
      program_id: manifest.program_id, service: 'test-api' }) };
}

test('approved Localnet and Devnet manifests and IDLs verify; Mainnet is rejected', async () => {
  await verifyManifest(LOCALNET_MANIFEST, localnetIdl);
  await verifyManifest(DEVNET_MANIFEST, devnetIdl);
  assert.throws(() => selectEnvironment('mainnet'), /MANIFEST_INVALID/);
  assert.throws(() => selectEnvironment('bogus'), /MANIFEST_INVALID/);
  assert.equal(CAPABILITIES.MAINNET.send_transaction, false);
});

test('manifest alteration, IDL alteration and environment injection fail closed', async () => {
  await assert.rejects(verifyManifest({ ...DEVNET_MANIFEST, program_id: LOCALNET_MANIFEST.token_mint }, devnetIdl), /MANIFEST_INVALID/);
  await assert.rejects(verifyManifest({ ...DEVNET_MANIFEST, rpc_endpoint: 'https://evil.example' }, devnetIdl), /MANIFEST_INVALID/);
  await assert.rejects(verifyManifest(DEVNET_MANIFEST, devnetIdl + ' '), /MANIFEST_INVALID/);
  await assert.rejects(verifyManifest({ ...DEVNET_MANIFEST, environment: 'MAINNET' }, devnetIdl), /MANIFEST_INVALID/);
});

test('Localnet is verified only when RPC and API agree', async () => {
  const { manifest, rpc, idl, api } = fixture('LOCALNET');
  assert.doesNotThrow(() => assertEndpointBinding(manifest, manifest.rpc_endpoint, manifest.api_endpoint));
  assert.throws(() => assertEndpointBinding(manifest, DEVNET_MANIFEST.rpc_endpoint, manifest.api_endpoint),
    /API_RPC_ENDPOINT_MISMATCH/);
  assert.throws(() => assertEndpointBinding(manifest, manifest.rpc_endpoint, 'https://foreign.example'),
    /API_RPC_ENDPOINT_MISMATCH/);
  assert.equal((await verifyEnvironment(manifest, idl, rpc, api)).status, 'VERIFIED');
  assert.equal((await verifyEnvironment(manifest, idl, rpc, async () => ({ ...await api(), genesis: DEVNET_MANIFEST.genesis_hash }))).status,
    'NETWORK_MISMATCH');
});

test('Devnet RPC identity yields read-only degraded state while API is absent', async () => {
  const { manifest, rpc, idl } = fixture('DEVNET');
  const result = await verifyEnvironment(manifest, idl, rpc);
  assert.equal(result.status, 'DEGRADED_READ_ONLY');
  assert.equal(result.provenance, 'LIVE_DEVNET_READ_ONLY');
  assert.equal(result.reason, 'API_NOT_CONFIGURED');
});

test('genesis, program, mint, owner, decimals and authority mismatch never verify', async () => {
  const base = fixture('DEVNET');
  const cases = [
    { genesis: LOCALNET_MANIFEST.genesis_hash },
    { program: { value: { owner: loader, executable: false, data: ['', 'base64'] } } },
    { mint: { value: null } },
    { mint: { value: { owner: loader, executable: false, data: ['', 'base64'] } } },
    { mint: { value: { owner: base.manifest.token_program, executable: false,
      data: [Buffer.from(Uint8Array.from({ length: 82 }, (_, i) => i === 44 ? 9 : i === 45 ? 1 : 0)).toString('base64'), 'base64'] } } },
    { mint: { value: { owner: base.manifest.token_program, executable: false,
      data: [Buffer.from(Uint8Array.from({ length: 82 }, (_, i) => i === 44 ? 6 : i === 45 ? 1 : 0)).toString('base64'), 'base64'] } } },
    { programData: { value: null } },
  ];
  for (const override of cases) {
    const { manifest, rpc, idl } = fixture('DEVNET', override);
    assert.notEqual((await verifyEnvironment(manifest, idl, rpc)).status, 'VERIFIED');
    assert.notEqual((await verifyEnvironment(manifest, idl, rpc)).status, 'DEGRADED_READ_ONLY');
  }
});

test('RPC failure, incomplete result and abort do not fall back to Localnet', async () => {
  const { manifest, idl } = fixture('DEVNET');
  assert.equal((await verifyEnvironment(manifest, idl, async () => { throw Error('RPC_OFFLINE'); })).status,
    'UNAVAILABLE');
  assert.equal((await verifyEnvironment(manifest, idl, async () => ({}))).status, 'NETWORK_MISMATCH');
  const controller = new AbortController();
  controller.abort();
  assert.equal((await verifyEnvironment(manifest, idl, async () => manifest.genesis_hash, undefined, controller.signal)).status,
    'UNAVAILABLE');
  const rpc = createRpc(manifest.rpc_endpoint, async (url, options) => {
    assert.equal(url, manifest.rpc_endpoint);
    assert.equal((options as RequestInit).method, 'POST');
    return { ok: false } as Response;
  });
  await assert.rejects(rpc('getGenesisHash', []), /RPC_UNAVAILABLE/);
});

test('Devnet financial and wallet capabilities reject attempted use', () => {
  for (const capability of ['connect_wallet', 'prepare_transaction', 'simulate_transaction',
    'request_signature', 'send_transaction'] as const)
    assert.throws(() => requireCapability('DEVNET', capability), /CAPABILITY_DISABLED/);
});

test('context changes discard stale verifications and abort outstanding requests', async () => {
  const session = new VerificationSession<string>();
  const applied: string[] = [];
  let resolveOld!: (value: string) => void;
  const old = session.run('old-wallet', () => new Promise<string>((resolve) => { resolveOld = resolve; }),
    (value) => applied.push(value));
  const fresh = session.run('new-wallet', async () => 'new-network', (value) => applied.push(value));
  await fresh;
  resolveOld('old-network');
  await old;
  assert.deepEqual(applied, ['new-network']);
});
