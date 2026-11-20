import { lazy, Suspense, useEffect, useRef, useState } from 'react';
import { BrowserRouter, Link, NavLink, Route, Routes, useLocation } from 'react-router';
import { LanguageProvider, LanguageSelect, useCopy } from './i18n.tsx';
import { useLandingMotion } from '../app/useLandingMotion.ts';
import { Brand, Icon } from './ui.tsx';
import { DevnetDataProvider, useDevnetData } from './DevnetDataProvider.tsx';
import { DevnetReadOnlyApp } from './DevnetReadOnlyApp.tsx';

const Overview = lazy(() => import('./pages/Overview.tsx'));
const Agents = lazy(() => import('./pages/Agents.tsx'));
const AgentDetail = lazy(() => import('./pages/AgentDetail.tsx'));
const Missions = lazy(() => import('./pages/Missions.tsx'));
const MissionDetail = lazy(() => import('./pages/MissionDetail.tsx'));

const links = [
  { to: '/app', en: 'Overview', es: 'Resumen', icon: 'grid' },
  { to: '/app/agents', en: 'Agents', es: 'Agentes', icon: 'agents' },
  { to: '/app/missions', en: 'Missions', es: 'Misiones', icon: 'missions' },
  { to: '/status', en: 'Network status', es: 'Estado de red', icon: 'activity' },
] as const;

function Navigation({ close }: { close?: () => void }) {
  const c = useCopy();
  return <>
    <Brand />
    <p className="nav-label">{c('DEVNET MARKETPLACE', 'MERCADO DEVNET')}</p>
    <nav aria-label={c('Marketplace navigation', 'Navegación del mercado')}>
      {links.map((item) => <NavLink key={item.to} to={item.to}
        end={item.to === '/app'} onClick={close}
        className={({ isActive }) => isActive ? 'active' : ''}>
        <Icon name={item.icon} /><span className="nav-link-label">{c(item.en, item.es)}</span>
        <span className="nav-dot" aria-hidden="true" />
      </NavLink>)}
    </nav>
    <div className="sidebar-footer"><span className="network-orb" aria-hidden="true" />
      <div><strong>Solana Devnet</strong><small>{c('Read-only preview', 'Vista de solo lectura')}</small></div>
    </div>
  </>;
}

function Shell({ children }: { children: React.ReactNode }) {
  const c = useCopy();
  const location = useLocation();
  const { catalog, verification } = useDevnetData();
  const [open, setOpen] = useState(false);
  const dialog = useRef<HTMLDialogElement>(null);
  const trigger = useRef<HTMLButtonElement>(null);
  useEffect(() => {
    if (open) dialog.current?.showModal();
    else dialog.current?.close();
    return () => dialog.current?.close();
  }, [open]);
  useEffect(() => {
    setOpen(false);
    document.getElementById('workspace-main')?.focus();
    window.scrollTo(0, 0);
  }, [location.pathname]);
  const label = links.find((item) => item.to === location.pathname ||
    (item.to !== '/app' && location.pathname.startsWith(item.to))) ?? links[0];
  const close = () => { setOpen(false); trigger.current?.focus(); };
  return <div className="devnet-app app-shell">
    <a className="skip-link" href="#workspace-main">{c('Skip to content', 'Saltar al contenido')}</a>
    <aside className="sidebar" id="primary-sidebar"><Navigation /></aside>
    <dialog ref={dialog} className="nav-drawer"
      aria-label={c('Navigation', 'Navegación')} onCancel={close}
      onClick={(event) => { if (event.target === dialog.current) close(); }}>
      <div className="drawer-content">
        <button className="drawer-close" onClick={close} aria-label={c('Close navigation', 'Cerrar navegación')}><Icon name="close" /></button>
        <Navigation close={close} />
      </div>
    </dialog>
    <div className="workspace">
      <header className="topbar">
        <button ref={trigger} className="menu-button" aria-expanded={open}
          aria-label={c('Open navigation', 'Abrir navegación')} onClick={() => setOpen(true)}><Icon name="menu" /></button>
        <nav className="breadcrumbs" aria-label={c('Breadcrumbs', 'Ruta')}>
          <Link to="/">Conatus</Link><span>/</span><span>{c(label.en, label.es)}</span>
        </nav>
        <div className="topbar-actions">
          <Link to="/status" className="network-status">
            <span className={catalog ? 'devnet-indicator ready' : 'devnet-indicator'} aria-hidden="true" />
            <span>{catalog ? c('Index verified', 'Índice verificado') :
              verification.status === 'VERIFYING' ? c('Verifying…', 'Verificando…') :
                c('Index unavailable', 'Índice no disponible')}</span>
          </Link>
          <LanguageSelect />
        </div>
      </header>
      <main id="workspace-main" className="workspace-main" tabIndex={-1}>{children}</main>
      <footer className="workspace-footer">
        <span>© {new Date().getFullYear()} Conatus Protocol</span>
        <span className="workspace-footer-links"><span>Solana Devnet</span><span>{c('Financial actions disabled', 'Operaciones financieras deshabilitadas')}</span></span>
      </footer>
    </div>
  </div>;
}

function Landing() {
  const c = useCopy();
  const { catalog } = useDevnetData();
  const motion = useLandingMotion();
  return <div ref={motion.root} className="conatus-site devnet-premium" data-motion={motion.enabled ? 'on' : 'off'}>
    <header className="c-nav">
      <Brand />
      <nav aria-label={c('Primary navigation', 'Navegación principal')}>
        <Link to="/app/agents">{c('Agents', 'Agentes')}</Link>
        <Link to="/app/missions">{c('Missions', 'Misiones')}</Link>
        <Link to="/status">{c('Network status', 'Estado de red')}</Link>
      </nav>
      <div className="public-actions"><LanguageSelect />
        <Link className="c-button c-button-primary c-button-small" to="/app">
          {c('Explore marketplace', 'Explorar mercado')} <Icon name="arrow" />
        </Link>
      </div>
    </header>
    <main>
      <section className="c-hero" aria-labelledby="devnet-hero-title">
        <div className="c-hero-copy">
          <p className="c-kicker"><span /> CONATUS / SOLANA DEVNET</p>
          <h1 id="devnet-hero-title">{c('The physical AI', 'La IA física')}<br />
            <span>{c('economy.', 'tiene mercado.')}</span></h1>
          <p className="c-hero-description">{c(
            'Explore verifiable agents and WorkOrders from the Conatus test network. Every listed account is bound to a finalized Devnet snapshot.',
            'Explora agentes y órdenes de trabajo verificables de la red de prueba Conatus. Cada cuenta publicada está vinculada a una instantánea finalizada de Devnet.')}</p>
          <div className="c-hero-actions">
            <Link to="/app/agents" className="c-button c-button-primary">{c('Discover agents', 'Descubrir agentes')} <Icon name="arrow" /></Link>
            <Link to="/app/missions" className="c-text-link">{c('Browse missions', 'Ver misiones')} <span>↗</span></Link>
          </div>
          <p className="c-hero-proof">SOLANA DEVNET <span>·</span> {c('READ ONLY', 'SOLO LECTURA')} <span>·</span>
            {catalog ? c('INDEX VERIFIED', 'ÍNDICE VERIFICADO') : c('INDEX TEMPORARILY UNAVAILABLE', 'ÍNDICE TEMPORALMENTE NO DISPONIBLE')}</p>
        </div>
        <div className="c-hero-art"><img src="/images/conatus-physical-ai.jpg" alt={c('Physical AI robotics in the Conatus visual identity', 'Robótica de IA física en la identidad visual de Conatus')} /></div>
      </section>
      <section className="c-section-top devnet-landing-section" data-reveal>
        <p className="c-index">01 / {c('EXPLORE THE NETWORK', 'EXPLORA LA RED')}</p>
        <div className="c-section-heading"><h2>{c('A marketplace grounded', 'Un mercado basado')}<br /><span>{c('in verifiable accounts.', 'en cuentas verificables.')}</span></h2>
          <p>{c('Browse public AgentAccounts and WorkOrders. Profile details come from the approved on-chain schema; unsupported commercial claims are left out.',
            'Consulta AgentAccounts y WorkOrders públicos. Los detalles proceden del esquema on-chain aprobado; se omiten afirmaciones comerciales sin respaldo.')}</p></div>
        <div className="devnet-landing-links">
          <Link to="/app/agents" className="agent-market-card"><Icon name="agents" /><h3>{c('Agent catalog', 'Catálogo de agentes')}</h3><p>{catalog ? `${catalog.agents.length} ${c('verified accounts', 'cuentas verificadas')}` : c('Available when the index is fresh', 'Disponible cuando el índice esté vigente')}</p><span>↗</span></Link>
          <Link to="/app/missions" className="mission-card"><Icon name="missions" /><h3>{c('WorkOrders', 'Órdenes de trabajo')}</h3><p>{catalog ? `${catalog.workorders.length} ${c('verified records', 'registros verificados')}` : c('Available when the index is fresh', 'Disponible cuando el índice esté vigente')}</p><span>↗</span></Link>
        </div>
      </section>
      <section className="devnet-landing-note" data-reveal><p className="eyebrow">{c('TRUST BOUNDARY', 'LÍMITE DE CONFIANZA')}</p>
        <h2>{c('Explore with confidence. Act later.', 'Explora con confianza. Actúa después.')}</h2>
        <p>{c('This preview cannot connect a wallet, sign, fund, claim or settle. Network and snapshot evidence remain available in the status view.',
          'Esta vista no puede conectar una wallet, firmar, financiar, reclamar ni liquidar. La evidencia de red e instantánea está disponible en la pantalla de estado.')}</p>
        <Link to="/status" className="c-text-link">{c('View verification details', 'Ver detalles de verificación')} <span>↗</span></Link>
      </section>
    </main>
    <footer className="devnet-landing-footer"><Brand /><span>Solana Devnet · {c('Test assets only', 'Solo activos de prueba')}</span></footer>
  </div>;
}

function RouteTree() {
  const c = useCopy();
  const location = useLocation();
  useEffect(() => { document.title = `Conatus · ${location.pathname === '/' ? c('The physical AI economy', 'Economía de IA física') : 'Devnet Marketplace'}`; }, [location.pathname, c]);
  const fallback = <div className="loading-state" role="status">{c('Loading marketplace…', 'Cargando mercado…')}</div>;
  return <Suspense fallback={fallback}><Routes>
    <Route path="/" element={<Landing />} />
    <Route path="/status" element={<Shell><DevnetReadOnlyApp /></Shell>} />
    <Route path="/app" element={<Shell><Overview /></Shell>} />
    <Route path="/app/agents" element={<Shell><Agents /></Shell>} />
    <Route path="/app/agents/:pubkey" element={<Shell><AgentDetail /></Shell>} />
    <Route path="/app/missions" element={<Shell><Missions /></Shell>} />
    <Route path="/app/missions/:pubkey" element={<Shell><MissionDetail /></Shell>} />
    <Route path="*" element={<Shell><div className="empty-state"><h1>{c('Page not found', 'Página no encontrada')}</h1><Link to="/">{c('Return home', 'Volver al inicio')}</Link></div></Shell>} />
  </Routes></Suspense>;
}
export function DevnetApp() {
  return <LanguageProvider><DevnetDataProvider><BrowserRouter><RouteTree /></BrowserRouter></DevnetDataProvider></LanguageProvider>;
}
