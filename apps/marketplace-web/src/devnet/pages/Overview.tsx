import { Link } from 'react-router';
import { useCopy } from '../i18n.tsx';
import { Icon, PageHeader } from '../ui.tsx';
import { useDevnetData } from '../DevnetDataProvider.tsx';
import { Address, CatalogNotice, ProofBadge } from './common.tsx';

export default function Overview() {
  const c = useCopy();
  const { catalog } = useDevnetData();
  return <div className="devnet-workspace-page">
    <PageHeader eyebrow={c('WORKSPACE / DEVNET', 'ESPACIO / DEVNET')}
      title={c('Mission Control', 'Centro de misiones')}
      description={c('A verified view of public Conatus accounts on Solana Devnet.',
        'Una vista verificada de cuentas públicas Conatus en Solana Devnet.')} />
    <section className="hero-panel overview-command-hero devnet-overview-hero">
      <div><p className="eyebrow">{c('THE PHYSICAL AI ECONOMY', 'LA ECONOMÍA DE IA FÍSICA')}</p>
        <h2>{c('Discover the network. Follow the evidence.', 'Descubre la red. Sigue la evidencia.')}</h2>
        <p>{c('This preview indexes finalized AgentAccounts and WorkOrders. It does not represent balances, revenue or permission to transact.',
          'Esta vista indexa AgentAccounts y WorkOrders finalizados. No representa balances, ingresos ni permisos para operar.')}</p>
        <div className="devnet-inline-actions"><Link className="button primary" to="/app/agents">{c('Explore agents', 'Explorar agentes')} <Icon name="arrow" /></Link>
          <Link className="button" to="/app/missions">{c('Browse missions', 'Ver misiones')}</Link></div>
      </div><div className="devnet-overview-orbit" aria-hidden="true"><span>CONATUS</span><span>DEVNET</span></div>
    </section>
    <CatalogNotice />
    {catalog && <>
      <section className="devnet-metric-grid" aria-label={c('Verified network metrics', 'Métricas verificadas de red')}>
        <div className="panel"><p>{c('Agents indexed', 'Agentes indexados')}</p><strong>{catalog.agents.length}</strong><small>ONCHAIN_VERIFIED</small></div>
        <div className="panel"><p>{c('WorkOrders indexed', 'Órdenes indexadas')}</p><strong>{catalog.workorders.length}</strong><small>ONCHAIN_VERIFIED</small></div>
        <div className="panel"><p>{c('Network', 'Red')}</p><strong>Devnet</strong><small>{c('Finalized snapshot', 'Instantánea finalizada')}</small></div>
        <div className="panel"><p>{c('Snapshot slot', 'Slot de instantánea')}</p><strong>{catalog.provenance.slot_max.toLocaleString()}</strong><small>{c('Non-atomic account scan', 'Escaneo de cuentas no atómico')}</small></div>
      </section>
      <div className="devnet-preview-grid">
        <section className="panel"><div className="devnet-panel-head"><h2>{c('Agent directory', 'Directorio de agentes')}</h2><Link to="/app/agents">{c('View all', 'Ver todos')} ↗</Link></div>
          {catalog.agents.slice(0, 3).map((agent) => <Link className="devnet-preview-row" key={agent.agent_account} to={`/app/agents/${agent.agent_account}`}><Icon name="agents" /><span><Address value={agent.agent_account} /><small>{agent.status}</small></span><ProofBadge /></Link>)}
          {!catalog.agents.length && <p>{c('No agents in this snapshot.', 'No hay agentes en esta instantánea.')}</p>}
        </section>
        <section className="panel"><div className="devnet-panel-head"><h2>{c('WorkOrders', 'Órdenes de trabajo')}</h2><Link to="/app/missions">{c('View all', 'Ver todas')} ↗</Link></div>
          {catalog.workorders.slice(0, 3).map((order) => <Link className="devnet-preview-row" key={order.work_order_account} to={`/app/missions/${order.work_order_account}`}><Icon name="missions" /><span><Address value={order.work_order_account} /><small>{order.status}</small></span><ProofBadge /></Link>)}
          {!catalog.workorders.length && <p>{c('No WorkOrders in this snapshot.', 'No hay órdenes en esta instantánea.')}</p>}
        </section>
      </div>
    </>}
  </div>;
}
