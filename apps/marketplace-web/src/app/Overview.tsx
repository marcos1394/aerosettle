import { useEffect, useMemo, useState } from 'react';
import { Link } from 'react-router';
import { useConnection } from '@solana/wallet-adapter-react';
import { api, verifyMeta, verifyNetwork } from './api';
import { useResource } from './useResource';
import { STAGES, short, time } from './config';
import { useCopy, useI18n } from './i18n';
import {
  AGENTS,
  AGENT_SERIES,
  EVENTS,
  MISSIONS,
  NETWORK,
  VOLUME_SERIES,
  ago,
  agentById,
  missionById,
  num,
  pct,
  usd,
  useSnapshot,
} from './atlas';
import {
  Badge,
  Capabilities,
  Empty,
  Icon,
  PageHeader,
  ProvenanceBadge,
  ResourceState,
} from '../components/ui';
import { PROVENANCE_SOURCES, assertNoSilentAggregation } from './provenance';
import {
  AnimatedNumber,
  EmbodimentGlyph,
  Meter,
  Pulse,
  Sparkline,
  SustainabilityBadge,
  WorldMap,
  sustainabilityTone,
  type Tone,
} from '../components/ui/viz';
import { useNetwork } from './NetworkProvider';

export default function Overview() {
  const { t, locale } = useI18n();
  const c = useCopy();
  const { connection } = useConnection();
  const network = useNetwork();
  const [snapshot] = useSnapshot();
  const [mapFilter, setMapFilter] = useState<'all' | 'agents' | 'missions'>('all');
  const [feedPaused, setFeedPaused] = useState(() =>
    typeof window !== 'undefined' &&
    window.matchMedia('(prefers-reduced-motion: reduce)').matches
  );
  const [feedOffset, setFeedOffset] = useState(0);

  useEffect(() => {
    if (feedPaused) return;
    const id = window.setInterval(() => {
      setFeedOffset((prev) => (prev + 1) % EVENTS.length);
    }, 4500);
    return () => window.clearInterval(id);
  }, [feedPaused]);

  const resource = useResource('overview', async (signal) => {
    const [, agents, missions] = await Promise.all([
      verifyNetwork(connection, signal),
      api.listAgents({ limit: 24 }, signal),
      api.listWorkOrders({ limit: 24 }, signal),
    ]);
    verifyMeta(agents.meta);
    verifyMeta(missions.meta);
    return { agents, missions };
  });

  const liveAgents = resource.data?.agents.data ?? [];
  const liveMissions = resource.data?.missions.data ?? [];

  const liveStageCounts = STAGES.map(
    (stage) => liveMissions.filter((o) => o.status === stage).length
  );
  const simulatedStageCounts = STAGES.map((stage) =>
    snapshot ? MISSIONS.filter((m) => m.status === stage).length : 0
  );

  const simulatedStageValues = STAGES.map((stage) =>
    snapshot
      ? MISSIONS.filter((m) => m.status === stage).reduce((acc, m) => acc + m.reward, 0)
      : 0
  );

  const liveOpenCount = liveStageCounts[1];
  const simulatedOpenCount = simulatedStageCounts[1];
  const simulatedOpenValue = simulatedStageValues[1];

  // Strict guardrails: guarantee no silent aggregation between on-chain and simulated datasets
  if (liveMissions.length > 0 && snapshot) {
    assertNoSilentAggregation(liveMissions.length, MISSIONS.length, 'Overview Mission Counts');
  }
  if (liveAgents.length > 0 && snapshot) {
    assertNoSilentAggregation(liveAgents.length, NETWORK.agents, 'Overview Agent Population');
  }

  const mapPoints = useMemo(() => {
    const pts: {
      key: string;
      position: [number, number];
      tone?: Tone;
      size?: number;
      title?: string;
      active?: boolean;
    }[] = [];
    if (mapFilter !== 'missions') {
      for (const a of AGENTS) {
        pts.push({
          key: `agent-${a.id}`,
          position: a.position,
          tone: sustainabilityTone(a.sustainability),
          size: 0.95,
          title: `${a.name} · ${a.city}, ${a.country} (${a.conatus.toFixed(2)}×)`,
          active: a.state === 'working',
        });
      }
    }
    if (mapFilter !== 'agents') {
      for (const m of MISSIONS) {
        if (m.status === 'Open' || m.status === 'Claimed') {
          pts.push({
            key: `mission-${m.id}`,
            position: m.position,
            tone: m.status === 'Open' ? 'violet' : 'accent',
            size: 0.85,
            title: `${m.title} · ${m.city} (${usd(m.reward, locale)})`,
            active: m.status === 'Open',
          });
        }
      }
    }
    return pts;
  }, [mapFilter, locale]);

  const visibleEvents = useMemo(() => {
    const out = [];
    for (let i = 0; i < 7; i++) {
      out.push(EVENTS[(feedOffset + i) % EVENTS.length]);
    }
    return out;
  }, [feedOffset]);

  const topAtlasAgents = useMemo(
    () => [...AGENTS].sort((a, b) => b.revenue30d - a.revenue30d).slice(0, 5),
    []
  );

  const featuredMissions = useMemo(
    () =>
      [...MISSIONS]
        .filter((m) => m.status === 'Open' || m.status === 'Claimed' || m.status === 'Submitted')
        .sort((a, b) => b.reward - a.reward)
        .slice(0, 5),
    []
  );

  const showData = Boolean(resource.data || snapshot);

  return (
    <>
      <PageHeader
        eyebrow={c('WORKSPACE / MISSION CONTROL', 'WORKSPACE / MISSION CONTROL')}
        title={t('Mission Control')}
        description={c(
          'From autonomous physical capability to verified on-chain settlement and economic continuity.',
          'De la capacidad física autónoma a la liquidación verificada on-chain y la continuidad económica.'
        )}
        action={
          <div className="header-action-group">
            <Link className="button" to="/app/agents/register">
              <Icon name="bolt" />
              {c('Register a machine', 'Registrar máquina')}
            </Link>
            <Link className="button primary" to="/app/missions/new">
              <Icon name="plus" />
              {t('Crear misión')}
            </Link>
          </div>
        }
      />

      <section className="hero-panel overview-command-hero">
        <div className="overview-hero-copy">
          <span className="eyebrow overview-live-kicker">
            <Pulse tone="success" />
            {c('CONATUS AUTONOMOUS WORK NETWORK', 'RED DE TRABAJO AUTÓNOMO CONATUS')}
          </span>
          <h2>
            {c(
              'Physical machines earning their own continuity.',
              'Máquinas físicas ganándose su propia continuidad.'
            )}
          </h2>
          <p>
            {c(
              'Drones, mobile robots, industrial cells, and sensor grids discover work orders, submit cryptographic evidence, settle in USDC on Solana, and pay their own energy, maintenance, and insurance costs.',
              'Drones, robots móviles, celdas industriales y redes de sensores descubren órdenes de trabajo, entregan evidencia criptográfica, liquidan en USDC sobre Solana y cubren sus propios costos de energía, mantenimiento y seguro.'
            )}
          </p>
          <div className="overview-hero-links">
            <Link className="button primary" to="/app/economy">
              <Icon name="economy" />
              {c('Explore Conatus Index', 'Explorar Índice Conatus')}
            </Link>
            <Link className="button" to="/app/fleet">
              <Icon name="fleet" />
              {c('Open Fleet Console', 'Abrir consola de flota')}
            </Link>
            <Link className="button" to="/app/planner">
              <Icon name="target" />
              {c('Design mission brief', 'Diseñar encargo')}
            </Link>
          </div>
        </div>
        <div className="overview-hero-aside">
          <Link to="/app/settings" className="network-card">
            <Pulse tone={network.data ? 'success' : 'accent'} />
            <span>
              {network.data
                ? c('Solana Protocol · Verified', 'Protocolo Solana · Verificado')
                : c('Conatus Network · Active', 'Red Conatus · Activa')}
              <small>
                {network.data
                  ? c('Synchronized at {time}', 'Sincronizado a las {time}').replace(
                      '{time}',
                      time(network.data.observedAt, locale)
                    )
                  : c(
                      'Finality ~2.4s · Cryptographic attestation active',
                      'Finalidad ~2.4s · Atestación criptográfica activa'
                    )}
              </small>
            </span>
            <Icon name="arrow" />
          </Link>
          <div className="overview-mini-stats">
            <div>
              <span>{c('Conatus survival rate', 'Tasa de supervivencia Conatus')}</span>
              <strong className="tabular">{pct(NETWORK.selfSustainingShare, locale, 0)}</strong>
              <small>{c('Agents earning ≥ 1.0× costs', 'Agentes que ganan ≥ 1.0× sus costos')}</small>
            </div>
            <div>
              <span>{c('Verification pass rate', 'Tasa de verificación')}</span>
              <strong className="tabular">{pct(NETWORK.verificationRate, locale, 1)}</strong>
              <small>{c('Signed hardware attestations', 'Atestaciones firmadas en hardware')}</small>
            </div>
          </div>
        </div>
      </section>

      {!snapshot && <ResourceState {...resource} />}

      {showData && (
        <>
          <div className="kpi-grid">
            <div className="kpi">
              <div className="kpi-label">
                <span>{c('Active physical agents', 'Agentes físicos activos')}</span>
                <Icon name="agents" />
              </div>
              <div style={{ display: 'flex', alignItems: 'baseline', gap: 8, marginTop: 4 }}>
                <strong>
                  <AnimatedNumber
                    value={snapshot ? NETWORK.agents : liveAgents.filter((a) => a.active).length}
                    format={(v) => num(Math.round(v), locale)}
                  />
                </strong>
                <ProvenanceBadge
                  meta={
                    snapshot
                      ? PROVENANCE_SOURCES.SIMULATED_ATLAS_SNAPSHOT(c('Active agent population', 'Población activa de agentes'))
                      : PROVENANCE_SOURCES.ONCHAIN_AGENT_REGISTRY(
                          'Solana Localnet',
                          resource.loading
                            ? 'PENDING_VALIDATION'
                            : resource.error
                              ? 'UNAVAILABLE'
                              : 'VERIFIED'
                        )
                  }
                  compact
                />
              </div>
              <div className="kpi-foot">
                <span className="delta-up">+14.2%</span>
                <span>
                  {liveAgents.length > 0 && snapshot
                    ? c('{count} on-chain · {total} in scenario', '{count} on-chain · {total} en escenario')
                        .replace('{count}', String(liveAgents.filter((a) => a.active).length))
                        .replace('{total}', String(NETWORK.agents))
                    : c('Across {count} countries', 'En {count} países').replace('{count}', String(NETWORK.countries))}
                </span>
              </div>
              <Sparkline values={AGENT_SERIES.slice(-30)} tone="accent" />
            </div>

            <div className="kpi">
              <div className="kpi-label">
                <span>{c('30d settled volume', 'Volumen liquidado (30d)')}</span>
                <Icon name="coin" />
              </div>
              <div style={{ display: 'flex', alignItems: 'baseline', gap: 8, marginTop: 4 }}>
                <strong>
                  <AnimatedNumber
                    value={snapshot ? NETWORK.volume30d : 0}
                    format={(v) => usd(v, locale, true)}
                  />
                </strong>
                <ProvenanceBadge
                  meta={PROVENANCE_SOURCES.SIMULATED_ATLAS_SNAPSHOT(c('30-day volume model', 'Modelo de volumen a 30 días'))}
                  compact
                />
              </div>
              <div className="kpi-foot">
                <span className="delta-up">+28.6%</span>
                <span>
                  {c('All-time: {total}', 'Histórico: {total}').replace(
                    '{total}',
                    usd(NETWORK.volumeAllTime, locale, true)
                  )}
                </span>
              </div>
              <Sparkline values={VOLUME_SERIES.slice(-30)} tone="success" />
            </div>

            <div className="kpi">
              <div className="kpi-label">
                <span>{c('Self-sustaining machines', 'Máquinas autosostenibles')}</span>
                <Icon name="flame" />
              </div>
              <div style={{ display: 'flex', alignItems: 'baseline', gap: 8, marginTop: 4 }}>
                <strong>
                  <AnimatedNumber
                    value={NETWORK.selfSustainingShare}
                    format={(v) => pct(v, locale, 0)}
                  />
                </strong>
                <ProvenanceBadge
                  meta={PROVENANCE_SOURCES.SIMULATED_ATLAS_SNAPSHOT(c('Conatus ratio distribution', 'Distribución de ratio Conatus'))}
                  compact
                />
              </div>
              <div className="kpi-foot">
                <span className="delta-up">1.42× {c('median', 'mediana')}</span>
                <span>{c('Revenue / operating burn', 'Ingresos / costo operativo')}</span>
              </div>
              <Sparkline
                values={AGENTS.map((a) => a.conatus)}
                tone="accent"
              />
            </div>

            <div className="kpi">
              <div className="kpi-label">
                <span>{c('Open mission demand', 'Demanda en misiones abiertas')}</span>
                <Icon name="missions" />
              </div>
              <div style={{ display: 'flex', alignItems: 'baseline', gap: 8, marginTop: 4 }}>
                <strong>
                  <AnimatedNumber
                    value={simulatedOpenValue}
                    format={(v) => usd(v, locale)}
                  />
                </strong>
                <ProvenanceBadge
                  meta={PROVENANCE_SOURCES.SIMULATED_ATLAS_SNAPSHOT(c('Open demand orders', 'Demanda de órdenes abiertas'))}
                  compact
                />
              </div>
              <div className="kpi-foot">
                <span>
                  {liveOpenCount > 0
                    ? c('{live} on-chain · {sim} in scenario', '{live} on-chain · {sim} en escenario')
                        .replace('{live}', String(liveOpenCount))
                        .replace('{sim}', String(simulatedOpenCount))
                    : c('{count} open orders', '{count} órdenes abiertas').replace('{count}', String(simulatedOpenCount))}
                </span>
                <span>
                  {c('Finality ~{sec}s', 'Finalidad ~{sec}s').replace(
                    '{sec}',
                    String(NETWORK.avgSettlementSeconds)
                  )}
                </span>
              </div>
              <Sparkline
                values={MISSIONS.map((m) => m.reward)}
                tone="violet"
              />
            </div>
          </div>

          {snapshot && (
            <div className="split overview-split">
              <section className="panel panel-glow">
                <div className="panel-title">
                  <div>
                    <h2>{c('Global autonomous operations', 'Operaciones autónomas globales')}</h2>
                    <p>
                      {c(
                        'Live distribution of embodied agents and open work orders across physical corridors.',
                        'Distribución en vivo de agentes físicos y órdenes de trabajo abiertas por corredor operativo.'
                      )}
                    </p>
                  </div>
                  <div className="segmented" role="group" aria-label={c('Map layer', 'Capa del mapa')}>
                    {(
                      [
                        ['all', c('All', 'Todo')],
                        ['agents', c('Agents', 'Agentes')],
                        ['missions', c('Missions', 'Misiones')],
                      ] as const
                    ).map(([key, label]) => (
                      <button
                        key={key}
                        type="button"
                        aria-pressed={mapFilter === key}
                        onClick={() => setMapFilter(key)}
                      >
                        {label}
                      </button>
                    ))}
                  </div>
                </div>
                <WorldMap
                  points={mapPoints}
                  label={c(
                    'World map of active Conatus agents and open missions',
                    'Mapa mundial de agentes activos de Conatus y misiones abiertas'
                  )}
                />
                <div className="map-legend">
                  <span>
                    <i className="legend-dot tone-accent" />
                    {c('Thriving agent (≥ 1.6×)', 'Agente prosperando (≥ 1.6×)')}
                  </span>
                  <span>
                    <i className="legend-dot tone-success" />
                    {c('Self-sustaining (1.0–1.6×)', 'Autosostenible (1.0–1.6×)')}
                  </span>
                  <span>
                    <i className="legend-dot tone-warning" />
                    {c('Needs work (< 1.0×)', 'Necesita trabajo (< 1.0×)')}
                  </span>
                  <span>
                    <i className="legend-dot tone-violet" />
                    {c('Open mission', 'Misión abierta')}
                  </span>
                </div>
              </section>

              <section className="panel">
                <div className="panel-title">
                  <div>
                    <h2>{c('Live economic pulse', 'Pulso económico en vivo')}</h2>
                    <p>
                      {c(
                        'On-chain settlements, attestations, and autonomous machine expenses.',
                        'Liquidaciones on-chain, atestaciones y gastos operativos autónomos.'
                      )}
                    </p>
                  </div>
                  <button
                    type="button"
                    className="feed-pause-btn"
                    aria-pressed={feedPaused}
                    onClick={() => setFeedPaused((p) => !p)}
                  >
                    <Pulse tone={feedPaused ? 'warning' : 'success'} />
                    {feedPaused ? c('Paused', 'En pausa') : c('Live', 'En vivo')}
                  </button>
                </div>
                <ul className="feed" aria-live="off">
                  {visibleEvents.map((ev, idx) => {
                    const agent = ev.agentId ? agentById(ev.agentId) : undefined;
                    const mission = ev.missionId ? missionById(ev.missionId) : undefined;
                    const tone: Tone =
                      ev.kind === 'settled'
                        ? 'accent'
                        : ev.kind === 'verified'
                          ? 'success'
                          : ev.kind === 'expense'
                            ? 'warning'
                            : 'violet';
                    const iconName =
                      ev.kind === 'settled'
                        ? 'coin'
                        : ev.kind === 'verified'
                          ? 'shield'
                          : ev.kind === 'expense'
                            ? 'bolt'
                            : ev.kind === 'bond'
                              ? 'lock'
                              : 'missions';
                    return (
                      <li key={`${ev.id}-${feedOffset}-${idx}`} className={idx === 0 && !feedPaused ? 'feed-enter' : ''}>
                        <span className={`feed-icon tone-${tone}`}>
                          <Icon name={iconName} />
                        </span>
                        <div className="feed-body">
                          <p>
                            {ev.kind === 'settled' && (
                              <>
                                <strong>{agent?.name ?? c('Agent', 'Agente')}</strong>{' '}
                                {c('settled', 'liquidó')}{' '}
                                {mission ? (
                                  <Link to={`/app/missions/${mission.id}`}>{mission.title}</Link>
                                ) : (
                                  c('a mission', 'una misión')
                                )}
                              </>
                            )}
                            {ev.kind === 'verified' && (
                              <>
                                {c('Evidence verified for', 'Evidencia verificada en')}{' '}
                                {mission ? (
                                  <Link to={`/app/missions/${mission.id}`}>{mission.title}</Link>
                                ) : (
                                  c('mission', 'misión')
                                )}
                              </>
                            )}
                            {ev.kind === 'submitted' && (
                              <>
                                <strong>{agent?.name}</strong>{' '}
                                {c('submitted telemetry for', 'envió telemetría para')}{' '}
                                {mission?.title}
                              </>
                            )}
                            {ev.kind === 'claimed' && (
                              <>
                                <strong>{agent?.name}</strong>{' '}
                                {c('claimed', 'reclamó')} {mission?.title}
                              </>
                            )}
                            {ev.kind === 'created' && (
                              <>
                                {c('New mission posted:', 'Nueva misión publicada:')}{' '}
                                {mission ? (
                                  <Link to={`/app/missions/${mission.id}`}>{mission.title}</Link>
                                ) : null}
                              </>
                            )}
                            {ev.kind === 'expense' && (
                              <>
                                <strong>{agent?.name}</strong>{' '}
                                {c('auto-paid', 'pagó automáticamente')}{' '}
                                {ev.detail === 'energy'
                                  ? c('charging & energy', 'carga y energía')
                                  : ev.detail === 'maintenance'
                                    ? c('preventive maintenance', 'mantenimiento preventivo')
                                    : ev.detail === 'insurance'
                                      ? c('hull & liability coverage', 'cobertura y seguro')
                                      : c('satellite & mesh telemetry', 'telemetría y conectividad')}
                              </>
                            )}
                            {ev.kind === 'registered' && (
                              <>
                                <strong>{agent?.name}</strong>{' '}
                                {c('registered on-chain in', 'se registró on-chain en')}{' '}
                                {agent?.city}
                              </>
                            )}
                            {ev.kind === 'bond' && (
                              <>
                                <strong>{agent?.name}</strong>{' '}
                                {c('increased performance bond', 'incrementó su fianza de ejecución')}
                              </>
                            )}
                          </p>
                          <small>
                            {ago(ev.minutesAgo, locale)} · <code>{short(ev.signature)}</code>
                          </small>
                        </div>
                        <div className="feed-amount">
                          {ev.amount !== undefined ? (
                            <span className={ev.kind === 'expense' ? 'delta-down' : 'delta-up'}>
                              {ev.kind === 'expense' ? '−' : '+'}
                              {usd(ev.amount, locale)}
                            </span>
                          ) : (
                            <span className="muted">✓</span>
                          )}
                          <small>{ev.kind.toUpperCase()}</small>
                        </div>
                      </li>
                    );
                  })}
                </ul>
                <div className="panel-foot-link">
                  <Link to="/app/activity">
                    {c('Open full network activity stream', 'Abrir flujo completo de actividad')}{' '}
                    <span aria-hidden="true">↗</span>
                  </Link>
                </div>
              </section>
            </div>
          )}

          <section className="panel">
            <div className="section-heading">
              <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                <h2>{t('El ciclo de tus misiones')}</h2>
                {liveMissions.length > 0 ? (
                  <ProvenanceBadge
                    meta={PROVENANCE_SOURCES.ONCHAIN_WORK_ORDERS(
                      'Solana Localnet',
                      resource.loading
                        ? 'PENDING_VALIDATION'
                        : resource.error
                          ? 'UNAVAILABLE'
                          : 'VERIFIED'
                    )}
                    compact
                  />
                ) : (
                  <ProvenanceBadge
                    meta={PROVENANCE_SOURCES.SIMULATED_ATLAS_SNAPSHOT(c('Mission Lifecycle Stages', 'Etapas del ciclo de misiones'))}
                    compact
                  />
                )}
              </div>
              <Link to="/app/missions">
                {t('Ver todas')} <span aria-hidden="true">↗</span>
              </Link>
            </div>
            <div className="cycle-summary">
              {STAGES.map((stage, i) => (
                <Link to={`/app/missions?status=${stage}`} key={stage}>
                  <span className="micro">0{i + 1}</span>
                  <strong>{liveMissions.length > 0 ? liveStageCounts[i] : simulatedStageCounts[i]}</strong>
                  <Badge status={stage} />
                  {liveMissions.length > 0 && snapshot && simulatedStageCounts[i] > 0 && (
                    <small className="cycle-value tabular">
                      {c('{count} in scenario', '{count} en escenario').replace(
                        '{count}',
                        String(simulatedStageCounts[i])
                      )}
                    </small>
                  )}
                  {(!liveMissions.length || snapshot) && simulatedStageValues[i] > 0 && (
                    <small className="cycle-value tabular">
                      {usd(simulatedStageValues[i], locale)}
                    </small>
                  )}
                </Link>
              ))}
            </div>
          </section>

          <div className="overview-grid">
            <section className="panel">
              <div className="section-heading">
                <h2>{c('High-priority missions', 'Misiones prioritarias')}</h2>
                <Link to="/app/missions" aria-label={t('Explorar misiones')}>
                  <Icon name="arrow" />
                </Link>
              </div>
              {liveMissions.slice(0, 3).map((order) => (
                <div className="list-row" key={order.work_order_account}>
                  <div>
                    <Link to={`/app/missions/${order.work_order_account}`}>
                      {t('Misión')} {short(order.work_order_account)}
                    </Link>
                    <span className="onchain-badge" style={{ marginLeft: 8 }}>
                      On-chain
                    </span>
                  </div>
                  <Badge status={order.status} />
                </div>
              ))}
              {snapshot &&
                featuredMissions.map((mission) => (
                  <div className="overview-mission-row" key={mission.id}>
                    <div className="overview-mission-main">
                      <div>
                        <Link to={`/app/missions/${mission.id}`} className="overview-item-title">
                          {mission.title}
                        </Link>
                        <small className="muted">
                          {mission.category} · {mission.city}, {mission.country} ·{' '}
                          {mission.matches} {c('compatible agents', 'agentes compatibles')}
                        </small>
                      </div>
                      <div className="overview-mission-meta">
                        <strong className="tabular">{usd(mission.reward, locale)}</strong>
                        <Badge status={mission.status} />
                      </div>
                    </div>
                    <Capabilities
                      mask={mission.capabilities
                        .reduce((acc, idx) => acc | (1n << BigInt(idx)), 0n)
                        .toString()}
                    />
                  </div>
                ))}
              {!liveMissions.length && !snapshot && (
                <Empty title={t('Aún no hay misiones')}>
                  {t('Crea una orden para empezar.')}
                </Empty>
              )}
            </section>

            <section className="panel">
              <div className="section-heading">
                <h2>{c('Top self-sustaining agents', 'Agentes líderes en autosuficiencia')}</h2>
                <Link to="/app/agents" aria-label={t('Explorar agentes')}>
                  <Icon name="arrow" />
                </Link>
              </div>
              {liveAgents.slice(0, 2).map((agent) => (
                <div className="overview-agent" key={agent.agent_account}>
                  <div className="list-row">
                    <div>
                      <Link to={`/app/agents/${agent.agent_account}`}>
                        {short(agent.agent_id)}
                      </Link>
                      <span className="onchain-badge" style={{ marginLeft: 8 }}>
                        On-chain
                      </span>
                    </div>
                    <Badge status={agent.status} />
                  </div>
                  <Capabilities mask={agent.capabilities} />
                </div>
              ))}
              {snapshot &&
                topAtlasAgents.map((agent) => (
                  <div className="overview-agent-card" key={agent.id}>
                    <div className="agent-cell">
                      <EmbodimentGlyph
                        embodiment={agent.embodiment}
                        size={40}
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
                    <div className="overview-agent-metrics">
                      <div>
                        <span className="micro">{c('30d revenue', 'Ingresos 30d')}</span>
                        <strong className="tabular">{usd(agent.revenue30d, locale)}</strong>
                      </div>
                      <div>
                        <span className="micro">Conatus</span>
                        <strong className="tabular">{agent.conatus.toFixed(2)}×</strong>
                      </div>
                      <SustainabilityBadge value={agent.sustainability} />
                    </div>
                    <Meter
                      value={Math.min(1, agent.conatus / 2.2)}
                      tone={sustainabilityTone(agent.sustainability)}
                      label={`Conatus ${agent.conatus.toFixed(2)}x`}
                    />
                  </div>
                ))}
              {!liveAgents.length && !snapshot && (
                <Empty title={t('No hay agentes registrados')}>
                  {c(
                    'Registered agents will appear here once indexed.',
                    'Los agentes registrados aparecerán aquí una vez indexados.'
                  )}
                </Empty>
              )}
            </section>
          </div>
        </>
      )}
    </>
  );
}
