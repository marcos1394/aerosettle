import { Link } from 'react-router';
import { useCopy } from '../i18n.tsx';
import { Icon } from '../ui.tsx';
import { useDevnetData } from '../DevnetDataProvider.tsx';
import { CAPABILITY_NAMES, capabilityBits, shortAddress } from '../catalog.ts';

export function CatalogNotice() {
  const c = useCopy();
  const { catalog, verification, loading, reload } = useDevnetData();
  if (catalog) return <p className="devnet-provenance-line">
    <Icon name="shield" /> {c('On-chain accounts · finalized Devnet snapshot', 'Cuentas on-chain · instantánea finalizada de Devnet')}
    <span> · {c('slot', 'slot')} {catalog.provenance.slot_max.toLocaleString()}</span>
    <Link to="/status">{c('Verify provenance', 'Ver procedencia')} ↗</Link>
  </p>;
  return <section className="devnet-unavailable" role="status" aria-live="polite">
    <Icon name="activity" />
    <div><h2>{loading ? c('Verifying the network', 'Verificando la red') :
      verification.status === 'NETWORK_MISMATCH' || verification.status === 'MANIFEST_INVALID'
        ? c('Network identity could not be verified', 'No se pudo verificar la identidad de la red')
        : verification.reason === 'INDEX_STALE'
          ? c('The snapshot has expired', 'La instantánea ha caducado')
        : c('The account index is temporarily unavailable', 'El índice de cuentas no está disponible temporalmente')}</h2>
      <p>{c('Navigation remains available. No account is shown as current until a fresh, verified snapshot is published.',
        'La navegación sigue disponible. No se muestra ninguna cuenta como actual hasta que se publique una instantánea nueva y verificada.')}</p>
      <p className="micro">{verification.reason}</p>
      <div className="devnet-inline-actions"><button onClick={reload}>{c('Try again', 'Reintentar')}</button>
        <Link to="/status" className="button">{c('View status', 'Ver estado')}</Link></div>
    </div>
  </section>;
}
export function CapabilityChips({ mask }: { mask: number }) {
  const c = useCopy();
  const bits = capabilityBits(mask);
  return <div className="devnet-capabilities">
    {bits.length ? bits.map((bit) => <span key={bit} className="devnet-capability">
      {c(CAPABILITY_NAMES[bit][0], CAPABILITY_NAMES[bit][1])}</span>) : <span className="muted">{c('No capability bits set', 'Sin bits de capacidad activos')}</span>}
  </div>;
}
export function Address({ value, full = false }: { value: string; full?: boolean }) {
  return <code className="devnet-address" title={value}>{full ? value : shortAddress(value)}</code>;
}
export function ProofBadge() {
  return <span className="devnet-proof-badge"><Icon name="shield" /> ONCHAIN_VERIFIED</span>;
}
export function SourceLegend() {
  const c = useCopy();
  return <aside className="devnet-source-legend" aria-label={c('Data source legend', 'Leyenda de fuentes')}>
    <strong>{c('What is shown', 'Qué se muestra')}</strong>
    <p><b>ONCHAIN_VERIFIED</b> — {c('account fields in the finalized release snapshot', 'campos de cuentas en la instantánea finalizada del release')}.</p>
    <p><b>AGENT_CARD_SIGNED_CLAIM</b>, <b>UNVERIFIED_METADATA</b>, <b>DEMO_ONLY</b> —
      {c(' not joined into this catalog or used as financial authority.',
        ' no se incorporan a este catálogo ni se usan como autoridad financiera.')}</p>
  </aside>;
}
export function EmptyResults() {
  const c = useCopy();
  return <div className="empty-state"><Icon name="search" /><h2>{c('No matching accounts', 'No hay cuentas coincidentes')}</h2>
    <p>{c('Change the search or filters. Only verified Devnet records are included.',
      'Cambia la búsqueda o los filtros. Solo se incluyen registros Devnet verificados.')}</p></div>;
}
