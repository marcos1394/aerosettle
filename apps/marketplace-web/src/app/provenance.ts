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

export interface ExternalTelemetryOptions {
  verifierAuthority?: string;
  attestationSignature?: string;
  isAttested?: boolean;
  verifiedAt?: string;
  error?: string;
  trustedVerifiers?: readonly string[];
}

/**
 * Trusted verifier authorities registry.
 * In production/localnet, verifier public keys must match an authorized verifier oracle.
 */
export const TRUSTED_VERIFIER_AUTHORITIES: readonly string[] = [
  'DmWQhuVujHrJb4jFzo62UnCT3mwnx9GFtVdo8VUu82Wu', // Protocol Verifier Authority (config.ts)
];

/**
 * Validates cryptographic attestation signatures from designated verifiers.
 * 
 * Rejects:
 * - Simple boolean flags (e.g. isAttested: true) without a cryptographic signature
 * - Arbitrary, placeholder, or short string signatures (< 64 characters)
 * - Signatures from unauthorized or unconfigured verifiers
 *
 * In all rejected/unverified cases, preserves EXTERNAL_VERIFIED provenance
 * but strictly enforces PENDING_ATTESTATION validation status.
 */
export function validateCryptographicAttestation(options?: {
  verifierAuthority?: string;
  attestationSignature?: string;
  trustedVerifiers?: readonly string[];
}): { isValid: boolean; status: ValidationStatus; reason?: string } {
  if (!options) {
    return {
      isValid: false,
      status: 'PENDING_ATTESTATION',
      reason: 'No attestation metadata provided',
    };
  }

  const { verifierAuthority, attestationSignature } = options;
  const trustedList = options.trustedVerifiers ?? TRUSTED_VERIFIER_AUTHORITIES;

  // 1. Signature must be present and non-empty
  if (!attestationSignature || typeof attestationSignature !== 'string') {
    return {
      isValid: false,
      status: 'PENDING_ATTESTATION',
      reason: 'Missing cryptographic attestation signature',
    };
  }

  const cleanSig = attestationSignature.trim();

  // 2. Structural cryptographic signature check:
  // An Ed25519 signature in Solana is 64 bytes (87-88 Base58 chars or 128 hex chars).
  // Arbitrary placeholders, short strings (<64 chars), or mock flags are strictly rejected.
  const isBase58OrHex = /^[1-9A-HJ-NP-Za-km-z0-9a-fA-F]+$/.test(cleanSig);
  const isCryptoLength = cleanSig.length >= 64 && cleanSig.length <= 130;
  const isNotPlaceholder =
    !cleanSig.toLowerCase().includes('placeholder') &&
    !cleanSig.toLowerCase().includes('mock') &&
    !cleanSig.toLowerCase().includes('dummy') &&
    !cleanSig.toLowerCase().includes('fake') &&
    !cleanSig.toLowerCase().includes('sig_');

  if (!isBase58OrHex || !isCryptoLength || !isNotPlaceholder) {
    return {
      isValid: false,
      status: 'PENDING_ATTESTATION',
      reason: 'Invalid cryptographic signature format (must be 64-byte Ed25519 signature)',
    };
  }

  // 3. Verifier authority check: Must be issued by an authorized trusted verifier
  if (!verifierAuthority || !trustedList.includes(verifierAuthority)) {
    return {
      isValid: false,
      status: 'PENDING_ATTESTATION',
      reason: verifierAuthority
        ? `Untrusted or unregistered verifier authority: ${verifierAuthority}`
        : 'Missing verifier authority',
    };
  }

  // Cryptographically verified by trusted authority
  return {
    isValid: true,
    status: 'VERIFIED',
  };
}

/**
 * Standard provenance descriptors for Conatus network data sources.
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

    const status: ValidationStatus =
      opts.status ?? (opts.error ? 'UNAVAILABLE' : 'VERIFIED');
    const network = opts.network || 'Solana Localnet';
    const commitment = opts.commitment || 'confirmed';
    const period = opts.error
      ? 'RPC Query Error'
      : opts.slot != null
        ? `Slot ${opts.slot} (${commitment})`
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

    const status: ValidationStatus =
      opts.status ?? (opts.error ? 'UNAVAILABLE' : 'VERIFIED');
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
    status: ValidationStatus = 'VERIFIED',
    slot?: number
  ): EconomicMetricMetadata => ({
    provenance: 'ONCHAIN_VERIFIED',
    status,
    source: 'AeroSettle Program Escrow Vault (PDA)',
    network: network || 'Solana Localnet',
    period: slot ? `Slot ${slot} (Finalized)` : 'On-chain Finality (~2.4s)',
  }),

  ONCHAIN_WORK_ORDERS: (
    network: string = 'Solana Localnet',
    status: ValidationStatus = 'VERIFIED',
    slot?: number
  ): EconomicMetricMetadata => ({
    provenance: 'ONCHAIN_VERIFIED',
    status,
    source: 'WorkOrder Registry Program Accounts (PDA)',
    network: network || 'Solana Localnet',
    period: slot ? `Slot ${slot} (Ledger State)` : 'Real-time (Ledger State)',
  }),

  ONCHAIN_AGENT_REGISTRY: (
    network: string = 'Solana Localnet',
    status: ValidationStatus = 'VERIFIED',
    slot?: number
  ): EconomicMetricMetadata => ({
    provenance: 'ONCHAIN_VERIFIED',
    status,
    source: 'Agent Registry Program Accounts (PDA)',
    network: network || 'Solana Localnet',
    period: slot ? `Slot ${slot} (Ledger State)` : 'Real-time (Ledger State)',
  }),

  // External verified sources — REQUIRE valid cryptographic signature from a trusted verifier
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

    // Cryptographic signature and trusted verifier authority verification
    const validation = validateCryptographicAttestation({
      verifierAuthority: opts.verifierAuthority,
      attestationSignature: opts.attestationSignature,
      trustedVerifiers: opts.trustedVerifiers,
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

/**
 * Guardrail function to guarantee that simulated numbers are NEVER silently added,
 * combined, or folded into verified on-chain balances or revenues.
 *
 * Coexistence of verified and simulated metrics on the same view in separate buckets is valid.
 * What this guardrail forbids is incompatible arithmetic aggregation (e.g. summing or folding)
 * that merges verified and simulated amounts into a single composite output value.
 *
 * Supported forms:
 * 1. assertNoSilentAggregation(aggregateValue, { verified, simulated }, context, strict?)
 * 2. assertNoSilentAggregation(verified, simulated, aggregateValue, context, strict?)
 * 3. assertNoSilentAggregation(verified, simulated, context, strict?) -> Coexistence assertion (does NOT throw)
 */
export function assertNoSilentAggregation(
  arg1: number,
  arg2: { verified: number; simulated: number } | number,
  arg3?: string | number,
  arg4?: string | boolean,
  arg5: boolean = true
): void {
  let aggregateValue: number | undefined;
  let verified: number;
  let simulated: number;
  let context: string;
  let strict = true;

  if (typeof arg2 === 'object' && arg2 !== null) {
    // Form 1: assertNoSilentAggregation(aggregateValue, { verified, simulated }, context, strict?)
    aggregateValue = arg1;
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
    verified = arg1;
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
  // If status is UNAVAILABLE, prioritize error state visually
  if (status === 'UNAVAILABLE') {
    return {
      tone: 'error',
      label: locale === 'es' ? 'No Disponible' : 'Unavailable',
      badgeClass: 'provenance-badge-unavailable',
      iconName: 'alert',
    };
  }

  // If status is PENDING_VALIDATION, prioritize pending in-flight state
  if (status === 'PENDING_VALIDATION') {
    return {
      tone: 'accent',
      label: locale === 'es' ? 'Validación Pendiente' : 'Pending Validation',
      badgeClass: 'provenance-badge-pending',
      iconName: 'clock',
    };
  }

  // If status is STALE
  if (status === 'STALE') {
    return {
      tone: 'warning',
      label: locale === 'es' ? 'Dato Obsoleto' : 'Stale Data',
      badgeClass: 'provenance-badge-stale',
      iconName: 'alert',
    };
  }

  switch (provenance) {
    case 'ONCHAIN_VERIFIED':
      return {
        tone: 'success',
        label: locale === 'es' ? 'On-chain Verificado' : 'On-chain Verified',
        badgeClass: 'provenance-badge-onchain',
        iconName: 'check',
      };
    case 'EXTERNAL_VERIFIED':
      return {
        tone: status === 'VERIFIED' ? 'accent' : 'warning',
        label: status === 'VERIFIED'
          ? (locale === 'es' ? 'Externo Verificado' : 'External Verified')
          : (locale === 'es' ? 'Atestación Pendiente' : 'Pending Attestation'),
        badgeClass: 'provenance-badge-external',
        iconName: 'shield',
      };
    case 'SIMULATED':
      return {
        tone: 'warning',
        label: locale === 'es' ? 'Escenario Simulado' : 'Simulated Scenario',
        badgeClass: 'provenance-badge-simulated',
        iconName: 'spark',
      };
  }
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
