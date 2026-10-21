import { useEffect, useMemo, useState } from 'react';
import { Link } from 'react-router';
import { PublicKey } from '@solana/web3.js';
import { useCopy, useI18n } from '../../app/i18n';
import {
  AGENTS,
  EVENTS,
  MISSIONS,
  NETWORK,
  SETTLEMENT_SYMBOL,
  VOLUME_SERIES,
  agentById,
  ago,
  missionById,
  num,
  pct,
  totalCosts,
  usd,
  type AtlasEvent,
  type CostBreakdown,
  type EventKind,
} from '../../app/atlas';
import { CopyAddress, Empty, Icon, PageHeader } from '../../components/ui';
import {
  AnimatedNumber,
  BarList,
  Pulse,
  Sparkline,
} from '../../components/ui/viz';
import Transactions from './Transactions';
import '../../styles/missions.css';

const EVENT_KINDS: EventKind[] = [
  'settled',
  'verified',
  'submitted',
  'claimed',
  'created',
  'registered',
  'expense',
  'bond',
];

function kindMeta(
  kind: EventKind,
  locale: string
): { label: string; icon: string; toneClass: string } {
  const es = locale === 'es';
  switch (kind) {
    case 'settled':
      return {
        label: es ? 'Liquidadas' : 'Settled',
        icon: 'coin',
        toneClass: 'tone-success',
      };
    case 'verified':
      return {
        label: es ? 'Verificadas' : 'Verified',
        icon: 'shield',
        toneClass: 'tone-violet',
      };
    case 'submitted':
      return {
        label: es ? 'Entregadas' : 'Submitted',
        icon: 'upload',
        toneClass: 'tone-warning',
      };
    case 'claimed':
      return {
        label: es ? 'Reclamadas' : 'Claimed',
        icon: 'bolt',
        toneClass: 'tone-accent',
      };
    case 'created':
      return {
        label: es ? 'Creadas' : 'Created',
        icon: 'plus',
        toneClass: 'tone-accent',
      };
    case 'registered':
      return {
        label: es ? 'Registros' : 'Registered',
        icon: 'agents',
        toneClass: 'tone-violet',
      };
    case 'expense':
      return {
        label: es ? 'Gastos de agentes' : 'Agent expenses',
        icon: 'flame',
        toneClass: 'tone-warning',
      };
    case 'bond':
      return {
        label: es ? 'Fianzas' : 'Bonds',
        icon: 'lock',
        toneClass: 'tone-accent',
      };
  }
}

function expenseDetailLabel(
  detail: keyof CostBreakdown | undefined,
  locale: string
): string {
  const es = locale === 'es';
  switch (detail) {
    case 'energy':
      return es ? 'energía y recarga' : 'energy & charging';
    case 'maintenance':
      return es ? 'mantenimiento mecánico' : 'mechanical maintenance';
    case 'insurance':
      return es ? 'cobertura de seguro' : 'liability insurance';
    case 'connectivity':
      return es ? 'conectividad satelital/5G' : '5G & telemetry link';
    case 'protocol':
      return es ? 'comisión de protocolo' : 'protocol fee';
    default:
      return es ? 'operación autónoma' : 'autonomous operation';
  }
}

type StreamEvent = AtlasEvent & {
  streamKey: string;
  fresh?: boolean;
};

export default function ActivityPage() {
  const { locale } = useI18n();
  const c = useCopy();

  const [kindFilter, setKindFilter] = useState<EventKind | 'all'>('all');
  const [search, setSearch] = useState('');
  const [paused, setPaused] = useState(() =>
    typeof window !== 'undefined'
      ? window.matchMedia('(prefers-reduced-motion: reduce)').matches
      : false
  );
  const [streamEvents, setStreamEvents] = useState<StreamEvent[]>(() =>
    EVENTS.map((ev) => ({ ...ev, streamKey: ev.id, fresh: false }))
  );

  // Rotate/prepend an event from EVENTS every 4.8s when live stream is active
  useEffect(() => {
    if (paused) return;
    if (
      typeof window !== 'undefined' &&
      window.matchMedia('(prefers-reduced-motion: reduce)').matches
    ) {
      return;
    }
    let cursor = 0;
    const timer = window.setInterval(() => {
      const template = EVENTS[cursor % EVENTS.length];
      cursor += 1;
      const nextEvent: StreamEvent = {
        ...template,
        minutesAgo: 0,
        streamKey: `live-${Date.now()}-${cursor}`,
        fresh: true,
      };
      setStreamEvents((prev) => [nextEvent, ...prev.slice(0, 71)]);
    }, 4800);
    return () => window.clearInterval(timer);
  }, [paused]);

  // 24h KPI calculations
  const settled24hValue = VOLUME_SERIES[VOLUME_SERIES.length - 1] ?? 112_400;
  const settlements24hCount = 1_428;
  const expenses24hValue = useMemo(() => {
    const monthlyTotal = AGENTS.reduce((sum, a) => sum + totalCosts(a), 0);
    return Math.round((monthlyTotal / 30) * 18);
  }, []);

  // Autonomous expense breakdown for side panel
  const expenseBreakdown = useMemo(() => {
    const totals: CostBreakdown = {
      energy: 0,
      maintenance: 0,
      insurance: 0,
      connectivity: 0,
      protocol: 0,
    };
    for (const a of AGENTS) {
      totals.energy += a.costs30d.energy;
      totals.maintenance += a.costs30d.maintenance;
      totals.insurance += a.costs30d.insurance;
      totals.connectivity += a.costs30d.connectivity;
      totals.protocol += a.costs30d.protocol;
    }
    return [
      {
        key: 'maintenance',
        label: c('Maintenance & servicing', 'Mantenimiento y servicio'),
        value: Math.round(totals.maintenance),
      },
      {
        key: 'energy',
        label: c('Energy & charging', 'Energía y recarga'),
        value: Math.round(totals.energy),
      },
      {
        key: 'insurance',
        label: c('Operational insurance', 'Seguro operativo'),
        value: Math.round(totals.insurance),
      },
      {
        key: 'connectivity',
        label: c('Telemetry & connectivity', 'Telemetría y conectividad'),
        value: Math.round(totals.connectivity),
      },
      {
        key: 'protocol',
        label: c('Protocol settlement fees', 'Comisiones de protocolo'),
        value: Math.round(totals.protocol),
      },
    ].sort((a, b) => b.value - a.value);
  }, [c]);

  const kindCounts = useMemo(() => {
    const map: Record<string, number> = { all: streamEvents.length };
    for (const k of EVENT_KINDS) {
      map[k] = streamEvents.filter((e) => e.kind === k).length;
    }
    return map;
  }, [streamEvents]);

  const filteredEvents = useMemo(() => {
    const q = search.trim().toLowerCase();
    return streamEvents.filter((ev) => {
      if (kindFilter !== 'all' && ev.kind !== kindFilter) return false;
      if (!q) return true;
      const agent = ev.agentId ? agentById(ev.agentId) : undefined;
      const mission = ev.missionId ? missionById(ev.missionId) : undefined;
      const haystack = `${ev.kind} ${agent?.name ?? ''} ${agent?.city ?? ''} ${mission?.title ?? ''} ${mission?.city ?? ''} ${ev.detail ?? ''} ${ev.signature}`.toLowerCase();
      return haystack.includes(q);
    });
  }, [streamEvents, kindFilter, search]);

  // On-chain signature lookup state
  const [input, setInput] = useState('');
  const [address, setAddress] = useState('');
  const [error, setError] = useState('');

  return (
    <>
      <PageHeader
        eyebrow={c('NETWORK LEDGER · SOLANA', 'REGISTRO DE RED · SOLANA')}
        title={c('Live network activity', 'Actividad de la red en vivo')}
        description={c(
          'Real-time mission settlements, cryptographic evidence verifications, and autonomous agent operating expenses across the Conatus protocol.',
          'Liquidaciones de misiones en tiempo real, verificaciones de evidencia criptográfica y gastos operativos autónomos en todo el protocolo Conatus.'
        )}
        action={
          <button
            type="button"
            className="button stream-toggle"
            aria-pressed={paused}
            onClick={() => setPaused((v) => !v)}
          >
            <Pulse tone={paused ? 'warning' : 'success'} />
            {paused
              ? c('Resume live stream', 'Reanudar stream en vivo')
              : c('Live stream · Pause', 'Stream en vivo · Pausar')}
          </button>
        }
      />

      {/* 24h KPIs */}
      <section
        className="kpi-grid"
        aria-label={c('24-hour network activity', 'Actividad de red en 24 horas')}
      >
        <article className="kpi">
          <div className="kpi-label">
            <span>{c('Settlements (24h)', 'Liquidaciones (24h)')}</span>
            <Icon name="check" />
          </div>
          <strong>
            <AnimatedNumber
              value={settlements24hCount}
              format={(v) => num(Math.round(v), locale)}
            />
          </strong>
          <div className="kpi-foot">
            <span className="delta-up">+14.2%</span>
            <span>
              {pct(NETWORK.verificationRate, locale, 1)}{' '}
              {c('verified', 'verificadas')}
            </span>
          </div>
        </article>

        <article className="kpi">
          <div className="kpi-label">
            <span>{c('Value settled (24h)', 'Valor liquidado (24h)')}</span>
            <Icon name="coin" />
          </div>
          <strong>
            <AnimatedNumber
              value={settled24hValue}
              format={(v) => usd(Math.round(v), locale)}
            />
          </strong>
          <div className="kpi-foot">
            <span>
              {SETTLEMENT_SYMBOL} · {c('Atomic escrow', 'Custodia atómica')}
            </span>
            <span className="delta-up">+21.6%</span>
          </div>
          <Sparkline values={VOLUME_SERIES.slice(-16)} tone="accent" />
        </article>

        <article className="kpi">
          <div className="kpi-label">
            <span>
              {c('Agent expenses paid (24h)', 'Gastos de agentes pagados (24h)')}
            </span>
            <Icon name="flame" />
          </div>
          <strong>
            <AnimatedNumber
              value={expenses24hValue}
              format={(v) => usd(Math.round(v), locale)}
            />
          </strong>
          <div className="kpi-foot">
            <span>
              {c('Auto-paid from treasuries', 'Autopagados desde tesorerías')}
            </span>
            <span>
              {pct(NETWORK.selfSustainingShare, locale, 0)}{' '}
              {c('self-sustaining', 'autosostenibles')}
            </span>
          </div>
        </article>

        <article className="kpi">
          <div className="kpi-label">
            <span>{c('Avg finality', 'Finalidad promedio')}</span>
            <Icon name="clock" />
          </div>
          <strong className="tabular">~{NETWORK.avgSettlementSeconds}s</strong>
          <div className="kpi-foot">
            <span className="delta-up">{c('Solana confirmed', 'Confirmado en Solana')}</span>
            <span>{c('Zero rollbacks', 'Cero reversiones')}</span>
          </div>
        </article>
      </section>

      {/* Filter Bar */}
      <div className="activity-controls">
        <div
          className="chip-filters"
          role="group"
          aria-label={c('Filter by event type', 'Filtrar por tipo de evento')}
        >
          <button
            type="button"
            aria-pressed={kindFilter === 'all'}
            onClick={() => setKindFilter('all')}
          >
            {c('All events', 'Todos')}
            <span className="chip-count">{kindCounts.all ?? 0}</span>
          </button>
          {EVENT_KINDS.map((k) => {
            const meta = kindMeta(k, locale);
            return (
              <button
                key={k}
                type="button"
                aria-pressed={kindFilter === k}
                onClick={() => setKindFilter(kindFilter === k ? 'all' : k)}
              >
                {meta.label}
                <span className="chip-count">{kindCounts[k] ?? 0}</span>
              </button>
            );
          })}
        </div>

        <div className="activity-search-row">
          <input
            type="search"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            aria-label={c('Filter activity feed', 'Filtrar feed de actividad')}
            placeholder={c(
              'Search agent, mission or signature…',
              'Buscar agente, misión o firma…'
            )}
          />
        </div>
      </div>

      {/* Main Split: Live Event Feed + Autonomous Expense Breakdown & Signature Explorer */}
      <div className="split" style={{ marginBottom: 24 }}>
        <section className="panel" style={{ marginBottom: 0 }}>
          <div className="panel-title">
            <div>
              <h2>{c('Protocol event stream', 'Flujo de eventos del protocolo')}</h2>
              <p>
                {c(
                  'Every mission transition and autonomous agent survival payment anchored on Solana.',
                  'Cada transición de misión y pago autónomo de supervivencia de agentes anclado en Solana.'
                )}
              </p>
            </div>
            <span className="onchain-badge">
              {filteredEvents.length} {c('events', 'eventos')}
            </span>
          </div>

          {filteredEvents.length === 0 ? (
            <Empty
              title={c(
                'No events match your filter',
                'Ningún evento coincide con el filtro'
              )}
            >
              {c(
                'Select another event category or clear the search query.',
                'Selecciona otra categoría de eventos o limpia la búsqueda.'
              )}
            </Empty>
          ) : (
            <ul className="feed" aria-live={paused ? 'off' : 'polite'}>
              {filteredEvents.slice(0, 32).map((ev) => {
                const meta = kindMeta(ev.kind, locale);
                const agent =
                  (ev.agentId ? agentById(ev.agentId) : undefined) ?? AGENTS[0];
                const mission =
                  (ev.missionId ? missionById(ev.missionId) : undefined) ??
                  MISSIONS[0];
                const timeText =
                  ev.minutesAgo === 0
                    ? c('just now', 'ahora mismo')
                    : ago(ev.minutesAgo, locale);

                return (
                  <li
                    key={ev.streamKey}
                    className={ev.fresh ? 'feed-enter' : undefined}
                  >
                    <span className={`feed-icon ${meta.toneClass}`}>
                      <Icon name={meta.icon} />
                    </span>

                    <div className="feed-body">
                      <p className="feed-sentence">
                        {ev.kind === 'settled' && (
                          <>
                            <Link to={`/app/agents/${agent.id}`}>
                              {agent.name}
                            </Link>{' '}
                            {c('settled', 'liquidó')}{' '}
                            <Link to={`/app/missions/${mission.id}`}>
                              {mission.title}
                            </Link>
                          </>
                        )}
                        {ev.kind === 'verified' && (
                          <>
                            {c(
                              'Verifier attested evidence for',
                              'Verificador acreditó evidencia de'
                            )}{' '}
                            <Link to={`/app/missions/${mission.id}`}>
                              {mission.title}
                            </Link>{' '}
                            ({c('by', 'por')}{' '}
                            <Link to={`/app/agents/${agent.id}`}>
                              {agent.name}
                            </Link>
                            )
                          </>
                        )}
                        {ev.kind === 'submitted' && (
                          <>
                            <Link to={`/app/agents/${agent.id}`}>
                              {agent.name}
                            </Link>{' '}
                            {c('submitted evidence for', 'entregó evidencia de')}{' '}
                            <Link to={`/app/missions/${mission.id}`}>
                              {mission.title}
                            </Link>
                          </>
                        )}
                        {ev.kind === 'claimed' && (
                          <>
                            <Link to={`/app/agents/${agent.id}`}>
                              {agent.name}
                            </Link>{' '}
                            {c('claimed', 'reclamó')}{' '}
                            <Link to={`/app/missions/${mission.id}`}>
                              {mission.title}
                            </Link>
                          </>
                        )}
                        {ev.kind === 'created' && (
                          <>
                            {c('New mission posted:', 'Nueva misión publicada:')}{' '}
                            <Link to={`/app/missions/${mission.id}`}>
                              {mission.title}
                            </Link>{' '}
                            ({mission.city}, {mission.country})
                          </>
                        )}
                        {ev.kind === 'registered' && (
                          <>
                            <Link to={`/app/agents/${agent.id}`}>
                              {agent.name}
                            </Link>{' '}
                            ({agent.model}){' '}
                            {c('registered in', 'se registró en')} {agent.city},{' '}
                            {agent.country}
                          </>
                        )}
                        {ev.kind === 'expense' && (
                          <>
                            <Link to={`/app/agents/${agent.id}`}>
                              {agent.name}
                            </Link>{' '}
                            {c('paid', 'pagó')}{' '}
                            <strong>
                              {expenseDetailLabel(ev.detail, locale)}
                            </strong>{' '}
                            {c('from its treasury', 'desde su tesorería')}
                          </>
                        )}
                        {ev.kind === 'bond' && (
                          <>
                            <Link to={`/app/agents/${agent.id}`}>
                              {agent.name}
                            </Link>{' '}
                            {c(
                              'staked performance bond on Solana',
                              'depositó fianza de cumplimiento en Solana'
                            )}
                          </>
                        )}
                      </p>

                      <div className="feed-meta-row">
                        <small>{timeText}</small>
                        <small>·</small>
                        <CopyAddress value={ev.signature} label="Signature" />
                      </div>
                    </div>

                    <div className="feed-amount">
                      {ev.amount !== undefined ? (
                        <span
                          style={{
                            color:
                              ev.kind === 'settled'
                                ? 'var(--success)'
                                : ev.kind === 'expense'
                                  ? 'var(--warning)'
                                  : 'var(--accent)',
                          }}
                        >
                          {ev.kind === 'settled'
                            ? '+'
                            : ev.kind === 'expense'
                              ? '−'
                              : ''}
                          {usd(ev.amount, locale)} {SETTLEMENT_SYMBOL}
                        </span>
                      ) : (
                        <span className="muted">{meta.label}</span>
                      )}
                      <small>{meta.label}</small>
                    </div>
                  </li>
                );
              })}
            </ul>
          )}
        </section>

        {/* Side Column: Autonomous Survival Costs + On-chain Signature Lookup */}
        <div className="stack" style={{ marginBottom: 0 }}>
          <section className="panel" style={{ marginBottom: 0 }}>
            <div className="panel-title">
              <div>
                <h2>
                  {c(
                    'Autonomous survival expenses (30d)',
                    'Gastos autónomos de supervivencia (30d)'
                  )}
                </h2>
                <p>
                  {c(
                    'How agents spend their earned USDC to stay operational without human intervention.',
                    'Cómo los agentes emplean sus ingresos en USDC para mantenerse operativos de forma autónoma.'
                  )}
                </p>
              </div>
              <Icon name="bolt" />
            </div>

            <BarList
              items={expenseBreakdown}
              format={(v) => `${usd(v, locale)} ${SETTLEMENT_SYMBOL}`}
              tone="warning"
            />
          </section>

          <section className="panel" style={{ marginBottom: 0 }}>
            <div className="panel-title">
              <div>
                <h2>
                  {c(
                    'Explore on-chain signatures',
                    'Explorar firmas on-chain'
                  )}
                </h2>
                <p>
                  {c(
                    'Query Solana RPC directly for confirmed signatures associated with any work order or agent PDA.',
                    'Consulta directamente en Solana RPC las firmas confirmadas asociadas con cualquier orden de trabajo o PDA de agente.'
                  )}
                </p>
              </div>
              <Icon name="code" />
            </div>

            <form
              className="lookup-form"
              onSubmit={(e) => {
                e.preventDefault();
                try {
                  setAddress(new PublicKey(input.trim()).toBase58());
                  setError('');
                } catch {
                  setError(
                    c(
                      'Enter a valid base58 Solana PDA.',
                      'Introduce una PDA Solana base58 válida.'
                    )
                  );
                }
              }}
            >
              <label>
                {c('Account / Work Order PDA', 'Cuenta / Work Order PDA')}
                <input
                  value={input}
                  onChange={(e) => setInput(e.target.value)}
                  spellCheck={false}
                  placeholder={c(
                    'Full Solana base58 address',
                    'Dirección Solana base58 completa'
                  )}
                />
              </label>
              <button className="primary" type="submit">
                {c('Query RPC', 'Consultar RPC')}
              </button>
            </form>

            <div
              style={{
                display: 'flex',
                flexWrap: 'wrap',
                gap: 8,
                marginBottom: 14,
              }}
            >
              {MISSIONS.slice(0, 3).map((m) => (
                <button
                  key={m.id}
                  type="button"
                  className="chip"
                  style={{ minHeight: 28, padding: '3px 10px' }}
                  onClick={() => {
                    setInput(m.account);
                    setAddress(m.account);
                    setError('');
                  }}
                >
                  {m.title.split('·')[0].trim()}
                </button>
              ))}
            </div>

            {error && <p role="alert">{error}</p>}
            <Link to="/app/missions" className="micro">
              {c(
                'Browse missions in the marketplace →',
                'Explorar misiones en el mercado →'
              )}
            </Link>
          </section>
        </div>
      </div>

      {address && <Transactions key={address} address={address} />}
    </>
  );
}
