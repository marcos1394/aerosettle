import { ed25519 } from '@noble/curves/ed25519';
// @ts-expect-error bs58 lacks bundled typescript declarations in this workspace
import bs58 from 'bs58';

/**
 * Conatus Economic Data Provenance & Validation Contract
 *
 * Defines strict taxonomy for economic figures across the marketplace:
 * - ONCHAIN_VERIFIED: Directly confirmed state or balance on the Solana ledger (PDA, SPL Token Account, Program Vault).
 * - EXTERNAL_VERIFIED: Cryptographically attested external data (signed telemetry from hardware enclaves, verifier oracle attestations).
 * - SIMULATED: Representative operational dataset (Atlas), projected runway, or financial simulation models.
 *
 * Separates Provenance (ontological source) from ValidationStatus (current verification/network health state).
 */

export type DataProvenance = 'ONCHAIN_VERIFIED' | 'EXTERNAL_VERIFIED' | 'SIMULATED';

export type ValidationStatus =
  | 'VERIFIED'
  | 'PENDING_ATTESTATION'
  | 'PENDING_VALIDATION'
  | 'STALE'
  | 'UNAVAILABLE'
  | 'SIMULATED_PROJECTION';

export interface EconomicMetricMetadata {
  provenance: DataProvenance;
  status: ValidationStatus;
  source: string;
  network: string;
  period: string;
  mint?: string;
  unit?: string;
}

export interface EconomicMetric<T = number> {
  value: T;
  meta: EconomicMetricMetadata;
}

export interface OnchainSolOptions {
  network?: string;
  slot?: number;
  commitment?: string;
  status?: ValidationStatus;
  error?: string;
}

export interface OnchainSplOptions {
  mint: string;
  network?: string;
  slot?: number;
  commitment?: string;
  status?: ValidationStatus;
  error?: string;
}

/**
 * Canonical attestation schema binding domain, network, subject, evidenceHash, nonce, and expiry.
 */
export interface AttestationPayload {
  domain: string; // e.g. 'conatus:attestation:v1'
  network: string; // e.g. 'solana:localnet'
  subject: string; // agent PDA or work order PDA
  evidenceHash: string; // hex or base58 digest of evidence/telemetry
  nonce: string; // unique nonce to prevent replay attacks
  expiresAt: number; // Unix timestamp in seconds (or ms if > 1e11)
  issuedAt?: number;
  economicValue?: number; // optional economic figure
}

export interface ExternalTelemetryOptions {
  verifierAuthority?: string;
  attestationSignature?: string;
  payload?: AttestationPayload;
  isAttested?: boolean;
  verifiedAt?: string;
  error?: string;
  /**
   * Optional isolated verifier instance for testing environments.
   * In production, always falls back to defaultAttestationVerifier.
   */
  verifier?: AttestationVerifier;
}

/**
 * Base58 / Hex decoding helpers for strict byte validation.
 */
function decodeBase58(str: string): Uint8Array | null {
  try {
    const fn = (bs58 as unknown as { default?: { decode: (s: string) => Uint8Array }; decode?: (s: string) => Uint8Array }).default?.decode ??
      (bs58 as unknown as { decode: (s: string) => Uint8Array }).decode;
    if (typeof fn === 'function') {
      return fn(str);
    }
    return null;
  } catch {
    return null;
  }
}

export function encodeBase58(bytes: Uint8Array): string {
  const fn = (bs58 as unknown as { default?: { encode: (b: Uint8Array) => string }; encode?: (b: Uint8Array) => string }).default?.encode ??
    (bs58 as unknown as { encode: (b: Uint8Array) => string }).encode;
  return fn(bytes);
}

function decodeHex(str: string): Uint8Array | null {
  if (str.length % 2 !== 0 || !/^[0-9a-fA-F]+$/.test(str)) return null;
  const arr = new Uint8Array(str.length / 2);
  for (let i = 0; i < str.length; i += 2) {
    arr[i / 2] = parseInt(str.substring(i, i + 2), 16);
  }
  return arr;
}

function decodeSignature(sigStr: string): Uint8Array | null {
  const clean = sigStr.trim();
  if (/^[0-9a-fA-F]{128}$/.test(clean)) {
    return decodeHex(clean);
  }
  const bytes = decodeBase58(clean);
  if (bytes && bytes.length === 64) {
    return bytes;
  }
  return null;
}

function decodePublicKey(pubkeyStr: string): Uint8Array | null {
  const clean = pubkeyStr.trim();
  if (/^[0-9a-fA-F]{64}$/.test(clean)) {
    return decodeHex(clean);
  }
  const bytes = decodeBase58(clean);
  if (bytes && bytes.length === 32) {
    return bytes;
  }
  return null;
}

export class InvalidAttestationPayloadError extends Error {
  constructor(message: string) {
    super(`[Invalid Attestation Payload] ${message}`);
    this.name = 'InvalidAttestationPayloadError';
  }
}

/**
 * Validates the semantic structure and invariants of an AttestationPayload:
 * - Domain and network must be non-empty strings without control characters.
 * - Subject must be a valid account/PDA identifier (Base58 string).
 * - EvidenceHash must be a valid 32-byte cryptographic digest (hex or Base58).
 * - Nonce must be a non-empty unique string.
 * - ExpiresAt must be a positive timestamp.
 */
export function validateAttestationPayload(payload: AttestationPayload): void {
  if (!payload || typeof payload !== 'object') {
    throw new InvalidAttestationPayloadError('Payload must be a non-null object');
  }

  // 1. Domain
  if (typeof payload.domain !== 'string' || payload.domain.trim().length === 0) {
    throw new InvalidAttestationPayloadError('domain must be a non-empty string');
  }
  if (!/^[a-zA-Z0-9_:.-]+$/.test(payload.domain.trim())) {
    throw new InvalidAttestationPayloadError('domain contains illegal characters; expected alphanumeric, underscore, colon, dot, or dash');
  }

  // 2. Network
  if (typeof payload.network !== 'string' || payload.network.trim().length === 0) {
    throw new InvalidAttestationPayloadError('network must be a non-empty string');
  }
  if (!/^[a-zA-Z0-9_:.-]+$/.test(payload.network.trim())) {
    throw new InvalidAttestationPayloadError('network contains illegal characters');
  }

  // 3. Subject (Agent PDA or WorkOrder PDA)
  if (typeof payload.subject !== 'string' || payload.subject.trim().length === 0) {
    throw new InvalidAttestationPayloadError('subject must be a non-empty identifier');
  }
  const cleanSubject = payload.subject.trim();
  if (cleanSubject.length < 10 || cleanSubject.length > 128) {
    throw new InvalidAttestationPayloadError(`subject length (${cleanSubject.length}) out of valid range (10-128 chars)`);
  }

  // 4. Evidence Hash (32-byte digest, 64 hex chars or 32-44 base58 chars)
  if (typeof payload.evidenceHash !== 'string' || payload.evidenceHash.trim().length === 0) {
    throw new InvalidAttestationPayloadError('evidenceHash must be a non-empty cryptographic digest');
  }
  const cleanHash = payload.evidenceHash.trim();
  const isHex64 = /^[0-9a-fA-F]{64}$/.test(cleanHash);
  const isBase58Hash = cleanHash.length >= 32 && cleanHash.length <= 44 && /^[1-9A-HJ-NP-Za-km-z]+$/.test(cleanHash);
  if (!isHex64 && !isBase58Hash) {
    throw new InvalidAttestationPayloadError('evidenceHash must be a valid 32-byte cryptographic digest (64 hex characters or 32-44 Base58 characters)');
  }

  // 5. Nonce
  if (typeof payload.nonce !== 'string' || payload.nonce.trim().length === 0) {
    throw new InvalidAttestationPayloadError('nonce must be a non-empty string');
  }

  // 6. ExpiresAt
  if (typeof payload.expiresAt !== 'number' || !Number.isFinite(payload.expiresAt) || payload.expiresAt <= 0) {
    throw new InvalidAttestationPayloadError('expiresAt must be a positive numeric timestamp');
  }

  // 7. Optional economicValue
  if (payload.economicValue !== undefined && (!Number.isFinite(payload.economicValue) || payload.economicValue < 0)) {
    throw new InvalidAttestationPayloadError('economicValue, when provided, must be a non-negative finite number');
  }
}

/**
 * Encodes a single field using [1-byte tag][4-byte uint32 big-endian length][value bytes].
 */
function encodeLengthPrefixedField(tag: number, valueBytes: Uint8Array): Uint8Array {
  const result = new Uint8Array(1 + 4 + valueBytes.length);
  result[0] = tag;
  const len = valueBytes.length;
  result[1] = (len >>> 24) & 0xff;
  result[2] = (len >>> 16) & 0xff;
  result[3] = (len >>> 8) & 0xff;
  result[4] = len & 0xff;
  result.set(valueBytes, 5);
  return result;
}

/**
 * Serializes an AttestationPayload into an unequivocal, versioned binary format (CON1).
 *
 * Uses unambiguous length-prefixed Tag-Length-Value (TLV) encoding:
 * - Magic header: 4 bytes `CON1` (0x43, 0x4F, 0x4E, 0x01)
 * - Field count: 1 byte
 * - Tag 0x01: domain (UTF-8 string)
 * - Tag 0x02: network (UTF-8 string)
 * - Tag 0x03: subject (UTF-8 string)
 * - Tag 0x04: evidenceHash (UTF-8 string)
 * - Tag 0x05: nonce (UTF-8 string)
 * - Tag 0x06: expiresAt (8 bytes uint64 big-endian timestamp in seconds)
 * - Tag 0x07: economicValue (optional, 8 bytes float64 big-endian)
 *
 * Length-prefixing makes delimiter injection and field boundary collision mathematically impossible.
 */
export function serializeCanonicalAttestation(payload: AttestationPayload): Uint8Array {
  validateAttestationPayload(payload);

  const encoder = new TextEncoder();
  const fields: Uint8Array[] = [
    encodeLengthPrefixedField(0x01, encoder.encode(payload.domain.trim())),
    encodeLengthPrefixedField(0x02, encoder.encode(payload.network.trim())),
    encodeLengthPrefixedField(0x03, encoder.encode(payload.subject.trim())),
    encodeLengthPrefixedField(0x04, encoder.encode(payload.evidenceHash.trim())),
    encodeLengthPrefixedField(0x05, encoder.encode(payload.nonce.trim())),
  ];

  // Tag 0x06: expiresAt as 8-byte uint64 big-endian (seconds)
  const expSec = payload.expiresAt > 1e11 ? Math.floor(payload.expiresAt / 1000) : Math.floor(payload.expiresAt);
  const expBuf = new ArrayBuffer(8);
  new DataView(expBuf).setBigUint64(0, BigInt(expSec), false);
  fields.push(encodeLengthPrefixedField(0x06, new Uint8Array(expBuf)));

  // Tag 0x07: optional economicValue
  if (payload.economicValue !== undefined) {
    const valBuf = new ArrayBuffer(8);
    new DataView(valBuf).setFloat64(0, payload.economicValue, false);
    fields.push(encodeLengthPrefixedField(0x07, new Uint8Array(valBuf)));
  }

  let totalSize = 4 + 1; // Magic + count
  for (const f of fields) {
    totalSize += f.length;
  }

  const result = new Uint8Array(totalSize);
  let offset = 0;
  result[offset++] = 0x43; // 'C'
  result[offset++] = 0x4F; // 'O'
  result[offset++] = 0x4E; // 'N'
  result[offset++] = 0x01; // Version 1
  result[offset++] = fields.length;

  for (const f of fields) {
    result.set(f, offset);
    offset += f.length;
  }

  return result;
}

// ─────────────────────────────────────────────────────────────────────────────
// Clock & Replay Protection Abstractions
// ─────────────────────────────────────────────────────────────────────────────

export interface Clock {
  /** Returns current UNIX timestamp in seconds */
  now(): number;
}

export const SystemClock: Clock = Object.freeze({
  now: () => Math.floor(Date.now() / 1000),
});

export interface NonceReplayStore {
  has(key: string): boolean;
  add(key: string): void;
  clear?(): void;
}

/**
 * Local in-memory nonce store for single-session tab deduplication.
 *
 * ARCHITECTURAL SECURITY NOTE:
 * This in-memory Set ONLY provides local client-side deduplication within the current browser
 * window/session memory. It is NOT a cryptographic anti-replay guarantee for economic transactions
 * across sessions, tabs, devices, or network participants.
 *
 * Economic finality and persistent anti-replay require durable on-chain state verification (e.g.
 * Solana transaction nonce accounts or PDA state transitions) or consensus-backed indexing services
 * implementing the `PersistentAttestationRegistry` interface.
 */
export class InMemoryNonceReplayStore implements NonceReplayStore {
  private readonly nonces = new Set<string>();

  has(key: string): boolean {
    return this.nonces.has(key);
  }

  add(key: string): void {
    this.nonces.add(key);
  }

  clear(): void {
    this.nonces.clear();
  }
}

export const defaultSessionNonceStore: NonceReplayStore = new InMemoryNonceReplayStore();

export function isNonceConsumed(nonce: string, domain: string = 'conatus'): boolean {
  return defaultSessionNonceStore.has(`${domain}:${nonce}`);
}

export function consumeNonce(nonce: string, domain: string = 'conatus'): boolean {
  const key = `${domain}:${nonce}`;
  if (defaultSessionNonceStore.has(key)) {
    return false;
  }
  defaultSessionNonceStore.add(key);
  return true;
}

export function _resetNonceStoreForTesting(): void {
  defaultSessionNonceStore.clear?.();
}

/**
 * Interface for persistent cross-session, distributed attestation anti-replay verification.
 *
 * Future backend or indexing infrastructure will implement this interface against a durable,
 * distributed datastore (e.g., PostgreSQL with transactional row locking, Redis with TTL, or
 * Solana on-chain account state verification) to prevent cross-client or cross-session replay attacks.
 */
export interface PersistentAttestationRegistry {
  /**
   * Checks whether a specific attestation nonce has already been consumed for a given authority.
   * @param verifierAuthority Base58 public key of the verifier
   * @param nonce Unique attestation nonce
   */
  hasNonceBeenConsumed(verifierAuthority: string, nonce: string): Promise<boolean>;

  /**
   * Atomically records an attestation nonce as consumed with an expiration TTL.
   * Rejects if the nonce was already consumed (atomic test-and-set).
   * @param verifierAuthority Base58 public key of the verifier
   * @param nonce Unique attestation nonce
   * @param expiresAt UNIX timestamp in seconds after which the record can be pruned
   * @param metadata Optional contextual audit metadata
   */
  recordNonceConsumption(
    verifierAuthority: string,
    nonce: string,
    expiresAt: number,
    metadata?: Record<string, unknown>
  ): Promise<{ success: boolean; error?: string }>;

  /**
   * Validates whether an attestation signature has been previously indexed or revoked.
   * @param signature 64-byte Ed25519 signature in Base58
   */
  isSignatureRevoked(signature: string): Promise<boolean>;
}

// ─────────────────────────────────────────────────────────────────────────────
// Trust Registry & Attestation Verifier
// ─────────────────────────────────────────────────────────────────────────────

/**
 * Internal private master list of protocol-trusted verifier authorities (Base58 public keys).
 * Kept strictly private to this module and deeply frozen.
 */
const _RAW_PRODUCTION_TRUSTED_AUTHORITIES: readonly string[] = Object.freeze([
  'DmWQhuVujHrJb4jFzo62UnCT3mwnx9GFtVdo8VUu82Wu', // Protocol Verifier Authority (config.ts)
]);

/**
 * Returns a defensive frozen copy of the production trusted verifier authorities list.
 * Prevents callers from obtaining mutable references to the internal registry.
 */
export function getProductionTrustedVerifierAuthorities(): readonly string[] {
  return Object.freeze([..._RAW_PRODUCTION_TRUSTED_AUTHORITIES]);
}

/**
 * Immutable frozen list of production trusted verifier authorities.
 */
export const TRUSTED_VERIFIER_AUTHORITIES: readonly string[] = Object.freeze([
  ..._RAW_PRODUCTION_TRUSTED_AUTHORITIES,
]);

export interface ValidationResult {
  isValid: boolean;
  status: ValidationStatus;
  reason?: string;
}

export interface AttestationVerifier {
  validate(options?: {
    verifierAuthority?: string;
    attestationSignature?: string;
    payload?: AttestationPayload;
    isAttested?: boolean;
  }): ValidationResult;
  isTrusted(pubkey: string): boolean;
}

export class CryptographicAttestationVerifier implements AttestationVerifier {
  private readonly trustedAuthorities: ReadonlySet<string>;
  private readonly clock: Clock;
  private readonly replayStore: NonceReplayStore;

  constructor(options?: {
    trustedAuthorities?: Iterable<string>;
    clock?: Clock;
    replayStore?: NonceReplayStore;
  }) {
    // Defensive copy: create an independent Set instance so that the verifier
    // never shares a mutable reference with callers, external scopes, or other instances.
    const sourceAuthorities = options?.trustedAuthorities ?? _RAW_PRODUCTION_TRUSTED_AUTHORITIES;
    const defensiveSet = new Set<string>();
    for (const auth of sourceAuthorities) {
      if (typeof auth === 'string' && auth.trim().length > 0) {
        defensiveSet.add(auth.trim());
      }
    }
    this.trustedAuthorities = defensiveSet;
    this.clock = options?.clock ?? SystemClock;
    this.replayStore = options?.replayStore ?? defaultSessionNonceStore;
  }

  isTrusted(pubkey: string): boolean {
    if (!pubkey || typeof pubkey !== 'string') return false;
    return this.trustedAuthorities.has(pubkey);
  }

  validate(options?: {
    verifierAuthority?: string;
    attestationSignature?: string;
    payload?: AttestationPayload;
    isAttested?: boolean;
  }): ValidationResult {
    if (!options) {
      return {
        isValid: false,
        status: 'PENDING_ATTESTATION',
        reason: 'No attestation metadata provided',
      };
    }

    // 1. Boolean flag isAttested: true alone is strictly insufficient
    if (options.isAttested && !options.attestationSignature) {
      return {
        isValid: false,
        status: 'PENDING_ATTESTATION',
        reason: 'Boolean flag isAttested=true is insufficient; cryptographic Ed25519 signature is required',
      };
    }

    // 2. Attestation signature must be provided
    if (!options.attestationSignature || typeof options.attestationSignature !== 'string') {
      return {
        isValid: false,
        status: 'PENDING_ATTESTATION',
        reason: 'Missing cryptographic attestation signature',
      };
    }

    const cleanSig = options.attestationSignature.trim();

    // A real Base58 signature may coincidentally contain words such as "fake".
    // Strict decoding and Ed25519 verification reject placeholders safely.
    // 3. Strict 64-byte decoding
    const sigBytes = decodeSignature(cleanSig);
    if (!sigBytes || sigBytes.length !== 64) {
      return {
        isValid: false,
        status: 'PENDING_ATTESTATION',
        reason: 'Signature must be strictly 64 decoded bytes (Ed25519 format)',
      };
    }

    // 4. Verifier authority check: must be a registered trusted authority
    if (!options.verifierAuthority || typeof options.verifierAuthority !== 'string') {
      return {
        isValid: false,
        status: 'PENDING_ATTESTATION',
        reason: 'Missing verifier authority',
      };
    }

    if (!this.isTrusted(options.verifierAuthority)) {
      return {
        isValid: false,
        status: 'PENDING_ATTESTATION',
        reason: `Untrusted or unregistered verifier authority: ${options.verifierAuthority}`,
      };
    }

    const pubKeyBytes = decodePublicKey(options.verifierAuthority);
    if (!pubKeyBytes || pubKeyBytes.length !== 32) {
      return {
        isValid: false,
        status: 'PENDING_ATTESTATION',
        reason: 'Verifier authority public key must be strictly 32 decoded bytes',
      };
    }

    // 5. Attestation payload binding
    if (!options.payload) {
      return {
        isValid: false,
        status: 'PENDING_ATTESTATION',
        reason: 'Missing canonical attestation payload binding (domain, network, subject, evidenceHash, nonce, expiresAt)',
      };
    }

    const { payload } = options;
    try {
      validateAttestationPayload(payload);
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : String(err);
      return {
        isValid: false,
        status: 'PENDING_ATTESTATION',
        reason: `Malformed attestation payload: ${msg}`,
      };
    }

    // 6. Expiration check using trusted clock (untrusted caller cannot alter)
    const currentSec = this.clock.now();
    const expiry = payload.expiresAt > 1e11 ? Math.floor(payload.expiresAt / 1000) : Math.floor(payload.expiresAt);
    if (expiry <= currentSec) {
      return {
        isValid: false,
        status: 'PENDING_ATTESTATION',
        reason: 'Attestation has expired',
      };
    }

    // 7. Nonce replay check
    const replayKey = `${options.verifierAuthority}:${payload.domain}:${payload.nonce}`;
    if (this.replayStore.has(replayKey)) {
      return {
        isValid: false,
        status: 'PENDING_ATTESTATION',
        reason: `Nonce already consumed (replay detected): ${payload.nonce}`,
      };
    }

    // 8. Authentic Ed25519 verification against canonical message
    const canonicalBytes = serializeCanonicalAttestation(payload);
    let isCryptoValid = false;
    try {
      isCryptoValid = ed25519.verify(sigBytes, canonicalBytes, pubKeyBytes);
    } catch {
      isCryptoValid = false;
    }

    if (!isCryptoValid) {
      return {
        isValid: false,
        status: 'PENDING_ATTESTATION',
        reason: 'Cryptographic Ed25519 signature verification failed (forged signature or tampered message)',
      };
    }

    // 9. Consume the nonce upon successful verification to prevent replay
    this.replayStore.add(replayKey);

    return {
      isValid: true,
      status: 'VERIFIED',
    };
  }
}

/**
 * Default production attestation verifier instance using sealed production trusted authorities,
 * the trusted environment system clock, and the default session nonce store.
 */
export const defaultAttestationVerifier: AttestationVerifier = new CryptographicAttestationVerifier();

/**
 * Checks if a public key belongs to the production trusted authorities.
 */
export function isTrustedVerifierAuthority(pubkey: string): boolean {
  return defaultAttestationVerifier.isTrusted(pubkey);
}

/**
 * Validates cryptographic attestation signatures in production using real Ed25519 primitives,
 * the immutable protocol trust registry, and the trusted environment clock.
 *
 * Does NOT permit arbitrary callers to inject test authorities or alter the clock.
 */
export function validateCryptographicAttestation(options?: {
  verifierAuthority?: string;
  attestationSignature?: string;
  payload?: AttestationPayload;
  isAttested?: boolean;
}): ValidationResult {
  return defaultAttestationVerifier.validate(options);
}

/**
 * Factory for creating an isolated attestation verifier instance.
 * Strictly intended for test suites requiring ephemeral keys, custom authorities,
 * mock clocks, or isolated replay stores.
 *
 * Does NOT mutate the production default verifier or the production trust registry.
 */
export function createIsolatedAttestationVerifier(options?: {
  trustedAuthorities?: Iterable<string>;
  clock?: Clock | (() => number);
  replayStore?: NonceReplayStore;
}): AttestationVerifier {
  const clock: Clock =
    typeof options?.clock === 'function'
      ? { now: options.clock }
      : (options?.clock ?? SystemClock);
  return new CryptographicAttestationVerifier({
    trustedAuthorities: options?.trustedAuthorities,
    clock,
    replayStore: options?.replayStore,
  });
}

/**
 * Standard provenance descriptors for Conatus network data sources.
 * Enforces safe, conservative defaults: descriptors never declare VERIFIED
 * until a valid confirmed read (such as confirmed slot > 0) has been established.
 */
export const PROVENANCE_SOURCES = {
  // On-chain verified sources (System Program / Native SOL)
  ONCHAIN_SOL_BALANCE: (
    networkOrOpts?: string | OnchainSolOptions,
    maybeSlot?: number,
    maybeCommitment: string = 'confirmed'
  ): EconomicMetricMetadata => {
    const opts: OnchainSolOptions =
      typeof networkOrOpts === 'object' && networkOrOpts !== null
        ? networkOrOpts
        : {
            network: networkOrOpts,
            slot: maybeSlot,
            commitment: maybeCommitment,
          };

    // Conservative safe default: require confirmed slot or explicit status; otherwise PENDING_VALIDATION
    let status: ValidationStatus;
    if (opts.error) {
      status = 'UNAVAILABLE';
    } else if (opts.status) {
      status = opts.status;
    } else if (opts.slot != null && opts.slot > 0) {
      status = 'VERIFIED';
    } else {
      status = 'PENDING_VALIDATION';
    }

    const network = opts.network || 'Solana Localnet';
    const commitment = opts.commitment || 'confirmed';
    const period = opts.error
      ? 'RPC Query Error'
      : opts.slot != null
        ? `Slot ${opts.slot} (${commitment})`
        : status === 'PENDING_VALIDATION'
          ? 'Pending Confirmation'
          : `Real-time (${commitment})`;

    return {
      provenance: 'ONCHAIN_VERIFIED',
      status,
      source: opts.error
        ? `Solana System Program (Error: ${opts.error})`
        : 'Solana System Program (Native Account)',
      network,
      period,
    };
  },

  // On-chain verified sources (SPL Token Program)
  ONCHAIN_SPL_BALANCE: (
    mintOrOpts: string | OnchainSplOptions,
    network?: string,
    slot?: number,
    commitment: string = 'confirmed'
  ): EconomicMetricMetadata => {
    const opts: OnchainSplOptions =
      typeof mintOrOpts === 'object' && mintOrOpts !== null
        ? mintOrOpts
        : {
            mint: mintOrOpts,
            network,
            slot,
            commitment,
          };

    // Conservative safe default: require confirmed slot or explicit status; otherwise PENDING_VALIDATION
    let status: ValidationStatus;
    if (opts.error) {
      status = 'UNAVAILABLE';
    } else if (opts.status) {
      status = opts.status;
    } else if (opts.slot != null && opts.slot > 0) {
      status = 'VERIFIED';
    } else {
      status = 'PENDING_VALIDATION';
    }

    const net = opts.network || 'Solana Localnet';
    const cmt = opts.commitment || 'confirmed';
    const shortMint =
      opts.mint.length > 12
        ? `${opts.mint.slice(0, 6)}...${opts.mint.slice(-4)}`
        : opts.mint;
    const period = opts.error
      ? 'RPC Query Error'
      : opts.slot != null
        ? `Slot ${opts.slot} (${cmt})`
        : status === 'PENDING_VALIDATION'
          ? 'Pending Confirmation'
          : `Real-time (${cmt})`;

    return {
      provenance: 'ONCHAIN_VERIFIED',
      status,
      source: opts.error
        ? `Solana Token Program (Error: ${opts.error})`
        : `Solana Token Program (SPL Account: ${shortMint})`,
      network: net,
      period,
    };
  },

  ONCHAIN_ESCROW_VAULT: (
    network: string = 'Solana Localnet',
    status?: ValidationStatus,
    slot?: number
  ): EconomicMetricMetadata => {
    const resolvedStatus: ValidationStatus =
      status ?? (slot != null && slot > 0 ? 'VERIFIED' : 'PENDING_VALIDATION');
    return {
      provenance: 'ONCHAIN_VERIFIED',
      status: resolvedStatus,
      source: 'AeroSettle Program Escrow Vault (PDA)',
      network: network || 'Solana Localnet',
      period: slot ? `Slot ${slot} (Finalized)` : 'Pending Finality',
    };
  },

  ONCHAIN_WORK_ORDERS: (
    network: string = 'Solana Localnet',
    status?: ValidationStatus,
    slot?: number
  ): EconomicMetricMetadata => {
    const resolvedStatus: ValidationStatus =
      status ?? (slot != null && slot > 0 ? 'VERIFIED' : 'PENDING_VALIDATION');
    return {
      provenance: 'ONCHAIN_VERIFIED',
      status: resolvedStatus,
      source: 'WorkOrder Registry Program Accounts (PDA)',
      network: network || 'Solana Localnet',
      period: slot ? `Slot ${slot} (Ledger State)` : 'Pending Ledger State',
    };
  },

  ONCHAIN_AGENT_REGISTRY: (
    network: string = 'Solana Localnet',
    status?: ValidationStatus,
    slot?: number
  ): EconomicMetricMetadata => {
    const resolvedStatus: ValidationStatus =
      status ?? (slot != null && slot > 0 ? 'VERIFIED' : 'PENDING_VALIDATION');
    return {
      provenance: 'ONCHAIN_VERIFIED',
      status: resolvedStatus,
      source: 'Agent Registry Program Accounts (PDA)',
      network: network || 'Solana Localnet',
      period: slot ? `Slot ${slot} (Ledger State)` : 'Pending Ledger State',
    };
  },

  // External verified sources — REQUIRE authentic Ed25519 signature from a registered trusted verifier
  EXTERNAL_TELEMETRY: (
    optionsOrVerifier?: string | ExternalTelemetryOptions
  ): EconomicMetricMetadata => {
    const opts: ExternalTelemetryOptions =
      typeof optionsOrVerifier === 'object' && optionsOrVerifier !== null
        ? optionsOrVerifier
        : { verifierAuthority: optionsOrVerifier };

    if (opts.error) {
      return {
        provenance: 'EXTERNAL_VERIFIED',
        status: 'UNAVAILABLE',
        source: `Hardware Enclave Attestation Error: ${opts.error}`,
        network: 'Off-chain Cryptographic Oracle',
        period: 'Execution Window',
      };
    }

    // Authentic Ed25519 cryptographic signature and trusted verifier authority verification
    const verifier = opts.verifier ?? defaultAttestationVerifier;
    const validation = verifier.validate({
      verifierAuthority: opts.verifierAuthority,
      attestationSignature: opts.attestationSignature,
      payload: opts.payload,
      isAttested: opts.isAttested,
    });

    const status: ValidationStatus = validation.status;

    const source = validation.isValid
      ? `Hardware Enclave Ed25519 (Signature: ${opts.attestationSignature!.slice(0, 8)}... Verified by: ${opts.verifierAuthority!.slice(0, 6)}...)`
      : opts.verifierAuthority
        ? `Designated Verifier Oracle (${opts.verifierAuthority.slice(0, 6)}... awaiting attestation)`
        : 'Hardware Enclave Ed25519 (Awaiting Attestation Signature)';

    return {
      provenance: 'EXTERNAL_VERIFIED',
      status,
      source,
      network: 'Off-chain Cryptographic Oracle',
      period: opts.verifiedAt ? `Attested ${opts.verifiedAt}` : 'Execution Window',
    };
  },

  EXTERNAL_PENDING_ATTESTATION: (verifierAuthority?: string): EconomicMetricMetadata => ({
    provenance: 'EXTERNAL_VERIFIED',
    status: 'PENDING_ATTESTATION',
    source: verifierAuthority
      ? `Designated Verifier Oracle (${verifierAuthority.slice(0, 6)}...)`
      : 'Designated Verifier Oracle (Pending Signature)',
    network: 'Off-chain Attestation Pipeline',
    period: 'Awaiting Settlement Oracle',
  }),

  // Off-chain compute / Algorithmic candidate matching
  OFFCHAIN_EVALUATION: (options?: {
    engineName?: string;
    status?: ValidationStatus;
    evaluatedAt?: string;
  }): EconomicMetricMetadata => {
    const baseName = options?.engineName ?? 'AeroSettle Matching Engine';
    const source = baseName.includes('Algorithmic Evaluation')
      ? baseName
      : `${baseName} (Algorithmic Evaluation)`;
    return {
      provenance: 'EXTERNAL_VERIFIED',
      status: options?.status ?? 'PENDING_ATTESTATION',
      source,
      network: 'Off-chain Compute Node',
      period: options?.evaluatedAt ? `Evaluated ${options.evaluatedAt}` : 'Real-time Evaluation',
    };
  },

  // Simulated sources
  SIMULATED_ATLAS_SNAPSHOT: (metricName: string): EconomicMetricMetadata => ({
    provenance: 'SIMULATED',
    status: 'SIMULATED_PROJECTION',
    source: `Atlas Representative Snapshot v0.4 (${metricName})`,
    network: 'Deterministic Simulation Engine',
    period: '30-day Rolling Model',
  }),

  SIMULATED_AGENT_ECONOMICS: (agentName: string): EconomicMetricMetadata => ({
    provenance: 'SIMULATED',
    status: 'SIMULATED_PROJECTION',
    source: `Atlas Conatus Model (${agentName})`,
    network: 'Simulated Environment',
    period: '30-day Window / Current Burn',
  }),

  SIMULATED_FLEET_PROJECTION: (): EconomicMetricMetadata => ({
    provenance: 'SIMULATED',
    status: 'SIMULATED_PROJECTION',
    source: 'Operator Fleet Model (Atlas Scenario)',
    network: 'Simulated Environment',
    period: '30-day Projected Runway',
  }),
};

// ─────────────────────────────────────────────────────────────────────────────
// Typed Provenance Aggregation Protection & Financial Guardrails
// ─────────────────────────────────────────────────────────────────────────────

/**
 * ARCHITECTURAL & FINANCIAL GUARDRAIL:
 *
 * The provenance arithmetic helpers (`addMetrics`, `sumMetrics`, `averageMetrics`, `reduceMetrics`)
 * enforce EPISTEMOLOGICAL DATA PROVENANCE COMPATIBILITY ONLY.
 *
 * They prevent the silent, corrupting aggregation of verified on-chain ledger state with simulated
 * or projected Atlas scenarios.
 *
 * THEY DO NOT CONSTITUTE A FINANCIAL LEDGER OR ACCOUNTING ENGINE.
 *
 * Legitimate economic and monetary aggregation across tokens and network states requires
 * strict multi-dimensional compatibility:
 * 1. Asset & Mint Compatibility: You cannot add USDC with native SOL or disparate SPL mints without
 *    an explicit, authenticated exchange rate or automated market maker (AMM) pool pricing.
 * 2. Network & Cluster Compatibility: Balances from 'Solana Mainnet' cannot be summed with 'Localnet'
 *    or 'Devnet' balances without creating fictitious asset totals.
 * 3. Unit & Decimals Alignment: Atomic units (e.g. lamports with 9 decimals vs USDC micro-units with
 *    6 decimals) must not be combined without decimal normalization.
 *
 * Do NOT use these provenance helpers as a substitute for on-chain ledger state or proper double-entry
 * financial accounting.
 */

export class IncompatibleProvenanceAggregationError extends Error {
  public readonly operandProvenances: DataProvenance[];
  public readonly context: string;

  constructor(operandProvenances: DataProvenance[], context: string) {
    const list = operandProvenances.join(' + ');
    super(
      `[Provenance Aggregation Error] Cannot aggregate metrics with incompatible provenances (${list}) in "${context}". Segregate on-chain verified balances from simulated projections into distinct buckets.`
    );
    this.name = 'IncompatibleProvenanceAggregationError';
    this.operandProvenances = operandProvenances;
    this.context = context;
  }
}

/**
 * Validates whether two provenances are compatible for arithmetic operations.
 * - ONCHAIN_VERIFIED + SIMULATED => INCOMPATIBLE
 * - EXTERNAL_VERIFIED + SIMULATED => INCOMPATIBLE
 * - Same provenance => COMPATIBLE
 */
export function areProvenancesCompatible(a: DataProvenance, b: DataProvenance): boolean {
  if (a === b) return true;
  if (a === 'SIMULATED' || b === 'SIMULATED') return false;
  return a === b;
}

/**
 * Type-safe addition of two EconomicMetrics.
 * Validates operand provenances before calculation.
 * Throws IncompatibleProvenanceAggregationError if operands mix verified and simulated data.
 */
export function addMetrics(
  a: EconomicMetric<number>,
  b: EconomicMetric<number>,
  context: string = 'Metric Addition'
): EconomicMetric<number> {
  if (!areProvenancesCompatible(a.meta.provenance, b.meta.provenance)) {
    throw new IncompatibleProvenanceAggregationError(
      [a.meta.provenance, b.meta.provenance],
      context
    );
  }

  // Currency / Mint compatibility guardrail
  if (a.meta.mint && b.meta.mint && a.meta.mint !== b.meta.mint) {
    throw new IncompatibleProvenanceAggregationError(
      [a.meta.provenance, b.meta.provenance],
      `${context}: Incompatible token mints (${a.meta.mint} vs ${b.meta.mint}). Currency conversion required.`
    );
  }

  // Monetary unit compatibility guardrail
  if (a.meta.unit && b.meta.unit && a.meta.unit !== b.meta.unit) {
    throw new IncompatibleProvenanceAggregationError(
      [a.meta.provenance, b.meta.provenance],
      `${context}: Incompatible monetary units (${a.meta.unit} vs ${b.meta.unit}). Normalization required.`
    );
  }

  let status: ValidationStatus = 'VERIFIED';
  if (a.meta.provenance === 'SIMULATED') {
    status = 'SIMULATED_PROJECTION';
  } else if (a.meta.status === 'UNAVAILABLE' || b.meta.status === 'UNAVAILABLE') {
    status = 'UNAVAILABLE';
  } else if (a.meta.status === 'STALE' || b.meta.status === 'STALE') {
    status = 'STALE';
  } else if (a.meta.status === 'PENDING_VALIDATION' || b.meta.status === 'PENDING_VALIDATION') {
    status = 'PENDING_VALIDATION';
  } else if (a.meta.status === 'PENDING_ATTESTATION' || b.meta.status === 'PENDING_ATTESTATION') {
    status = 'PENDING_ATTESTATION';
  }

  return {
    value: a.value + b.value,
    meta: {
      provenance: a.meta.provenance,
      status,
      source: `Composite (${context})`,
      network: a.meta.network === b.meta.network ? a.meta.network : 'Multi-Network',
      period: a.meta.period,
      mint: a.meta.mint === b.meta.mint ? a.meta.mint : undefined,
      unit: a.meta.unit === b.meta.unit ? a.meta.unit : undefined,
    },
  };
}

/**
 * Type-safe summation of an array of EconomicMetrics.
 * Validates that all operand metrics share a compatible provenance.
 * Throws IncompatibleProvenanceAggregationError if operands mix verified and simulated data.
 */
export function sumMetrics(
  metrics: EconomicMetric<number>[],
  context: string = 'Metric Summation'
): EconomicMetric<number> {
  if (metrics.length === 0) {
    return {
      value: 0,
      meta: PROVENANCE_SOURCES.SIMULATED_ATLAS_SNAPSHOT('Empty Sum'),
    };
  }

  const first = metrics[0];
  const distinctProvenances = Array.from(new Set(metrics.map((m) => m.meta.provenance)));

  for (let i = 1; i < distinctProvenances.length; i++) {
    if (!areProvenancesCompatible(distinctProvenances[0], distinctProvenances[i])) {
      throw new IncompatibleProvenanceAggregationError(distinctProvenances, context);
    }
  }

  // Currency / Mint compatibility guardrail
  const distinctMints = Array.from(new Set(metrics.map((m) => m.meta.mint).filter(Boolean)));
  if (distinctMints.length > 1) {
    throw new IncompatibleProvenanceAggregationError(
      distinctProvenances,
      `${context}: Incompatible token mints (${distinctMints.join(', ')}). Currency conversion required.`
    );
  }

  // Monetary unit compatibility guardrail
  const distinctUnits = Array.from(new Set(metrics.map((m) => m.meta.unit).filter(Boolean)));
  if (distinctUnits.length > 1) {
    throw new IncompatibleProvenanceAggregationError(
      distinctProvenances,
      `${context}: Incompatible monetary units (${distinctUnits.join(', ')}). Normalization required.`
    );
  }

  const totalValue = metrics.reduce((sum, m) => sum + m.value, 0);
  let status: ValidationStatus =
    first.meta.provenance === 'SIMULATED' ? 'SIMULATED_PROJECTION' : 'VERIFIED';

  if (metrics.some((m) => m.meta.status === 'UNAVAILABLE')) {
    status = 'UNAVAILABLE';
  } else if (metrics.some((m) => m.meta.status === 'STALE')) {
    status = 'STALE';
  } else if (metrics.some((m) => m.meta.status === 'PENDING_VALIDATION')) {
    status = 'PENDING_VALIDATION';
  } else if (metrics.some((m) => m.meta.status === 'PENDING_ATTESTATION')) {
    status = 'PENDING_ATTESTATION';
  }

  return {
    value: totalValue,
    meta: {
      provenance: first.meta.provenance,
      status,
      source: `Sum of ${metrics.length} metrics (${context})`,
      network: first.meta.network,
      period: first.meta.period,
    },
  };
}

/**
 * Type-safe average of an array of EconomicMetrics.
 */
export function averageMetrics(
  metrics: EconomicMetric<number>[],
  context: string = 'Metric Average'
): EconomicMetric<number> {
  if (metrics.length === 0) {
    return {
      value: 0,
      meta: PROVENANCE_SOURCES.SIMULATED_ATLAS_SNAPSHOT('Empty Average'),
    };
  }
  const sum = sumMetrics(metrics, context);
  return {
    value: sum.value / metrics.length,
    meta: {
      ...sum.meta,
      source: `Average of ${metrics.length} metrics (${context})`,
    },
  };
}

/**
 * Type-safe reduction of an array of EconomicMetrics.
 */
export function reduceMetrics(
  metrics: EconomicMetric<number>[],
  reducer: (acc: number, curr: number) => number,
  initialValue: number,
  context: string = 'Metric Reduction'
): EconomicMetric<number> {
  if (metrics.length === 0) {
    return {
      value: initialValue,
      meta: PROVENANCE_SOURCES.SIMULATED_ATLAS_SNAPSHOT('Empty Reduction'),
    };
  }
  const distinctProvenances = Array.from(new Set(metrics.map((m) => m.meta.provenance)));
  for (let i = 1; i < distinctProvenances.length; i++) {
    if (!areProvenancesCompatible(distinctProvenances[0], distinctProvenances[i])) {
      throw new IncompatibleProvenanceAggregationError(distinctProvenances, context);
    }
  }

  // Currency / Mint compatibility guardrail
  const distinctMints = Array.from(new Set(metrics.map((m) => m.meta.mint).filter(Boolean)));
  if (distinctMints.length > 1) {
    throw new IncompatibleProvenanceAggregationError(
      distinctProvenances,
      `${context}: Incompatible token mints (${distinctMints.join(', ')}). Currency conversion required.`
    );
  }

  // Monetary unit compatibility guardrail
  const distinctUnits = Array.from(new Set(metrics.map((m) => m.meta.unit).filter(Boolean)));
  if (distinctUnits.length > 1) {
    throw new IncompatibleProvenanceAggregationError(
      distinctProvenances,
      `${context}: Incompatible monetary units (${distinctUnits.join(', ')}). Normalization required.`
    );
  }

  const reducedValue = metrics.reduce((acc, m) => reducer(acc, m.value), initialValue);
  const sample = sumMetrics(metrics, context);

  return {
    value: reducedValue,
    meta: {
      ...sample.meta,
      source: `Reduction of ${metrics.length} metrics (${context})`,
    },
  };
}

/**
 * Asserts that multiple metrics can coexist in the same user view / dashboard
 * while strictly remaining segregated in separate buckets.
 * This operation NEVER throws for coexistence across different provenances.
 */
export function assertCoexistenceOnly(
  metrics: (EconomicMetric<unknown> | { provenance: DataProvenance })[],
  context: string = 'Coexistence Display'
): void {
  // Coexistence is explicitly valid; verifies that segregation is acknowledged
  if (!metrics || metrics.length === 0) return;
  // Does not perform arithmetic aggregation, so no incompatibility error
}

/**
 * @deprecated Prefer typed metric operations (`addMetrics`, `sumMetrics`, `averageMetrics`)
 * for compile-time and runtime provenance safety.
 *
 * Runtime boundary guardrail: verifies that segregated values are not arithmetically folded.
 *
 * Supported forms:
 * 1. assertNoSilentAggregation(aggregateValue, { verified, simulated }, context, strict?)
 * 2. assertNoSilentAggregation(verified, simulated, aggregateValue, context, strict?)
 * 3. assertNoSilentAggregation(verified, simulated, context, strict?) -> Coexistence assertion (does NOT throw)
 */
export function assertNoSilentAggregation(
  arg1: number | EconomicMetric<number>,
  arg2: { verified: number; simulated: number } | number | EconomicMetric<number>,
  arg3?: string | number,
  arg4?: string | boolean,
  arg5: boolean = true
): void {
  // If typed EconomicMetrics are provided, delegate to strict provenance compatibility check
  if (
    typeof arg1 === 'object' &&
    arg1 !== null &&
    'meta' in arg1 &&
    typeof arg2 === 'object' &&
    arg2 !== null &&
    'meta' in arg2
  ) {
    if (!areProvenancesCompatible(arg1.meta.provenance, arg2.meta.provenance)) {
      const context = typeof arg3 === 'string' ? arg3 : 'Legacy Assertion';
      throw new IncompatibleProvenanceAggregationError(
        [arg1.meta.provenance, arg2.meta.provenance],
        context
      );
    }
    return;
  }

  let aggregateValue: number | undefined;
  let verified: number;
  let simulated: number;
  let context: string;
  let strict = true;

  if (typeof arg2 === 'object' && arg2 !== null && 'verified' in arg2) {
    // Form 1: assertNoSilentAggregation(aggregateValue, { verified, simulated }, context, strict?)
    aggregateValue = arg1 as number;
    verified = arg2.verified;
    simulated = arg2.simulated;
    context = typeof arg3 === 'string' ? arg3 : 'Unknown Context';
    if (typeof arg4 === 'boolean') strict = arg4;
  } else if (typeof arg1 === 'number' && typeof arg2 === 'number' && typeof arg3 === 'number') {
    // Form 2: assertNoSilentAggregation(verified, simulated, aggregateValue, context, strict?)
    verified = arg1;
    simulated = arg2;
    aggregateValue = arg3;
    context = typeof arg4 === 'string' ? arg4 : 'Unknown Context';
    if (typeof arg5 === 'boolean') strict = arg5;
  } else {
    // Form 3: assertNoSilentAggregation(verified, simulated, context, strict?)
    // Coexistence check: showing a verified balance (e.g. 10) and a simulated portfolio (e.g. 18,420)
    // simultaneously in separate buckets is completely valid and must NOT throw.
    verified = typeof arg1 === 'number' ? arg1 : 0;
    simulated = typeof arg2 === 'number' ? arg2 : 0;
    context = typeof arg3 === 'string' ? arg3 : 'Unknown Context';
    if (typeof arg4 === 'boolean') strict = arg4;
    aggregateValue = undefined;
  }

  // If an aggregateValue was computed or provided, verify that it does NOT fold both sources together
  if (aggregateValue !== undefined && verified > 0 && simulated > 0) {
    const isArithmeticFold = aggregateValue === verified + simulated;

    if (isArithmeticFold) {
      const errorMsg = `[Conatus Provenance Guardrail Violation] Incompatible economic aggregation in "${context}": cannot fold verified balance (${verified}) and simulated projection (${simulated}) into a single aggregate (${aggregateValue}). Maintain separate, explicitly tagged buckets.`;
      if (strict) {
        throw new Error(errorMsg);
      } else {
        console.warn(errorMsg);
      }
    }
  }
}

/**
 * Segregates an array of items into distinct provenance buckets to prevent accidental aggregation.
 */
export function segregateByProvenance<T extends { provenance?: DataProvenance }>(
  items: T[]
): {
  onChainVerified: T[];
  externalVerified: T[];
  simulated: T[];
} {
  const onChainVerified: T[] = [];
  const externalVerified: T[] = [];
  const simulated: T[] = [];

  for (const item of items) {
    if (item.provenance === 'ONCHAIN_VERIFIED') {
      onChainVerified.push(item);
    } else if (item.provenance === 'EXTERNAL_VERIFIED') {
      externalVerified.push(item);
    } else {
      simulated.push(item);
    }
  }

  return { onChainVerified, externalVerified, simulated };
}

/**
 * Creates an economic metric bundle with guaranteed provenance metadata.
 */
export function makeMetric<T = number>(
  value: T,
  meta: EconomicMetricMetadata
): EconomicMetric<T> {
  return { value, meta };
}

/**
 * Maps ValidationStatus to visual color tones.
 */
export function getStatusTone(status: ValidationStatus): 'success' | 'accent' | 'warning' | 'error' | 'muted' {
  switch (status) {
    case 'VERIFIED':
      return 'success';
    case 'PENDING_ATTESTATION':
    case 'PENDING_VALIDATION':
      return 'accent';
    case 'STALE':
    case 'SIMULATED_PROJECTION':
      return 'warning';
    case 'UNAVAILABLE':
      return 'error';
    default:
      return 'muted';
  }
}

/**
 * UI visual tone, badge CSS class, and icon based on provenance AND status.
 * Guarantees that unconfirmed, pending, stale, or unavailable metrics NEVER display as verified.
 */
export function getProvenanceVisuals(
  provenance: DataProvenance,
  locale: 'en' | 'es' = 'en',
  status?: ValidationStatus
): {
  tone: 'success' | 'accent' | 'warning' | 'error' | 'muted';
  label: string;
  badgeClass: string;
  iconName: 'check' | 'shield' | 'spark' | 'alert' | 'clock';
} {
  const isEs = locale === 'es';

  // 1. UNAVAILABLE: Error state takes highest precedence
  if (status === 'UNAVAILABLE') {
    return {
      tone: 'error',
      label: isEs ? 'No Disponible' : 'Unavailable',
      badgeClass: 'provenance-badge-unavailable',
      iconName: 'alert',
    };
  }

  // 2. STALE: Obsolete data state
  if (status === 'STALE') {
    return {
      tone: 'warning',
      label: isEs ? 'Dato Obsoleto' : 'Stale Data',
      badgeClass: 'provenance-badge-stale',
      iconName: 'alert',
    };
  }

  // 3. PENDING_VALIDATION: In-flight or unconfirmed read
  if (status === 'PENDING_VALIDATION') {
    return {
      tone: 'accent',
      label: isEs ? 'Validación Pendiente' : 'Pending Validation',
      badgeClass: 'provenance-badge-pending',
      iconName: 'clock',
    };
  }

  // 4. PENDING_ATTESTATION: Awaiting cryptographic attestation
  if (status === 'PENDING_ATTESTATION') {
    return {
      tone: 'accent',
      label: isEs ? 'Atestación Pendiente' : 'Pending Attestation',
      badgeClass: 'provenance-badge-pending',
      iconName: 'shield',
    };
  }

  // 5. SIMULATED_PROJECTION or SIMULATED provenance
  if (status === 'SIMULATED_PROJECTION' || provenance === 'SIMULATED') {
    return {
      tone: 'warning',
      label: isEs ? 'Escenario Simulado' : 'Simulated Scenario',
      badgeClass: 'provenance-badge-simulated',
      iconName: 'spark',
    };
  }

  // 6. Only when status is explicitly VERIFIED can it display verified visuals!
  if (status === 'VERIFIED') {
    if (provenance === 'ONCHAIN_VERIFIED') {
      return {
        tone: 'success',
        label: isEs ? 'On-chain Verificado' : 'On-chain Verified',
        badgeClass: 'provenance-badge-onchain',
        iconName: 'check',
      };
    }
    if (provenance === 'EXTERNAL_VERIFIED') {
      return {
        tone: 'accent',
        label: isEs ? 'Externo Verificado' : 'External Verified',
        badgeClass: 'provenance-badge-external',
        iconName: 'shield',
      };
    }
  }

  // Fallback: If status is not VERIFIED, NEVER display as verified
  return {
    tone: 'muted',
    label: isEs ? 'Estado No Confirmado' : 'Unconfirmed State',
    badgeClass: 'provenance-badge-pending',
    iconName: 'clock',
  };
}

export function getStatusLabel(
  status: ValidationStatus,
  locale: 'en' | 'es' = 'en'
): string {
  switch (status) {
    case 'VERIFIED':
      return locale === 'es' ? 'Verificado' : 'Verified';
    case 'PENDING_ATTESTATION':
      return locale === 'es' ? 'Atestación Pendiente' : 'Pending Attestation';
    case 'PENDING_VALIDATION':
      return locale === 'es' ? 'Validación Pendiente' : 'Pending Validation';
    case 'STALE':
      return locale === 'es' ? 'Dato Obsoleto' : 'Stale Data';
    case 'UNAVAILABLE':
      return locale === 'es' ? 'No Disponible' : 'Unavailable';
    case 'SIMULATED_PROJECTION':
      return locale === 'es' ? 'Proyección Simulada' : 'Simulated Projection';
  }
}
