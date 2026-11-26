import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';
import { DEVNET_MANIFEST } from './devnet-manifest.ts';
import { verifyDevnetManifest } from './verify-devnet-manifest.ts';

const idl = readFileSync(new URL('../../public/idl/devnet-idl.json', import.meta.url), 'utf8');

test('isolated browser manifest verifies approved Devnet IDL and independent pins', async () => {
  const result = await verifyDevnetManifest(DEVNET_MANIFEST, idl);
  assert.equal(result.network, 'solana:devnet');
  assert.equal(result.token_mint, DEVNET_MANIFEST.token_mint);
});

test('isolated browser manifest rejects altered IDL, endpoint, network and program', async () => {
  for (const changed of [
    { network: 'solana:mainnet' }, { rpc_endpoint: 'http://127.0.0.1:8899' },
    { program_id: 'F'.repeat(32) }, { token_mint: 'F'.repeat(32) },
  ]) await assert.rejects(verifyDevnetManifest({ ...DEVNET_MANIFEST, ...changed }, idl),
    /MANIFEST_INVALID/);
  await assert.rejects(verifyDevnetManifest(DEVNET_MANIFEST,
    idl.replace('"version"', '"altered_version"')), /MANIFEST_INVALID/);
});
