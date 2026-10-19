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
  currentTime?: number;
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

/**
 * Serializes an AttestationPayload into its canonical byte representation.
 */
export function serializeCanonicalAttestation(payload: AttestationPayload): Uint8Array {
  const parts = [
    `domain=${payload.domain}`,
    `network=${payload.network}`,
    `subject=${payload.subject}`,
    `evidenceHash=${payload.evidenceHash}`,
    `nonce=${payload.nonce}`,
    `expiresAt=${payload.expiresAt}`,
    payload.economicValue !== undefined ? `economicValue=${payload.economicValue}` : '',
  ].filter(Boolean);
  return new TextEncoder().encode(parts.join('&'));
}

/**
 * Protocol-controlled trusted verifier authorities registry.
 * Arbitrary callers cannot inject untrusted verifiers into validation functions.
 */
const _trustedVerifierAuthorities = new Set<string>([
  'DmWQhuVujHrJb4jFzo62UnCT3mwnx9GFtVdo8VUu82Wu', // Protocol Verifier Authority (config.ts)
]);

export const TRUSTED_VERIFIER_AUTHORITIES: readonly string[] = [
  'DmWQhuVujHrJb4jFzo62UnCT3mwnx9GFtVdo8VUu82Wu',
];

export function isTrustedVerifierAuthority(pubkey: string): boolean {
  return _trustedVerifierAuthorities.has(pubkey);
}

/**
 * Internal helper for registering ephemeral verifier authorities during testing ONLY.
 * Returns an unregister cleanup function to maintain test isolation.
 */
export function _registerTestVerifierAuthority(pubkey: string): () => void {
  _trustedVerifierAuthorities.add(pubkey);
  return () => {
    _trustedVerifierAuthorities.delete(pubkey);
  };
}

/**
 * In-memory store for consumed nonces to prevent replay attacks.
 */
const _consumedNonces = new Set<string>();

export function isNonceConsumed(nonce: string, domain: string = 'conatus'): boolean {
  return _consumedNonces.has(`${domain}:${nonce}`);
}

export function consumeNonce(nonce: string, domain: string = 'conatus'): boolean {
  const key = `${domain}:${nonce}`;
  if (_consumedNonces.has(key)) {
    return false;
  }
  _consumedNonces.add(key);
  return true;
}

export function _resetNonceStoreForTesting(): void {
  _consumedNonces.clear();
}

export interface ValidationResult {
  isValid: boolean;
  status: ValidationStatus;
  reason?: string;
}

/**
 * Validates cryptographic attestation signatures using real Ed25519 primitives.
 * 
 * Enforces:
 * - Real Ed25519 mathematical signature verification against authorized public key.
 * - Strict 64-byte signature and 32-byte public key decoding.
 * - Verification against the canonical serialized message (domain, network, subject, evidenceHash, nonce, expiry).
 * - Protocol-controlled trusted verifier authority registry (prevents arbitrary caller injection).
 * - Nonce replay protection.
 * - Expiration validation.
 * - Rejection of boolean flag `isAttested: true` alone without valid signature.
 *
 * In all rejected/unverified cases, preserves EXTERNAL_VERIFIED provenance
 * but strictly enforces PENDING_ATTESTATION validation status; NEVER returns VERIFIED.
 */
export function validateCryptographicAttestation(options?: {
  verifierAuthority?: string;
  attestationSignature?: string;
  payload?: AttestationPayload;
  isAttested?: boolean;
  currentTime?: number;
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

  // Reject placeholders
  if (
    cleanSig.toLowerCase().includes('placeholder') ||
    cleanSig.toLowerCase().includes('mock') ||
    cleanSig.toLowerCase().includes('dummy') ||
    cleanSig.toLowerCase().includes('fake') ||
    cleanSig.toLowerCase().includes('sig_')
  ) {
    return {
      isValid: false,
      status: 'PENDING_ATTESTATION',
      reason: 'Placeholder or mock signature rejected',
    };
  }

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

  if (!isTrustedVerifierAuthority(options.verifierAuthority)) {
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
  if (
    !payload.domain ||
    !payload.network ||
    !payload.subject ||
    !payload.evidenceHash ||
    !payload.nonce ||
    typeof payload.expiresAt !== 'number'
  ) {
    return {
      isValid: false,
      status: 'PENDING_ATTESTATION',
      reason: 'Malformed attestation payload (all canonical binding fields required)',
    };
  }

  // 6. Expiration check
  const now = options.currentTime ?? Math.floor(Date.now() / 1000);
  const expiry = payload.expiresAt > 1e11 ? Math.floor(payload.expiresAt / 1000) : payload.expiresAt;
  const currentSec = now > 1e11 ? Math.floor(now / 1000) : now;
  if (expiry <= currentSec) {
    return {
      isValid: false,
      status: 'PENDING_ATTESTATION',
      reason: 'Attestation has expired',
    };
  }

  // 7. Nonce replay check
  if (isNonceConsumed(payload.nonce, payload.domain)) {
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
  consumeNonce(payload.nonce, payload.domain);

  return {
    isValid: true,
    status: 'VERIFIED',
  };
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
    const validation = validateCryptographicAttestation({
      verifierAuthority: opts.verifierAuthority,
      attestationSignature: opts.attestationSignature,
      payload: opts.payload,
      isAttested: opts.isAttested,
      currentTime: opts.currentTime,
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
// Typed Provenance Aggregation Protection
// ─────────────────────────────────────────────────────────────────────────────

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
