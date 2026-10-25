import { useEffect, useRef, useState } from 'react';
import { useWallet } from '@solana/wallet-adapter-react';
import { paperSimulationMessage, type AgentBudgetPolicy, type PaperScenario,
  type PaperSimulationRequest, type PaperSimulationResult, type ProductiveReinvestmentScenario,
} from '@aerosettle/marketplace-sdk';
// @ts-expect-error bs58 lacks bundled TypeScript declarations in this workspace
import bs58 from 'bs58';
import { api } from '../../app/api';
import { ownerAuthHeaders } from '../../app/economic';
import { useCopy } from '../../app/i18n';
import { useResource } from '../../app/useResource';

/** Owner-only sandbox; every displayed amount is explicitly fictitious. */
export function PaperTradingLab({ policy, tokenMint }: { policy: AgentBudgetPolicy; tokenMint: string }) {
  const c = useCopy();
  const wallet = useWallet();
  const owner = policy.owner_pubkey;
  const address = wallet.publicKey?.toBase58() ?? '';
  const authorized = address === owner && Boolean(wallet.signMessage);
  const abortRef = useRef(new AbortController());
  const [mint, setMint] = useState(tokenMint);
  const [budget, setBudget] = useState('1000');
  const [quantity, setQuantity] = useState('9');
  const [instrument, setInstrument] = useState('fixture:spot:compute-credit:alpha');
  const [scenario, setScenario] = useState<PaperScenario>('BASE');
  const [horizon, setHorizon] = useState<7 | 30 | 90>(30);
  const [kind, setKind] = useState<'FINANCIAL_SPOT' | 'PRODUCTIVE_COMPARISON'>('FINANCIAL_SPOT');
  const [hardwareCost, setHardwareCost] = useState('400');
  const [replacementCost, setReplacementCost] = useState('300');
  const [operatingCost, setOperatingCost] = useState('20');
  const [maintenanceCost, setMaintenanceCost] = useState('10');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [latest, setLatest] = useState<PaperSimulationResult | null>(null);
  const identity = `${policy.agent_account}:${policy.agent_id}:${owner}:${address}:${mint}`;

  useEffect(() => {
    const controller = new AbortController();
    abortRef.current = controller;
    setLatest(null); setError(''); setBusy(false);
    return () => controller.abort();
  }, [identity, policy.version]);
  useEffect(() => setMint(tokenMint), [tokenMint]);

  const history = useResource(`paper-history:${identity}:${policy.version}`, async (signal) => {
    if (!authorized || !wallet.signMessage) return [] as PaperSimulationResult[];
    const authHeaders = await ownerAuthHeaders(policy.agent_account, owner, {
      publicKey: address, signMessage: (message) => wallet.signMessage!(message),
    }, signal);
    return (await api.listAgentPaperSimulations(policy.agent_account, { authHeaders, signal })).data;
  });

  const productive = (name: string, resourceType: 'HARDWARE' | 'REPLACEMENT', initial: string): ProductiveReinvestmentScenario => ({
    scenario_id: name, resource_type: resourceType, initial_cost_base_units_str: initial,
    operating_cost_base_units_str: operatingCost, maintenance_cost_base_units_str: maintenanceCost,
    useful_life_days: 365, estimated_utilization_bps: 5000, capacity_change_bps: 2000,
    currency_or_token_mint: mint, evidence_provenance: 'USER_SUPPLIED_ASSUMPTION',
  });

  async function run() {
    if (!authorized || !wallet.signMessage || abortRef.current.signal.aborted) return;
    setBusy(true); setError(''); setLatest(null);
    try {
      const timestamp = Math.floor(Date.now() / 1000);
      const request: PaperSimulationRequest = {
        agent_account: policy.agent_account, agent_id: policy.agent_id, owner_pubkey: owner,
        network: policy.network, genesis_hash: policy.genesis_hash, program_id: policy.program_id,
        treasury_token_mint: mint, trading_quote_currency: mint,
        paper_budget_base_units_str: budget.trim(), funding_source: 'MANUAL_PAPER_ALLOCATION',
        scenario_id: `paper_${crypto.randomUUID()}`, scenario_kind: kind, scenario,
        instrument_id: instrument, side: 'BUY', quantity_base_units_str: quantity.trim(),
        require_full_fill: false, holding_period_days: horizon,
        productive_alternatives: [productive('hardware', 'HARDWARE', hardwareCost.trim()),
          productive('replacement', 'REPLACEMENT', replacementCost.trim())],
        simulation_timestamp: timestamp, nonce: crypto.randomUUID(), idempotency_key: crypto.randomUUID(),
      };
      const message = await paperSimulationMessage(policy.agent_account, owner, timestamp, request);
      const signature = await wallet.signMessage(message);
      if (abortRef.current.signal.aborted || wallet.publicKey?.toBase58() !== owner) return;
      const response = await api.runAgentPaperSimulation(policy.agent_account, request, {
        authHeaders: { 'X-Signer-Pubkey': owner, 'X-Timestamp': String(timestamp),
          'X-Signature': bs58.encode(signature) }, signal: abortRef.current.signal,
      });
      if (!abortRef.current.signal.aborted) { setLatest(response.data); history.reload(); }
    } catch (cause) {
      if (!abortRef.current.signal.aborted) setError(cause instanceof Error ? cause.message : String(cause));
    } finally {
      if (!abortRef.current.signal.aborted) setBusy(false);
    }
  }

  if (!authorized) return <section className="panel" aria-label="Paper Trading Lab">
    <h3>Investment Simulation Lab</h3><p role="status">{c('Connect the current owner wallet to enter paper mode.', 'Conecta la wallet del propietario actual para entrar al modo de simulación.')}</p>
  </section>;

  return <section className="panel" aria-label="Paper Trading Lab" style={{ marginTop: 18,
    background: 'linear-gradient(135deg, rgba(34,197,171,.12), rgba(75,89,200,.11))',
    border: '1px solid rgba(74,204,180,.35)' }}>
    <div className="section-heading"><h3>Investment Simulation Lab</h3><strong>PAPER MODE</strong></div>
    <p className="hint"><strong>PAPER TRADING — NO REAL ORDERS</strong> · SIMULATED CAPITAL — NOT WITHDRAWABLE · NO FINANCIAL EXECUTION</p>
    <p className="hint">{c('Fixtures and user assumptions only. This budget is separate from the ledger, wallet and CON-30 estimated surplus.',
      'Solo fixtures y supuestos del usuario. Este presupuesto está separado del ledger, la wallet y el excedente estimado de CON-30.')}</p>
    <p className="hint">{policy.agent_account} · {owner} · {mint} · OFFLINE_FIXTURE</p>
    <div className="kpi-grid" style={{ gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))' }}>
      <label>{c('Paper budget · base units', 'Presupuesto ficticio · unidades base')}
        <input inputMode="numeric" value={budget} onChange={(event) => setBudget(event.target.value)} /></label>
      <label>{c('Paper asset quantity', 'Cantidad ficticia de activo')}
        <input inputMode="numeric" value={quantity} onChange={(event) => setQuantity(event.target.value)} /></label>
      <label>{c('Asset / quote mint', 'Activo / mint cotizado')}
        <select value={mint} onChange={(event) => setMint(event.target.value)}>
          {policy.asset_rules.filter((item) => item.enabled).map((item) => <option key={item.token_mint} value={item.token_mint}>{item.token_mint}</option>)}
        </select></label>
      <label>{c('Paper spot venue', 'Mercado spot ficticio')}
        <select value={instrument} onChange={(event) => setInstrument(event.target.value)}>
          <option value="fixture:spot:compute-credit:alpha">PAPER · FIXTURE_ALPHA</option>
          <option value="fixture:spot:compute-credit:beta">PAPER · FIXTURE_BETA</option>
        </select></label>
      <label>{c('Sensitivity', 'Sensibilidad')}
        <select value={scenario} onChange={(event) => setScenario(event.target.value as PaperScenario)}>
          <option>BASE</option><option>DOWNSIDE</option><option>STRESS</option>
        </select></label>
      <label>{c('Horizon', 'Horizonte')}
        <select value={horizon} onChange={(event) => setHorizon(Number(event.target.value) as 7 | 30 | 90)}>
          <option value={7}>7 days</option><option value={30}>30 days</option><option value={90}>90 days</option>
        </select></label>
    </div>
    <div role="group" aria-label="Simulation category">
      <button className="button" type="button" aria-pressed={kind === 'FINANCIAL_SPOT'} onClick={() => setKind('FINANCIAL_SPOT')}>Financial Paper Portfolio</button>{' '}
      <button className="button" type="button" aria-pressed={kind === 'PRODUCTIVE_COMPARISON'} onClick={() => setKind('PRODUCTIVE_COMPARISON')}>Productive Reinvestment</button>
    </div>
    <details open={kind === 'PRODUCTIVE_COMPARISON'}>
      <summary>{c('Explicit productive assumptions · no inferred revenue', 'Supuestos productivos explícitos · sin ingresos inferidos')}</summary>
      <div className="kpi-grid" style={{ gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))' }}>
        <label>Hardware CAPEX <input inputMode="numeric" value={hardwareCost} onChange={(event) => setHardwareCost(event.target.value)} /></label>
        <label>Replacement CAPEX <input inputMode="numeric" value={replacementCost} onChange={(event) => setReplacementCost(event.target.value)} /></label>
        <label>Monthly OPEX <input inputMode="numeric" value={operatingCost} onChange={(event) => setOperatingCost(event.target.value)} /></label>
        <label>Monthly maintenance <input inputMode="numeric" value={maintenanceCost} onChange={(event) => setMaintenanceCost(event.target.value)} /></label>
      </div>
      <p className="hint">{c('Illustrative assumptions: 365-day life, 50% utilization, 20% nominal capacity change. Payback remains unknown without explicit cash benefits.',
        'Supuestos ilustrativos: vida útil de 365 días, utilización de 50% y cambio nominal de capacidad de 20%. La recuperación queda desconocida sin beneficios monetarios explícitos.')}</p>
    </details>
    <button className="button" type="button" disabled={busy || policy.effective_status !== 'ACTIVE'} onClick={() => void run()}>
      {busy ? c('Simulating…', 'Simulando…') : c('Run Simulation', 'Ejecutar simulación')}
    </button>
    {error && <p role="alert">{error}</p>}
    {latest && <div className="panel" style={{ marginTop: 14 }}>
      <strong>{latest.status} · {latest.fill_status ?? 'PRODUCTIVE COMPARISON'}</strong>
      <p>{c('Paper budget', 'Presupuesto ficticio')}: {latest.paper_budget_base_units_str} ·
        {c('Paper residual liquidity', 'Liquidez ficticia residual')}: {latest.remaining_paper_budget_base_units_str} ·
        {c('Entry total', 'Costo de entrada')}: {latest.entry_total_base_units_str ?? '—'}</p>
      <p>{c('Hypothetical stress loss', 'Pérdida hipotética bajo estrés')}: {latest.hypothetical_loss_base_units_str ?? '—'} ·
        {c('Market provenance', 'Procedencia de mercado')}: {latest.data_provenance} · {latest.provider_mode}</p>
      {latest.scenario_kind === 'FINANCIAL_SPOT' && <p>{c('Fixture reference price', 'Precio de referencia ficticio')}:
        {String(latest.market_snapshot.price_numerator_str ?? '—')}/{String(latest.market_snapshot.price_denominator_str ?? '—')} ·
        {c('Liquidity units', 'Unidades de liquidez')}: {String(latest.market_snapshot.available_quantity_base_units_str ?? '—')} ·
        Fee: {String(latest.execution_cost_snapshot.fee_bps ?? '—')} bps ·
        Spread: {String(latest.execution_cost_snapshot.spread_bps ?? '—')} bps ·
        Slippage: {String(latest.execution_cost_snapshot.slippage_bps ?? '—')} bps</p>}
      {latest.scenario_kind === 'FINANCIAL_SPOT' && <p>{c('Hypothetical fill', 'Fill hipotético')}:
        {latest.filled_quantity_base_units_str ?? '—'} ·
        Fee: {latest.entry_fee_base_units_str ?? '—'} ·
        Spread: {latest.entry_spread_base_units_str ?? '—'} ·
        Slippage: {latest.entry_slippage_base_units_str ?? '—'}</p>}
      <p>{c('Fixture snapshot', 'Snapshot del fixture')}: {new Date(latest.simulation_timestamp * 1000).toISOString()} · {latest.market_snapshot_hash}</p>
      <h4>Productive Reinvestment</h4>
      {latest.productive_alternatives.map((item) => <p key={String(item.scenario_id)}>
        {String(item.scenario_id)} · {String(item.status)} · CAPEX {String(item.initial_cost_base_units_str)} ·
        {c('Total paper cost', 'Costo ficticio total')} {String(item.total_paper_cost_base_units_str)} ·
        {c('Residual', 'Residual')} {String(item.remaining_paper_budget_base_units_str)} ·
        {c('Payback', 'Recuperación')} {item.payback_days == null ? 'INSUFFICIENT_ASSUMPTIONS' : `${item.payback_days} days`}
      </p>)}
      <p className="hint">{latest.simulation_id} · {latest.methodology_version} · NO FINANCIAL EXECUTION</p>
    </div>}
    {history.error && <p role="alert">{history.error}</p>}
    <details><summary>{c('Immutable paper history', 'Historial ficticio inmutable')} ({history.data?.length ?? 0})</summary>
      {history.data?.map((item) => <p key={item.simulation_id}>{item.simulation_id} · {item.scenario} · {item.status} ·
        {item.paper_budget_base_units_str} · {item.data_provenance} · PAPER ONLY</p>)}
    </details>
  </section>;
}
