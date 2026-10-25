import { useState } from 'react';
import { useWallet } from '@solana/wallet-adapter-react';
import type { InvestibleSurplusAssessment, InvestibleSurplusScenario } from '@aerosettle/marketplace-sdk';
import { api } from '../../app/api';
import { ownerAuthHeaders } from '../../app/economic';
import { useCopy } from '../../app/i18n';
import { useResource } from '../../app/useResource';
import { PaperTradingLab } from './PaperTradingLab';

const SCENARIOS: InvestibleSurplusScenario[] = ['BASE', 'CONSERVATIVE', 'STRESS'];

/** A private accounting projection. It never signs a transaction or allocates capital. */
export function InvestibleSurplusPanel({ context, owner }: {
  context: { agent_account: string; network: string; genesis_hash: string; program_id: string; token_mint: string };
  owner: string;
}) {
  const c = useCopy();
  const wallet = useWallet();
  const address = wallet.publicKey?.toBase58() ?? '';
  const identity = `${context.agent_account}:${owner}:${address}:${context.network}:${context.genesis_hash}:${context.program_id}:${context.token_mint}`;
  const [horizon, setHorizon] = useState<7 | 30 | 90>(30);
  const [scenario, setScenario] = useState<InvestibleSurplusScenario>('BASE');
  const [requested, setRequested] = useState('');
  const active = requested === `${identity}:${horizon}` && address === owner && Boolean(wallet.signMessage);
  const resource = useResource(`surplus:${identity}:${horizon}:${requested}`, async (signal) => {
    if (!active || !wallet.signMessage) return null;
    const authHeaders = await ownerAuthHeaders(context.agent_account, owner, {
      publicKey: address, signMessage: (message) => wallet.signMessage!(message),
    }, signal);
    const results = await Promise.all(SCENARIOS.map((name) => api.getAgentInvestibleSurplus(
      context.agent_account, { network: context.network, genesis_hash: context.genesis_hash,
        program_id: context.program_id, token_mint: context.token_mint, scenario: name, horizon_days: horizon },
      { authHeaders, signal })));
    return results.map((result) => result.data);
  });
  const paperPolicy = useResource(`paper-policy:${identity}`, async (signal) => {
    if (address !== owner || !wallet.signMessage) return null;
    const authHeaders = await ownerAuthHeaders(context.agent_account, owner, {
      publicKey: address, signMessage: (message) => wallet.signMessage!(message),
    }, signal);
    return (await api.getAgentBudgetPolicy(context.agent_account, { authHeaders, signal })).data;
  });
  const assessments: InvestibleSurplusAssessment[] = active ? resource.data ?? [] : [];
  const current = assessments.find((item) => item.scenario === scenario);
  const shown = (value: string | null | undefined) => value ?? '—';
  return <section className="panel" aria-label="Investible surplus advisory assessment">
    <h3>{c('Operational continuity and potential surplus', 'Continuidad operativa y excedente potencial')}</h3>
    <p className="hint">ADVISORY ASSESSMENT — NO INVESTMENT EXECUTED</p>
    <p className="hint">Potential surplus is not guaranteed available capital.</p>
    <label>{c('Continuity horizon', 'Horizonte de continuidad')}
      <select value={horizon} onChange={(event) => setHorizon(Number(event.target.value) as 7 | 30 | 90)}>
        <option value={7}>7 {c('days', 'días')}</option><option value={30}>30 {c('days', 'días')}</option>
        <option value={90}>90 {c('days', 'días')}</option>
      </select>
    </label>
    <button type="button" className="button" disabled={resource.loading && active}
      onClick={() => { if (requested === `${identity}:${horizon}`) resource.reload(); else setRequested(`${identity}:${horizon}`); }}>
      {c('Assess all scenarios', 'Evaluar todos los escenarios')}
    </button>
    {active && resource.loading && <p role="status">{c('Assessing…', 'Evaluando…')}</p>}
    {active && resource.error && <p role="alert">{resource.error}</p>}
    {assessments.length > 0 && <>
      <div role="group" aria-label="Sensitivity scenario">
        {SCENARIOS.map((name) => <button key={name} type="button" className="button"
          aria-pressed={scenario === name} onClick={() => setScenario(name)}>{name}</button>)}
      </div>
      <p className="hint">{assessments.map((item) => `${item.scenario}: ${shown(item.estimated_investible_surplus_base_units_str)} (${item.calculation_status})`).join(' · ')}</p>
      {current && <div>
        <strong>{current.calculation_status}</strong> · {current.provenance}
        <p>{c('Treasury considered', 'Tesorería considerada')}: {shown(current.treasury_available_base_units_str)} ·
          {c('Accrued obligations', 'Obligaciones devengadas')}: {shown(current.accrued_obligations_base_units_str)} ·
          {c('Accounting reserve', 'Reserva contable')}: {shown(current.accounting_reserved_base_units_str)}</p>
        <p>{c('Unfunded reserve', 'Reserva sin cubrir')}: {shown(current.unfunded_policy_reserve_base_units_str)} ·
          {c('Pending commitments', 'Compromisos pendientes')}: {shown(current.pending_commitments_base_units_str)} ·
          {c('Continuity buffer', 'Buffer de continuidad')}: {shown(current.operational_buffer_base_units_str)}</p>
        <p>{c('Potential estimated surplus', 'Excedente potencial estimado')}: {shown(current.estimated_investible_surplus_base_units_str)} ·
          {c('Verified surplus', 'Excedente verificado')}: {shown(current.verified_investible_surplus_base_units_str)}</p>
        <p>{c('Policy', 'Política')}: {current.policy_id} v{current.policy_version} ·
          {c('Assessed at', 'Evaluado en')}: {new Date(current.assessed_at * 1000).toISOString()}</p>
        {current.solvency_context && <p className="hint">CON-25: {current.solvency_context.calculation_status} ·
          {c('Conatus Ratio', 'Ratio Conatus')}: {shown(current.solvency_context.conatus_ratio)} ·
          {c('Operating Margin', 'Margen operativo')}: {shown(current.solvency_context.operating_margin)} ·
          Runway: {shown(current.solvency_context.runway_days)} · {current.solvency_context.provenance}</p>}
        {current.calculation_status === 'INSUFFICIENT_DATA' && <p role="status">INSUFFICIENT_DATA ·
          {current.exclusion_reasons.join(', ')}</p>}
        {current.calculation_status === 'ESTIMATED' && <p role="status">{current.provenance === 'SYNTHETIC_TEST'
          ? 'SIMULATED / ESTIMATED — NOT VERIFIED CAPITAL' : 'ESTIMATED — NOT VERIFIED CAPITAL'}</p>}
        <details><summary>{c('Deductions and evidence', 'Deducciones y evidencia')}</summary>
          {current.deductions.map((item) => <p key={item.component}>{item.component}: {shown(item.amount_base_units_str)} ·
            {item.applied_to_surplus ? c('applied', 'aplicada') : c('already reflected or informational', 'ya reflejada o informativa')} · {item.reason}</p>)}
        </details>
      </div>}
    </>}
    {paperPolicy.data?.effective_status === 'ACTIVE' &&
      paperPolicy.data.asset_rules.some((rule) => rule.enabled && rule.token_mint === context.token_mint) &&
      <PaperTradingLab policy={paperPolicy.data} tokenMint={context.token_mint} />}
  </section>;
}
