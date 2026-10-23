import { useMemo, useState } from 'react';
import { Link } from 'react-router';
import { useWallet } from '@solana/wallet-adapter-react';
import {
  AGENTS,
  SETTLEMENT_SYMBOL,
  totalCosts,
  usd,
  pct,
  useSnapshot,
  type AtlasAgent,
  type Embodiment,
  type OperationalState,
  type Sustainability,
} from '../../app/atlas';
import { api } from '../../app/api';
import { short } from '../../app/config';
import { useCopy, useI18n } from '../../app/i18n';
import { useResource } from '../../app/useResource';
import {
  CopyAddress,
  Empty,
  Icon,
  PageHeader,
  ProvenanceBadge,
} from '../../components/ui';
import { PROVENANCE_SOURCES, assertNoSilentAggregation } from '../../app/provenance';
import { WalletControl } from '../../components/ui/WalletControl';
import {
  AnimatedNumber,
  Donut,
  EarlyAccess,
  EmbodimentGlyph,
  Meter,
  Pulse,
  Sparkline,
  SustainabilityBadge,
  sustainabilityTone,
  type Tone,
} from '../../components/ui/viz';
import '../../styles/treasury.css';

export const OPERATOR_FLEET_IDS = [
  'lumen-array-2',
  'mantis-r2',
  'polar-cart-6',
  'halcyon-3',
  'kestrel-7',
  'orbis-edge-5',
  'delta-rover-1',
  'sentinel-grid-04',
];

const EMBODIMENT_LABELS: Record<Embodiment, [string, string]> = {
  Drone: ['Aerial drone', 'Dron aéreo'],
  Ugv: ['Ground rover (UGV)', 'Rover terrestre (UGV)'],
  Amr: ['Mobile robot (AMR)', 'Robot móvil (AMR)'],
  RobotArm: ['Robotic arm', 'Brazo robótico'],
  Camera: ['Vision node', 'Nodo de visión'],
  IotSensor: ['Sensor mesh', 'Malla sensorial'],
  Vehicle: ['Autonomous vehicle', 'Vehículo autónomo'],
  IndustrialMachine: ['Industrial CNC', 'Maquinaria industrial'],
  EdgeCompute: ['Edge compute', 'Cómputo edge'],
  EnergyAsset: ['Energy microgrid', 'Microred energética'],
};

const STATE_LABELS: Record<OperationalState, [string, string]> = {
  working: ['Working', 'En misión'],
  available: ['Available', 'Disponible'],
  charging: ['Charging', 'Cargando'],
  maintenance: ['Maintenance', 'Mantenimiento'],
};

const STATE_TONE: Record<OperationalState, Tone> = {
  working: 'accent',
  available: 'success',
  charging: 'violet',
  maintenance: 'warning',
};

type RemediationKey = 'lowerPrice' | 'autoInsurance' | 'highDemandRoute';

type FleetItem = AtlasAgent & { onChain?: boolean };

export default function FleetPage() {
  const { locale } = useI18n();
  const c = useCopy();
  const { publicKey, connected } = useWallet();
  const [snapshot, setSnapshot] = useSnapshot();

  // Optional live on-chain agent merge
  const liveAgents = useResource('fleet:live-agents', (signal) =>
    api.listAgents({ limit: 24 }, signal)
  );

  // Interactive operator UI state
  const [filter, setFilter] = useState<'all' | 'working' | 'available' | 'at-risk'>('all');
  const [pausedIds, setPausedIds] = useState<Record<string, boolean>>({});
  const [topUps, setTopUps] = useState<Record<string, number>>({});
  const [activeTopUpId, setActiveTopUpId] = useState<string | null>(null);
  const [remediations, setRemediations] = useState<
    Record<string, Partial<Record<RemediationKey, boolean>>>
  >({});

  // Autonomous spending policies state (EarlyAccess UI state)
  const [policyScope, setPolicyScope] = useState<string>('all');
  const [dailySpendLimit, setDailySpendLimit] = useState<number>(140);
  const [reinvestShare, setReinvestShare] = useState<number>(65);
  const [autoPayEnergy, setAutoPayEnergy] = useState<boolean>(true);
  const [autoPayMaintenance, setAutoPayMaintenance] = useState<boolean>(true);
  const [autoInsurancePolicy, setAutoInsurancePolicy] = useState<boolean>(true);
  const [runwayGuard, setRunwayGuard] = useState<boolean>(true);

  const fleet = useMemo<FleetItem[]>(() => {
    const base: FleetItem[] = snapshot
      ? OPERATOR_FLEET_IDS.map((id) => AGENTS.find((a) => a.id === id)).filter(
          (a): a is AtlasAgent => Boolean(a)
        )
      : [];

    const onChainRows: FleetItem[] = (liveAgents.data?.data ?? [])
      .filter((row) =>
        publicKey
          ? String(row.owner ?? '') === publicKey.toBase58() || base.length === 0
          : false
      )
      .slice(0, 4)
      .map(
        (row, idx): FleetItem => ({
          id: row.agent_account,
          account: row.agent_account,
          owner: String(row.owner ?? ''),
          signingAuthority: String(row.signing_authority ?? ''),
          name: row.agent_id ? short(row.agent_id) : `Machine #${idx + 1}`,
          model:
            typeof row.metadata_uri === 'string' && row.metadata_uri
              ? row.metadata_uri
              : c('On-chain registered unit', 'Unidad registrada on-chain'),
          embodiment: 'Drone',
          capabilities: [0, 5, 15],
          city: 'Solana',
          country: 'ON-CHAIN',
          position: [50, 50],
          state: row.active ? 'available' : 'maintenance',
          autonomy: 'Autonomous',
          reputation: 94,
          jobs: 18,
          successRate: 0.98,
          rate: 145,
          revenue30d: 3120,
          costs30d: {
            energy: 390,
            maintenance: 620,
            insurance: 410,
            connectivity: 140,
            protocol: 120,
          },
          treasury: 4250,
          bond: 800,
          conatus: 1.85,
          runwayDays: 76,
          sustainability: 'thriving',
          earnings: [80, 92, 85, 104, 110, 95, 115, 120, 108, 125, 130, 118],
          registeredDaysAgo: 14,
          uptime: 0.992,
          onChain: true,
        })
      );

    return [...onChainRows, ...base];
  }, [snapshot, liveAgents.data, publicKey, c]);

  // Compute effective per-agent numbers incorporating UI top-ups and applied remediations
  const enrichedFleet = useMemo(() => {
    return fleet.map((agent) => {
      const addedTreasury = topUps[agent.id] ?? 0;
      const applied = remediations[agent.id] ?? {};
      const boostFactor =
        1 +
        (applied.lowerPrice ? 0.14 : 0) +
        (applied.highDemandRoute ? 0.22 : 0);
      const costReduction = applied.autoInsurance ? 0.88 : 1;

      const rawCosts = totalCosts(agent);
      const effectiveCosts = Math.round(rawCosts * costReduction);
      const effectiveRevenue = Math.round(agent.revenue30d * boostFactor);
      const effectiveTreasury = agent.treasury + addedTreasury;
      const effectiveConatus =
        effectiveCosts > 0 ? effectiveRevenue / effectiveCosts : agent.conatus;
      const effectiveRunway = Math.max(
        1,
        Math.round(effectiveTreasury / (effectiveCosts / 30))
      );
      const effectiveSustainability: Sustainability =
        effectiveConatus >= 1.6
          ? 'thriving'
          : effectiveConatus >= 1
            ? 'stable'
            : 'at-risk';

      return {
        ...agent,
        effectiveRevenue,
        effectiveCosts,
        effectiveNet: effectiveRevenue - effectiveCosts,
        effectiveTreasury,
        effectiveConatus,
        effectiveRunway,
        effectiveSustainability,
        isPaused: Boolean(pausedIds[agent.id]),
        appliedCount: Object.values(applied).filter(Boolean).length,
      };
    });
  }, [fleet, topUps, remediations, pausedIds]);

  const onChainFleet = useMemo(
    () => enrichedFleet.filter((a) => a.onChain),
    [enrichedFleet]
  );
  const simulatedFleet = useMemo(
    () => enrichedFleet.filter((a) => !a.onChain),
    [enrichedFleet]
  );

  const kpis = useMemo(() => {
    // Audit check: All fleet financial metrics come from the simulation model.
    // If on-chain agents exist, their on-chain state tracks registry/identity, NOT historical revenue.
    // Therefore, financial KPIs are strictly SIMULATED projections.
    const onChainRevenue = onChainFleet.reduce((acc, a) => acc + (a.onChain ? 0 : a.effectiveRevenue), 0);
    const simulatedRevenue = simulatedFleet.reduce((acc, a) => acc + a.effectiveRevenue, 0);

    // Strict guardrail: assert no silent aggregation between on-chain financial figures and simulated models
    assertNoSilentAggregation(onChainRevenue, simulatedRevenue, 'Fleet Financial KPIs');

    // Isolate simulated dataset from on-chain dataset to prevent silent aggregation
    const targetSet = simulatedFleet.length > 0 ? simulatedFleet : enrichedFleet;
    const revenue30d = targetSet.reduce((acc, a) => acc + a.effectiveRevenue, 0);
    const costs30d = targetSet.reduce((acc, a) => acc + a.effectiveCosts, 0);
    const net30d = revenue30d - costs30d;
    const margin = revenue30d > 0 ? net30d / revenue30d : 0;
    const conatus = costs30d > 0 ? revenue30d / costs30d : 0;
    const treasury = targetSet.reduce((acc, a) => acc + a.effectiveTreasury, 0);
    const bond = targetSet.reduce((acc, a) => acc + a.bond, 0);
    const dailyBurn = costs30d / 30;
    const runwayDays = dailyBurn > 0 ? Math.round(treasury / dailyBurn) : 0;
    const combinedEarnings = Array.from({ length: 30 }, (_, dayIdx) =>
      targetSet.reduce((sum, a) => sum + (a.earnings[dayIdx] ?? 0), 0)
    );
    const sustainability: Sustainability =
      conatus >= 1.6 ? 'thriving' : conatus >= 1 ? 'stable' : 'at-risk';
    return {
      revenue30d,
      costs30d,
      net30d,
      margin,
      conatus,
      treasury,
      bond,
      runwayDays,
      combinedEarnings,
      sustainability,
      onChainCount: onChainFleet.length,
      simulatedCount: simulatedFleet.length,
    };
  }, [enrichedFleet, simulatedFleet, onChainFleet]);

  const filteredFleet = useMemo(() => {
    return enrichedFleet.filter((agent) => {
      if (filter === 'working') return !agent.isPaused && agent.state === 'working';
      if (filter === 'available') return !agent.isPaused && agent.state === 'available';
      if (filter === 'at-risk')
        return agent.conatus < 1 || agent.runwayDays < 30;
      return true;
    });
  }, [enrichedFleet, filter]);

  // Agents originally at-risk in the fleet so user can see and toggle remediations
  const atRiskAgents = useMemo(
    () => enrichedFleet.filter((a) => a.conatus < 1 || a.runwayDays < 30),
    [enrichedFleet]
  );

  // Revenue by embodiment Donut segments
  const embodimentSegments = useMemo(() => {
    const totals = new Map<Embodiment, number>();
    for (const agent of enrichedFleet) {
      totals.set(
        agent.embodiment,
        (totals.get(agent.embodiment) ?? 0) + agent.effectiveRevenue
      );
    }
    const palette: string[] = [
      'var(--accent)',
      'var(--success)',
      '#9fb4ff',
      'var(--warning)',
      '#63d2ff',
      '#e599f7',
      '#ff9da8',
    ];
    return Array.from(totals.entries())
      .sort((a, b) => b[1] - a[1])
      .map(([embodiment, value], i) => ({
        embodiment,
        label: EMBODIMENT_LABELS[embodiment][locale === 'es' ? 1 : 0],
        value,
        tone: palette[i % palette.length],
      }));
  }, [enrichedFleet, locale]);

  const activeTopUpAgent = useMemo(
    () => enrichedFleet.find((a) => a.id === activeTopUpId) ?? null,
    [enrichedFleet, activeTopUpId]
  );

  function togglePause(id: string) {
    setPausedIds((prev) => ({ ...prev, [id]: !prev[id] }));
  }

  function handleTopUp(id: string, amountUsdc: number) {
    setTopUps((prev) => ({ ...prev, [id]: (prev[id] ?? 0) + amountUsdc }));
  }

  function toggleRemediation(id: string, key: RemediationKey) {
    setRemediations((prev) => ({
      ...prev,
      [id]: {
        ...prev[id],
        [key]: !prev[id]?.[key],
      },
    }));
  }

  return (
    <>
      <PageHeader
        eyebrow={c('OPERATE / MY FLEET', 'OPERAR / MI FLOTA')}
        title={c('My fleet', 'Mi flota')}
        description={c(
          'Command your deployed machines, monitor their Conatus survival ratio and runway, and configure autonomous spending policies.',
          'Dirige tus máquinas desplegadas, supervisa su ratio de supervivencia Conatus y su autonomía, y configura políticas de gasto autónomo.'
        )}
        action={
          <Link className="button primary" to="/app/agents/register">
            <Icon name="plus" />
            {c('Register a machine', 'Registrar una máquina')}
          </Link>
        }
      />

      <p className="hint"><ProvenanceBadge meta={PROVENANCE_SOURCES.SIMULATED_FLEET_PROJECTION()} compact /> {c('Simulated economic scenario · fleet ratio does not include verified live assessments.', 'Escenario económico simulado · el ratio de flota no incluye evaluaciones reales verificadas.')}</p>

      {/* Operator wallet connection / preview bar */}
      <div className="operator-banner" role="region" aria-label={c('Operator session', 'Sesión de operador')}>
        <div className="operator-banner-info">
          <span className="operator-banner-icon" aria-hidden="true">
            <Icon name="fleet" />
          </span>
          <div>
            {connected && publicKey ? (
              <>
                <strong>
                  {c('Operator fleet authenticated', 'Flota de operador autenticada')}
                </strong>
                <p>
                  {c(
                    'Connected authority for policy signing and surplus yield withdrawals:',
                    'Autoridad conectada para firma de políticas y retiro de excedentes:'
                  )}{' '}
                  <CopyAddress value={publicKey.toBase58()} />
                </p>
              </>
            ) : (
              <>
                <strong>
                  {c(
                    'Operator fleet preview · Connect your wallet to sign on-chain actions',
                    'Vista de flota del operador · Conecta tu wallet para firmar acciones on-chain'
                  )}
                </strong>
                <p>
                  {c(
                    'Exploring your 8 deployed machines across 7 embodiments. Connect an operator wallet to authorize treasury withdrawals or register new hardware.',
                    'Explorando tus 8 máquinas desplegadas en 7 tipos de hardware. Conecta una wallet de operador para autorizar retiros de tesorería o registrar nuevo hardware.'
                  )}
                </p>
              </>
            )}
          </div>
        </div>
        <div className="operator-banner-actions">
          <WalletControl />
        </div>
      </div>

      {!enrichedFleet.length ? (
        <section className="panel">
          <Empty title={c('No machines in your fleet view', 'No hay máquinas en la vista de flota')}>
            {c(
              'Enable the network snapshot or register an on-chain machine to populate your operator console.',
              'Activa la instantánea de red o registra una máquina on-chain para poblar tu consola de operador.'
            )}
          </Empty>
          <div className="actions" style={{ justifyContent: 'center' }}>
            <button type="button" onClick={() => setSnapshot(true)}>
              {c('Enable network snapshot', 'Activar instantánea de red')}
            </button>
            <Link className="button primary" to="/app/agents/register">
              <Icon name="plus" />
              {c('Register a machine', 'Registrar una máquina')}
            </Link>
          </div>
        </section>
      ) : (
        <>
          {/* 5-KPI Row */}
          <section className="fleet-kpi-grid" aria-label={c('Fleet key performance indicators', 'Indicadores clave de la flota')}>
            <div className="kpi">
              <div className="kpi-label">
                <span>{c('Fleet revenue (30d)', 'Ingresos de flota (30d)')}</span>
                <Icon name="coin" />
              </div>
              <div style={{ display: 'flex', alignItems: 'baseline', gap: 8, marginTop: 4 }}>
                <strong>
                  <AnimatedNumber
                    value={kpis.revenue30d}
                    format={(v) => usd(v, locale)}
                  />
                </strong>
                <ProvenanceBadge
                  meta={PROVENANCE_SOURCES.SIMULATED_FLEET_PROJECTION()}
                  compact
                />
              </div>
              <div className="kpi-foot">
                <span className="delta-up">+14.8%</span>
                <span>
                  {kpis.onChainCount > 0
                    ? c('{onChain} on-chain · {sim} simulated', '{onChain} on-chain · {sim} simuladas')
                        .replace('{onChain}', String(kpis.onChainCount))
                        .replace('{sim}', String(kpis.simulatedCount))
                    : `${kpis.simulatedCount} ${c('machines', 'máquinas')} · ${SETTLEMENT_SYMBOL}`}
                </span>
              </div>
              <Sparkline values={kpis.combinedEarnings} tone="accent" width={110} height={32} />
            </div>

            <div className="kpi">
              <div className="kpi-label">
                <span>{c('Operating costs (30d)', 'Costos operativos (30d)')}</span>
                <Icon name="bolt" />
              </div>
              <div style={{ display: 'flex', alignItems: 'baseline', gap: 8, marginTop: 4 }}>
                <strong>
                  <AnimatedNumber
                    value={kpis.costs30d}
                    format={(v) => usd(v, locale)}
                  />
                </strong>
                <ProvenanceBadge
                  meta={PROVENANCE_SOURCES.SIMULATED_FLEET_PROJECTION()}
                  compact
                />
              </div>
              <div className="kpi-foot">
                <span>
                  {c(
                    'Energy · Maint. · Insurance',
                    'Energía · Manten. · Seguro'
                  )}
                </span>
              </div>
            </div>

            <div className="kpi">
              <div className="kpi-label">
                <span>{c('Net margin (30d)', 'Margen neto (30d)')}</span>
                <Icon name="economy" />
              </div>
              <div style={{ display: 'flex', alignItems: 'baseline', gap: 8, marginTop: 4 }}>
                <strong>
                  <AnimatedNumber
                    value={kpis.net30d}
                    format={(v) => usd(v, locale)}
                  />
                </strong>
                <ProvenanceBadge
                  meta={PROVENANCE_SOURCES.SIMULATED_FLEET_PROJECTION()}
                  compact
                />
              </div>
              <div className="kpi-foot">
                <span className={kpis.margin >= 0 ? 'delta-up' : 'delta-down'}>
                  {pct(kpis.margin, locale, 1)} {c('net margin', 'margen neto')}
                </span>
                <span>{c('After autonomous costs', 'Tras costos autónomos')}</span>
              </div>
            </div>

            <div className="kpi">
              <div className="kpi-label">
                <span>{c('Fleet Conatus ratio', 'Ratio Conatus promedio')}</span>
                <Icon name="flame" />
              </div>
              <div style={{ display: 'flex', alignItems: 'baseline', gap: 8, marginTop: 4 }}>
                <strong>
                  <AnimatedNumber
                    value={kpis.conatus}
                    format={(v) => `${v.toFixed(2)}×`}
                  />
                </strong>
                <ProvenanceBadge
                  meta={PROVENANCE_SOURCES.SIMULATED_FLEET_PROJECTION()}
                  compact
                />
              </div>
              <div className="kpi-foot">
                <SustainabilityBadge value={kpis.sustainability} />
                <span>{c('Target ≥ 1.00×', 'Meta ≥ 1.00×')}</span>
              </div>
            </div>

            <div className="kpi">
              <div className="kpi-label">
                <span>{c('Combined treasury & runway', 'Tesorería y autonomía')}</span>
                <Icon name="shield" />
              </div>
              <div style={{ display: 'flex', alignItems: 'baseline', gap: 8, marginTop: 4 }}>
                <strong>
                  <AnimatedNumber
                    value={kpis.treasury}
                    format={(v) => usd(v, locale)}
                  />
                </strong>
                <ProvenanceBadge
                  meta={PROVENANCE_SOURCES.SIMULATED_FLEET_PROJECTION()}
                  compact
                />
              </div>
              <div className="kpi-foot">
                <span className="delta-up">
                  {kpis.runwayDays}d {c('runway', 'autonomía')}
                </span>
                <span>
                  +{usd(kpis.bond, locale, true)} {c('bonded', 'en fianza')}
                </span>
              </div>
            </div>
          </section>

          {/* Fleet Table Panel */}
          <section className="panel">
            <div className="panel-title">
              <div>
                <h2>{c('Deployed machines', 'Máquinas desplegadas')}</h2>
                <p>
                  {c(
                    'Real-time operational state, 30-day economic self-sustainability, and per-machine treasury controls.',
                    'Estado operativo en tiempo real, autosostenibilidad económica a 30 días y controles de tesorería por máquina.'
                  )}
                </p>
              </div>
              <div
                className="chip-filters"
                role="group"
                aria-label={c('Filter fleet machines', 'Filtrar máquinas de la flota')}
              >
                {(
                  [
                    ['all', c(`All (${enrichedFleet.length})`, `Todas (${enrichedFleet.length})`)],
                    [
                      'working',
                      c(
                        `Working (${enrichedFleet.filter((a) => !a.isPaused && a.state === 'working').length})`,
                        `En misión (${enrichedFleet.filter((a) => !a.isPaused && a.state === 'working').length})`
                      ),
                    ],
                    [
                      'available',
                      c(
                        `Available (${enrichedFleet.filter((a) => !a.isPaused && a.state === 'available').length})`,
                        `Disponibles (${enrichedFleet.filter((a) => !a.isPaused && a.state === 'available').length})`
                      ),
                    ],
                    [
                      'at-risk',
                      c(
                        `At-risk (${atRiskAgents.length})`,
                        `En riesgo (${atRiskAgents.length})`
                      ),
                    ],
                  ] as const
                ).map(([key, label]) => (
                  <button
                    key={key}
                    type="button"
                    aria-pressed={filter === key}
                    onClick={() => setFilter(key)}
                  >
                    {label}
                  </button>
                ))}
              </div>
            </div>

            {activeTopUpAgent && (
              <div
                className="topup-bar"
                role="region"
                aria-label={c('Top up machine treasury', 'Recargar tesorería de máquina')}
              >
                <div className="topup-bar-copy">
                  <strong>
                    <Icon name="coin" />
                    {c(
                      `Top up ${activeTopUpAgent.name} treasury`,
                      `Recargar tesorería de ${activeTopUpAgent.name}`
                    )}
                    <EarlyAccess />
                  </strong>
                  <p>
                    {c(
                      `Current reserve: ${usd(activeTopUpAgent.effectiveTreasury, locale)} (${activeTopUpAgent.effectiveRunway}d runway). Inject ${SETTLEMENT_SYMBOL} to extend autonomous survival runway.`,
                      `Reserva actual: ${usd(activeTopUpAgent.effectiveTreasury, locale)} (${activeTopUpAgent.effectiveRunway}d de autonomía). Inyecta ${SETTLEMENT_SYMBOL} para extender su autonomía operativa.`
                    )}
                  </p>
                </div>
                <div className="topup-controls">
                  {[250, 500, 1000].map((amt) => (
                    <button
                      key={amt}
                      type="button"
                      className="btn-compact primary"
                      onClick={() => handleTopUp(activeTopUpAgent.id, amt)}
                    >
                      +{usd(amt, locale)} {SETTLEMENT_SYMBOL}
                    </button>
                  ))}
                  <button
                    type="button"
                    className="btn-compact"
                    onClick={() => setActiveTopUpId(null)}
                  >
                    {c('Done', 'Listo')}
                  </button>
                </div>
              </div>
            )}

            <div className="table-scroll">
              <table className="rank-table">
                <thead>
                  <tr>
                    <th>{c('Machine', 'Máquina')}</th>
                    <th>{c('State', 'Estado')}</th>
                    <th>{c('Conatus ratio', 'Ratio Conatus')}</th>
                    <th className="num">{c('Runway & reserve', 'Autonomía y reserva')}</th>
                    <th className="num">
                      {c('Revenue (30d)', 'Ingresos (30d)')}{' '}
                      <ProvenanceBadge meta={PROVENANCE_SOURCES.SIMULATED_FLEET_PROJECTION()} compact />
                    </th>
                    <th className="num">{c('Net (30d)', 'Neto (30d)')}</th>
                    <th>{c('30d trend', 'Tendencia 30d')}</th>
                    <th className="num">{c('Actions', 'Acciones')}</th>
                  </tr>
                </thead>
                <tbody>
                  {filteredFleet.map((agent) => {
                    const stateLabel = agent.isPaused
                      ? c('Paused', 'En pausa')
                      : STATE_LABELS[agent.state][locale === 'es' ? 1 : 0];
                    const stateTone: Tone = agent.isPaused
                      ? 'warning'
                      : STATE_TONE[agent.state];
                    return (
                      <tr key={agent.id}>
                        <td>
                          <Link to={`/app/agents/${agent.id}`} className="agent-cell">
                            <EmbodimentGlyph
                              embodiment={agent.embodiment}
                              size={40}
                              tone={agent.effectiveSustainability}
                            />
                            <div>
                              <strong>
                                {agent.name}{' '}
                                {agent.onChain ? (
                                  <ProvenanceBadge
                                    meta={PROVENANCE_SOURCES.ONCHAIN_AGENT_REGISTRY('Solana Localnet')}
                                    compact
                                  />
                                ) : (
                                  <ProvenanceBadge
                                    meta={PROVENANCE_SOURCES.SIMULATED_FLEET_PROJECTION()}
                                    compact
                                  />
                                )}
                              </strong>
                              <small>
                                {agent.model} · {agent.city}, {agent.country}
                              </small>
                            </div>
                          </Link>
                        </td>
                        <td>
                          <span
                            className={`fleet-state-pill ${agent.isPaused ? 'is-paused' : ''}`}
                          >
                            <Pulse tone={stateTone} />
                            {stateLabel}
                          </span>
                        </td>
                        <td>
                          <div className="conatus-cell">
                            <div className="conatus-cell-top">
                              <strong>{agent.effectiveConatus.toFixed(2)}×</strong>
                              <SustainabilityBadge value={agent.effectiveSustainability} />
                            </div>
                            <Meter
                              value={Math.min(1, agent.effectiveConatus / 2.2)}
                              tone={sustainabilityTone(agent.effectiveSustainability)}
                              label={`${agent.name} Conatus ${agent.effectiveConatus.toFixed(2)}x`}
                            />
                          </div>
                        </td>
                        <td className="num runway-cell">
                          <strong>{agent.effectiveRunway}d</strong>
                          <small>{usd(agent.effectiveTreasury, locale)}</small>
                        </td>
                        <td className="num">{usd(agent.effectiveRevenue, locale)}</td>
                        <td
                          className={`num ${agent.effectiveNet >= 0 ? 'delta-up' : 'delta-down'}`}
                        >
                          {agent.effectiveNet >= 0 ? '+' : ''}
                          {usd(agent.effectiveNet, locale)}
                        </td>
                        <td>
                          <Sparkline
                            values={agent.earnings}
                            tone={sustainabilityTone(agent.effectiveSustainability)}
                            width={108}
                            height={30}
                          />
                        </td>
                        <td className="num">
                          <div className="fleet-row-actions">
                            <Link
                              to={`/app/agents/${agent.id}`}
                              className="button btn-compact"
                            >
                              {c('View', 'Ver')}
                            </Link>
                            <button
                              type="button"
                              className={`btn-compact ${agent.isPaused ? 'is-active' : ''}`}
                              onClick={() => togglePause(agent.id)}
                            >
                              {agent.isPaused
                                ? c('Resume work', 'Reanudar')
                                : c('Pause work', 'Pausar')}
                            </button>
                            <button
                              type="button"
                              className={`btn-compact ${activeTopUpId === agent.id ? 'is-active' : ''}`}
                              onClick={() =>
                                setActiveTopUpId((cur) =>
                                  cur === agent.id ? null : agent.id
                                )
                              }
                            >
                              {c('Top up treasury', 'Recargar tesorería')}
                            </button>
                          </div>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </section>

          {/* Split Row: Alerts Panel (At-Risk Machines) + Revenue by Embodiment Donut */}
          <div className="split" style={{ marginBottom: 24 }}>
            <section className="panel">
              <div className="panel-title">
                <div>
                  <h2>
                    {c(
                      'Survival alerts & interventions',
                      'Alertas de supervivencia e intervenciones'
                    )}
                  </h2>
                  <p>
                    {c(
                      'Machines with a Conatus ratio below 1.00× or compressed runway require pricing or routing adjustments.',
                      'Las máquinas con ratio Conatus menor a 1.00× o autonomía reducida requieren ajustes de tarifa o enrutamiento.'
                    )}
                  </p>
                </div>
                <span className="sustain sustain-at-risk">
                  <span aria-hidden="true" />
                  {atRiskAgents.filter((a) => a.effectiveConatus < 1).length}{' '}
                  {c('at risk', 'en riesgo')}
                </span>
              </div>

              <div className="alert-list">
                {atRiskAgents.map((agent) => {
                  const applied = remediations[agent.id] ?? {};
                  const stabilized = agent.effectiveConatus >= 1;
                  return (
                    <article
                      key={agent.id}
                      className={`alert-card ${stabilized ? 'is-stabilized' : ''}`}
                    >
                      <div className="alert-head">
                        <Link to={`/app/agents/${agent.id}`} className="agent-cell">
                          <EmbodimentGlyph
                            embodiment={agent.embodiment}
                            size={38}
                            tone={agent.effectiveSustainability}
                          />
                          <div>
                            <strong>
                              {agent.name} · {agent.city}, {agent.country}
                            </strong>
                            <small>
                              {stabilized
                                ? c(
                                    'Projected ratio stabilized above self-sustaining threshold.',
                                    'Ratio proyectado estabilizado por encima del umbral autosostenible.'
                                  )
                                : c(
                                    'Operating costs exceed 30d revenue; treasury reserve is depleting.',
                                    'Los costos operativos superan los ingresos de 30d; la reserva se está agotando.'
                                  )}
                            </small>
                          </div>
                        </Link>
                        <SustainabilityBadge value={agent.effectiveSustainability} />
                      </div>

                      <div className="alert-metrics">
                        <span>
                          {c('Conatus ratio:', 'Ratio Conatus:')}{' '}
                          <strong>{agent.effectiveConatus.toFixed(2)}×</strong>
                        </span>
                        <span>
                          {c('Runway:', 'Autonomía:')}{' '}
                          <strong>{agent.effectiveRunway}d</strong>
                        </span>
                        <span>
                          {c('30d net:', 'Neto 30d:')}{' '}
                          <strong>{usd(agent.effectiveNet, locale)}</strong>
                        </span>
                        <span>
                          {c('Treasury:', 'Tesorería:')}{' '}
                          <strong>{usd(agent.effectiveTreasury, locale)}</strong>
                        </span>
                      </div>

                      <div
                        className="alert-actions"
                        role="group"
                        aria-label={c(
                          `Suggested interventions for ${agent.name}`,
                          `Intervenciones sugeridas para ${agent.name}`
                        )}
                      >
                        <button
                          type="button"
                          aria-pressed={Boolean(applied.lowerPrice)}
                          onClick={() => toggleRemediation(agent.id, 'lowerPrice')}
                        >
                          {applied.lowerPrice ? '✓ ' : ''}
                          {c('Lower price', 'Reducir tarifa')}
                        </button>
                        <button
                          type="button"
                          aria-pressed={Boolean(applied.autoInsurance)}
                          onClick={() => toggleRemediation(agent.id, 'autoInsurance')}
                        >
                          {applied.autoInsurance ? '✓ ' : ''}
                          {c('Enable auto-insurance', 'Activar autoseguro')}
                        </button>
                        <button
                          type="button"
                          aria-pressed={Boolean(applied.highDemandRoute)}
                          onClick={() => toggleRemediation(agent.id, 'highDemandRoute')}
                        >
                          {applied.highDemandRoute ? '✓ ' : ''}
                          {c(
                            'Route to higher-demand missions',
                            'Enrutar a misiones de alta demanda'
                          )}
                        </button>
                      </div>
                    </article>
                  );
                })}
              </div>
            </section>

            {/* Revenue by Embodiment Donut */}
            <section className="panel">
              <div className="panel-title">
                <div>
                  <h2>{c('Revenue by embodiment', 'Ingresos por tipo de hardware')}</h2>
                  <p>
                    {c(
                      '30-day settled revenue distribution across physical machine classes.',
                      'Distribución de ingresos liquidados en 30 días por clase de máquina física.'
                    )}
                  </p>
                </div>
              </div>

              <div className="embodiment-donut-layout">
                <Donut
                  segments={embodimentSegments}
                  size={172}
                  center={
                    <>
                      <strong>{usd(kpis.revenue30d, locale, true)}</strong>
                      <small>{c('30d gross', 'Bruto 30d')}</small>
                    </>
                  }
                />
                <ul className="embodiment-legend">
                  {embodimentSegments.map((seg) => (
                    <li key={seg.embodiment}>
                      <span
                        className="embodiment-swatch"
                        style={{ background: seg.tone }}
                        aria-hidden="true"
                      />
                      <span>{seg.label}</span>
                      <strong>{usd(seg.value, locale)}</strong>
                      <small>
                        {pct(
                          kpis.revenue30d > 0 ? seg.value / kpis.revenue30d : 0,
                          locale,
                          0
                        )}
                      </small>
                    </li>
                  ))}
                </ul>
              </div>
            </section>
          </div>

          {/* Autonomous Spending Policies Panel (EarlyAccess) */}
          <section className="panel">
            <div className="panel-title">
              <div>
                <h2 style={{ display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap' }}>
                  {c('Autonomous spending policies', 'Políticas de gasto autónomo')}
                  <EarlyAccess />
                </h2>
                <p>
                  {c(
                    'Define how your machines autonomously pay for energy, maintenance, and insurance from their own earnings and how surplus profit is split.',
                    'Define cómo tus máquinas pagan autónomamente su energía, mantenimiento y seguro con sus propios ingresos y cómo se reparte el excedente.'
                  )}
                </p>
              </div>
              <label style={{ minWidth: 210 }}>
                <span className="sr-only">
                  {c('Policy target scope', 'Alcance de la política')}
                </span>
                <select
                  value={policyScope}
                  onChange={(e) => setPolicyScope(e.target.value)}
                  aria-label={c('Policy target scope', 'Alcance de la política')}
                >
                  <option value="all">
                    {c(
                      `All fleet machines (${enrichedFleet.length})`,
                      `Todas las máquinas de la flota (${enrichedFleet.length})`
                    )}
                  </option>
                  {enrichedFleet.map((agent) => (
                    <option key={agent.id} value={agent.id}>
                      {agent.name} ({agent.city})
                    </option>
                  ))}
                </select>
              </label>
            </div>

            <div className="policy-grid">
              <div className="stack" style={{ marginBottom: 0, gap: 16 }}>
                <div className="policy-box">
                  <div className="policy-box-head">
                    <label htmlFor="daily-spend-slider">
                      <strong>
                        {c(
                          'Per-agent daily spend limit',
                          'Límite de gasto diario por agente'
                        )}
                      </strong>
                    </label>
                    <span className="policy-readout">
                      {usd(dailySpendLimit, locale)} / {c('day', 'día')}
                    </span>
                  </div>
                  <p className="micro" style={{ margin: 0 }}>
                    {c(
                      'Maximum autonomous outflow per machine every 24h for charging, parts, and connectivity without human co-signing.',
                      'Flujo máximo de salida autónomo por máquina cada 24h para carga, repuestos y conectividad sin requerir co-firma humana.'
                    )}
                  </p>
                  <input
                    id="daily-spend-slider"
                    type="range"
                    className="policy-range"
                    min={25}
                    max={500}
                    step={5}
                    value={dailySpendLimit}
                    onChange={(e) => setDailySpendLimit(Number(e.target.value))}
                  />
                  <div className="policy-range-labels">
                    <span>$25 {SETTLEMENT_SYMBOL}</span>
                    <span>{c('Recommended: $140', 'Recomendado: $140')}</span>
                    <span>$500 {SETTLEMENT_SYMBOL}</span>
                  </div>
                </div>

                <div className="policy-box">
                  <div className="policy-box-head">
                    <label htmlFor="reinvest-slider">
                      <strong>
                        {c(
                          'Net profit reinvestment rule',
                          'Regla de reinversión de beneficio neto'
                        )}
                      </strong>
                    </label>
                    <span className="policy-readout">
                      {reinvestShare}% / {100 - reinvestShare}%
                    </span>
                  </div>
                  <p className="micro" style={{ margin: 0 }}>
                    {c(
                      'Share of settled net profit retained in the machine treasury to compound runway vs. swept to the operator wallet.',
                      'Porcentaje del beneficio neto liquidado que permanece en la tesorería de la máquina para ampliar su autonomía frente al retiro al operador.'
                    )}
                  </p>
                  <input
                    id="reinvest-slider"
                    type="range"
                    className="policy-range"
                    min={0}
                    max={100}
                    step={5}
                    value={reinvestShare}
                    onChange={(e) => setReinvestShare(Number(e.target.value))}
                  />
                  <div className="policy-split-bar" aria-hidden="true">
                    <span style={{ width: `${reinvestShare}%` }} />
                    <span />
                  </div>
                  <div className="policy-split-legend">
                    <span>
                      <strong>{reinvestShare}%</strong>{' '}
                      {c('Machine treasury reserve', 'Reserva de tesorería de la máquina')} (
                      {usd(Math.max(0, (kpis.net30d * reinvestShare) / 100), locale)}/mo)
                    </span>
                    <span>
                      <strong>{100 - reinvestShare}%</strong>{' '}
                      {c('Withdraw to owner', 'Retiro al propietario')} (
                      {usd(
                        Math.max(0, (kpis.net30d * (100 - reinvestShare)) / 100),
                        locale
                      )}
                      /mo)
                    </span>
                  </div>
                </div>
              </div>

              <div className="switch-list" role="group" aria-label={c('Autonomous settlement rules', 'Reglas de liquidación autónoma')}>
                <div className="switch-row">
                  <div className="switch-row-copy">
                    <strong>
                      <Icon name="bolt" />
                      {c('Auto-pay energy & charging', 'Autopago de energía y carga')}
                    </strong>
                    <p>
                      {c(
                        'Authorize machines to settle kilowatt-hour and depot charging invoices directly from their treasury.',
                        'Autoriza a las máquinas a liquidar facturas de carga y kilovatios-hora directamente desde su tesorería.'
                      )}
                    </p>
                  </div>
                  <button
                    type="button"
                    role="switch"
                    aria-checked={autoPayEnergy}
                    aria-label={c('Auto-pay energy & charging', 'Autopago de energía y carga')}
                    className="toggle-switch"
                    onClick={() => setAutoPayEnergy((v) => !v)}
                  >
                    <span className="toggle-switch-thumb" />
                  </button>
                </div>

                <div className="switch-row">
                  <div className="switch-row-copy">
                    <strong>
                      <Icon name="wrench" />
                      {c(
                        'Auto-pay scheduled maintenance',
                        'Autopago de mantenimiento preventivo'
                      )}
                    </strong>
                    <p>
                      {c(
                        'Automatically escrow wear-and-tear reserves and pay certified service bays after telemetry diagnostics.',
                        'Reserva automáticamente fondos por desgaste y paga a talleres certificados tras diagnósticos de telemetría.'
                      )}
                    </p>
                  </div>
                  <button
                    type="button"
                    role="switch"
                    aria-checked={autoPayMaintenance}
                    aria-label={c(
                      'Auto-pay scheduled maintenance',
                      'Autopago de mantenimiento preventivo'
                    )}
                    className="toggle-switch"
                    onClick={() => setAutoPayMaintenance((v) => !v)}
                  >
                    <span className="toggle-switch-thumb" />
                  </button>
                </div>

                <div className="switch-row">
                  <div className="switch-row-copy">
                    <strong>
                      <Icon name="shield" />
                      {c(
                        'Per-mission liability & hull insurance',
                        'Seguro de responsabilidad y casco por misión'
                      )}
                    </strong>
                    <p>
                      {c(
                        'Attach parametric coverage on every claimed mission to protect machine bond against field incidents.',
                        'Adjunta cobertura paramétrica en cada misión reclamada para proteger la fianza de la máquina ante incidentes.'
                      )}
                    </p>
                  </div>
                  <button
                    type="button"
                    role="switch"
                    aria-checked={autoInsurancePolicy}
                    aria-label={c(
                      'Per-mission liability & hull insurance',
                      'Seguro de responsabilidad y casco por misión'
                    )}
                    className="toggle-switch"
                    onClick={() => setAutoInsurancePolicy((v) => !v)}
                  >
                    <span className="toggle-switch-thumb" />
                  </button>
                </div>

                <div className="switch-row">
                  <div className="switch-row-copy">
                    <strong>
                      <Icon name="clock" />
                      {c(
                        'Low-runway survival guard (< 15 days)',
                        'Protección de autonomía crítica (< 15 días)'
                      )}
                    </strong>
                    <p>
                      {c(
                        'Reject low-margin missions and hold owner profit sweeps whenever a machine falls below 15 days of operating runway.',
                        'Rechaza misiones de bajo margen y suspende el retiro de utilidades cuando una máquina baje de 15 días de autonomía.'
                      )}
                    </p>
                  </div>
                  <button
                    type="button"
                    role="switch"
                    aria-checked={runwayGuard}
                    aria-label={c(
                      'Low-runway survival guard (< 15 days)',
                      'Protección de autonomía crítica (< 15 días)'
                    )}
                    className="toggle-switch"
                    onClick={() => setRunwayGuard((v) => !v)}
                  >
                    <span className="toggle-switch-thumb" />
                  </button>
                </div>
              </div>
            </div>
          </section>
        </>
      )}
    </>
  );
}
