import type { EnvironmentManifest } from './schema.ts';

export const LOCALNET_MANIFEST: EnvironmentManifest = Object.freeze({
  environment: 'LOCALNET', network: 'solana:localnet',
  genesis_hash: 'HP9XKTusRPGC78EFDpR9xdEq6simL2vqyDdrMvn6Vacg',
  rpc_endpoint: 'http://127.0.0.1:8899',
  api_endpoint: 'http://127.0.0.1:5173',
  program_id: 'CeA1P1NSuPLUH31KsT4j3pZeBsknQZ3NSC6GUAqcsCLy',
  idl_sha256: '73d2f8b0e5184229deae81d08ba5742765f4bc2ba21f325d0da223f765fa5c98',
  token_mint: 'HTHpns7gqLAhSBhAzqxhYdyHv9HeXkkRW6aHQfdUjL1G',
  token_program: 'TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA',
  token_decimals: 6, manifest_version: 1,
  manifest_sha256: '22e026a55a0b0e0f30ef5f1530fcfe4eb18386657cf4fdbf4ef0393308800f9b', provenance: 'LOCALNET_FIXTURE',
});

import { DEVNET_MANIFEST } from './devnet-manifest.ts';
export { DEVNET_MANIFEST };

export function selectEnvironment(target: string): EnvironmentManifest {
  if (target === 'localnet') return LOCALNET_MANIFEST;
  if (target === 'devnet') return DEVNET_MANIFEST;
  throw new Error('MANIFEST_INVALID');
}
