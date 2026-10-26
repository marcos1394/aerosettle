import { useCallback, useEffect, useState } from 'react';
import { useWallet } from '@solana/wallet-adapter-react';
import { Link } from 'react-router';
import { organizationMutationMessage, organizationReadMessage,
  type ConatusOrganization, type OrganizationAction, type OrganizationAgentMember,
  type OrganizationDelegation, type OrganizationInvitation, type OrganizationMember,
  type OrganizationMutationRequest, type OrganizationOverview,
} from '@aerosettle/marketplace-sdk';
// @ts-expect-error bs58 lacks bundled TypeScript declarations in this workspace
import bs58 from 'bs58';
import { api } from '../../app/api';
import { useCopy } from '../../app/i18n';
import './organizations.css';
import OrganizationGovernancePanel from './OrganizationGovernancePanel';

type Section = 'members' | 'agents' | 'invitations' | 'roles' | 'delegations' | 'audit-events';
const SECTIONS: Section[] = ['members', 'agents', 'invitations', 'roles', 'delegations', 'audit-events'];
const SECTION_PERMISSIONS: Record<Section, string> = { members: 'members.read', agents: 'agents.read_membership',
  invitations: 'members.read', roles: 'roles.read', delegations: 'delegations.read', 'audit-events': 'audit.read' };
const nextId = (prefix: string) => `${prefix}_${crypto.randomUUID().replaceAll('-', '')}`;

export default function OrganizationsPage() {
  const c = useCopy();
  const wallet = useWallet();
  const actor = wallet.publicKey?.toBase58() ?? '';
  const [list, setList] = useState<OrganizationOverview[]>([]);
  const [selectedId, setSelectedId] = useState('');
  const [detail, setDetail] = useState<OrganizationOverview | null>(null);
  const [section, setSection] = useState<Section>('members');
  const [sectionData, setSectionData] = useState<unknown>([]);
  const [name, setName] = useState('');
  const [slug, setSlug] = useState('');
  const [description, setDescription] = useState('');
  const [organizationType, setOrganizationType] = useState<'INDIVIDUAL_LED' | 'COLLECTIVE' | 'REGISTERED_ENTITY_CLAIMED'>('COLLECTIVE');
  const [representative, setRepresentative] = useState('');
  const [subject, setSubject] = useState('');
  const [role, setRole] = useState('MEMBER');
  const [delegate, setDelegate] = useState('');
  const [permission, setPermission] = useState('members.invite');
  const [scope, setScope] = useState('organization');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [revision, setRevision] = useState(0);

  const signedRead = useCallback(async (path: string) => {
    if (!wallet.signMessage || !actor) throw new Error('Owner wallet with message signing required');
    const at = Math.floor(Date.now() / 1000);
    const signature = await wallet.signMessage(organizationReadMessage(path, actor, at));
    if (wallet.publicKey?.toBase58() !== actor) throw new Error('Wallet changed during signature');
    return { 'X-Signer-Pubkey': actor, 'X-Timestamp': String(at), 'X-Signature': bs58.encode(signature) };
  }, [actor, wallet.signMessage]);

  useEffect(() => {
    setList([]); setDetail(null); setSectionData([]); setSelectedId(''); setError('');
  }, [actor]);

  useEffect(() => {
    let live = true;
    if (!actor || !wallet.signMessage) return () => { live = false; };
    void (async () => {
      try {
        const authHeaders = await signedRead('/v1/organizations');
        const items = (await api.listMyOrganizations({ authHeaders })).data;
        if (live) setList(items);
      } catch (cause) { if (live) setError(cause instanceof Error ? cause.message : String(cause)); }
    })();
    return () => { live = false; };
  }, [actor, revision, signedRead, wallet.signMessage]);

  useEffect(() => {
    let live = true;
    setDetail(null); setSectionData([]);
    if (!selectedId || !actor || !wallet.signMessage) return () => { live = false; };
    void (async () => {
      try {
        const path = `/v1/organizations/${selectedId}`;
        const authHeaders = await signedRead(path);
        const result = (await api.getOrganization(selectedId, { authHeaders })).data;
        if (live) setDetail(result);
        if (!result.permissions.includes(SECTION_PERMISSIONS[section])) {
          const first = SECTIONS.find(item => result.permissions.includes(SECTION_PERMISSIONS[item]));
          if (first && live) { setSection(first); return; }
        }
        if (result.permissions.includes(SECTION_PERMISSIONS[section]) && live) {
          const route = `${path}/${section}`;
          const scoped = await signedRead(route);
          const sectionResult = (await api.getOrganizationSection(selectedId, section, { authHeaders: scoped })).data;
          if (live) setSectionData(sectionResult);
        } else if (live) setSectionData(result.pending_invitations ?? []);
      } catch (cause) { if (live) setError(cause instanceof Error ? cause.message : String(cause)); }
    })();
    return () => { live = false; };
  }, [selectedId, section, actor, revision, signedRead, wallet.signMessage]);

  async function mutate(action: OrganizationAction, targetType: string, targetId: string,
                        payload: Record<string, unknown> = {}, org?: ConatusOrganization) {
    if (!wallet.signMessage || !actor) return;
    setBusy(true); setError('');
    try {
      const organizationId = org?.organization_id ?? nextId('org');
      const at = Math.floor(Date.now() / 1000);
      const body: OrganizationMutationRequest = {
        organization_id: organizationId, actor_pubkey: actor, target_type: targetType,
        target_id: action === 'CREATE' ? organizationId : targetId, action,
        role_id: action === 'CREATE' ? 'OWNER' : '', permission_scope: 'organization',
        payload, expected_version: org?.version ?? 0, issued_at: at, expires_at: at + 300,
        nonce: crypto.randomUUID(), idempotency_key: crypto.randomUUID(),
      };
      const path = action === 'CREATE' ? '/v1/organizations' : `/v1/organizations/${organizationId}/actions`;
      const signature = await wallet.signMessage(await organizationMutationMessage('POST', path, body));
      if (wallet.publicKey?.toBase58() !== actor) throw new Error('Wallet changed during signature');
      const options = { authHeaders: { 'X-Signer-Pubkey': actor, 'X-Timestamp': String(at),
        'X-Signature': bs58.encode(signature) } };
      if (action === 'CREATE') {
        await api.createOrganization(body, options);
        setSelectedId(organizationId); setName(''); setSlug(''); setDescription('');
      } else await api.applyOrganizationAction(organizationId, body, options);
      setRevision((n) => n + 1);
    } catch (cause) { setError(cause instanceof Error ? cause.message : String(cause)); }
    finally { setBusy(false); }
  }

  async function inviteAgent() {
    if (!detail) return;
    setBusy(true); setError('');
    try {
      const path = `/v1/organizations/agent-registration/${subject.trim()}`;
      const registration = (await api.getOrganizationAgentRegistration(subject.trim(),
        { authHeaders: await signedRead(path) })).data;
      await mutate('INVITE_AGENT', 'INVITATION', nextId('inv'), {
        agent_account: subject.trim(), registration,
        valid_from: Math.floor(Date.now() / 1000), expires_at: Math.floor(Date.now() / 1000) + 7*86400,
      }, detail.organization);
    } catch (cause) { setError(cause instanceof Error ? cause.message : String(cause)); setBusy(false); }
  }

  const org = detail?.organization;
  const can = (permission: string) => Boolean(detail?.permissions.includes(permission));
  const rows = Array.isArray(sectionData) ? sectionData as Array<Record<string, unknown>> : [];
  const roleCatalog = section === 'roles' && sectionData && typeof sectionData === 'object' &&
    'catalog' in sectionData ? (sectionData as { catalog: Record<string, string[]> }).catalog : {};
  const pending = detail?.pending_invitations ?? [];
  const visibleSections = SECTIONS.filter(item => can(SECTION_PERMISSIONS[item]));
  return <main className="organizations-page">
    <header className="org-hero">
      <p className="eyebrow">CONATUS / ORGANIZATIONS</p>
      <h1>{c('Organizations', 'Organizaciones')}</h1>
      <p>{c('Build a coordinated fleet with consent, limited roles and a verifiable administrative history.',
        'Coordina una flota con consentimiento, roles limitados e historial administrativo verificable.')}</p>
      <div className="org-safety">OFF-CHAIN ORGANIZATION · ADMINISTRATIVE PERMISSIONS ONLY · NO CUSTODY OR DEVICE SIGNING AUTHORITY</div>
    </header>
    {!actor || !wallet.signMessage ? <div className="panel" role="status">{c('Connect a wallet that can sign messages.',
      'Conecta una wallet capaz de firmar mensajes.')}</div> : <>
      {error && <div className="panel" role="alert">{error}</div>}
      <div className="org-layout">
        <aside className="org-list panel">
          <div className="section-heading"><h2>{c('My organizations', 'Mis organizaciones')}</h2><span>{list.length}</span></div>
          {list.map((item) => <button key={item.organization.organization_id} type="button"
            className={`org-list-item ${selectedId === item.organization.organization_id ? 'selected' : ''}`}
            onClick={() => setSelectedId(item.organization.organization_id)}>
            <strong>{item.organization.organization_name}</strong>
            <span>{item.organization.organization_type} · {item.organization.organization_status}</span>
            <small>{item.member_count ?? 0} {c('members', 'miembros')} · {item.agent_count ?? 0} {c('agents', 'agentes')}</small>
          </button>)}
          {!list.length && <p className="hint">{c('No accessible organizations yet.', 'Aún no tienes organizaciones accesibles.')}</p>}
          <div className="org-create">
            <h3>{c('Create organization', 'Crear organización')}</h3>
            <label>{c('Name', 'Nombre')}<input value={name} maxLength={120} onChange={(e) => setName(e.target.value)} /></label>
            <label>Slug<input value={slug} maxLength={64} onChange={(e) => setSlug(e.target.value.toLowerCase())} /></label>
            <label>{c('Description', 'Descripción')}<textarea value={description} maxLength={1000}
              onChange={(e) => setDescription(e.target.value)} /></label>
            <label>{c('Declared type', 'Tipo declarado')}<select value={organizationType}
              onChange={(e) => setOrganizationType(e.target.value as typeof organizationType)}>
              <option value="INDIVIDUAL_LED">INDIVIDUAL LED</option><option value="COLLECTIVE">COLLECTIVE</option>
              <option value="REGISTERED_ENTITY_CLAIMED">REGISTERED ENTITY CLAIMED</option></select></label>
            <label>{c('Declared representative wallet (optional)', 'Wallet de representante declarado (opcional)')}
              <input value={representative} onChange={(e) => setRepresentative(e.target.value)} /></label>
            <button className="button primary" disabled={busy || !name.trim() || !slug.trim()}
              onClick={() => void mutate('CREATE', 'ORGANIZATION', '', {
                owner_pubkey: actor, organization_name: name.trim(), organization_slug: slug.trim(),
                description: description.trim(), organization_type: organizationType, jurisdiction: 'UNDECLARED',
                legal_representative_pubkey: representative.trim() || null,
              })}>{c('Sign & create', 'Firmar y crear')}</button>
          </div>
        </aside>
        <div className="org-main">
          {!org ? <section className="panel"><h2>{c('Choose an organization', 'Elige una organización')}</h2>
            <p className="hint">{c('Administrative identity is separate from every agent owner.',
              'La identidad administrativa es independiente del propietario de cada agente.')}</p></section> : <>
            <section className="panel org-overview">
              <div className="section-heading"><div><p className="eyebrow">{org.organization_slug} · v{org.version}</p>
                <h2>{org.organization_name}</h2></div><strong>{org.organization_status}</strong></div>
              <p>{org.description || '—'}</p>
              <div className="org-facts"><span>{c('Owner', 'Titular')}<strong>{org.owner_pubkey}</strong></span>
                <span>{c('Representative', 'Representante')}<strong>{org.legal_representative_pubkey ?? '—'}</strong></span>
                <span>{c('Legal status', 'Estado legal')}<strong>{org.legal_entity_verification_status}</strong></span></div>
              <p className="hint">LEGAL REPRESENTATION NOT VERIFIED · {c('Agent ownership stays on-chain with each current owner.',
                'La propiedad on-chain de cada agente permanece con su titular actual.')}</p>
              {org.owner_pubkey === actor && <button className="button" disabled={busy}
                onClick={() => void mutate('UPDATE_METADATA', 'ORGANIZATION', org.organization_id,
                  { organization_status: org.organization_status === 'ACTIVE' ? 'SUSPENDED' : 'ACTIVE' }, org)}>
                {org.organization_status === 'ACTIVE' ? c('Suspend organization', 'Suspender organización') :
                  c('Resume organization', 'Reactivar organización')}</button>}
            </section>
            {org.organization_status === 'ACTIVE' && !pending.length &&
              <OrganizationGovernancePanel key={`${org.organization_id}:${actor}`} organizationId={org.organization_id}
                ownerPubkey={org.owner_pubkey} />}
            {pending.length > 0 && <section className="panel"><h3>{c('Invitations awaiting your consent', 'Invitaciones pendientes de tu consentimiento')}</h3>
              {pending.map((item: OrganizationInvitation) => <div className="org-row" key={item.invitation_id}>
                <span>{item.subject_type} · {item.subject_id} · {item.proposed_role}</span>
                <button className="button" disabled={busy} onClick={() => void mutate(
                  item.subject_type === 'AGENT' ? 'ACCEPT_AGENT' : 'ACCEPT_HUMAN',
                  'INVITATION', item.invitation_id,
                  item.subject_type === 'AGENT' ? { agent_account: item.subject_id,
                    registration_snapshot_hash: item.registration_snapshot_hash } : {}, org)}>
                  {c('Accept with wallet', 'Aceptar con wallet')}</button>
                {item.subject_type === 'HUMAN' && <button className="button" disabled={busy}
                  onClick={() => void mutate('DECLINE_HUMAN', 'INVITATION', item.invitation_id, {}, org)}>
                  {c('Decline', 'Rechazar')}</button>}
              </div>)}</section>}
            {visibleSections.length ? <>
              <nav className="org-tabs" aria-label={c('Organization sections', 'Secciones de organización')}>
                {visibleSections.map((item) => <button key={item} type="button" className={section === item ? 'active' : ''}
                  onClick={() => setSection(item)}>{item.replace('-', ' ')}</button>)}
              </nav>
              <section className="panel org-section">
                <div className="section-heading"><h3>{section.replace('-', ' ')}</h3><small>{rows.length || ' '}</small></div>
                {section === 'members' && <>
                  {rows.map((item) => { const member = item as unknown as OrganizationMember; return <div className="org-row" key={member.membership_id}>
                    <span><strong>{member.member_pubkey}</strong><small>{member.role_id} · {member.status}</small></span>
                    {member.role_id !== 'OWNER' && can('members.suspend') && member.status === 'ACTIVE' &&
                      <button className="button" disabled={busy} onClick={() => void mutate('SUSPEND_MEMBER', 'MEMBER', member.member_pubkey, {}, org)}>Suspend</button>}
                    {can('members.reinstate') && member.status === 'SUSPENDED' && <button className="button" disabled={busy}
                      onClick={() => void mutate('REINSTATE_MEMBER', 'MEMBER', member.member_pubkey, {}, org)}>Reinstate</button>}
                    {member.role_id !== 'OWNER' && can('members.remove') && <button className="button" disabled={busy}
                      onClick={() => void mutate('REMOVE_MEMBER', 'MEMBER', member.member_pubkey, {}, org)}>Remove</button>}
                  </div>; })}
                  {can('members.invite') && <div className="org-form"><h4>{c('Invite a wallet', 'Invitar wallet')}</h4>
                    <input placeholder={c('Wallet public key', 'Clave pública de wallet')} value={subject} onChange={(e) => setSubject(e.target.value)} />
                    <select value={role} onChange={(e) => setRole(e.target.value)}><option>MEMBER</option><option>VIEWER</option>
                      <option>AUDITOR</option><option>OPERATOR</option><option>ADMIN</option>
                      {org.legal_representative_pubkey === subject.trim() && <option>LEGAL_REPRESENTATIVE</option>}</select>
                    <button className="button primary" disabled={busy || !subject.trim()} onClick={() => void mutate(
                      'INVITE_HUMAN', 'INVITATION', nextId('inv'), { subject_pubkey: subject.trim(), role_id: role,
                        valid_from: Math.floor(Date.now()/1000), expires_at: Math.floor(Date.now()/1000)+7*86400 }, org)}>
                      {c('Sign invitation', 'Firmar invitación')}</button></div>}
                </>}
                {section === 'agents' && <>
                  {rows.map((item) => { const agent = item as unknown as OrganizationAgentMember; return <div className="org-row" key={agent.membership_id}>
                    <span><strong>{agent.agent_account}</strong><small>{agent.agent_id} · {agent.effective_status} ·
                      {c('On-chain owner', 'Titular on-chain')}: {agent.current_owner_pubkey ?? '—'}</small></span>
                    {can('agents.remove_membership') && agent.status === 'ACTIVE' && <button className="button"
                      disabled={busy} onClick={() => void mutate('REMOVE_AGENT', 'AGENT', agent.agent_account, {}, org)}>Remove</button>}
                  </div>; })}
                  {can('agents.invite') && <div className="org-form"><h4>{c('Invite a registered agent', 'Invitar un agente registrado')}</h4>
                    <input placeholder="AgentAccount pubkey" value={subject} onChange={(e) => setSubject(e.target.value)} />
                    <button className="button primary" disabled={busy || !subject.trim()} onClick={() => void inviteAgent()}>
                      {c('Verify identity & invite', 'Verificar identidad e invitar')}</button></div>}
                </>}
                {section === 'invitations' && rows.map((item) => { const invitation = item as unknown as OrganizationInvitation;
                  return <div className="org-row" key={invitation.invitation_id}><span>{invitation.subject_type} · {invitation.subject_id}</span>
                    <strong>{invitation.status}</strong></div>; })}
                {section === 'roles' && <>
                  <p className="hint">{c('Role names map to fixed administrative permissions. No financial rights are included.',
                    'Los roles corresponden a permisos administrativos fijos, sin derechos financieros.')}</p>
                  {Object.entries(roleCatalog).map(([roleName, permissions]) => <div className="org-row" key={roleName}>
                    <strong>{roleName}</strong><small>{permissions.join(' · ')}</small></div>)}
                  {can('roles.assign') && <div className="org-form"><input placeholder={c('Member wallet', 'Wallet de miembro')} value={subject}
                    onChange={(e) => setSubject(e.target.value)} /><select value={role} onChange={(e) => setRole(e.target.value)}>
                    <option>MEMBER</option><option>VIEWER</option><option>AUDITOR</option><option>OPERATOR</option><option>ADMIN</option></select>
                    <button className="button" disabled={busy || !subject.trim()} onClick={() => void mutate('ASSIGN_ROLE', 'MEMBER',
                      subject.trim(), { role_id: role }, org)}>{c('Assign role', 'Asignar rol')}</button>
                    <button className="button" disabled={busy || !subject.trim()} onClick={() => void mutate('REVOKE_ROLE', 'MEMBER',
                      subject.trim(), {}, org)}>{c('Revoke role', 'Revocar rol')}</button></div>}
                </>}
                {section === 'delegations' && <>
                  {rows.map((item) => { const delegation = item as unknown as OrganizationDelegation; return <div className="org-row" key={delegation.delegation_id}>
                    <span><strong>{delegation.permission}</strong><small>{delegation.delegator_pubkey} → {delegation.delegate_pubkey} ·
                      {delegation.resource_scope} · {delegation.status}</small></span>
                    {can('delegations.revoke') && delegation.status === 'ACTIVE' && <button className="button"
                      disabled={busy} onClick={() => void mutate('REVOKE_DELEGATION', 'DELEGATION', delegation.delegation_id, {}, org)}>
                      {c('Revoke', 'Revocar')}</button>}</div>; })}
                  {can('delegations.create') && <div className="org-form"><input placeholder={c('Delegate wallet', 'Wallet delegada')}
                    value={delegate} onChange={(e) => setDelegate(e.target.value)} />
                    <select value={permission} onChange={(e) => setPermission(e.target.value)}><option>members.invite</option>
                      <option>members.suspend</option><option>agents.invite</option><option>audit.read</option></select>
                    <input placeholder="organization or exact resource pubkey" value={scope} onChange={(e) => setScope(e.target.value)} />
                    <button className="button primary" disabled={busy || !delegate.trim() || !scope.trim()} onClick={() => void mutate(
                      'CREATE_DELEGATION', 'DELEGATION', nextId('del'), { delegate_pubkey: delegate.trim(), permission,
                        resource_scope: scope.trim(), valid_from: Math.floor(Date.now()/1000),
                        expires_at: Math.floor(Date.now()/1000)+86400 }, org)}>{c('Sign delegation', 'Firmar delegación')}</button></div>}
                </>}
                {section === 'audit-events' && rows.map((item) => <div className="org-row" key={String(item.event_id)}>
                  <span><strong>{String(item.event_type)}</strong><small>{String(item.actor_pubkey)} · {String(item.target_id)}</small></span>
                  <time>{new Date(Number(item.occurred_at)*1000).toLocaleString()}</time></div>)}
              </section>
            </> : <p className="hint">{org.organization_status === 'SUSPENDED' ?
              c('This organization is suspended. Only its owner may reactivate it.',
                'La organización está suspendida. Solo su titular puede reactivarla.') :
              c('Accept an invitation to access administrative sections.',
                'Acepta una invitación para acceder a las secciones administrativas.')}</p>}
          </>}
        </div>
      </div>
    </>}
    <p className="hint"><Link to="/app/agents">{c('Explore agents', 'Explorar agentes')}</Link> ·
      {c('Organization membership never grants access to private agent finances or device signing.',
        'La membresía organizacional nunca concede acceso a finanzas privadas ni a la firma de dispositivos.')}</p>
  </main>;
}
