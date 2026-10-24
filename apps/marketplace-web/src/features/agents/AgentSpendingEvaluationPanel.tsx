import { useEffect, useRef, useState } from 'react';
import { useWallet } from '@solana/wallet-adapter-react';
import { spendingEvaluationMessage, type AgentBudgetPolicy, type SpendingDecision,
  type SpendingProposal } from '@aerosettle/marketplace-sdk';
// @ts-expect-error bs58 lacks bundled TypeScript declarations in this workspace
import bs58 from 'bs58';
import { api } from '../../app/api';
import { ownerAuthHeaders } from '../../app/economic';
import { useCopy } from '../../app/i18n';
import { useResource } from '../../app/useResource';

/** A signed advisory evaluation; this panel never creates or signs a payment. */
export function AgentSpendingEvaluationPanel({ policy }: { policy: AgentBudgetPolicy }) {
  const c = useCopy();
  const wallet = useWallet();
  const address = wallet.publicKey?.toBase58() ?? '';
  const owner = policy.owner_pubkey;
  const account = policy.agent_account;
  const identity = `${account}:${policy.agent_id}:${owner}:${address}`;
  const authorized = address === owner && Boolean(wallet.signMessage);
  const abortRef = useRef(new AbortController());
  const [mint, setMint] = useState(policy.asset_rules[0]?.token_mint ?? '');
  const [recipient, setRecipient] = useState('');
  const [amount, setAmount] = useState('');
  const [purpose, setPurpose] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [decision, setDecision] = useState<SpendingDecision | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    abortRef.current = controller;
    setMint(policy.asset_rules[0]?.token_mint ?? '');
    setRecipient(''); setAmount(''); setPurpose(''); setDecision(null); setError(''); setBusy(false);
    return () => controller.abort();
  }, [identity, policy.version]);

  const history = useResource(`spending-evaluations:${identity}:${policy.version}`, async (signal) => {
    if (!authorized || !wallet.signMessage) return [] as SpendingDecision[];
    const authHeaders = await ownerAuthHeaders(account, owner, {
      publicKey: address, signMessage: (message) => wallet.signMessage!(message),
    }, signal);
    return (await api.listAgentSpendingEvaluations(account, { authHeaders, signal })).data;
  });

  async function evaluate() {
    if (!authorized || !wallet.signMessage || abortRef.current.signal.aborted) return;
    setBusy(true); setError(''); setDecision(null);
    try {
      const requestedAt = Math.floor(Date.now() / 1000);
      const proposal: SpendingProposal = {
        proposal_id: crypto.randomUUID(), idempotency_key: crypto.randomUUID(),
        nonce: crypto.randomUUID(), agent_account: account, agent_id: policy.agent_id,
        requester_pubkey: owner, network: policy.network,
        genesis_hash: policy.genesis_hash, program_id: policy.program_id,
        token_mint: mint, recipient_pubkey: recipient.trim(),
        amount_base_units_str: amount.trim(), purpose: purpose.trim(), requested_at: requestedAt,
        expected_policy_id: policy.policy_id, expected_policy_version: policy.version,
        expected_policy_hash: policy.policy_hash, metadata: {},
      };
      const message = await spendingEvaluationMessage(account, owner, requestedAt, proposal);
      const signature = await wallet.signMessage(message);
      if (abortRef.current.signal.aborted || wallet.publicKey?.toBase58() !== owner) return;
      const response = await api.evaluateAgentSpending(account, proposal, {
        authHeaders: { 'X-Signer-Pubkey': owner, 'X-Timestamp': String(requestedAt),
          'X-Signature': bs58.encode(signature) }, signal: abortRef.current.signal,
      });
      if (!abortRef.current.signal.aborted) { setDecision(response.data); history.reload(); }
    } catch (cause) {
      if (!abortRef.current.signal.aborted) setError(cause instanceof Error ? cause.message : String(cause));
    } finally {
      if (!abortRef.current.signal.aborted) setBusy(false);
    }
  }

  if (!authorized) return null;
  return <section className="panel" aria-label="Agent spending evaluation">
    <h3>{c('Evaluate a spending proposal', 'Evaluar una propuesta de gasto')}</h3>
    <p className="hint">{c('Advisory only. No payment or token transfer is executed.',
      'Solo consultivo. No se ejecuta ningún pago ni transferencia de tokens.')}</p>
    <label>{c('Asset', 'Activo')}
      <select value={mint} onChange={(event) => setMint(event.target.value)}>
        {policy.asset_rules.map((rule) => <option key={rule.token_mint} value={rule.token_mint}>{rule.token_mint}</option>)}
      </select>
    </label>
    <label>{c('Recipient public key', 'Clave pública del destinatario')}
      <input value={recipient} onChange={(event) => setRecipient(event.target.value)} />
    </label>
    <label>{c('Amount in base units', 'Importe en unidades base')}
      <input inputMode="numeric" value={amount} onChange={(event) => setAmount(event.target.value)} />
    </label>
    <label>{c('Purpose', 'Motivo')}
      <input value={purpose} onChange={(event) => setPurpose(event.target.value)} maxLength={500} />
    </label>
    <button type="button" className="button" disabled={busy || !mint || !recipient || !amount || !purpose}
      onClick={() => void evaluate()}>{busy ? c('Evaluating…', 'Evaluando…') : c('Evaluate only', 'Solo evaluar')}</button>
    {error && <p role="alert">{error}</p>}
    {decision && <div role="status">
      <strong>{decision.decision}</strong> · {decision.reason_codes.join(', ') || c('All checks passed', 'Se cumplieron todas las comprobaciones')}
      <p>{decision.decision === 'ALLOW'
        ? 'Eligible for next authorization stage — no payment executed'
        : decision.decision === 'REQUIRE_APPROVAL'
          ? 'Manual review required — funds cannot be moved'
          : c('Proposal does not meet policy limits.', 'La propuesta no cumple los límites de la política.')}</p>
      <p className="hint">v{decision.policy_version ?? '—'} · {new Date(decision.evaluated_at * 1000).toISOString()} · {c('Expires', 'Vence')}: {new Date(decision.expires_at * 1000).toISOString()} · {decision.economic_evidence_status}</p>
      <p className="hint">{c('Daily limit / used / committed / remaining', 'Límite / consumo / compromiso / restante diario')}: {[
        decision.daily_limit_base_units_str, decision.daily_used_base_units_str,
        decision.daily_committed_base_units_str, decision.daily_remaining_base_units_str,
      ].map((value) => value ?? '—').join(' / ')}</p>
      <p className="hint">{c('Reserve target / accounting reserve / available', 'Objetivo de reserva / reserva contable / disponible')}: {[
        decision.minimum_reserve_base_units_str, decision.accounting_reserved_base_units_str,
        decision.available_liquidity_base_units_str,
      ].map((value) => value ?? '—').join(' / ')}</p>
    </div>}
    <details><summary>{c('Evaluation history', 'Historial de evaluaciones')} ({history.data?.length ?? 0})</summary>
      {history.error && <p role="alert">{history.error}</p>}
      {history.data?.map((item) => <p key={item.decision_id}>{item.decision} · {item.reason_codes.join(', ')} · v{item.policy_version ?? '—'} · {item.economic_evidence_status} · {item.is_currently_applicable ? c('current', 'vigente') : c('historical', 'histórico')}</p>)}
    </details>
  </section>;
}
