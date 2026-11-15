import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { existsSync, readFileSync, readdirSync, writeFileSync } from 'node:fs';
import { DEVNET_MANIFEST, LOCALNET_MANIFEST } from '../src/config/environments.ts';
import { verifyManifest } from '../src/config/manifest.ts';

const target = process.argv[2];
assert.ok(target === 'localnet' || target === 'devnet', 'Unknown build target');
const root = new URL('../', import.meta.url);
const manifest = target === 'devnet' ? DEVNET_MANIFEST : LOCALNET_MANIFEST;
const idl = readFileSync(new URL(`public/idl/${target}-idl.json`, root), 'utf8');
await verifyManifest(manifest, idl);
const output = new URL(`dist-${target}/`, root);
const html = readFileSync(new URL('index.html', output), 'utf8');
const assets = readdirSync(new URL('assets/', output))
  .filter((name) => name.endsWith('.js'))
  .map((name) => readFileSync(new URL(`assets/${name}`, output), 'utf8'));
const bundle = assets.join('\n');
assert.ok(assets.length > 0 && html.includes('/assets/'), 'Missing build artifact');
if (target === 'devnet') {
  assert.ok(existsSync(new URL('idl/devnet-idl.json', output)), 'Approved Devnet IDL missing');
  assert.ok(!existsSync(new URL('idl/localnet-idl.json', output)), 'Localnet IDL leaked into Devnet artifact');
  assert.equal(readFileSync(new URL('idl/devnet-idl.json', output), 'utf8'), idl,
    'Devnet IDL artifact differs from approved source');
  assert.ok(bundle.includes('devnet-app') && bundle.includes(manifest.token_mint), 'Wrong entry or mint');
  for (const forbidden of ['signTransaction', 'sendTransaction', 'LocalnetDevWalletAdapter',
    'localnet-idl.json', 'dev-signer', 'funding-api', 'PhantomWalletAdapter'])
    assert.ok(!bundle.includes(forbidden), `Devnet bundle contains forbidden capability: ${forbidden}`);
} else {
  assert.ok(bundle.includes('bootstrap') || bundle.includes('wallet-adapter'), 'Localnet entry missing');
}
const hash = createHash('sha256').update(bundle).digest('hex');
const evidence = {
  CON53_MULTIENVIROMENT_VERIFIED: false,
  LOCALNET_COMPATIBILITY_VERIFIED: target === 'localnet',
  DEVNET_MANIFEST_VERIFIED: target === 'devnet',
  DEVNET_READ_ONLY: target === 'devnet',
  MAINNET_ENABLED: false,
  TRANSACTION_SIGNING_ENABLED: target === 'localnet',
  ONCHAIN_TRANSACTIONS_SENT: 0,
  STAGING_PUBLIC_DEPLOYED: false,
  target,
  provenance: target === 'devnet' ? 'APPROVED_MANIFEST_OFFLINE' : 'LOCALNET_FIXTURE',
  rpc_live_checked: false,
  manifest_sha256: manifest.manifest_sha256,
  idl_sha256: manifest.idl_sha256,
  bundle_sha256: hash,
};
writeFileSync(new URL(`dist-${target}/con53-evidence.json`, root), JSON.stringify(evidence, null, 2) + '\n');
console.log(JSON.stringify(evidence));
