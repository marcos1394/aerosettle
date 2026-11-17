// Cloudflare Pages advanced-mode Function. The release packager replaces both sentinels.
// It serves only public, read-only Devnet account snapshots; it never calls Solana RPC.
const SNAPSHOT_JSON = __SNAPSHOT_JSON__;
const SNAPSHOT_SHA256 = '__SNAPSHOT_SHA256__';
const ORIGIN = 'https://conatus-devnet-staging.pages.dev';
const GENESIS = 'EtWTRABZaYq6iMfeYKouRu166VU2xqa1wcaWoxPkrZBG';
const PROGRAM = 'CeA1P1NSuPLUH31KsT4j3pZeBsknQZ3NSC6GUAqcsCLy';
const IDL = 'a6e436aa1c6468b4f518b742e40a2664e38dcdf7bc1419e53e1624444888e15d';
const BINARY = '6cf3412c55c38e91b2ba0039aea24d58782c5db0d18759ffdab1c88788cdc3a2';
const MINT = 'HpfaV9oRuTN1b3ktDKvJoWqUWFZ1o9VFmhejxxqQ1vyh';
const TOKEN = 'TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA';
const MINT_AUTHORITY = '4om6LcFXaZ2Wtbn3P2ZvvyqssXFQs1xjNmE2Fnj7mRHa';
const DEPLOYMENT = '06c7dfa7528460969a5ca1e8bd001f9c9f1f1f0df3d69fe36649e413e0b14ae6';
const ADDRESS = /^[1-9A-HJ-NP-Za-km-z]{32,44}$/;
const STATUS = {
  agents: new Set(['Active', 'OwnerSuspended', 'AdminSuspended', 'Revoked']),
  workorders: new Set(['Draft', 'Open', 'Claimed', 'Submitted', 'Verified', 'Settled', 'Cancelled', 'Expired']),
};
let verified;

function response(status, body, origin) {
  const headers = { 'Content-Type': 'application/json; charset=utf-8', 'Cache-Control': 'no-store',
    'X-Content-Type-Options': 'nosniff', 'Vary': 'Origin' };
  if (origin === ORIGIN) headers['Access-Control-Allow-Origin'] = ORIGIN;
  return new Response(JSON.stringify(body), { status, headers });
}

async function snapshot() {
  if (verified) return verified;
  const digest = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(SNAPSHOT_JSON));
  const actual = Array.from(new Uint8Array(digest), (byte) => byte.toString(16).padStart(2, '0')).join('');
  if (actual !== SNAPSHOT_SHA256) throw Error('SNAPSHOT_HASH_MISMATCH');
  const value = JSON.parse(SNAPSHOT_JSON);
  const meta = value.metadata;
  if (value.schema_version !== 1 || !meta || meta.network !== 'solana:devnet' ||
      meta.genesis_hash !== GENESIS || meta.program_id !== PROGRAM ||
      meta.idl_sha256 !== IDL || meta.binary_sha256 !== BINARY ||
      meta.deployment_id !== DEPLOYMENT || meta.mint !== MINT ||
      meta.token_program !== TOKEN || meta.mint_authority !== MINT_AUTHORITY ||
      meta.mint_decimals !== 6 ||
      meta.source_rpc !== 'https://api.devnet.solana.com' ||
      meta.commitment !== 'finalized' || meta.provenance !== 'RELEASE_BOUND_RPC_SNAPSHOT' ||
      meta.atomic_snapshot !== false || !Number.isInteger(meta.slot_min) ||
      !Number.isInteger(meta.slot_max) || meta.slot_min > meta.slot_max ||
      !Array.isArray(value.agents) || !Array.isArray(value.work_orders) ||
      value.agents.length !== meta.agent_count || value.work_orders.length !== meta.work_order_count ||
      value.agents.length > 500 || value.work_orders.length > 500 ||
      !Number.isFinite(Date.parse(meta.generated_at)) || !Number.isFinite(Date.parse(meta.expires_at)) ||
      Date.parse(meta.expires_at) <= Date.parse(meta.generated_at) ||
      Date.parse(meta.expires_at) - Date.parse(meta.generated_at) > 86_400_000)
    throw Error('SNAPSHOT_IDENTITY_INVALID');
  verified = value;
  return verified;
}

function decodeCursor(token, kind, status) {
  if (!token) return 0;
  if (token.length > 256 || !/^[A-Za-z0-9_-]+$/.test(token)) throw Error('INVALID_CURSOR');
  let decoded;
  try { decoded = JSON.parse(atob(token.replaceAll('-', '+').replaceAll('_', '/'))); }
  catch { throw Error('INVALID_CURSOR'); }
  if (decoded?.hash !== SNAPSHOT_SHA256 || decoded.kind !== kind || decoded.status !== status ||
      !Number.isInteger(decoded.offset) || decoded.offset < 0) throw Error('INVALID_CURSOR');
  return decoded.offset;
}

function encodeCursor(offset, kind, status) {
  return btoa(JSON.stringify({ hash: SNAPSHOT_SHA256, kind, status, offset }))
    .replaceAll('+', '-').replaceAll('/', '_').replaceAll('=', '');
}

export async function handle(request, now = Date.now()) {
  const origin = request.headers.get('Origin');
  if (origin && origin !== ORIGIN)
    return response(403, { error: { code: 'ORIGIN_NOT_ALLOWED' }, provenance_status: 'UNVERIFIABLE' });
  if (request.method !== 'GET')
    return response(405, { error: { code: 'METHOD_NOT_ALLOWED' }, provenance_status: 'UNVERIFIABLE' }, origin);
  const url = new URL(request.url);
  if (url.pathname === '/api/health' && !url.search)
    return response(200, { status: 'ok', service: 'con59-pages-read-only' }, origin);
  if (url.href.length > 2048 || url.searchParams.size > 3 ||
      Array.from(url.searchParams.keys()).some((key) => url.searchParams.getAll(key).length !== 1))
    return response(400, { error: { code: 'INVALID_QUERY' }, provenance_status: 'UNVERIFIABLE' }, origin);
  const match = url.pathname.match(/^\/api\/v1\/(network|program|agents|workorders)(?:\/([^/]+))?$/);
  if (url.pathname !== '/api/ready' && !match)
    return response(404, { error: { code: 'ROUTE_NOT_FOUND' }, provenance_status: 'UNVERIFIABLE' }, origin);
  let value;
  try { value = await snapshot(); }
  catch { return response(503, { status: 'unready', reason: 'SNAPSHOT_UNVERIFIABLE',
    provenance_status: 'INSUFFICIENT_DATA' }, origin); }
  const meta = value.metadata;
  if (now < Date.parse(meta.generated_at) - 300_000 || now >= Date.parse(meta.expires_at))
    return response(503, { status: 'stale', reason: 'SNAPSHOT_EXPIRED',
      expires_at: meta.expires_at, provenance_status: 'INSUFFICIENT_DATA' }, origin);
  if (url.pathname === '/api/ready') {
    if (url.search) return response(400, { error: { code: 'INVALID_QUERY' } }, origin);
    return response(200, { status: 'ready', genesis: GENESIS, program_id: PROGRAM,
      snapshot_sha256: SNAPSHOT_SHA256, source: meta.provenance, expires_at: meta.expires_at }, origin);
  }
  const [, resource, pubkey] = match;
  const allowed = resource === 'agents' || resource === 'workorders'
    ? pubkey ? [] : ['limit', 'cursor', 'status'] : [];
  if (Array.from(url.searchParams.keys()).some((key) => !allowed.includes(key)))
    return response(400, { error: { code: 'INVALID_QUERY' } }, origin);
  let data;
  if (resource === 'network') data = { network: meta.network, genesis_hash: GENESIS, status: 'snapshot' };
  else if (resource === 'program') data = { program_id: PROGRAM, idl_sha256: IDL,
    binary_sha256: BINARY, mint: MINT, deployment_id: DEPLOYMENT };
  else {
    const kind = resource === 'agents' ? 'agents' : 'work_orders';
    const key = resource === 'agents' ? 'agent_account' : 'work_order_account';
    if (pubkey) {
      if (!ADDRESS.test(pubkey)) return response(400, { error: { code: 'INVALID_PUBKEY' } }, origin);
      data = value[kind].find((row) => row[key] === pubkey);
      if (!data) return response(404, { error: { code: 'ACCOUNT_NOT_FOUND' } }, origin);
    } else {
      const status = url.searchParams.get('status');
      if (status && !STATUS[resource].has(status))
        return response(400, { error: { code: 'INVALID_FILTER' } }, origin);
      const textLimit = url.searchParams.get('limit') ?? '20';
      if (!/^[1-9][0-9]?$/.test(textLimit) || Number(textLimit) > 50)
        return response(400, { error: { code: 'INVALID_LIMIT' } }, origin);
      const records = value[kind].filter((row) => !status || row.status === status)
        .sort((a, b) => a[key] < b[key] ? -1 : a[key] > b[key] ? 1 : 0);
      let offset;
      try { offset = decodeCursor(url.searchParams.get('cursor'), resource, status); }
      catch { return response(400, { error: { code: 'INVALID_CURSOR' } }, origin); }
      if (offset > records.length) return response(400, { error: { code: 'INVALID_CURSOR' } }, origin);
      const end = offset + Number(textLimit);
      data = { items: records.slice(offset, end), next_cursor: end < records.length
        ? encodeCursor(end, resource, status) : null, total: records.length };
    }
  }
  return response(200, { data, provenance: { ...meta, snapshot_sha256: SNAPSHOT_SHA256 },
    advisory_only: true, is_financial_authority: false, is_executable: false }, origin);
}

export default { async fetch(request, env) {
  if (!new URL(request.url).pathname.startsWith('/api/')) return env.ASSETS.fetch(request);
  return handle(request);
} };
