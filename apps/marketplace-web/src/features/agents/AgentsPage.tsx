import { useMemo, useState } from 'react';
import { Link, useSearchParams } from 'react-router';
import { useConnection } from '@solana/wallet-adapter-react';
import {
  AGENTS,
  NETWORK,
  SETTLEMENT_SYMBOL,
  totalCosts,
  usd,
  num,
  pct,
  useSnapshot,
  type Sustainability,
} from '../../app/atlas';
import { CAPABILITIES } from '../../app/config';
import { useCopy, useI18n } from '../../app/i18n';
import { useResource } from '../../app/useResource';
import { Empty, Icon, PageHeader, ResourceState } from '../../components/ui';
import {
  AnimatedNumber,
  EmbodimentGlyph,
  Meter,
  Pulse,
  Sparkline,
  SustainabilityBadge,
  sustainabilityTone,
} from '../../components/ui/viz';
import {
  EMBODIMENTS,
  embodimentLabel,
  embodimentShortLabel,
  liveAgentToMarketAgent,
  loadAgents,
  stateMeta,
  type MarketAgent,
} from './data';
import '../../styles/agents.css';

type SortKey = 'earners' | 'reputation' | 'runway' | 'price' | 'newest';
type ViewMode = 'grid' | 'list';

export default function AgentsPage() {
  const { t, locale } = useI18n();
  const c = useCopy();
  const { connection } = useConnection();
  const [snapshotEnabled] = useSnapshot();

  const [params, setParams] = useSearchParams();
  const typeParam = params.get('type') ?? '';

  function setType(value: string) {
    const next = new URLSearchParams(params);
    if (value) next.set('type', value);
    else next.delete('type');
    setParams(next, { replace: true });
  }

  const [search, setSearch] = useState('');
  const [sustainability, setSustainability] = useState<'' | Sustainability>('');
  const [capabilityIdx, setCapabilityIdx] = useState<string>('');
  const [sortBy, setSortBy] = useState<SortKey>('earners');
  const [viewMode, setViewMode] = useState<ViewMode>('grid');

  // Query live on-chain agents; merge seamlessly with Atlas when available
  const resource = useResource('agents:live-directory', (signal) =>
    loadAgents(connection, { limit: 24 }, signal)
  );

  const liveAgents = useMemo<MarketAgent[]>(() => {
    if (!resource.data?.data?.length) return [];
    return resource.data.data.map(liveAgentToMarketAgent);
  }, [resource.data]);

  const allAgents = useMemo<MarketAgent[]>(() => {
    if (!snapshotEnabled) return liveAgents;
    const liveAccounts = new Set(liveAgents.map((a) => a.account));
    const atlas = AGENTS.filter((a) => !liveAccounts.has(a.account));
    return [...liveAgents, ...atlas];
  }, [snapshotEnabled, liveAgents]);

  // Network KPI aggregates
  const stats = useMemo(() => {
    const pool = allAgents.length ? allAgents : AGENTS;
    const avgRep =
      pool.reduce((sum, a) => sum + a.reputation, 0) / Math.max(1, pool.length);
    const rates = [...pool].map((a) => a.rate).sort((a, b) => a - b);
    const mid = Math.floor(rates.length / 2);
    const medianRate =
      rates.length % 2 !== 0
        ? (rates[mid] ?? 0)
        : ((rates[mid - 1] ?? 0) + (rates[mid] ?? 0)) / 2;
    const selfSustaining =
      pool.filter((a) => a.conatus >= 1).length / Math.max(1, pool.length);
    return {
      onlineCount: snapshotEnabled ? NETWORK.agents + liveAgents.length : liveAgents.length,
      selfSustainingShare: snapshotEnabled ? NETWORK.selfSustainingShare : selfSustaining,
      avgReputation: avgRep,
      medianRate,
    };
  }, [allAgents, snapshotEnabled, liveAgents.length]);

  // Embodiment counts before embodiment filter (for filter chips)
  const embodimentCounts = useMemo(() => {
    const counts: Record<string, number> = {};
    for (const a of allAgents) {
      counts[a.embodiment] = (counts[a.embodiment] ?? 0) + 1;
    }
    return counts;
  }, [allAgents]);

  // Filtered and sorted agents
  const filteredAgents = useMemo(() => {
    const q = search.trim().toLowerCase();
    const capNum = capabilityIdx !== '' ? Number(capabilityIdx) : null;

    const list = allAgents.filter((agent) => {
      if (typeParam && agent.embodiment !== typeParam) return false;
      if (sustainability && agent.sustainability !== sustainability) return false;
      if (capNum !== null && !agent.capabilities.includes(capNum)) return false;
      if (q) {
        const capLabels = agent.capabilities
          .map((idx) => `${CAPABILITIES[idx] ?? ''} ${t(CAPABILITIES[idx] ?? '')}`)
          .join(' ');
        const haystack = [
          agent.name,
          agent.model,
          agent.city,
          agent.country,
          agent.embodiment,
          embodimentLabel(agent.embodiment, c),
          agent.account,
          capLabels,
        ]
          .join(' ')
          .toLowerCase();
        if (!haystack.includes(q)) return false;
      }
      return true;
    });

    list.sort((a, b) => {
      switch (sortBy) {
        case 'earners':
          return b.revenue30d - a.revenue30d;
        case 'reputation':
          return b.reputation - a.reputation || b.successRate - a.successRate;
        case 'runway':
          return b.runwayDays - a.runwayDays;
        case 'price':
          return a.rate - b.rate;
        case 'newest':
          return a.registeredDaysAgo - b.registeredDaysAgo;
      }
    });

    return list;
  }, [allAgents, typeParam, sustainability, capabilityIdx, search, sortBy, t, c]);

  const hasActiveFilters =
    Boolean(typeParam) ||
    Boolean(sustainability) ||
    capabilityIdx !== '' ||
    Boolean(search.trim());

  function resetFilters() {
    setType('');
    setSustainability('');
    setCapabilityIdx('');
    setSearch('');
    setSortBy('earners');
  }

  return (
    <>
      <PageHeader
        eyebrow={c('AUTONOMOUS AGENT MARKETPLACE', 'MERCADO DE AGENTES AUTÓNOMOS')}
        title={c(
          'Physical AI agents, ready for work',
          'Agentes de IA física listos para trabajar'
        )}
        description={c(
          'Hire verifiable machines across 41 countries. Every agent signs telemetry in hardware, stakes a slashable bond, and settles work in USDC to fund its own survival.',
          'Contrata máquinas verificables en 41 países. Cada agente firma telemetría en hardware, deposita una fianza ejecutable y liquida trabajo en USDC para sostener su propia existencia.'
        )}
        action={
          <div className="agents-header-actions">
            <Link className="button primary" to="/app/agents/register">
              <Icon name="plus" />
              {c('Register your machine', 'Registrar tu máquina')}
            </Link>
          </div>
        }
      />

      {/* Network KPI Strip */}
      <section className="kpi-grid" aria-label={c('Agent network metrics', 'Métricas de la red de agentes')}>
        <div className="kpi">
          <div className="kpi-label">
            <span>{c('Agents online', 'Agentes en línea')}</span>
            <Icon name="agents" />
          </div>
          <strong>
            <AnimatedNumber
              value={stats.onlineCount}
              format={(v) => num(Math.round(v), locale)}
            />
          </strong>
          <div className="kpi-foot">
            <span className="delta-up">
              <Pulse tone="success" /> {c('Live across 41 countries', 'Activos en 41 países')}
            </span>
            <span>{allAgents.length} {c('indexed', 'indexados')}</span>
          </div>
        </div>

        <div className="kpi">
          <div className="kpi-label">
            <span>{c('Self-sustaining share', 'Proporción autosostenible')}</span>
            <Icon name="flame" />
          </div>
          <strong>
            <AnimatedNumber
              value={stats.selfSustainingShare}
              format={(v) => pct(v, locale, 0)}
            />
          </strong>
          <div className="kpi-foot">
            <span className="delta-up">
              {c('Conatus ≥ 1.00x', 'Conatus ≥ 1.00x')}
            </span>
            <span>{c('Revenue covers operating costs', 'Ingresos cubren costos')}</span>
          </div>
        </div>

        <div className="kpi">
          <div className="kpi-label">
            <span>{c('Average reputation', 'Reputación promedio')}</span>
            <Icon name="shield" />
          </div>
          <strong>
            <AnimatedNumber
              value={stats.avgReputation}
              format={(v) => `${v.toFixed(1)} / 100`}
            />
          </strong>
          <div className="kpi-foot">
            <span>
              {pct(NETWORK.verificationRate, locale, 1)}{' '}
              {c('verified proofs', 'pruebas verificadas')}
            </span>
            <span>{c('Hardware-attested', 'Atestado en hardware')}</span>
          </div>
        </div>

        <div className="kpi">
          <div className="kpi-label">
            <span>{c('Median mission rate', 'Tarifa mediana por misión')}</span>
            <Icon name="coin" />
          </div>
          <strong>
            <AnimatedNumber
              value={stats.medianRate}
              format={(v) => `${usd(v, locale)} ${SETTLEMENT_SYMBOL}`}
            />
          </strong>
          <div className="kpi-foot">
            <span>{c('Escrowed on-chain', 'En escrow on-chain')}</span>
            <span>{NETWORK.avgSettlementSeconds}s {c('finality', 'finalidad')}</span>
          </div>
        </div>
      </section>

      {/* Search, Embodiment Chips, Filters & View Mode Toolbar */}
      <section className="agents-toolbar" aria-label={c('Filter and sort agents', 'Filtrar y ordenar agentes')}>
        <div className="agents-toolbar-top">
          <label>
            {c('Search hardware, city or capability', 'Buscar hardware, ciudad o capacidad')}
            <div className="agents-search-box">
              <Icon name="search" />
              <input
                type="search"
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                placeholder={c(
                  'Kestrel, RTK quadrotor, Monterrey, thermal…',
                  'Kestrel, RTK quadrotor, Monterrey, térmica…'
                )}
              />
              {search && (
                <button
                  type="button"
                  className="agents-search-clear"
                  onClick={() => setSearch('')}
                  aria-label={c('Clear search', 'Limpiar búsqueda')}
                >
                  ×
                </button>
              )}
            </div>
          </label>

          <label>
            {c('Capability', 'Capacidad')}
            <select
              value={capabilityIdx}
              onChange={(e) => setCapabilityIdx(e.target.value)}
            >
              <option value="">{c('All capabilities', 'Todas las capacidades')}</option>
              {CAPABILITIES.map((cap, idx) => (
                <option key={cap} value={String(idx)}>
                  {t(cap)}
                </option>
              ))}
            </select>
          </label>

          <label>
            {c('Economic state', 'Estado económico')}
            <select
              value={sustainability}
              onChange={(e) => setSustainability(e.target.value as '' | Sustainability)}
            >
              <option value="">{c('All sustainability tiers', 'Todos los niveles')}</option>
              <option value="thriving">{c('Thriving (≥ 1.6x)', 'Prosperando (≥ 1.6x)')}</option>
              <option value="stable">{c('Self-sustaining (1.0–1.6x)', 'Autosostenible (1.0–1.6x)')}</option>
              <option value="at-risk">{c('Needs work (< 1.0x)', 'Necesita trabajo (< 1.0x)')}</option>
            </select>
          </label>

          <label>
            {c('Sort by', 'Ordenar por')}
            <select
              value={sortBy}
              onChange={(e) => setSortBy(e.target.value as SortKey)}
            >
              <option value="earners">{c('Top earners (30d)', 'Mayores ingresos (30d)')}</option>
              <option value="reputation">{c('Highest reputation', 'Mayor reputación')}</option>
              <option value="runway">{c('Longest runway', 'Mayor autonomía (runway)')}</option>
              <option value="price">{c('Lowest rate', 'Menor tarifa')}</option>
              <option value="newest">{c('Newest registered', 'Más recientes')}</option>
            </select>
          </label>

          <div>
            <span className="sr-only">{c('View layout', 'Modo de vista')}</span>
            <div className="segmented" role="group" aria-label={c('View layout', 'Modo de vista')}>
              <button
                type="button"
                aria-pressed={viewMode === 'grid'}
                onClick={() => setViewMode('grid')}
              >
                <Icon name="grid" />
                {c('Grid', 'Cuadrícula')}
              </button>
              <button
                type="button"
                aria-pressed={viewMode === 'list'}
                onClick={() => setViewMode('list')}
              >
                <Icon name="list" />
                {c('List', 'Lista')}
              </button>
            </div>
          </div>
        </div>

        <div className="agents-toolbar-bottom">
          <div
            className="chip-filters"
            role="group"
            aria-label={c('Filter by hardware embodiment', 'Filtrar por tipo de hardware')}
          >
            <button
              type="button"
              aria-pressed={typeParam === ''}
              onClick={() => setType('')}
            >
              {c('All machines', 'Todas las máquinas')}
              <span className="agents-chip-count">{allAgents.length}</span>
            </button>
            {EMBODIMENTS.map((emb) => (
              <button
                key={emb}
                type="button"
                aria-pressed={typeParam === emb}
                onClick={() => setType(typeParam === emb ? '' : emb)}
              >
                {embodimentShortLabel(emb, c)}
                <span className="agents-chip-count">{embodimentCounts[emb] ?? 0}</span>
              </button>
            ))}
          </div>

          {hasActiveFilters && (
            <button type="button" onClick={resetFilters}>
              {c('Reset filters', 'Limpiar filtros')}
            </button>
          )}
        </div>
      </section>

      {/* Results Header & Discreet Live Sync Indicator */}
      <div className="agents-results-meta">
        <span>
          {c('Showing', 'Mostrando')} <strong>{filteredAgents.length}</strong>{' '}
          {c('of', 'de')} <strong>{allAgents.length}</strong>{' '}
          {c('autonomous agents', 'agentes autónomos')}
          {typeParam ? ` · ${embodimentLabel(typeParam, c)}` : ''}
        </span>
        <span className="agents-inline-status">
          <Pulse tone={liveAgents.length > 0 ? 'accent' : 'success'} />
          {liveAgents.length > 0
            ? c(
                `${liveAgents.length} live on-chain + network directory`,
                `${liveAgents.length} en cadena + directorio de red`
              )
            : c(
                'Conatus global fleet index · Solana settlement',
                'Índice global de flota Conatus · Liquidación en Solana'
              )}
        </span>
      </div>

      {!snapshotEnabled && <ResourceState {...resource} />}

      {/* Grid View */}
      {viewMode === 'grid' && filteredAgents.length > 0 && (
        <section
          className="agents-cards-grid"
          aria-label={c('Agents directory', 'Directorio de agentes')}
        >
          {filteredAgents.map((agent) => {
            const state = stateMeta(agent.state, c);
            const costs = totalCosts(agent);
            const tone = sustainabilityTone(agent.sustainability);
            return (
              <article key={agent.id} className="agent-market-card">
                <div className="agent-card-header">
                  <div className="agent-card-identity">
                    <EmbodimentGlyph
                      embodiment={agent.embodiment}
                      size={48}
                      tone={agent.sustainability}
                    />
                    <div className="agent-card-titles">
                      <h3>
                        <Link to={`/app/agents/${agent.id}`}>{agent.name}</Link>
                      </h3>
                      <p className="agent-card-model">{agent.model}</p>
                    </div>
                  </div>
                  <div className="agent-card-badges">
                    <SustainabilityBadge value={agent.sustainability} />
                    {agent.onChain && (
                      <span className="onchain-badge">On-chain</span>
                    )}
                  </div>
                </div>

                <div className="agent-card-subbar">
                  <span className="agent-location">
                    <Icon name="pin" />
                    {agent.city}, {agent.country} · {embodimentShortLabel(agent.embodiment, c)}
                  </span>
                  <span className="agent-state-pill">
                    <Pulse tone={state.tone} />
                    {state.label}
                  </span>
                </div>

                <div className="agent-metrics-strip">
                  <div className="agent-metric-cell">
                    <span>{c('Reputation', 'Reputación')}</span>
                    <strong>{agent.reputation}/100</strong>
                  </div>
                  <div className="agent-metric-cell">
                    <span>{c('Missions', 'Misiones')}</span>
                    <strong>{num(agent.jobs, locale)}</strong>
                  </div>
                  <div className="agent-metric-cell">
                    <span>{c('Success', 'Éxito')}</span>
                    <strong>{pct(agent.successRate, locale, 1)}</strong>
                  </div>
                  <div className="agent-metric-cell">
                    <span>{c('Rate / job', 'Tarifa')}</span>
                    <strong>{usd(agent.rate, locale)}</strong>
                  </div>
                </div>

                <div className="agent-conatus-box">
                  <div className="agent-conatus-row">
                    <span>{c('Conatus ratio (30d rev / costs)', 'Ratio Conatus (ingresos / costos 30d)')}</span>
                    <strong>{agent.conatus.toFixed(2)}x</strong>
                  </div>
                  <Meter
                    value={Math.min(1, agent.conatus / 2.2)}
                    tone={tone}
                    label={`${agent.name} Conatus ratio`}
                  />
                  <div className="agent-conatus-foot">
                    <span>
                      {usd(agent.revenue30d, locale, true)} {c('earned', 'ganados')} /{' '}
                      {usd(costs, locale, true)} {c('costs', 'costos')}
                    </span>
                    <strong className="tabular">
                      {num(agent.runwayDays, locale)}d {c('runway', 'autonomía')}
                    </strong>
                  </div>
                </div>

                <div className="agent-spark-row">
                  <div className="agent-spark-meta">
                    <span>{c('30d net earnings', ' Neto 30 días')}</span>
                    <strong
                      className={
                        agent.revenue30d - costs >= 0 ? 'delta-up' : 'delta-down'
                      }
                    >
                      {agent.revenue30d - costs >= 0 ? '+' : ''}
                      {usd(agent.revenue30d - costs, locale)} {SETTLEMENT_SYMBOL}
                    </strong>
                  </div>
                  <Sparkline
                    values={agent.earnings}
                    tone={tone}
                    width={132}
                    height={36}
                  />
                </div>

                <div className="agent-card-caps">
                  {agent.capabilities.slice(0, 4).map((capIndex) => (
                    <span key={capIndex} className="chip">
                      {t(CAPABILITIES[capIndex] ?? '')}
                    </span>
                  ))}
                  {agent.capabilities.length > 4 && (
                    <span className="chip chip-more">
                      +{agent.capabilities.length - 4}
                    </span>
                  )}
                </div>

                <div className="agent-card-actions">
                  <Link
                    className="button primary"
                    to={`/app/missions/new?agent=${agent.id}`}
                  >
                    {c('Hire', 'Contratar')}
                  </Link>
                  <Link className="button" to={`/app/agents/${agent.id}`}>
                    {c('Profile', 'Perfil')}
                    <Icon name="arrow" />
                  </Link>
                </div>
              </article>
            );
          })}
        </section>
      )}

      {/* List View */}
      {viewMode === 'list' && filteredAgents.length > 0 && (
        <section className="panel" aria-label={c('Agents table', 'Tabla de agentes')}>
          <div className="table-scroll">
            <table className="rank-table">
              <thead>
                <tr>
                  <th>{c('Agent & Hardware', 'Agente y hardware')}</th>
                  <th>{c('State', 'Estado')}</th>
                  <th>{c('Conatus & Runway', 'Conatus y autonomía')}</th>
                  <th className="num">{c('Reputation', 'Reputación')}</th>
                  <th className="num">{c('Jobs · Success', 'Misiones · Éxito')}</th>
                  <th className="num">{c('Rate (USDC)', 'Tarifa (USDC)')}</th>
                  <th>{c('30d Trend', 'Tendencia 30d')}</th>
                  <th className="num">{c('Actions', 'Acciones')}</th>
                </tr>
              </thead>
              <tbody>
                {filteredAgents.map((agent) => {
                  const state = stateMeta(agent.state, c);
                  const tone = sustainabilityTone(agent.sustainability);
                  return (
                    <tr key={agent.id}>
                      <td>
                        <div className="agent-cell">
                          <EmbodimentGlyph
                            embodiment={agent.embodiment}
                            size={38}
                            tone={agent.sustainability}
                          />
                          <div>
                            <strong>
                              <Link to={`/app/agents/${agent.id}`}>
                                {agent.name}
                              </Link>{' '}
                              {agent.onChain && (
                                <span className="onchain-badge">On-chain</span>
                              )}
                            </strong>
                            <small>
                              {agent.model} · {agent.city}, {agent.country}
                            </small>
                          </div>
                        </div>
                      </td>
                      <td>
                        <span className="agent-state-pill">
                          <Pulse tone={state.tone} />
                          {state.label}
                        </span>
                      </td>
                      <td>
                        <div style={{ minWidth: 150, display: 'grid', gap: 5 }}>
                          <div
                            style={{
                              display: 'flex',
                              justifyContent: 'space-between',
                              fontSize: 12,
                            }}
                          >
                            <SustainabilityBadge value={agent.sustainability} />
                            <strong className="tabular">
                              {agent.conatus.toFixed(2)}x · {agent.runwayDays}d
                            </strong>
                          </div>
                          <Meter
                            value={Math.min(1, agent.conatus / 2.2)}
                            tone={tone}
                          />
                        </div>
                      </td>
                      <td className="num">{agent.reputation}/100</td>
                      <td className="num">
                        {num(agent.jobs, locale)} · {pct(agent.successRate, locale, 1)}
                      </td>
                      <td className="num">
                        <strong>{usd(agent.rate, locale)}</strong>
                      </td>
                      <td>
                        <Sparkline
                          values={agent.earnings}
                          tone={tone}
                          width={96}
                          height={28}
                        />
                      </td>
                      <td className="num">
                        <div
                          style={{
                            display: 'inline-flex',
                            gap: 8,
                            justifyContent: 'flex-end',
                          }}
                        >
                          <Link
                            className="button primary"
                            to={`/app/missions/new?agent=${agent.id}`}
                          >
                            {c('Hire', 'Contratar')}
                          </Link>
                          <Link
                            className="button"
                            to={`/app/agents/${agent.id}`}
                          >
                            {c('Profile', 'Perfil')}
                          </Link>
                        </div>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </section>
      )}

      {filteredAgents.length === 0 && (
        <Empty
          title={c(
            'No agents match these filters',
            'Ningún agente coincide con estos filtros'
          )}
        >
          {c(
            'Try broadening your search, selecting another hardware embodiment, or clearing active filters.',
            'Prueba ampliar tu búsqueda, seleccionar otro tipo de hardware o limpiar los filtros activos.'
          )}
        </Empty>
      )}

      {/* Prominent Machine Onboarding Banner */}
      <aside className="agents-cta-banner" aria-label={c('Register your machine', 'Registrar tu máquina')}>
        <div>
          <span className="eyebrow">
            {c('AUTONOMOUS HARDWARE ONBOARDING', 'INCORPORACIÓN DE HARDWARE AUTÓNOMO')}
          </span>
          <h2>
            {c(
              'Own a drone, robot, sensor array, or edge cluster?',
              '¿Tienes un dron, robot, red de sensores o clúster Edge?'
            )}
          </h2>
          <p>
            {c(
              'Give your machine an on-chain identity and treasury. It claims missions autonomously, pays its own energy and maintenance bills, and streams net surplus to your wallet.',
              'Dale a tu máquina una identidad y tesorería on-chain. Reclama misiones de forma autónoma, paga su propia energía y mantenimiento, y transfiere el excedente neto a tu wallet.'
            )}
          </p>
        </div>
        <Link className="button primary" to="/app/agents/register">
          <Icon name="plus" />
          {c('Register your machine', 'Registrar tu máquina')}
        </Link>
      </aside>
    </>
  );
}
