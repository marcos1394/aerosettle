import assert from 'node:assert/strict';
import { readFileSync, writeFileSync } from 'node:fs';
const read = (name) => JSON.parse(readFileSync(new URL(`../dist-${name}/con53-evidence.json`, import.meta.url)));
const localnet = read('localnet');
const devnet = read('devnet');
assert.equal(localnet.LOCALNET_COMPATIBILITY_VERIFIED, true);
assert.equal(devnet.DEVNET_MANIFEST_VERIFIED, true);
assert.equal(devnet.DEVNET_READ_ONLY, true);
assert.equal(devnet.TRANSACTION_SIGNING_ENABLED, false);
assert.notEqual(localnet.manifest_sha256, devnet.manifest_sha256);
const evidence = {
  CON53_MULTIENVIROMENT_VERIFIED: true,
  LOCALNET_COMPATIBILITY_VERIFIED: true,
  DEVNET_MANIFEST_VERIFIED: true,
  DEVNET_READ_ONLY: true,
  MAINNET_ENABLED: false,
  TRANSACTION_SIGNING_ENABLED: false,
  ONCHAIN_TRANSACTIONS_SENT: 0,
  STAGING_PUBLIC_DEPLOYED: false,
  rpc_live_checked: false,
  api_devnet_configured: false,
  localnet: { manifest_sha256: localnet.manifest_sha256, idl_sha256: localnet.idl_sha256,
    bundle_sha256: localnet.bundle_sha256 },
  devnet: { manifest_sha256: devnet.manifest_sha256, idl_sha256: devnet.idl_sha256,
    bundle_sha256: devnet.bundle_sha256 },
};
writeFileSync(new URL('../dist-devnet/con53-evidence.json', import.meta.url),
  JSON.stringify(evidence, null, 2) + '\n');
console.log(JSON.stringify(evidence));
