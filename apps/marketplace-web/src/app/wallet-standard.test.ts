import assert from 'node:assert/strict';
import { test } from 'node:test';
// @ts-expect-error bs58 v4 has no bundled TypeScript declarations in this workspace.
import bs58 from 'bs58';
import type { Wallet, WalletAccount } from '@wallet-standard/base';
import { WalletIdentitySession, inspectWallet, validateAccount, type WalletRegistry } from '../devnet/wallet/standard.ts';
import { informationalPreview, WALLET_CAPABILITIES } from '../devnet/wallet/permissions.ts';

function account(byte = 1, chains: readonly `${string}:${string}`[] = ['solana:devnet']): WalletAccount {
  const publicKey = Uint8Array.from({ length: 32 }, () => byte);
  return { address: bs58.encode(publicKey), publicKey, chains, features: [] };
}
function setup(name = 'Phantom', chains: readonly `${string}:${string}`[] = ['solana:devnet']) {
  const handlers: ((change: { accounts?: readonly WalletAccount[]; chains?: readonly string[];
    features?: Wallet['features'] }) => void)[] = [];
  let connectCalls = 0;
  let disconnectCalls = 0;
  let result: () => Promise<{ accounts: readonly WalletAccount[] }> = async () => ({ accounts: [account()] });
  const wallet = {
    version: '1.0.0', name, icon: 'data:image/png;base64,', chains, accounts: [],
    features: {
      'standard:connect': { version: '1.0.0', connect: () => { connectCalls++; return result(); } },
      'standard:disconnect': { version: '1.0.0', disconnect: async () => { disconnectCalls++; } },
      'standard:events': { version: '1.0.0', on: (_event: string, cb: typeof handlers[number]) => {
        handlers.push(cb); return () => { const i = handlers.indexOf(cb); if (i >= 0) handlers.splice(i, 1); };
      } },
      'solana:signAndSendTransaction': { signAndSendTransaction: () => { throw Error('Must never be called'); } },
    },
  } as unknown as Wallet;
  return { wallet, emit: (change: Parameters<typeof handlers[number]>[0]) => handlers.forEach((cb) => cb(change)),
    setResult: (fn: typeof result) => { result = fn; },
    calls: () => ({ connect: connectCalls, disconnect: disconnectCalls }) };
}
function registry(initial: Wallet[] = []) {
  let wallets = initial;
  const listeners = { register: [] as ((...wallets: Wallet[]) => void)[],
    unregister: [] as ((...wallets: Wallet[]) => void)[] };
  const value: WalletRegistry = { get: () => wallets, on: (event, callback) => {
    listeners[event].push(callback);
    return () => { const i = listeners[event].indexOf(callback); if (i >= 0) listeners[event].splice(i, 1); };
  } };
  return { value, set: (next: Wallet[]) => {
    const event = next.length < wallets.length ? 'unregister' : 'register';
    wallets = next; listeners[event].forEach((callback) => callback(...wallets));
  } };
}

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((done) => { resolve = done; });
  return { promise, resolve };
}

test('Phantom and Solflare are discovered without automatic permission prompts', async () => {
  const phantom = setup('Phantom');
  const solflare = setup('Solflare');
  const source = registry([phantom.wallet, solflare.wallet]);
  const session = new WalletIdentitySession(source.value);
  session.start();
  assert.deepEqual(session.snapshot.wallets.map((wallet) => wallet.name), ['Phantom', 'Solflare']);
  assert.equal(phantom.calls().connect, 0);
  assert.equal(solflare.calls().connect, 0);
  await session.connect(session.snapshot.wallets[0].id);
  assert.equal(phantom.calls().connect, 1);
  assert.equal(session.snapshot.status, 'CONNECTED');
  assert.equal(session.snapshot.networkStatus, 'NETWORK_UNVERIFIED');
  assert.equal(session.snapshot.address, account().address);
  await session.disconnect();
  assert.equal(phantom.calls().disconnect, 1);
  assert.equal(session.snapshot.address, null);
  assert.equal(phantom.calls().connect, 1);
  await session.connect(session.snapshot.wallets[0].id); // Manual reconnect only.
  assert.equal(phantom.calls().connect, 2);
  session.dispose();
});

test('wrong network and missing lifecycle capabilities never prompt', async () => {
  const mainnet = setup('Mainnet only', ['solana:mainnet']);
  const broken = setup('Broken');
  delete (broken.wallet.features as Record<string, unknown>)['standard:events'];
  const source = registry([mainnet.wallet, broken.wallet]);
  const session = new WalletIdentitySession(source.value);
  session.start();
  await session.connect(session.snapshot.wallets[0].id);
  assert.equal(session.snapshot.status, 'WRONG_NETWORK');
  await session.connect(session.snapshot.wallets[1].id);
  assert.equal(session.snapshot.status, 'UNSUPPORTED');
  assert.equal(mainnet.calls().connect + broken.calls().connect, 0);
  session.dispose();
});

test('malformed or inconsistent public keys and invalid wallet responses fail closed', async () => {
  const mock = setup();
  const source = registry([mock.wallet]);
  const session = new WalletIdentitySession(source.value);
  session.start();
  mock.setResult(async () => ({ accounts: [{ ...account(), address: 'not-a-public-key' }] }));
  await session.connect(session.snapshot.wallets[0].id);
  assert.equal(session.snapshot.status, 'ERROR');
  assert.equal(session.snapshot.address, null);
  mock.setResult(async () => ({ accounts: [{ ...account(), publicKey: new Uint8Array(32) }] }));
  await session.connect(session.snapshot.wallets[0].id);
  assert.equal(session.snapshot.address, null);
  assert.equal(validateAccount({ ...account(), chains: ['solana:mainnet'] }, mock.wallet), null);
  session.dispose();
});

test('multiple accounts require explicit selection; account and network changes invalidate identity', async () => {
  const mock = setup();
  mock.setResult(async () => ({ accounts: [account(1), account(2)] }));
  const source = registry([mock.wallet]);
  const session = new WalletIdentitySession(source.value);
  session.start();
  await session.connect(session.snapshot.wallets[0].id);
  assert.equal(session.snapshot.status, 'ACCOUNT_CHANGED');
  assert.equal(session.snapshot.address, null);
  session.selectAccount(account(2).address);
  assert.equal(session.snapshot.address, account(2).address);
  mock.emit({ accounts: [account(1)] });
  assert.equal(session.snapshot.status, 'ACCOUNT_CHANGED');
  assert.equal(session.snapshot.address, null);
  session.selectAccount(account(1).address);
  mock.emit({ accounts: [account(1)] }); // Duplicate event preserves the current account.
  assert.equal(session.snapshot.address, account(1).address);
  mock.emit({ chains: ['solana:mainnet'] });
  assert.equal(session.snapshot.status, 'WRONG_NETWORK');
  assert.equal(session.snapshot.address, null);
  const previousCalls = mock.calls().connect;
  await session.connect(session.snapshot.wallets[0].id);
  assert.equal(mock.calls().connect, previousCalls); // Changed chain cannot be bypassed by another click.
  mock.emit({ accounts: [] });
  assert.equal(session.snapshot.status, 'DISCONNECTED');
  session.dispose();
});

test('late connection response cannot resurrect identity after disconnect or unregister', async () => {
  const mock = setup();
  let resolve!: (value: { accounts: readonly WalletAccount[] }) => void;
  mock.setResult(() => new Promise((done) => { resolve = done; }));
  const source = registry([mock.wallet]);
  const session = new WalletIdentitySession(source.value);
  session.start();
  const pending = session.connect(session.snapshot.wallets[0].id);
  mock.emit({ accounts: [account()] });
  await session.disconnect();
  resolve({ accounts: [account()] });
  await pending;
  assert.equal(session.snapshot.status, 'DISCONNECTED');
  assert.equal(session.snapshot.address, null);
  source.set([]);
  assert.equal(session.snapshot.wallets.length, 0);
  session.dispose();
});

test('one account announced before connect resolves remains selectable only after authorization', async () => {
  const mock = setup();
  const authorization = deferred<{ accounts: readonly WalletAccount[] }>();
  mock.setResult(() => authorization.promise);
  const session = new WalletIdentitySession(registry([mock.wallet]).value);
  session.start();
  const pending = session.connect(session.snapshot.wallets[0].id);
  mock.emit({ accounts: [account(1)] });
  assert.equal(session.snapshot.status, 'CONNECTING');
  assert.equal(session.snapshot.address, null);
  authorization.resolve({ accounts: [account(1)] });
  await pending;
  assert.equal(session.snapshot.status, 'CONNECTED');
  assert.equal(session.snapshot.address, account(1).address);
  assert.equal(session.snapshot.networkStatus, 'NETWORK_UNVERIFIED');
  session.dispose();
});

test('multiple accounts announced before authorization require explicit selection', async () => {
  const mock = setup();
  const authorization = deferred<{ accounts: readonly WalletAccount[] }>();
  mock.setResult(() => authorization.promise);
  const session = new WalletIdentitySession(registry([mock.wallet]).value);
  session.start();
  const pending = session.connect(session.snapshot.wallets[0].id);
  mock.emit({ accounts: [account(1), account(2)] });
  mock.emit({ accounts: [account(2), account(1)] }); // Duplicate set in a different order.
  assert.equal(session.snapshot.status, 'CONNECTING');
  authorization.resolve({ accounts: [account(1), account(2)] });
  await pending;
  assert.equal(session.snapshot.status, 'ACCOUNT_CHANGED');
  assert.equal(session.snapshot.address, null);
  session.selectAccount(account(2).address);
  assert.equal(session.snapshot.status, 'CONNECTED');
  assert.equal(session.snapshot.address, account(2).address);
  session.dispose();
});

test('a pending multi-account announcement can authorize one returned account', async () => {
  const mock = setup();
  const authorization = deferred<{ accounts: readonly WalletAccount[] }>();
  mock.setResult(() => authorization.promise);
  const session = new WalletIdentitySession(registry([mock.wallet]).value);
  session.start();
  const pending = session.connect(session.snapshot.wallets[0].id);
  mock.emit({ accounts: [account(1), account(2)] });
  authorization.resolve({ accounts: [account(2)] });
  await pending;
  assert.equal(session.snapshot.status, 'CONNECTED');
  assert.equal(session.snapshot.address, account(2).address);
  session.dispose();
});

test('real chain change while connecting invalidates the late response', async () => {
  const mock = setup();
  const authorization = deferred<{ accounts: readonly WalletAccount[] }>();
  mock.setResult(() => authorization.promise);
  const session = new WalletIdentitySession(registry([mock.wallet]).value);
  session.start();
  const pending = session.connect(session.snapshot.wallets[0].id);
  mock.emit({ accounts: [account(1)] });
  mock.emit({ chains: ['solana:mainnet'] });
  authorization.resolve({ accounts: [account(1)] });
  await pending;
  assert.equal(session.snapshot.status, 'WRONG_NETWORK');
  assert.equal(session.snapshot.networkStatus, 'WRONG_NETWORK');
  assert.equal(session.snapshot.address, null);
  mock.emit({ chains: ['solana:devnet'] });
  mock.emit({ accounts: [account(1)] }); // No authorization survived the chain change.
  assert.equal(session.snapshot.address, null);
  assert.deepEqual(session.snapshot.accounts, []);
  session.dispose();
});

test('unregistration while connecting invalidates the late response', async () => {
  const mock = setup();
  const authorization = deferred<{ accounts: readonly WalletAccount[] }>();
  mock.setResult(() => authorization.promise);
  const source = registry([mock.wallet]);
  const session = new WalletIdentitySession(source.value);
  session.start();
  const pending = session.connect(session.snapshot.wallets[0].id);
  mock.emit({ accounts: [account(1)] });
  source.set([]);
  authorization.resolve({ accounts: [account(1)] });
  await pending;
  assert.equal(session.snapshot.status, 'DISCONNECTED');
  assert.equal(session.snapshot.address, null);
  assert.equal(session.snapshot.wallets.length, 0);
  session.dispose();
});

test('changed or inconsistent accounts during a pending connection fail closed', async () => {
  const mock = setup();
  const source = registry([mock.wallet]);
  const session = new WalletIdentitySession(source.value);
  session.start();
  const first = deferred<{ accounts: readonly WalletAccount[] }>();
  mock.setResult(() => first.promise);
  const pending = session.connect(session.snapshot.wallets[0].id);
  mock.emit({ accounts: [account(1)] });
  mock.emit({ accounts: [account(2)] });
  first.resolve({ accounts: [account(2)] });
  await pending;
  assert.equal(session.snapshot.status, 'ERROR');
  assert.equal(session.snapshot.error, 'ACCOUNT_CHANGED');
  assert.equal(session.snapshot.address, null);
  const second = deferred<{ accounts: readonly WalletAccount[] }>();
  mock.setResult(() => second.promise);
  const retry = session.connect(session.snapshot.wallets[0].id);
  mock.emit({ accounts: [account(1)] });
  second.resolve({ accounts: [account(2)] });
  await retry;
  assert.equal(session.snapshot.status, 'ERROR');
  assert.equal(session.snapshot.address, null);
  session.dispose();
});

test('duplicate events and out-of-order connection responses cannot restore stale identity', async () => {
  const mock = setup();
  const first = deferred<{ accounts: readonly WalletAccount[] }>();
  const second = deferred<{ accounts: readonly WalletAccount[] }>();
  let count = 0;
  mock.setResult(() => ++count === 1 ? first.promise : second.promise);
  const session = new WalletIdentitySession(registry([mock.wallet]).value);
  session.start();
  const id = session.snapshot.wallets[0].id;
  const oldPending = session.connect(id);
  const newPending = session.connect(id);
  mock.emit({ accounts: [account(2)] });
  mock.emit({ accounts: [account(2)] });
  second.resolve({ accounts: [account(2)] });
  await newPending;
  assert.equal(session.snapshot.address, account(2).address);
  first.resolve({ accounts: [account(1)] });
  await oldPending;
  assert.equal(session.snapshot.address, account(2).address);
  assert.equal(session.snapshot.status, 'CONNECTED');
  session.dispose();
});

test('authorization rejection and duplicate events cannot grant an account', async () => {
  const mock = setup();
  const source = registry([mock.wallet]);
  const session = new WalletIdentitySession(source.value);
  session.start();
  mock.setResult(async () => { throw Error('User rejected with private extension detail'); });
  await session.connect(session.snapshot.wallets[0].id);
  assert.equal(session.snapshot.status, 'ERROR');
  assert.equal(session.snapshot.error, 'CONNECTION_FAILED');
  assert.equal(session.snapshot.address, null);
  assert.ok(!JSON.stringify(session.snapshot).includes('private extension detail'));
  mock.setResult(async () => ({ accounts: [account()] }));
  await session.connect(session.snapshot.wallets[0].id);
  mock.emit({ accounts: [account()] });
  mock.emit({ accounts: [account()] });
  assert.equal(session.snapshot.status, 'CONNECTED');
  mock.emit({ chains: ['solana:mainnet'] });
  mock.emit({ chains: ['solana:mainnet'] });
  assert.equal(session.snapshot.address, null);
  assert.equal(session.snapshot.status, 'WRONG_NETWORK');
  session.dispose();
});

test('feature changes invalidate identity even when the wallet object advertises stale features', async () => {
  const mock = setup();
  const source = registry([mock.wallet]);
  const session = new WalletIdentitySession(source.value);
  session.start();
  await session.connect(session.snapshot.wallets[0].id);
  assert.equal(session.snapshot.status, 'CONNECTED');
  mock.emit({ features: {} });
  assert.equal(session.snapshot.status, 'UNSUPPORTED');
  assert.equal(session.snapshot.address, null);
  const calls = mock.calls().connect;
  await session.connect(session.snapshot.wallets[0].id);
  assert.equal(mock.calls().connect, calls);
  session.dispose();
});

test('wallet metadata is inert and no financial capability is exposed', () => {
  const mock = setup('<img src=x onerror=alert(1)>\u0000');
  assert.equal(inspectWallet(mock.wallet).name, '<img src=x onerror=alert(1)>'); // React escapes text.
  assert.equal(WALLET_CAPABILITIES.WALLET_IDENTITY_VERIFIED, false);
  assert.equal(WALLET_CAPABILITIES.TRANSACTION_SIGNING, false);
  assert.equal(WALLET_CAPABILITIES.TRANSACTION_SUBMISSION, false);
  assert.equal(WALLET_CAPABILITIES.FINANCIAL_AUTHORIZATION, false);
  const preview = informationalPreview();
  assert.equal(preview.status, 'INSUFFICIENT_DATA');
  assert.equal(preview.estimated_fee, null);
  assert.equal(preview.recipient, null);
  assert.equal(preview.network, 'solana:devnet');
});

test('provider lifecycle can restart discovery after React StrictMode cleanup', () => {
  const mock = setup();
  const source = registry([mock.wallet]);
  const session = new WalletIdentitySession(source.value);
  session.start();
  assert.equal(session.snapshot.wallets.length, 1);
  session.dispose();
  assert.equal(session.snapshot.address, null);
  session.start();
  assert.equal(session.snapshot.wallets.length, 1);
  assert.equal(mock.calls().connect, 0);
  session.dispose();
});
