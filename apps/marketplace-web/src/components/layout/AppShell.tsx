import { CommandMenu } from '../ui/CommandMenu';
import { time } from '../../app/config';
import { useCopy, useI18n } from '../../app/i18n';
import { useEffect, useRef, useState, Suspense } from 'react';
import { Link, NavLink, Outlet, useLocation } from 'react-router';
import { WalletControl } from '../ui/WalletControl';
import { LanguageSelect } from '../../app/i18n';
import { Brand, Icon } from '../ui';
import { Pulse } from '../ui/viz';
import { useSnapshot } from '../../app/atlas';
import { NetworkProvider, useNetwork } from '../../app/NetworkProvider';

type Section = { en: string; es: string; to: string; icon: string };
const groups: { en: string; es: string; items: Section[] }[] = [
  {
    en: 'MARKET',
    es: 'MERCADO',
    items: [
      { en: 'Mission Control', es: 'Mission Control', to: '/app', icon: 'grid' },
      { en: 'Economy', es: 'Economía', to: '/app/economy', icon: 'economy' },
      { en: 'Agents', es: 'Agentes', to: '/app/agents', icon: 'agents' },
      { en: 'Organizations', es: 'Organizaciones', to: '/app/organizations', icon: 'agents' },
      { en: 'Missions', es: 'Misiones', to: '/app/missions', icon: 'missions' },
      { en: 'Mission planner', es: 'Planificador', to: '/app/planner', icon: 'target' },
    ],
  },
  {
    en: 'OPERATE',
    es: 'OPERAR',
    items: [
      { en: 'My fleet', es: 'Mi flota', to: '/app/fleet', icon: 'fleet' },
      { en: 'Treasury', es: 'Tesorería', to: '/app/wallet', icon: 'wallet' },
      { en: 'Activity', es: 'Actividad', to: '/app/activity', icon: 'activity' },
      { en: 'Settings', es: 'Configuración', to: '/app/settings', icon: 'settings' },
    ],
  },
];
const sections = groups.flatMap((group) => group.items);
function findSection(pathname: string) {
  return [...sections]
    .sort((a, b) => b.to.length - a.to.length)
    .find((s) => (s.to === '/app' ? pathname === '/app' : pathname.startsWith(s.to)));
}

/** Network state shown in the shell: live chain, connecting, or snapshot. */
function useNetworkLabel() {
  const c = useCopy();
  const network = useNetwork();
  const [snapshot] = useSnapshot();
  if (network.data)
    return { tone: 'success' as const, title: c('Solana · Live', 'Solana · En vivo'), detail: c('Protocol verified', 'Protocolo verificado') };
  if (network.loading)
    return { tone: 'warning' as const, title: c('Connecting…', 'Conectando…'), detail: c('Syncing with Solana', 'Sincronizando con Solana') };
  return snapshot
    ? { tone: 'accent' as const, title: c('Conatus Network', 'Red Conatus'), detail: c('Network snapshot', 'Instantánea de red') }
    : { tone: 'error' as const, title: c('Offline', 'Sin conexión'), detail: c('Cannot reach the network', 'No se alcanza la red') };
}

function Navigation({ close, compact = false }: { close?: () => void; compact?: boolean }) {
  const c = useCopy();
  const status = useNetworkLabel();
  return (
    <>
      <Brand />
      <div className="nav-scroll">
        {groups.map((group) => (
          <div key={group.en} className="nav-group">
            <p className="nav-label">{c(group.en, group.es)}</p>
            <nav aria-label={c(group.en, group.es)}>
              {group.items.map((item) => {
                const label = c(item.en, item.es);
                return (
                  <NavLink
                    key={item.to}
                    to={item.to}
                    end={item.to === '/app'}
                    onClick={close}
                    aria-label={label}
                    title={compact ? label : undefined}
                    className={({ isActive }) => (isActive ? 'active' : '')}
                  >
                    <Icon name={item.icon} />
                    <span className="nav-link-label">{label}</span>
                    {compact && (
                      <span className="nav-tooltip" aria-hidden="true">
                        {label}
                      </span>
                    )}
                    <span className="nav-dot" aria-hidden="true" />
                  </NavLink>
                );
              })}
            </nav>
          </div>
        ))}
        <Link to="/app/agents/register" className="nav-cta" onClick={close}>
          <span className="nav-cta-icon">
            <Icon name="bolt" />
          </span>
          <span className="nav-cta-copy">
            <strong>{c('Put a machine to work', 'Pon una máquina a trabajar')}</strong>
            <small>{c('Register an agent in minutes', 'Registra un agente en minutos')}</small>
          </span>
        </Link>
      </div>
      <Link to="/app/settings" className="sidebar-footer" onClick={close}>
        <Pulse tone={status.tone} />
        <div>
          <strong>{status.title}</strong>
          <small>{status.detail}</small>
        </div>
      </Link>
    </>
  );
}

function Shell() {
  const { t, locale } = useI18n();
  const c = useCopy();
  const [open, setOpen] = useState(false);
  const [collapsed, setCollapsed] = useState(() => {
    try {
      return localStorage.getItem('conatus.sidebar') === 'collapsed';
    } catch {
      return false;
    }
  });
  useEffect(() => {
    try {
      localStorage.setItem('conatus.sidebar', collapsed ? 'collapsed' : 'expanded');
    } catch {
      /* Session preference still applies. */
    }
  }, [collapsed]);
  const dialog = useRef<HTMLDialogElement>(null);
  const trigger = useRef<HTMLButtonElement>(null);
  const location = useLocation();
  const network = useNetwork();
  const status = useNetworkLabel();
  const previous = useRef(location.pathname);
  const section = findSection(location.pathname);
  const sectionLabel = section ? c(section.en, section.es) : 'Mission Control';
  useEffect(() => {
    if (previous.current !== location.pathname) {
      document.getElementById('workspace-main')?.focus();
      window.scrollTo(0, 0);
      if (!window.matchMedia('(prefers-reduced-motion: reduce)').matches)
        document.getElementById('workspace-main')?.animate(
          [
            { opacity: 0.35, transform: 'translateY(6px)' },
            { opacity: 1, transform: 'translateY(0)' },
          ],
          { duration: 220, easing: 'ease-out' }
        );
      previous.current = location.pathname;
    }
    document.title = `${sectionLabel} · Conatus`;
  }, [location.pathname, sectionLabel]);
  useEffect(() => {
    if (open) {
      dialog.current?.showModal();
      document.body.style.overflow = 'hidden';
    } else {
      dialog.current?.close();
      document.body.style.overflow = '';
    }
    return () => {
      document.body.style.overflow = '';
    };
  }, [open]);
  function close() {
    setOpen(false);
    trigger.current?.focus();
  }
  return (
    <div className={`app-shell ${collapsed ? 'sidebar-collapsed' : ''}`}>
      <a className="skip-link" href="#workspace-main">
        {t('Saltar al contenido')}
      </a>
      <aside className="sidebar" id="primary-sidebar">
        <Navigation compact={collapsed} />
      </aside>
      <dialog
        ref={dialog}
        className="nav-drawer"
        aria-label={t('Navegación')}
        onCancel={close}
        onClick={(e) => {
          if (e.target === dialog.current) close();
        }}
      >
        <div className="drawer-content">
          <button className="drawer-close" aria-label={t('Cerrar navegación')} onClick={close}>
            <Icon name="close" />
          </button>
          <Navigation close={close} />
        </div>
      </dialog>
      <div className="workspace">
        <header className="topbar">
          <button
            ref={trigger}
            className="menu-button"
            aria-label={t('Abrir navegación')}
            aria-expanded={open}
            onClick={() => setOpen(true)}
          >
            <Icon name="menu" />
          </button>
          <button
            className="sidebar-toggle"
            type="button"
            aria-label={t(collapsed ? 'Expand sidebar' : 'Collapse sidebar')}
            title={t(collapsed ? 'Expand sidebar' : 'Collapse sidebar')}
            aria-controls="primary-sidebar"
            aria-expanded={!collapsed}
            onClick={() => setCollapsed((value) => !value)}
          >
            <Icon name="sidebar" />
          </button>
          <nav className="breadcrumbs" aria-label={t('Ruta')}>
            <Link to="/app">Conatus</Link>
            <span>/</span>
            <Link to={section?.to ?? '/app'}>{sectionLabel}</Link>
          </nav>
          <div className="topbar-actions">
            <Link
              to="/app/settings"
              className="network-status"
              title={
                network.data
                  ? c('Verified at {time}', 'Verificada a las {time}').replace(
                      '{time}',
                      time(network.data.observedAt, locale)
                    )
                  : status.detail
              }
            >
              <Pulse tone={status.tone} />
              <span>
                {status.title}
              </span>
            </Link>
            <CommandMenu />
            <LanguageSelect />
            <WalletControl />
          </div>
        </header>
        <main id="workspace-main" className="workspace-main" tabIndex={-1}>
          <Suspense
            fallback={
              <div className="loading-state" role="status">
                {t('Cargando sección…')}
              </div>
            }
          >
            <Outlet />
          </Suspense>
        </main>
        <footer className="workspace-footer">
          <span>© {new Date().getFullYear()} Conatus Protocol</span>
          <span className="workspace-footer-links">
            <Link to="/roadmap">{c('Roadmap', 'Hoja de ruta')}</Link>
            <Link to="/journal">Journal</Link>
            <span>{c('Settled on Solana', 'Liquidado en Solana')}</span>
          </span>
        </footer>
      </div>
    </div>
  );
}
export default function AppShell() {
  return (
    <NetworkProvider>
      <Shell />
    </NetworkProvider>
  );
}
