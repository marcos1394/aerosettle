import { APPROVED } from './trust.ts';
import { verifyManifest } from './manifest.ts';
import type { EnvironmentManifest } from './schema.ts';

const LOADER = 'BPFLoaderUpgradeab1e11111111111111111111111';
const ALPHABET = '123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz';
function base58(bytes: Uint8Array): string {
  let number = 0n;
  for (const byte of bytes) number = (number << 8n) + BigInt(byte);
  let result = '';
  while (number > 0n) {
    result = ALPHABET[Number(number % 58n)] + result;
    number /= 58n;
  }
  for (const byte of bytes) {
    if (byte !== 0) break;
    result = '1' + result;
  }
  return result;
}
type Account = { executable: boolean; owner: string; data: [string, string] };
export type VerificationStatus = 'VERIFYING' | 'VERIFIED' | 'DEGRADED_READ_ONLY' |
  'UNAVAILABLE' | 'NETWORK_MISMATCH' | 'MANIFEST_INVALID';
export type Verification = { status: VerificationStatus; reason: string; genesis?: string;
  service?: string; observedAt: string; provenance: 'LIVE_DEVNET_READ_ONLY' | 'LOCALNET' | 'UNVERIFIABLE' };
export type Rpc = (method: string, params: unknown[], signal?: AbortSignal) => Promise<unknown>;
export type ApiHealth = () => Promise<{ status: string; genesis: string; service: string; program_id: string }>;

export function assertEndpointBinding(manifest: EnvironmentManifest,
  rpcEndpoint: string, apiEndpoint: string): void {
  if (rpcEndpoint !== manifest.rpc_endpoint || apiEndpoint !== manifest.api_endpoint)
    throw new Error('API_RPC_ENDPOINT_MISMATCH');
}

function decode(account: Account): Uint8Array {
  if (!Array.isArray(account.data) || account.data[1] !== 'base64' || typeof account.data[0] !== 'string')
    throw new Error('INCOMPLETE_RPC');
  return Uint8Array.from(atob(account.data[0]), (char) => char.charCodeAt(0));
}

function accountOf(value: unknown): Account | null {
  if (!value || typeof value !== 'object') throw new Error('INCOMPLETE_RPC');
  const account = (value as { value?: unknown }).value;
  if (account === null) return null;
  if (!account || typeof account !== 'object') throw new Error('INCOMPLETE_RPC');
  const row = account as Account;
  if (typeof row.owner !== 'string' || typeof row.executable !== 'boolean') throw new Error('INCOMPLETE_RPC');
  return row;
}

export async function verifyEnvironmentCore(manifest: EnvironmentManifest, idlText: string,
  rpc: Rpc, api: ApiHealth | undefined, signal: AbortSignal | undefined,
  verify: (value: unknown, idlText: string) => Promise<EnvironmentManifest>): Promise<Verification> {
  const observedAt = new Date().toISOString();
  const unavailable = (reason: string): Verification => ({ status: 'UNAVAILABLE', reason,
    observedAt, provenance: 'UNVERIFIABLE' });
  try { await verify(manifest, idlText); }
  catch { return { ...unavailable('MANIFEST_INVALID'), status: 'MANIFEST_INVALID' }; }
  try {
    const genesis = await rpc('getGenesisHash', [], signal);
    if (signal?.aborted) return unavailable('REQUEST_ABORTED');
    if (genesis !== manifest.genesis_hash)
      return { ...unavailable('GENESIS_MISMATCH'), status: 'NETWORK_MISMATCH' };
    const [programResult, mintResult] = await Promise.all([
      rpc('getAccountInfo', [manifest.program_id, { encoding: 'base64', commitment: 'finalized' }], signal),
      rpc('getAccountInfo', [manifest.token_mint, { encoding: 'base64', commitment: 'finalized' }], signal),
    ]);
    if (signal?.aborted) return unavailable('REQUEST_ABORTED');
    const program = accountOf(programResult);
    const mint = accountOf(mintResult);
    if (!program || !mint) return unavailable('ACCOUNT_MISSING');
    if (!program.executable || program.owner !== LOADER ||
        mint.executable || mint.owner !== manifest.token_program)
      return { ...unavailable('ACCOUNT_IDENTITY_MISMATCH'), status: 'NETWORK_MISMATCH' };
    const programBytes = decode(program);
    const mintBytes = decode(mint);
    if (programBytes.length < 36 || programBytes[0] !== 2 || programBytes[1] !== 0 ||
        programBytes[2] !== 0 || programBytes[3] !== 0 ||
        mintBytes.length !== 82 || mintBytes[44] !== manifest.token_decimals || mintBytes[45] !== 1)
      return { ...unavailable('ACCOUNT_DATA_MISMATCH'), status: 'NETWORK_MISMATCH' };
    if (manifest.environment === 'DEVNET') {
      const approved = APPROVED.DEVNET;
      if (mintBytes[0] !== 1 || mintBytes[1] !== 0 || mintBytes[2] !== 0 ||
          mintBytes[3] !== 0 || base58(mintBytes.slice(4, 36)) !== approved.mint_authority ||
          mintBytes[46] !== 0 || mintBytes[47] !== 0 ||
          mintBytes[48] !== 0 || mintBytes[49] !== 0)
        return { ...unavailable('MINT_AUTHORITY_MISMATCH'), status: 'NETWORK_MISMATCH' };
      const programDataAddress = base58(programBytes.slice(4, 36));
      if (programDataAddress !== approved.program_data)
        return { ...unavailable('PROGRAM_DATA_MISMATCH'), status: 'NETWORK_MISMATCH' };
      const data = accountOf(await rpc('getAccountInfo', [programDataAddress,
        { encoding: 'base64', commitment: 'finalized' }], signal));
      if (signal?.aborted) return unavailable('REQUEST_ABORTED');
      if (!data || data.owner !== LOADER || data.executable)
        return { ...unavailable('PROGRAM_DATA_MISSING'), status: 'NETWORK_MISMATCH' };
      const bytes = decode(data);
      if (bytes.length < 45 || bytes[0] !== 3 || bytes[1] !== 0 || bytes[2] !== 0 ||
          bytes[3] !== 0 || bytes[12] !== 1 ||
          base58(bytes.slice(13, 45)) !== approved.upgrade_authority)
        return { ...unavailable('UPGRADE_AUTHORITY_MISMATCH'), status: 'NETWORK_MISMATCH' };
    }
    const provenance = manifest.environment === 'DEVNET' ? 'LIVE_DEVNET_READ_ONLY' : 'LOCALNET';
    if (!api || manifest.api_endpoint === 'API_NOT_CONFIGURED')
      return { status: 'DEGRADED_READ_ONLY', reason: manifest.api_endpoint === 'API_NOT_CONFIGURED'
        ? 'API_NOT_CONFIGURED' : 'API_UNAVAILABLE', genesis: String(genesis),
        observedAt, provenance };
    let health;
    try { health = await api(); }
    catch { return { status: 'DEGRADED_READ_ONLY', reason: 'API_UNAVAILABLE',
      genesis: String(genesis), observedAt, provenance }; }
    if (signal?.aborted) return unavailable('REQUEST_ABORTED');
    if (health.status === 'stale' || health.status === 'unready')
      return { status: 'DEGRADED_READ_ONLY', reason: 'INDEX_STALE',
        genesis: String(genesis), observedAt, provenance };
    if (health.status !== 'ok' || health.genesis !== genesis || health.program_id !== manifest.program_id)
      return { ...unavailable('API_RPC_MISMATCH'), status: 'NETWORK_MISMATCH' };
    return { status: 'VERIFIED', reason: 'RPC_AND_API_VERIFIED', genesis: String(genesis),
      service: health.service, observedAt, provenance };
  } catch (cause) {
    return unavailable(cause instanceof Error ? cause.message : 'RPC_UNAVAILABLE');
  }
}

export async function verifyEnvironment(manifest: EnvironmentManifest, idlText: string,
  rpc: Rpc, api?: ApiHealth, signal?: AbortSignal): Promise<Verification> {
  return verifyEnvironmentCore(manifest, idlText, rpc, api, signal, verifyManifest);
}

export function createRpc(endpoint: string, fetcher: typeof fetch = fetch): Rpc {
  let counter = 0;
  return async (method, params, signal) => {
    const id = ++counter;
    const boundedSignal = signal
      ? AbortSignal.any([signal, AbortSignal.timeout(12_000)])
      : AbortSignal.timeout(12_000);
    const response = await fetcher(endpoint, { method: 'POST', cache: 'no-store', signal: boundedSignal,
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ jsonrpc: '2.0', id, method, params }) });
    if (!response.ok) throw new Error('RPC_UNAVAILABLE');
    const body = await response.json() as { id?: number; error?: unknown; result?: unknown };
    if (body.id !== id || body.error || body.result === undefined) throw new Error('INCOMPLETE_RPC');
    return body.result;
  };
}
