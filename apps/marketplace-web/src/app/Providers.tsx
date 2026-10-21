import { LanguageProvider } from './i18n';
import type { ReactNode } from 'react';
import {
  ConnectionProvider,
  WalletProvider,
} from '@solana/wallet-adapter-react';
import { WalletModalProvider } from '@solana/wallet-adapter-react-ui';
import { PhantomWalletAdapter } from '@solana/wallet-adapter-phantom';
import { LocalnetDevWalletAdapter } from '../LocalnetDevWalletAdapter';
import { RPC } from './config';
const wallets = [
  new PhantomWalletAdapter(),
  ...(import.meta.env.DEV && window.location.hostname === '127.0.0.1'
    ? [new LocalnetDevWalletAdapter()]
    : []),
];
export function Providers({ children }: { children: ReactNode }) {
  return (
    <LanguageProvider>
      <ConnectionProvider endpoint={RPC}>
        <WalletProvider wallets={wallets} autoConnect={false}>
          <WalletModalProvider>{children}</WalletModalProvider>
        </WalletProvider>
      </ConnectionProvider>
    </LanguageProvider>
  );
}
