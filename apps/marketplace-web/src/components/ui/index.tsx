import { useI18n } from '../../app/i18n';
import { useEffect, useState, type ReactNode } from 'react';
import { Link } from 'react-router';
import { capabilities, short } from '../../app/config';
export function Icon({ name = 'grid' }: { name?: string }) {
  const paths: Record<string, ReactNode> = {
    search: (
      <>
        <circle cx="10.5" cy="10.5" r="6.5" />
        <path d="m16 16 5 5" />
      </>
    ),
    sidebar: (
      <>
        <rect x="3" y="4" width="18" height="16" rx="2" />
        <path d="M9 4v16m5-11-3 3 3 3" />
      </>
    ),
    grid: (
      <>
        <rect x="3" y="3" width="7" height="7" rx="1.5" />
        <rect x="14" y="3" width="7" height="7" rx="1.5" />
        <rect x="3" y="14" width="7" height="7" rx="1.5" />
        <rect x="14" y="14" width="7" height="7" rx="1.5" />
      </>
    ),
    agents: (
      <>
        <path d="M8 3h8l5 9-5 9H8l-5-9Z" />
        <circle cx="12" cy="12" r="3" />
      </>
    ),
    missions: (
      <>
        <rect x="5" y="4" width="14" height="17" rx="2" />
        <path d="M9 3h6v4H9zM9 12h6M9 16h4" />
      </>
    ),
    wallet: (
      <>
        <path d="M20 7H5a2 2 0 0 1 0-4h13v4M4 7v13h16V7" />
        <path d="M20 12h-6v4h6" />
      </>
    ),
    activity: <path d="M2 12h5l3-8 4 16 3-8h5" />,
    settings: (
      <>
        <path d="M4 6h16M4 12h16M4 18h16" />
        <circle cx="9" cy="6" r="2" />
        <circle cx="16" cy="12" r="2" />
        <circle cx="9" cy="18" r="2" />
      </>
    ),
    arrow: <path d="M4 12h16m-6-6 6 6-6 6" />,
    plus: <path d="M12 5v14M5 12h14" />,
    menu: <path d="M4 6h16M4 12h16M4 18h16" />,
    close: <path d="m6 6 12 12M6 18 18 6" />,
    economy: (
      <>
        <path d="M3 20h18" />
        <path d="M6 16v-5m5 5V8m5 8v-3m4 3V5" />
      </>
    ),
    fleet: (
      <>
        <path d="m12 3 9 5-9 5-9-5Z" />
        <path d="m3 13 9 5 9-5" />
      </>
    ),
    bolt: <path d="M13 2 5 13h6l-1 9 8-11h-6Z" />,
    shield: (
      <>
        <path d="M12 3 4 6v6c0 5 3.5 8 8 9 4.5-1 8-4 8-9V6Z" />
        <path d="m9 12 2 2 4-4" />
      </>
    ),
    coin: (
      <>
        <circle cx="12" cy="12" r="8.5" />
        <path d="M14.5 9.5c-.4-1-1.4-1.5-2.5-1.5-1.5 0-2.5.8-2.5 2s1 1.6 2.5 2 2.5.8 2.5 2-1 2-2.5 2c-1.2 0-2.2-.6-2.6-1.6M12 6.5V8m0 8v1.5" />
      </>
    ),
    globe: (
      <>
        <circle cx="12" cy="12" r="9" />
        <path d="M3 12h18M12 3c2.5 2.7 3.8 5.7 3.8 9s-1.3 6.3-3.8 9c-2.5-2.7-3.8-5.7-3.8-9S9.5 5.7 12 3Z" />
      </>
    ),
    trophy: (
      <>
        <path d="M8 4h8v5a4 4 0 0 1-8 0Z" />
        <path d="M8 6H5a3 3 0 0 0 3 4m8-4h3a3 3 0 0 1-3 4M12 13v4m-4 3h8" />
      </>
    ),
    clock: (
      <>
        <circle cx="12" cy="12" r="9" />
        <path d="M12 7v5l3 2" />
      </>
    ),
    check: <path d="m5 12 5 5 9-10" />,
    spark: <path d="M12 3v4m0 10v4M3 12h4m10 0h4M6 6l2.5 2.5m7 7L18 18M6 18l2.5-2.5m7-7L18 6" />,
    cpu: (
      <>
        <rect x="6" y="6" width="12" height="12" rx="2" />
        <path d="M9 3v3m6-3v3M9 18v3m6-3v3M3 9h3m-3 6h3m12-6h3m-3 6h3" />
      </>
    ),
    pin: (
      <>
        <path d="M12 21s7-6 7-11a7 7 0 0 0-14 0c0 5 7 11 7 11Z" />
        <circle cx="12" cy="10" r="2.5" />
      </>
    ),
    eye: (
      <>
        <path d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7S2 12 2 12Z" />
        <circle cx="12" cy="12" r="3" />
      </>
    ),
    lock: (
      <>
        <rect x="5" y="11" width="14" height="10" rx="2" />
        <path d="M8 11V8a4 4 0 0 1 8 0v3" />
      </>
    ),
    wrench: <path d="M14.7 6.3a4 4 0 0 0-5.4 5.4L3 18l3 3 6.3-6.3a4 4 0 0 0 5.4-5.4l-2.5 2.5-2.5-2.5Z" />,
    wifi: (
      <>
        <path d="M2 9a15 15 0 0 1 20 0M5 12.5a10 10 0 0 1 14 0M8.5 16a5 5 0 0 1 7 0" />
        <circle cx="12" cy="19" r="1" />
      </>
    ),
    upload: <path d="M12 16V4m-5 5 5-5 5 5M4 20h16" />,
    download: <path d="M12 4v12m-5-5 5 5 5-5M4 20h16" />,
    flame: <path d="M12 21c-4 0-7-2.8-7-6.5 0-4 3.5-6 4.5-10 2 1.5 3 3.5 3 5.5 1-.7 1.6-1.8 1.8-3 2.4 1.9 3.7 4.6 3.7 7.5 0 3.7-2 6.5-6 6.5Z" />,
    target: (
      <>
        <circle cx="12" cy="12" r="9" />
        <circle cx="12" cy="12" r="5" />
        <circle cx="12" cy="12" r="1" />
      </>
    ),
    link: <path d="M10 14a4 4 0 0 0 5.7 0l3-3a4 4 0 0 0-5.7-5.7l-1 1M14 10a4 4 0 0 0-5.7 0l-3 3a4 4 0 0 0 5.7 5.7l1-1" />,
    filter: <path d="M4 5h16l-6 8v5l-4 2v-7Z" />,
    list: <path d="M8 6h13M8 12h13M8 18h13M3 6h.01M3 12h.01M3 18h.01" />,
    map: (
      <>
        <path d="m9 4-6 2v14l6-2 6 2 6-2V4l-6 2Z" />
        <path d="M9 4v14m6-12v14" />
      </>
    ),
    sun: (
      <>
        <circle cx="12" cy="12" r="4" />
        <path d="M12 2v2m0 16v2M2 12h2m16 0h2M5 5l1.5 1.5m11 11L19 19M5 19l1.5-1.5m11-11L19 5" />
      </>
    ),
    code: <path d="m8 7-5 5 5 5m8-10 5 5-5 5M14 4l-4 16" />,
  };
  return (
    <svg
      width="20"
      height="20"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.6"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      {paths[name] ?? paths.grid}
    </svg>
  );
}
export function Brand() {
  const { t } = useI18n();

  return (
    <Link to="/" className="brand" aria-label={t('Conatus, home')}>
      <svg viewBox="0 0 32 32" width="30" height="30" aria-hidden="true">
        <path
          d="M23 6a12 12 0 1 0 0 20M21 11a6 6 0 1 0 0 10"
          fill="none"
          stroke="currentColor"
          strokeWidth="1.8"
          strokeLinecap="round"
        />
        <circle cx="27" cy="16" r="2" fill="currentColor" />
      </svg>
      <span>
        Conatus<span className="brand-period">.</span>
      </span>
    </Link>
  );
}
export function PageHeader({
  eyebrow,
  title,
  description,
  action,
}: {
  eyebrow?: string;
  title: string;
  description?: string;
  action?: ReactNode;
}) {
  const { t } = useI18n();

  return (
    <header className="page-header">
      <div>
        {eyebrow && <p className="eyebrow">{eyebrow}</p>}
        <h1 tabIndex={-1}>{t(title)}</h1>
        {description && <p>{t(description)}</p>}
      </div>
      {action}
    </header>
  );
}
export function Empty({
  title,
  children,
}: {
  title: string;
  children?: ReactNode;
}) {
  return (
    <div className="empty-state">
      <div className="empty-icon">
        <Icon name="activity" />
      </div>
      <h3>{title}</h3>
      <p>{children}</p>
    </div>
  );
}
export function ResourceState({
  loading,
  error,
  reload,
}: {
  loading: boolean;
  error?: string;
  reload: () => void;
}) {
  const { t, locale } = useI18n();
  const c = (en: string, es: string) => (locale === 'es' ? es : en);

  if (loading)
    return (
      <div
        className="loading-state resource-loading"
        role="status"
        aria-live="polite"
      >
        <div className="loading-caption">
          <span className="loading-dot" />
          {c('Syncing with Solana network…', 'Sincronizando con la red Solana…')}
        </div>
        <div className="skeleton-lines" aria-hidden="true">
          <span />
          <span />
          <span />
        </div>
      </div>
    );
  if (error)
    return (
      <div className="error-state" role="alert">
        <h3>{t('No pudimos verificar los datos')}</h3>
        <p>
          {c(
            'Verify connectivity with the Solana RPC and protocol indexers, then try again.',
            'Comprueba la conexión con el RPC de Solana y los indexadores del protocolo, y vuelve a intentar.'
          )}
        </p>
        <details>
          <summary>{t('Diagnóstico')}</summary>
          <pre>{error}</pre>
        </details>
        <button onClick={reload}>{t('Reintentar lectura')}</button>
      </div>
    );
  return null;
}
export function Badge({ status }: { status: string }) {
  const { t } = useI18n();

  return (
    <span className={`badge status-${status.toLowerCase()}`}>{t(status)}</span>
  );
}
export function CopyAddress({
  value,
  label = 'Dirección',
}: {
  value: string;
  label?: string;
}) {
  const { t } = useI18n();

  const [message, setMessage] = useState('');
  useEffect(() => {
    if (!message) return;
    const timeout = window.setTimeout(() => setMessage(''), 2200);
    return () => window.clearTimeout(timeout);
  }, [message]);
  return (
    <span className="copy-address">
      <code title={value} translate="no">
        {short(value)}
      </code>
      <button
        type="button"
        aria-label={t('Copy {label}', { label: t(label) })}
        title={t('Copy {label}', { label: value })}
        onClick={async () => {
          try {
            await navigator.clipboard.writeText(value);
            setMessage('Copiado');
          } catch {
            setMessage('No se pudo copiar');
          }
        }}
      >
        {message === 'Copiado' ? '✓' : '⧉'}
      </button>
      <span className={message ? 'copy-feedback' : 'sr-only'} role="status">
        {t(message)}
      </span>
    </span>
  );
}
export function Capabilities({ mask }: { mask: string }) {
  const { t } = useI18n();

  const names = capabilities(mask);
  return (
    <div className="chips">
      {names.length ? (
        names.map((name) => (
          <span key={name} className="chip">
            {name.startsWith('extra:')
              ? t('Additional bits: {bits}', { bits: name.slice(6) })
              : t(name)}
          </span>
        ))
      ) : (
        <span className="muted">{t('Sin capacidades requeridas')}</span>
      )}
    </div>
  );
}
export function DataGrid({ items }: { items: [ReactNode, ReactNode][] }) {
  const { t } = useI18n();

  return (
    <dl className="data-grid">
      {items.map(([label, value], idx) => (
        <div key={typeof label === 'string' ? label : idx}>
          <dt>{typeof label === 'string' ? t(label) : label}</dt>
          <dd>{typeof value === 'string' ? t(value) : value}</dd>
        </div>
      ))}
    </dl>
  );
}
export function Diagnostics({ value }: { value: unknown }) {
  const { t } = useI18n();

  return (
    <details className="diagnostics">
      <summary>{t('Metadatos de lectura')}</summary>
      <pre>{JSON.stringify(value, null, 2)}</pre>
    </details>
  );
}

export { ProvenanceBadge } from './ProvenanceBadge';
export type { ProvenanceBadgeProps } from './ProvenanceBadge';
