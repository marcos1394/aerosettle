import { useState } from 'react';
import { useWallet } from '@solana/wallet-adapter-react';
import { api } from '../../app/api';
import {
  assessmentFor, contextKey, contextsOf, formatBaseUnits,
  isProductiveAssessment, loadOwnerEconomy, sameContext, summaryFor,
} from '../../app/economic';
import { useCopy } from '../../app/i18n';
import { useResource } from '../../app/useResource';
import { ProvenanceBadge } from '../../components/ui';

/** Owner-authorized economic read, reused by Agent Detail, Economy, Fleet and Wallet. */
export function LiveSolvencyPanel({ account, owner, title }: {
  account: string; owner: string; title?: string;
}) {
  const c = useCopy();
  const wallet = useWallet();
  const walletAddress = wallet.publicKey?.toBase58() ?? '';
  const identity = `${account}:${owner}:${walletAddress}`;
  const [requested, setRequested] = useState<{ identity: string; revision: number } | null>(null);
  const [selectedContext, setSelectedContext] = useState('');
  const active = requested?.identity === identity;
  const canRead = Boolean(walletAddress && walletAddress === owner && wallet.signMessage);
  const resource = useResource(`${identity}:${requested?.revision ?? 0}:${active}`, async (signal) => {
    if (!active || !canRead || !wallet.signMessage) return null;
    return loadOwnerEconomy(api, account, owner, {
      publicKey: walletAddress,
      signMessage: (message) => wallet.signMessage!(message),
    }, signal);
  });
  const snapshot = active && canRead ? resource.data : null;
  const contexts = snapshot ? contextsOf(snapshot) : [];
  const context = contexts.find((item) => contextKey(item) === selectedContext) ?? contexts[0];
  const summary = snapshot && context ? summaryFor(snapshot, context) : undefined;
  const assessment = snapshot && context ? assessmentFor(snapshot, context) : undefined;
  const productive = Boolean(assessment && isProductiveAssessment(assessment));
  const authorizationError = resource.error && /\b(401|403|UNAUTHORIZED|FORBIDDEN)\b/i.test(resource.error);

  return <section className="panel" aria-label={c('Agent economic assessment', 'Evaluación económica del agente')}>
    <div className="section-heading">
      <h2>{title ?? c('Agent economy · owner scope', 'Economía del agente · alcance del propietario')}</h2>
      <ProvenanceBadge provenance={assessment?.provenance === 'LIVE_RPC' ? 'ONCHAIN_VERIFIED' : 'EXTERNAL_VERIFIED'}
        status={productive ? 'VERIFIED' : 'PENDING_ATTESTATION'}
        source="Economic Ledger / CON-25" network={context?.network ?? '—'}
        period={assessment ? `${assessment.window_start}–${assessment.window_end} UTC` : '30 days UTC'} compact />
    </div>
    <p className="hint">{c('Private accounting and solvency for the selected on-chain agent. A signed coverage record alone does not verify underlying income or costs.', 'Contabilidad y solvencia privadas del agente on-chain seleccionado. Una cobertura firmada no verifica por sí sola ingresos ni costos.')}</p>
    {!walletAddress && <p role="status">{c('Wallet disconnected. Connect the current owner to view private economics.', 'Wallet desconectada. Conecta al propietario actual para consultar la economía privada.')}</p>}
    {walletAddress && walletAddress !== owner && <p role="status">{c('Access restricted to the current agent owner.', 'Acceso restringido al propietario actual del agente.')}</p>}
    {walletAddress === owner && !wallet.signMessage && <p role="status">{c('This wallet cannot sign the required ownership challenge.', 'Esta wallet no puede firmar el desafío de propiedad requerido.')}</p>}
    {canRead && <button type="button" className="button" disabled={resource.loading && active}
      onClick={() => setRequested((current) => ({ identity, revision: (current?.revision ?? 0) + 1 }))}>
      {resource.loading && active ? c('Loading economy…', 'Cargando economía…') : c('View owner economy', 'Consultar economía del propietario')}
    </button>}
    {active && canRead && resource.loading && <p role="status">{c('Loading private economic records…', 'Cargando registros económicos privados…')}</p>}
    {active && canRead && resource.error && <p role="alert">{authorizationError
      ? c('Authorization expired or access denied. Sign again to retry.', 'Autorización vencida o acceso denegado. Firma de nuevo para reintentar.')
      : c('Economic API unavailable: ', 'API económica no disponible: ') + resource.error}</p>}
    {snapshot && contexts.length === 0 && <p role="status">INSUFFICIENT_DATA · {c('No economic context was returned for this agent.', 'No hay contexto económico para este agente.')}</p>}
    {snapshot?.mixedAssetContext && <p role="alert">MIXED_ASSET_CONTEXT · {c('The API found incompatible monetary contexts. Select an explicit context before comparing assessments.', 'La API detectó contextos monetarios incompatibles. Selecciona un contexto explícito antes de comparar evaluaciones.')}</p>}
    {snapshot && context && <>
      {contexts.length > 1 && <label>{c('Monetary context', 'Contexto monetario')}
        <select value={contextKey(context)} onChange={(event) => setSelectedContext(event.target.value)}>
          {contexts.map((item) => <option key={contextKey(item)} value={contextKey(item)}>{item.network} · {item.token_mint}</option>)}
        </select>
      </label>}
      <p className="hint">{c('Agent', 'Agente')}: {context.agent_account} · {context.network} · {c('Genesis', 'Génesis')}: {context.genesis_hash} · {c('Program', 'Programa')}: {context.program_id} · {c('Mint', 'Mint')}: {context.token_mint}</p>
      <p className="hint">{c('Read at', 'Consultado')}: {snapshot.observedAt} · {c('Independent API reads; no atomic cross-source snapshot.', 'Lecturas API independientes; no son un snapshot atómico entre fuentes.')}</p>
      <div className="kpi-grid" style={{ gridTemplateColumns: 'repeat(auto-fit, minmax(190px, 1fr))' }}>
        {([
          [c('Reconciled income', 'Ingresos conciliados'), summary?.total_income_reconciled_str, 'RECONCILED'],
          [c('Provisional income', 'Ingresos provisionales'), summary?.total_income_provisional_str, 'PROVISIONAL'],
          [c('Realized OPEX', 'OPEX realizado'), summary?.total_expenses_realized_str, 'ACCOUNTING'],
          [c('Accrued obligations', 'Obligaciones devengadas'), summary?.total_obligations_accrued_str, 'ACCOUNTING'],
          [c('Accounting reserve', 'Reserva contable'), summary?.total_capital_reserved_str, 'OFF-CHAIN RESERVE'],
          [c('Ledger available', 'Disponible en ledger'), summary?.available_balance_str, 'ACCOUNTING'],
          [c('Potentially investible', 'Potencialmente invertible'), productive ? assessment?.eligible_liquid_capital_base_units_str : null, 'CON-25 POLICY · VALID ONLY'],
        ] as const).map(([label, value, source]) => <div className="kpi" key={label}>
          <div className="kpi-label">{label}</div>
          <strong className="tabular">{formatBaseUnits(value, context.token_mint)}</strong>
          <div className="kpi-foot">Economic Ledger · {source} · {context.network} · {context.token_mint}</div>
        </div>)}
      </div>
      <div className="panel" style={{ marginTop: 14 }}>
        <strong>{assessment?.calculation_status ?? 'INSUFFICIENT_DATA'}</strong>
        <p>{c('Conatus Ratio', 'Ratio Conatus')}: {productive ? `${assessment!.conatus_ratio}×` : '—'} · {c('Operating Margin', 'Margen operativo')}: {productive ? assessment!.operating_margin ?? '—' : '—'} · {c('Operating Surplus', 'Excedente operativo')}: {productive ? formatBaseUnits(assessment!.operating_surplus_base_units_str, context.token_mint) : '—'} · Runway: {productive ? assessment!.runway_days ?? '—' : '—'}</p>
        <p>{c('Sustainability', 'Sostenibilidad')}: {productive ? assessment!.sustainability_class : 'UNDETERMINED'} · {c('Origin', 'Origen')}: {assessment?.provenance ?? 'HISTORICAL_UNVERIFIED'}</p>
        <p className="hint">{assessment ? `${new Date(assessment.window_start * 1000).toISOString()} – ${new Date(assessment.window_end * 1000).toISOString()} UTC · ${new Date(assessment.calculated_at * 1000).toISOString()}` : c('No assessed window', 'Sin ventana evaluada')}</p>
        {!productive && <p className="hint">{assessment?.calculation_status ?? 'INSUFFICIENT_DATA'} · {c('Authentic economic origin, coverage, or a valid calculation is still unavailable.', 'Aún falta origen económico auténtico, cobertura o un cálculo válido.')}</p>}
      </div>
      <details><summary>{c('Costs, reserves and movements', 'Costos, reservas y movimientos')}</summary>
        <p>{c('Costs shown', 'Costos mostrados')}: {snapshot.costs.filter((item) => sameContext(item as typeof context, context)).length}{snapshot.costsHasMore ? ' · more pages available' : ''} · {c('Reserves', 'Reservas')}: {snapshot.reserves.filter((item) => sameContext(item as typeof context, context)).length} · {c('Movements shown', 'Movimientos mostrados')}: {snapshot.movements.filter((item) => sameContext(item, context)).length}{snapshot.movementsHasMore ? ' · more pages available' : ''}</p>
        <p>{c('Historical assessments', 'Evaluaciones históricas')}: {snapshot.history.filter((item) => sameContext(item, context)).length} · {c('Recent list pages do not represent complete economic totals.', 'Las páginas recientes no representan totales económicos completos.')}</p>
        {snapshot.reserves.filter((item) => sameContext(item as typeof context, context)).map((reserve) => <p key={reserve.reserve_id}>{reserve.reserve_type} · {reserve.status} · {formatBaseUnits(reserve.current_reserved_str, context.token_mint)} · OFF-CHAIN ACCOUNTING RESERVE</p>)}
      </details>
    </>}
  </section>;
}
