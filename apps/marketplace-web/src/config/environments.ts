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

export const DEVNET_MANIFEST: EnvironmentManifest = Object.freeze({
  environment: 'DEVNET', network: 'solana:devnet',
  genesis_hash: 'EtWTRABZaYq6iMfeYKouRu166VU2xqa1wcaWoxPkrZBG',
  rpc_endpoint: 'https://api.devnet.solana.com', api_endpoint: 'API_NOT_CONFIGURED',
  program_id: 'CeA1P1NSuPLUH31KsT4j3pZeBsknQZ3NSC6GUAqcsCLy',
  idl_sha256: 'a6e436aa1c6468b4f518b742e40a2664e38dcdf7bc1419e53e1624444888e15d',
  token_mint: 'HpfaV9oRuTN1b3ktDKvJoWqUWFZ1o9VFmhejxxqQ1vyh',
  token_program: 'TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA',
  token_decimals: 6, manifest_version: 1,
  manifest_sha256: 'db8d0bf22b0e9102d9464d9f35c6732a8e0e9e444fe459ead4a75a1fc8469592', provenance: 'CON35_CON36_VERIFIED',
});

export function selectEnvironment(target: string): EnvironmentManifest {
  if (target === 'localnet') return LOCALNET_MANIFEST;
  if (target === 'devnet') return DEVNET_MANIFEST;
  throw new Error('MANIFEST_INVALID');
}
