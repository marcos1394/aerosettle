import { useEffect, useState } from 'react';
import { Link, useParams } from 'react-router';
import { useCopy } from '../i18n.tsx';
import { Icon, PageHeader } from '../ui.tsx';
import { useDevnetData } from '../DevnetDataProvider.tsx';
import { explorerUrl, parseWorkOrder, type VerifiedWorkOrder } from '../catalog.ts';
import { fetchRecord } from '../index.ts';
import { Address, CapabilityChips, CatalogNotice, ProofBadge } from './common.tsx';

export default function MissionDetail() {
  const c = useCopy();
  const { pubkey = '' } = useParams();
  const { catalog, ready } = useDevnetData();
  const [record, setRecord] = useState<VerifiedWorkOrder>();
  const [error, setError] = useState('');
  useEffect(() => {
    setRecord(undefined); setError('');
    if (!catalog || !ready) return;
    const listed = catalog.workorders.find((order) => order.work_order_account === pubkey);
    if (!listed) { setError('ACCOUNT_NOT_INDEXED'); return; }
    const controller = new AbortController();
    void fetchRecord('workorders', pubkey, ready, catalog.provenance, fetch, controller.signal)
      .then((row) => {
        const detail = parseWorkOrder(row);
        if (JSON.stringify(detail) !== JSON.stringify(listed)) throw Error('DETAIL_LIST_MISMATCH');
        if (!controller.signal.aborted) setRecord(detail);
      }).catch((cause) => { if (!controller.signal.aborted)
        setError(cause instanceof Error ? cause.message : 'DETAIL_UNAVAILABLE'); });
    return () => controller.abort();
  }, [catalog, ready, pubkey]);
  return <div className="devnet-workspace-page">
    <PageHeader eyebrow={c('MISSION / VERIFIED WORKORDER', 'MISIÓN / ORDEN VERIFICADA')}
      title={c('WorkOrder detail', 'Detalle de orden')}
      description={c('A read-only view of the published on-chain WorkOrder fields.',
        'Una vista de solo lectura de los campos on-chain publicados de la orden.')} />
    <CatalogNotice />
    {catalog && <>
      {!record && <div className="devnet-unavailable" role="status"><Icon name="missions" /><div>
        <h2>{error ? c('Record unavailable', 'Registro no disponible') : c('Verifying WorkOrder detail…', 'Verificando detalle de la orden…')}</h2>
        {error && <p>{error}</p>}<Link to="/app/missions">{c('Back to missions', 'Volver a misiones')}</Link>
      </div></div>}
      {record && <article className="panel devnet-detail-panel">
        <div className="devnet-detail-head"><span className="agent-icon"><Icon name="missions" /></span><ProofBadge /></div>
        <h2><Address value={record.work_order_account} full /></h2>
        <div className="devnet-detail-grid">
          <div><small>WorkOrder PDA</small><Address value={record.work_order_account} full /></div>
          <div><small>WorkOrder ID</small><code>{record.work_order_id}</code></div>
          <div><small>{c('Status', 'Estado')}</small><strong>{record.status}</strong></div>
          <div><small>{c('Open flag', 'Marca abierta')}</small><strong>{String(record.is_open)}</strong></div>
          <div><small>{c('Creator', 'Creador')}</small><Address value={record.creator} full /></div>
          <div><small>ProtocolConfig</small><Address value={record.protocol_config} full /></div>
          <div><small>{c('Test mint', 'Mint de prueba')}</small><Address value={record.token_mint} full /></div>
          <div><small>SPL Token Program</small><Address value={record.token_program} full /></div>
          <div><small>{c('Execution deadline', 'Fecha límite de ejecución')}</small><strong>{record.execution_deadline ? new Date(record.execution_deadline * 1000).toLocaleString() : c('Not set', 'No indicada')}</strong></div>
          <div><small>{c('Snapshot slot', 'Slot de instantánea')}</small><strong>{catalog.provenance.slot_max.toLocaleString()}</strong></div>
        </div>
        <section><h3>{c('Required capability bits', 'Bits de capacidad requeridos')}</h3>
          <CapabilityChips mask={record.required_capabilities} /></section>
        <p className="devnet-detail-foot">{c('Reward, beneficiary and settlement evidence are not included in the public CON-59 snapshot. No amount is inferred from status.',
          'La recompensa, el beneficiario y la evidencia de liquidación no están en la instantánea pública CON-59. No se infiere ningún importe a partir del estado.')}</p>
        <div className="devnet-inline-actions"><a className="button" href={explorerUrl(record.work_order_account)} target="_blank" rel="noopener noreferrer">Solana Explorer ↗</a>
          <Link className="button" to="/app/missions">{c('Back to missions', 'Volver a misiones')}</Link></div>
      </article>}
    </>}
  </div>;
}
