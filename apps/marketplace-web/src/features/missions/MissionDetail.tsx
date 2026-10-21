import { useCopy, useI18n } from '../../app/i18n';
import type { WorkOrder } from '@aerosettle/marketplace-sdk';
import { lazy, Suspense, useMemo, useState } from 'react';
import { Link, useParams, useSearchParams } from 'react-router';
import { useConnection } from '@solana/wallet-adapter-react';
import { api, verifyMeta, verifyNetwork } from '../../app/api';
import { readAccount } from '../../app/readAccount';
import { useResource } from '../../app/useResource';
import {
  CAPABILITIES,
  MINT,
  STAGES,
  VERIFIER,
  amount,
  date,
  field,
  short,
} from '../../app/config';
import {
  AGENTS,
  EVENTS,
  MISSIONS,
  SETTLEMENT_SYMBOL,
  agentById,
  ago,
  inHours,
  missionById,
  pct,
  usd,
  type AtlasMission,
} from '../../app/atlas';
import {
  Badge,
  Capabilities,
  CopyAddress,
  DataGrid,
  Diagnostics,
  Icon,
  PageHeader,
  ResourceState,
} from '../../components/ui';
import {
  EarlyAccess,
  EmbodimentGlyph,
  Identicon,
  Meter,
  SustainabilityBadge,
  WorldMap,
} from '../../components/ui/viz';
import { CATEGORY_ICONS, stageTone, translateCategory } from './MissionsPage';
import '../../styles/missions.css';

const Matching = lazy(() => import('./Matching'));
const EscrowView = lazy(() => import('../funding/EscrowView'));
const Funding = lazy(() => import('../funding/FundingPanel'));
const Transactions = lazy(() => import('../activity/Transactions'));

const tabs = [
  ['overview', 'Overview'],
  ['matching', 'Matching'],
  ['evidence', 'Execution & Evidence'],
  ['escrow', 'Escrow & Settlement'],
  ['transactions', 'Transactions'],
];

function pseudoHash(seed: string): string {
  let h1 = 0xdeadbeef ^ seed.length;
  let h2 = 0x41c6ce57 ^ seed.length;
  for (let i = 0; i < seed.length; i++) {
    const ch = seed.charCodeAt(i);
    h1 = Math.imul(h1 ^ ch, 2654435761);
    h2 = Math.imul(h2 ^ ch, 1597334677);
  }
  h1 =
    Math.imul(h1 ^ (h1 >>> 16), 2246822507) ^
    Math.imul(h2 ^ (h2 >>> 13), 3266489909);
  h2 =
    Math.imul(h2 ^ (h2 >>> 16), 2246822507) ^
    Math.imul(h1 ^ (h1 >>> 13), 3266489909);
  return (
    (h1 >>> 0).toString(16).padStart(8, '0') +
    (h2 >>> 0).toString(16).padStart(8, '0') +
    ((h1 ^ h2) >>> 0).toString(16).padStart(8, '0')
  );
}

function AtlasMissionDetailView({ mission }: { mission: AtlasMission }) {
  const { t, locale } = useI18n();
  const c = useCopy();
  const [invited, setInvited] = useState<Record<string, boolean>>({});

  const stageIndex = STAGES.indexOf(mission.status);
  const evidenceReceived = stageIndex >= 3; // Submitted, Verified, Settled
  const isVerified = stageIndex >= 4; // Verified, Settled
  const isSettled = stageIndex >= 5;

  const assignedAgent = mission.agentId ? agentById(mission.agentId) : undefined;

  const compatibleAgents = useMemo(() => {
    return AGENTS.filter((agent) =>
      mission.capabilities.every((cap) => agent.capabilities.includes(cap))
    )
      .map((agent) => {
        const extraCaps = Math.max(
          0,
          agent.capabilities.length - mission.capabilities.length
        );
        const score = Math.min(
          99,
          Math.round(
            agent.reputation * 0.55 +
              agent.successRate * 40 +
              Math.min(4, extraCaps)
          )
        );
        return { agent, score };
      })
      .sort((a, b) => b.score - a.score);
  }, [mission]);

  // Stepper timestamps relative to mission creation
  const stageTimestamps = useMemo(() => {
    const created = mission.createdHoursAgo;
    const offsets = [
      created,
      Math.max(1, Math.round(created * 0.92)),
      Math.max(1, Math.round(created * 0.72)),
      Math.max(1, Math.round(created * 0.38)),
      Math.max(1, Math.round(created * 0.2)),
      Math.max(1, Math.round(created * 0.08)),
    ];
    return STAGES.map((stage, idx) => ({
      stage,
      reached: idx <= stageIndex,
      current: idx === stageIndex,
      timeLabel:
        idx <= stageIndex
          ? inHours(-offsets[idx], locale)
          : c('Pending', 'Pendiente'),
    }));
  }, [mission.createdHoursAgo, stageIndex, locale, c]);

  // Mission timeline events (merge EVENTS for this mission + synthesized stage transitions)
  const timelineEvents = useMemo(() => {
    const matching = EVENTS.filter((e) => e.missionId === mission.id);
    const synthetic = [
      {
        id: `${mission.id}-created`,
        kind: 'created' as const,
        minutesAgo: mission.createdHoursAgo * 60,
        agentId: undefined,
        missionId: mission.id,
        amount: mission.reward,
        signature: `${mission.account.slice(0, 22)}${pseudoHash(mission.id + 'created')}`,
      },
      ...(stageIndex >= 2
        ? [
            {
              id: `${mission.id}-claimed`,
              kind: 'claimed' as const,
              minutesAgo: Math.max(15, Math.round(mission.createdHoursAgo * 42)),
              agentId: assignedAgent?.id,
              missionId: mission.id,
              amount: undefined,
              signature: `${mission.account.slice(0, 22)}${pseudoHash(mission.id + 'claimed')}`,
            },
          ]
        : []),
      ...(stageIndex >= 3
        ? [
            {
              id: `${mission.id}-submitted`,
              kind: 'submitted' as const,
              minutesAgo: Math.max(10, Math.round(mission.createdHoursAgo * 22)),
              agentId: assignedAgent?.id,
              missionId: mission.id,
              amount: undefined,
              signature: `${mission.account.slice(0, 22)}${pseudoHash(mission.id + 'submitted')}`,
            },
          ]
        : []),
      ...(stageIndex >= 4
        ? [
            {
              id: `${mission.id}-verified`,
              kind: 'verified' as const,
              minutesAgo: Math.max(5, Math.round(mission.createdHoursAgo * 12)),
              agentId: assignedAgent?.id,
              missionId: mission.id,
              amount: undefined,
              signature: `${mission.account.slice(0, 22)}${pseudoHash(mission.id + 'verified')}`,
            },
          ]
        : []),
      ...(stageIndex >= 5
        ? [
            {
              id: `${mission.id}-settled`,
              kind: 'settled' as const,
              minutesAgo: Math.max(2, Math.round(mission.createdHoursAgo * 5)),
              agentId: assignedAgent?.id,
              missionId: mission.id,
              amount: mission.reward,
              signature: `${mission.account.slice(0, 22)}${pseudoHash(mission.id + 'settled')}`,
            },
          ]
        : []),
    ];
    const combined = [...matching, ...synthetic];
    const seen = new Set<string>();
    return combined
      .filter((ev) => {
        const key = `${ev.kind}-${ev.id}`;
        if (seen.has(key)) return false;
        seen.add(key);
        return true;
      })
      .sort((a, b) => a.minutesAgo - b.minutesAgo);
  }, [mission, stageIndex, assignedAgent]);

  const agentShare = Math.round(mission.reward * 0.96);
  const protocolFee = mission.reward - agentShare;

  return (
    <>
      <div className="mission-back-row">
        <Link to="/app/missions" className="mission-back-link">
          ← {c('Back to mission board', 'Volver al tablero de misiones')}
        </Link>
        <div className="missions-header-actions">
          <Link
            to={
              assignedAgent
                ? `/app/missions/new?agent=${assignedAgent.id}`
                : '/app/missions/new'
            }
            className="button primary"
          >
            <Icon name="plus" />
            {c('Post similar mission', 'Publicar misión similar')}
          </Link>
        </div>
      </div>

      {/* HERO */}
      <section className="hero-panel">
        <div className="mission-hero-top">
          <div className="mission-hero-tags">
            <span className="mission-cat-pill">
              <Icon name={CATEGORY_ICONS[mission.category]} />
              {translateCategory(mission.category, locale)}
            </span>
            <Badge status={mission.status} />
            <span className="mission-card-location">
              <Icon name="pin" />
              {mission.city}, {mission.country}
            </span>
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <span className="micro">{c('Work Order PDA', 'Work Order PDA')}</span>
            <CopyAddress value={mission.account} />
          </div>
        </div>

        <h1 className="mission-hero-title" tabIndex={-1}>
          {mission.title}
        </h1>
        <p className="mission-hero-summary">{mission.summary}</p>

        <div className="mission-hero-stats">
          <div className="mission-hero-stat">
            <span>{c('Contracted reward', 'Recompensa contratada')}</span>
            <strong style={{ color: 'var(--accent)' }}>
              {usd(mission.reward, locale)} {SETTLEMENT_SYMBOL}
            </strong>
            <small>
              {mission.status === 'Draft'
                ? c('Awaiting escrow deposit', 'Pendiente de depósito en custodia')
                : isSettled
                  ? c('Released to agent treasury', 'Liberada a la tesorería del agente')
                  : c('Locked in program escrow', 'Bloqueada en custodia del programa')}
            </small>
          </div>

          <div className="mission-hero-stat">
            <span>{c('Execution window', 'Ventana de ejecución')}</span>
            <strong>
              {mission.deadlineHours >= 0
                ? inHours(mission.deadlineHours, locale)
                : c('Completed', 'Completada')}
            </strong>
            <small>
              {c('Posted', 'Publicada')} {inHours(-mission.createdHoursAgo, locale)}
            </small>
          </div>

          <div className="mission-hero-stat">
            <span>{c('Compatible fleet', 'Flota compatible')}</span>
            <strong>
              {compatibleAgents.length} {c('agents', 'agentes')}
            </strong>
            <small>
              {c(
                '100% hardware capability match',
                '100% compatibilidad de hardware'
              )}
            </small>
          </div>

          <div className="mission-hero-stat">
            <span>{c('Requester', 'Solicitante')}</span>
            <div className="requester-inline" style={{ marginTop: 2 }}>
              <Identicon seed={mission.requester} size={22} />
              <CopyAddress value={mission.requester} />
            </div>
            <small>{c('Verified mission creator', 'Creador de misión verificado')}</small>
          </div>
        </div>
      </section>

      {/* LIFECYCLE STEPPER */}
      <section
        className="panel mission-stepper-panel"
        aria-label={c('Mission lifecycle', 'Ciclo de vida de la misión')}
      >
        <div className="panel-title" style={{ marginBottom: 14 }}>
          <div>
            <h2>{c('On-chain lifecycle', 'Ciclo de vida on-chain')}</h2>
            <p>
              {c(
                'Every stage transition is signed by the responsible authority and recorded on Solana.',
                'Cada transición de etapa es firmada por la autoridad correspondiente y registrada en Solana.'
              )}
            </p>
          </div>
          <span className="onchain-badge">
            {c('Finality ~2.4s', 'Finalidad ~2.4s')}
          </span>
        </div>

        <ol className="mission-stepper">
          {stageTimestamps.map((item, index) => (
            <li
              key={item.stage}
              className={`${item.reached ? 'reached' : ''} ${item.current ? 'current' : ''}`}
              aria-current={item.current ? 'step' : undefined}
            >
              <div className="mission-stepper-head">
                <span className="mission-step-num">
                  {item.reached ? '✓' : index + 1}
                </span>
                {item.current && (
                  <span className="micro" style={{ color: 'var(--accent)' }}>
                    {c('Current', 'Actual')}
                  </span>
                )}
              </div>
              <strong>{t(item.stage)}</strong>
              <small>{item.timeLabel}</small>
            </li>
          ))}
        </ol>
      </section>

      {/* MAIN 2-COLUMN CONTENT */}
      <div className="split" style={{ marginBottom: 24 }}>
        <div className="stack" style={{ marginBottom: 0 }}>
          {/* Brief & Capabilities */}
          <section className="panel" style={{ marginBottom: 0 }}>
            <div className="panel-title">
              <div>
                <h2>{c('Operational brief & site', 'Especificación operativa y sitio')}</h2>
                <p>
                  {mission.city}, {mission.country} ·{' '}
                  {c('Manifest digest committed on-chain', 'Resumen del manifiesto comprometido on-chain')}
                </p>
              </div>
              <span className="mission-cat-pill">
                <Icon name={CATEGORY_ICONS[mission.category]} />
                {translateCategory(mission.category, locale)}
              </span>
            </div>

            <p style={{ color: 'var(--text)', fontSize: 14, lineHeight: 1.65 }}>
              {mission.summary}
            </p>

            <h3 style={{ marginTop: 18, marginBottom: 8 }}>
              {c('Required hardware capabilities', 'Capacidades de hardware requeridas')}
            </h3>
            <div className="chips" style={{ marginBottom: 18 }}>
              {mission.capabilities.map((idx) => (
                <span key={idx} className="chip">
                  {t(CAPABILITIES[idx] ?? `Cap #${idx}`)}
                </span>
              ))}
            </div>

            <WorldMap
              label={`${mission.title} (${mission.city}, ${mission.country})`}
              points={[
                {
                  key: mission.id,
                  position: mission.position,
                  tone: stageTone(mission.status),
                  size: 1.9,
                  active: true,
                  title: `${mission.title} · ${mission.city}, ${mission.country}`,
                },
                ...compatibleAgents.slice(0, 6).map(({ agent }) => ({
                  key: agent.id,
                  position: agent.position,
                  tone: 'muted' as const,
                  size: 0.9,
                  title: `${agent.name} (${agent.city})`,
                })),
              ]}
            />

            <DataGrid
              items={[
                [
                  c('Manifest hash', 'Hash de manifiesto'),
                  <CopyAddress
                    value={`0x${pseudoHash(mission.id + 'manifest')}${pseudoHash(mission.title)}`}
                  />,
                ],
                [
                  c('Category', 'Categoría'),
                  translateCategory(mission.category, locale),
                ],
                [
                  c('Operating location', 'Ubicación operativa'),
                  `${mission.city}, ${mission.country}`,
                ],
                [
                  c('Payment model', 'Modelo de pago'),
                  c('Fixed · Atomic escrow', 'Fijo · Custodia atómica'),
                ],
              ]}
            />
          </section>

          {/* Evidence Requirements Checklist */}
          <section className="panel" style={{ marginBottom: 0 }}>
            <div className="panel-title">
              <div>
                <h2>
                  {c(
                    'Evidence & telemetry checklist',
                    'Lista de evidencia y telemetría'
                  )}
                </h2>
                <p>
                  {evidenceReceived
                    ? c(
                        'All required artifacts were signed by the executing machine and anchored to the mission receipt.',
                        'Todos los artefactos requeridos fueron firmados por la máquina ejecutora y anclados al recibo de misión.'
                      )
                    : c(
                        'Artifacts the assigned agent must sign and submit before the verification window closes.',
                        'Artefactos que el agente asignado debe firmar y entregar antes del cierre de la ventana de verificación.'
                      )}
                </p>
              </div>
              <span className="badge status-settled">
                {evidenceReceived
                  ? `${mission.evidence.length}/${mission.evidence.length} ${c('received', 'recibidos')}`
                  : `0/${mission.evidence.length} ${c('submitted', 'entregados')}`}
              </span>
            </div>

            <ul className="evidence-checklist">
              {mission.evidence.map((item) => {
                const digest = pseudoHash(`${mission.id}:${item}`);
                return (
                  <li
                    key={item}
                    className={`evidence-item ${evidenceReceived ? 'verified' : ''}`}
                  >
                    <div className="evidence-item-left">
                      <span className="evidence-check-icon">
                        <Icon name={evidenceReceived ? 'check' : 'clock'} />
                      </span>
                      <div>
                        <strong>{item}</strong>
                        <code>
                          {evidenceReceived
                            ? `sha256:${digest}`
                            : c(
                                'Awaiting signed machine artifact',
                                'Esperando artefacto firmado por la máquina'
                              )}
                        </code>
                      </div>
                    </div>
                    <Badge
                      status={
                        isVerified
                          ? 'Verified'
                          : evidenceReceived
                            ? 'Submitted'
                            : 'Open'
                      }
                    />
                  </li>
                );
              })}
            </ul>
          </section>

          {/* Activity Timeline */}
          <section className="panel" style={{ marginBottom: 0 }}>
            <div className="panel-title">
              <div>
                <h2>{c('Mission activity timeline', 'Línea de tiempo de la misión')}</h2>
                <p>
                  {c(
                    'On-chain events and state transitions associated with this work order.',
                    'Eventos on-chain y transiciones de estado asociadas con esta orden de trabajo.'
                  )}
                </p>
              </div>
              <Link to="/app/activity" className="micro">
                {c('Network explorer →', 'Explorador de red →')}
              </Link>
            </div>

            <ul className="feed">
              {timelineEvents.map((ev) => {
                const evAgent = ev.agentId ? agentById(ev.agentId) : assignedAgent;
                const iconName =
                  ev.kind === 'settled'
                    ? 'coin'
                    : ev.kind === 'verified'
                      ? 'shield'
                      : ev.kind === 'submitted'
                        ? 'upload'
                        : ev.kind === 'claimed'
                          ? 'bolt'
                          : 'plus';
                const toneClass =
                  ev.kind === 'settled'
                    ? 'tone-success'
                    : ev.kind === 'verified'
                      ? 'tone-violet'
                      : ev.kind === 'submitted'
                        ? 'tone-warning'
                        : 'tone-accent';
                return (
                  <li key={ev.id}>
                    <span className={`feed-icon ${toneClass}`}>
                      <Icon name={iconName} />
                    </span>
                    <div className="feed-body">
                      <p className="feed-sentence">
                        {ev.kind === 'created' && (
                          <>
                            {c('Work order posted in', 'Orden de trabajo publicada en')}{' '}
                            <strong>
                              {mission.city}, {mission.country}
                            </strong>
                          </>
                        )}
                        {ev.kind === 'claimed' && (
                          <>
                            {evAgent ? (
                              <Link to={`/app/agents/${evAgent.id}`}>
                                {evAgent.name}
                              </Link>
                            ) : (
                              c('Authorized agent', 'Agente autorizado')
                            )}{' '}
                            {c('claimed the mission', 'reclamó la misión')}
                          </>
                        )}
                        {ev.kind === 'submitted' && (
                          <>
                            {evAgent ? (
                              <Link to={`/app/agents/${evAgent.id}`}>
                                {evAgent.name}
                              </Link>
                            ) : (
                              c('Assigned agent', 'Agente asignado')
                            )}{' '}
                            {c(
                              'submitted signed evidence package',
                              'entregó paquete de evidencia firmada'
                            )}
                          </>
                        )}
                        {ev.kind === 'verified' && (
                          <>
                            {c(
                              'Verifier attested cryptographic evidence integrity',
                              'El verificador acreditó la integridad de la evidencia criptográfica'
                            )}
                          </>
                        )}
                        {ev.kind === 'settled' && (
                          <>
                            {c('Escrow settled to', 'Custodia liquidada a')}{' '}
                            {evAgent ? (
                              <Link to={`/app/agents/${evAgent.id}`}>
                                {evAgent.name}
                              </Link>
                            ) : (
                              c('agent treasury', 'tesorería del agente')
                            )}
                          </>
                        )}
                      </p>
                      <div className="feed-meta-row">
                        <small>{ago(ev.minutesAgo, locale)}</small>
                        <CopyAddress value={ev.signature} label="Signature" />
                      </div>
                    </div>
                    <div className="feed-amount">
                      {ev.amount
                        ? `${usd(ev.amount, locale)} ${SETTLEMENT_SYMBOL}`
                        : t(ev.kind)}
                    </div>
                  </li>
                );
              })}
            </ul>
          </section>
        </div>

        {/* RIGHT COLUMN: Assigned/Compatible Agents, Escrow, Verification */}
        <div className="stack" style={{ marginBottom: 0 }}>
          {/* Assigned Agent OR Compatible Agents Ranked List */}
          <section className="panel" style={{ marginBottom: 0 }}>
            {assignedAgent ? (
              <>
                <div className="panel-title">
                  <div>
                    <h2>{c('Assigned machine agent', 'Agente físico asignado')}</h2>
                    <p>
                      {c(
                        'Bound on-chain as the execution authority and settlement beneficiary.',
                        'Vinculado on-chain como autoridad de ejecución y beneficiario de liquidación.'
                      )}
                    </p>
                  </div>
                  <SustainabilityBadge value={assignedAgent.sustainability} />
                </div>

                <div className="assigned-agent-card">
                  <div className="assigned-agent-top">
                    <div className="agent-cell">
                      <EmbodimentGlyph
                        embodiment={assignedAgent.embodiment}
                        tone={assignedAgent.sustainability}
                        size={52}
                      />
                      <div>
                        <strong>
                          <Link to={`/app/agents/${assignedAgent.id}`}>
                            {assignedAgent.name}
                          </Link>
                        </strong>
                        <small>
                          {assignedAgent.model} · {assignedAgent.city},{' '}
                          {assignedAgent.country}
                        </small>
                      </div>
                    </div>
                    <Link
                      className="button"
                      to={`/app/agents/${assignedAgent.id}`}
                    >
                      {c('Agent profile', 'Perfil del agente')}
                      <Icon name="arrow" />
                    </Link>
                  </div>

                  <div className="assigned-agent-metrics">
                    <div>
                      <span>{c('Reputation', 'Reputación')}</span>
                      <strong>{assignedAgent.reputation}/100</strong>
                    </div>
                    <div>
                      <span>{c('Conatus ratio', 'Ratio Conatus')}</span>
                      <strong style={{ color: 'var(--accent)' }}>
                        {assignedAgent.conatus.toFixed(2)}×
                      </strong>
                    </div>
                    <div>
                      <span>{c('Success rate', 'Tasa de éxito')}</span>
                      <strong>{pct(assignedAgent.successRate, locale, 1)}</strong>
                    </div>
                  </div>
                </div>
              </>
            ) : (
              <>
                <div className="panel-title">
                  <div>
                    <h2>
                      {c(
                        'Compatible agents ranked',
                        'Agentes compatibles por afinidad'
                      )}
                    </h2>
                    <p>
                      {c(
                        'Machines satisfying 100% of required hardware capabilities, ranked by reputation and reliability.',
                        'Máquinas que cumplen el 100% de las capacidades de hardware requeridas, ordenadas por reputación y fiabilidad.'
                      )}
                    </p>
                  </div>
                  <span className="chip">
                    {compatibleAgents.length} {c('eligible', 'elegibles')}
                  </span>
                </div>

                <ul className="compatible-list">
                  {compatibleAgents.map(({ agent, score }) => {
                    const isInvited = Boolean(invited[agent.id]);
                    return (
                      <li key={agent.id} className="compatible-row">
                        <div className="agent-cell">
                          <EmbodimentGlyph
                            embodiment={agent.embodiment}
                            tone={agent.sustainability}
                            size={38}
                          />
                          <div>
                            <strong>
                              <Link to={`/app/agents/${agent.id}`}>
                                {agent.name}
                              </Link>
                            </strong>
                            <small>
                              {agent.model} · {agent.city}, {agent.country} ·{' '}
                              { c('Conatus', 'Conatus')} {agent.conatus.toFixed(2)}×
                            </small>
                          </div>
                        </div>
                        <div className="compatible-row-right">
                          <span className="match-score-pill">
                            {score}% {c('match', 'afinidad')}
                          </span>
                          <button
                            type="button"
                            className={`button ${isInvited ? '' : 'primary'}`}
                            style={{ minHeight: 32, padding: '4px 12px', fontSize: 12 }}
                            aria-pressed={isInvited}
                            onClick={() =>
                              setInvited((prev) => ({
                                ...prev,
                                [agent.id]: !prev[agent.id],
                              }))
                            }
                          >
                            {isInvited
                              ? c('Invited ✓', 'Invitado ✓')
                              : c('Invite', 'Invitar')}
                          </button>
                        </div>
                      </li>
                    );
                  })}
                </ul>
              </>
            )}
          </section>

          {/* Escrow Panel */}
          <section className="panel" style={{ marginBottom: 0 }}>
            <div className="panel-title">
              <div>
                <h2>{c('Escrow & settlement', 'Custodia y liquidación')}</h2>
                <p>
                  {c(
                    'Program-controlled vault on Solana. Funds release automatically upon verified evidence.',
                    'Bóveda controlada por programa en Solana. Los fondos se liberan automáticamente tras verificar la evidencia.'
                  )}
                </p>
              </div>
              <Icon name="lock" />
            </div>

            <div className="escrow-Split-bar">
              <div className="escrow-split-labels">
                <span>
                  {c('Agent treasury share (96%)', 'Tesorería del agente (96%)')}:{' '}
                  <strong className="tabular">{usd(agentShare, locale)}</strong>
                </span>
                <span className="muted">
                  {c('Protocol fee (4%)', 'Comisión protocolo (4%)')}:{' '}
                  <strong className="tabular">{usd(protocolFee, locale)}</strong>
                </span>
              </div>
              <Meter
                value={mission.status === 'Draft' ? 0.08 : 0.96}
                tone={isSettled ? 'success' : 'accent'}
                label={c('Escrow allocation', 'Asignación de custodia')}
              />
            </div>

            <DataGrid
              items={[
                [
                  c('Locked in escrow', 'Bloqueado en custodia'),
                  mission.status === 'Draft'
                    ? c('Awaiting funding', 'Pendiente de fondeo')
                    : `${usd(mission.reward, locale)} ${SETTLEMENT_SYMBOL}`,
                ],
                [
                  c('Release condition', 'Condición de liberación'),
                  c(
                    'Cryptographic evidence + verifier attestation',
                    'Evidencia criptográfica + atestación del verificador'
                  ),
                ],
                [
                  c('Settlement asset', 'Activo de liquidación'),
                  <CopyAddress value={MINT.toBase58()} />,
                ],
                [
                  c('Authorized verifier', 'Verificador autorizado'),
                  <CopyAddress value={VERIFIER.toBase58()} />,
                ],
              ]}
            />
          </section>

          {/* Verification Panel */}
          <section className="panel" style={{ marginBottom: 0 }}>
            <div className="panel-title">
              <div>
                <h2>
                  {c('Verification & attestation', 'Verificación y atestación')}
                </h2>
                <p>
                  {c(
                    'Hardware-signed telemetry and independent verifier quorum.',
                    'Telemetría firmada por hardware y quórum verificador independiente.'
                  )}
                </p>
              </div>
              <EarlyAccess />
            </div>

            <DataGrid
              items={[
                [
                  c('Attestation status', 'Estado de atestación'),
                  isVerified
                    ? c('Approved (10,000 bps)', 'Aprobada (10,000 bps)')
                    : evidenceReceived
                      ? c('In verifier review', 'En revisión del verificador')
                      : c('Awaiting submission', 'Esperando entrega'),
                ],
                [
                  c('Verifier signature', 'Firma del verificador'),
                  isVerified ? (
                    <CopyAddress
                      value={`${VERIFIER.toBase58().slice(0, 18)}${pseudoHash(mission.id + 'att')}`}
                    />
                  ) : (
                    c('Pending attestation', 'Pendiente de atestación')
                  ),
                ],
                [
                  c('Hardware enclave proof', 'Prueba de enclave de hardware'),
                  c('TEE + RTK signed digest', 'Resumen firmado TEE + RTK'),
                ],
                [
                  c('Dispute window', 'Ventana de disputa'),
                  c('Protected by agent bond', 'Protegida por fianza del agente'),
                ],
              ]}
            />
          </section>
        </div>
      </div>
    </>
  );
}

export default function MissionDetail() {
  const { t, locale } = useI18n();
  const c = useCopy();

  const { workOrderPda = '' } = useParams();
  const { connection } = useConnection();
  const [params, setParams] = useSearchParams();

  const atlasMission = useMemo(
    () =>
      missionById(workOrderPda) ??
      MISSIONS.find((m) => m.account === workOrderPda),
    [workOrderPda]
  );

  const tab = tabs.some(([id]) => id === params.get('tab'))
    ? params.get('tab')!
    : 'overview';

  const resource = useResource(
    `mission:${workOrderPda}`,
    async (signal) => {
      if (atlasMission) return null;
      await verifyNetwork(connection, signal);
      const [detail, account] = await Promise.all([
        api.getWorkOrder(workOrderPda, signal),
        readAccount(connection, workOrderPda, 'WorkOrderAccount'),
      ]);
      verifyMeta(detail.meta);
      if (
        detail.data.work_order_account !== workOrderPda ||
        detail.data.status !== account.status ||
        detail.data.creator !== account.creator ||
        detail.data.work_order_id !== account.work_order_id ||
        detail.data.required_capabilities !== account.required_capabilities
      )
        throw new Error(
          'La orden cambió entre lecturas. Actualiza para obtener un estado consistente.'
        );
      const order: WorkOrder = { ...account, ...detail.data };
      return { order, meta: detail.meta };
    }
  );

  if (atlasMission) {
    return <AtlasMissionDetailView mission={atlasMission} />;
  }

  const order = resource.data?.order;
  function selectTab(id: string) {
    const next = new URLSearchParams(params);
    next.set('tab', id);
    setParams(next, { replace: true });
  }
  const address = (value: unknown) =>
    field(value) === 'No registrado' ? (
      c('Not recorded', 'No registrado')
    ) : (
      <CopyAddress value={String(value)} />
    );

  return (
    <>
      <PageHeader
        eyebrow={c('ON-CHAIN WORK ORDER · SOLANA', 'ORDEN DE TRABAJO ON-CHAIN · SOLANA')}
        title={t('Mission {id}', { id: short(workOrderPda) })}
        description={c(
          'State and identity cross-verified between the Conatus indexer and Solana RPC.',
          'Estado e identidad contrastados entre el indexador de Conatus y Solana RPC.'
        )}
        action={
          <button disabled={resource.loading} onClick={resource.reload}>
            {t('Actualizar estado')}
          </button>
        }
      />
      <ResourceState {...resource} />
      {order && (
        <>
          <section className="mission-hero">
            <div>
              <Badge status={order.status} />
              <CopyAddress value={workOrderPda} />
            </div>
            <div>
              <span className="micro">{t('Monto contratado')}</span>
              <strong>
                {amount(order, locale).replace(' DEMO', ` ${SETTLEMENT_SYMBOL}`)}
              </strong>
            </div>
            <div>
              <span className="micro">{t('Creator')}</span>
              {address(order.creator)}
            </div>
          </section>
          <ol className="lifecycle" aria-label={t('Ciclo de vida on-chain')}>
            {STAGES.map((stage, index) => {
              const timestamp =
                order[
                  [
                    'created_at',
                    'funded_at',
                    'claimed_at',
                    'submitted_at',
                    'verified_at',
                    'settled_at',
                  ][index]
                ];
              const reached = Number(timestamp) > 0;
              const current = order.status === stage;
              return (
                <li
                  key={stage}
                  className={`${reached ? 'reached' : ''} ${current ? 'current' : ''}`}
                  aria-current={current ? 'step' : undefined}
                >
                  <span className="stage-dot">{reached ? '✓' : index + 1}</span>
                  <strong>{t(stage)}</strong>
                  <small>
                    {reached
                      ? date(timestamp, locale)
                      : current
                        ? t('Estado actual')
                        : t('Sin registro')}
                  </small>
                </li>
              );
            })}
          </ol>
          <div
            className="tabs"
            role="tablist"
            aria-label={t('Detalle de misión')}
          >
            {tabs.map(([id, title], i) => (
              <button
                key={id}
                id={`tab-${id}`}
                role="tab"
                aria-selected={tab === id}
                aria-controls={`panel-${id}`}
                tabIndex={tab === id ? 0 : -1}
                onClick={() => selectTab(id)}
                onKeyDown={(e) => {
                  let next = i;
                  if (e.key === 'ArrowRight') next = (i + 1) % tabs.length;
                  else if (e.key === 'ArrowLeft')
                    next = (i + tabs.length - 1) % tabs.length;
                  else if (e.key === 'Home') next = 0;
                  else if (e.key === 'End') next = tabs.length - 1;
                  else return;
                  e.preventDefault();
                  selectTab(tabs[next][0]);
                  document.getElementById(`tab-${tabs[next][0]}`)?.focus();
                }}
              >
                {t(title)}
              </button>
            ))}
          </div>
          <section
            className="tab-panel"
            id={`panel-${tab}`}
            role="tabpanel"
            aria-labelledby={`tab-${tab}`}
            tabIndex={0}
          >
            <Suspense
              fallback={
                <div role="status" className="loading-state">
                  {t('Cargando detalle…')}
                </div>
              }
            >
              {tab === 'overview' && (
                <section className="panel">
                  <div className="section-heading">
                    <h2>{t(field(order.work_type))}</h2>
                    <span className="muted">
                      {t('Cuenta de protocolo v')}
                      {field(order.protocol_version)}
                    </span>
                  </div>
                  <h3>{t('Capacidades requeridas')}</h3>
                  <Capabilities mask={order.required_capabilities!} />
                  <DataGrid
                    items={[
                      ['Manifest hash', address(order.manifest_hash)],
                      [
                        t('Ejecución antes de'),
                        date(order.execution_deadline, locale),
                      ],
                      [
                        t('Verificación antes de'),
                        date(order.verification_deadline, locale),
                      ],
                      [
                        t('Agente contratado'),
                        typeof order.claimed_agent === 'string' &&
                        field(order.claimed_agent) !== 'No registrado' ? (
                          <Link to={`/app/agents/${order.claimed_agent}`}>
                            {short(order.claimed_agent)}
                          </Link>
                        ) : (
                          t('Sin asignar')
                        ),
                      ],
                      [t('Verificador'), address(order.verifier)],
                      [t('Modelo de pago'), field(order.payment_model)],
                    ]}
                  />
                  <p className="hint">
                    {c(
                      'The manifest hash is an on-chain cryptographic commitment to the mission parameters and acceptance criteria.',
                      'El hash del manifiesto es un compromiso criptográfico on-chain con los parámetros de la misión y sus criterios de aceptación.'
                    )}
                  </p>
                </section>
              )}
              {tab === 'matching' && (
                <Matching
                  mission={order}
                  initialAgent={params.get('agent') ?? ''}
                  onClaimed={resource.reload}
                />
              )}
              {tab === 'evidence' && (
                <section className="panel">
                  <h2>{t('Execution & Evidence')}</h2>
                  <div className="notice">
                    <strong>
                      {c(
                        'Cryptographic evidence attestation',
                        'Atestación criptográfica de evidencia'
                      )}
                    </strong>
                    <p>
                      {c(
                        'Each submission records SHA-256 digests of the execution receipt and evidence manifest signed by the authorized machine authority, then verified prior to escrow settlement.',
                        'Cada entrega registra resúmenes SHA-256 del recibo de ejecución y del manifiesto de evidencia firmados por la autoridad de la máquina, verificados antes de liberar la custodia.'
                      )}
                    </p>
                  </div>
                  <DataGrid
                    items={[
                      ['Receipt hash', address(order.execution_receipt_hash)],
                      [
                        'Evidence manifest hash',
                        address(order.evidence_manifest_hash),
                      ],
                      [
                        t('Autoridad que ejecutó'),
                        address(order.execution_signer),
                      ],
                      [
                        t('Evidence mask requerida'),
                        field(order.evidence_requirements),
                      ],
                      [
                        t('Evidence mask aportada'),
                        field(order.provided_evidence),
                      ],
                      [
                        t('Inicio registrado'),
                        date(order.execution_started_at, locale),
                      ],
                      [
                        t('Fin registrado'),
                        date(order.execution_ended_at, locale),
                      ],
                      [
                        t('Decisión del verificador'),
                        field(order.verification_status),
                      ],
                      [
                        'Attestation hash',
                        address(order.verification_attestation_hash),
                      ],
                      [
                        'Completion (basis points)',
                        field(order.completion_bps),
                      ],
                    ]}
                  />
                </section>
              )}
              {tab === 'escrow' && (
                <>
                  <section className="panel">
                    <h2>{t('Condiciones económicas')}</h2>
                    <DataGrid
                      items={[
                        [
                          t('Monto contratado'),
                          amount(order, locale).replace(
                            ' DEMO',
                            ` ${SETTLEMENT_SYMBOL}`
                          ),
                        ],
                        ['Mint', address(order.token_mint)],
                        [t('Modelo de pago'), field(order.payment_model)],
                        [
                          t('Beneficiario congelado al Claim'),
                          address(order.settlement_beneficiary),
                        ],
                        [t('Verificación'), field(order.verification_status)],
                        [
                          t('Settlement registrado'),
                          date(order.settled_at, locale),
                        ],
                      ]}
                    />
                    <p className="hint">
                      {c(
                        'Escrowed settlement is released atomically to the beneficiary once verification passes. Review the on-chain transaction log to audit every transfer.',
                        'La liquidación en custodia se libera atómicamente al beneficiario tras aprobarse la verificación. Consulta el registro de transacciones on-chain para auditar cada transferencia.'
                      )}
                    </p>
                  </section>
                  <EscrowView workOrderPda={workOrderPda} />
                  {order.status === 'Draft' && (
                    <Funding
                      key={workOrderPda}
                      workOrderPda={workOrderPda}
                      onFunded={resource.reload}
                    />
                  )}
                </>
              )}
              {tab === 'transactions' && (
                <Transactions address={workOrderPda} />
              )}
            </Suspense>
          </section>
          <Diagnostics value={resource.data?.meta} />
          <p className="scope-note">
            {t(
              'Lecturas no atómicas. Cada operación vuelve a validar sus precondiciones antes del envío.'
            )}
          </p>
        </>
      )}
    </>
  );
}
