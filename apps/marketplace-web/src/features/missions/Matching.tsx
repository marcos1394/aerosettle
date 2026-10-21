import { useCopy, useI18n } from '../../app/i18n';
import { useState } from 'react';
import { Link } from 'react-router';
import type { WorkOrder } from '@aerosettle/marketplace-sdk';
import { useConnection } from '@solana/wallet-adapter-react';
import { api, verifyMeta, verifyNetwork } from '../../app/api';
import { useResource } from '../../app/useResource';
import { short } from '../../app/config';
import { Capabilities, Empty, ResourceState } from '../../components/ui';
import ClaimMissionPanel from './ClaimMissionPanel';

export default function Matching({
  mission,
  initialAgent,
  onClaimed,
}: {
  mission: WorkOrder;
  initialAgent: string;
  onClaimed: () => void;
}) {
  const { t } = useI18n();
  const c = useCopy();

  const { connection } = useConnection();
  const [selected, setSelected] = useState(initialAgent);
  const resource = useResource(
    `matches:${mission.work_order_account}:${mission.status}`,
    async (signal) => {
      await verifyNetwork(connection, signal);
      const result = await api.getMatches(mission.work_order_account, signal);
      verifyMeta(result.meta);
      if (
        result.data.work_order.work_order_account !== mission.work_order_account
      )
        throw new Error('Matching de otra misión.');
      return result.data;
    }
  );
  const data = resource.data;
  const agent =
    data?.eligible_agents.find((a) => a.agent_account === selected) ?? null;
  const canClaim =
    mission.status === 'Open' &&
    data?.work_order.status === 'Open' &&
    data.work_order.discoverable;
  return (
    <section className="panel">
      <div className="section-heading">
        <h2>{c('Agent capability matching', 'Compatibilidad de agentes')}</h2>
        <span className="onchain-badge">
          {c('Protocol matcher', 'Motor de protocolo')}
        </span>
      </div>
      <p>
        {c(
          'Evaluates required hardware capabilities, operational status, protocol configuration, and execution window. Claiming re-verifies every condition on-chain.',
          'Evalúa las capacidades de hardware requeridas, el estado operativo, la configuración de protocolo y la ventana de ejecución. Al reclamar se revalidan todas las condiciones on-chain.'
        )}
      </p>
      <ResourceState {...resource} />
      {data && (
        <>
          <div className="matching-grid">
            <div>
              <h3>{t('Agentes elegibles')}</h3>
              {data.eligible_agents.length ? (
                <label>
                  {t('Seleccionar agente')}
                  <select
                    value={agent?.agent_account ?? ''}
                    onChange={(e) => setSelected(e.target.value)}
                  >
                    <option value="">{t('Elige un agente')}</option>
                    {data.eligible_agents.map((a) => (
                      <option value={a.agent_account} key={a.agent_account}>
                        {short(a.agent_id)} · {short(a.agent_account)}
                      </option>
                    ))}
                  </select>
                </label>
              ) : (
                <Empty title={t('Sin agentes elegibles')}>
                  {t('La evaluación actual no permite un Claim.')}
                </Empty>
              )}
              {agent && (
                <div className="selected-agent">
                  <Link to={`/app/agents/${agent.agent_account}`}>
                    {t('Ver agente')} {short(agent.agent_id)}
                  </Link>
                  <Capabilities mask={agent.capabilities} />
                  <p className="success-text">
                    {c(
                      'Verified compatible with all mission requirements',
                      'Compatible con todos los requisitos de la misión'
                    )}
                  </p>
                </div>
              )}
            </div>
            <div>
              <h3>{t('Evaluaciones incompatibles')}</h3>
              {data.evaluations
                .filter((e) => !e.eligible)
                .map((e) => (
                  <div key={e.agent_account} className="rejection-row">
                    <Link to={`/app/agents/${e.agent_account}`}>
                      {short(e.agent_account)}
                    </Link>
                    <span>{e.rejection?.code}</span>
                    {e.rejection?.missing_mask && (
                      <Capabilities mask={e.rejection.missing_mask} />
                    )}
                  </div>
                ))}
              {data.evaluations.every((e) => e.eligible) && (
                <p className="muted">{t('Sin rechazos en esta evaluación.')}</p>
              )}
            </div>
          </div>
          {canClaim ? (
            <ClaimMissionPanel
              agent={agent}
              mission={data.work_order}
              onClaimed={onClaimed}
            />
          ) : (
            <div className="notice">
              {t(
                'Claim no está disponible: la misión debe estar Open, ser descubrible y conservar su ventana de ejecución.'
              )}
            </div>
          )}
        </>
      )}
    </section>
  );
}
