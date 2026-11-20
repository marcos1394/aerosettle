import { useEffect, useState } from 'react';
import { Link, useParams } from 'react-router';
import { useCopy } from '../i18n.tsx';
import { Icon, PageHeader } from '../ui.tsx';
import { useDevnetData } from '../DevnetDataProvider.tsx';
import { explorerUrl, parseAgent, type VerifiedAgent } from '../catalog.ts';
import { fetchRecord } from '../index.ts';
import { Address, CapabilityChips, CatalogNotice, ProofBadge } from './common.tsx';

export default function AgentDetail() {
  const c = useCopy();
  const { pubkey = '' } = useParams();
  const { catalog, ready } = useDevnetData();
  const [record, setRecord] = useState<VerifiedAgent>();
  const [error, setError] = useState('');
  useEffect(() => {
    setRecord(undefined); setError('');
    if (!catalog || !ready) return;
    const listed = catalog.agents.find((agent) => agent.agent_account === pubkey);
    if (!listed) { setError('ACCOUNT_NOT_INDEXED'); return; }
    const controller = new AbortController();
    void fetchRecord('agents', pubkey, ready, catalog.provenance, fetch, controller.signal)
      .then((row) => {
        const detail = parseAgent(row);
        if (JSON.stringify(detail) !== JSON.stringify(listed)) throw Error('DETAIL_LIST_MISMATCH');
        if (!controller.signal.aborted) setRecord(detail);
      }).catch((cause) => { if (!controller.signal.aborted)
        setError(cause instanceof Error ? cause.message : 'DETAIL_UNAVAILABLE'); });
    return () => controller.abort();
  }, [catalog, ready, pubkey]);
  return <div className="devnet-workspace-page">
    <PageHeader eyebrow={c('AGENT / VERIFIED RECORD', 'AGENTE / REGISTRO VERIFICADO')}
      title={c('Agent account', 'Cuenta de agente')}
      description={c('Public fields from one finalized Devnet snapshot. Agent Cards and metadata do not grant financial authority.',
        'Campos públicos de una instantánea finalizada de Devnet. Agent Cards y metadatos no conceden autoridad financiera.')} />
    <CatalogNotice />
    {catalog && <>
      {!record && <div className="devnet-unavailable" role="status">
        <Icon name="agents" /><div><h2>{error ? c('Record unavailable', 'Registro no disponible') : c('Verifying account detail…', 'Verificando detalle de cuenta…')}</h2>
          {error && <p>{error}</p>}<Link to="/app/agents">{c('Back to agents', 'Volver a agentes')}</Link></div></div>}
      {record && <article className="panel devnet-detail-panel">
        <div className="devnet-detail-head"><span className="agent-icon"><Icon name="agents" /></span><ProofBadge /></div>
        <h2><Address value={record.agent_account} full /></h2>
        <div className="devnet-detail-grid">
          <div><small>AgentAccount / PDA</small><Address value={record.agent_account} full /></div>
          <div><small>Agent ID</small><code>{record.agent_id}</code></div>
          <div><small>{c('Owner', 'Propietario')}</small><Address value={record.owner} full /></div>
          <div><small>{c('Signing authority', 'Autoridad firmante')}</small><Address value={record.signing_authority} full /></div>
          <div><small>{c('Status', 'Estado')}</small><strong>{record.status}</strong></div>
          <div><small>{c('Active flag', 'Marca activa')}</small><strong>{String(record.active)}</strong></div>
          <div><small>ProtocolConfig</small><Address value={record.protocol_config} full /></div>
          <div><small>{c('Network', 'Red')}</small><strong>Solana Devnet</strong></div>
          <div><small>{c('Snapshot slot', 'Slot de instantánea')}</small><strong>{catalog.provenance.slot_max.toLocaleString()}</strong></div>
          <div><small>{c('Observed', 'Observado')}</small><strong>{catalog.provenance.generated_at}</strong></div>
        </div>
        <section><h3>{c('On-chain capability bits', 'Bits de capacidad on-chain')}</h3>
          <CapabilityChips mask={record.capabilities} /></section>
        <p className="devnet-detail-foot">{c('Capability bits are declared on-chain. This view does not independently attest hardware, location, performance or income.',
          'Los bits de capacidad se declaran on-chain. Esta vista no certifica hardware, ubicación, rendimiento ni ingresos por separado.')}</p>
        <div className="devnet-inline-actions"><a className="button" href={explorerUrl(record.agent_account)} target="_blank" rel="noopener noreferrer">Solana Explorer ↗</a>
          <Link className="button" to="/app/agents">{c('Back to catalog', 'Volver al catálogo')}</Link></div>
      </article>}
    </>}
  </div>;
}
