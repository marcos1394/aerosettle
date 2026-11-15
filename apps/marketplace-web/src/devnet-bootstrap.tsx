import React from 'react';
import { createRoot } from 'react-dom/client';
import './styles/tokens.css';
import './styles/global.css';
import './styles/devnet.css';
import { DevnetReadOnlyApp } from './devnet/DevnetReadOnlyApp.tsx';

const root = document.getElementById('root');
if (!root) throw new Error('Missing root element');
createRoot(root).render(<React.StrictMode><DevnetReadOnlyApp /></React.StrictMode>);
