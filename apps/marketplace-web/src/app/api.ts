import { MarketplaceClient, type ApiMeta } from '@aerosettle/marketplace-sdk';
import type { Connection } from '@solana/web3.js';
import { LOCALNET_GENESIS, PROGRAM_ID } from './config';
export const api = new MarketplaceClient({
  baseUrl: window.location.origin,
  timeoutMs: 15000,
});
export function verifyMeta(meta: ApiMeta) {
  if (meta.program_id !== PROGRAM_ID.toBase58())
    throw new Error('La API devuelve otro programa.');
}
export async function verifyNetwork(
  connection: Connection,
  signal?: AbortSignal
) {
  const [genesis, health, program] = await Promise.all([
    connection.getGenesisHash(),
    api.health(signal),
    connection.getAccountInfo(PROGRAM_ID, 'confirmed'),
  ]);
  if (genesis !== LOCALNET_GENESIS || health.genesis !== LOCALNET_GENESIS)
    throw new Error(
      'RPC y Marketplace API no coinciden con el Localnet esperado.'
    );
  if (!program?.executable)
    throw new Error('El programa AeroSettle no está desplegado.');
  return {
    genesis,
    service: health.service,
    observedAt: new Date().toISOString(),
  };
}
