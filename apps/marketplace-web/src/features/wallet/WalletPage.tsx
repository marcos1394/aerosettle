import { useMemo, useState } from 'react';
import { Link } from 'react-router';
import { useConnection, useWallet } from '@solana/wallet-adapter-react';
import {
  AGENTS,
  EVENTS,
  MISSIONS,
  SETTLEMENT_SYMBOL,
  agentById,
  ago,
  missionById,
  pct,
  usd,
  useSnapshot,
  type CostBreakdown,
} from '../../app/atlas';
import { verifyNetwork } from '../../app/api';
import {
  LOCALNET_GENESIS,
  MINT,
  PROGRAM_ID,
  TOKEN_PROGRAM,
  short,
  time,
} from '../../app/config';
import { useCopy, useI18n } from '../../app/i18n';
import { useResource } from '../../app/useResource';
import {
  CopyAddress,
  DataGrid,
  Icon,
  PageHeader,
  ProvenanceBadge,
  ResourceState,
} from '../../components/ui';
import { PROVENANCE_SOURCES, assertNoSilentAggregation } from '../../app/provenance';
import { WalletControl } from '../../components/ui/WalletControl';
import {
  AnimatedNumber,
  AreaChart,
  Meter,
  Pulse,
} from '../../components/ui/viz';
import { OPERATOR_FLEET_IDS } from '../fleet/FleetPage';
import '../../styles/treasury.css';

const EXPENSE_LABELS: Record<keyof CostBreakdown, [string, string]> = {
  energy: ['Energy & charging', 'Energía y carga'],
  maintenance: ['Scheduled maintenance', 'Mantenimiento preventivo'],
  insurance: ['Mission hull insurance', 'Seguro de misión'],
  connectivity: ['Telemetry & connectivity', 'Telemetría y conectividad'],
  protocol: ['Protocol settlement fee', 'Comisión del protocolo'],
};

export default function WalletPage() {
  const { t, locale } = useI18n();
  const c = useCopy();
  const [snapshot] = useSnapshot();
  const [feedFilter, setFeedFilter] = useState<'all' | 'settled' | 'expense'>('all');

  const { connection } = useConnection();
  const { publicKey } = useWallet();

  // Preserve live Solana balance & settlement mint token account query
  const resource = useResource(
    `wallet:${publicKey?.toBase58() ?? ''}`,
    async (signal) => {
      const network = await verifyNetwork(connection, signal);
      if (!publicKey)
        return {
          network,
          balance: null,
          tokens: [] as { address: string; amount: string }[],
        };
      const [balanceRes, tokenAccountsRes] = await Promise.all([
        connection.getBalanceAndContext(publicKey, 'confirmed'),
        connection.getParsedTokenAccountsByOwner(
          publicKey,
          { mint: MINT },
          'confirmed'
        ),
      ]);
      const balance = balanceRes.value;
      const balanceSlot = balanceRes.context.slot;
      const tokenSlot = tokenAccountsRes.context.slot;

      const tokens = tokenAccountsRes.value.map((item) => {
        if (!item.account.owner.equals(TOKEN_PROGRAM))
          throw new Error('Propietario de cuenta SPL incompatible.');
        const info = item.account.data.parsed?.info;
        if (
          info?.mint !== MINT.toBase58() ||
          info?.owner !== publicKey.toBase58() ||
          typeof info?.tokenAmount?.uiAmountString !== 'string'
        )
          throw new Error('Respuesta de saldo SPL incompatible.');
        return {
          address: item.pubkey.toBase58(),
          amount: info.tokenAmount.uiAmountString as string,
        };
      });
      return {
        network,
        balance,
        balanceSlot,
        tokens,
        tokenSlot,
        commitment: 'confirmed' as const,
      };
    }
  );

  // Sum live SPL settlement balance if present
  const liveTokenBalance = useMemo(() => {
    if (!resource.data?.tokens.length) return 0;
    return resource.data.tokens.reduce(
      (sum, item) => sum + (Number.parseFloat(item.amount) || 0),
      0
    );
  }, [resource.data]);

  // Portfolio breakdown across Available, Locked in escrow, Agent treasuries, and Bonded stake
  const portfolio = useMemo(() => {
    const fleetAgents = snapshot
      ? OPERATOR_FLEET_IDS.map((id) => AGENTS.find((a) => a.id === id)).filter(
          (a): a is NonNullable<typeof a> => Boolean(a)
        )
      : [];

    // Strictly segregated: simulated available is from Atlas scenario, liveTokenBalance is tracked separately
    const simulatedAvailable = snapshot ? 18_420 : 0;
    const lockedEscrow = snapshot
      ? MISSIONS.filter((m) =>
          ['Open', 'Claimed', 'Submitted', 'Verified'].includes(m.status)
        )
          .slice(0, 6)
          .reduce((sum, m) => sum + m.reward, 0)
      : 0;
    const agentTreasuries = fleetAgents.reduce((sum, a) => sum + a.treasury, 0);
    const bondedStake = fleetAgents.reduce((sum, a) => sum + a.bond, 0);
    const total = simulatedAvailable + lockedEscrow + agentTreasuries + bondedStake;

    // Strict guardrails: guarantee no silent aggregation between verified on-chain and simulated figures
    assertNoSilentAggregation(total, { verified: liveTokenBalance, simulated: simulatedAvailable }, 'WalletPage Portfolio Total');

    // 30-day portfolio valuation series ending at `total`
    const base = total > 0 ? total : 0;
    const values = Array.from({ length: 30 }, (_, i) => {
      if (base === 0) return 0;
      const progress = (i + 1) / 30;
      const wave = Math.sin(i * 0.45) * (base * 0.018);
      return Math.round(base * (0.76 + 0.24 * progress) + wave);
    });
    if (values.length) values[values.length - 1] = Math.round(total);

    const now = Date.now();
    const fmt = new Intl.DateTimeFormat(locale === 'es' ? 'es-MX' : 'en-US', {
      month: 'short',
      day: 'numeric',
    });
    const labels = Array.from({ length: 30 }, (_, i) =>
      fmt.format(new Date(now - (29 - i) * 86_400_000))
    );

    return {
      available: simulatedAvailable,
      lockedEscrow,
      agentTreasuries,
      bondedStake,
      total,
      values,
      labels,
    };
  }, [snapshot, locale]);

  // Recent payouts & autonomous expenses from EVENTS
  const treasuryEvents = useMemo(() => {
    if (!snapshot) return [];
    return EVENTS.filter((ev) => {
      if (feedFilter === 'settled') return ev.kind === 'settled';
      if (feedFilter === 'expense') return ev.kind === 'expense';
      return ev.kind === 'settled' || ev.kind === 'expense';
    }).slice(0, 10);
  }, [snapshot, feedFilter]);

  const roles = [
    {
      icon: 'wallet',
      title: t('Wallet humana'),
      badge: c('Requester & operator', 'Solicitante y operador'),
      desc: t('Crea y financia órdenes cuando su clave es el creator.'),
    },
    {
      icon: 'coin',
      title: t('Owner económico'),
      badge: c('Beneficiary', 'Beneficiario'),
      desc: t('Propietario del agente; el beneficiario queda registrado al Claim.'),
    },
    {
      icon: 'cpu',
      title: t('Autoridad de dispositivo'),
      badge: c('Machine key', 'Clave de máquina'),
      desc: t('Clave registrada que autoriza Claim y firma la ejecución.'),
    },
    {
      icon: 'shield',
      title: t('Verificador'),
      badge: c('Settlement oracle', 'Oráculo de liquidación'),
      desc: t('Autoridad designada en la orden para verificar la evidencia.'),
    },
  ];

  return (
    <>
      <PageHeader
        eyebrow={c('OPERATE / TREASURY', 'OPERAR / TESORERÍA')}
        title={c('Treasury & settlements', 'Tesorería y liquidaciones')}
        description={c(
          `Consolidated ${SETTLEMENT_SYMBOL} liquidity across your operator wallet, active protocol escrows, and autonomous machine treasuries.`,
          `Liquidez consolidada en ${SETTLEMENT_SYMBOL} a través de tu wallet de operador, escrows activos del protocolo y tesorerías autónomas de máquinas.`
        )}
        action={<WalletControl />}
      />

      {/* Only show page-level error if snapshot is disabled */}
      {!snapshot && <ResourceState {...resource} />}

      {/* Verified On-Chain Liquid Assets Panel (when wallet connected) */}
      {publicKey && (
        <section className="panel" style={{ marginBottom: 20 }}>
          <div className="section-heading">
            <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
              <h2>{c('Verified on-chain liquid holdings', 'Saldos líquidos verificados on-chain')}</h2>
              <ProvenanceBadge
                meta={PROVENANCE_SOURCES.ONCHAIN_SPL_BALANCE({
                  mint: MINT.toBase58(),
                  network: 'Solana Localnet',
                  slot: resource.data?.tokenSlot ?? resource.data?.balanceSlot,
                  commitment: 'confirmed',
                  status: resource.loading
                    ? 'PENDING_VALIDATION'
                    : resource.error
                      ? 'UNAVAILABLE'
                      : 'VERIFIED',
                  error: resource.error,
                })}
                compact
              />
            </div>
            <span className="muted" style={{ fontSize: 12 }}>
              {resource.loading
                ? c('Querying Solana Localnet ledger state...', 'Consultando estado en libro de Solana Localnet...')
                : resource.error
                  ? c('Solana RPC endpoint unreachable: {err}', 'Punto de enlace Solana RPC no disponible: {err}').replace('{err}', resource.error)
                  : resource.data?.balanceSlot === resource.data?.tokenSlot
                    ? c('Network: Solana Localnet · Confirmed Slot {slot}', 'Red: Solana Localnet · Slot confirmado {slot}').replace('{slot}', String(resource.data?.tokenSlot ?? '—'))
                    : c('Network: Solana Localnet · Confirmed Slots (Tokens: {ts} / SOL: {ss})', 'Red: Solana Localnet · Slots confirmados (Tokens: {ts} / SOL: {ss})').replace('{ts}', String(resource.data?.tokenSlot ?? '—')).replace('{ss}', String(resource.data?.balanceSlot ?? '—'))}
            </span>
          </div>

          {resource.loading && (
            <div style={{ padding: '16px 0', color: 'var(--muted)', fontSize: 13, display: 'flex', alignItems: 'center', gap: 8 }}>
              <Pulse tone="accent" />
              <span>{c('Fetching native SOL and SPL token balances...', 'Obteniendo saldos de SOL nativo y tokens SPL...')}</span>
            </div>
          )}

          {resource.error && (
            <div style={{ padding: '14px 16px', background: '#ff6b6b15', border: '1px solid #ff6b6b35', borderRadius: 8, marginTop: 10, color: '#ff9b9b', fontSize: 13 }}>
              <strong>{c('On-chain read error', 'Error de lectura on-chain')}</strong>: {resource.error}
            </div>
          )}

          {resource.data && (
            <div className="kpi-grid" style={{ gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))', marginTop: 12 }}>
              <div className="kpi">
                <div className="kpi-label">
                  <span>{c('Localnet Settlement Tokens', 'Tokens de liquidación Localnet')}</span>
                  <Icon name="coin" />
                </div>
                <strong className="tabular">
                  {liveTokenBalance.toLocaleString(locale === 'es' ? 'es-MX' : 'en-US')} {SETTLEMENT_SYMBOL}
                </strong>
                <div className="kpi-foot">
                  <span>SPL Mint {short(MINT.toBase58())}</span>
                  <ProvenanceBadge
                    meta={PROVENANCE_SOURCES.ONCHAIN_SPL_BALANCE({
                      mint: MINT.toBase58(),
                      network: 'Solana Localnet',
                      slot: resource.data.tokenSlot,
                      commitment: 'confirmed',
                      status: 'VERIFIED',
                    })}
                    compact
                  />
                </div>
              </div>
              <div className="kpi">
                <div className="kpi-label">
                  <span>{c('Native SOL (Transaction Fees)', 'SOL nativo (Comisiones de red)')}</span>
                  <Icon name="bolt" />
                </div>
                <strong className="tabular">
                  {resource.data.balance != null
                    ? `${(resource.data.balance / 1e9).toFixed(4)} SOL`
                    : '—'}
                </strong>
                <div className="kpi-foot">
                  <span>{c('Solana Localnet Gas', 'Gas en Solana Localnet')}</span>
                  <ProvenanceBadge
                    meta={PROVENANCE_SOURCES.ONCHAIN_SOL_BALANCE({
                      network: 'Solana Localnet',
                      slot: resource.data.balanceSlot,
                      commitment: 'confirmed',
                      status: 'VERIFIED',
                    })}
                    compact
                  />
                </div>
              </div>
            </div>
          )}
        </section>
      )}

      {/* Portfolio Hero */}
      <section className="hero-panel" aria-label={c('Treasury portfolio valuation', 'Valoración del portafolio de tesorería')}>
        <div className="treasury-hero-grid">
          <div className="treasury-hero-total">
            <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 4 }}>
              <span className="eyebrow" style={{ margin: 0 }}>
                {c('SIMULATED FLEET PORTFOLIO SCENARIO', 'ESCENARIO SIMULADO DEL PORTAFOLIO')}
              </span>
              <ProvenanceBadge
                meta={PROVENANCE_SOURCES.SIMULATED_ATLAS_SNAPSHOT(c('Fleet Portfolio Projection', 'Proyección de cartera de flota'))}
                compact
              />
            </div>
            <div className="treasury-hero-value">
              <AnimatedNumber
                value={portfolio.total}
                format={(v) => usd(v, locale)}
              />
            </div>
            <div className="treasury-hero-meta">
              <span className="delta-up">+18.4% (30d)</span>
              <span>·</span>
              <span>
                {c(
                  `Projected in ${SETTLEMENT_SYMBOL} (Simulated Scenario)`,
                  `Proyección en ${SETTLEMENT_SYMBOL} (Escenario Simulado)`
                )}
              </span>
            </div>

            <div className="treasury-wallet-pill">
              <Pulse tone={publicKey ? 'success' : 'accent'} />
              {publicKey ? (
                <>
                  <span>{c('Connected wallet:', 'Wallet conectada:')}</span>
                  <CopyAddress value={publicKey.toBase58()} />
                </>
              ) : (
                <span>
                  {c(
                    'Connect a wallet to inspect on-chain SPL accounts & sign transfers',
                    'Conecta una wallet para inspeccionar cuentas SPL on-chain y firmar transferencias'
                  )}
                </span>
              )}
            </div>
          </div>

          <AreaChart
            values={portfolio.values}
            labels={portfolio.labels}
            format={(v) => `${usd(v, locale)} ${SETTLEMENT_SYMBOL}`}
            tone="accent"
            height={196}
            label={c('30-day treasury value in USDC', 'Valor de tesorería de 30 días en USDC')}
          />
        </div>
      </section>

      {/* 4 Breakdown Cards */}
      <section
        className="treasury-breakdown-grid"
        aria-label={c('Capital allocation breakdown', 'Desglose de asignación de capital')}
      >
        {[
          {
            key: 'available',
            label: c('Available (Scenario)', 'Disponible (Escenario)'),
            value: portfolio.available,
            icon: 'wallet',
            tone: 'accent' as const,
            sub: c(
              'Representative reserve ready for simulated missions',
              'Reserva representativa lista para misiones simuladas'
            ),
          },
          {
            key: 'escrow',
            label: c('Locked in escrow', 'Bloqueado en escrow'),
            value: portfolio.lockedEscrow,
            icon: 'lock',
            tone: 'violet' as const,
            sub: c(
              'Held by protocol vaults until verification',
              'En custodia del protocolo hasta verificación'
            ),
          },
          {
            key: 'agents',
            label: c('Agent treasuries', 'Tesorerías de agentes'),
            value: portfolio.agentTreasuries,
            icon: 'fleet',
            tone: 'success' as const,
            sub: c(
              'Autonomous machine reserves for operating costs',
              'Reservas autónomas de máquinas para costos operativos'
            ),
          },
          {
            key: 'bonded',
            label: c('Bonded stake', 'Fianza en garantía'),
            value: portfolio.bondedStake,
            icon: 'shield',
            tone: 'warning' as const,
            sub: c(
              'Collateralized SLA bonds across active fleet',
              'Garantías de cumplimiento en la flota activa'
            ),
          },
        ].map((card) => {
          const share = portfolio.total > 0 ? card.value / portfolio.total : 0;
          return (
            <div key={card.key} className="treasury-card">
              <div className="treasury-card-top">
                <span>{card.label}</span>
                <span className="treasury-card-icon" aria-hidden="true">
                  <Icon name={card.icon} />
                </span>
              </div>
              <div style={{ display: 'flex', alignItems: 'baseline', gap: 8, marginTop: 4, marginBottom: 8 }}>
                <strong>
                  <AnimatedNumber
                    value={card.value}
                    format={(v) => usd(v, locale)}
                  />
                </strong>
                <ProvenanceBadge
                  meta={PROVENANCE_SOURCES.SIMULATED_ATLAS_SNAPSHOT(card.label)}
                  compact
                />
              </div>
              <Meter
                value={share}
                tone={card.tone}
                label={`${card.label} ${pct(share, locale, 0)}`}
              />
              <small>
                {pct(share, locale, 1)} {c('of portfolio', 'del portafolio')} · {card.sub}
              </small>
            </div>
          );
        })}
      </section>

      {/* Split Row: Recent Payouts / Settlements & On-Chain Accounts */}
      <div className="split" style={{ marginBottom: 24 }}>
        <section className="panel">
          <div className="panel-title">
            <div>
              <h2>
                {c(
                  'Recent payouts & autonomous expenses',
                  'Liquidaciones recientes y gastos autónomos'
                )}
              </h2>
              <p>
                {c(
                  'Mission escrow releases to agent treasuries and autonomous operating cost settlements.',
                  'Liberaciones de escrow hacia tesorerías de agentes y pagos autónomos de costos operativos.'
                )}
              </p>
            </div>
            <div
              className="segmented"
              role="group"
              aria-label={c('Filter treasury events', 'Filtrar movimientos de tesorería')}
            >
              {(
                [
                  ['all', c('All', 'Todos')],
                  ['settled', c('Payouts', 'Ingresos')],
                  ['expense', c('Expenses', 'Gastos')],
                ] as const
              ).map(([key, label]) => (
                <button
                  key={key}
                  type="button"
                  aria-pressed={feedFilter === key}
                  onClick={() => setFeedFilter(key)}
                >
                  {label}
                </button>
              ))}
            </div>
          </div>

          {treasuryEvents.length > 0 ? (
            <ul className="feed">
              {treasuryEvents.map((ev) => {
                const agent = ev.agentId ? agentById(ev.agentId) : undefined;
                const mission = ev.missionId ? missionById(ev.missionId) : undefined;
                const isPayout = ev.kind === 'settled';
                const expenseLabel = ev.detail
                  ? EXPENSE_LABELS[ev.detail][locale === 'es' ? 1 : 0]
                  : c('Operating expense', 'Gasto operativo');
                return (
                  <li key={ev.id}>
                    <span
                      className={`feed-icon ${isPayout ? 'tone-success' : 'tone-warning'}`}
                      aria-hidden="true"
                    >
                      <Icon name={isPayout ? 'check' : 'bolt'} />
                    </span>
                    <div className="feed-body">
                      <p>
                        {isPayout ? (
                          <>
                            {c('Mission settled:', 'Misión liquidada:')}{' '}
                            {mission ? (
                              <Link to={`/app/missions/${mission.id}`}>
                                <strong>{mission.title}</strong>
                              </Link>
                            ) : (
                              <strong>{c('Escrow release', 'Liberación de escrow')}</strong>
                            )}
                          </>
                        ) : (
                          <>
                            {expenseLabel} ·{' '}
                            {agent ? (
                              <Link to={`/app/agents/${agent.id}`}>
                                <strong>{agent.name}</strong>
                              </Link>
                            ) : (
                              <strong>{c('Fleet unit', 'Unidad de flota')}</strong>
                            )}
                          </>
                        )}
                      </p>
                      <small>
                        {agent && isPayout ? (
                          <>
                            <Link to={`/app/agents/${agent.id}`}>{agent.name}</Link>
                            {' · '}
                          </>
                        ) : null}
                        {ago(ev.minutesAgo, locale)} ·{' '}
                        <CopyAddress value={ev.signature} label={c('signature', 'firma')} />
                      </small>
                    </div>
                    <div className="feed-amount">
                      <span className={isPayout ? 'delta-up' : ''}>
                        {isPayout ? '+' : '−'}
                        {usd(ev.amount ?? 0, locale)} {SETTLEMENT_SYMBOL}
                      </span>
                      <small>
                        {isPayout
                          ? c('Escrow → Treasury', 'Escrow → Tesorería')
                          : c('Auto-settled', 'Liquidación autónoma')}
                      </small>
                    </div>
                  </li>
                );
              })}
            </ul>
          ) : (
            <p className="muted">
              {c(
                'No recent settlement events in the current view.',
                'No hay movimientos de liquidación recientes en la vista actual.'
              )}
            </p>
          )}
        </section>

        {/* On-chain Wallet & Settlement Token Accounts */}
        <section className="panel">
          <div className="panel-title">
            <div>
              <h2>{c('On-chain accounts & custody', 'Cuentas on-chain y custodia')}</h2>
              <p>
                {c(
                  `Direct balances and program parameters for ${SETTLEMENT_SYMBOL} settlement on Solana.`,
                  `Saldos directos y parámetros del programa para liquidación en ${SETTLEMENT_SYMBOL} sobre Solana.`
                )}
              </p>
            </div>
            <button
              type="button"
              disabled={resource.loading}
              onClick={resource.reload}
            >
              {c('Refresh balances', 'Actualizar saldos')}
            </button>
          </div>

          <DataGrid
            items={[
              [
                c('Connected operator wallet', 'Wallet de operador conectada'),
                publicKey ? (
                  <CopyAddress value={publicKey.toBase58()} />
                ) : (
                  c('Not connected', 'Sin conectar')
                ),
              ],
              [
                c('Native SOL balance (network fees)', 'Saldo SOL nativo (comisiones de red)'),
                !publicKey
                  ? c('Connect a wallet', 'Conecta una wallet')
                  : resource.data?.balance != null
                    ? (
                        <div style={{ display: 'inline-flex', alignItems: 'center', gap: 8 }}>
                          <span>
                            {new Intl.NumberFormat(
                              locale === 'es' ? 'es-MX' : 'en-US',
                              { maximumFractionDigits: 6 }
                            ).format(resource.data.balance / 1e9)} SOL
                          </span>
                          <ProvenanceBadge
                            meta={PROVENANCE_SOURCES.ONCHAIN_SOL_BALANCE('Solana Localnet')}
                            compact
                          />
                        </div>
                      )
                    : c('Awaiting RPC sync', 'En espera de sincronización RPC'),
              ],
              [
                c(`Settlement mint (${SETTLEMENT_SYMBOL} Localnet SPL)`, `Mint de liquidación (${SETTLEMENT_SYMBOL} Localnet SPL)`),
                <div style={{ display: 'inline-flex', alignItems: 'center', gap: 8 }}>
                  <CopyAddress value={MINT.toBase58()} />
                  <ProvenanceBadge
                    meta={PROVENANCE_SOURCES.ONCHAIN_SPL_BALANCE(
                      MINT.toBase58(),
                      'Solana Localnet'
                    )}
                    compact
                  />
                </div>,
              ],
              [
                c('Settlement program', 'Programa de liquidación'),
                <CopyAddress value={PROGRAM_ID.toBase58()} />,
              ],
              [
                c('Verified cluster genesis', 'Genesis verificado del clúster'),
                <CopyAddress value={LOCALNET_GENESIS} />,
              ],
              [
                c('Last chain sync', 'Última lectura on-chain'),
                resource.data
                  ? time(resource.data.network.observedAt, locale)
                  : c('Snapshot active', 'Instantánea activa'),
              ],
            ]}
          />

          <h3 style={{ marginTop: 20, marginBottom: 10 }}>
            {c(
              `${SETTLEMENT_SYMBOL} token accounts`,
              `Cuentas de token ${SETTLEMENT_SYMBOL}`
            )}
          </h3>
          {resource.data?.tokens.length ? (
            <DataGrid
              items={resource.data.tokens.map((token) => [
                <span key={`token-bal-${token.address}`} style={{ display: 'inline-flex', alignItems: 'center', gap: 8 }}>
                  <span>{token.amount} {SETTLEMENT_SYMBOL}</span>
                  <ProvenanceBadge
                    meta={PROVENANCE_SOURCES.ONCHAIN_SPL_BALANCE(
                      MINT.toBase58(),
                      'Solana Localnet'
                    )}
                    compact
                  />
                </span>,
                <CopyAddress key={token.address} value={token.address} />,
              ])}
            />
          ) : (
            <p className="hint" style={{ marginBottom: 0 }}>
              {publicKey
                ? c(
                    `No ${SETTLEMENT_SYMBOL} SPL token accounts detected for this wallet on the connected RPC endpoint.`,
                    `No se detectaron cuentas SPL de ${SETTLEMENT_SYMBOL} para esta wallet en el endpoint RPC conectado.`
                  )
                : c(
                    `Connect your operator wallet to list its associated ${SETTLEMENT_SYMBOL} token accounts.`,
                    `Conecta tu wallet de operador para listar sus cuentas de token ${SETTLEMENT_SYMBOL} asociadas.`
                  )}
            </p>
          )}
        </section>
      </div>

      {/* Roles in the network */}
      <section className="panel">
        <div className="panel-title">
          <div>
            <h2>{c('Roles in the network', 'Roles en la red')}</h2>
            <p>
              {c(
                'Conatus separates human capital allocation, machine cryptographic signing, and third-party verification across distinct keys.',
                'Conatus separa la asignación de capital humano, la firma criptográfica de la máquina y la verificación independiente en claves distintas.'
              )}
            </p>
          </div>
        </div>

        <div className="role-cards-grid">
          {roles.map((role) => (
            <article key={role.title} className="role-card">
              <div className="treasury-card-top">
                <span className="role-card-icon" aria-hidden="true">
                  <Icon name={role.icon} />
                </span>
                <span className="badge">{role.badge}</span>
              </div>
              <h3>{role.title}</h3>
              <p>{role.desc}</p>
            </article>
          ))}
        </div>
      </section>
    </>
  );
}
