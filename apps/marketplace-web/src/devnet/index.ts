import { DEVNET_MANIFEST } from '../config/environments.ts';

type Ready = { status: string; genesis?: string; program_id?: string;
  snapshot_sha256?: string; expires_at?: string; source?: string };
type Row = Record<string, unknown>;
type Page = { data?: { items?: Row[]; total?: number; next_cursor?: string | null };
  provenance?: { genesis_hash?: string; program_id?: string; idl_sha256?: string;
    binary_sha256?: string; mint?: string; token_program?: string; mint_decimals?: number;
    snapshot_sha256?: string; expires_at?: string; provenance?: string };
  advisory_only?: boolean; is_financial_authority?: boolean; is_executable?: boolean };

export interface DevnetIndex {
  agents: Row[];
  workorders: Row[];
  agentCount: number;
  workorderCount: number;
  snapshotSha: string;
  expiresAt: string;
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
      !body.expires_at || Date.parse(body.expires_at) <= Date.now())
    throw Error('API_IDENTITY_MISMATCH');
  return body;
}

export async function fetchIndex(ready: Ready, fetcher: typeof fetch = fetch,
  signal?: AbortSignal): Promise<DevnetIndex> {
  if (ready.status !== 'ready') throw Error('INDEX_NOT_READY');
  const base = DEVNET_MANIFEST.api_endpoint;
  const load = async (kind: 'agents' | 'workorders') => {
    const response = await fetcher(`${base}/v1/${kind}?limit=50`, { cache: 'no-store', signal });
    if (!response.ok) throw Error('INDEX_UNAVAILABLE');
    const page = await response.json() as Page;
    const provenance = page.provenance;
    if (!provenance || provenance.genesis_hash !== DEVNET_MANIFEST.genesis_hash ||
        provenance.program_id !== DEVNET_MANIFEST.program_id ||
        provenance.idl_sha256 !== DEVNET_MANIFEST.idl_sha256 ||
        provenance.binary_sha256 !== '6cf3412c55c38e91b2ba0039aea24d58782c5db0d18759ffdab1c88788cdc3a2' ||
        provenance.mint !== DEVNET_MANIFEST.token_mint ||
        provenance.token_program !== DEVNET_MANIFEST.token_program ||
        provenance.mint_decimals !== DEVNET_MANIFEST.token_decimals ||
        provenance.snapshot_sha256 !== ready.snapshot_sha256 ||
        provenance.expires_at !== ready.expires_at ||
        provenance.provenance !== 'RELEASE_BOUND_RPC_SNAPSHOT' ||
        Date.parse(provenance.expires_at ?? '') <= Date.now() ||
        page.advisory_only !== true || page.is_financial_authority !== false ||
        page.is_executable !== false || !Array.isArray(page.data?.items) ||
        !Number.isInteger(page.data.total) || (page.data.total ?? 0) < page.data.items.length)
      throw Error('INDEX_PROVENANCE_INVALID');
    return page.data;
  };
  const [agents, workorders] = await Promise.all([load('agents'), load('workorders')]);
  return { agents: agents.items!, workorders: workorders.items!,
    agentCount: agents.total!, workorderCount: workorders.total!,
    snapshotSha: ready.snapshot_sha256!, expiresAt: ready.expires_at! };
}
