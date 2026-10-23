import { useCopy, useI18n } from '../../app/i18n';
import { useConnection } from '@solana/wallet-adapter-react';
import { PublicKey } from '@solana/web3.js';
import { verifyNetwork } from '../../app/api';
import { readAccount } from '../../app/readAccount';
import { PROGRAM_ID, TOKEN_PROGRAM } from '../../app/config';
import { SETTLEMENT_SYMBOL } from '../../app/atlas';
import { useResource } from '../../app/useResource';
import { CopyAddress, DataGrid, ResourceState } from '../../components/ui';
export default function EscrowView({ workOrderPda }: { workOrderPda: string }) {
  const { t } = useI18n();
  const c = useCopy();

  const { connection } = useConnection();
  const resource = useResource(`escrow:${workOrderPda}`, async (signal) => {
    await verifyNetwork(connection, signal);
    const order = await readAccount(
      connection,
      workOrderPda,
      'WorkOrderAccount'
    );
    const [vault] = PublicKey.findProgramAddressSync(
      [
        new TextEncoder().encode('escrow'),
        new PublicKey(workOrderPda).toBuffer(),
      ],
      PROGRAM_ID
    );
    if (order.status !== 'Draft' && order.escrow_vault !== vault.toBase58())
      throw new Error('Escrow registrado incompatible con su PDA.');
    const rpc = await connection.getAccountInfoAndContext(vault, 'confirmed');
    const info = rpc.value;
    let balance: string | null = null;
    if (info) {
      if (
        !info.owner.equals(TOKEN_PROGRAM) ||
        info.data.length !== 165 ||
        info.data[108] !== 1 ||
        !new PublicKey(info.data.subarray(32, 64)).equals(vault) ||
        new PublicKey(info.data.subarray(0, 32)).toBase58() !== order.token_mint
      )
        throw new Error('Vault SPL, mint o autoridad no válidos.');
      balance = info.data.readBigUInt64LE(64).toString();
      if (order.status === 'Settled' && balance !== '0')
        throw new Error('Orden Settled con saldo pendiente en escrow.');
    } else if (
      ['Open', 'Claimed', 'Submitted', 'Verified'].includes(order.status!)
    )
      throw new Error('Orden financiada sin vault verificable.');
    return { vault: vault.toBase58(), balance, exists: !!info, slot: rpc.context.slot,
      mint: order.token_mint, status: order.status };
  });
  return (
    <section className="panel">
      <div className="section-heading">
        <h2>{t('Escrow on-chain')}</h2>
        <button disabled={resource.loading} onClick={resource.reload}>
          {c('Verify on-chain vault', 'Verificar vault on-chain')}
        </button>
      </div>
      <ResourceState {...resource} />
      {resource.data && (
        <>
          <DataGrid
            items={[
              [
                c('Derived vault PDA', 'PDA derivada del vault'),
                <CopyAddress value={resource.data.vault} />,
              ],
              [
                t('Estado observado'),
                resource.data.exists
                  ? t('Cuenta SPL existente')
                  : c('Account not initialized', 'Cuenta no inicializada'),
              ],
              [c('RPC slot / commitment', 'Slot RPC / compromiso'), `${resource.data.slot} / confirmed`],
              [c('WorkOrder state', 'Estado de WorkOrder'), resource.data.status ?? '—'],
              [c('Escrow mint', 'Mint del escrow'), resource.data.mint
                ? <CopyAddress value={resource.data.mint} /> : '—'],
              [
                c(
                  `Escrow balance (${SETTLEMENT_SYMBOL} base units)`,
                  `Saldo en custodia (unidades base ${SETTLEMENT_SYMBOL})`
                ),
                resource.data.balance ?? c('No active account', 'Sin cuenta activa'),
              ],
            ]}
          />
          <p className="hint">
            {c(
              'Funds remain locked in the program-derived escrow vault until mission evidence is verified and settled on-chain.',
              'Los fondos permanecen bloqueados en el vault de escrow derivado del programa hasta que la evidencia de la misión se verifica y liquida on-chain.'
            )}
          </p>
        </>
      )}
    </section>
  );
}
