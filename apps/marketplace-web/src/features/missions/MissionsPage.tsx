import { useMemo, useState } from 'react';
import { Link, useNavigate, useSearchParams } from 'react-router';
import { useConnection } from '@solana/wallet-adapter-react';
import type { OrderStatus, WorkOrder } from '@aerosettle/marketplace-sdk';
import { PublicKey } from '@solana/web3.js';
import { api, verifyMeta, verifyNetwork } from '../../app/api';
import { CAPABILITIES, MINT, STAGES, capabilities, short } from '../../app/config';
import { useCopy, useI18n } from '../../app/i18n';
import { useResource } from '../../app/useResource';
import {
  AGENTS,
  MISSIONS,
  MISSION_CATEGORIES,
  NETWORK,
  SETTLEMENT_SYMBOL,
  VOLUME_SERIES,
  agentById,
  inHours,
  num,
  pct,
  usd,
  useSnapshot,
  type AtlasMission,
  type MissionCategory,
  type Stage,
} from '../../app/atlas';
import {
  Badge,
  Empty,
  Icon,
  PageHeader,
  ResourceState,
} from '../../components/ui';
import {
  AnimatedNumber,
  EmbodimentGlyph,
  Sparkline,
  WorldMap,
  type Tone,
} from '../../components/ui/viz';
import '../../styles/missions.css';

export const CATEGORY_ICONS: Record<MissionCategory, string> = {
  Inspection: 'eye',
  Mapping: 'map',
  Delivery: 'fleet',
  Manufacturing: 'wrench',
  Monitoring: 'activity',
  Energy: 'bolt',
  Compute: 'cpu',
  Agriculture: 'sun',
  Logistics: 'grid',
};

export function translateCategory(cat: MissionCategory, locale: string): string {
  if (locale !== 'es') return cat;
  const map: Record<MissionCategory, string> = {
    Inspection: 'Inspección',
    Mapping: 'Cartografía',
    Delivery: 'Entrega',
    Manufacturing: 'Manufactura',
    Monitoring: 'Monitoreo',
    Energy: 'Energía',
    Compute: 'Cómputo',
    Agriculture: 'Agricultura',
    Logistics: 'Logística',
  };
  return map[cat] ?? cat;
}

export function stageTone(status: Stage | string): Tone {
  switch (status) {
    case 'Open':
      return 'accent';
    case 'Claimed':
      return 'violet';
    case 'Submitted':
      return 'warning';
    case 'Verified':
    case 'Settled':
      return 'success';
    default:
      return 'muted';
  }
}

type SortKey = 'reward' | 'ending' | 'newest' | 'matches';
type ViewMode = 'board' | 'map' | 'lifecycle';

type UnifiedMission = AtlasMission & {
  onChain?: boolean;
  href: string;
};

function liveOrderToMission(order: WorkOrder, locale: string): UnifiedMission {
  const capNames = capabilities(order.required_capabilities);
  const capIndexes = CAPABILITIES.map((name, i) => (capNames.includes(name) ? i : -1)).filter(
    (i) => i >= 0
  );
  const nowSec = Math.floor(Date.now() / 1000);
  const deadlineHours = order.execution_deadline
    ? Math.round((order.execution_deadline - nowSec) / 3600)
    : 12;
  const rawAmount =
    typeof order.total_amount === 'string' && /^\d+$/.test(order.total_amount)
      ? Number(BigInt(order.total_amount) / 1_000_000n)
      : 250;
  const matches = AGENTS.filter((a) =>
    capIndexes.every((c) => a.capabilities.includes(c))
  ).length;
  return {
    id: order.work_order_account,
    account: order.work_order_account,
    title:
      locale === 'es'
        ? `Orden de inspección · ${short(order.work_order_account)}`
        : `Inspection work order · ${short(order.work_order_account)}`,
    category: 'Inspection',
    city: 'Solana',
    country: 'ON-CHAIN',
    position: [26, 34],
    reward: rawAmount > 0 ? rawAmount : 250,
    capabilities: capIndexes.length ? capIndexes : [0, 5],
    status: (order.status as Stage) || 'Open',
    evidence:
      locale === 'es'
        ? ['Manifiesto criptográfico', 'Recibo firmado']
        : ['Cryptographic manifest', 'Signed receipt'],
    deadlineHours,
    createdHoursAgo: 1,
    matches,
    requester:
      typeof order.creator === 'string'
        ? order.creator
        : order.work_order_account,
    agentId:
      typeof order.claimed_agent === 'string' &&
      order.claimed_agent !== '11111111111111111111111111111111'
        ? order.claimed_agent
        : undefined,
    summary:
      locale === 'es'
        ? 'Orden de trabajo verificada directamente desde el programa en Solana.'
        : 'Work order verified directly from the on-chain Solana program.',
    onChain: true,
    href: `/app/missions/${order.work_order_account}`,
  };
}

export default function MissionsPage() {
  const { t, locale } = useI18n();
  const c = useCopy();
  const { connection } = useConnection();
  const navigate = useNavigate();
  const [params, setParams] = useSearchParams();
  const [snapshot] = useSnapshot();

  const status = STAGES.includes(params.get('status') as OrderStatus)
    ? (params.get('status') as Stage)
    : '';
  const [category, setCategory] = useState<MissionCategory | 'all'>('all');
  const [search, setSearch] = useState('');
  const [sort, setSort] = useState<SortKey>('reward');
  const [view, setView] = useState<ViewMode>('board');
  const [selectedMapId, setSelectedMapId] = useState<string>(MISSIONS[0]?.id ?? '');
  const [address, setAddress] = useState('');
  const [addressError, setAddressError] = useState('');

  const resource = useResource(`missions:${status}`, async (signal) => {
    const [, page] = await Promise.all([
      verifyNetwork(connection, signal),
      api.listWorkOrders(
        {
          status: (status || undefined) as OrderStatus | undefined,
          limit: 24,
        },
        signal
      ),
    ]);
    verifyMeta(page.meta);
    return page;
  });

  const allMissions = useMemo<UnifiedMission[]>(() => {
    const liveOrders = (resource.data?.data ?? []).map((o) =>
      liveOrderToMission(o, locale)
    );
    const atlasItems: UnifiedMission[] = snapshot
      ? MISSIONS.map((m) => ({
          ...m,
          onChain: false,
          href: `/app/missions/${m.id}`,
        }))
      : [];
    const seen = new Set(liveOrders.map((o) => o.account));
    return [...liveOrders, ...atlasItems.filter((m) => !seen.has(m.account))];
  }, [resource.data, snapshot, locale]);

  // Header KPI metrics
  const openMissions = useMemo(
    () => allMissions.filter((m) => m.status === 'Open'),
    [allMissions]
  );
  const openValueUsdc = useMemo(
    () => openMissions.reduce((sum, m) => sum + m.reward, 0),
    [openMissions]
  );

  // Category counts (respecting current status filter)
  const categoryCounts = useMemo(() => {
    const base = status
      ? allMissions.filter((m) => m.status === status)
      : allMissions;
    const counts: Record<string, number> = { all: base.length };
    for (const cat of MISSION_CATEGORIES) {
      counts[cat] = base.filter((m) => m.category === cat).length;
    }
    return counts;
  }, [allMissions, status]);

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase();
    const list = allMissions.filter((m) => {
      if (status && m.status !== status) return false;
      if (category !== 'all' && m.category !== category) return false;
      if (!q) return true;
      const agent = m.agentId ? agentById(m.agentId) : undefined;
      const capText = m.capabilities
        .map((idx) => t(CAPABILITIES[idx] ?? ''))
        .join(' ');
      const haystack = `${m.title} ${m.summary} ${m.city} ${m.country} ${m.category} ${translateCategory(m.category, locale)} ${m.id} ${m.account} ${agent?.name ?? ''} ${capText}`.toLowerCase();
      return haystack.includes(q);
    });

    return [...list].sort((a, b) => {
      if (sort === 'reward') return b.reward - a.reward;
      if (sort === 'ending') {
        const aOpen = a.deadlineHours > 0 ? 0 : 1;
        const bOpen = b.deadlineHours > 0 ? 0 : 1;
        if (aOpen !== bOpen) return aOpen - bOpen;
        return a.deadlineHours - b.deadlineHours;
      }
      if (sort === 'newest') return a.createdHoursAgo - b.createdHoursAgo;
      if (sort === 'matches') return b.matches - a.matches;
      return 0;
    });
  }, [allMissions, status, category, search, sort, locale, t]);

  const activeMapMission =
    filtered.find((m) => m.id === selectedMapId) ?? filtered[0] ?? null;

  return (
    <>
      <PageHeader
        eyebrow={c('MISSION MARKETPLACE', 'MERCADO DE MISIONES')}
        title={c(
          'Physical work, settled on-chain.',
          'Trabajo físico, liquidado on-chain.'
        )}
        description={c(
          'Commission autonomous machines for real-world operations with cryptographic evidence and instant USDC escrow settlement on Solana.',
          'Contrata máquinas autónomas para operaciones en el mundo real con evidencia criptográfica y liquidación instantánea en custodia USDC sobre Solana.'
        )}
        action={
          <div className="missions-header-actions">
            <Link className="button" to="/app/planner">
              <Icon name="target" />
              {c('Plan a brief', 'Planificar encargo')}
            </Link>
            <Link className="button primary" to="/app/missions/new">
              <Icon name="plus" />
              {c('Post a mission', 'Publicar misión')}
            </Link>
          </div>
        }
      />

      {/* Header KPI stats */}
      <section className="kpi-grid" aria-label={c('Marketplace metrics', 'Métricas del mercado')}>
        <article className="kpi">
          <div className="kpi-label">
            <span>{c('Open missions', 'Misiones abiertas')}</span>
            <Icon name="missions" />
          </div>
          <strong>
            <AnimatedNumber
              value={openMissions.length}
              format={(v) => num(Math.round(v), locale)}
            />
          </strong>
          <div className="kpi-foot">
            <span className="delta-up">
              {c('Ready to claim', 'Listas para reclamar')}
            </span>
            <span>
              {num(allMissions.length, locale)} {c('total on board', 'en el tablero')}
            </span>
          </div>
        </article>

        <article className="kpi">
          <div className="kpi-label">
            <span>
              {c('Value open in', 'Valor abierto en')} {SETTLEMENT_SYMBOL}
            </span>
            <Icon name="coin" />
          </div>
          <strong>
            <AnimatedNumber
              value={openValueUsdc}
              format={(v) => usd(Math.round(v), locale)}
            />
          </strong>
          <div className="kpi-foot">
            <span>{c('Escrowed on claim', 'En custodia al reclamar')}</span>
            <span className="delta-up">+18.4%</span>
          </div>
          <Sparkline values={VOLUME_SERIES.slice(-16)} tone="accent" />
        </article>

        <article className="kpi">
          <div className="kpi-label">
            <span>{c('Avg time to settlement', 'Tiempo medio de liquidación')}</span>
            <Icon name="clock" />
          </div>
          <strong className="tabular">{NETWORK.avgSettlementSeconds}s</strong>
          <div className="kpi-foot">
            <span>{c('After attestation', 'Tras atestación')}</span>
            <span>{c('Solana finality', 'Finalidad en Solana')}</span>
          </div>
        </article>

        <article className="kpi">
          <div className="kpi-label">
            <span>{c('Verification rate', 'Tasa de verificación')}</span>
            <Icon name="shield" />
          </div>
          <strong>
            <AnimatedNumber
              value={NETWORK.verificationRate}
              format={(v) => pct(v, locale, 1)}
            />
          </strong>
          <div className="kpi-foot">
            <span className="delta-up">{c('First-pass proofs', 'Pruebas en primer pase')}</span>
            <span>{c('Signed telemetry', 'Telemetría firmada')}</span>
          </div>
        </article>
      </section>

      {/* Toolbar: Search, Status, Sort, View Switcher */}
      <div className="missions-toolbar" role="search">
        <label className="missions-search-box">
          {c('Search missions', 'Buscar misiones')}
          <Icon name="search" />
          <input
            type="search"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder={c(
              'Title, city, capability, agent or PDA…',
              'Título, ciudad, capacidad, agente o PDA…'
            )}
          />
        </label>

        <label>
          {c('Lifecycle stage', 'Etapa del ciclo')}
          <select
            value={status}
            onChange={(e) => {
              setParams(e.target.value ? { status: e.target.value } : {});
            }}
          >
            <option value="">{c('All stages', 'Todas las etapas')}</option>
            {STAGES.map((stage) => (
              <option key={stage} value={stage}>
                {t(stage)}
              </option>
            ))}
          </select>
        </label>

        <label>
          {c('Sort by', 'Ordenar por')}
          <select
            value={sort}
            onChange={(e) => setSort(e.target.value as SortKey)}
          >
            <option value="reward">{c('Highest reward', 'Mayor recompensa')}</option>
            <option value="ending">{c('Ending soon', 'Próximas a vencer')}</option>
            <option value="newest">{c('Newest', 'Más recientes')}</option>
            <option value="matches">{c('Most matches', 'Más agentes compatibles')}</option>
          </select>
        </label>

        <div
          className="segmented"
          role="group"
          aria-label={c('View mode', 'Modo de vista')}
        >
          <button
            type="button"
            aria-pressed={view === 'board'}
            onClick={() => setView('board')}
          >
            <Icon name="grid" />
            {c('Board', 'Tablero')}
          </button>
          <button
            type="button"
            aria-pressed={view === 'map'}
            onClick={() => setView('map')}
          >
            <Icon name="map" />
            {c('Map', 'Mapa')}
          </button>
          <button
            type="button"
            aria-pressed={view === 'lifecycle'}
            onClick={() => setView('lifecycle')}
          >
            <Icon name="list" />
            {c('Lifecycle', 'Ciclo')}
          </button>
        </div>
      </div>

      {/* Category Chip Filters */}
      <div className="missions-category-bar">
        <div
          className="chip-filters"
          role="group"
          aria-label={c('Mission categories', 'Categorías de misión')}
        >
          <button
            type="button"
            aria-pressed={category === 'all'}
            onClick={() => setCategory('all')}
          >
            {c('All categories', 'Todas')}
            <span className="chip-count">{categoryCounts.all ?? 0}</span>
          </button>
          {MISSION_CATEGORIES.map((cat) => (
            <button
              key={cat}
              type="button"
              aria-pressed={category === cat}
              onClick={() => setCategory(cat === category ? 'all' : cat)}
            >
              <Icon name={CATEGORY_ICONS[cat]} />
              {translateCategory(cat, locale)}
              <span className="chip-count">{categoryCounts[cat] ?? 0}</span>
            </button>
          ))}
        </div>

        {(category !== 'all' || status !== '' || search.trim() !== '') && (
          <button
            type="button"
            className="button"
            onClick={() => {
              setCategory('all');
              setSearch('');
              setParams({});
            }}
          >
            {c('Reset filters', 'Limpiar filtros')}
          </button>
        )}
      </div>

      {/* Only show ResourceState error when snapshot is off */}
      {!snapshot && (
        <ResourceState {...resource} reload={() => resource.reload()} />
      )}

      {/* Empty State */}
      {filtered.length === 0 && (
        <Empty
          title={c(
            'No missions match these filters',
            'Ninguna misión coincide con estos filtros'
          )}
        >
          {c(
            'Adjust the category, lifecycle stage, or search query — or post a new mission to the network.',
            'Ajusta la categoría, la etapa del ciclo o la búsqueda, o publica una nueva misión en la red.'
          )}
        </Empty>
      )}

      {/* VIEW 1: BOARD (Cards) */}
      {view === 'board' && filtered.length > 0 && (
        <section
          className="mission-cards-grid"
          aria-label={c('Mission board', 'Tablero de misiones')}
        >
          {filtered.map((mission) => {
            const assignedAgent = mission.agentId
              ? agentById(mission.agentId)
              : undefined;
            return (
              <article className="mission-card" key={mission.id}>
                <div>
                  <div className="mission-card-top">
                    <span className="mission-cat-pill">
                      <Icon name={CATEGORY_ICONS[mission.category]} />
                      {translateCategory(mission.category, locale)}
                    </span>
                    <div className="mission-card-badges">
                      {mission.onChain && (
                        <span className="onchain-badge">
                          {c('On-chain', 'On-chain')}
                        </span>
                      )}
                      <Badge status={mission.status} />
                    </div>
                  </div>

                  <div className="mission-card-body" style={{ marginTop: 14 }}>
                    <h2 className="mission-card-title">
                      <Link to={mission.href}>{mission.title}</Link>
                    </h2>
                    <div className="mission-card-location">
                      <Icon name="pin" />
                      <span>
                        {mission.city}, {mission.country}
                      </span>
                      <span>·</span>
                      <code>{short(mission.account)}</code>
                    </div>
                    <p className="mission-card-summary">{mission.summary}</p>
                  </div>
                </div>

                <div className="mission-card-meta">
                  <div className="mission-reward-row">
                    <div className="mission-reward-amount">
                      <strong>{usd(mission.reward, locale)}</strong>
                      <span>{SETTLEMENT_SYMBOL}</span>
                    </div>
                    <span className="mission-deadline">
                      <Icon name="clock" />
                      {mission.deadlineHours >= 0
                        ? `${c('Due', 'Vence')} ${inHours(mission.deadlineHours, locale)}`
                        : `${c('Closed', 'Cerró')} ${inHours(mission.deadlineHours, locale)}`}
                    </span>
                  </div>

                  <div className="mission-meta-group">
                    <span className="mission-meta-label">
                      {c('Required capabilities', 'Capacidades requeridas')}
                    </span>
                    <div className="chips">
                      {mission.capabilities.map((capIdx) => (
                        <span key={capIdx} className="chip">
                          {t(CAPABILITIES[capIdx] ?? `Cap #${capIdx}`)}
                        </span>
                      ))}
                    </div>
                  </div>

                  <div className="mission-meta-group">
                    <span className="mission-meta-label">
                      {c('Evidence requirements', 'Evidencia requerida')}
                    </span>
                    <div className="mission-evidence-chips">
                      {mission.evidence.map((ev) => (
                        <span key={ev} className="evidence-pill">
                          <Icon name="shield" />
                          {ev}
                        </span>
                      ))}
                    </div>
                  </div>
                </div>

                <div className="mission-card-foot">
                  {assignedAgent ? (
                    <Link
                      to={`/app/agents/${assignedAgent.id}`}
                      className="mission-agent-link"
                    >
                      <EmbodimentGlyph
                        embodiment={assignedAgent.embodiment}
                        tone={assignedAgent.sustainability}
                        size={26}
                      />
                      <span>{assignedAgent.name}</span>
                    </Link>
                  ) : mission.agentId ? (
                    <Link
                      to={`/app/agents/${mission.agentId}`}
                      className="mission-agent-link"
                    >
                      <Icon name="agents" />
                      <span>{short(mission.agentId)}</span>
                    </Link>
                  ) : (
                    <span className="mission-matches-pill">
                      <Icon name="agents" />
                      <strong>{mission.matches}</strong>{' '}
                      {c('compatible agents', 'agentes compatibles')}
                    </span>
                  )}

                  <Link
                    to={mission.href}
                    className="button"
                    style={{ minHeight: 32, padding: '4px 12px', fontSize: 12 }}
                  >
                    {mission.status === 'Open'
                      ? c('Inspect & claim', 'Ver y reclamar')
                      : c('View mission', 'Ver misión')}
                    <Icon name="arrow" />
                  </Link>
                </div>
              </article>
            );
          })}
        </section>
      )}

      {/* VIEW 2: MAP */}
      {view === 'map' && filtered.length > 0 && (
        <section
          className="missions-map-layout"
          aria-label={c('Global mission map', 'Mapa global de misiones')}
        >
          <div className="panel missions-map-stage">
            <div className="panel-title">
              <div>
                <h2>{c('Geospatial mission dispatch', 'Despacho geoespacial de misiones')}</h2>
                <p>
                  {c(
                    'Select a mission from the list to highlight its operational site and inspect telemetry requirements.',
                    'Selecciona una misión de la lista para resaltar su ubicación operativa e inspeccionar requisitos de telemetría.'
                  )}
                </p>
              </div>
              <div className="map-legend" aria-hidden="true">
                <span>
                  <i style={{ background: 'var(--accent)' }} />
                  {t('Open')}
                </span>
                <span>
                  <i style={{ background: '#9fb4ff' }} />
                  {t('Claimed')}
                </span>
                <span>
                  <i style={{ background: 'var(--warning)' }} />
                  {t('Submitted')}
                </span>
                <span>
                  <i style={{ background: 'var(--success)' }} />
                  {t('Settled')}
                </span>
              </div>
            </div>

            <WorldMap
              label={c('World map of active missions', 'Mapa mundial de misiones activas')}
              points={filtered.map((m) => ({
                key: m.id,
                position: m.position,
                tone: stageTone(m.status),
                size: activeMapMission?.id === m.id ? 1.8 : 1.05,
                active: activeMapMission?.id === m.id,
                title: `${m.title} — ${m.city}, ${m.country} (${usd(m.reward, locale)})`,
              }))}
            />

            {activeMapMission && (
              <div className="map-selected-card">
                <div>
                  <div className="mission-card-badges">
                    <span className="mission-cat-pill">
                      <Icon name={CATEGORY_ICONS[activeMapMission.category]} />
                      {translateCategory(activeMapMission.category, locale)}
                    </span>
                    <Badge status={activeMapMission.status} />
                    <span className="muted" style={{ fontSize: 12 }}>
                      {activeMapMission.city}, {activeMapMission.country}
                    </span>
                  </div>
                  <h3>{activeMapMission.title}</h3>
                  <p className="micro" style={{ margin: 0 }}>
                    {activeMapMission.summary}
                  </p>
                </div>
                <div style={{ display: 'flex', alignItems: 'center', gap: 14 }}>
                  <div style={{ textAlign: 'right' }}>
                    <strong
                      className="tabular"
                      style={{ fontSize: 20, color: 'var(--accent)', display: 'block' }}
                    >
                      {usd(activeMapMission.reward, locale)} {SETTLEMENT_SYMBOL}
                    </strong>
                    <small className="muted">
                      {activeMapMission.matches}{' '}
                      {c('compatible agents', 'agentes compatibles')}
                    </small>
                  </div>
                  <Link className="button primary" to={activeMapMission.href}>
                    {c('Open mission', 'Abrir misión')}
                    <Icon name="arrow" />
                  </Link>
                </div>
              </div>
            )}
          </div>

          <aside className="panel" style={{ marginBottom: 0 }}>
            <div className="panel-title">
              <h2>
                {c('Missions in view', 'Misiones en vista')} ({filtered.length})
              </h2>
            </div>
            <div className="missions-map-list" role="listbox" aria-label={c('Missions', 'Misiones')}>
              {filtered.map((m) => {
                const isSelected = activeMapMission?.id === m.id;
                return (
                  <button
                    key={m.id}
                    type="button"
                    className="map-list-item"
                    aria-pressed={isSelected}
                    onClick={() => setSelectedMapId(m.id)}
                  >
                    <div style={{ minWidth: 0 }}>
                      <strong>{m.title}</strong>
                      <small>
                        {m.city}, {m.country} · {translateCategory(m.category, locale)}
                      </small>
                    </div>
                    <div style={{ textAlign: 'right', flexShrink: 0 }}>
                      <strong className="tabular" style={{ color: 'var(--accent)' }}>
                        {usd(m.reward, locale)}
                      </strong>
                      <Badge status={m.status} />
                    </div>
                  </button>
                );
              })}
            </div>
          </aside>
        </section>
      )}

      {/* VIEW 3: LIFECYCLE KANBAN */}
      {view === 'lifecycle' && (
        <section
          className="lifecycle-board"
          aria-label={c('Mission lifecycle board', 'Tablero de ciclo de vida')}
        >
          {STAGES.map((stage) => {
            const stageMissions = filtered.filter((m) => m.status === stage);
            const stageTotal = stageMissions.reduce((acc, m) => acc + m.reward, 0);
            return (
              <div className="lifecycle-col" key={stage}>
                <header className="lifecycle-col-head">
                  <div className="lifecycle-col-top">
                    <Badge status={stage} />
                    <span className="lifecycle-col-count">
                      {stageMissions.length}
                    </span>
                  </div>
                  <div className="lifecycle-col-sum">
                    {usd(stageTotal, locale)} {SETTLEMENT_SYMBOL}
                  </div>
                </header>
                <div className="lifecycle-col-body">
                  {stageMissions.map((m) => {
                    const agent = m.agentId ? agentById(m.agentId) : undefined;
                    return (
                      <Link
                        to={m.href}
                        key={m.id}
                        className="lifecycle-card"
                      >
                        <div
                          style={{
                            display: 'flex',
                            justifyContent: 'space-between',
                            gap: 6,
                            fontSize: 11,
                            color: 'var(--muted)',
                          }}
                        >
                          <span>{translateCategory(m.category, locale)}</span>
                          <span>
                            {m.city}, {m.country}
                          </span>
                        </div>
                        <div className="lifecycle-card-title">{m.title}</div>
                        <div className="lifecycle-card-foot">
                          <span className="lifecycle-card-reward">
                            {usd(m.reward, locale)}
                          </span>
                          <span>
                            {agent
                              ? agent.name
                              : `${m.matches} ${c('matches', 'compatibles')}`}
                          </span>
                        </div>
                      </Link>
                    );
                  })}
                  {stageMissions.length === 0 && (
                    <p
                      className="micro"
                      style={{ textAlign: 'center', padding: '24px 8px', margin: 0 }}
                    >
                      {c('No missions in stage', 'Sin misiones en esta etapa')}
                    </p>
                  )}
                </div>
              </div>
            );
          })}
        </section>
      )}

      {/* Secondary Action: Direct lookup by full PDA */}
      <details className="direct-lookup panel" style={{ padding: '14px 20px' }}>
        <summary>
          {c(
            'Open an on-chain work order by its full Solana PDA',
            'Abrir una orden de trabajo on-chain por su PDA completa de Solana'
          )}
        </summary>
        <form
          onSubmit={(e) => {
            e.preventDefault();
            try {
              const key = new PublicKey(address.trim()).toBase58();
              setAddressError('');
              navigate(`/app/missions/${key}`);
            } catch {
              setAddressError(
                c(
                  'Enter a valid base58 Solana address.',
                  'Introduce una dirección Solana base58 válida.'
                )
              );
            }
          }}
        >
          <label>
            {c('Work Order PDA', 'Work Order PDA')}
            <input
              value={address}
              onChange={(e) => setAddress(e.target.value)}
              autoComplete="off"
              spellCheck={false}
              placeholder={MINT.toBase58()}
            />
          </label>
          <button type="submit" className="button primary">
            {c('Open mission', 'Abrir misión')}
          </button>
        </form>
        {addressError && <p role="alert">{addressError}</p>}
      </details>
    </>
  );
}
