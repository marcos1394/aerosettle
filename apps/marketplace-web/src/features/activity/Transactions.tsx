import { useCopy, useI18n } from '../../app/i18n';
import { useConnection } from '@solana/wallet-adapter-react';
import { PublicKey } from '@solana/web3.js';
import { verifyNetwork } from '../../app/api';
import { useResource } from '../../app/useResource';
import { date } from '../../app/config';
import { useSnapshot } from '../../app/atlas';
import { Badge, CopyAddress, Empty, ResourceState } from '../../components/ui';

export default function Transactions({ address }: { address: string }) {
  const { t, locale } = useI18n();
  const c = useCopy();
  const [snapshot] = useSnapshot();

  const { connection } = useConnection();
  const resource = useResource(`transactions:${address}`, async (signal) => {
    await verifyNetwork(connection, signal);
    return connection.getSignaturesForAddress(
      new PublicKey(address),
      { limit: 20 },
      'confirmed'
    );
  });
  return (
    <section className="panel">
      <div className="section-heading">
        <h2>{c('On-chain transactions', 'Transacciones on-chain')}</h2>
        <button disabled={resource.loading} onClick={resource.reload}>
          {t('Actualizar historial')}
        </button>
      </div>
      <p className="hint">
        {c(
          'Up to 20 recent confirmed signatures associated with this Solana account, ordered by slot.',
          'Hasta 20 firmas confirmadas recientes asociadas a esta cuenta de Solana, ordenadas por slot.'
        )}
      </p>
      {!snapshot || !resource.error ? (
        <ResourceState {...resource} />
      ) : (
        <p className="micro">
          {c(
            'RPC node is currently unreachable. Connect to an active Solana RPC endpoint in Settings to query live account signatures.',
            'El nodo RPC no está disponible en este momento. Conéctate a un endpoint RPC de Solana activo en Configuración para consultar firmas en vivo.'
          )}
        </p>
      )}
      {resource.data?.map((tx) => (
        <article className="transaction-row" key={tx.signature}>
          <div>
            <CopyAddress value={tx.signature} label={t('firma')} />
            <p className="micro">
              {t('Slot')} {tx.slot} · {date(tx.blockTime, locale)}
            </p>
          </div>
          <Badge
            status={tx.err ? 'Error' : (tx.confirmationStatus ?? 'Confirmed')}
          />
          {tx.err && (
            <details>
              <summary>{t('Error on-chain')}</summary>
              <pre>{JSON.stringify(tx.err)}</pre>
            </details>
          )}
        </article>
      ))}
      {resource.data?.length === 0 && (
        <Empty title={t('Sin historial disponible')}>
          {c(
            'No confirmed signatures were returned for this account yet.',
            'Todavía no se devolvieron firmas confirmadas para esta cuenta.'
          )}
        </Empty>
      )}
    </section>
  );
}
