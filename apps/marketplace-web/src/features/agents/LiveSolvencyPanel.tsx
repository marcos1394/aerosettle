import { useState } from 'react';
import { useWallet } from '@solana/wallet-adapter-react';
// @ts-expect-error bs58 lacks bundled TypeScript declarations in this workspace
import bs58 from 'bs58';
import type { AgentSolvencyAssessment, SolvencyMethodology } from '@aerosettle/marketplace-sdk';
import { api } from '../../app/api';
import { useCopy } from '../../app/i18n';
import { ProvenanceBadge } from '../../components/ui';

/** Owner-authenticated, read-only economic assessment for live agents. */
export function LiveSolvencyPanel({ account, owner }: { account: string; owner: string }) {
  const c = useCopy();
  const wallet = useWallet();
  const [assessments, setAssessments] = useState<AgentSolvencyAssessment[]>([]);
  const [method, setMethod] = useState<SolvencyMethodology | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  async function load() {
    if (!wallet.publicKey || wallet.publicKey.toBase58() !== owner || !wallet.signMessage) {
      setError(c('Connect the owner wallet with message signing to view this assessment.', 'Conecta la cartera del propietario con firma de mensajes para consultar esta evaluación.'));
      return;
    }
    setLoading(true);
    setError(null);
    try {
      const timestamp = Math.floor(Date.now() / 1000);
      const challenge = new TextEncoder().encode(`conatus:economic-auth:v1:${timestamp}:${account}`);
      const signature = await wallet.signMessage(challenge);
      const authHeaders = {
        'X-Signer-Pubkey': wallet.publicKey.toBase58(),
        'X-Timestamp': String(timestamp),
        'X-Signature': bs58.encode(signature),
      };
      const [result, details] = await Promise.all([
        api.getAgentSolvency(account, { window: 30 }, { authHeaders }),
        api.getSolvencyMethodology(account, { authHeaders }),
      ]);
      setAssessments(result.data.filter((item): item is AgentSolvencyAssessment => item.calculation_status !== 'MIXED_ASSET_CONTEXT'));
      setMethod(details.data);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : String(cause));
    } finally {
      setLoading(false);
    }
  }

  return <section className="panel" aria-label={c('Verified economic assessment', 'Evaluación económica verificada')}>
    <div className="section-heading">
      <h2>{c('Live / verified economic assessment', 'Evaluación económica real / verificada')}</h2>
      <ProvenanceBadge provenance="EXTERNAL_VERIFIED" status={assessments.some(a => a.calculation_status === 'VALID' && (a.provenance.startsWith('LIVE_RPC') || a.provenance === 'EXTERNAL_ATTESTED_LEDGER')) ? 'VERIFIED' : 'UNAVAILABLE'}
        source="Economic Ledger / CON-25" network="Per asset" period="30 UTC days" compact />
    </div>
    <p className="hint">{c('Owner access is required. Each mint and network is assessed separately.', 'Se requiere acceso del propietario. Cada activo y red se evalúa por separado.')}</p>
    <button type="button" className="button" disabled={loading} onClick={load}>
      {loading ? c('Loading…', 'Cargando…') : c('View verified assessment', 'Ver evaluación verificada')}
    </button>
    {error && <p role="alert">{error}</p>}
    {!error && assessments.length === 0 && <p className="hint">INSUFFICIENT_DATA · {c('No verified financial context available.', 'No hay contexto financiero verificado disponible.')}</p>}
    {assessments.map(a => <div key={a.assessment_id} className="panel" style={{ marginTop: 12 }}>
      <strong>{a.calculation_status === 'VALID' ? `${a.conatus_ratio}× · ${a.sustainability_class}` : `${a.calculation_status} · UNDETERMINED`}</strong>
      <p className="hint">{a.provenance}</p>
      <p>{a.network} · {a.token_mint}</p>
      <p>{c('Window', 'Período')}: {new Date(a.window_start * 1000).toISOString()} – {new Date(a.window_end * 1000).toISOString()} UTC</p>
      <p>{c('Verified revenue', 'Ingresos verificados')}: {a.verified_revenue_base_units_str ?? '—'} · {c('Verified OPEX', 'Gasto operativo verificado')}: {a.verified_opex_base_units_str ?? '—'} {c('base units', 'unidades base')}</p>
      <p>{c('Available cash', 'Caja disponible')}: {a.available_liquidity_base_units_str ?? '—'} · {c('Reserved', 'Reservado')}: {a.total_reserved_base_units_str ?? '—'} · {c('Runway days', 'Días de autonomía')}: {a.runway_days ?? '—'}</p>
      <p className="hint">{a.methodology_version} · {a.threshold_config_version} · {a.evidence_references.length} {c('evidence references', 'referencias de evidencia')}</p>
    </div>)}
    {method && <details><summary>{c('Methodology and thresholds', 'Metodología y umbrales')}</summary>
      <p>{method.ratio}. {method.window_semantics}. {method.zero_coverage}.</p>
      <p>AT_RISK &lt; {method.thresholds.stable}; STABLE &lt; {method.thresholds.thriving}; THRIVING ≥ {method.thresholds.thriving}.</p>
    </details>}
  </section>;
}
