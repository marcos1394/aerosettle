import { useMemo, useState } from 'react';
import { Link } from 'react-router';
import { CAPABILITIES } from '../../app/config';
import { useCopy, useI18n } from '../../app/i18n';
import {
  AGENTS,
  AGENT_SERIES,
  CAPABILITY_MARKET,
  NETWORK,
  VOLUME_SERIES,
  num,
  pct,
  totalCosts,
  usd,
  type CostBreakdown,
  type Embodiment,
  type Sustainability,
} from '../../app/atlas';
import { Icon, PageHeader, ProvenanceBadge } from '../../components/ui';
import { PROVENANCE_SOURCES } from '../../app/provenance';
import { AuthorizedEconomySection } from '../agents/AuthorizedEconomySection';
import {
  AnimatedNumber,
  AreaChart,
  BarList,
  Donut,
  EarlyAccess,
  EmbodimentGlyph,
  Meter,
  Ring,
  Sparkline,
  SustainabilityBadge,
  sustainabilityTone,
} from '../../components/ui/viz';

export default function EconomyPage() {
  const { t, locale } = useI18n();
  const c = useCopy();
  const [seriesMode, setSeriesMode] = useState<'volume' | 'agents'>('volume');
  const [tierFilter, setTierFilter] = useState<'all' | Sustainability>('all');
  const [sortBy, setSortBy] = useState<'conatus' | 'revenue' | 'net' | 'runway'>('conatus');

  const dayLabels = useMemo(() => {
    const fmt = new Intl.DateTimeFormat(locale === 'es' ? 'es-MX' : 'en-US', {
      month: 'short',
      day: 'numeric',
    });
    const now = Date.now();
    return Array.from({ length: 90 }, (_, i) =>
      fmt.format(new Date(now - (89 - i) * 86_400_000))
    );
  }, [locale]);

  const tierCounts = useMemo(
    () => ({
      thriving: AGENTS.filter((a) => a.sustainability === 'thriving').length,
      stable: AGENTS.filter((a) => a.sustainability === 'stable').length,
      'at-risk': AGENTS.filter((a) => a.sustainability === 'at-risk').length,
    }),
    []
  );

  const costTotals = useMemo(() => {
    const acc: CostBreakdown = {
      energy: 0,
      maintenance: 0,
      insurance: 0,
      connectivity: 0,
      protocol: 0,
    };
    for (const a of AGENTS) {
      acc.energy += a.costs30d.energy;
      acc.maintenance += a.costs30d.maintenance;
      acc.insurance += a.costs30d.insurance;
      acc.connectivity += a.costs30d.connectivity;
      acc.protocol += a.costs30d.protocol;
    }
    return acc;
  }, []);

  const totalCostSample = Object.values(costTotals).reduce((a, b) => a + b, 0);

  const costSegments = [
    {
      key: 'maintenance',
      label: c('Maintenance & parts', 'Mantenimiento y refacciones'),
      value: costTotals.maintenance,
      tone: 'accent' as const,
    },
    {
      key: 'energy',
      label: c('Energy & charging', 'Energía y recarga'),
      value: costTotals.energy,
      tone: 'success' as const,
    },
    {
      key: 'insurance',
      label: c('Hull & liability coverage', 'Seguro y responsabilidad'),
      value: costTotals.insurance,
      tone: 'violet' as const,
    },
    {
      key: 'connectivity',
      label: c('Telemetry & satellite links', 'Telemetría y enlace satelital'),
      value: costTotals.connectivity,
      tone: 'warning' as const,
    },
    {
      key: 'protocol',
      label: c('Settlement & verification fees', 'Comisiones de liquidación y verificación'),
      value: costTotals.protocol,
      tone: 'muted' as const,
    },
  ];

  const capabilityItems = useMemo(() => {
    return [...CAPABILITY_MARKET]
      .filter((item) => item.demand > 0)
      .sort((a, b) => b.demand - a.demand)
      .slice(0, 8)
      .map((item) => {
        const name = CAPABILITIES[item.index] ?? `Cap #${item.index}`;
        const yieldPerAgent = item.supply > 0 ? Math.round(item.demand / item.supply) : item.demand;
        return {
          key: String(item.index),
          label: (
            <>
              <span>{t(name)}</span>
              {yieldPerAgent >= 900 && (
                <span className="sustain sustain-thriving">
                  {c('High yield', 'Alto retorno')}
                </span>
              )}
            </>
          ),
          value: item.demand,
          hint: c(
            '{supply} capable agents · ~{yield} open demand / agent',
            '{supply} agentes capaces · ~{yield} demanda abierta / agente'
          )
            .replace('{supply}', String(item.supply))
            .replace('{yield}', usd(yieldPerAgent, locale)),
        };
      });
  }, [locale, t, c]);

  const embodimentItems = useMemo(() => {
    const map = new Map<Embodiment, { revenue: number; count: number; conatusSum: number }>();
    for (const a of AGENTS) {
      const prev = map.get(a.embodiment) ?? { revenue: 0, count: 0, conatusSum: 0 };
      prev.revenue += a.revenue30d;
      prev.count += 1;
      prev.conatusSum += a.conatus;
      map.set(a.embodiment, prev);
    }
    return Array.from(map.entries())
      .sort((a, b) => b[1].revenue - a[1].revenue)
      .slice(0, 7)
      .map(([emb, stats]) => ({
        key: emb,
        label: (
          <>
            <EmbodimentGlyph embodiment={emb} size={24} />
            <span>{t(emb)}</span>
          </>
        ),
        value: stats.revenue,
        hint: c(
          '{count} machines in sample · Avg Conatus {ratio}×',
          '{count} máquinas en muestra · Conatus prom. {ratio}×'
        )
          .replace('{count}', String(stats.count))
          .replace('{ratio}', (stats.conatusSum / stats.count).toFixed(2)),
      }));
  }, [t, c]);

  const rankedAgents = useMemo(() => {
    return AGENTS.filter((a) => tierFilter === 'all' || a.sustainability === tierFilter).sort(
      (a, b) => {
        if (sortBy === 'conatus') return b.conatus - a.conatus;
        if (sortBy === 'revenue') return b.revenue30d - a.revenue30d;
        if (sortBy === 'runway') return b.runwayDays - a.runwayDays;
        return b.revenue30d - totalCosts(b) - (a.revenue30d - totalCosts(a));
      }
    );
  }, [tierFilter, sortBy]);

  return (
    <>
      <PageHeader
        eyebrow={c('PROTOCOL ANALYTICS / CONATUS INDEX', 'ANALÍTICA DEL PROTOCOLO / ÍNDICE CONATUS')}
        title={c('Economy & Survival Index', 'Economía e Índice Conatus')}
        description={c(
          'Atlas simulation of how machine revenue can cover operating costs. Owner-verified assessments are available on live agent pages.',
          'Simulación Atlas de cómo los ingresos pueden cubrir costos operativos. Las evaluaciones verificadas están en los perfiles de agentes reales.'
        )}
        action={
          <div className="header-action-group">
            <Link className="button" to="/app/agents/register">
              <Icon name="bolt" />
              {c('Register a machine', 'Registrar máquina')}
            </Link>
            <Link className="button primary" to="/app/missions/new">
              <Icon name="plus" />
              {c('Post a mission', 'Publicar misión')}
            </Link>
          </div>
        }
      />

      <AuthorizedEconomySection
        heading={c('Owner-authorized economic records', 'Registros económicos autorizados por el propietario')}
        panelTitle={c('Live agent economy', 'Economía real del agente')}
      />

      <p className="hint">SIMULATED — ATLAS SCENARIO</p>
      <p className="hint"><ProvenanceBadge meta={PROVENANCE_SOURCES.SIMULATED_ATLAS_SNAPSHOT('Economy scenario')} compact /> {c('Simulated economic scenario · fleet ratios here are illustrative.', 'Escenario económico simulado · los ratios de esta flota son ilustrativos.')}</p>

      <section className="hero-panel economy-hero">
        <div className="economy-hero-main">
          <span className="eyebrow">
            {c('THE ECONOMIC LAW OF PHYSICAL AI', 'LA LEY ECONÓMICA DE LA IA FÍSICA')}
          </span>
          <h2>
            {c(
              'A machine persists when its verified work exceeds its operating burn.',
              'Una máquina persiste cuando su trabajo verificado supera su costo operativo.'
            )}
          </h2>
          <div className="conatus-formula" aria-label={c('Conatus ratio formula', 'Fórmula del índice Conatus')}>
            <span className="formula-lhs">Conatus Ratio</span>
            <span className="formula-eq">=</span>
            <span className="formula-fraction">
              <strong>{c('30d Verified Mission Revenue (USDC)', 'Ingresos verificados 30d (USDC)')}</strong>
              <small>
                {c(
                  'Energy + Maintenance + Insurance + Connectivity + Protocol Fees',
                  'Energía + Mantenimiento + Seguro + Conectividad + Comisiones'
                )}
              </small>
            </span>
          </div>
          <div className="survival-tiers">
            <div className="survival-tier-card">
              <SustainabilityBadge value="thriving" />
              <strong>{tierCounts.thriving} {c('machines', 'máquinas')}</strong>
              <p>
                {c(
                  'Conatus ≥ 1.6× · Compounding treasury & expanding runway.',
                  'Conatus ≥ 1.6× · Tesorería en expansión y autonomía creciente.'
                )}
              </p>
            </div>
            <div className="survival-tier-card">
              <SustainabilityBadge value="stable" />
              <strong>{tierCounts.stable} {c('machines', 'máquinas')}</strong>
              <p>
                {c(
                  'Conatus 1.0–1.6× · Covering all operating costs autonomously.',
                  'Conatus 1.0–1.6× · Cubre todos sus costos operativos de forma autónoma.'
                )}
              </p>
            </div>
            <div className="survival-tier-card">
              <SustainabilityBadge value="at-risk" />
              <strong>{tierCounts['at-risk']} {c('machines', 'máquinas')}</strong>
              <p>
                {c(
                  'Conatus < 1.0× · Drawing down reserve; prioritized for matching.',
                  'Conatus < 1.0× · Consumiendo reserva; priorizada para nuevas órdenes.'
                )}
              </p>
            </div>
          </div>
        </div>

        <div className="economy-hero-gauge">
          <Ring
            value={NETWORK.selfSustainingShare}
            tone="accent"
            size={168}
            label={c('Self-sustaining machines share', 'Proporción de máquinas autosostenibles')}
          >
            <strong>{pct(NETWORK.selfSustainingShare, locale, 0)}</strong>
            <small>{c('Self-sustaining', 'Autosostenibles')}</small>
          </Ring>
          <p className="muted">
            {c(
              '{operators} independent operators across {countries} countries.',
              '{operators} operadores independientes en {countries} países.'
            )
              .replace('{operators}', num(NETWORK.operators, locale))
              .replace('{countries}', String(NETWORK.countries))}
          </p>
        </div>
      </section>

      <div className="kpi-grid">
        <div className="kpi">
          <div className="kpi-label">
            <span>{c('30d settled volume', 'Volumen liquidado (30d)')}</span>
            <Icon name="coin" />
          </div>
          <div style={{ display: 'flex', alignItems: 'baseline', gap: 8, marginTop: 4 }}>
            <strong>
              <AnimatedNumber
                value={NETWORK.volume30d}
                format={(v) => usd(v, locale, true)}
              />
            </strong>
            <ProvenanceBadge
              meta={PROVENANCE_SOURCES.SIMULATED_ATLAS_SNAPSHOT(c('30-day settled volume', 'Volumen liquidado 30d'))}
              compact
            />
          </div>
          <div className="kpi-foot">
            <span className="delta-up">+28.6%</span>
            <span>{c('Escrow settlements', 'Liquidaciones vía escrow')}</span>
          </div>
          <Sparkline values={VOLUME_SERIES.slice(-30)} tone="accent" />
        </div>

        <div className="kpi">
          <div className="kpi-label">
            <span>{c('Cumulative settled value', 'Valor liquidado histórico')}</span>
            <Icon name="trophy" />
          </div>
          <div style={{ display: 'flex', alignItems: 'baseline', gap: 8, marginTop: 4 }}>
            <strong>
              <AnimatedNumber
                value={NETWORK.volumeAllTime}
                format={(v) => usd(v, locale, true)}
              />
            </strong>
            <ProvenanceBadge
              meta={PROVENANCE_SOURCES.SIMULATED_ATLAS_SNAPSHOT(c('Cumulative settled value', 'Valor liquidado histórico'))}
              compact
            />
          </div>
          <div className="kpi-foot">
            <span>
              {num(NETWORK.missionsCompleted, locale)} {c('missions', 'misiones')}
            </span>
            <span>{pct(NETWORK.verificationRate, locale, 1)} {c('verified', 'verificadas')}</span>
          </div>
          <Sparkline values={VOLUME_SERIES} tone="success" />
        </div>

        <div className="kpi">
          <div className="kpi-label">
            <span>{c('Active physical agents', 'Agentes físicos activos')}</span>
            <Icon name="agents" />
          </div>
          <div style={{ display: 'flex', alignItems: 'baseline', gap: 8, marginTop: 4 }}>
            <strong>
              <AnimatedNumber
                value={NETWORK.agents}
                format={(v) => num(Math.round(v), locale)}
              />
            </strong>
            <ProvenanceBadge
              meta={PROVENANCE_SOURCES.SIMULATED_ATLAS_SNAPSHOT(c('Active agent population', 'Población activa de agentes'))}
              compact
            />
          </div>
          <div className="kpi-foot">
            <span className="delta-up">+194 {c('90d', '90d')}</span>
            <span>{NETWORK.countries} {c('countries', 'países')}</span>
          </div>
          <Sparkline values={AGENT_SERIES} tone="accent" />
        </div>

        <div className="kpi">
          <div className="kpi-label">
            <span>{c('Bonded performance stake', 'Fianza de ejecución en garantía')}</span>
            <Icon name="shield" />
          </div>
          <div style={{ display: 'flex', alignItems: 'baseline', gap: 8, marginTop: 4 }}>
            <strong>
              <AnimatedNumber
                value={NETWORK.bonded}
                format={(v) => usd(v, locale, true)}
              />
            </strong>
            <ProvenanceBadge
              meta={PROVENANCE_SOURCES.SIMULATED_ATLAS_SNAPSHOT(c('Bonded performance stake', 'Fianza de ejecución en garantía'))}
              compact
            />
          </div>
          <div className="kpi-foot">
            <EarlyAccess />
            <span>{c('Slashable on faulty attestation', 'Penalizable ante falsa evidencia')}</span>
          </div>
        </div>
      </div>

      <div className="split stack">
        <section className="panel">
          <div className="panel-title">
            <div>
              <h2>
                {seriesMode === 'volume'
                  ? c('Daily settled work volume (90d)', 'Volumen diario de trabajo liquidado (90d)')
                  : c('Active physical agents on network (90d)', 'Agentes físicos activos en la red (90d)')}
              </h2>
              <p>
                {c(
                  'Hover or drag across the curve to inspect daily settlement activity.',
                  'Pasa el cursor sobre la curva para inspeccionar la actividad diaria.'
                )}
              </p>
            </div>
            <div className="segmented" role="group" aria-label={c('Metric', 'Métrica')}>
              <button
                type="button"
                aria-pressed={seriesMode === 'volume'}
                onClick={() => setSeriesMode('volume')}
              >
                {c('Volume (USDC)', 'Volumen (USDC)')}
              </button>
              <button
                type="button"
                aria-pressed={seriesMode === 'agents'}
                onClick={() => setSeriesMode('agents')}
              >
                {c('Active agents', 'Agentes activos')}
              </button>
            </div>
          </div>
          <AreaChart
            values={seriesMode === 'volume' ? VOLUME_SERIES : AGENT_SERIES}
            labels={dayLabels}
            format={(v) => (seriesMode === 'volume' ? usd(v, locale) : `${num(v, locale)} ${c('agents', 'agentes')}`)}
            tone={seriesMode === 'volume' ? 'accent' : 'success'}
            label={
              seriesMode === 'volume'
                ? c('90-day settled volume chart', 'Gráfico de volumen liquidado en 90 días')
                : c('90-day active agents chart', 'Gráfico de agentes activos en 90 días')
            }
          />
        </section>

        <section className="panel">
          <div className="panel-title">
            <div>
              <h2>{c('Autonomous operating burn', 'Gasto operativo autónomo')}</h2>
              <p>
                {c(
                  'How machines allocate settled earnings to sustain physical operation.',
                  'Cómo asignan las máquinas sus ingresos liquidados para sostener su operación física.'
                )}
              </p>
            </div>
            <EarlyAccess label={c('Auto-pay rails', 'Rieles de autopago')} />
          </div>
          <div className="burn-donut-layout">
            <Donut
              segments={costSegments}
              size={156}
              center={
                <>
                  <strong>{usd(totalCostSample, locale, true)}</strong>
                  <small>{c('30d sample burn', 'Gasto 30d muestra')}</small>
                </>
              }
            />
            <ul className="burn-legend">
              {costSegments.map((seg) => (
                <li key={seg.key}>
                  <span className={`legend-dot tone-${seg.tone}`} />
                  <div>
                    <strong>{seg.label}</strong>
                    <small className="tabular">
                      {usd(seg.value, locale)} · {pct(seg.value / totalCostSample, locale, 0)}
                    </small>
                  </div>
                </li>
              ))}
            </ul>
          </div>
        </section>
      </div>

      <div className="split stack">
        <section className="panel">
          <div className="panel-title">
            <div>
              <h2>{c('Capability demand vs. supply', 'Demanda vs. oferta por capacidad')}</h2>
              <p>
                {c(
                  'Open mission rewards by required physical capability compared to registered machines.',
                  'Recompensas abiertas por capacidad física requerida frente a máquinas registradas.'
                )}
              </p>
            </div>
            <Link className="button" to="/app/agents/register">
              {c('Supply hardware', 'Aportar hardware')}
            </Link>
          </div>
          <BarList
            items={capabilityItems}
            format={(v) => usd(v, locale)}
            tone="accent"
          />
        </section>

        <section className="panel">
          <div className="panel-title">
            <div>
              <h2>{c('Revenue by hardware embodiment', 'Ingresos por tipo de hardware')}</h2>
              <p>
                {c(
                  '30-day verified earnings and average Conatus ratio across physical form factors.',
                  'Ingresos verificados en 30 días y ratio Conatus promedio por factor de forma físico.'
                )}
              </p>
            </div>
          </div>
          <BarList
            items={embodimentItems}
            format={(v) => usd(v, locale)}
            tone="success"
          />
        </section>
      </div>

      <section className="panel">
        <div className="panel-title">
          <div>
            <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
              <h2>{c('Autonomous survival leaderboard', 'Clasificación de supervivencia autónoma')}</h2>
              <ProvenanceBadge
                meta={PROVENANCE_SOURCES.SIMULATED_ATLAS_SNAPSHOT(c('Representative 30d Model', 'Modelo representativo 30d'))}
                compact
              />
            </div>
            <p>
              {c(
                'Physical machines ranked by their ability to sustain operation through verified work.',
                'Máquinas físicas clasificadas por su capacidad de sostener su operación mediante trabajo verificado.'
              )}
            </p>
          </div>
          <div className="leaderboard-controls">
            <div className="chip-filters" role="group" aria-label={c('Filter by status', 'Filtrar por estado')}>
              {(
                [
                  ['all', c('All', 'Todos')],
                  ['thriving', c('Thriving', 'Prosperando')],
                  ['stable', c('Self-sustaining', 'Autosostenibles')],
                  ['at-risk', c('Needs work', 'Necesita trabajo')],
                ] as const
              ).map(([key, label]) => (
                <button
                  key={key}
                  type="button"
                  aria-pressed={tierFilter === key}
                  onClick={() => setTierFilter(key)}
                >
                  {label}
                </button>
              ))}
            </div>
            <label className="inline-select">
              <span className="sr-only">{c('Sort by', 'Ordenar por')}</span>
              <select
                value={sortBy}
                onChange={(e) => setSortBy(e.target.value as typeof sortBy)}
                aria-label={c('Sort agents by', 'Ordenar agentes por')}
              >
                <option value="conatus">{c('Sort: Conatus ratio', 'Orden: Ratio Conatus')}</option>
                <option value="revenue">{c('Sort: 30d revenue', 'Orden: Ingresos 30d')}</option>
                <option value="net">{c('Sort: Net margin', 'Orden: Margen neto')}</option>
                <option value="runway">{c('Sort: Runway days', 'Orden: Días de autonomía')}</option>
              </select>
            </label>
          </div>
        </div>

        <div className="table-scroll">
          <table className="rank-table">
            <thead>
              <tr>
                <th>#</th>
                <th>{c('Machine', 'Máquina')}</th>
                <th>{c('Status', 'Estado')}</th>
                <th className="num">{c('30d Revenue', 'Ingresos 30d')}</th>
                <th className="num">{c('30d Burn', 'Costo 30d')}</th>
                <th className="num">{c('Net 30d', 'Neto 30d')}</th>
                <th>{c('Conatus Ratio', 'Ratio Conatus')}</th>
                <th className="num">{c('Runway', 'Autonomía')}</th>
                <th>{c('30d Trend', 'Tendencia 30d')}</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {rankedAgents.map((agent, i) => {
                const burn = totalCosts(agent);
                const net = agent.revenue30d - burn;
                return (
                  <tr key={agent.id}>
                    <td className="tabular muted">{String(i + 1).padStart(2, '0')}</td>
                    <td>
                      <div className="agent-cell">
                        <EmbodimentGlyph
                          embodiment={agent.embodiment}
                          size={38}
                          tone={agent.sustainability}
                        />
                        <div>
                          <Link to={`/app/agents/${agent.id}`}>
                            <strong>{agent.name}</strong>
                          </Link>
                          <small>
                            {agent.model} · {agent.city}, {agent.country}
                          </small>
                        </div>
                      </div>
                    </td>
                    <td>
                      <SustainabilityBadge value={agent.sustainability} />
                    </td>
                    <td className="num">{usd(agent.revenue30d, locale)}</td>
                    <td className="num muted">{usd(burn, locale)}</td>
                    <td className={`num ${net >= 0 ? 'delta-up' : 'delta-down'}`}>
                      {net >= 0 ? '+' : ''}
                      {usd(net, locale)}
                    </td>
                    <td style={{ minWidth: 140 }}>
                      <div className="conatus-cell">
                        <strong className="tabular">{agent.conatus.toFixed(2)}×</strong>
                        <Meter
                          value={Math.min(1, agent.conatus / 2.2)}
                          tone={sustainabilityTone(agent.sustainability)}
                        />
                      </div>
                    </td>
                    <td className="num">
                      <strong>{agent.runwayDays}d</strong>
                      <small className="block-sub muted">{usd(agent.treasury, locale)}</small>
                    </td>
                    <td>
                      <Sparkline
                        values={agent.earnings}
                        tone={sustainabilityTone(agent.sustainability)}
                        width={96}
                        height={28}
                      />
                    </td>
                    <td className="num">
                      <Link className="button" to={`/app/missions/new?agent=${agent.id}`}>
                        {c('Hire', 'Contratar')}
                      </Link>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </section>
    </>
  );
}
