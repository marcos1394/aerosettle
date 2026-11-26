import React from 'react';
import { createRoot } from 'react-dom/client';
import './styles/tokens.css';
import './styles/global.css';
import './styles/landing.css';
import './styles/agents.css';
import './styles/missions.css';
import './styles/devnet.css';
import './styles/devnet-premium.css';
import './styles/devnet-wallet.css';
import { DevnetApp } from './devnet/DevnetApp.tsx';

const root = document.getElementById('root');
if (!root) throw new Error('Missing root element');
createRoot(root).render(<React.StrictMode><DevnetApp /></React.StrictMode>);
