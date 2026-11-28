import { getWallets } from '@wallet-standard/app';
import { createContext, useContext, useEffect, useMemo, useSyncExternalStore,
  type ReactNode } from 'react';
import { WalletIdentitySession } from './standard.ts';

const Context = createContext<WalletIdentitySession | null>(null);

export function DevnetWalletIdentityProvider({ children }: { children: ReactNode }) {
  const session = useMemo(() => new WalletIdentitySession(getWallets()), []);
  useEffect(() => { session.start(); return () => session.dispose(); }, [session]);
  return <Context.Provider value={session}>{children}</Context.Provider>;
}

export function useWalletIdentity() {
  const session = useContext(Context);
  if (!session) throw new Error('DevnetWalletIdentityProvider required');
  const snapshot = useSyncExternalStore(session.subscribe, () => session.snapshot);
  return { session, snapshot };
}
