import { useEffect, useRef, useState } from 'react';
import { useWallet } from '@solana/wallet-adapter-react';
import {
  MarketplaceApiError, budgetPolicyMutationMessage,
  type AgentBudgetPolicy, type AssetBudgetRule, type BudgetPolicyMutationControl,
  type BudgetPolicyMutationRequest,
} from '@aerosettle/marketplace-sdk';
// @ts-expect-error bs58 lacks bundled TypeScript declarations in this workspace
import bs58 from 'bs58';
import { api } from '../../app/api';
import { LOCALNET_GENESIS, MINT, PROGRAM_ID } from '../../app/config';
import { formatBaseUnits, ownerAuthHeaders } from '../../app/economic';
import { useCopy } from '../../app/i18n';
import { useResource } from '../../app/useResource';

const emptyRule = (): AssetBudgetRule => ({
  token_mint: MINT.toBase58(),
  max_per_operation_base_units_str: '0',
  max_daily_spend_base_units_str: '0',
  minimum_reserve_base_units_str: '0',
  enabled: true,
});

/** Owner-only policy administration. No payment, reserve allocation, or spend decision occurs here. */
export function AgentBudgetPolicyPanel({ account, owner }: { account: string; owner: string }) {
  const c = useCopy();
  const wallet = useWallet();
  const address = wallet.publicKey?.toBase58() ?? '';
  const identity = `${account}:${owner}:${address}`;
  const canRead = address === owner && Boolean(wallet.signMessage);
  const actionAbort = useRef(new AbortController());
  const [rules, setRules] = useState<AssetBudgetRule[]>([emptyRule()]);
  const [recipients, setRecipients] = useState('');
  const [validFrom, setValidFrom] = useState(() => Math.floor(Date.now() / 1000));
  const [expiresAt, setExpiresAt] = useState(() => Math.floor(Date.now() / 1000) + 30 * 86400);
  const [reason, setReason] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  useEffect(() => {
    const controller = new AbortController();
    actionAbort.current = controller;
    setRules([emptyRule()]);
    setRecipients('');
    setValidFrom(Math.floor(Date.now() / 1000));
    setExpiresAt(Math.floor(Date.now() / 1000) + 30 * 86400);
    setReason('');
    setBusy(false);
    setError('');
    setNotice('');
    return () => controller.abort();
  }, [identity]);

  const resource = useResource(`budget-policy:${identity}`, async (signal) => {
    if (!canRead || !wallet.signMessage) return null;
    const authHeaders = await ownerAuthHeaders(account, owner, {
      publicKey: address, signMessage: (message) => wallet.signMessage!(message),
    }, signal);
    let current;
    try {
      current = await api.getAgentBudgetPolicy(account, { authHeaders, signal });
    } catch (cause) {
      if (cause instanceof MarketplaceApiError && cause.status === 404)
        return { current: null, history: [] as AgentBudgetPolicy[] };
      throw cause;
    }
    const history = await api.listAgentBudgetPolicyHistory(account, { authHeaders, signal });
    return { current: current.data, history: history.data };
  });
  const data = canRead ? resource.data : null;
  const policy = data?.current;
  useEffect(() => {
    if (policy) {
      setRules(policy.asset_rules.map((rule) => ({ ...rule })));
      setRecipients(policy.allowed_recipients.join('\n'));
      setValidFrom(policy.valid_from);
      setExpiresAt(policy.expires_at);
    }
  }, [policy?.policy_id, policy?.version]);

  function editCurrent() {
    if (!policy) return;
    setRules(policy.asset_rules.map((rule) => ({ ...rule })));
    setRecipients(policy.allowed_recipients.join('\n'));
    setValidFrom(policy.valid_from);
    setExpiresAt(policy.expires_at);
    setReason('');
  }

  async function mutate(action: 'create' | 'update' | 'activate' | 'pause' | 'resume' | 'revoke') {
    if (!canRead || !wallet.signMessage || actionAbort.current.signal.aborted) return;
    setError(''); setNotice(''); setBusy(true);
    try {
      const control: BudgetPolicyMutationControl = {
        expected_version: policy?.version ?? 0,
        idempotency_key: crypto.randomUUID(),
        nonce: crypto.randomUUID(),
        ...(reason.trim() ? { revision_reason: reason.trim() } : {}),
      };
      const config: BudgetPolicyMutationRequest = {
        ...control, network: 'solana:localnet', genesis_hash: LOCALNET_GENESIS,
        program_id: PROGRAM_ID.toBase58(), asset_rules: rules,
        allowed_recipients: recipients.split(/\r?\n|,/).map((item) => item.trim()).filter(Boolean),
        valid_from: validFrom, expires_at: expiresAt,
      };
      const method = action === 'update' ? 'PUT' : 'POST';
      const path = `/v1/agents/${account}/budget-policy${['create', 'update'].includes(action) ? '' : `/${action}`}`;
      const body = action === 'create' || action === 'update' ? config : control;
      const timestamp = Math.floor(Date.now() / 1000);
      const challenge = await budgetPolicyMutationMessage(method, account, path, owner, timestamp, body);
      const signature = await wallet.signMessage(challenge);
      if (actionAbort.current.signal.aborted || wallet.publicKey?.toBase58() !== owner) return;
      const options = {
        authHeaders: {
          'X-Signer-Pubkey': owner, 'X-Timestamp': String(timestamp),
          'X-Signature': bs58.encode(signature),
        },
        signal: actionAbort.current.signal,
      };
      if (action === 'create') await api.createAgentBudgetPolicy(account, config, options);
      else if (action === 'update') await api.updateAgentBudgetPolicy(account, config, options);
      else if (action === 'activate') await api.activateAgentBudgetPolicy(account, control, options);
      else if (action === 'pause') await api.pauseAgentBudgetPolicy(account, control, options);
      else if (action === 'resume') await api.resumeAgentBudgetPolicy(account, control, options);
      else await api.revokeAgentBudgetPolicy(account, control, options);
      if (!actionAbort.current.signal.aborted) {
        setNotice(c('Policy version saved.', 'Versión de política guardada.'));
        resource.reload();
      }
    } catch (cause) {
      if (!actionAbort.current.signal.aborted) setError(cause instanceof Error ? cause.message : String(cause));
    } finally {
      if (!actionAbort.current.signal.aborted) setBusy(false);
    }
  }

  return <section className="panel" aria-label="Agent Budget Policy">
    <div className="section-heading"><h2>Agent Budget Policy</h2></div>
    <p className="hint"><strong>OFF-CHAIN POLICY — NO FUNDS LOCKED</strong> · {c(
      'Policy configuration does not transfer funds, reserve tokens, or authorize a spend. CON-28 will evaluate future proposals.',
      'Política off-chain: no se bloquean ni transfieren fondos. CON-28 evaluará las propuestas futuras.',
    )}</p>
    {!address && <p role="status">{c('Connect the owner wallet to view this policy.', 'Conecta la wallet propietaria para ver esta política.')}</p>}
    {address && address !== owner && <p role="status">{c('Only the current agent owner may view or edit this policy.', 'Solo el propietario actual del agente puede ver o editar esta política.')}</p>}
    {address === owner && !wallet.signMessage && <p role="status">{c('This wallet cannot sign policy requests.', 'Esta wallet no puede firmar solicitudes de política.')}</p>}
    {canRead && resource.loading && <p role="status">{c('Loading policy…', 'Cargando política…')}</p>}
    {canRead && resource.error && <p role="alert">{resource.error}</p>}
    {canRead && data && <>
      {policy ? <>
        <p><strong>{policy.effective_status}</strong> · v{policy.version} · {c('Owner', 'Propietario')}: {policy.owner_pubkey}</p>
        <p className="hint">{policy.network} · {policy.genesis_hash} · {policy.program_id} · SHA-256 {policy.policy_hash}</p>
        <p className="hint">{c('Valid from', 'Válida desde')}: {new Date(policy.valid_from * 1000).toISOString()} · {c('Expires', 'Vence')}: {new Date(policy.expires_at * 1000).toISOString()}</p>
        {policy.asset_rules.map((rule) => <p key={rule.token_mint}>{rule.enabled ? '●' : '○'} {rule.token_mint} · {c('Operation', 'Operación')}: {formatBaseUnits(rule.max_per_operation_base_units_str, rule.token_mint)} · {c('Daily', 'Diario')}: {formatBaseUnits(rule.max_daily_spend_base_units_str, rule.token_mint)} · {c('Reserve target', 'Objetivo de reserva')}: {formatBaseUnits(rule.minimum_reserve_base_units_str, rule.token_mint)}</p>)}
        <p>{c('Allowed recipients', 'Destinatarios permitidos')}: {policy.allowed_recipients.length ? policy.allowed_recipients.join(', ') : c('none', 'ninguno')}</p>
        {policy.reserve_comparison?.map((item) => <p className="hint" key={item.token_mint}>{item.token_mint} · {c('Accounting reserve', 'Reserva contable')}: {formatBaseUnits(item.accounting_reserved_base_units_str, item.token_mint)} · {c('Shortfall to policy target', 'Brecha frente al objetivo')}: {formatBaseUnits(item.reserve_shortfall_base_units_str, item.token_mint)} · {c('Ledger available', 'Disponible contable')}: {formatBaseUnits(item.ledger_available_balance_str, item.token_mint)} · {c('Accrued obligations', 'Obligaciones devengadas')}: {formatBaseUnits(item.ledger_accrued_obligations_base_units_str, item.token_mint)}</p>)}
        <details><summary>{c('Version history', 'Historial de versiones')} ({data.history.length})</summary>
          {data.history.map((item) => <p key={item.version}>v{item.version} · {item.action} · {item.status} · {new Date(item.created_at * 1000).toISOString()} · {item.created_by} · {item.policy_hash}</p>)}
        </details>
        <button type="button" className="button" onClick={editCurrent}>{c('Edit current rules', 'Editar reglas actuales')}</button>{' '}
        {policy.status === 'DRAFT' && <button type="button" className="button" disabled={busy} onClick={() => void mutate('activate')}>{c('Activate', 'Activar')}</button>}{' '}
        {policy.effective_status === 'ACTIVE' && <button type="button" className="button" disabled={busy} onClick={() => void mutate('pause')}>{c('Pause', 'Pausar')}</button>}{' '}
        {policy.status === 'PAUSED' && <button type="button" className="button" disabled={busy} onClick={() => void mutate('resume')}>{c('Resume', 'Reactivar')}</button>}{' '}
        {policy.status !== 'REVOKED' && <button type="button" className="button" disabled={busy} onClick={() => void mutate('revoke')}>{c('Revoke permanently', 'Revocar definitivamente')}</button>}
      </> : <p role="status">{c('No policy exists. New policies begin as drafts and grant no spending permission.', 'No existe política. Las nuevas políticas comienzan como borradores y no conceden permiso de gasto.')}</p>}
      {policy?.status !== 'REVOKED' && <div className="panel" style={{ marginTop: 14 }}>
        <h3>{policy ? c('New policy version', 'Nueva versión de política') : c('Create policy draft', 'Crear borrador de política')}</h3>
        {rules.map((rule, index) => <div key={index} className="kpi-grid" style={{ gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))' }}>
          {(['token_mint', 'max_per_operation_base_units_str', 'max_daily_spend_base_units_str', 'minimum_reserve_base_units_str'] as const).map((field) => <label key={field}>{field}
            <input value={rule[field]} onChange={(event) => setRules((current) => current.map((row, rowIndex) => rowIndex === index ? { ...row, [field]: event.target.value } : row))} />
          </label>)}
          <label>{c('Enabled', 'Habilitado')} <input type="checkbox" checked={rule.enabled} onChange={(event) => setRules((current) => current.map((row, rowIndex) => rowIndex === index ? { ...row, enabled: event.target.checked } : row))} /></label>
          <button type="button" className="button" onClick={() => setRules((current) => current.filter((_, rowIndex) => rowIndex !== index))}>{c('Remove asset', 'Quitar activo')}</button>
        </div>)}
        <button type="button" className="button" onClick={() => setRules((current) => [...current, { ...emptyRule(), token_mint: '' }])}>{c('Add asset', 'Agregar activo')}</button>
        <label>{c('Allowed recipient pubkeys, one per line', 'Destinatarios autorizados, uno por línea')}
          <textarea value={recipients} onChange={(event) => setRecipients(event.target.value)} rows={3} />
        </label>
        <label>{c('Valid from (Unix seconds)', 'Válida desde (segundos Unix)')} <input type="number" value={validFrom} onChange={(event) => setValidFrom(Number(event.target.value))} /></label>
        <label>{c('Expires at (Unix seconds)', 'Vence (segundos Unix)')} <input type="number" value={expiresAt} onChange={(event) => setExpiresAt(Number(event.target.value))} /></label>
        <label>{c('Revision reason (optional)', 'Motivo de revisión (opcional)')} <input value={reason} onChange={(event) => setReason(event.target.value)} /></label>
        <button type="button" className="button" disabled={busy || rules.length === 0} onClick={() => void mutate(policy ? 'update' : 'create')}>{busy ? c('Signing…', 'Firmando…') : policy ? c('Save new version', 'Guardar nueva versión') : c('Create draft', 'Crear borrador')}</button>
      </div>}
      {notice && <p role="status">{notice}</p>}
      {error && <p role="alert">{error}</p>}
    </>}
  </section>;
}
