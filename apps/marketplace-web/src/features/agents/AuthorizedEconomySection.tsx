import { useState } from 'react';
import { useWallet } from '@solana/wallet-adapter-react';
import type { Agent } from '@aerosettle/marketplace-sdk';
import { api } from '../../app/api';
import { useCopy } from '../../app/i18n';
import { useResource } from '../../app/useResource';
import { LiveSolvencyPanel } from './LiveSolvencyPanel';

/** Public registry discovery followed by an explicit owner-authorized private read. */
export function AuthorizedEconomySection({ heading, panelTitle }: {
  heading: string; panelTitle?: string;
}) {
  const c = useCopy();
  const { publicKey } = useWallet();
  const wallet = publicKey?.toBase58() ?? '';
  const [selected, setSelected] = useState('');
  const resource = useResource(`owned-economy:${wallet}`, async (signal) => {
    if (!wallet) return { agents: [] as Agent[], complete: true };
    const agents: Agent[] = [];
    let cursor: string | undefined;
    let complete = false;
    for (let pageNumber = 0; pageNumber < 5; pageNumber += 1) {
      const page = await api.listAgents({ limit: 100, cursor }, signal);
      agents.push(...page.data.filter((row) => row.owner === wallet));
      if (!page.page.next_cursor) { complete = true; break; }
      cursor = page.page.next_cursor;
    }
    return { agents, complete };
  });
  const agents = resource.data?.agents ?? [];
  const chosen = agents.find((item) => item.agent_account === selected) ?? agents[0];

  return <section className="panel" aria-label={heading}>
    <div className="section-heading"><h2>{heading}</h2></div>
    <p className="hint">AUTHORIZED FLEET SCOPE · {c('Only registry agents owned by the connected wallet are eligible for private reads. This is not a network-wide total.', 'Solo los agentes del registro pertenecientes a la wallet conectada pueden consultarse en privado. Esto no es un total de la red.')}</p>
    {!wallet && <p role="status">{c('Wallet disconnected. Connect the owner wallet to discover accessible agents.', 'Wallet desconectada. Conecta la wallet propietaria para descubrir agentes accesibles.')}</p>}
    {wallet && resource.loading && <p role="status">{c('Loading owned agents…', 'Cargando agentes propios…')}</p>}
    {wallet && resource.error && <p role="alert">{c('Agent registry unavailable: ', 'Registro de agentes no disponible: ')}{resource.error}</p>}
    {wallet && !resource.loading && !resource.error && agents.length === 0 && <p role="status">INSUFFICIENT_DATA · {c('No registered agents owned by this wallet in the queried scope.', 'No hay agentes registrados de esta wallet en el alcance consultado.')}</p>}
    {wallet && !resource.loading && !resource.error && agents.length > 0 && <>
      <p>{c('Owned agents in queried registry scope', 'Agentes propios en el alcance consultado')}: {agents.length}{resource.data?.complete ? '' : ' · PARTIAL REGISTRY PAGE SCOPE'}</p>
      <label>{c('Select agent', 'Seleccionar agente')}
        <select value={chosen.agent_account} onChange={(event) => setSelected(event.target.value)}>
          {agents.map((item) => <option key={item.agent_account} value={item.agent_account}>{item.agent_account}</option>)}
        </select>
      </label>
      <LiveSolvencyPanel key={`${wallet}:${chosen.agent_account}`} account={chosen.agent_account}
        owner={String(chosen.owner)} title={panelTitle} />
    </>}
  </section>;
}
