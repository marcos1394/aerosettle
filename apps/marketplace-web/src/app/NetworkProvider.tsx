import { createContext, useContext, type ReactNode } from 'react';
import { useConnection } from '@solana/wallet-adapter-react';
import { useWallet } from '@solana/wallet-adapter-react';
import { verifyNetwork } from './api';
import { useResource } from './useResource';
import { LOCALNET_MANIFEST } from '../config/environments.ts';
type Network = {
  loading: boolean;
  error?: string;
  data?: { genesis: string; service: string; observedAt: string };
  reload: () => void;
};
const Context = createContext<Network | null>(null);
export function NetworkProvider({ children }: { children: ReactNode }) {
  const { connection } = useConnection();
  const { publicKey } = useWallet();
  const identity = `${LOCALNET_MANIFEST.manifest_sha256}:${connection.rpcEndpoint}:${publicKey?.toBase58() ?? 'DISCONNECTED'}`;
  const value = useResource(identity, (signal) =>
    verifyNetwork(connection, signal)
  );
  return <Context.Provider value={value}>{children}</Context.Provider>;
}
export function useNetwork() {
  const value = useContext(Context);
  if (!value) throw new Error('Missing NetworkProvider');
  return value;
}
