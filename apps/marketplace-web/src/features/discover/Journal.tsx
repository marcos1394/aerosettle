import { useEffect, useState } from 'react';
import { Link, useParams, useSearchParams } from 'react-router';
import { useI18n } from '../../app/i18n';
import { articles } from './content';
import PublicLayout, { EditorialArt, useCopy } from './PublicLayout';

export default function Journal() {
  const { locale } = useI18n();
  const c = useCopy();
  const [params, setParams] = useSearchParams();
  const query = params.get('q') ?? '';
  const category = params.get('topic') ?? 'all';
  const filtered = articles.filter(
    (a) =>
      (category === 'all' || a.art === category) &&
      `${a.title[locale]} ${a.summary[locale]}`
        .toLocaleLowerCase(locale)
        .includes(query.trim().toLocaleLowerCase(locale))
  );
  const update = (key: string, value: string) => {
    const next = new URLSearchParams(params);
    if (value && value !== 'all') next.set(key, value);
    else next.delete(key);
    setParams(next, { replace: true, preventScrollReset: true });
  };
  return (
    <PublicLayout
      title="Journal"
      description={c(
        'Essays, field notes, and protocol architecture for the physical AI economy.',
        'Ensayos, notas de campo y arquitectura de protocolo para la economía de la IA física.'
      )}
    >
      <section className="discover-hero journal-hero">
        <span className="c-index">CONATUS JOURNAL / 01</span>
        <h1>
          {c('Thinking ahead.', 'Pensar en el futuro.')}
          <br />
          <em>{c('Working it out.', 'Darle forma.')}</em>
        </h1>
        <p>
          {c(
            'Essays, field notes, and protocol design for an economy where autonomous machines earn their keep.',
            'Ensayos, notas de campo y diseño de protocolo para una economía donde las máquinas autónomas se sostienen por su trabajo.'
          )}
        </p>
      </section>
      <section
        className="discover-body"
        aria-label={c('Journal articles', 'Artículos del journal')}
      >
        <div className="discovery-toolbar">
          <div className="filter-pills" aria-label={c('Topics', 'Temas')}>
            <button
              aria-pressed={category === 'all'}
              onClick={() => update('topic', 'all')}
            >
              {c('All stories', 'Todas las historias')}
            </button>
            {articles.map((a) => (
              <button
                key={a.art}
                aria-pressed={category === a.art}
                onClick={() => update('topic', a.art)}
              >
                {a.category[locale]}
              </button>
            ))}
          </div>
          <label className="discovery-search">
            <span>{c('Search stories', 'Buscar artículos')}</span>
            <input
              type="search"
              value={query}
              onChange={(e) => update('q', e.target.value)}
              placeholder={c('Find an idea…', 'Encuentra una idea…')}
            />
          </label>
        </div>
        <p className="result-count" role="status">
          {filtered.length} {c('stories', 'artículos')}
        </p>
        <div className="journal-grid">
          {filtered.map((a) => (
            <Link to={`/journal/${a.slug}`} className="story-card" key={a.slug}>
              <EditorialArt kind={a.art} />
              <div className="story-meta">
                <span>{a.category[locale]}</span>
                <span>
                  {Math.max(
                    1,
                    Math.ceil(
                      a.sections
                        .map((s) => s.body[locale])
                        .join(' ')
                        .split(/\s+/).length / 200
                    )
                  )}{' '}
                  {c('min read', 'min de lectura')}
                </span>
              </div>
              <h2>{a.title[locale]}</h2>
              <p>{a.summary[locale]}</p>
              <span className="story-arrow" aria-hidden="true">
                ↗
              </span>
            </Link>
          ))}
        </div>
        {!filtered.length && (
          <div className="discovery-empty">
            <h2>
              {c('No matching stories.', 'No hay artículos coincidentes.')}
            </h2>
            <button className="c-button" onClick={() => setParams({})}>
              {c('Clear filters', 'Limpiar filtros')}
            </button>
          </div>
        )}
      </section>
    </PublicLayout>
  );
}

export function Article() {
  const { slug } = useParams();
  const { locale } = useI18n();
  const c = useCopy();
  const article = articles.find((a) => a.slug === slug);
  const [progress, setProgress] = useState(0);
  useEffect(() => {
    let frame = 0;
    const update = () => {
      cancelAnimationFrame(frame);
      frame = requestAnimationFrame(() => {
        const el = document.querySelector('.article-content');
        if (!el) return;
        const r = el.getBoundingClientRect();
        setProgress(
          Math.min(
            100,
            Math.max(
              0,
              ((innerHeight - r.top) / (r.height + innerHeight)) * 100
            )
          )
        );
      });
    };
    update();
    addEventListener('scroll', update, { passive: true });
    addEventListener('resize', update);
    return () => {
      cancelAnimationFrame(frame);
      removeEventListener('scroll', update);
      removeEventListener('resize', update);
    };
  }, [slug, locale]);
  if (!article)
    return (
      <PublicLayout
        title={c('Story not found', 'Artículo no encontrado')}
        description="Conatus Journal"
      >
        <section className="discover-hero">
          <h1>{c('Story not found.', 'Artículo no encontrado.')}</h1>
          <Link className="c-button" to="/journal">
            {c('Back to the journal', 'Volver al journal')}
          </Link>
        </section>
      </PublicLayout>
    );
  return (
    <PublicLayout
      title={article.title[locale]}
      description={article.summary[locale]}
    >
      <div
        className="reading-progress"
        aria-hidden="true"
        style={{ transform: `scaleX(${progress / 100})` }}
      />
      <header className="article-heading">
        <Link to="/journal" className="c-text-link">
          ← {c('All stories', 'Todos los artículos')}
        </Link>
        <div className="story-meta">
          <span>{article.category[locale]}</span>
          <time dateTime="2026-10-17">
            {locale === 'en' ? 'October 17, 2026' : '17 de octubre de 2026'}
          </time>
        </div>
        <h1>{article.title[locale]}</h1>
        <p>{article.summary[locale]}</p>
        <span className="c-index">CONATUS JOURNAL</span>
      </header>
      <div className="article-layout">
        <aside>
          <span className="c-index">
            {c('IN THIS STORY', 'EN ESTE ARTÍCULO')}
          </span>
          <nav>
            {article.sections.map((s, i) => (
              <a href={`#section-${i}`} key={i}>
                {s.title[locale]}
              </a>
            ))}
          </nav>
          <EditorialArt kind={article.art} />
        </aside>
        <article className="article-content">
          {article.sections.map((s, i) => (
            <section id={`section-${i}`} key={i}>
              <h2>{s.title[locale]}</h2>
              <p>{s.body[locale]}</p>
            </section>
          ))}
          {article.sources.length > 0 && (
            <section className="article-sources">
              <h2>{c('Specifications & references', 'Especificaciones y referencias')}</h2>
              <p>
                {c(
                  'Foundational literature and protocol specifications referenced in the Conatus architecture.',
                  'Literatura fundacional y especificaciones de protocolo referenciadas en la arquitectura de Conatus.'
                )}
              </p>
              {article.sources.map((s) => (
                <a key={s.url} href={s.url} target="_blank" rel="noreferrer">
                  {s.label} ↗
                </a>
              ))}
            </section>
          )}
          <div className="article-next">
            <span className="c-index">
              {c('FROM IDEA TO EXECUTION', 'DE LA IDEA A LA EJECUCIÓN')}
            </span>
            <h2>
              {c(
                'Dispatch your next mission on-chain.',
                'Publica tu siguiente misión on-chain.'
              )}
            </h2>
            <div style={{ display: 'flex', gap: '16px', flexWrap: 'wrap' }}>
              <Link className="c-button c-button-primary" to="/app/missions/new">
                {c('Post a mission', 'Publicar una misión')} ↗
              </Link>
              <Link className="c-button" to="/app/planner">
                {c('Open mission planner', 'Abrir planificador')} ↗
              </Link>
            </div>
          </div>
        </article>
      </div>
    </PublicLayout>
  );
}

