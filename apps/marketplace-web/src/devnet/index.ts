import { DEVNET_MANIFEST } from '../config/devnet-manifest.ts';
import { APPROVED } from '../config/trust.ts';

export type Ready = { status: string; genesis?: string; program_id?: string;
  snapshot_sha256?: string; expires_at?: string; source?: string };
export type Row = Record<string, unknown>;
export type SnapshotProvenance = {
  network: 'solana:devnet'; genesis_hash: string; program_id: string;
  idl_sha256: string; binary_sha256: string; deployment_id: string;
  mint: string; mint_authority: string; token_program: string; mint_decimals: number;
  commitment: 'finalized'; slot_min: number; slot_max: number; observed_slot: number;
  generated_at: string; expires_at: string; snapshot_sha256: string;
  provenance: 'RELEASE_BOUND_RPC_SNAPSHOT'; provider: string;
};
type Page = { data?: unknown; provenance?: Partial<SnapshotProvenance>;
  advisory_only?: boolean; is_financial_authority?: boolean; is_executable?: boolean };
export interface DevnetIndex {
  agents: Row[];
  workorders: Row[];
  agentCount: number;
  workorderCount: number;
  snapshotSha: string;
  expiresAt: string;
  provenance: SnapshotProvenance;
}
const BINARY_SHA256 = '6cf3412c55c38e91b2ba0039aea24d58782c5db0d18759ffdab1c88788cdc3a2';
const DEPLOYMENT_ID = '06c7dfa7528460969a5ca1e8bd001f9c9f1f1f0df3d69fe36649e413e0b14ae6';

function object(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === 'object' && !Array.isArray(value);
}
function validTime(value: unknown): value is string {
  return typeof value === 'string' && Number.isFinite(Date.parse(value));
}
export function validatePage(body: unknown, ready: Ready,
  expected?: SnapshotProvenance): { data: unknown; provenance: SnapshotProvenance } {
  if (!object(body)) throw Error('INDEX_PROVENANCE_INVALID');
  const page = body as Page;
  const p = page.provenance;
  if (!p || p.network !== DEVNET_MANIFEST.network ||
      p.genesis_hash !== DEVNET_MANIFEST.genesis_hash ||
      p.program_id !== DEVNET_MANIFEST.program_id ||
      p.idl_sha256 !== DEVNET_MANIFEST.idl_sha256 ||
      p.binary_sha256 !== BINARY_SHA256 || p.deployment_id !== DEPLOYMENT_ID ||
      p.mint !== DEVNET_MANIFEST.token_mint ||
      p.mint_authority !== APPROVED.DEVNET.mint_authority ||
      p.token_program !== DEVNET_MANIFEST.token_program ||
      p.mint_decimals !== DEVNET_MANIFEST.token_decimals ||
      p.snapshot_sha256 !== ready.snapshot_sha256 || p.expires_at !== ready.expires_at ||
      p.commitment !== 'finalized' || p.provenance !== 'RELEASE_BOUND_RPC_SNAPSHOT' ||
      p.provider !== 'official-devnet' || !Number.isSafeInteger(p.slot_min) ||
      !Number.isSafeInteger(p.slot_max) || !Number.isSafeInteger(p.observed_slot) ||
      p.slot_min! < 0 || p.slot_min! > p.slot_max! || p.slot_max! > p.observed_slot! ||
      !validTime(p.generated_at) || !validTime(p.expires_at) ||
      Date.parse(p.generated_at) >= Date.parse(p.expires_at) ||
      Date.parse(p.expires_at) <= Date.now() ||
      Date.parse(p.expires_at) - Date.parse(p.generated_at) > 86_400_000 ||
      page.advisory_only !== true || page.is_financial_authority !== false ||
      page.is_executable !== false ||
      (expected && (p.snapshot_sha256 !== expected.snapshot_sha256 ||
        p.slot_min !== expected.slot_min || p.slot_max !== expected.slot_max ||
        p.generated_at !== expected.generated_at || p.observed_slot !== expected.observed_slot)))
    throw Error('INDEX_PROVENANCE_INVALID');
  return { data: page.data, provenance: p as SnapshotProvenance };
}

export async function fetchReady(fetcher: typeof fetch = fetch, signal?: AbortSignal): Promise<Ready> {
  const response = await fetcher(`${DEVNET_MANIFEST.api_endpoint}/ready`,
    { cache: 'no-store', signal });
  const body = await response.json() as Ready;
  if (response.status === 503 && (body.status === 'stale' || body.status === 'unready'))
    return body;
  if (!response.ok || body.status !== 'ready' || body.genesis !== DEVNET_MANIFEST.genesis_hash ||
      body.program_id !== DEVNET_MANIFEST.program_id ||
      !/^[a-f0-9]{64}$/.test(body.snapshot_sha256 ?? '') ||
      body.source !== 'RELEASE_BOUND_RPC_SNAPSHOT' ||
      !validTime(body.expires_at) || Date.parse(body.expires_at) <= Date.now())
    throw Error('API_IDENTITY_MISMATCH');
  return body;
}

export async function fetchIndex(ready: Ready, fetcher: typeof fetch = fetch,
  signal?: AbortSignal): Promise<DevnetIndex> {
  if (ready.status !== 'ready') throw Error('INDEX_NOT_READY');
  const base = DEVNET_MANIFEST.api_endpoint;
  const load = async (kind: 'agents' | 'workorders', expected?: SnapshotProvenance) => {
    const items: Row[] = [];
    const seen = new Set<string>();
    let cursor: string | null = null;
    let total = -1;
    let provenance = expected;
    for (let pageNumber = 0; pageNumber < 10; pageNumber += 1) {
      const query = new URLSearchParams({ limit: '50' });
      if (cursor) query.set('cursor', cursor);
      const response = await fetcher(`${base}/v1/${kind}?${query}`, { cache: 'no-store', signal });
      if (!response.ok) throw Error('INDEX_UNAVAILABLE');
      const page = validatePage(await response.json(), ready, provenance);
      const data = page.data;
      if (!object(data) || !Array.isArray(data.items) ||
          !Number.isSafeInteger(data.total) || (data.total as number) < data.items.length ||
          (data.total as number) > 500 || data.items.length > 50 ||
          (total >= 0 && total !== data.total) ||
          (data.next_cursor !== null && typeof data.next_cursor !== 'string'))
        throw Error('INDEX_PROVENANCE_INVALID');
      total = data.total as number;
      provenance = page.provenance;
      items.push(...data.items as Row[]);
      if (items.length > total) throw Error('INDEX_PAGINATION_INCOMPLETE');
      const next = data.next_cursor as string | null;
      if (!next) {
        if (items.length !== total) throw Error('INDEX_PAGINATION_INCOMPLETE');
        return { items, total, provenance };
      }
      if (seen.has(next) || data.items.length === 0) throw Error('INDEX_PAGINATION_INCOMPLETE');
      seen.add(next);
      cursor = next;
    }
    throw Error('INDEX_PAGINATION_INCOMPLETE');
  };
  const agents = await load('agents');
  const workorders = await load('workorders', agents.provenance);
  return { agents: agents.items, workorders: workorders.items,
    agentCount: agents.total, workorderCount: workorders.total,
    snapshotSha: ready.snapshot_sha256!, expiresAt: ready.expires_at!,
    provenance: agents.provenance };
}

export async function fetchRecord(kind: 'agents' | 'workorders', pubkey: string,
  ready: Ready, expected: SnapshotProvenance, fetcher: typeof fetch = fetch,
  signal?: AbortSignal): Promise<Row> {
  if (!/^[1-9A-HJ-NP-Za-km-z]{32,44}$/.test(pubkey)) throw Error('INVALID_PUBKEY');
  const response = await fetcher(`${DEVNET_MANIFEST.api_endpoint}/v1/${kind}/${pubkey}`,
    { cache: 'no-store', signal });
  if (!response.ok) throw Error(response.status === 404 ? 'ACCOUNT_NOT_FOUND' : 'INDEX_UNAVAILABLE');
  const { data } = validatePage(await response.json(), ready, expected);
  const key = kind === 'agents' ? 'agent_account' : 'work_order_account';
  if (!object(data) || data[key] !== pubkey) throw Error('INDEX_RECORD_INVALID');
  return data;
}
