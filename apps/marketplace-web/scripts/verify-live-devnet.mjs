import { readFileSync, writeFileSync } from 'node:fs';
import { DEVNET_MANIFEST } from '../src/config/environments.ts';
import { createRpc, verifyEnvironment } from '../src/config/verify.ts';

const idl = readFileSync(new URL('../public/idl/devnet-idl.json', import.meta.url), 'utf8');
const result = await verifyEnvironment(DEVNET_MANIFEST, idl, createRpc(DEVNET_MANIFEST.rpc_endpoint));
const evidence = {
  environment: 'DEVNET',
  verification_status: result.status,
  reason: result.reason,
  provenance: result.provenance,
  observed_at: result.observedAt,
  network: DEVNET_MANIFEST.network,
  genesis_hash: result.genesis ?? null,
  program_id: DEVNET_MANIFEST.program_id,
  mint: DEVNET_MANIFEST.token_mint,
  idl_sha256: DEVNET_MANIFEST.idl_sha256,
  manifest_sha256: DEVNET_MANIFEST.manifest_sha256,
  api_configured: false,
  onchain_transactions_sent: 0,
};
if (process.argv[2]) writeFileSync(process.argv[2], JSON.stringify(evidence, null, 2) + '\n');
console.log(JSON.stringify(evidence));
if (result.status !== 'DEGRADED_READ_ONLY' || result.provenance !== 'LIVE_DEVNET_READ_ONLY')
  process.exitCode = 1;
