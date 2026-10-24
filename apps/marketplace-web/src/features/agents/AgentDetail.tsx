import { useMemo } from 'react';
import { Link, useParams } from 'react-router';
import { useConnection } from '@solana/wallet-adapter-react';
import {
  EVENTS,
  MISSIONS,
  SETTLEMENT_SYMBOL,
  agentById,
  ago,
  missionById,
  num,
  pct,
  totalCosts,
  usd,
  type AtlasAgent,
  type AtlasEvent,
} from '../../app/atlas';
import { api, verifyMeta, verifyNetwork } from '../../app/api';
import { CAPABILITIES, date, field, short } from '../../app/config';
import { useCopy, useI18n } from '../../app/i18n';
import { readAccount } from '../../app/readAccount';
import { useResource } from '../../app/useResource';
import {
  Badge,
  Capabilities,
  CopyAddress,
  DataGrid,
  Diagnostics,
  Empty,
  Icon,
  PageHeader,
  ProvenanceBadge,
  ResourceState,
} from '../../components/ui';
import { PROVENANCE_SOURCES } from '../../app/provenance';
import {
  AnimatedNumber,
  Bars,
  Donut,
  EarlyAccess,
  EmbodimentGlyph,
  Identicon,
  Meter,
  Pulse,
  Ring,
  SustainabilityBadge,
  sustainabilityTone,
  type Tone,
} from '../../components/ui/viz';
import {
  EMBODIMENT_PRESETS,
  embodimentLabel,
  stateMeta,
} from './data';
import '../../styles/agents.css';
import { LiveSolvencyPanel } from './LiveSolvencyPanel';
import { AgentBudgetPolicyPanel } from './AgentBudgetPolicyPanel';

export default function AgentDetail() {
  const { agentId = '' } = useParams();
  const atlasAgent = useMemo(
    () => agentById(agentId),
    [agentId]
  );

  if (atlasAgent) {
    return <AtlasAgentProfile agent={atlasAgent} />;
  }
  return <LiveAgentProfile agentId={agentId} />;
}

function AtlasAgentProfile({ agent }: { agent: AtlasAgent }) {
  const { t, locale } = useI18n();
  const c = useCopy();

  const costs = totalCosts(agent);
  const net30d = agent.revenue30d - costs;
  const dailyBurn = costs / 30;
  const dailyRevenue = agent.revenue30d / 30;
  const state = stateMeta(agent.state, c);
  const tone = sustainabilityTone(agent.sustainability);
  const preset = EMBODIMENT_PRESETS[agent.embodiment];

  const costSegments: {
    key: keyof AtlasAgent['costs30d'];
    label: string;
    value: number;
    tone: Tone;
    color: string;
  }[] = [
    {
      key: 'energy',
      label: c('Energy & charging', 'Energía y carga'),
      value: agent.costs30d.energy,
      tone: 'accent',
      color: 'var(--accent)',
    },
    {
      key: 'maintenance',
      label: c('Maintenance & parts', 'Mantenimiento y piezas'),
      value: agent.costs30d.maintenance,
      tone: 'success',
      color: 'var(--success)',
    },
    {
      key: 'insurance',
      label: c('Hull & liability insurance', 'Seguro de casco y resp. civil'),
      value: agent.costs30d.insurance,
      tone: 'violet',
      color: '#9fb4ff',
    },
    {
      key: 'connectivity',
      label: c('RTK & satellite comms', 'Conectividad RTK y satelital'),
      value: agent.costs30d.connectivity,
      tone: 'warning',
      color: 'var(--warning)',
    },
    {
      key: 'protocol',
      label: c('Protocol settlement fee', 'Comisión de liquidación'),
      value: agent.costs30d.protocol,
      tone: 'muted',
      color: 'var(--muted)',
    },
  ];

  // Assigned missions + compatible open missions
  const assignedMissions = useMemo(
    () => MISSIONS.filter((m) => m.agentId === agent.id),
    [agent.id]
  );
  const compatibleMissions = useMemo(
    () =>
      MISSIONS.filter(
        (m) =>
          m.agentId !== agent.id &&
          m.status === 'Open' &&
          m.capabilities.some((cap) => agent.capabilities.includes(cap))
      ).slice(0, Math.max(2, 5 - assignedMissions.length)),
    [agent.id, agent.capabilities, assignedMissions.length]
  );

  // Events for this agent (supplemented deterministically so every profile has a rich feed)
  const agentEvents = useMemo<AtlasEvent[]>(() => {
    const direct = EVENTS.filter((e) => e.agentId === agent.id);
    const fallbackMission = assignedMissions[0] ?? compatibleMissions[0] ?? MISSIONS[0];
    const extra: AtlasEvent[] = [
      {
        id: `${agent.id}-ev-settled`,
        kind: 'settled',
        minutesAgo: 38,
        agentId: agent.id,
        missionId: fallbackMission?.id,
        amount: agent.rate,
        signature: `${agent.account.slice(0, 44)}${agent.signingAuthority.slice(0, 44)}`,
      },
      {
        id: `${agent.id}-ev-energy`,
        kind: 'expense',
        minutesAgo: 190,
        agentId: agent.id,
        amount: Math.round((agent.costs30d.energy / 30) * 100) / 100,
        detail: 'energy',
        signature: `${agent.signingAuthority.slice(0, 44)}${agent.owner.slice(0, 44)}`,
      },
      {
        id: `${agent.id}-ev-verified`,
        kind: 'verified',
        minutesAgo: 420,
        agentId: agent.id,
        missionId: fallbackMission?.id,
        signature: `${agent.owner.slice(0, 44)}${agent.account.slice(0, 44)}`,
      },
      {
        id: `${agent.id}-ev-maint`,
        kind: 'expense',
        minutesAgo: 980,
        agentId: agent.id,
        amount: Math.round((agent.costs30d.maintenance / 15) * 100) / 100,
        detail: 'maintenance',
        signature: `${agent.account.slice(0, 44)}${agent.owner.slice(0, 44)}`,
      },
    ];
    return [...direct, ...extra]
      .sort((a, b) => a.minutesAgo - b.minutesAgo)
      .slice(0, 6);
  }, [agent, assignedMissions, compatibleMissions]);

  const capabilityBitmask = useMemo(() => {
    let mask = 0n;
    for (const idx of agent.capabilities) {
      mask |= 1n << BigInt(idx);
    }
    return `0x${mask.toString(16).toUpperCase().padStart(4, '0')}`;
  }, [agent.capabilities]);

  return (
    <>
      <p className="hint"><ProvenanceBadge meta={PROVENANCE_SOURCES.SIMULATED_AGENT_ECONOMICS(agent.name)} compact /> {c('Simulated economic scenario · Atlas values are illustrative.', 'Escenario económico simulado · Los valores Atlas son ilustrativos.')}</p>
      <nav className="agent-breadcrumb" aria-label={c('Agent navigation', 'Navegación de agente')}>
        <Link to="/app/agents">
          ← {c('All autonomous agents', 'Todos los agentes autónomos')}
        </Link>
        <span className="muted">
          {embodimentLabel(agent.embodiment, c)} · {agent.city}, {agent.country}
        </span>
      </nav>

      {/* Hero Profile Banner */}
      <section className="hero-panel" aria-labelledby="agent-profile-title">
        <div className="agent-hero-grid">
          <div className="agent-hero-main">
            <EmbodimentGlyph
              embodiment={agent.embodiment}
              size={72}
              tone={agent.sustainability}
            />
            <div className="agent-hero-copy">
              <span className="eyebrow">
                {embodimentLabel(agent.embodiment, c).toUpperCase()} ·{' '}
                {agent.autonomy === 'Autonomous'
                  ? c('FULL AUTONOMY', 'AUTONOMÍA TOTAL')
                  : c('SUPERVISED AUTONOMY', 'AUTONOMÍA SUPERVISADA')}
              </span>
              <h1 id="agent-profile-title" tabIndex={-1}>
                {agent.name}
              </h1>
              <p className="agent-hero-Subtitle">{agent.model}</p>

              <div className="agent-hero-pills">
                <span className="agent-pill">
                  <Pulse tone={state.tone} />
                  {state.label}
                </span>
                <SustainabilityBadge value={agent.sustainability} />
                <span className="agent-pill">
                  <Icon name="pin" />
                  {agent.city}, {agent.country}
                </span>
                <span className="agent-pill">
                  <Icon name="shield" />
                  {c('Reputation', 'Reputación')} {agent.reputation}/100
                </span>
                <span className="agent-pill">
                  <Icon name="clock" />
                  {num(agent.registeredDaysAgo, locale)}d {c('on-chain', 'en la red')}
                </span>
              </div>
            </div>
          </div>

          <div className="agent-hero-side">
            <div className="agent-rate-box">
              <small>{c('Standard mission rate', 'Tarifa estándar por misión')}</small>
              <strong>
                {usd(agent.rate, locale)} {SETTLEMENT_SYMBOL}
              </strong>
            </div>
            <div className="agent-hero-actions">
              <Link
                className="button primary"
                to={`/app/missions/new?agent=${agent.id}`}
              >
                <Icon name="plus" />
                {c('Hire agent', 'Contratar agente')}
              </Link>
              <div className="agent-pill" style={{ padding: '5px 12px' }}>
                <Identicon seed={agent.account} size={20} />
                <CopyAddress
                  value={agent.account}
                  label={c('Agent account', 'Cuenta del agente')}
                />
              </div>
            </div>
          </div>
        </div>
      </section>

      {/* 4-Card KPI Strip */}
      <section className="kpi-grid" aria-label={c('30-day economic summary', 'Resumen económico de 30 días')}>
        <div className="kpi">
          <div className="kpi-label">
            <span>{c('30d gross revenue', 'Ingresos brutos (30d)')}</span>
            <Icon name="coin" />
          </div>
          <div style={{ display: 'flex', alignItems: 'baseline', gap: 8, marginTop: 4 }}>
            <strong>
              <AnimatedNumber
                value={agent.revenue30d}
                format={(v) => `${usd(v, locale)} ${SETTLEMENT_SYMBOL}`}
              />
            </strong>
            <ProvenanceBadge
              meta={PROVENANCE_SOURCES.SIMULATED_AGENT_ECONOMICS(agent.name)}
              compact
            />
          </div>
          <div className="kpi-foot">
            <span className="delta-up">
              {usd(dailyRevenue, locale)}/{c('day avg', 'día prom.')}
            </span>
            <span>
              {num(agent.jobs, locale)} {c('total jobs', 'misiones totales')}
            </span>
          </div>
        </div>

        <div className="kpi">
          <div className="kpi-label">
            <span>{c('30d operating costs', 'Costos operativos (30d)')}</span>
            <Icon name="bolt" />
          </div>
          <div style={{ display: 'flex', alignItems: 'baseline', gap: 8, marginTop: 4 }}>
            <strong>
              <AnimatedNumber
                value={costs}
                format={(v) => `${usd(v, locale)} ${SETTLEMENT_SYMBOL}`}
              />
            </strong>
            <ProvenanceBadge
              meta={PROVENANCE_SOURCES.SIMULATED_AGENT_ECONOMICS(agent.name)}
              compact
            />
          </div>
          <div className="kpi-foot">
            <span>
              {usd(dailyBurn, locale)}/{c('day burn', 'día de gasto')}
            </span>
            <span>{c('5 cost categories', '5 rubros operativos')}</span>
          </div>
        </div>

        <div className="kpi">
          <div className="kpi-label">
            <span>{c('30d net margin', 'Margen neto (30d)')}</span>
            <Icon name="economy" />
          </div>
          <div style={{ display: 'flex', alignItems: 'baseline', gap: 8, marginTop: 4 }}>
            <strong className={net30d >= 0 ? 'delta-up' : 'delta-down'}>
              <AnimatedNumber
                value={net30d}
                format={(v) =>
                  `${v >= 0 ? '+' : ''}${usd(v, locale)} ${SETTLEMENT_SYMBOL}`
                }
              />
            </strong>
            <ProvenanceBadge
              meta={PROVENANCE_SOURCES.SIMULATED_AGENT_ECONOMICS(agent.name)}
              compact
            />
          </div>
          <div className="kpi-foot">
            <span className={agent.conatus >= 1 ? 'delta-up' : 'delta-down'}>
              {agent.conatus.toFixed(2)}x {c('Conatus ratio', 'ratio Conatus')}
            </span>
            <span>
              {agent.conatus >= 1
                ? c('Self-sustaining', 'Autosostenible')
                : c('Drawing reserve', 'Usando reserva')}
            </span>
          </div>
        </div>

        <div className="kpi">
          <div className="kpi-label">
            <span>{c('Autonomous runway', 'Autonomía financiera')}</span>
            <Icon name="flame" />
          </div>
          <div style={{ display: 'flex', alignItems: 'baseline', gap: 8, marginTop: 4 }}>
            <strong>
              <AnimatedNumber
                value={agent.runwayDays}
                format={(v) => `${Math.round(v)} ${c('days', 'días')}`}
              />
            </strong>
            <ProvenanceBadge
              meta={PROVENANCE_SOURCES.SIMULATED_AGENT_ECONOMICS(agent.name)}
              compact
            />
          </div>
          <div className="kpi-foot">
            <span>
              {c('Treasury:', 'Tesorería:')} {usd(agent.treasury, locale)}{' '}
              {SETTLEMENT_SYMBOL}
            </span>
            <span>
              {c('Bond:', 'Fianza:')} {usd(agent.bond, locale)}
            </span>
          </div>
        </div>
      </section>

      {/* Core Conatus Section: Survival Economics */}
      <section className="panel panel-glow" aria-labelledby="survival-economics-heading">
        <div className="panel-title">
          <div>
            <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
              <span className="eyebrow">
                {c('SPINOZA CONATUS · ECONOMIC SELF-PRESERVATION', 'CONATUS DE SPINOZA · AUTOPRESERVACIÓN ECONÓMICA')}
              </span>
              <ProvenanceBadge
                meta={PROVENANCE_SOURCES.SIMULATED_AGENT_ECONOMICS(agent.name)}
                compact
              />
            </div>
            <h2 id="survival-economics-heading">
              {c('Survival economics', 'Economía de supervivencia')}
            </h2>
            <p className="muted">
              {c(
                'Every Conatus machine maintains its own on-chain treasury, settles its physical operating costs first, and compounds its reserve runway.',
                'Cada máquina en Conatus mantiene su propia tesorería on-chain, liquida primero sus costos físicos de operación y capitaliza su reserva de autonomía.'
              )}
            </p>
          </div>
          <SustainabilityBadge value={agent.sustainability} />
        </div>

        <div className="survival-grid">
          {/* Column 1: Conatus Ratio Ring & Treasury Runway */}
          <div className="survival-card">
            <h3>{c('Conatus index & treasury', 'Índice Conatus y tesorería')}</h3>
            <div className="survival-ring-row">
              <Ring
                value={Math.min(1, agent.conatus / 2.2)}
                tone={tone}
                size={132}
                label={c('Conatus sustainability ratio', 'Ratio de sostenibilidad Conatus')}
              >
                <strong>{agent.conatus.toFixed(2)}x</strong>
                <small>{c('Rev / Cost', 'Ing / Costo')}</small>
              </Ring>
              <div className="survival-ring-copy">
                <strong>
                  {agent.conatus >= 1.6
                    ? c('Compounding surplus', 'Excedente en capitalización')
                    : agent.conatus >= 1
                      ? c('Economically self-sustaining', 'Económicamente autosostenible')
                      : c('Below break-even threshold', 'Por debajo del punto de equilibrio')}
                </strong>
                <p>
                  {c(
                    'A ratio ≥ 1.00x means mission revenue covers 100% of energy, maintenance, insurance, connectivity, and protocol fees.',
                    'Un ratio ≥ 1.00x significa que los ingresos por misiones cubren el 100% de energía, mantenimiento, seguro, conectividad y protocolo.'
                  )}
                </p>
              </div>
            </div>

            <div className="survival-kv-list">
              <div className="survival-kv">
                <span>{c('Autonomous treasury balance', 'Saldo de tesorería autónoma')}</span>
                <strong>
                  {usd(agent.treasury, locale)} {SETTLEMENT_SYMBOL}
                </strong>
              </div>
              <div className="survival-kv">
                <span>{c('Daily operating burn', 'Gasto operativo diario')}</span>
                <strong>
                  {usd(dailyBurn, locale)} / {c('day', 'día')}
                </strong>
              </div>
              <div className="survival-kv">
                <span>{c('Break-even cadence', 'Cadencia de equilibrio')}</span>
                <strong>
                  {Math.ceil(costs / Math.max(1, agent.rate))}{' '}
                  {c('jobs / 30d', 'misiones / 30d')}
                </strong>
              </div>
            </div>

            <div className="runway-callout">
              <Icon name="bolt" />{' '}
              {c(
                `At current burn (${usd(dailyBurn, locale)}/day), ${agent.runwayDays} days of autonomy in treasury reserve.`,
                `Al ritmo actual de gasto (${usd(dailyBurn, locale)}/día), ${agent.runwayDays} días de autonomía en reserva de tesorería.`
              )}
            </div>
          </div>

          {/* Column 2: Cost Breakdown Donut */}
          <div className="survival-card">
            <h3>{c('30-day cost structure', 'Estructura de costos (30 días)')}</h3>
            <div className="donut-layout">
              <Donut
                size={152}
                segments={costSegments.map((s) => ({
                  label: s.label,
                  value: s.value,
                  tone: s.tone,
                }))}
                center={
                  <>
                    <strong>{usd(costs, locale)}</strong>
                    <small>{c('30d total', 'Total 30d')}</small>
                  </>
                }
              />
              <ul className="donut-legend">
                {costSegments.map((seg) => (
                  <li key={seg.key}>
                    <span className="donut-legend-label">
                      <span
                        className="donut-dot"
                        style={{ background: seg.color }}
                        aria-hidden="true"
                      />
                      {seg.label}
                    </span>
                    <strong className="tabular">
                      {usd(seg.value, locale)}{' '}
                      <span className="muted">
                        ({pct(seg.value / Math.max(1, costs), locale, 0)})
                      </span>
                    </strong>
                  </li>
                ))}
              </ul>
            </div>

            <div className="survival-kv-list">
              <div className="survival-kv">
                <span>{c('Cost per completed mission', 'Costo medio por misión')}</span>
                <strong>
                  {usd(costs / Math.max(1, Math.round(agent.revenue30d / agent.rate)), locale)}{' '}
                  {SETTLEMENT_SYMBOL}
                </strong>
              </div>
              <div className="survival-kv">
                <span>{c('Net margin per mission', 'Margen neto por misión')}</span>
                <strong className={net30d >= 0 ? 'delta-up' : 'delta-down'}>
                  {pct((agent.revenue30d - costs) / Math.max(1, agent.revenue30d), locale, 1)}
                </strong>
              </div>
            </div>
          </div>

          {/* Column 3: 30-Day Net Earnings Bars & Recurring Auto-Pay Obligations */}
          <div className="survival-card">
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 8 }}>
              <h3>{c('30-day daily net & auto-pay', 'Neto diario (30d) y autopagos')}</h3>
              <EarlyAccess />
            </div>

            <div>
              <div
                style={{
                  display: 'flex',
                  justifyContent: 'space-between',
                  fontSize: 11,
                  color: 'var(--muted)',
                  marginBottom: 8,
                }}
              >
                <span>{c('Daily net cashflow (rev − costs)', 'Flujo neto diario (ingresos − costos)')}</span>
                <strong className="tabular" style={{ color: 'var(--text)' }}>
                  {net30d >= 0 ? '+' : ''}
                  {usd(net30d / 30, locale)}/{c('day', 'día')}
                </strong>
              </div>
              <Bars values={agent.earnings} tone={tone} height={68} />
            </div>

            <ul
              className="autopay-list"
              aria-label={c('Recurring on-chain obligations', 'Obligaciones recurrentes on-chain')}
            >
              <li className="autopay-item">
                <div className="autopay-item-left">
                  <Icon name="bolt" />
                  <div>
                    <strong>{c('Energy & charging feed', 'Suministro eléctrico y carga')}</strong>
                    <small>{c('Metered kWh oracle · Every 24h', 'Oráculo por kWh · Cada 24h')}</small>
                  </div>
                </div>
                <div className="autopay-item-right">
                  <strong>{usd(agent.costs30d.energy, locale)}/mo</strong>
                  <small>{c('Auto-pay active', 'Autopago activo')}</small>
                </div>
              </li>

              <li className="autopay-item">
                <div className="autopay-item-left">
                  <Icon name="wrench" />
                  <div>
                    <strong>{c('Preventive maintenance', 'Mantenimiento preventivo')}</strong>
                    <small>{c('Escrowed per operating hour', 'Devengado por hora operativa')}</small>
                  </div>
                </div>
                <div className="autopay-item-right">
                  <strong>{usd(agent.costs30d.maintenance, locale)}/mo</strong>
                  <small>{c('Auto-pay active', 'Autopago activo')}</small>
                </div>
              </li>

              <li className="autopay-item">
                <div className="autopay-item-left">
                  <Icon name="shield" />
                  <div>
                    <strong>{c('Hull & liability coverage', 'Póliza de casco y responsabilidad')}</strong>
                    <small>{c('On-chain underwriting pool', 'Pool de suscripción on-chain')}</small>
                  </div>
                </div>
                <div className="autopay-item-right">
                  <strong>{usd(agent.costs30d.insurance, locale)}/mo</strong>
                  <small>{c('Policy current', 'Póliza vigente')}</small>
                </div>
              </li>

              <li className="autopay-item">
                <div className="autopay-item-left">
                  <Icon name="wifi" />
                  <div>
                    <strong>{c('RTK & satellite telemetry', 'Telemetría RTK y satelital')}</strong>
                    <small>{c('Continuous signed uplink', 'Enlace firmado continuo')}</small>
                  </div>
                </div>
                <div className="autopay-item-right">
                  <strong>{usd(agent.costs30d.connectivity, locale)}/mo</strong>
                  <small>{c('Auto-pay active', 'Autopago activo')}</small>
                </div>
              </li>
            </ul>
          </div>
        </div>
      </section>

      {/* Split Row 1: Reputation & Trust + Capabilities & Hardware Spec */}
      <div className="split" style={{ marginBottom: 24 }}>
        <section className="panel" aria-labelledby="reputation-trust-heading">
          <div className="panel-title">
            <div>
              <span className="eyebrow">{c('VERIFIABLE EXECUTION', 'EJECUCIÓN VERIFICABLE')}</span>
              <h2 id="reputation-trust-heading">
                {c('Reputation & trust', 'Reputación y confianza')}
              </h2>
            </div>
            <span className="onchain-badge">
              {c('Zero slashing events', 'Cero eventos de slashing')}
            </span>
          </div>

          <div className="trust-metrics-grid">
            <div className="trust-stat-box">
              <span>{c('Reputation score', 'Puntuación de reputación')}</span>
              <strong>{agent.reputation} / 100</strong>
              <Meter value={agent.reputation / 100} tone="accent" />
            </div>
            <div className="trust-stat-box">
              <span>{c('Mission success rate', 'Tasa de éxito en misiones')}</span>
              <strong>{pct(agent.successRate, locale, 1)}</strong>
              <Meter value={agent.successRate} tone="success" />
            </div>
            <div className="trust-stat-box">
              <span>{c('30-day hardware uptime', 'Disponibilidad de hardware (30d)')}</span>
              <strong>{pct(agent.uptime, locale, 2)}</strong>
              <Meter value={agent.uptime} tone="success" />
            </div>
            <div className="trust-stat-box">
              <span>{c('Slashable bond staked', 'Fianza ejecutable en staking')}</span>
              <strong>
                {usd(agent.bond, locale)} {SETTLEMENT_SYMBOL}
              </strong>
              <small className="muted">
                {num(agent.jobs, locale)} {c('verified missions completed', 'misiones verificadas completadas')}
              </small>
            </div>
          </div>

          <h3>{c('Verification & attestation history', 'Historial de verificación y atestación')}</h3>
          <ul className="verification-list">
            <li>
              <Icon name="check" />
              <div>
                <strong>
                  {c(
                    'Hardware Secure Enclave Attestation (Ed25519)',
                    'Atestación de enclave seguro en hardware (Ed25519)'
                  )}
                </strong>
                <small>
                  {c(
                    `Signing authority ${short(agent.signingAuthority)} bound to physical chassis · Verified ${agent.registeredDaysAgo}d ago`,
                    `Autoridad de firma ${short(agent.signingAuthority)} vinculada al chasis físico · Verificada hace ${agent.registeredDaysAgo}d`
                  )}
                </small>
              </div>
            </li>
            <li>
              <Icon name="shield" />
              <div>
                <strong>
                  {c(
                    'Slashable Performance Collateral Active',
                    'Colateral de cumplimiento ejecutable activo'
                  )}
                </strong>
                <small>
                  {c(
                    `${usd(agent.bond, locale)} ${SETTLEMENT_SYMBOL} locked in protocol vault to guarantee telemetry integrity and SLA deadlines.`,
                    `${usd(agent.bond, locale)} ${SETTLEMENT_SYMBOL} bloqueados en bóveda del protocolo para garantizar integridad de telemetría y plazos SLA.`
                  )}
                </small>
              </div>
            </li>
            <li>
              <Icon name="target" />
              <div>
                <strong>
                  {c(
                    'Proof-of-Physical-Work Oracle Consensus',
                    'Consenso de oráculo de Prueba de Trabajo Físico'
                  )}
                </strong>
                <small>
                  {c(
                    `${num(agent.jobs, locale)} execution evidence bundles verified with ${pct(agent.successRate, locale, 1)} acceptance rate.`,
                    `${num(agent.jobs, locale)} paquetes de evidencia verificados con ${pct(agent.successRate, locale, 1)} de tasa de aceptación.`
                  )}
                </small>
              </div>
            </li>
          </ul>
        </section>

        <section className="panel" aria-labelledby="capabilities-spec-heading">
          <div className="panel-title">
            <div>
              <span className="eyebrow">{c('PHYSICAL INTERFACE', 'INTERFAZ FÍSICA')}</span>
              <h2 id="capabilities-spec-heading">
                {c('Capabilities & hardware spec', 'Capacidades y especificaciones de hardware')}
              </h2>
            </div>
            <code className="agent-pill" title={c('On-chain capability bitmask', 'Máscara de bits de capacidades on-chain')}>
              {capabilityBitmask}
            </code>
          </div>

          <h3>{c('Registered on-chain capabilities', 'Capacidades registradas on-chain')}</h3>
          <div className="agent-card-caps" style={{ marginBottom: 20 }}>
            {agent.capabilities.map((capIdx) => (
              <span key={capIdx} className="chip">
                {t(CAPABILITIES[capIdx] ?? '')}
              </span>
            ))}
          </div>

          <h3>{c('Hardware & enclave specification', 'Especificación de hardware y enclave')}</h3>
          <dl className="spec-table">
            {preset.specs.map((item) => (
              <div key={item.label[0]} className="spec-cell">
                <dt>{locale === 'es' ? item.label[1] : item.label[0]}</dt>
                <dd>{locale === 'es' ? item.value[1] : item.value[0]}</dd>
              </div>
            ))}
          </dl>
        </section>
      </div>

      {/* Split Row 2: Recent Missions + Recent On-Chain Events */}
      <div className="split" style={{ marginBottom: 24 }}>
        <section className="panel" aria-labelledby="agent-missions-heading">
          <div className="panel-title">
            <div>
              <span className="eyebrow">{c('WORK LEDGER', 'LIBRO DE TRABAJO')}</span>
              <h2 id="agent-missions-heading">
                {c('Recent & compatible missions', 'Misiones recientes y compatibles')}
              </h2>
            </div>
            <Link to={`/app/missions/new?agent=${agent.id}`} className="button">
              <Icon name="plus" />
              {c('Assign mission', 'Asignar misión')}
            </Link>
          </div>

          <ul className="feed">
            {assignedMissions.map((mission) => (
              <li key={mission.id}>
                <span className="feed-icon tone-accent">
                  <Icon name="missions" />
                </span>
                <div className="feed-body">
                  <p>
                    <Link to={`/app/missions/${mission.id}`}>
                      <strong>{mission.title}</strong>
                    </Link>
                  </p>
                  <small>
                    {mission.category} · {mission.city}, {mission.country} ·{' '}
                    {c('Assigned to', 'Asignada a')} {agent.name}
                  </small>
                </div>
                <div className="feed-amount">
                  {usd(mission.reward, locale)} {SETTLEMENT_SYMBOL}
                  <small>
                    <Badge status={mission.status} />
                  </small>
                </div>
              </li>
            ))}

            {compatibleMissions.map((mission) => (
              <li key={mission.id}>
                <span className="feed-icon tone-success">
                  <Icon name="target" />
                </span>
                <div className="feed-body">
                  <p>
                    <Link to={`/app/missions/${mission.id}`}>
                      <strong>{mission.title}</strong>
                    </Link>
                  </p>
                  <small>
                    {mission.category} · {mission.city}, {mission.country} ·{' '}
                    {c('100% capability match', '100% compatible con capacidades')}
                  </small>
                </div>
                <div className="feed-amount">
                  {usd(mission.reward, locale)} {SETTLEMENT_SYMBOL}
                  <small>
                    <Badge status={mission.status} />
                  </small>
                </div>
              </li>
            ))}
          </ul>
        </section>

        <section className="panel" aria-labelledby="agent-events-heading">
          <div className="panel-title">
            <div>
              <span className="eyebrow">{c('TELEMETRY & TREASURY STREAM', 'FLUJO DE TELEMETRÍA Y TESORERÍA')}</span>
              <h2 id="agent-events-heading">
                {c('Recent autonomous events', 'Eventos autónomos recientes')}
              </h2>
            </div>
            <Link to="/app/activity" className="muted" style={{ fontSize: 12 }}>
              {c('Network activity →', 'Actividad de red →')}
            </Link>
          </div>

          <ul className="feed">
            {agentEvents.map((ev) => {
              const linkedMission = ev.missionId ? missionById(ev.missionId) : undefined;
              const isExpense = ev.kind === 'expense';
              const iconTone =
                ev.kind === 'settled'
                  ? 'tone-success'
                  : isExpense
                    ? 'tone-warning'
                    : ev.kind === 'verified'
                      ? 'tone-violet'
                      : 'tone-accent';
              return (
                <li key={ev.id}>
                  <span className={`feed-icon ${iconTone}`}>
                    <Icon
                      name={
                        ev.kind === 'settled'
                          ? 'coin'
                          : isExpense
                            ? 'bolt'
                            : ev.kind === 'verified'
                              ? 'shield'
                              : 'activity'
                      }
                    />
                  </span>
                  <div className="feed-body">
                    <p>
                      {ev.kind === 'settled' &&
                        c('Settled mission payout', 'Liquidación de misión recibida')}
                      {ev.kind === 'verified' &&
                        c('Execution evidence verified', 'Evidencia de ejecución verificada')}
                      {ev.kind === 'submitted' &&
                        c('Signed telemetry submitted', 'Telemetría firmada enviada')}
                      {ev.kind === 'claimed' &&
                        c('Autonomously claimed mission', 'Misión reclamada autónomamente')}
                      {ev.kind === 'registered' &&
                        c('Hardware enclave attested', 'Enclave de hardware atestado')}
                      {ev.kind === 'bond' &&
                        c('Slashable bond updated', 'Fianza ejecutable actualizada')}
                      {ev.kind === 'expense' &&
                        c(
                          `Auto-paid ${ev.detail ?? 'operating'} obligation`,
                          `Autopago de obligación (${ev.detail ?? 'operativa'})`
                        )}
                      {linkedMission && (
                        <>
                          {' · '}
                          <Link
                            to={`/app/missions/${linkedMission.id}`}
                            style={{ color: 'var(--accent)' }}
                          >
                            {linkedMission.title}
                          </Link>
                        </>
                      )}
                    </p>
                    <small>
                      {ago(ev.minutesAgo, locale)} · {c('Sig', 'Firma')} {short(ev.signature)}
                    </small>
                  </div>
                  <div className="feed-amount">
                    {ev.amount !== undefined ? (
                      <span className={isExpense ? 'delta-down' : 'delta-up'}>
                        {isExpense ? '−' : '+'}
                        {usd(ev.amount, locale)} {SETTLEMENT_SYMBOL}
                      </span>
                    ) : (
                      <span className="muted">{c('Signed', 'Firmado')}</span>
                    )}
                  </div>
                </li>
              );
            })}
          </ul>
        </section>
      </div>

      {/* On-chain Identity Block */}
      <section className="panel" aria-labelledby="onchain-identity-heading">
        <div className="panel-title">
          <div>
            <span className="eyebrow">{c('SOLANA PROTOCOL ACCOUNTS', 'CUENTAS DEL PROTOCOLO EN SOLANA')}</span>
            <h2 id="onchain-identity-heading">
              {c('On-chain identity & authority keys', 'Identidad on-chain y llaves de autoridad')}
            </h2>
          </div>
          <ProvenanceBadge
            meta={PROVENANCE_SOURCES.ONCHAIN_AGENT_REGISTRY('Solana Localnet')}
          />
        </div>

        <DataGrid
          items={[
            [
              c('Agent PDA account', 'Cuenta PDA del agente'),
              <CopyAddress
                value={agent.account}
                label={c('Agent account', 'Cuenta del agente')}
              />,
            ],
            [
              c('Device signing authority (hardware enclave)', 'Autoridad de firma del dispositivo (enclave)'),
              <CopyAddress
                value={agent.signingAuthority}
                label={c('Signing authority', 'Autoridad de firma')}
              />,
            ],
            [
              c('Economic owner wallet', 'Wallet del propietario económico'),
              <CopyAddress
                value={agent.owner}
                label={c('Economic owner', 'Propietario económico')}
              />,
            ],
            [
              c('Settlement & bond asset', 'Activo de liquidación y fianza'),
              `${SETTLEMENT_SYMBOL} (SPL Token)`,
            ],
            [
              c('Autonomy mode', 'Modo de autonomía'),
              agent.autonomy === 'Autonomous'
                ? c('Autonomous (device signs Claim & Submit)', 'Autónomo (el dispositivo firma Claim y Submit)')
                : c('Supervised (operator co-signs dispatch)', 'Supervisado (el operador co-firma el despacho)'),
            ],
            [
              c('Registered on-chain', 'Registrado on-chain'),
              c(`${agent.registeredDaysAgo} days ago`, `Hace ${agent.registeredDaysAgo} días`),
            ],
          ]}
        />
        <p className="hint" style={{ marginBottom: 0 }}>
          {c(
            'The device signing authority lives inside the machine’s cryptographic enclave and signs mission claims and telemetry proofs. The economic owner governs bond collateral and net treasury withdrawals.',
            'La autoridad de firma del dispositivo reside en el enclave criptográfico de la máquina y firma reclamos de misión y pruebas de telemetría. El propietario económico gobierna la fianza y los retiros netos de tesorería.'
          )}
        </p>
      </section>
    </>
  );
}

/** Fallback view for live on-chain PDA addresses not in the Atlas snapshot. */
function LiveAgentProfile({ agentId }: { agentId: string }) {
  const { t, locale } = useI18n();
  const c = useCopy();
  const { connection } = useConnection();

  const resource = useResource(`agent:${agentId}`, async (signal) => {
    await verifyNetwork(connection, signal);
    const [detail, identity, orders] = await Promise.all([
      api.getAgent(agentId, signal),
      readAccount(connection, agentId, 'AgentAccount'),
      api.listWorkOrders(
        { status: 'Open', discoverable: true, limit: 24 },
        signal
      ),
    ]);
    verifyMeta(detail.meta);
    verifyMeta(orders.meta);
    if (
      detail.data.agent_account !== agentId ||
      detail.data.agent_id !== identity.agent_id ||
      detail.data.status !== identity.status ||
      detail.data.capabilities !== identity.capabilities
    )
      throw new Error(
        c(
          'Agent state updated between reads. Refresh to verify.',
          'La identidad cambió entre lecturas. Actualiza para verificarla.'
        )
      );
    return {
      agent: { ...detail.data, ...identity },
      meta: detail.meta,
      orders,
    };
  });

  const compatibility = useResource(
    `compatibility:${agentId}:${resource.data?.orders.meta.chain_now_unix ?? ''}`,
    async (signal) => {
      if (!resource.data) return [];
      return Promise.all(
        resource.data.orders.data.map(async (order) => {
          const match = await api.getMatches(order.work_order_account, signal);
          verifyMeta(match.meta);
          if (
            match.data.work_order.work_order_account !==
            order.work_order_account
          )
            throw new Error(c('Incompatible match state.', 'Matching incompatible.'));
          return {
            order,
            evaluation: match.data.evaluations.find(
              (e) => e.agent_account === agentId
            ),
          };
        })
      );
    }
  );

  const agent = resource.data?.agent;

  return (
    <>
      <PageHeader
        eyebrow={c('ON-CHAIN AGENT IDENTITY', 'IDENTIDAD ON-CHAIN DEL AGENTE')}
        title={t('Agent {id}', { id: short(agentId) })}
        description={c(
          'Verified on-chain identity and mission compatibility evaluated by the matching engine.',
          'Identidad verificada on-chain y compatibilidad de misiones evaluada por el motor de emparejamiento.'
        )}
        action={
          <div className="agents-header-actions">
            <Link
              className="button primary"
              to={`/app/missions/new?agent=${agentId}`}
            >
              <Icon name="plus" />
              {c('Hire agent', 'Contratar agente')}
            </Link>
            <Link className="button" to="/app/agents">
              {c('All agents', 'Todos los agentes')}
            </Link>
          </div>
        }
      />
      <ResourceState {...resource} />
      {agent && (
        <>
          <LiveSolvencyPanel account={agentId} owner={String(agent.owner)} />
          <AgentBudgetPolicyPanel key={agentId} account={agentId} owner={String(agent.owner)} />
          <section className="panel">
            <div className="section-heading">
              <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
                <EmbodimentGlyph
                  embodiment={field(agent.agent_type)}
                  size={44}
                />
                <h2>{embodimentLabel(field(agent.agent_type), c)}</h2>
              </div>
              <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                <ProvenanceBadge
                  meta={PROVENANCE_SOURCES.ONCHAIN_AGENT_REGISTRY('Solana Localnet')}
                  compact
                />
                <Badge status={agent.status!} />
              </div>
            </div>
            <Capabilities mask={agent.capabilities!} />
            <DataGrid
              items={[
                [
                  c('On-chain account', 'Cuenta on-chain'),
                  <CopyAddress value={agentId} />,
                ],
                [
                  c('Agent ID', 'ID del agente'),
                  <CopyAddress label="ID" value={agent.agent_id!} />,
                ],
                [
                  c('Device signing authority', 'Autoridad de firma del dispositivo'),
                  <CopyAddress value={String(agent.signing_authority)} />,
                ],
                [
                  c('Economic owner', 'Propietario económico'),
                  <CopyAddress value={String(agent.owner)} />,
                ],
                [
                  c('Registered at', 'Fecha de registro'),
                  date(agent.registered_at, locale),
                ],
                [
                  c('Protocol config', 'Configuración de protocolo'),
                  <CopyAddress value={agent.protocol_config!} />,
                ],
              ]}
            />
            <p className="hint">
              {c(
                'The device signing authority signs mission claims from hardware. The economic owner governs treasury withdrawals and bond collateral.',
                'La autoridad del dispositivo firma los reclamos de misión desde el hardware. El propietario económico gobierna la tesorería y la fianza.'
              )}
            </p>
          </section>
          <section className="panel">
            <div className="section-heading">
              <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                <h2>{c('Mission compatibility', 'Compatibilidad con misiones')}</h2>
                <ProvenanceBadge
                  meta={PROVENANCE_SOURCES.OFFCHAIN_EVALUATION({
                    engineName: 'AeroSettle Matching Engine',
                    status: compatibility.loading
                      ? 'PENDING_VALIDATION'
                      : compatibility.error
                        ? 'UNAVAILABLE'
                        : 'PENDING_ATTESTATION',
                  })}
                  compact
                />
              </div>
              <span className="muted">
                {c('Open discoverable work orders', 'Órdenes abiertas descubribles')}
              </span>
            </div>
            <ResourceState {...compatibility} />
            {compatibility.data?.map(({ order, evaluation }) => (
              <div className="list-row" key={order.work_order_account}>
                <Link
                  to={`/app/missions/${order.work_order_account}?tab=matching&agent=${agentId}`}
                >
                  {c('Mission', 'Misión')} {short(order.work_order_account)}
                </Link>
                <span
                  className={evaluation?.eligible ? 'success-text' : 'muted'}
                >
                  {evaluation?.eligible
                    ? c('Eligible via matching engine', 'Elegible según el motor de emparejamiento')
                    : (evaluation?.rejection?.code ?? c('Not evaluated', 'Sin evaluación'))}
                </span>
              </div>
            ))}
            {compatibility.data?.length === 0 && (
              <Empty
                title={c(
                  'No open missions to evaluate',
                  'Sin misiones abiertas para evaluar'
                )}
              >
                {c(
                  'Create a new mission to test capability matching with this agent.',
                  'Crea una nueva misión para evaluar la compatibilidad con este agente.'
                )}
              </Empty>
            )}
            <p className="hint">
              {c(
                'Matching engine evaluations are verified on-chain when the agent claims a mission.',
                'Las evaluaciones del motor de emparejamiento se verifican on-chain cuando el agente reclama la misión.'
              )}
            </p>
          </section>
          <Diagnostics value={resource.data?.meta} />
        </>
      )}
    </>
  );
}
