import { useCallback, useEffect, useRef, useState } from 'react';
import { DEVNET_MANIFEST } from '../config/environments.ts';
import { createRpc, verifyEnvironment, type Verification } from '../config/verify.ts';
import { VerificationSession } from '../config/session.ts';

const RPC = createRpc(DEVNET_MANIFEST.rpc_endpoint);
const initial: Verification = { status: 'VERIFYING', reason: 'CHECKING_RPC',
  observedAt: '', provenance: 'UNVERIFIABLE' };

export function DevnetReadOnlyApp() {
  const [verification, setVerification] = useState<Verification>(initial);
  const [revision, setRevision] = useState(0);
  const session = useRef(new VerificationSession<Verification>());
  const reload = useCallback(() => setRevision((value) => value + 1), []);
  useEffect(() => {
    setVerification(initial);
    void session.current.run(DEVNET_MANIFEST.manifest_sha256, async (signal) => {
      try {
        const response = await fetch('/idl/devnet-idl.json', { cache: 'no-store', signal });
        if (!response.ok) throw new Error('IDL_UNAVAILABLE');
        const result = await verifyEnvironment(DEVNET_MANIFEST, await response.text(),
          RPC, undefined, signal);
        return result;
      } catch {
        return { ...initial, status: 'UNAVAILABLE', reason: 'IDL_UNAVAILABLE',
          observedAt: new Date().toISOString() } as Verification;
      }
    }, setVerification);
    return () => session.current.invalidate();
  }, [revision]);

  const identified = verification.provenance === 'LIVE_DEVNET_READ_ONLY';
  return <div className="devnet-app">
    <header className="devnet-header">
      <div className="devnet-brand">CONATUS <span> / SOLANA DEVNET</span></div>
      <span className="devnet-pill">Experimental network · Test assets only</span>
    </header>
    <main className="devnet-main">
      <p className="devnet-eyebrow">NETWORK PREVIEW / READ ONLY</p>
      <h1>Verifiable infrastructure.<br /><em>Carefully connected.</em></h1>
      <p className="devnet-lead">This Devnet preview reads the approved Conatus program and test mint.
        Wallet connection, signatures, WorkOrders and payments are disabled in this build.</p>
      <section className="devnet-card" aria-live="polite">
        <div className="devnet-card-heading"><div><small>Environment status</small>
          <h2>{verification.status.replaceAll('_', ' ')}</h2></div>
          <span className={identified ? 'devnet-indicator ready' : 'devnet-indicator'} />
        </div>
        <p>{identified
          ? 'Devnet RPC identity, executable program, upgrade authority and SPL test mint match the approved evidence. A Devnet Marketplace API is not configured yet.'
          : verification.status === 'VERIFYING'
            ? 'Checking the approved manifest and live Devnet RPC…'
            : `Devnet cannot be represented as verified: ${verification.reason}.`}</p>
        <div className="devnet-grid">
          <div><small>Data provenance</small><strong>{verification.provenance}</strong></div>
          <div><small>API</small><strong>API_NOT_CONFIGURED</strong></div>
          <div><small>Asset</small><strong>Devnet test token · 6 decimals</strong></div>
          <div><small>Financial actions</small><strong>Disabled</strong></div>
        </div>
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
      <p className="devnet-footnote">Agent catalog and economic history will appear after the Devnet read API is deployed and independently verified. No Localnet fixtures are shown here.</p>
    </main>
  </div>;
}
