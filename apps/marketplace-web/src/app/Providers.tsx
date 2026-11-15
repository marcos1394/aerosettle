import { LanguageProvider } from './i18n';
import { Fragment, type ReactNode } from 'react';
import {
  ConnectionProvider,
  WalletProvider,
  useWallet,
} from '@solana/wallet-adapter-react';
import { WalletModalProvider } from '@solana/wallet-adapter-react-ui';
import { PhantomWalletAdapter } from '@solana/wallet-adapter-phantom';
import { LocalnetDevWalletAdapter } from '../LocalnetDevWalletAdapter';
import { RPC } from './config';
import { LOCALNET_MANIFEST } from '../config/environments.ts';
const wallets = [
  new PhantomWalletAdapter(),
  ...(import.meta.env.DEV && window.location.hostname === '127.0.0.1'
    ? [new LocalnetDevWalletAdapter()]
    : []),
];
function WalletContextBoundary({ children }: { children: ReactNode }) {
  const { publicKey } = useWallet();
  const identity = `${LOCALNET_MANIFEST.manifest_sha256}:${RPC}:${publicKey?.toBase58() ?? 'DISCONNECTED'}`;
  return <Fragment key={identity}>{children}</Fragment>;
}
export function Providers({ children }: { children: ReactNode }) {
  return (
    <LanguageProvider>
      <ConnectionProvider endpoint={RPC}>
        <WalletProvider wallets={wallets} autoConnect={false}>
          <WalletModalProvider><WalletContextBoundary>{children}</WalletContextBoundary></WalletModalProvider>
        </WalletProvider>
      </ConnectionProvider>
    </LanguageProvider>
  );
}
