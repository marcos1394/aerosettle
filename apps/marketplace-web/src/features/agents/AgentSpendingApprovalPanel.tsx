import { useEffect, useRef, useState } from 'react';
import { useWallet } from '@solana/wallet-adapter-react';
import { spendingApprovalMessage, type AgentBudgetPolicy, type SpendingApproval,
  type SpendingApprovalAction, type SpendingApprovalMutation } from '@aerosettle/marketplace-sdk';
// @ts-expect-error bs58 lacks bundled TypeScript declarations in this workspace
import bs58 from 'bs58';
import { api } from '../../app/api';
import { ownerAuthHeaders } from '../../app/economic';
import { useCopy } from '../../app/i18n';
import { useResource } from '../../app/useResource';

/** Owner consent is audited off-chain and never sends a payment. */
export function AgentSpendingApprovalPanel({ policy }: { policy: AgentBudgetPolicy }) {
  const c = useCopy();
  const wallet = useWallet();
  const owner = policy.owner_pubkey;
  const account = policy.agent_account;
  const address = wallet.publicKey?.toBase58() ?? '';
  const identity = `${account}:${policy.agent_id}:${owner}:${address}:${policy.network}:${policy.version}`;
  const authorized = address === owner && Boolean(wallet.signMessage);
  const abortRef = useRef(new AbortController());
  const [selected, setSelected] = useState('');
  const [reason, setReason] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');

  useEffect(() => {
    const controller = new AbortController();
    abortRef.current = controller;
    setSelected(''); setReason(''); setBusy(false); setError(''); setNotice('');
    return () => controller.abort();
  }, [identity]);

  const records = useResource(`owner-approvals:${identity}`, async (signal) => {
    if (!authorized || !wallet.signMessage) return { decisions: [], approvals: [] };
    const authHeaders = await ownerAuthHeaders(account, owner, {
      publicKey: address, signMessage: (message) => wallet.signMessage!(message),
    }, signal);
    const [decisions, approvals] = await Promise.all([
      api.listAgentSpendingEvaluations(account, { authHeaders, signal }),
      api.listAgentSpendingApprovals(account, { authHeaders, signal }),
    ]);
    return { decisions: decisions.data, approvals: approvals.data };
  });

  const context = useResource(`owner-approval-context:${identity}:${selected}`, async (signal) => {
    if (!authorized || !selected || !wallet.signMessage) return null;
    const authHeaders = await ownerAuthHeaders(account, owner, {
      publicKey: address, signMessage: (message) => wallet.signMessage!(message),
    }, signal);
    return (await api.getSpendingApprovalContext(account, selected, { authHeaders, signal })).data;
  });

  const review = records.data?.approvals.find((item) => item.decision_id === selected) ?? null;
  const eventHistory = useResource(`owner-approval-events:${identity}:${review?.approval_id ?? ''}`, async (signal) => {
    if (!authorized || !review || !wallet.signMessage) return [];
    const authHeaders = await ownerAuthHeaders(account, owner, {
      publicKey: address, signMessage: (message) => wallet.signMessage!(message),
    }, signal);
    return (await api.getSpendingApprovalHistory(account, review.approval_id, { authHeaders, signal })).data;
  });

  async function act(action: SpendingApprovalAction) {
    const source = context.data;
    if (!authorized || !wallet.signMessage || !source || abortRef.current.signal.aborted) return;
    if ((action === 'REJECT' || action === 'REVOKE') && !reason.trim()) {
      setError(c('A reason is required.', 'Se requiere un motivo.')); return;
    }
    setBusy(true); setError(''); setNotice('');
    try {
      const { approval_id: approvalId, proposal: _proposal, decision: _decision, ...binding } = source;
      const now = Math.floor(Date.now() / 1000);
      const expiresAt = action === 'OPEN'
        ? Math.min(source.decision.expires_at, policy.expires_at, now + 120)
        : review?.expires_at ?? 0;
      const body: SpendingApprovalMutation = {
        ...binding, action, issued_at: now, expires_at: expiresAt,
        nonce: crypto.randomUUID(), idempotency_key: crypto.randomUUID(), reason: reason.trim(),
      };
      const path = `/v1/agents/${account}/spending-approvals${action === 'OPEN' ? '' : `/${approvalId}/${action.toLowerCase()}`}`;
      const message = await spendingApprovalMessage(account, owner, path, now, body);
      const signature = await wallet.signMessage(message);
      if (abortRef.current.signal.aborted || wallet.publicKey?.toBase58() !== owner) return;
      const options = { authHeaders: {
        'X-Signer-Pubkey': owner, 'X-Timestamp': String(now), 'X-Signature': bs58.encode(signature),
      }, signal: abortRef.current.signal };
      let result: SpendingApproval;
      if (action === 'OPEN') result = (await api.createSpendingApprovalReview(account, body, options)).data;
      else if (action === 'APPROVE') result = (await api.approveSpendingProposal(account, approvalId, body, options)).data;
      else if (action === 'REJECT') result = (await api.rejectSpendingProposal(account, approvalId, body, options)).data;
      else result = (await api.revokeSpendingApproval(account, approvalId, body, options)).data;
      if (!abortRef.current.signal.aborted) {
        setReason('');
        setNotice(result.approval_status === 'APPROVED'
          ? 'OWNER CONSENT RECORDED — NO PAYMENT EXECUTED'
          : result.approval_status === 'REVOKED' ? 'REVOKED — NO LONGER VALID'
            : c('Review action recorded. No payment executed.', 'Acción registrada. No se ejecutó ningún pago.'));
        records.reload(); eventHistory.reload();
      }
    } catch (cause) {
      if (!abortRef.current.signal.aborted) setError(cause instanceof Error ? cause.message : String(cause));
    } finally {
      if (!abortRef.current.signal.aborted) setBusy(false);
    }
  }

  if (!authorized) return null;
  return <section className="panel" aria-label="Owner spending consent">
    <h3>{c('Owner spending review', 'Revisión de gastos del propietario')}</h3>
    <p className="hint">{c('Each action requires your Ed25519 signature. Consent never transfers funds.',
      'Cada acción requiere su firma Ed25519. El consentimiento nunca transfiere fondos.')}</p>
    {records.error && <p role="alert">{records.error}</p>}
    <label>{c('Economic decision', 'Decisión económica')}
      <select value={selected} onChange={(event) => { setSelected(event.target.value); setError(''); setNotice(''); }}>
        <option value="">{c('Select a proposal', 'Seleccione una propuesta')}</option>
        {records.data?.decisions.map((item) => <option key={item.decision_id} value={item.decision_id}>
          {item.decision} · {item.proposal_id} · {item.requested_amount_base_units_str}
        </option>)}
      </select>
    </label>
    {context.error && <p role="alert">{context.error}</p>}
    {context.data && <div>
      <p>{c('Agent', 'Agente')}: {account} · {c('Purpose', 'Propósito')}: {context.data.proposal.purpose}</p>
      <p>{c('Amount', 'Importe')}: {context.data.amount_base_units_str} · {c('Mint', 'Activo')}: {context.data.token_mint}</p>
      <p>{c('Recipient', 'Destinatario')}: {context.data.recipient_pubkey}</p>
      <p>CON-28: {context.data.decision.decision} · {context.data.decision.reason_codes.join(', ')} · {context.data.decision.economic_evidence_status}</p>
      <p>{c('Policy', 'Política')}: {context.data.policy_id} v{context.data.policy_version} · {c('Requested', 'Solicitada')}: {new Date(context.data.proposal.requested_at * 1000).toISOString()} · {c('Expires', 'Vence')}: {new Date(context.data.decision.expires_at * 1000).toISOString()}</p>
      {context.data.decision.decision === 'DENY' && <p>DENIED BY POLICY — APPROVAL NOT PERMITTED</p>}
      {(context.data.decision.decision === 'REQUIRE_APPROVAL' || context.data.decision.economic_evidence_status !== 'VERIFIED') &&
        <p>OWNER APPROVAL DOES NOT VERIFY AVAILABLE FUNDS</p>}
      {review && <p>{c('Consent', 'Consentimiento')}: {review.approval_status} · {review.effective_status} · {review.financial_eligibility}</p>}
      {review?.approval_status === 'REVOKED' && <p>REVOKED — NO LONGER VALID</p>}
      <label>{c('Reason for rejection or revocation', 'Motivo de rechazo o revocación')}
        <input value={reason} onChange={(event) => setReason(event.target.value)} maxLength={500} />
      </label>
      {!review && <button type="button" className="button" disabled={busy || Date.now() / 1000 >= context.data.decision.expires_at}
        onClick={() => void act('OPEN')}>{c('Open review', 'Abrir revisión')}</button>}
      {review?.approval_status === 'PENDING_REVIEW' && <>
        <button type="button" className="button" disabled={busy || context.data.decision.decision === 'DENY' || Date.now() / 1000 >= review.expires_at}
          onClick={() => void act('APPROVE')}>{c('Record owner approval', 'Registrar aprobación')}</button>
        <button type="button" className="button" disabled={busy} onClick={() => void act('REJECT')}>
          {c('Reject', 'Rechazar')}</button>
      </>}
      {review?.approval_status === 'APPROVED' && <button type="button" className="button" disabled={busy}
        onClick={() => void act('REVOKE')}>{c('Revoke consent', 'Revocar consentimiento')}</button>}
      {eventHistory.data?.length ? <details><summary>{c('Signed history', 'Historial firmado')} ({eventHistory.data.length})</summary>
        {eventHistory.data.map((event) => <p key={event.event_id}>{event.action} · {event.actor_pubkey} · {new Date(event.occurred_at * 1000).toISOString()} · {event.reason}</p>)}
      </details> : null}
    </div>}
    {error && <p role="alert">{error}</p>}
    {notice && <p role="status">{notice}</p>}
  </section>;
}
