import { useCallback, useEffect, useState } from 'react';
import { useWallet } from '@solana/wallet-adapter-react';
import { governanceMutationMessage, organizationReadMessage,
  type GovernanceAction, type GovernanceAuditEvent, type GovernanceDispute,
  type GovernanceMutationRequest, type GovernanceOverview, type GovernanceProposal,
  type OrganizationBylaws, type OrganizationDistributionPolicy, type DistributionSimulation,
} from '@aerosettle/marketplace-sdk';
// @ts-expect-error bs58 lacks bundled TypeScript declarations in this workspace
import bs58 from 'bs58';
import { api } from '../../app/api';
import { useCopy } from '../../app/i18n';

const nextId = (prefix: string) => `${prefix}_${crypto.randomUUID().replaceAll('-', '')}`;
const initialRules = {
  title: 'Organization charter', purpose: 'Administrative governance only',
  eligible_voter_roles: ['OWNER', 'MEMBER'], proposal_roles: ['OWNER', 'MEMBER'],
  proposal_permissions: ['BYLAWS_AMENDMENT', 'MEMBERSHIP_RULE_CHANGE', 'OPERATIONAL_POLICY',
    'RESOURCE_ALLOCATION_PROPOSAL', 'ECONOMIC_DISTRIBUTION_POLICY', 'RESERVE_POLICY_PROPOSAL',
    'DISPUTE_RESOLUTION', 'OTHER_NON_FINANCIAL'], distribution_policy_id: null,
  quorum_bps: 5000, approval_threshold_bps: 5001, voting_period_seconds: 86400,
  minimum_voting_period_seconds: 60, dispute_window_seconds: 86400,
  vote_weighting_rule: 'ONE_ELIGIBLE_WALLET_ONE_VOTE',
};

export default function OrganizationGovernancePanel({ organizationId, ownerPubkey }:
  { organizationId: string; ownerPubkey: string }) {
  const c = useCopy();
  const wallet = useWallet();
  const actor = wallet.publicKey?.toBase58() ?? '';
  const [overview, setOverview] = useState<GovernanceOverview | null>(null);
  const [proposals, setProposals] = useState<GovernanceProposal[]>([]);
  const [bylawsVersions, setBylawsVersions] = useState<OrganizationBylaws[]>([]);
  const [disputes, setDisputes] = useState<GovernanceDispute[]>([]);
  const [policies, setPolicies] = useState<OrganizationDistributionPolicy[]>([]);
  const [simulations, setSimulations] = useState<DistributionSimulation[]>([]);
  const [audit, setAudit] = useState<GovernanceAuditEvent[]>([]);
  const [rulesJson, setRulesJson] = useState(JSON.stringify(initialRules, null, 2));
  const [proposalType, setProposalType] = useState('OTHER_NON_FINANCIAL');
  const [title, setTitle] = useState('');
  const [description, setDescription] = useState('');
  const [proposalPayload, setProposalPayload] = useState('{}');
  const [poolAmount, setPoolAmount] = useState('1000');
  const [activeTab, setActiveTab] = useState<'proposals' | 'agreements' | 'disputes' | 'audit'>('proposals');
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const [revision, setRevision] = useState(0);
  const [clock, setClock] = useState(() => Math.floor(Date.now()/1000));

  useEffect(() => {
    const timer = window.setInterval(() => setClock(Math.floor(Date.now()/1000)), 30000);
    return () => window.clearInterval(timer);
  }, []);

  const signedRead = useCallback(async (path: string) => {
    if (!wallet.signMessage || !actor) throw new Error('Wallet message signing required');
    const at = Math.floor(Date.now() / 1000);
    const signature = await wallet.signMessage(organizationReadMessage(path, actor, at));
    if (wallet.publicKey?.toBase58() !== actor) throw new Error('Wallet changed during signature');
    return { 'X-Signer-Pubkey': actor, 'X-Timestamp': String(at), 'X-Signature': bs58.encode(signature) };
  }, [actor, wallet.publicKey, wallet.signMessage]);

  useEffect(() => {
    setOverview(null); setProposals([]); setBylawsVersions([]); setDisputes([]); setPolicies([]); setSimulations([]); setAudit([]);
    setError('');
  }, [organizationId, actor]);

  useEffect(() => {
    let live = true;
    if (!organizationId || !actor || !wallet.signMessage) return () => { live = false; };
    void (async () => {
      try {
        const base = `/v1/organizations/${organizationId}/governance`;
        const get = async <T,>(section: '' | 'bylaws' | 'proposals' | 'disputes' | 'distributions' | 'audit-events') =>
          (await api.getGovernanceSection<T>(organizationId, section,
            { authHeaders: await signedRead(`${base}${section ? `/${section}` : ''}`) })).data;
        const summary = await get<GovernanceOverview>('');
        const versions = await get<OrganizationBylaws[]>('bylaws');
        const proposalRows = await get<GovernanceProposal[]>('proposals');
        const disputeRows = await get<GovernanceDispute[]>('disputes');
        const distributions = await get<{ policies: OrganizationDistributionPolicy[]; simulations: DistributionSimulation[] }>('distributions');
        let events: GovernanceAuditEvent[] = [];
        try { events = await get<GovernanceAuditEvent[]>('audit-events'); } catch { /* Audit role is narrower. */ }
        if (live) {
          setOverview(summary); setBylawsVersions(versions); setProposals(proposalRows); setDisputes(disputeRows);
          setPolicies(distributions.policies); setSimulations(distributions.simulations); setAudit(events);
        }
      } catch (cause) { if (live) setError(cause instanceof Error ? cause.message : String(cause)); }
    })();
    return () => { live = false; };
  }, [organizationId, actor, revision, signedRead, wallet.signMessage]);

  async function act(action: GovernanceAction, proposal?: GovernanceProposal, payload: Record<string, unknown> = {}) {
    if (!wallet.signMessage || !overview || !actor) return;
    setBusy(true); setError('');
    try {
      const now = Math.floor(Date.now() / 1000);
      const proposalScoped = ['CAST_VOTE', 'CLOSE_VOTING', 'OPEN_DISPUTE', 'RESOLVE_DISPUTE',
        'ADOPT_DISTRIBUTION_POLICY'].includes(action);
      const bylaws = overview.current_bylaws;
      const body: GovernanceMutationRequest = {
        organization_id: organizationId,
        proposal_id: action === 'CREATE_PROPOSAL' ? nextId('gp') : proposal?.proposal_id ?? '',
        actor_pubkey: actor, action,
        bylaws_version: proposalScoped && proposal ? proposal.bylaws_version : bylaws?.version ?? 0,
        bylaws_hash: proposalScoped && proposal ? proposal.bylaws_hash : bylaws?.bylaws_hash ?? '',
        electorate_snapshot_hash: (proposalScoped || action === 'AMEND_BYLAWS') && proposal ?
          proposal.electorate_snapshot_hash : '',
        payload, expected_version: overview.governance_version,
        issued_at: now, expires_at: now + 300,
        nonce: crypto.randomUUID(), idempotency_key: crypto.randomUUID(),
      };
      const path = `/v1/organizations/${organizationId}/governance/actions`;
      const signature = await wallet.signMessage(await governanceMutationMessage('POST', path, body));
      if (wallet.publicKey?.toBase58() !== actor) throw new Error('Wallet changed during signature');
      await api.applyGovernanceAction(organizationId, body, { authHeaders: {
        'X-Signer-Pubkey': actor, 'X-Timestamp': String(now), 'X-Signature': bs58.encode(signature),
      } });
      setRevision(value => value + 1);
      if (action === 'CREATE_PROPOSAL') { setTitle(''); setDescription(''); setProposalPayload('{}'); }
    } catch (cause) { setError(cause instanceof Error ? cause.message : String(cause)); }
    finally { setBusy(false); }
  }

  const current = overview?.current_bylaws;
  const visibleProposalType = current?.proposal_permissions.includes(proposalType) ? proposalType :
    current?.proposal_permissions[0] ?? proposalType;
  const isOwner = ownerPubkey === actor;
  const decisionReady = (proposal: GovernanceProposal) => {
    const source = bylawsVersions.find(item => item.bylaws_hash === proposal.bylaws_hash);
    return Boolean(source && proposal.resolved_at !== null &&
      clock >= proposal.resolved_at + source.dispute_window_seconds);
  };
  return <section className="panel org-governance">
    <div className="section-heading"><div><p className="eyebrow">OFF-CHAIN GOVERNANCE</p>
      <h2>{c('Collective decisions', 'Decisiones colectivas')}</h2></div>
      <strong>v{overview?.governance_version ?? '—'}</strong></div>
    <p className="hint">COLLECTIVE DECISION — NO FINANCIAL EXECUTION · LEGAL STATUS NOT VERIFIED</p>
    {error && <p role="alert" className="org-gov-error">{error}</p>}
    <div className="org-gov-rules">
      <h3>{c('Charter & electorate', 'Estatutos y electorado')}</h3>
      {current ? <p>{current.title} · v{current.version} · {c('Quorum', 'Quórum')} {current.quorum_bps / 100}% ·
        {c('Approval', 'Aprobación')} {current.approval_threshold_bps / 100}% ·
        {c('One eligible wallet, one vote', 'Una wallet elegible, un voto')}</p> :
        <p className="hint">{c('The owner must sign initial bylaws before proposals can open.',
          'El titular debe firmar los estatutos iniciales antes de abrir propuestas.')}</p>}
      {isOwner && !current && <div className="org-form"><label>{c('Initial bylaws JSON', 'Estatutos iniciales JSON')}
        <textarea value={rulesJson} onChange={event => setRulesJson(event.target.value)} rows={8} /></label>
        <button className="button primary" disabled={busy} onClick={() => {
          try { void act('CREATE_BYLAWS', undefined, { bylaws: JSON.parse(rulesJson) as Record<string, unknown> }); }
          catch (cause) { setError(cause instanceof Error ? cause.message : String(cause)); }
        }}>{c('Sign bylaws', 'Firmar estatutos')}</button></div>}
    </div>
    <nav className="org-tabs" aria-label={c('Governance sections', 'Secciones de gobernanza')}>
      {(['proposals', 'agreements', 'disputes', 'audit'] as const).map(tab =>
        <button key={tab} type="button" className={activeTab === tab ? 'active' : ''}
          onClick={() => setActiveTab(tab)}>{tab === 'proposals' ? c('Proposals', 'Propuestas') :
            tab === 'agreements' ? c('Economic agreements', 'Acuerdos económicos') :
            tab === 'disputes' ? c('Disputes', 'Disputas') : c('Audit', 'Auditoría')}</button>)}
    </nav>
    {activeTab === 'proposals' && <div className="org-gov-board">
      {proposals.map(proposal => <article className="org-gov-card" key={proposal.proposal_id}>
        <div className="section-heading"><h3>{proposal.title}</h3><strong>{proposal.status}</strong></div>
        <p>{proposal.description}</p><small>{proposal.proposal_type} · {proposal.proposal_id}</small>
        <p>{c('Voting progress', 'Progreso de votación')}: {proposal.vote_count ?? 0}/{Object.keys(proposal.electorate).length} ·
          {c('Deadline', 'Cierre')}: {proposal.voting_ends_at ? new Date(proposal.voting_ends_at*1000).toLocaleString() : '—'}</p>
        {proposal.tally && <p>{c('Yes', 'Sí')} {proposal.tally.yes_weight} · No {proposal.tally.no_weight} ·
          {c('Abstain', 'Abstención')} {proposal.tally.abstain_weight} ·
          {c('Quorum met', 'Quórum alcanzado')}: {String(proposal.tally.quorum_met)}</p>}
        <div className="org-gov-actions">
          {proposal.status === 'DRAFT' && (isOwner || proposal.created_by === actor) &&
            <button className="button" disabled={busy} onClick={() => void act('OPEN_VOTING', proposal)}>
              {c('Open voting', 'Abrir votación')}</button>}
          {proposal.status === 'OPEN' && proposal.electorate[actor] && !proposal.my_vote &&
            (['YES', 'NO', 'ABSTAIN'] as const).map(choice =>
              <button className="button" key={choice} disabled={busy || clock >= (proposal.voting_ends_at ?? 0)}
                onClick={() => void act('CAST_VOTE', proposal, { choice })}>{choice === 'YES' ? c('Yes', 'Sí') :
                  choice === 'NO' ? 'No' : c('Abstain', 'Abstenerse')}</button>)}
          {proposal.status === 'OPEN' && isOwner && clock >= (proposal.voting_ends_at ?? Infinity) &&
            <button className="button" disabled={busy} onClick={() => void act('CLOSE_VOTING', proposal)}>
              {c('Close & tally', 'Cerrar y contabilizar')}</button>}
          {['ACCEPTED', 'REJECTED'].includes(proposal.status) && proposal.electorate[actor] &&
            <button className="button" disabled={busy} onClick={() => void act('OPEN_DISPUTE', proposal,
              { dispute_id: nextId('gd'), reason_code: 'PROCEDURAL', evidence_refs: [] })}>
              {c('Open procedural dispute', 'Abrir disputa procesal')}</button>}
          {proposal.status === 'ACCEPTED' && proposal.proposal_type === 'ECONOMIC_DISTRIBUTION_POLICY' &&
            proposal.resolution_status === 'FINAL' && !proposal.consumed && isOwner && decisionReady(proposal) &&
            <button className="button" disabled={busy} onClick={() => void act('ADOPT_DISTRIBUTION_POLICY', proposal,
              { distribution_policy_id: nextId('gpol') })}>{c('Record agreement', 'Registrar acuerdo')}</button>}
          {proposal.status === 'ACCEPTED' && proposal.proposal_type === 'BYLAWS_AMENDMENT' &&
            proposal.resolution_status === 'FINAL' && !proposal.consumed && isOwner && decisionReady(proposal) &&
            <button className="button" disabled={busy} onClick={() => void act('AMEND_BYLAWS', proposal,
              { bylaws: proposal.proposal_payload, approved_proposal_id: proposal.proposal_id })}>
              {c('Apply approved charter', 'Aplicar estatutos aprobados')}</button>}
        </div>
      </article>)}
      {!proposals.length && <p className="hint">{c('No proposals recorded.', 'No hay propuestas registradas.')}</p>}
      {current && <div className="org-form"><h3>{c('Create proposal', 'Crear propuesta')}</h3>
        <select value={visibleProposalType} onChange={event => setProposalType(event.target.value)}>
          {['OTHER_NON_FINANCIAL', 'OPERATIONAL_POLICY', 'MEMBERSHIP_RULE_CHANGE',
            'BYLAWS_AMENDMENT', 'ECONOMIC_DISTRIBUTION_POLICY', 'RESOURCE_ALLOCATION_PROPOSAL',
            'RESERVE_POLICY_PROPOSAL', 'DISPUTE_RESOLUTION'].filter(value => current.proposal_permissions.includes(value))
            .map(value => <option key={value}>{value}</option>)}
        </select>
        <input placeholder={c('Proposal title', 'Título de propuesta')} value={title} onChange={event => setTitle(event.target.value)} />
        <textarea placeholder={c('Description', 'Descripción')} value={description}
          onChange={event => setDescription(event.target.value)} />
        <label>{c('Declarative payload JSON', 'Contenido declarativo JSON')}
          <textarea value={proposalPayload} onChange={event => setProposalPayload(event.target.value)} rows={5} /></label>
        <button className="button primary" disabled={busy || !title.trim()} onClick={() => {
          try { void act('CREATE_PROPOSAL', undefined, { proposal_type: visibleProposalType, title: title.trim(),
            description, proposal_payload: JSON.parse(proposalPayload) as Record<string, unknown>, author_agent_account: null }); }
          catch (cause) { setError(cause instanceof Error ? cause.message : String(cause)); }
        }}>{c('Sign proposal', 'Firmar propuesta')}</button>
      </div>}
    </div>}
    {activeTab === 'agreements' && <div className="org-gov-board">
      <p className="hint">HYPOTHETICAL DISTRIBUTION · {c('No participant funds are pooled or transferred.',
        'No se agrupan ni transfieren fondos de participantes.')}</p>
      {policies.map(policy => <article className="org-gov-card" key={policy.distribution_policy_id}>
        <h3>{policy.distribution_policy_id}</h3><p>{policy.mint} · {c('Reserve', 'Reserva')} {policy.reserve_share_bps/100}%</p>
        {Object.entries(policy.participant_shares_bps).map(([participant, share]) =>
          <p key={participant}>{participant}: {share/100}%</p>)}
        <div className="org-form"><input type="number" min="0" max={Number.MAX_SAFE_INTEGER} value={poolAmount}
          onChange={event => setPoolAmount(event.target.value)} />
          <button className="button" disabled={busy || !Number.isSafeInteger(Number(poolAmount))} onClick={() =>
            void act('SIMULATE_DISTRIBUTION', undefined, { distribution_policy_id: policy.distribution_policy_id,
              hypothetical_pool: { organization_id: organizationId, mint: policy.mint,
                amount_base_units: Number(poolAmount), provenance: 'SYNTHETIC_POOL' }, assumptions: {} })}>
            {c('Simulate only', 'Solo simular')}</button></div>
      </article>)}
      {simulations.map((simulation, index) => <div className="org-gov-card" key={`${simulation.distribution_policy_id}-${index}`}>
        <strong>HYPOTHETICAL DISTRIBUTION</strong><p>{simulation.pool_amount_base_units} ·
          {c('Reserve', 'Reserva')} {simulation.reserve_base_units}</p>
        {Object.entries(simulation.participant_allocations_base_units).map(([participant, amount]) =>
          <p key={participant}>{participant}: {amount}</p>)}
        <small>{c('No funds transferred', 'No se transfirieron fondos')}</small></div>)}
    </div>}
    {activeTab === 'disputes' && <div className="org-gov-board">
      {disputes.map(dispute => <article className="org-gov-card" key={dispute.dispute_id}>
        <div className="section-heading"><h3>{dispute.reason_code}</h3><strong>{dispute.status}</strong></div>
        <p>{dispute.proposal_id} · {dispute.opened_by}</p>
        <small>{dispute.evidence_refs.join(' · ') || c('No evidence references', 'Sin referencias de evidencia')}</small>
        {isOwner && dispute.status === 'OPEN' && <button className="button" disabled={busy}
          onClick={() => void act('RESOLVE_DISPUTE', proposals.find(item => item.proposal_id === dispute.proposal_id),
            { dispute_id: dispute.dispute_id, resolution: 'REFER_EXTERNAL' })}>
          {c('Refer for external review', 'Remitir a revisión externa')}</button>}
      </article>)}
      {!disputes.length && <p className="hint">{c('No disputes recorded.', 'No hay disputas registradas.')}</p>}
    </div>}
    {activeTab === 'audit' && <div className="org-gov-board">
      {audit.map(event => <div className="org-row" key={event.event_id}><span><strong>{event.action}</strong>
        <small>{event.actor_pubkey} · {event.event_id}</small></span>
        <time>{new Date(event.occurred_at*1000).toLocaleString()}</time></div>)}
      {!audit.length && <p className="hint">{c('Audit history requires an authorized role.',
        'El historial requiere un rol autorizado.')}</p>}
    </div>}
  </section>;
}
