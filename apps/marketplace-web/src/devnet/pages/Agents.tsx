import { useMemo, useState } from 'react';
import { Link } from 'react-router';
import { useCopy } from '../i18n.tsx';
import { Icon, PageHeader } from '../ui.tsx';
import { useDevnetData } from '../DevnetDataProvider.tsx';
import { CAPABILITY_NAMES, filterAgents } from '../catalog.ts';
import { Address, CapabilityChips, CatalogNotice, EmptyResults, ProofBadge, SourceLegend } from './common.tsx';

const PAGE_SIZE = 6;
export default function Agents() {
  const c = useCopy();
  const { catalog } = useDevnetData();
  const [search, setSearch] = useState('');
  const [status, setStatus] = useState('');
  const [capability, setCapability] = useState('');
  const [sort, setSort] = useState('address');
  const [view, setView] = useState<'grid' | 'list'>('grid');
  const [page, setPage] = useState(1);
  const filtered = useMemo(() => filterAgents(catalog?.agents ?? [], search, status, capability, sort),
    [catalog, search, status, capability, sort]);
  const maxPage = Math.max(1, Math.ceil(filtered.length / PAGE_SIZE));
  const current = Math.min(page, maxPage);
  const visible = filtered.slice((current - 1) * PAGE_SIZE, current * PAGE_SIZE);
  return <div className="devnet-workspace-page">
    <PageHeader eyebrow={c('MARKET / VERIFIED DEVNET', 'MERCADO / DEVNET VERIFICADA')}
      title={c('Agent directory', 'Directorio de agentes')}
      description={c('Public AgentAccounts from the finalized Conatus snapshot. Addresses are identities, not invented profiles.',
        'AgentAccounts públicos de la instantánea finalizada Conatus. Las direcciones son identidades, no perfiles inventados.')} />
    <CatalogNotice />
    <SourceLegend />
    {catalog && <>
      <div className="agents-toolbar"><div className="agents-toolbar-top">
        <label>{c('Search verified fields', 'Buscar campos verificados')}<input value={search}
          onChange={(event) => { setSearch(event.target.value); setPage(1); }}
          placeholder={c('Address, ID or owner', 'Dirección, ID o propietario')} /></label>
        <label>{c('Status', 'Estado')}<select value={status} onChange={(event) => { setStatus(event.target.value); setPage(1); }}>
          <option value="">{c('All statuses', 'Todos los estados')}</option>
          {['Active', 'OwnerSuspended', 'AdminSuspended', 'Revoked'].map((value) => <option key={value}>{value}</option>)}
        </select></label>
        <label>{c('Capability bit', 'Bit de capacidad')}<select value={capability} onChange={(event) => { setCapability(event.target.value); setPage(1); }}>
          <option value="">{c('All capabilities', 'Todas las capacidades')}</option>
          {CAPABILITY_NAMES.map(([en, es], index) => <option value={String(index)} key={en}>{c(en, es)}</option>)}
        </select></label>
        <label>{c('Sort', 'Ordenar')}<select value={sort} onChange={(event) => setSort(event.target.value)}>
          <option value="address">{c('Address A–Z', 'Dirección A–Z')}</option><option value="address-desc">{c('Address Z–A', 'Dirección Z–A')}</option><option value="status">{c('Status', 'Estado')}</option>
        </select></label>
      </div><div className="agents-toolbar-bottom">
        <span>{filtered.length} {c('verified accounts', 'cuentas verificadas')}</span>
        <div className="devnet-view-switch" role="group" aria-label={c('View mode', 'Modo de vista')}>
          <button aria-pressed={view === 'grid'} onClick={() => setView('grid')}><Icon name="grid" /> {c('Grid', 'Cuadrícula')}</button>
          <button aria-pressed={view === 'list'} onClick={() => setView('list')}><Icon name="list" /> {c('List', 'Lista')}</button>
        </div>
      </div></div>
      {visible.length ? <div className={view === 'grid' ? 'agents-cards-grid' : 'devnet-list-grid'}>
        {visible.map((agent) => <article className="agent-market-card" key={agent.agent_account}>
          <div className="devnet-card-top"><span className="agent-icon"><Icon name="agents" /></span><ProofBadge /></div>
          <p className="eyebrow">AGENTACCOUNT / {agent.status.toUpperCase()}</p>
          <h2><Address value={agent.agent_account} /></h2>
          <p className="muted">{c('Owner', 'Propietario')}: <Address value={agent.owner} /></p>
          <CapabilityChips mask={agent.capabilities} />
          <div className="card-link"><span>{c('Verified account · Devnet', 'Cuenta verificada · Devnet')}</span>
            <Link to={`/app/agents/${agent.agent_account}`}>{c('View agent', 'Ver agente')} <Icon name="arrow" /></Link></div>
        </article>)}
      </div> : <EmptyResults />}
      <nav className="devnet-pagination" aria-label={c('Catalog pages', 'Páginas del catálogo')}>
        <button disabled={current <= 1} onClick={() => setPage(current - 1)}>{c('Previous', 'Anterior')}</button>
        <span>{c('Page', 'Página')} {current} / {maxPage}</span>
        <button disabled={current >= maxPage} onClick={() => setPage(current + 1)}>{c('Next', 'Siguiente')}</button>
      </nav>
    </>}
  </div>;
}
