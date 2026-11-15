import { APPROVED } from './trust.ts';
import { parseManifest, type EnvironmentManifest } from './schema.ts';

export function canonical(value: Record<string, unknown>): string {
  return JSON.stringify(Object.fromEntries(Object.entries(value).sort(([a], [b]) => a.localeCompare(b))));
}

export async function sha256(value: string): Promise<string> {
  const bytes = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(value));
  return Array.from(new Uint8Array(bytes), (byte) => byte.toString(16).padStart(2, '0')).join('');
}

export async function verifyManifest(value: unknown, idlText: string): Promise<EnvironmentManifest> {
  const manifest = parseManifest(value);
  const approved = APPROVED[manifest.environment];
  if (manifest.program_id !== approved.program_id ||
      manifest.genesis_hash !== approved.genesis_hash ||
      manifest.idl_sha256 !== approved.idl_sha256 ||
      manifest.token_mint !== approved.mint ||
      manifest.manifest_sha256 !== approved.manifest_sha256)
    throw new Error('MANIFEST_INVALID');
  const { manifest_sha256: _, ...payload } = manifest;
  if (await sha256(canonical(payload)) !== manifest.manifest_sha256 ||
      await sha256(idlText) !== manifest.idl_sha256)
    throw new Error('MANIFEST_INVALID');
  let idl: unknown;
  try { idl = JSON.parse(idlText); } catch { throw new Error('MANIFEST_INVALID'); }
  if (!idl || typeof idl !== 'object' || (idl as { address?: unknown }).address !== manifest.program_id)
    throw new Error('MANIFEST_INVALID');
  return manifest;
}
