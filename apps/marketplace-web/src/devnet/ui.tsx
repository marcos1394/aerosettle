import type { ReactNode } from 'react';
import { Link } from 'react-router';
import { useCopy } from './i18n.tsx';
export function Icon({ name }: { name: string }) {
  const paths: Record<string, ReactNode> = {
    grid: <><rect x="3" y="3" width="7" height="7" rx="1.5" /><rect x="14" y="3" width="7" height="7" rx="1.5" /><rect x="3" y="14" width="7" height="7" rx="1.5" /><rect x="14" y="14" width="7" height="7" rx="1.5" /></>,
    agents: <><path d="M8 3h8l5 9-5 9H8l-5-9Z" /><circle cx="12" cy="12" r="3" /></>,
    missions: <><rect x="5" y="4" width="14" height="17" rx="2" /><path d="M9 3h6v4H9zM9 12h6M9 16h4" /></>,
    activity: <path d="M2 12h5l3-8 4 16 3-8h5" />,
    arrow: <path d="M4 12h16m-6-6 6 6-6 6" />,
    menu: <path d="M4 6h16M4 12h16M4 18h16" />,
    close: <path d="m6 6 12 12M6 18 18 6" />,
    shield: <><path d="M12 3 4 6v6c0 5 3.5 8 8 9 4.5-1 8-4 8-9V6Z" /><path d="m9 12 2 2 4-4" /></>,
    search: <><circle cx="10.5" cy="10.5" r="6.5" /><path d="m16 16 5 5" /></>,
    list: <path d="M8 6h13M8 12h13M8 18h13M3 6h.01M3 12h.01M3 18h.01" />,
  };
  return <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor"
    strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
    {paths[name] ?? paths.grid}</svg>;
}
export function Brand() {
  const c = useCopy();
  return <Link to="/" className="brand" aria-label={c('Conatus, home', 'Conatus, inicio')}>
    <svg viewBox="0 0 32 32" width="30" height="30" aria-hidden="true">
      <path d="M23 6a12 12 0 1 0 0 20M21 11a6 6 0 1 0 0 10" fill="none"
        stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" />
      <circle cx="27" cy="16" r="2" fill="currentColor" />
    </svg><span>Conatus<span className="brand-period">.</span></span>
  </Link>;
}
export function PageHeader({ eyebrow, title, description }: {
  eyebrow?: string; title: string; description?: string }) {
  return <header className="page-header"><div>{eyebrow && <p className="eyebrow">{eyebrow}</p>}
    <h1 tabIndex={-1}>{title}</h1>{description && <p>{description}</p>}</div></header>;
}
