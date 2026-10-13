import FundingPanel from "./FundingPanel";
import { LocalnetDevWalletAdapter } from './LocalnetDevWalletAdapter';
import React from 'react';
import { createRoot } from 'react-dom/client';

import {
  ConnectionProvider,
  WalletProvider,
} from '@solana/wallet-adapter-react';

import {
  WalletModalProvider,
} from '@solana/wallet-adapter-react-ui';

import { PhantomWalletAdapter } from '@solana/wallet-adapter-phantom';

import '@solana/wallet-adapter-react-ui/styles.css';
import './styles.css';

import { App } from './App';

const RPC = 'http://127.0.0.1:8899';

const wallets = [
  new PhantomWalletAdapter(),
  ...(
    import.meta.env.DEV &&
    window.location.hostname === '127.0.0.1'
      ? [new LocalnetDevWalletAdapter()]
      : []
  ),
];

const root = document.getElementById('root');

if (!root) {
  throw new Error('Missing root element');
}

createRoot(root).render(
  <React.StrictMode>
    <ConnectionProvider endpoint={RPC}>
      <WalletProvider wallets={wallets} autoConnect={false}>
        <WalletModalProvider>
          <><App /><FundingPanel /></>
        </WalletModalProvider>
      </WalletProvider>
    </ConnectionProvider>
  </React.StrictMode>
);
