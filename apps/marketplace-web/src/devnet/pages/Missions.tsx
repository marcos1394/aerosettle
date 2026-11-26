import { useMemo, useState } from 'react';
import { Link } from 'react-router';
import { useCopy } from '../i18n.tsx';
import { Icon, PageHeader } from '../ui.tsx';
import { useDevnetData } from '../DevnetDataProvider.tsx';
import { CAPABILITY_NAMES, filterWorkOrders } from '../catalog.ts';
import { Address, CapabilityChips, CatalogNotice, EmptyResults, ProofBadge, SourceLegend } from './common.tsx';

const PAGE_SIZE = 6;
export default function Missions() {
  const c = useCopy();
  const { catalog } = useDevnetData();
  const [search, setSearch] = useState('');
  const [status, setStatus] = useState('');
  const [capability, setCapability] = useState('');
  const [sort, setSort] = useState('address');
  const [view, setView] = useState<'grid' | 'list'>('grid');
  const [page, setPage] = useState(1);
  const filtered = useMemo(() => filterWorkOrders(catalog?.workorders ?? [], search, status, capability, sort),
    [catalog, search, status, capability, sort]);
  const maxPage = Math.max(1, Math.ceil(filtered.length / PAGE_SIZE));
  const current = Math.min(page, maxPage);
  const visible = filtered.slice((current - 1) * PAGE_SIZE, current * PAGE_SIZE);
  return <div className="devnet-workspace-page">
    <PageHeader eyebrow={c('MARKET / WORKORDERS', 'MERCADO / ÓRDENES')}
      title={c('Mission marketplace', 'Mercado de misiones')}
      description={c('On-chain WorkOrders indexed from Devnet. Creation, funding, claiming and settlement remain disabled.',
        'WorkOrders on-chain indexadas desde Devnet. Crear, financiar, reclamar y liquidar permanecen deshabilitados.')} />
    <CatalogNotice />
    <SourceLegend />
    {catalog && <>
      <div className="missions-toolbar">
        <label>{c('Search verified fields', 'Buscar campos verificados')}<input value={search}
          onChange={(event) => { setSearch(event.target.value); setPage(1); }} placeholder={c('Address, ID or creator', 'Dirección, ID o creador')} /></label>
        <label>{c('Status', 'Estado')}<select value={status} onChange={(event) => { setStatus(event.target.value); setPage(1); }}>
          <option value="">{c('All statuses', 'Todos los estados')}</option>
          {['Draft', 'Open', 'Claimed', 'Submitted', 'Verified', 'Settled', 'Cancelled', 'Expired'].map((value) => <option key={value}>{value}</option>)}
        </select></label>
        <label>{c('Required capability', 'Capacidad requerida')}<select value={capability} onChange={(event) => { setCapability(event.target.value); setPage(1); }}>
          <option value="">{c('All capabilities', 'Todas las capacidades')}</option>
          {CAPABILITY_NAMES.map(([en, es], index) => <option value={String(index)} key={en}>{c(en, es)}</option>)}
        </select></label>
        <label>{c('Sort', 'Ordenar')}<select value={sort} onChange={(event) => setSort(event.target.value)}>
          <option value="address">{c('Address A–Z', 'Dirección A–Z')}</option><option value="address-desc">{c('Address Z–A', 'Dirección Z–A')}</option>
          <option value="status">{c('Status', 'Estado')}</option><option value="deadline">{c('Deadline', 'Fecha límite')}</option>
        </select></label>
      </div><div className="devnet-results-bar"><span>{filtered.length} WorkOrders · ONCHAIN_VERIFIED</span>
        <div className="devnet-view-switch" role="group" aria-label={c('View mode', 'Modo de vista')}>
          <button aria-pressed={view === 'grid'} onClick={() => setView('grid')}><Icon name="grid" /> {c('Grid', 'Cuadrícula')}</button>
          <button aria-pressed={view === 'list'} onClick={() => setView('list')}><Icon name="list" /> {c('List', 'Lista')}</button></div></div>
      {visible.length ? <div className={view === 'grid' ? 'mission-cards-grid' : 'devnet-list-grid'}>
        {visible.map((order) => <article className="mission-card" key={order.work_order_account}>
          <div className="mission-card-top"><span className="mission-cat-pill"><Icon name="missions" /> WorkOrder</span><ProofBadge /></div>
          <div className="mission-card-body"><p className="eyebrow">{order.status.toUpperCase()} / SOLANA DEVNET</p>
            <h2 className="mission-card-title"><Address value={order.work_order_account} /></h2>
            <p>{c('Creator', 'Creador')}: <Address value={order.creator} /></p>
            <CapabilityChips mask={order.required_capabilities} /></div>
          <div className="card-link"><span>{c('Test mint · amount not indexed', 'Mint de prueba · importe no indexado')}</span>
            <Link to={`/app/missions/${order.work_order_account}`}>{c('View WorkOrder', 'Ver orden')} <Icon name="arrow" /></Link></div>
        </article>)}
      </div> : <EmptyResults />}
      <nav className="devnet-pagination" aria-label={c('Mission pages', 'Páginas de misiones')}>
        <button disabled={current <= 1} onClick={() => setPage(current - 1)}>{c('Previous', 'Anterior')}</button>
        <span>{c('Page', 'Página')} {current} / {maxPage}</span>
        <button disabled={current >= maxPage} onClick={() => setPage(current + 1)}>{c('Next', 'Siguiente')}</button>
      </nav>
    </>}
  </div>;
}
