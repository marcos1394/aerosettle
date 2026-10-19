import { createContext, useContext, type ReactNode } from 'react';
import { useConnection } from '@solana/wallet-adapter-react';
import { verifyNetwork } from './api';
import { useResource } from './useResource';
type Network = {
  loading: boolean;
  error?: string;
  data?: { genesis: string; service: string; observedAt: string };
  reload: () => void;
};
const Context = createContext<Network | null>(null);
export function NetworkProvider({ children }: { children: ReactNode }) {
  const { connection } = useConnection();
  const value = useResource('network', (signal) =>
    verifyNetwork(connection, signal)
  );
  return <Context.Provider value={value}>{children}</Context.Provider>;
}
export function useNetwork() {
  const value = useContext(Context);
  if (!value) throw new Error('Missing NetworkProvider');
  return value;
}
