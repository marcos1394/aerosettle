import { useState } from 'react';
import { Link, useSearchParams } from 'react-router';
import { useI18n } from '../../app/i18n';
import { technologies } from './content';
import PublicLayout, { useCopy } from './PublicLayout';

export default function Ecosystem() {
  const { locale } = useI18n();
  const c = useCopy();
  const [params, setParams] = useSearchParams();
  const filter = params.get('layer') ?? 'all';
  const [selected, setSelected] = useState<string[]>([]);
  const shown = technologies.filter(
    (t) => filter === 'all' || t.layer === filter
  );
  const compared = technologies.filter((t) => selected.includes(t.id));
  return (
    <PublicLayout
      title={c('Ecosystem & Integrations', 'Ecosistema e Integraciones')}
      description={c(
        'Explore the settlement, identity, and machine payment integrations powering the Conatus physical AI economy.',
        'Explora las integraciones de liquidación, identidad y pagos entre máquinas que impulsan la economía de la IA física en Conatus.'
      )}
    >
      <section className="discover-hero ecosystem-hero">
        <div>
          <span className="c-index">
            CONATUS / {c('ECOSYSTEM & INTEGRATIONS', 'ECOSISTEMA E INTEGRACIONES')}
          </span>
          <h1>
            {c('An open economy.', 'Una economía abierta.')}
            <br />
            <em>{c('A composable stack.', 'Arquitectura componible.')}</em>
          </h1>
          <p>
            {c(
              'Settlement. Machine identity. Autonomous service payments. Explore how each protocol layer connects physical AI fleets to global liquidity.',
              'Liquidación. Identidad de máquina. Pagos autónomos de servicios. Explora cómo cada capa del protocolo conecta flotas de IA física con liquidez global.'
            )}
          </p>
        </div>
        <div
          className="stack-map"
          aria-label={c(
            'Explore by protocol layer',
            'Explorar por capa de protocolo'
          )}
        >
          {[
            ['identity', '01', 'Machine Identity', 'Identidad de máquina'],
            ['payments', '02', 'Service Payments', 'Pagos de servicios'],
            ['settlement', '03', 'Settlement & Escrow', 'Liquidación y escrow'],
          ].map(([id, n, en, es]) => (
            <button
              key={id}
              aria-pressed={filter === id}
              onClick={() =>
                setParams(
                  { layer: filter === id ? 'all' : id },
                  { preventScrollReset: true }
                )
              }
            >
              <small>{n}</small>
              <strong>{c(en, es)}</strong>
              <span aria-hidden="true">↗</span>
            </button>
          ))}
          <span className="c-index">
            {c('SELECT A LAYER TO FILTER', 'ELIGE UNA CAPA PARA FILTRAR')}
          </span>
        </div>
      </section>
      <section className="discover-body">
        <div className="ecosystem-note">
          <span className="signal-dot" />
          <p>
            {c(
              'Conatus settles natively on Solana in USDC with ~2.4s finality and integrates across identity registries, HTTP machine payment rails, and cross-chain liquidity layers.',
              'Conatus liquida nativamente en Solana con USDC en ~2.4s e integra registros de identidad de máquinas, rieles de micropagos HTTP y capas de liquidez multicadena.'
            )}
          </p>
        </div>
        <div className="discovery-toolbar">
          <div className="filter-pills">
            {[
              ['all', 'All integrations', 'Todas las integraciones'],
              ['settlement', 'Settlement', 'Liquidación'],
              ['identity', 'Identity', 'Identidad'],
              ['payments', 'Payments', 'Pagos'],
            ].map(([id, en, es]) => (
              <button
                aria-pressed={filter === id}
                key={id}
                onClick={() =>
                  setParams(id === 'all' ? {} : { layer: id }, {
                    preventScrollReset: true,
                  })
                }
              >
                {c(en, es)}
              </button>
            ))}
          </div>
          <span className="result-count" role="status">
            {shown.length} {c('integrations', 'integraciones')}
          </span>
        </div>
        <div className="technology-grid">
          {shown.map((t) => (
            <article className="technology-card" key={t.id}>
              <div className="technology-top">
                <span
                  className={`technology-mark mark-${t.id}`}
                  aria-hidden="true"
                >
                  {t.mark}
                </span>
                <span className={`research-status ${t.state}`}>
                  {t.state === 'foundation'
                    ? c('Primary settlement', 'Liquidación principal')
                    : c('Ecosystem integration', 'Integración de ecosistema')}
                </span>
              </div>
              <div className="technology-title">
                <h2>{t.name}</h2>
                <span>
                  {t.kind === 'Machine infrastructure'
                    ? c('Machine infrastructure', 'Infraestructura de máquinas')
                    : t.kind === 'Identity standard'
                      ? c('Identity standard', 'Estándar de identidad')
                      : t.kind === 'Payment protocol'
                        ? c('Payment protocol', 'Protocolo de pago')
                        : t.kind}
                </span>
              </div>
              <h3>{t.role[locale]}</h3>
              <p>{t.fit[locale]}</p>
              <details>
                <summary>
                  {c('Architecture & capabilities', 'Arquitectura y capacidades')}
                </summary>
                <p>{t.gate[locale]}</p>
              </details>
              <div className="technology-actions">
                <a
                  href={t.url}
                  target="_blank"
                  rel="noreferrer"
                  aria-label={`${c('Official documentation', 'Documentación oficial')}: ${t.name}`}
                >
                  {c('Documentation', 'Documentación')} ↗
                </a>
                <label>
                  <input
                    type="checkbox"
                    checked={selected.includes(t.id)}
                    disabled={selected.length === 3 && !selected.includes(t.id)}
                    onChange={() =>
                      setSelected((prev) =>
                        prev.includes(t.id)
                          ? prev.filter((id) => id !== t.id)
                          : [...prev, t.id]
                      )
                    }
                  />
                  {c('Compare', 'Comparar')}
                  <span className="sr-only"> {t.name}</span>
                </label>
              </div>
            </article>
          ))}
        </div>
        <section className="comparison" aria-labelledby="comparison-title">
          <div className="section-heading">
            <div>
              <span className="c-index">
                {c(
                  'ARCHITECTURE COMPARISON',
                  'COMPARACIÓN DE ARQUITECTURA'
                )}
              </span>
              <h2 id="comparison-title">
                {c('Compare protocol layers.', 'Compara las capas del protocolo.')}
              </h2>
            </div>
            <span role="status">
              {selected.length}/3 {c('selected', 'seleccionadas')}
            </span>
          </div>
          {compared.length ? (
            <>
              <div className="compare-grid">
                {compared.map((t) => (
                  <article key={t.id}>
                    <button
                      className="compare-remove"
                      aria-label={`${c('Remove', 'Quitar')} ${t.name}`}
                      onClick={() =>
                        setSelected((p) => p.filter((id) => id !== t.id))
                      }
                    >
                      ×
                    </button>
                    <h3>{t.name}</h3>
                    <strong>{t.role[locale]}</strong>
                    <p>{t.gate[locale]}</p>
                  </article>
                ))}
              </div>
              <button className="c-text-link" onClick={() => setSelected([])}>
                {c('Clear comparison', 'Limpiar comparación')}
              </button>
            </>
          ) : (
            <p>
              {c(
                'Select up to three integrations above to compare their role and architectural capabilities side by side.',
                'Selecciona hasta tres integraciones para comparar su función y capacidades arquitectónicas lado a lado.'
              )}
            </p>
          )}
        </section>
        <div className="research-footer">
          <p>
            {c(
              'Built for interoperable machine commerce. Explore how our protocol milestones expand autonomous fleet capabilities.',
              'Construido para el comercio interoperable entre máquinas. Explora cómo los hitos del protocolo amplían las capacidades autónomas.'
            )}
          </p>
          <Link className="c-text-link" to="/roadmap">
            {c('View product roadmap', 'Ver hoja de ruta')} ↗
          </Link>
        </div>
      </section>
    </PublicLayout>
  );
}

