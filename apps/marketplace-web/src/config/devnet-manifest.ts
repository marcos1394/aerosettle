import type { EnvironmentManifest } from './schema.ts';

export const DEVNET_MANIFEST: EnvironmentManifest = Object.freeze({
  environment: 'DEVNET', network: 'solana:devnet',
  genesis_hash: 'EtWTRABZaYq6iMfeYKouRu166VU2xqa1wcaWoxPkrZBG',
  rpc_endpoint: 'https://api.devnet.solana.com',
  api_endpoint: 'https://conatus-devnet-staging.pages.dev/api',
  program_id: 'CeA1P1NSuPLUH31KsT4j3pZeBsknQZ3NSC6GUAqcsCLy',
  idl_sha256: 'a6e436aa1c6468b4f518b742e40a2664e38dcdf7bc1419e53e1624444888e15d',
  token_mint: 'HpfaV9oRuTN1b3ktDKvJoWqUWFZ1o9VFmhejxxqQ1vyh',
  token_program: 'TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA',
  token_decimals: 6, manifest_version: 1,
  manifest_sha256: '059c968875c41036186dc79e203a60de60724e0496e7ac1ea3af61c24d902203', provenance: 'CON35_CON36_VERIFIED',
});
