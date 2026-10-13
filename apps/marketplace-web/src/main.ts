import { Buffer } from 'buffer';

// Make Buffer available before loading Solana web3.js
// and wallet-adapter modules in the browser.
(globalThis as typeof globalThis & {
  Buffer: typeof Buffer;
}).Buffer = Buffer;

void import('./bootstrap');
