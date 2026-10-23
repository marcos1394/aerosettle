import { useState } from 'react';
import { useWallet } from '@solana/wallet-adapter-react';
import { api } from '../../app/api';
import { useCopy } from '../../app/i18n';
import { useResource } from '../../app/useResource';
import EscrowView from '../funding/EscrowView';

/** A scoped list of protocol vaults; each selected vault is verified by EscrowView over RPC. */
export function ProtocolEscrowSection() {
  const c = useCopy();
  const { publicKey } = useWallet();
  const wallet = publicKey?.toBase58() ?? '';
  const [selected, setSelected] = useState('');
  const orders = useResource(`wallet-escrow:${wallet}`, async (signal) => {
    if (!wallet) return { rows: [] as string[], complete: true };
    const rows: string[] = [];
    let cursor: string | undefined;
    let complete = false;
    for (let pageNumber = 0; pageNumber < 5; pageNumber += 1) {
      const page = await api.listWorkOrders({ limit: 100, cursor }, signal);
      rows.push(...page.data.filter((order) => order.creator === wallet)
        .map((order) => order.work_order_account));
      if (!page.page.next_cursor) { complete = true; break; }
      cursor = page.page.next_cursor;
    }
    return { rows, complete };
  });
  const row = orders.data?.rows.includes(selected) ? selected : orders.data?.rows[0];
  return <section className="panel" aria-label="PROTOCOL ESCROW">
    <div className="section-heading"><h2>PROTOCOL ESCROW</h2></div>
    <p className="hint">{c('Vault funds belong to individual WorkOrders. Showing only orders where this wallet is creator; deposits are not agent earnings or settled payouts.', 'Los fondos del vault pertenecen a WorkOrders individuales. Solo se muestran órdenes creadas por esta wallet; los depósitos no son ingresos del agente ni pagos liquidados.')}</p>
    {!wallet && <p role="status">{c('Wallet disconnected.', 'Wallet desconectada.')}</p>}
    {wallet && orders.loading && <p role="status">{c('Loading WorkOrders…', 'Cargando WorkOrders…')}</p>}
    {wallet && orders.error && <p role="alert">{c('WorkOrder API unavailable: ', 'API de WorkOrders no disponible: ')}{orders.error}</p>}
    {wallet && !orders.loading && !orders.error && orders.data?.rows.length === 0 && <p role="status">{c('No creator WorkOrders in the queried scope.', 'No hay WorkOrders del creador en el alcance consultado.')}</p>}
    {wallet && row && !orders.loading && !orders.error && <>
      <p>{c('Creator orders in queried scope', 'Órdenes del creador en el alcance consultado')}: {orders.data?.rows.length}{orders.data?.complete ? '' : ' · PARTIAL PAGE SCOPE'}</p>
      <label>{c('Select WorkOrder', 'Seleccionar WorkOrder')}
        <select value={row} onChange={(event) => setSelected(event.target.value)}>
          {orders.data?.rows.map((account) => <option key={account} value={account}>{account}</option>)}
        </select>
      </label>
      <EscrowView key={row} workOrderPda={row} />
    </>}
  </section>;
}
