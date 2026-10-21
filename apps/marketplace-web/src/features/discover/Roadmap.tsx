import { Link } from 'react-router';
import { useI18n } from '../../app/i18n';
import { Pulse } from '../../components/ui/viz';
import { roadmap } from './content';
import PublicLayout, { useCopy } from './PublicLayout';

export default function Roadmap() {
  const { locale } = useI18n();
  const c = useCopy();
  return (
    <PublicLayout
      title={c('Product Roadmap', 'Hoja de ruta')}
      description={c(
        'Protocol milestones across settlement, autonomous agent treasuries, reputation bonds, and planetary scale.',
        'Hitos del protocolo en liquidación, tesorerías autónomas de agentes, garantías de reputación y escala global.'
      )}
    >
      <section className="discover-hero">
        <span className="c-index">
          CONATUS / {c('PRODUCT ROADMAP', 'HOJA DE RUTA DEL PROTOCOLO')}
        </span>
        <h1>
          {c('Built for what', 'Construido para lo que')}
          <br />
          <em>{c('persists.', 'persiste.')}</em>
        </h1>
        <p>
          {c(
            'From live on-chain settlement on Solana to self-sustaining agent treasuries, slashable SLA bonds, and mutualized fleet insurance.',
            'Desde la liquidación on-chain activa en Solana hasta tesorerías autónomas de agentes, garantías ejecutables y seguros mutualizados de flota.'
          )}
        </p>
        <div className="roadmap-summary" aria-label={c('Milestone summary', 'Resumen de hitos')}>
          <div className="roadmap-summary-pill is-shipped">
            <Pulse tone="accent" />
            <span>{c('Shipped · Core Protocol & Settlement', 'En producción · Protocolo base y liquidación')}</span>
          </div>
          <div className="roadmap-summary-pill is-progress">
            <Pulse tone="success" />
            <span>{c('In progress · Treasuries, SDK & Bonds', 'En curso · Tesorerías, SDK y garantías')}</span>
          </div>
          <div className="roadmap-summary-pill is-next">
            <span className="roadmap-dot-next" aria-hidden="true" />
            <span>{c('Next · Insurance Pools & Multi-Asset Mainnet', 'Próximo · Fondos de seguro y Mainnet multiactivo')}</span>
          </div>
        </div>
      </section>
      <section className="roadmap-list discover-body">
        {roadmap.map((r, i) => (
          <article className={`roadmap-row roadmap-row-${r.status}`} key={i}>
            <div className="roadmap-marker">
              <span>0{i + 1}</span>
              <small className={`roadmap-stage-badge stage-${r.status}`}>
                {r.stage[locale]}
              </small>
            </div>
            <div>
              <h2>{r.title[locale]}</h2>
              <p>{r.body[locale]}</p>
              <ul>
                {r.items.map((item) => (
                  <li key={item.en}>{item[locale]}</li>
                ))}
              </ul>
              <details open={i === 0}>
                <summary>
                  {c('Architecture & enforcement', 'Arquitectura y garantías')}
                </summary>
                <p>{r.gate[locale]}</p>
              </details>
              {r.link && (
                <Link className="c-text-link" to={r.link}>
                  {r.linkLabel
                    ? r.linkLabel[locale]
                    : c('Explore in app', 'Explorar en la app')}{' '}
                  <span aria-hidden="true">↗</span>
                </Link>
              )}
            </div>
          </article>
        ))}
        <div className="research-footer">
          <p>
            {c(
              'Ready to deploy physical capability or dispatch a verifiable work order today? Launch the Conatus marketplace.',
              '¿Listo para desplegar capacidad física o publicar una orden de trabajo verificable hoy mismo? Abre el mercado de Conatus.'
            )}
          </p>
          <Link className="c-button c-button-primary c-button-small" to="/app">
            {c('Launch app', 'Abrir app')} <span aria-hidden="true">↗</span>
          </Link>
        </div>
      </section>
    </PublicLayout>
  );
}

