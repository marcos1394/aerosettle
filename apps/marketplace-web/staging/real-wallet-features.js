import { getWallets } from '@wallet-standard/app';

// Local Vite-only diagnostic. It reads public feature metadata and never calls a wallet.
export function inspectRealWalletFeatures() {
  const required = {
    'standard:connect': 'connect',
    'standard:disconnect': 'disconnect',
    'standard:events': 'on',
  };
  return getWallets().get()
    .filter((wallet) => wallet.name === 'Phantom' || wallet.name === 'Solflare')
    .map((wallet) => ({
      wallet: wallet.name,
      standardVersion: wallet.version,
      devnetAdvertised: Array.isArray(wallet.chains) && wallet.chains.includes('solana:devnet'),
      features: Object.fromEntries(Object.entries(required).map(([name, method]) => [
        name, wallet.features?.[name]?.version === '1.0.0' &&
          typeof wallet.features[name][method] === 'function',
      ])),
    }));
}
