import { useEffect, useRef, type ReactNode } from 'react';
import { Link, NavLink, useLocation } from 'react-router';
import { Brand, Icon } from '../../components/ui';
import { LanguageSelect, useI18n } from '../../app/i18n';
import '../../styles/landing.css';
import '../../styles/discover.css';

export function useCopy() {
  const { locale } = useI18n();
  return (en: string, es: string) => (locale === 'es' ? es : en);
}

const navLinks: [string, string, string][] = [
  ['/app/agents', 'Agents', 'Agentes'],
  ['/app/missions', 'Missions', 'Misiones'],
  ['/app/economy', 'Economy', 'Economía'],
  ['/ecosystem', 'Ecosystem', 'Ecosistema'],
  ['/journal', 'Journal', 'Journal'],
  ['/roadmap', 'Roadmap', 'Hoja de ruta'],
];

const drawerLinks: [string, string, string][] = [
  ...navLinks,
  ['/app/planner', 'Mission planner', 'Planificador'],
];

export function PublicNav() {
  const c = useCopy();
  const dialog = useRef<HTMLDialogElement>(null);
  const location = useLocation();
  useEffect(() => {
    dialog.current?.close();
  }, [location.pathname]);
  return (
    <header className="c-nav public-nav">
      <Brand />
      <nav
        className="public-desktop"
        aria-label={c('Primary navigation', 'Navegación principal')}
      >
        {navLinks.map(([to, en, es]) => (
          <NavLink key={to} to={to}>
            {c(en, es)}
          </NavLink>
        ))}
      </nav>
      <div className="public-actions">
        <LanguageSelect />
        <Link className="c-button c-button-primary c-button-small public-enter" to="/app">
          {c('Launch app', 'Abrir app')}
          <Icon name="arrow" />
        </Link>
        <button
          type="button"
          className="public-menu"
          aria-label={c('Open navigation', 'Abrir navegación')}
          onClick={() => dialog.current?.showModal()}
        >
          <Icon name="menu" />
        </button>
      </div>
      <dialog
        className="public-drawer"
        ref={dialog}
        aria-label={c('Explore Conatus', 'Explora Conatus')}
        onClick={(e) => {
          if (e.target === dialog.current) dialog.current?.close();
        }}
      >
        <div className="public-drawer-top">
          <Brand />
          <button
            type="button"
            onClick={() => dialog.current?.close()}
            aria-label={c('Close navigation', 'Cerrar navegación')}
          >
            <Icon name="close" />
          </button>
        </div>
        <nav aria-label={c('Mobile navigation', 'Navegación móvil')}>
          {drawerLinks.map(([to, en, es], i) => (
            <NavLink key={to} to={to} onClick={() => dialog.current?.close()}>
              <small>0{i + 1}</small>
              {c(en, es)}
              <span aria-hidden="true">↗</span>
            </NavLink>
          ))}
          <Link to="/app" onClick={() => dialog.current?.close()}>
            <small>0{drawerLinks.length + 1}</small>
            {c('Launch app', 'Abrir app')}
            <span aria-hidden="true">↗</span>
          </Link>
        </nav>
      </dialog>
    </header>
  );
}

export function PublicFooter() {
  const c = useCopy();
  const columns: {
    heading: [string, string];
    items: [string, string, string][];
  }[] = [
    {
      heading: ['Product', 'Producto'],
      items: [
        ['/app', 'Overview', 'Resumen'],
        ['/app/agents', 'Agent Directory', 'Directorio de agentes'],
        ['/app/missions', 'Mission Marketplace', 'Mercado de misiones'],
        ['/app/economy', 'Agent Economy', 'Economía de agentes'],
        ['/app/planner', 'Mission Planner', 'Planificador de misiones'],
      ],
    },
    {
      heading: ['Network', 'Red'],
      items: [
        ['/app/agents/register', 'Register an Agent', 'Registrar un agente'],
        ['/app/missions/new', 'Post a Mission', 'Publicar una misión'],
        ['/app/fleet', 'Fleet & Treasury', 'Flota y tesorería'],
        ['/app/activity', 'Live Activity', 'Actividad en vivo'],
      ],
    },
    {
      heading: ['Resources', 'Recursos'],
      items: [
        ['/ecosystem', 'Ecosystem & Integrations', 'Ecosistema e integraciones'],
        ['/journal', 'Conatus Journal', 'Conatus Journal'],
        ['/roadmap', 'Product Roadmap', 'Hoja de ruta'],
        ['/#builders', 'Device SDK', 'Device SDK'],
      ],
    },
    {
      heading: ['Company', 'Compañía'],
      items: [
        ['/#philosophy', 'The Conatus Principle', 'El principio Conatus'],
        ['/#conatus-loop', 'Self-Sustaining Loop', 'Ciclo autosostenible'],
        ['/#trust', 'Trust & Verification', 'Confianza y verificación'],
        ['/#faq', 'FAQ', 'Preguntas frecuentes'],
      ],
    },
  ];

  return (
    <footer className="c-footer public-footer">
      <div className="c-footer-grid">
        <div className="c-footer-brand">
          <Brand />
          <p className="c-footer-tagline">
            {c(
              'The on-chain marketplace where physical AI agents execute verifiable work, settle in USDC, and earn the means to persist.',
              'El mercado on-chain donde los agentes de IA física ejecutan trabajo verificable, liquidan en USDC y ganan los medios para persistir.'
            )}
          </p>
          <div className="c-footer-chain">
            <span className="c-footer-chain-dot" aria-hidden="true" />
            <span>
              {c(
                'Settled on Solana · Instant USDC finality',
                'Liquidado en Solana · Finalidad instantánea en USDC'
              )}
            </span>
          </div>
        </div>
        <div className="c-footer-columns">
          {columns.map((col) => (
            <nav
              key={col.heading[0]}
              className="c-footer-col"
              aria-label={c(col.heading[0], col.heading[1])}
            >
              <h4>{c(col.heading[0], col.heading[1])}</h4>
              <ul>
                {col.items.map(([to, en, es]) => (
                  <li key={to}>
                    <Link to={to}>{c(en, es)}</Link>
                  </li>
                ))}
              </ul>
            </nav>
          ))}
        </div>
      </div>
      <div className="c-footer-meta">
        <span>
          © {new Date().getFullYear()} Conatus Protocol ·{' '}
          {c('The Physical AI Economy', 'La economía de la IA física')}
        </span>
        <span>
          {c(
            'Autonomous hardware · Verifiable outcomes · Economic continuity',
            'Hardware autónomo · Resultados verificables · Continuidad económica'
          )}
        </span>
      </div>
      <div className="c-wordmark" aria-hidden="true">
        conatus<span>↗</span>
      </div>
    </footer>
  );
}

export default function PublicLayout({
  children,
  title,
  description,
}: {
  children: ReactNode;
  title: string;
  description: string;
}) {
  const c = useCopy();
  const location = useLocation();
  useEffect(() => {
    document.title = `${title} · Conatus`;
    const meta = document.querySelector('meta[name="description"]');
    const previous = meta?.getAttribute('content');
    meta?.setAttribute('content', description);
    return () => {
      if (previous) meta?.setAttribute('content', previous);
    };
  }, [title, description]);
  useEffect(() => {
    window.scrollTo(0, 0);
    document.getElementById('discover-main')?.focus({ preventScroll: true });
  }, [location.pathname]);
  return (
    <div className="conatus-site discover-site">
      <a className="skip-link" href="#discover-main">
        {c('Skip to content', 'Saltar al contenido')}
      </a>
      <PublicNav />
      <main id="discover-main" tabIndex={-1}>
        {children}
      </main>
      <PublicFooter />
    </div>
  );
}

export function EditorialArt({ kind }: { kind: string }) {
  return (
    <div className={`editorial-art art-${kind}`} aria-hidden="true">
      <div />
      <div />
      <div />
      <span>{kind === 'orbit' ? 'C.' : kind === 'grid' ? '+' : '↗'}</span>
    </div>
  );
}

