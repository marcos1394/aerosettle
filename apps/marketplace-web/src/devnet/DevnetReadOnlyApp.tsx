import { useEffect, useState } from 'react';
import { Link } from 'react-router';
import { useCopy } from './i18n.tsx';
import { DEVNET_MANIFEST } from '../config/devnet-manifest.ts';
import { PageHeader } from './ui.tsx';
import { useDevnetData } from './DevnetDataProvider.tsx';
import { validatePage } from './index.ts';
import { stagingReadiness } from './readiness.ts';

export function DevnetReadOnlyApp() {
  const c = useCopy();
  const { catalog, ready, verification, reload } = useDevnetData();
  const [supplement, setSupplement] = useState<'VERIFYING' | 'VERIFIED' | 'UNAVAILABLE'>('VERIFYING');
  useEffect(() => {
    setSupplement('VERIFYING');
    if (!catalog || !ready) return;
    const controller = new AbortController();
    void Promise.all(['network', 'program'].map(async (kind) => {
      const response = await fetch(`${DEVNET_MANIFEST.api_endpoint}/v1/${kind}`,
        { cache: 'no-store', signal: controller.signal });
      if (!response.ok) throw Error('STATUS_API_UNAVAILABLE');
      return validatePage(await response.json(), ready, catalog.provenance).data;
    })).then(([network, program]) => {
      if (!network || typeof network !== 'object' || !program || typeof program !== 'object')
        throw Error('STATUS_IDENTITY_INVALID');
      const n = network as Record<string, unknown>;
      const p = program as Record<string, unknown>;
      if (n.network !== DEVNET_MANIFEST.network || n.genesis_hash !== DEVNET_MANIFEST.genesis_hash ||
          n.status !== 'snapshot' ||
          p.program_id !== DEVNET_MANIFEST.program_id || p.idl_sha256 !== DEVNET_MANIFEST.idl_sha256 ||
          p.binary_sha256 !== catalog.provenance.binary_sha256 ||
          p.deployment_id !== catalog.provenance.deployment_id ||
          p.mint !== DEVNET_MANIFEST.token_mint) throw Error('STATUS_IDENTITY_INVALID');
      if (!controller.signal.aborted) setSupplement('VERIFIED');
    }).catch(() => { if (!controller.signal.aborted) setSupplement('UNAVAILABLE'); });
    return () => controller.abort();
  }, [catalog, ready]);
  const readiness = stagingReadiness(verification, Boolean(catalog));
  return <div className="devnet-status-page">
    <PageHeader eyebrow={c('NETWORK / DIAGNOSTICS', 'RED / DIAGNÓSTICO')}
      title={c('Verification status', 'Estado de verificación')}
      description={c('Technical evidence for the read-only Devnet preview.',
        'Evidencia técnica de la vista Devnet de solo lectura.')} />
    <section className="devnet-card" aria-live="polite">
      <div className="devnet-card-heading"><div><small>{c('Environment status', 'Estado del entorno')}</small>
        <h2>{verification.status.replaceAll('_', ' ')}</h2></div>
        <span className={catalog ? 'devnet-indicator ready' : 'devnet-indicator'} aria-hidden="true" /></div>
      <p>{catalog ? c('RPC identity and the release-bound finalized account index are verified. This is an advisory snapshot, not a financial authority.',
        'La identidad RPC y el índice finalizado vinculado al release están verificados. Es una instantánea informativa, no autoridad financiera.') :
        c('The current account index cannot be shown as verified. The landing and navigation remain available.',
          'El índice actual no puede mostrarse como verificado. La landing y la navegación siguen disponibles.')}</p>
      <div className="devnet-grid">
        <div><small>RPC</small><strong>{readiness.RPC_VERIFIED ? 'RPC_VERIFIED' : verification.status}</strong></div>
        <div><small>API</small><strong>{catalog ? 'API_VERIFIED' : 'API_UNAVAILABLE'}</strong></div>
        <div><small>{c('Index', 'Índice')}</small><strong>{catalog ? 'INDEX_FRESH' : verification.reason === 'INDEX_STALE' ? 'INDEX_STALE' : 'INSUFFICIENT_DATA'}</strong></div>
        <div><small>{c('Network/program routes', 'Rutas de red/programa')}</small><strong>{catalog ? supplement : 'UNAVAILABLE'}</strong></div>
        <div><small>{c('Financial actions', 'Acciones financieras')}</small><strong>DISABLED</strong></div>
        <div><small>{c('Transactions', 'Transacciones')}</small><strong>READY_FOR_TRANSACTIONS=false</strong></div>
      </div>
      <dl className="devnet-status-facts">
        <dt>Network</dt><dd>{DEVNET_MANIFEST.network}</dd>
        <dt>Genesis</dt><dd>{verification.genesis ?? 'UNVERIFIABLE'}</dd>
        <dt>Program ID</dt><dd>{DEVNET_MANIFEST.program_id}</dd>
        <dt>IDL SHA-256</dt><dd>{DEVNET_MANIFEST.idl_sha256}</dd>
        <dt>Manifest SHA-256</dt><dd>{DEVNET_MANIFEST.manifest_sha256}</dd>
        <dt>Test mint</dt><dd>{DEVNET_MANIFEST.token_mint}</dd>
        <dt>Snapshot SHA-256</dt><dd>{catalog?.snapshotSha ?? 'INSUFFICIENT_DATA'}</dd>
        <dt>Commitment</dt><dd>{catalog?.provenance.commitment ?? 'UNVERIFIABLE'}</dd>
        <dt>Slots</dt><dd>{catalog ? `${catalog.provenance.slot_min}–${catalog.provenance.slot_max}` : 'UNVERIFIABLE'}</dd>
        <dt>Observed</dt><dd>{(catalog?.provenance.generated_at ?? verification.observedAt) || 'UNVERIFIABLE'}</dd>
        <dt>Expires</dt><dd>{catalog?.expiresAt ?? 'UNVERIFIABLE'}</dd>
        <dt>Provenance</dt><dd>{catalog?.provenance.provenance ?? 'INSUFFICIENT_DATA'}</dd>
        <dt>Reason</dt><dd>{verification.reason}</dd>
      </dl>
      <div className="devnet-inline-actions"><button onClick={reload}>{c('Verify again', 'Verificar de nuevo')}</button>
        <Link className="button" to="/">{c('Back to marketplace', 'Volver al mercado')}</Link></div>
    </section>
    <p className="devnet-footnote">{c('The snapshot is bounded to 24 hours and is not a transaction history, balance or proof of agent hardware.',
      'La instantánea dura hasta 24 horas y no es un historial de transacciones, balance ni prueba del hardware de un agente.')}</p>
  </div>;
}
