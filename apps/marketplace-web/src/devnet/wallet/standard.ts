// @ts-expect-error bs58 v4 has no bundled TypeScript declarations in this workspace.
import bs58 from 'bs58';
import type { Wallet, WalletAccount } from '@wallet-standard/base';

export const DEVNET_CHAIN = 'solana:devnet';
export type IdentityStatus = 'DISCONNECTED' | 'DISCOVERING' | 'CONNECTING' | 'CONNECTED' |
  'UNSUPPORTED' | 'WRONG_NETWORK' | 'ACCOUNT_CHANGED' | 'DISCONNECTING' | 'ERROR';
export type NetworkStatus = 'NETWORK_UNVERIFIED' | 'WRONG_NETWORK';
export type WalletOption = { id: string; name: string; supported: boolean; reason: string | null };
export type PublicAccount = { address: string; label: string | null };
export type IdentitySnapshot = {
  status: IdentityStatus;
  networkStatus: NetworkStatus;
  wallets: WalletOption[];
  walletId: string | null;
  walletName: string | null;
  address: string | null;
  accounts: PublicAccount[];
  error: string | null;
};
export type WalletRegistry = {
  get(): readonly Wallet[];
  on(event: 'register' | 'unregister', callback: (...wallets: Wallet[]) => void): () => void;
};

type Connect = { version: '1.0.0'; connect(input?: { silent?: boolean }): Promise<{ accounts: readonly WalletAccount[] }> };
type Disconnect = { version: '1.0.0'; disconnect(): Promise<void> };
type Events = { version: '1.0.0'; on(event: 'change', callback: (change: {
  accounts?: readonly WalletAccount[]; chains?: readonly string[]; features?: Wallet['features'];
}) => void): () => void };
type ConnectionFeatures = { connect: Connect; disconnect: Disconnect; events: Events };

function safeName(value: unknown): string {
  if (typeof value !== 'string') return 'Unnamed wallet';
  const name = value.replace(/[\u0000-\u001f\u007f-\u009f]/g, '').trim().slice(0, 48);
  return name || 'Unnamed wallet';
}

function featuresOf(wallet: Wallet): ConnectionFeatures | null {
  try {
    const features = wallet.features;
    const connect = features?.['standard:connect'] as Connect | undefined;
    const disconnect = features?.['standard:disconnect'] as Disconnect | undefined;
    const events = features?.['standard:events'] as Events | undefined;
    if (connect?.version !== '1.0.0' || typeof connect.connect !== 'function' ||
      disconnect?.version !== '1.0.0' || typeof disconnect.disconnect !== 'function' ||
      events?.version !== '1.0.0' || typeof events.on !== 'function') return null;
    return { connect, disconnect, events };
  } catch { return null; }
}

function sameAccountSet(left: readonly string[], right: readonly string[]): boolean {
  return left.length === right.length && left.every((address) => right.includes(address));
}

export function inspectWallet(wallet: Wallet): Pick<WalletOption, 'name' | 'supported' | 'reason'> {
  try {
    const name = safeName(wallet.name);
    if (wallet.version !== '1.0.0' || !featuresOf(wallet))
      return { name, supported: false, reason: 'UNSUPPORTED_FEATURES' };
    if (!Array.isArray(wallet.chains) || !wallet.chains.includes(DEVNET_CHAIN))
      return { name, supported: false, reason: 'WRONG_NETWORK' };
    return { name, supported: true, reason: null };
  } catch { return { name: 'Unnamed wallet', supported: false, reason: 'INVALID_WALLET' }; }
}

export function validateAccount(account: WalletAccount, wallet: Wallet): PublicAccount | null {
  try {
    if (typeof account.address !== 'string' || !Array.isArray(account.chains) ||
      !account.chains.includes(DEVNET_CHAIN) || !wallet.chains.includes(DEVNET_CHAIN) ||
      account.chains.some((chain) => !wallet.chains.includes(chain))) return null;
    const bytes = Uint8Array.from(bs58.decode(account.address) as Uint8Array);
    if (bytes.length !== 32 || bs58.encode(bytes) !== account.address ||
      !ArrayBuffer.isView(account.publicKey) || account.publicKey.byteLength !== 32 ||
      bytes.some((byte, i) => byte !== account.publicKey[i])) return null;
    return { address: account.address, label: account.label ? safeName(account.label) : null };
  } catch { return null; }
}

const initial: IdentitySnapshot = {
  status: 'DISCOVERING', networkStatus: 'NETWORK_UNVERIFIED', wallets: [], walletId: null,
  walletName: null, address: null, accounts: [], error: null,
};

export class WalletIdentitySession {
  private registry: WalletRegistry;
  private snapshotValue: IdentitySnapshot = initial;
  private listeners = new Set<() => void>();
  private known = new Map<string, Wallet>();
  private blocked = new Map<string, 'WRONG_NETWORK' | 'UNSUPPORTED_FEATURES'>();
  private nextId = 0;
  private offRegistry: (() => void)[] = [];
  private offWallet: (() => void) | null = null;
  private generation = 0;
  private disposed = false;

  constructor(registry: WalletRegistry) { this.registry = registry; }
  get snapshot(): IdentitySnapshot { return this.snapshotValue; }
  subscribe = (listener: () => void): (() => void) => {
    this.listeners.add(listener);
    return () => { this.listeners.delete(listener); };
  };
  private set(changes: Partial<IdentitySnapshot>) {
    this.snapshotValue = { ...this.snapshotValue, ...changes };
    this.listeners.forEach((listener) => listener());
  }
  start() {
    if (this.offRegistry.length) return;
    this.disposed = false;
    this.offRegistry = [
      this.registry.on('register', () => this.refresh()),
      this.registry.on('unregister', () => this.refresh()),
    ];
    this.refresh();
  }
  dispose() {
    this.disposed = true;
    this.generation++;
    this.offRegistry.forEach((off) => off());
    this.offRegistry = [];
    this.offWallet?.();
    this.offWallet = null;
    this.listeners.clear();
    this.known.clear();
    this.blocked.clear();
    this.nextId = 0;
    this.snapshotValue = { ...initial, status: 'DISCONNECTED' };
  }
  refresh() {
    if (this.disposed) return;
    let announced: readonly Wallet[];
    try { announced = this.registry.get(); }
    catch { this.set({ status: 'ERROR', error: 'DISCOVERY_FAILED' }); return; }
    if (!Array.isArray(announced)) { this.set({ status: 'ERROR', error: 'DISCOVERY_FAILED' }); return; }
    for (const [id, wallet] of this.known) if (!announced.includes(wallet)) {
      this.known.delete(id);
      this.blocked.delete(id);
    }
    for (const wallet of announced) {
      if (!wallet || typeof wallet !== 'object') continue;
      if (![...this.known.values()].includes(wallet)) this.known.set(`wallet-${++this.nextId}`, wallet);
    }
    const wallets = [...this.known].map(([id, wallet]) => {
      const inspected = inspectWallet(wallet);
      const blocked = this.blocked.get(id);
      return { id, ...inspected, supported: inspected.supported && !blocked,
        reason: blocked ?? inspected.reason };
    });
    const selected = this.snapshotValue.walletId;
    if (selected && !this.known.has(selected)) {
      this.generation++;
      this.offWallet?.();
      this.offWallet = null;
      this.set({ wallets, status: 'DISCONNECTED', walletId: null, walletName: null,
        address: null, accounts: [], error: null });
    } else if (selected && (!inspectWallet(this.known.get(selected)!).supported || this.blocked.has(selected))) {
      this.generation++;
      this.offWallet?.();
      this.offWallet = null;
      this.set({ wallets, status: 'UNSUPPORTED', walletId: null, walletName: null,
        address: null, accounts: [], error: 'WALLET_CHANGED' });
    } else this.set({ wallets, status: this.snapshotValue.status === 'DISCOVERING' ? 'DISCONNECTED' : this.snapshotValue.status });
  }
  async connect(id: string): Promise<void> {
    const wallet = this.known.get(id);
    if (!wallet || this.disposed) { this.set({ status: 'UNSUPPORTED', error: 'WALLET_NOT_FOUND' }); return; }
    const blocked = this.blocked.get(id);
    if (blocked) {
      this.set({ status: blocked === 'WRONG_NETWORK' ? 'WRONG_NETWORK' : 'UNSUPPORTED',
        networkStatus: blocked === 'WRONG_NETWORK' ? 'WRONG_NETWORK' : 'NETWORK_UNVERIFIED',
        walletId: id, walletName: inspectWallet(wallet).name, address: null, accounts: [], error: blocked });
      return;
    }
    const inspection = inspectWallet(wallet);
    if (!inspection.supported) {
      this.set({ status: inspection.reason === 'WRONG_NETWORK' ? 'WRONG_NETWORK' : 'UNSUPPORTED',
        networkStatus: inspection.reason === 'WRONG_NETWORK' ? 'WRONG_NETWORK' : 'NETWORK_UNVERIFIED',
        walletId: null, walletName: null, address: null, accounts: [], error: inspection.reason });
      return;
    }
    const features = featuresOf(wallet);
    if (!features) { this.set({ status: 'UNSUPPORTED', error: 'UNSUPPORTED_FEATURES' }); return; }
    const current = ++this.generation;
    this.offWallet?.();
    this.offWallet = null;
    this.set({ status: 'CONNECTING', networkStatus: 'NETWORK_UNVERIFIED',
      walletId: id, walletName: inspection.name, address: null, accounts: [], error: null });
    let announcedAddresses: string[] | null = null;
    let awaitingAuthorization = true;
    let invalidatedBeforeAuthorization = false;
    try {
      this.offWallet = features.events.on('change', (change) => {
        try {
          if (invalidatedBeforeAuthorization && change.accounts !== undefined) return;
          if (current === this.generation && this.snapshotValue.status === 'CONNECTING' &&
            change.accounts !== undefined && change.chains === undefined && change.features === undefined &&
            Array.isArray(change.accounts) && change.accounts.length) {
            const accounts = change.accounts.map((account) => validateAccount(account, wallet));
            if (accounts.every((account) => account !== null)) {
              const addresses = (accounts as PublicAccount[]).map((account) => account.address);
              if (new Set(addresses).size === addresses.length &&
                (!announcedAddresses || sameAccountSet(announcedAddresses, addresses))) {
                // A wallet may announce accounts before connect() resolves. The response still
                // authorizes the identity; this event cannot select an account by itself.
                announcedAddresses = addresses;
                return;
              }
              this.generation++;
              invalidatedBeforeAuthorization = true;
              this.offWallet?.();
              this.offWallet = null;
              this.set({ status: 'ERROR', walletId: null, walletName: null,
                address: null, accounts: [], error: 'ACCOUNT_CHANGED' });
              return;
            }
          }
          const before = this.generation;
          this.changed(wallet, id, change);
          if (awaitingAuthorization && this.generation !== before) invalidatedBeforeAuthorization = true;
        }
        catch {
          this.generation++;
          invalidatedBeforeAuthorization = true;
          this.set({ status: 'ERROR', address: null, accounts: [], error: 'INVALID_WALLET_EVENT' });
        }
      });
      if (current !== this.generation) {
        this.offWallet?.();
        this.offWallet = null;
        return;
      }
      const response = await features.connect.connect(); // Explicit user action; never silent on page load.
      if (current !== this.generation || this.disposed || !this.known.has(id)) return;
      awaitingAuthorization = false;
      if (!inspectWallet(wallet).supported) throw new Error('WALLET_CHANGED');
      if (!response || !Array.isArray(response.accounts)) throw new Error('INVALID_RESPONSE');
      const accounts = response.accounts.map((account) => validateAccount(account, wallet));
      if (accounts.some((account) => account === null) || !accounts.length) throw new Error('INVALID_ACCOUNT');
      const valid = accounts as PublicAccount[];
      const addresses = valid.map((account) => account.address);
      const observed = announcedAddresses as string[] | null;
      if (new Set(addresses).size !== addresses.length ||
        (observed !== null && !addresses.every((address) => observed.includes(address))))
        throw new Error('ACCOUNT_CHANGED');
      this.set({ status: valid.length === 1 ? 'CONNECTED' : 'ACCOUNT_CHANGED',
        networkStatus: 'NETWORK_UNVERIFIED', accounts: valid,
        address: valid.length === 1 ? valid[0].address : null, error: null });
    } catch {
      if (current !== this.generation || this.disposed) return;
      this.offWallet?.();
      this.offWallet = null;
      this.set({ status: 'ERROR', walletId: null, walletName: null, address: null,
        accounts: [], error: 'CONNECTION_FAILED' });
    }
  }
  selectAccount(address: string) {
    if (this.snapshotValue.status !== 'ACCOUNT_CHANGED' ||
      !this.snapshotValue.accounts.some((account) => account.address === address)) return;
    this.set({ status: 'CONNECTED', address, error: null });
  }
  private changed(wallet: Wallet, id: string, change: {
    accounts?: readonly WalletAccount[]; chains?: readonly string[]; features?: Wallet['features'];
  }) {
    if (this.disposed || this.snapshotValue.walletId !== id ||
      this.snapshotValue.status === 'DISCONNECTING' || this.snapshotValue.status === 'DISCONNECTED') return;
    if (change.chains !== undefined || change.features !== undefined) {
      this.generation++;
      const compatible = inspectWallet(wallet).supported &&
        (change.chains === undefined || (Array.isArray(change.chains) && change.chains.includes(DEVNET_CHAIN))) &&
        (change.features === undefined || !!featuresOf({ features: change.features } as Wallet));
      if (compatible) this.blocked.delete(id);
      else this.blocked.set(id, change.chains !== undefined &&
        (!Array.isArray(change.chains) || !change.chains.includes(DEVNET_CHAIN))
        ? 'WRONG_NETWORK' : 'UNSUPPORTED_FEATURES');
      const reason = this.blocked.get(id);
      this.set({ status: compatible ? 'ACCOUNT_CHANGED' : reason === 'WRONG_NETWORK' ? 'WRONG_NETWORK' : 'UNSUPPORTED',
        networkStatus: reason === 'WRONG_NETWORK' ? 'WRONG_NETWORK' : 'NETWORK_UNVERIFIED',
        address: null, accounts: [], error: compatible ? 'NETWORK_CHANGED' : reason ?? 'WALLET_CHANGED',
        wallets: this.snapshotValue.wallets.map((option) => option.id === id
          ? { ...option, supported: compatible, reason: compatible ? null : reason ?? 'WALLET_CHANGED' }
          : option) });
      return;
    }
    if (change.accounts === undefined) return;
    if (Array.isArray(change.accounts) && this.snapshotValue.status === 'CONNECTED' &&
      change.accounts.length === 1 && change.accounts[0]?.address === this.snapshotValue.address &&
      validateAccount(change.accounts[0], wallet)) return;
    this.generation++;
    if (!Array.isArray(change.accounts) || !change.accounts.length) {
      this.set({ status: 'DISCONNECTED', walletId: null, walletName: null, address: null,
        accounts: [], error: null });
      return;
    }
    const accounts = change.accounts.map((account) => validateAccount(account, wallet));
    if (accounts.some((account) => account === null)) {
      this.set({ status: 'ERROR', address: null, accounts: [], error: 'INVALID_ACCOUNT' });
      return;
    }
    const valid = accounts as PublicAccount[];
    this.set({ status: 'ACCOUNT_CHANGED', address: null, accounts: valid, error: 'ACCOUNT_CHANGED' });
  }
  async disconnect() {
    const id = this.snapshotValue.walletId;
    const wallet = id ? this.known.get(id) : null;
    const current = ++this.generation;
    this.offWallet?.();
    this.offWallet = null;
    this.set({ status: 'DISCONNECTING', address: null, accounts: [], error: null });
    try { if (wallet) await featuresOf(wallet)?.disconnect.disconnect(); }
    catch { /* The local identity is still cleared; wallet permission may persist externally. */ }
    if (current === this.generation && !this.disposed)
      this.set({ status: 'DISCONNECTED', walletId: null, walletName: null,
        address: null, accounts: [], networkStatus: 'NETWORK_UNVERIFIED', error: null });
  }
}
