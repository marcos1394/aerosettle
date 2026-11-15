import { MarketplaceClient, type ApiMeta } from '@aerosettle/marketplace-sdk';
import { PublicKey, type Connection } from '@solana/web3.js';
import { LOCALNET_MANIFEST } from '../config/environments.ts';
import { assertEndpointBinding, verifyEnvironment, type Rpc } from '../config/verify.ts';
export const api = new MarketplaceClient({
  baseUrl: window.location.origin,
  timeoutMs: 15000,
});
export function verifyMeta(meta: ApiMeta) {
  if (meta.program_id !== LOCALNET_MANIFEST.program_id)
    throw new Error('La API devuelve otro programa.');
}
export async function verifyNetwork(
  connection: Connection,
  signal?: AbortSignal
) {
  assertEndpointBinding(LOCALNET_MANIFEST, connection.rpcEndpoint, window.location.origin);
  const idlResponse = await fetch('/idl/localnet-idl.json', { cache: 'no-store', signal });
  if (!idlResponse.ok) throw new Error('MANIFEST_INVALID');
  const rpc: Rpc = async (method, params) => {
    if (method === 'getGenesisHash') return connection.getGenesisHash();
    if (method !== 'getAccountInfo' || typeof params[0] !== 'string')
      throw new Error('RPC_METHOD_REJECTED');
    const account = await connection.getAccountInfo(new PublicKey(params[0]), 'finalized');
    return { value: account ? { executable: account.executable,
      owner: account.owner.toBase58(), data: [account.data.toString('base64'), 'base64'] } : null };
  };
  const result = await verifyEnvironment(LOCALNET_MANIFEST, await idlResponse.text(),
    rpc, async () => {
      const [health, agents] = await Promise.all([api.health(signal), api.listAgents({ limit: 1 }, signal)]);
      return { ...health, program_id: agents.meta.program_id };
    }, signal);
  if (result.status !== 'VERIFIED') throw new Error(result.reason);
  return {
    genesis: result.genesis!,
    service: result.service!,
    observedAt: result.observedAt,
  };
}
