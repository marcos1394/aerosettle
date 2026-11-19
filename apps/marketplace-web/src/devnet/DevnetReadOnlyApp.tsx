import { useCallback, useEffect, useRef, useState } from 'react';
import { DEVNET_MANIFEST } from '../config/environments.ts';
import { createRpc, verifyEnvironment, type Verification } from '../config/verify.ts';
import { VerificationSession } from '../config/session.ts';
import { stagingReadiness } from './readiness.ts';
import { fetchIndex, fetchReady, type DevnetIndex } from './index.ts';

const RPC = createRpc(DEVNET_MANIFEST.rpc_endpoint);
const initial: Verification = { status: 'VERIFYING', reason: 'CHECKING_RPC',
  observedAt: '', provenance: 'UNVERIFIABLE' };

export function DevnetReadOnlyApp() {
  const [verification, setVerification] = useState<Verification>(initial);
  const [index, setIndex] = useState<DevnetIndex>();
  const [revision, setRevision] = useState(0);
  const session = useRef(new VerificationSession<{ verification: Verification; index?: DevnetIndex }>());
  const reload = useCallback(() => setRevision((value) => value + 1), []);
  useEffect(() => {
    setVerification(initial);
    setIndex(undefined);
    void session.current.run(DEVNET_MANIFEST.manifest_sha256, async (signal) => {
      try {
        const response = await fetch('/idl/devnet-idl.json', { cache: 'no-store', signal });
        if (!response.ok) throw new Error('IDL_UNAVAILABLE');
        let ready: Awaited<ReturnType<typeof fetchReady>> | undefined;
        const result = await verifyEnvironment(DEVNET_MANIFEST, await response.text(),
          RPC, async () => {
            ready = await fetchReady(fetch, signal);
            return { status: ready.status === 'ready' ? 'ok' : ready.status,
              genesis: ready.genesis ?? '', program_id: ready.program_id ?? '',
              service: 'con59-pages-read-only' };
          }, signal);
        if (result.status !== 'VERIFIED' || !ready) return { verification: result };
        try { return { verification: result, index: await fetchIndex(ready, fetch, signal) }; }
        catch { return { verification: { ...result, status: 'DEGRADED_READ_ONLY',
          reason: 'INDEX_UNAVAILABLE' } as Verification }; }
      } catch {
        return { verification: { ...initial, status: 'UNAVAILABLE', reason: 'IDL_UNAVAILABLE',
          observedAt: new Date().toISOString() } as Verification };
      }
    }, (value) => { setVerification(value.verification); setIndex(value.index); });
    return () => session.current.invalidate();
  }, [revision]);

  const identified = verification.provenance === 'LIVE_DEVNET_READ_ONLY';
  const readiness = stagingReadiness(verification, Boolean(index));
  return <div className="devnet-app">
    <header className="devnet-header">
      <div className="devnet-brand">CONATUS <span> / SOLANA DEVNET</span></div>
      <span className="devnet-pill">Experimental network · Test assets only</span>
    </header>
    <main className="devnet-main">
      <p className="devnet-eyebrow">NETWORK PREVIEW / READ ONLY</p>
      <h1>Verifiable infrastructure.<br /><em>Carefully connected.</em></h1>
      <p className="devnet-lead">This Devnet preview reads the approved Conatus program, test mint,
        and a release-bound account snapshot. Wallet connection, signatures, WorkOrder actions and payments are disabled.</p>
      <section className="devnet-card" aria-live="polite">
        <div className="devnet-card-heading"><div><small>Environment status</small>
          <h2>{verification.status.replaceAll('_', ' ')}</h2></div>
          <span className={identified ? 'devnet-indicator ready' : 'devnet-indicator'} />
        </div>
        <p>{identified
          ? readiness.INDEX_FRESH
            ? 'Devnet RPC identity is verified. The public account index is a bounded snapshot from finalized RPC reads; it is not a live financial authority.'
            : `Devnet RPC identity is verified. The account index is unavailable or stale (${verification.reason}).`
          : verification.status === 'VERIFYING'
            ? 'Checking the approved manifest and live Devnet RPC…'
            : `Devnet cannot be represented as verified: ${verification.reason}.`}</p>
        <div className="devnet-grid">
          <div><small>Data provenance</small><strong>{verification.provenance}</strong></div>
          <div><small>API</small><strong>{readiness.API_VERIFIED ? 'API_VERIFIED' : readiness.API_UNAVAILABLE ? 'API_UNAVAILABLE' : 'API_UNVERIFIED'}</strong></div>
          <div><small>Index</small><strong>{readiness.INDEX_FRESH ? 'INDEX_FRESH' : readiness.INDEX_STALE ? 'INDEX_STALE' : 'INSUFFICIENT_DATA'}</strong></div>
          <div><small>Asset</small><strong>Devnet test token · 6 decimals</strong></div>
          <div><small>Financial actions</small><strong>Disabled</strong></div>
        </div>
        <p>Read-only preview readiness: {readiness.READY_FOR_READ_ONLY_PREVIEW
          ? 'READY_FOR_READ_ONLY_PREVIEW' : 'WAITING_FOR_RPC_VERIFICATION'}.
          Transactions: disabled.</p>
        {readiness.INDEX_FRESH && index && <section aria-label="Devnet public account index">
          <p>Public Devnet accounts at snapshot: {index.agentCount} agents, {index.workorderCount} WorkOrders.
            Expires {index.expiresAt}. Historical snapshot only.</p>
          <h3>Agents</h3><ul>{index.agents.map((row) => <li key={String(row.agent_account)}>
            <code>{String(row.agent_account)}</code> · {String(row.status)}</li>)}</ul>
          <h3>WorkOrders</h3><ul>{index.workorders.map((row) => <li key={String(row.work_order_account)}>
            <code>{String(row.work_order_account)}</code> · {String(row.status)}</li>)}</ul>
        </section>}
        <details><summary>Verification details</summary>
          <dl>
            <dt>Genesis</dt><dd>{verification.genesis ?? 'Unverified'}</dd>
            <dt>Program ID</dt><dd>{DEVNET_MANIFEST.program_id}</dd>
            <dt>Test mint</dt><dd>{DEVNET_MANIFEST.token_mint}</dd>
            <dt>Manifest SHA-256</dt><dd>{DEVNET_MANIFEST.manifest_sha256}</dd>
            <dt>Last checked</dt><dd>{verification.observedAt || 'In progress'}</dd>
          </dl>
        </details>
        <button type="button" onClick={reload}>Verify again</button>
      </section>
      <p className="devnet-footnote">The snapshot expires after 24 hours and is not a transaction history or balance. No Localnet fixtures are shown here.</p>
    </main>
  </div>;
}
