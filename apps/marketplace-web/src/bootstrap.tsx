import React from 'react';
import { createRoot } from 'react-dom/client';
import './styles/wallet-adapter.css';
import './styles/tokens.css';
import './styles/global.css';
import './styles/viz.css';
import { Providers } from './app/Providers';
import { AppRoutes } from './app/routes';
const root = document.getElementById('root');
if (!root) throw new Error('Missing root element');
createRoot(root).render(
  <React.StrictMode>
    <Providers>
      <AppRoutes />
    </Providers>
  </React.StrictMode>
);
