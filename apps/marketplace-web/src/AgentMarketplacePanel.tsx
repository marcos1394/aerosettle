import { useEffect, useState } from 'react';
import { useConnection } from '@solana/wallet-adapter-react';

import {
  MarketplaceClient,
  type Agent,
  type WorkOrder,
  type MatchResult,
} from '@aerosettle/marketplace-sdk';

import {
  LOCALNET_GENESIS,
  PROGRAM_ID,
} from '@aerosettle/transaction-sdk';

import './agent-marketplace.css';

const api = new MarketplaceClient({
  baseUrl: window.location.origin,
  timeoutMs: 15000,
});

// Bits oficiales de Capability en AeroSettle Protocol v1.
const CAPABILITIES = [
  [0, 'Movilidad aérea'],
  [1, 'Movilidad terrestre'],
  [2, 'Visión RGB'],
  [3, 'Visión térmica'],
  [4, 'Visión multiespectral'],
  [5, 'GPS'],
  [6, 'RTK GPS'],
  [7, 'Sensores ambientales'],
  [8, 'Detección de objetos'],
  [9, 'Inferencia Edge'],
  [10, 'Manipulación física'],
  [11, 'Transporte'],
  [12, 'Suministro energético'],
  [13, 'Cadena de frío'],
  [14, 'Cartografía'],
  [15, 'Telemetría'],
] as const;

type ActivityFilter = 'all' | 'active' | 'inactive';

function abbreviate(value: string) {
  return value.length > 22
    ? `${value.slice(0, 10)}…${value.slice(-8)}`
    : value;
}

function capabilityNames(mask: string): string[] {
  const bits = BigInt(mask);

  return CAPABILITIES
    .filter(([index]) => (bits & (1n << BigInt(index))) !== 0n)
    .map(([, name]) => name);
}

function message(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

export default function AgentMarketplacePanel() {
  const { connection } = useConnection();

  const [agents, setAgents] = useState<Agent[]>([]);
  const [missions, setMissions] = useState<WorkOrder[]>([]);
  const [selectedAgent, setSelectedAgent] = useState('');
  const [selectedMission, setSelectedMission] = useState('');

  const [activity, setActivity] = useState<ActivityFilter>('all');
  const [capability, setCapability] = useState('all');
  const [search, setSearch] = useState('');

  const [nextCursor, setNextCursor] = useState<string | null>(null);
  const [totalAgents, setTotalAgents] = useState(0);
  const [chainTime, setChainTime] = useState<number | null>(null);

  const [matching, setMatching] = useState<MatchResult | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadingMore, setLoadingMore] = useState(false);
  const [loadingMatch, setLoadingMatch] = useState(false);
  const [error, setError] = useState('');
  const [matchError, setMatchError] = useState('');
  const [refresh, setRefresh] = useState(0);

  useEffect(() => {
    const controller = new AbortController();
    const signal = controller.signal;

    async function load() {
      setLoading(true);
      setError('');
      setAgents([]);
      setNextCursor(null);
      setMatching(null);

      try {
        const active =
          activity === 'all'
            ? undefined
            : activity === 'active';

        const capabilitiesAll =
          capability === 'all' ? undefined : capability;

        const [genesis, health, agentPage, missionPage] =
          await Promise.all([
            connection.getGenesisHash(),
            api.health(signal),
            api.listAgents(
              {
                limit: 24,
                active,
                capabilitiesAll,
              },
              signal
            ),
            api.listWorkOrders(
              {
                status: 'Open',
                discoverable: true,
                limit: 50,
              },
              signal
            ),
          ]);

        if (signal.aborted) return;

        if (
          genesis !== LOCALNET_GENESIS ||
          health.genesis !== LOCALNET_GENESIS ||
          agentPage.meta.program_id !== PROGRAM_ID.toBase58() ||
          missionPage.meta.program_id !== PROGRAM_ID.toBase58()
        ) {
          throw new Error(
            'Marketplace API y Solana RPC no coinciden con Localnet.'
          );
        }

        setAgents(agentPage.data);
        setTotalAgents(agentPage.total_count);
        setNextCursor(agentPage.page.next_cursor);
        setChainTime(agentPage.meta.chain_now_unix);

        setMissions(missionPage.data);

        setSelectedMission(previous =>
          missionPage.data.some(
            order => order.work_order_account === previous
          )
            ? previous
            : missionPage.data[0]?.work_order_account ?? ''
        );

        setSelectedAgent(previous =>
          agentPage.data.some(
            agent => agent.agent_account === previous
          )
            ? previous
            : agentPage.data[0]?.agent_account ?? ''
        );
      } catch (cause) {
        if (!signal.aborted) setError(message(cause));
      } finally {
        if (!signal.aborted) setLoading(false);
      }
    }

    void load();

    return () => controller.abort();
  }, [connection, activity, capability, refresh]);

  useEffect(() => {
    const controller = new AbortController();
    const signal = controller.signal;

    setMatching(null);
    setMatchError('');

    if (!selectedMission) {
      setLoadingMatch(false);
      return () => controller.abort();
    }

    async function evaluate() {
      setLoadingMatch(true);

      try {
        const result = await api.getMatches(
          selectedMission,
          signal
        );

        if (signal.aborted) return;

        if (
          result.meta.program_id !== PROGRAM_ID.toBase58() ||
          result.data.work_order.work_order_account !== selectedMission
        ) {
          throw new Error('Respuesta de matching incompatible.');
        }

        setMatching(result.data);
      } catch (cause) {
        if (!signal.aborted) setMatchError(message(cause));
      } finally {
        if (!signal.aborted) setLoadingMatch(false);
      }
    }

    void evaluate();

    return () => controller.abort();
  }, [selectedMission, refresh]);

  async function loadMore() {
    if (!nextCursor || loadingMore || loading) return;

    setLoadingMore(true);
    setError('');

    try {
      const result = await api.listAgents({
        limit: 24,
        cursor: nextCursor,
        active:
          activity === 'all'
            ? undefined
            : activity === 'active',
        capabilitiesAll:
          capability === 'all' ? undefined : capability,
      });

      if (result.meta.program_id !== PROGRAM_ID.toBase58()) {
        throw new Error('Programa inesperado en la paginación.');
      }

      setAgents(previous => {
        const known = new Set(
          previous.map(agent => agent.agent_account)
        );

        return [
          ...previous,
          ...result.data.filter(
            agent => !known.has(agent.agent_account)
          ),
        ];
      });

      setNextCursor(result.page.next_cursor);
      setTotalAgents(result.total_count);
    } catch (cause) {
      setError(message(cause));
    } finally {
      setLoadingMore(false);
    }
  }

  const visible = agents.filter(agent => {
    const needle = search.trim().toLowerCase();

    return (
      !needle ||
      agent.agent_account.toLowerCase().includes(needle) ||
      agent.agent_id.toLowerCase().includes(needle)
    );
  });

  const currentAgent =
    agents.find(agent => agent.agent_account === selectedAgent);

  const currentEvaluation =
    matching?.evaluations.find(
      item => item.agent_account === selectedAgent
    );

  const eligibleCount = matching?.eligible_agents.length ?? 0;

  return (
    <section className="agent-marketplace">
      <div className="agent-marketplace-eyebrow">
        AEROSETTLE / AGENT NETWORK / PROTOCOL V1
      </div>

      <div className="agent-marketplace-heading">
        <div>
          <h2>Autonomous Agent Marketplace</h2>
          <p>
            Identidades verificables, capacidades on-chain
            y matching para misiones autónomas.
          </p>
        </div>

        <button
          className="agent-refresh"
          disabled={loading}
          onClick={() => setRefresh(value => value + 1)}
        >
          Actualizar red
        </button>
      </div>

      <div className="agent-marketplace-stats">
        <div>
          <span>Agentes registrados según filtros</span>
          <strong>{totalAgents}</strong>
        </div>
        <div>
          <span>Resultados cargados</span>
          <strong>{agents.length}</strong>
        </div>
        <div>
          <span>Misiones disponibles en esta página</span>
          <strong>{missions.length}</strong>
        </div>
        <div>
          <span>Agentes elegibles para la misión</span>
          <strong>
            {loadingMatch ? '…' : matching ? eligibleCount : '—'}
          </strong>
        </div>
      </div>

      <div className="agent-marketplace-controls">
        <label>
          Estado
          <select
            value={activity}
            disabled={loadingMore}
            onChange={event =>
              setActivity(event.target.value as ActivityFilter)
            }
          >
            <option value="all">Todos</option>
            <option value="active">Activos</option>
            <option value="inactive">No activos</option>
          </select>
        </label>

        <label>
          Capacidad requerida
          <select
            value={capability}
            disabled={loadingMore}
            onChange={event => setCapability(event.target.value)}
          >
            <option value="all">Todas las capacidades</option>
            {CAPABILITIES.map(([bit, name]) => (
              <option
                key={bit}
                value={(1n << BigInt(bit)).toString()}
              >
                {name}
              </option>
            ))}
          </select>
        </label>

        <label>
          Buscar en resultados cargados
          <input
            value={search}
            onChange={event => setSearch(event.target.value)}
            placeholder="Agent ID o dirección"
          />
        </label>
      </div>

      {error && (
        <div className="agent-marketplace-error" role="alert">
          {error}
        </div>
      )}

      <div className="agent-marketplace-layout">
        <div>
          <div className="agent-marketplace-section">
            <h3>Explore agents</h3>
            <span>
              Datos obtenidos de Marketplace API
            </span>
          </div>

          {loading && (
            <p className="agent-marketplace-muted">
              Consultando agentes registrados…
            </p>
          )}

          {!loading && visible.length === 0 && (
            <div className="agent-marketplace-empty">
              No se encontraron agentes con estos filtros.
            </div>
          )}

          <div className="agent-marketplace-grid">
            {visible.map(agent => {
              const selected =
                agent.agent_account === selectedAgent;

              const capabilities =
                capabilityNames(agent.capabilities);

              return (
                <button
                  type="button"
                  key={agent.agent_account}
                  className={
                    `agent-tile${selected ? ' selected' : ''}`
                  }
                  onClick={() =>
                    setSelectedAgent(agent.agent_account)
                  }
                  aria-pressed={selected}
                >
                  <div className="agent-tile-top">
                    <span className="agent-avatar">◈</span>
                    <span
                      className={
                        agent.active
                          ? 'agent-state active'
                          : 'agent-state'
                      }
                    >
                      {agent.status}
                    </span>
                  </div>

                  <strong>
                    Agent {agent.agent_id.slice(0, 8)}
                  </strong>

                  <code>
                    {abbreviate(agent.agent_account)}
                  </code>

                  <div className="agent-tags">
                    {capabilities.slice(0, 4).map(name => (
                      <span key={name}>{name}</span>
                    ))}

                    {capabilities.length > 4 && (
                      <span>+{capabilities.length - 4}</span>
                    )}

                    {capabilities.length === 0 && (
                      <span>Sin capacidades registradas</span>
                    )}
                  </div>
                </button>
              );
            })}
          </div>

          {nextCursor && (
            <button
              className="agent-load-more"
              disabled={loading || loadingMore}
              onClick={() => void loadMore()}
            >
              {loadingMore
                ? 'Cargando…'
                : 'Cargar más agentes'}
            </button>
          )}
        </div>

        <aside className="agent-marketplace-inspector">
          <div className="agent-marketplace-section">
            <h3>Agent intelligence</h3>
            <span>Identidad y elegibilidad</span>
          </div>

          {currentAgent ? (
            <>
              <div className="agent-inspector-field">
                <span>Agent account</span>
                <code>{currentAgent.agent_account}</code>
              </div>

              <div className="agent-inspector-field">
                <span>Agent ID</span>
                <code>{currentAgent.agent_id}</code>
              </div>

              <div className="agent-inspector-field">
                <span>Estado</span>
                <strong>{currentAgent.status}</strong>
              </div>

              <div className="agent-inspector-field">
                <span>Capabilities bitmask</span>
                <code>{currentAgent.capabilities}</code>
              </div>

              <div className="agent-inspector-field">
                <span>Capacidades registradas</span>
                <div className="agent-tags">
                  {capabilityNames(
                    currentAgent.capabilities
                  ).map(name => <span key={name}>{name}</span>)}
                </div>
              </div>
            </>
          ) : (
            <p className="agent-marketplace-muted">
              Selecciona un agente para inspeccionar
              sus capacidades.
            </p>
          )}

          <div className="agent-marketplace-section agent-match-heading">
            <h3>Mission matching</h3>
            <span>Motor Rust de AeroSettle</span>
          </div>

          <label className="agent-mission-select">
            Misión disponible
            <select
              value={selectedMission}
              onChange={event =>
                setSelectedMission(event.target.value)
              }
            >
              {missions.length === 0 && (
                <option value="">Sin misiones disponibles</option>
              )}

              {missions.map(order => (
                <option
                  value={order.work_order_account}
                  key={order.work_order_account}
                >
                  {abbreviate(order.work_order_account)}
                </option>
              ))}
            </select>
          </label>

          {loadingMatch && (
            <p className="agent-marketplace-muted">
              Evaluando compatibilidad…
            </p>
          )}

          {matchError && (
            <div className="agent-marketplace-error">
              {matchError}
            </div>
          )}

          {!selectedMission && (
            <p className="agent-marketplace-muted">
              No hay una misión abierta y disponible
              para ejecutar matching.
            </p>
          )}

          {currentAgent && matching && !loadingMatch && (
            <div className="agent-match-result">
              {currentEvaluation?.eligible === true ? (
                <strong className="agent-match-eligible">
                  ✓ Agente elegible
                </strong>
              ) : currentEvaluation ? (
                <>
                  <strong>Agente no elegible</strong>
                  <code>
                    {currentEvaluation.rejection?.code ??
                      'UNSPECIFIED_REJECTION'}
                  </code>

                  {currentEvaluation.rejection?.missing_mask && (
                    <span>
                      Capacidades faltantes (bitmask):{' '}
                      {currentEvaluation.rejection.missing_mask}
                    </span>
                  )}
                </>
              ) : (
                <span>Sin evaluación disponible</span>
              )}
            </div>
          )}
        </aside>
      </div>

      <footer className="agent-marketplace-footer">
        <span>Solana Localnet · Read-only</span>
        <span>
          Chain time:{' '}
          {chainTime === null
            ? '—'
            : new Date(chainTime * 1000).toLocaleString()}
        </span>
      </footer>

      <p className="agent-marketplace-muted">
        El matching es orientativo y se calcula sobre lecturas
        RPC no atómicas. La elegibilidad se valida de nuevo
        en el contrato durante ClaimWorkOrder. No se firman
        ni transmiten transacciones desde esta vista.
      </p>
    </section>
  );
}
