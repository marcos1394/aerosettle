import { DEVNET_MANIFEST } from './devnet-manifest.ts';
import { APPROVED } from './trust.ts';
import type { EnvironmentManifest } from './schema.ts';

export async function verifyDevnetManifest(value: unknown,
  idlText: string): Promise<EnvironmentManifest> {
  if (!value || typeof value !== 'object' || Array.isArray(value))
    throw Error('MANIFEST_INVALID');
  const row = value as Record<string, unknown>;
  const pinned = DEVNET_MANIFEST as unknown as Record<string, unknown>;
  if (Object.keys(row).sort().join('|') !== Object.keys(pinned).sort().join('|') ||
      Object.entries(pinned).some(([key, expected]) => row[key] !== expected) ||
      row.environment !== 'DEVNET' || row.network !== 'solana:devnet' ||
      row.program_id !== APPROVED.DEVNET.program_id ||
      row.genesis_hash !== APPROVED.DEVNET.genesis_hash ||
      row.token_mint !== APPROVED.DEVNET.mint ||
      row.idl_sha256 !== APPROVED.DEVNET.idl_sha256 ||
      row.manifest_sha256 !== APPROVED.DEVNET.manifest_sha256 ||
      row.rpc_endpoint !== 'https://api.devnet.solana.com' ||
      row.api_endpoint !== 'https://conatus-devnet-staging.pages.dev/api')
    throw Error('MANIFEST_INVALID');
  const { manifest_sha256: _, ...payload } = row;
  const hash = async (input: string) => Array.from(new Uint8Array(await crypto.subtle.digest(
    'SHA-256', new TextEncoder().encode(input))), (byte) => byte.toString(16).padStart(2, '0')).join('');
  const canonical = JSON.stringify(Object.fromEntries(Object.entries(payload)
    .sort(([a], [b]) => a.localeCompare(b))));
  if (await hash(canonical) !== row.manifest_sha256 ||
      await hash(idlText) !== row.idl_sha256) throw Error('MANIFEST_INVALID');
  let idl: unknown;
  try { idl = JSON.parse(idlText); } catch { throw Error('MANIFEST_INVALID'); }
  if (!idl || typeof idl !== 'object' || (idl as { address?: unknown }).address !== row.program_id)
    throw Error('MANIFEST_INVALID');
  return row as EnvironmentManifest;
}
