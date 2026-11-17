export type Environment = 'LOCALNET' | 'DEVNET' | 'MAINNET';

export type EnvironmentManifest = Readonly<{
  environment: Exclude<Environment, 'MAINNET'>;
  network: string;
  genesis_hash: string;
  rpc_endpoint: string;
  api_endpoint: string;
  program_id: string;
  idl_sha256: string;
  token_mint: string;
  token_program: string;
  token_decimals: number;
  manifest_version: number;
  manifest_sha256: string;
  provenance: string;
}>;

const FIELDS = [
  'environment', 'network', 'genesis_hash', 'rpc_endpoint', 'api_endpoint',
  'program_id', 'idl_sha256', 'token_mint', 'token_program', 'token_decimals',
  'manifest_version', 'manifest_sha256', 'provenance',
] as const;
const SHA256 = /^[0-9a-f]{64}$/;
const ADDRESS = /^[1-9A-HJ-NP-Za-km-z]{32,44}$/;

export function parseManifest(value: unknown): EnvironmentManifest {
  if (!value || typeof value !== 'object' || Array.isArray(value))
    throw new Error('MANIFEST_INVALID');
  const row = value as Record<string, unknown>;
  if (Object.keys(row).sort().join('|') !== [...FIELDS].sort().join('|'))
    throw new Error('MANIFEST_INVALID');
  if (row.environment !== 'LOCALNET' && row.environment !== 'DEVNET')
    throw new Error('MANIFEST_INVALID');
  if (row.network !== `solana:${String(row.environment).toLowerCase()}` ||
      typeof row.genesis_hash !== 'string' || !ADDRESS.test(row.genesis_hash) ||
      typeof row.program_id !== 'string' || !ADDRESS.test(row.program_id) ||
      typeof row.token_mint !== 'string' || !ADDRESS.test(row.token_mint) ||
      row.token_program !== 'TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA' ||
      typeof row.idl_sha256 !== 'string' || !SHA256.test(row.idl_sha256) ||
      typeof row.manifest_sha256 !== 'string' || !SHA256.test(row.manifest_sha256) ||
      !Number.isInteger(row.token_decimals) || Number(row.token_decimals) < 0 ||
      Number(row.token_decimals) > 9 || row.manifest_version !== 1 ||
      (row.provenance !== 'LOCALNET_FIXTURE' && row.provenance !== 'CON35_CON36_VERIFIED'))
    throw new Error('MANIFEST_INVALID');
  for (const field of ['rpc_endpoint', 'api_endpoint'] as const) {
    if (typeof row[field] !== 'string') throw new Error('MANIFEST_INVALID');
  }
  if (row.environment === 'DEVNET') {
    if (row.provenance !== 'CON35_CON36_VERIFIED' ||
        row.rpc_endpoint !== 'https://api.devnet.solana.com' ||
        row.api_endpoint !== 'https://conatus-devnet-staging.pages.dev/api')
      throw new Error('MANIFEST_INVALID');
  } else if (row.provenance !== 'LOCALNET_FIXTURE' ||
             row.rpc_endpoint !== 'http://127.0.0.1:8899' ||
             row.api_endpoint !== 'http://127.0.0.1:5173') {
    throw new Error('MANIFEST_INVALID');
  }
  return row as EnvironmentManifest;
}
