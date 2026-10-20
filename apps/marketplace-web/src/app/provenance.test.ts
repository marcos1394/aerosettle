import test from 'node:test';
import assert from 'node:assert/strict';
import { ed25519 } from '@noble/curves/ed25519';
import {
  type DataProvenance,
  type ValidationStatus,
  type EconomicMetric,
  type AttestationPayload,
  type Clock,
  PROVENANCE_SOURCES,
  assertNoSilentAggregation,
  segregateByProvenance,
  makeMetric,
  getProvenanceVisuals,
  getStatusLabel,
  getStatusTone,
  validateCryptographicAttestation,
  serializeCanonicalAttestation,
  encodeBase58,
  createIsolatedAttestationVerifier,
  InvalidAttestationPayloadError,
  isTrustedVerifierAuthority,
  getProductionTrustedVerifierAuthorities,
  TRUSTED_VERIFIER_AUTHORITIES,
  addMetrics,
  sumMetrics,
  averageMetrics,
  reduceMetrics,
  assertCoexistenceOnly,
  IncompatibleProvenanceAggregationError,
} from './provenance.ts';

test('Taxonomy: DataProvenance contracts adhere strictly to the 3 defined levels', () => {
  const validProvenances: DataProvenance[] = [
    'ONCHAIN_VERIFIED',
    'EXTERNAL_VERIFIED',
    'SIMULATED',
  ];
  assert.equal(validProvenances.length, 3);
  assert.ok(validProvenances.includes('ONCHAIN_VERIFIED'));
  assert.ok(validProvenances.includes('EXTERNAL_VERIFIED'));
  assert.ok(validProvenances.includes('SIMULATED'));
});

test('Taxonomy: ValidationStatus contracts adhere to all 6 distinct lifecycle validation states', () => {
  const validStatuses: ValidationStatus[] = [
    'VERIFIED',
    'PENDING_ATTESTATION',
    'PENDING_VALIDATION',
    'STALE',
    'UNAVAILABLE',
    'SIMULATED_PROJECTION',
  ];
  assert.equal(validStatuses.length, 6);
  assert.ok(validStatuses.includes('VERIFIED'));
  assert.ok(validStatuses.includes('PENDING_ATTESTATION'));
  assert.ok(validStatuses.includes('PENDING_VALIDATION'));
  assert.ok(validStatuses.includes('STALE'));
  assert.ok(validStatuses.includes('UNAVAILABLE'));
  assert.ok(validStatuses.includes('SIMULATED_PROJECTION'));
});

test('PROVENANCE_SOURCES: Native SOL balance conservative default is PENDING_VALIDATION; VERIFIED only on confirmed slot', () => {
  // Conservative default without confirmed slot
  const unconfirmed = PROVENANCE_SOURCES.ONCHAIN_SOL_BALANCE('Solana Localnet');
  assert.equal(unconfirmed.provenance, 'ONCHAIN_VERIFIED');
  assert.equal(unconfirmed.status, 'PENDING_VALIDATION');
  assert.equal(unconfirmed.period, 'Pending Confirmation');

  // With confirmed slot -> VERIFIED
  const confirmed = PROVENANCE_SOURCES.ONCHAIN_SOL_BALANCE('Solana Localnet', 1042, 'confirmed');
  assert.equal(confirmed.provenance, 'ONCHAIN_VERIFIED');
  assert.equal(confirmed.status, 'VERIFIED');
  assert.match(confirmed.source, /System Program/);
  assert.equal(confirmed.network, 'Solana Localnet');
  assert.equal(confirmed.period, 'Slot 1042 (confirmed)');
});

test('PROVENANCE_SOURCES: Native SOL handles RPC errors and pending validation', () => {
  const errorMeta = PROVENANCE_SOURCES.ONCHAIN_SOL_BALANCE({
    network: 'Solana Localnet',
    error: 'Connection timeout',
  });
  assert.equal(errorMeta.provenance, 'ONCHAIN_VERIFIED');
  assert.equal(errorMeta.status, 'UNAVAILABLE');
  assert.match(errorMeta.source, /Error: Connection timeout/);
  assert.equal(errorMeta.period, 'RPC Query Error');

  const pendingMeta = PROVENANCE_SOURCES.ONCHAIN_SOL_BALANCE({
    network: 'Solana Localnet',
    status: 'PENDING_VALIDATION',
  });
  assert.equal(pendingMeta.status, 'PENDING_VALIDATION');
});

test('PROVENANCE_SOURCES: SPL token balance conservative default is PENDING_VALIDATION; VERIFIED only on confirmed slot', () => {
  const mint = 'HTHpns7gqLAhSBhAzqxhYdyHv9HeXkkRW6aHQfdUjL1G';

  // Conservative default without slot
  const unconfirmed = PROVENANCE_SOURCES.ONCHAIN_SPL_BALANCE({ mint });
  assert.equal(unconfirmed.provenance, 'ONCHAIN_VERIFIED');
  assert.equal(unconfirmed.status, 'PENDING_VALIDATION');
  assert.equal(unconfirmed.period, 'Pending Confirmation');

  // Confirmed slot -> VERIFIED
  const meta = PROVENANCE_SOURCES.ONCHAIN_SPL_BALANCE({
    mint,
    network: 'Solana Localnet',
    slot: 2840,
    commitment: 'confirmed',
  });
  assert.equal(meta.provenance, 'ONCHAIN_VERIFIED');
  assert.equal(meta.status, 'VERIFIED');
  assert.match(meta.source, /Token Program/);
  assert.match(meta.source, /HTHpns/);
  assert.equal(meta.period, 'Slot 2840 (confirmed)');
});

test('PROVENANCE_SOURCES: SPL token balance handles RPC failure', () => {
  const mint = 'HTHpns7gqLAhSBhAzqxhYdyHv9HeXkkRW6aHQfdUjL1G';
  const errorMeta = PROVENANCE_SOURCES.ONCHAIN_SPL_BALANCE({
    mint,
    error: 'Account not found',
  });
  assert.equal(errorMeta.provenance, 'ONCHAIN_VERIFIED');
  assert.equal(errorMeta.status, 'UNAVAILABLE');
  assert.match(errorMeta.source, /Account not found/);
});

test('PROVENANCE_SOURCES: Escrow vault, WorkOrders and Agent PDA default to PENDING_VALIDATION and support confirmed slots', () => {
  // Unconfirmed default
  const escrowDefault = PROVENANCE_SOURCES.ONCHAIN_ESCROW_VAULT('Solana Localnet');
  assert.equal(escrowDefault.status, 'PENDING_VALIDATION');
  assert.equal(escrowDefault.period, 'Pending Finality');

  // Confirmed slot
  const escrowMeta = PROVENANCE_SOURCES.ONCHAIN_ESCROW_VAULT('Solana Localnet', undefined, 501);
  assert.equal(escrowMeta.provenance, 'ONCHAIN_VERIFIED');
  assert.equal(escrowMeta.status, 'VERIFIED');
  assert.match(escrowMeta.source, /PDA/);
  assert.match(escrowMeta.period, /Slot 501/);

  const woDefault = PROVENANCE_SOURCES.ONCHAIN_WORK_ORDERS('Solana Localnet');
  assert.equal(woDefault.status, 'PENDING_VALIDATION');

  const agentDefault = PROVENANCE_SOURCES.ONCHAIN_AGENT_REGISTRY('Solana Localnet');
  assert.equal(agentDefault.status, 'PENDING_VALIDATION');
});

// ─────────────────────────────────────────────────────────────────────────────
// Authentic Ed25519 Cryptographic Attestation Verification Tests
// ─────────────────────────────────────────────────────────────────────────────

test('Ed25519 Authentic Verification: Case 1 — Genuine signature from authorized authority is accepted', () => {
  // Generate ephemeral keypair
  const privKey = ed25519.utils.randomPrivateKey();
  const pubKeyBytes = ed25519.getPublicKey(privKey);
  const pubKey = encodeBase58(pubKeyBytes);

  // Isolated test verifier configured strictly for this test (isolated authority registry)
  const verifier = createIsolatedAttestationVerifier({
    trustedAuthorities: [pubKey],
  });

  const payload: AttestationPayload = {
    domain: 'conatus:attestation:v1',
    network: 'solana:localnet',
    subject: 'Agent1111111111111111111111111111111111111111',
    evidenceHash: 'e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855',
    nonce: 'nonce-case-1-valid',
    expiresAt: Math.floor(Date.now() / 1000) + 3600,
    economicValue: 250,
  };

  const canonicalBytes = serializeCanonicalAttestation(payload);
  const signatureBytes = ed25519.sign(canonicalBytes, privKey);
  const validSignature = encodeBase58(signatureBytes);

  const result = verifier.validate({
    verifierAuthority: pubKey,
    attestationSignature: validSignature,
    payload,
  });

  assert.equal(result.isValid, true);
  assert.equal(result.status, 'VERIFIED');
});

test('Ed25519 Authentic Verification: Case 2 — Well-formed Base58 string with false/forged signature is rejected', () => {
  const privKey = ed25519.utils.randomPrivateKey();
  const pubKey = encodeBase58(ed25519.getPublicKey(privKey));
  const verifier = createIsolatedAttestationVerifier({
    trustedAuthorities: [pubKey],
  });

  const payload: AttestationPayload = {
    domain: 'conatus:attestation:v1',
    network: 'solana:localnet',
    subject: 'Agent1111111111111111111111111111111111111111',
    evidenceHash: 'e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855',
    nonce: 'nonce-case-2-forged',
    expiresAt: Math.floor(Date.now() / 1000) + 3600,
  };

  // 64 arbitrary bytes encoded in legitimate Base58 (correct format, but mathematically forged)
  const forgedBytes = new Uint8Array(64).fill(0x3a);
  const forgedBase58Sig = encodeBase58(forgedBytes);

  const result = verifier.validate({
    verifierAuthority: pubKey,
    attestationSignature: forgedBase58Sig,
    payload,
  });

  assert.equal(result.isValid, false);
  assert.equal(result.status, 'PENDING_ATTESTATION');
  assert.match(result.reason!, /Cryptographic Ed25519 signature verification failed/);
});

test('Ed25519 Authentic Verification: Case 3 — Valid signature with tampered message is rejected', () => {
  const privKey = ed25519.utils.randomPrivateKey();
  const pubKey = encodeBase58(ed25519.getPublicKey(privKey));
  const verifier = createIsolatedAttestationVerifier({
    trustedAuthorities: [pubKey],
  });

  const originalPayload: AttestationPayload = {
    domain: 'conatus:attestation:v1',
    network: 'solana:localnet',
    subject: 'Agent1111111111111111111111111111111111111111',
    evidenceHash: 'e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855',
    nonce: 'nonce-case-3-tampered',
    expiresAt: Math.floor(Date.now() / 1000) + 3600,
    economicValue: 100,
  };

  const signature = encodeBase58(
    ed25519.sign(serializeCanonicalAttestation(originalPayload), privKey)
  );

  // Attacker modifies economicValue to 500,000 without having the private key
  const tamperedPayload: AttestationPayload = {
    ...originalPayload,
    economicValue: 500_000,
  };

  const result = verifier.validate({
    verifierAuthority: pubKey,
    attestationSignature: signature,
    payload: tamperedPayload,
  });

  assert.equal(result.isValid, false);
  assert.equal(result.status, 'PENDING_ATTESTATION');
  assert.match(result.reason!, /signature verification failed/);
});

test('Ed25519 Authentic Verification: Case 4 — Unauthorized authority signature is rejected by both production and isolated verifiers', () => {
  // Ephemeral key generated but intentionally NOT registered in trusted authorities
  const unauthorizedPriv = ed25519.utils.randomPrivateKey();
  const unauthorizedPub = encodeBase58(ed25519.getPublicKey(unauthorizedPriv));

  const payload: AttestationPayload = {
    domain: 'conatus:attestation:v1',
    network: 'solana:localnet',
    subject: 'Agent1111111111111111111111111111111111111111',
    evidenceHash: 'e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855',
    nonce: 'nonce-case-4-unauthorized',
    expiresAt: Math.floor(Date.now() / 1000) + 3600,
  };

  const validSig = encodeBase58(
    ed25519.sign(serializeCanonicalAttestation(payload), unauthorizedPriv)
  );

  // 1) Production default verifier rejects the unauthorized ephemeral pubkey
  const prodResult = validateCryptographicAttestation({
    verifierAuthority: unauthorizedPub,
    attestationSignature: validSig,
    payload,
  });
  assert.equal(prodResult.isValid, false);
  assert.equal(prodResult.status, 'PENDING_ATTESTATION');
  assert.match(prodResult.reason!, /Untrusted or unregistered verifier authority/);

  // 2) Isolated verifier with a different trusted authority also rejects it
  const isolatedVerifier = createIsolatedAttestationVerifier({
    trustedAuthorities: ['DmWQhuVujHrJb4jFzo62UnCT3mwnx9GFtVdo8VUu82Wu'],
  });
  const isolatedResult = isolatedVerifier.validate({
    verifierAuthority: unauthorizedPub,
    attestationSignature: validSig,
    payload,
  });
  assert.equal(isolatedResult.isValid, false);
  assert.equal(isolatedResult.status, 'PENDING_ATTESTATION');
  assert.match(isolatedResult.reason!, /Untrusted or unregistered verifier authority/);
});

test('Ed25519 Authentic Verification: Case 5 — Reused nonce is rejected by replay protection', () => {
  const privKey = ed25519.utils.randomPrivateKey();
  const pubKey = encodeBase58(ed25519.getPublicKey(privKey));
  const verifier = createIsolatedAttestationVerifier({
    trustedAuthorities: [pubKey],
  });

  const payload: AttestationPayload = {
    domain: 'conatus:attestation:v1',
    network: 'solana:localnet',
    subject: 'Agent1111111111111111111111111111111111111111',
    evidenceHash: 'e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855',
    nonce: 'nonce-replay-unique-123',
    expiresAt: Math.floor(Date.now() / 1000) + 3600,
  };

  const signature = encodeBase58(
    ed25519.sign(serializeCanonicalAttestation(payload), privKey)
  );

  // First presentation: accepted
  const firstResult = verifier.validate({
    verifierAuthority: pubKey,
    attestationSignature: signature,
    payload,
  });
  assert.equal(firstResult.isValid, true);
  assert.equal(firstResult.status, 'VERIFIED');

  // Replay presentation with identical nonce: rejected
  const replayResult = verifier.validate({
    verifierAuthority: pubKey,
    attestationSignature: signature,
    payload,
  });
  assert.equal(replayResult.isValid, false);
  assert.equal(replayResult.status, 'PENDING_ATTESTATION');
  assert.match(replayResult.reason!, /Nonce already consumed/);
});

test('Ed25519 Authentic Verification: Case 6 — Expired attestation is rejected via injected mock clock and real clock', () => {
  const privKey = ed25519.utils.randomPrivateKey();
  const pubKey = encodeBase58(ed25519.getPublicKey(privKey));

  const payload: AttestationPayload = {
    domain: 'conatus:attestation:v1',
    network: 'solana:localnet',
    subject: 'Agent1111111111111111111111111111111111111111',
    evidenceHash: 'e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855',
    nonce: 'nonce-clock-test-1',
    expiresAt: 1_700_000_000, // Fixed historical timestamp
  };

  const signature = encodeBase58(
    ed25519.sign(serializeCanonicalAttestation(payload), privKey)
  );

  // 1) Test with mock clock injected at T = 1,699,999,000 (BEFORE expiration) -> accepted
  const validClockVerifier = createIsolatedAttestationVerifier({
    trustedAuthorities: [pubKey],
    clock: () => 1_699_999_000,
  });
  const validResult = validClockVerifier.validate({
    verifierAuthority: pubKey,
    attestationSignature: signature,
    payload,
  });
  assert.equal(validResult.isValid, true);
  assert.equal(validResult.status, 'VERIFIED');

  // 2) Test with mock clock injected at T = 1_700_000_001 (AFTER expiration) -> strictly rejected
  const expiredClockVerifier = createIsolatedAttestationVerifier({
    trustedAuthorities: [pubKey],
    clock: () => 1_700_000_001,
  });
  const expiredResult = expiredClockVerifier.validate({
    verifierAuthority: pubKey,
    attestationSignature: signature,
    payload,
  });
  assert.equal(expiredResult.isValid, false);
  assert.equal(expiredResult.status, 'PENDING_ATTESTATION');
  assert.match(expiredResult.reason!, /Attestation has expired/);

  // 3) Production verifier uses environment clock and strictly rejects historical expiry
  const prodResult = validateCryptographicAttestation({
    verifierAuthority: pubKey,
    attestationSignature: signature,
    payload,
  });
  assert.equal(prodResult.isValid, false);
  assert.equal(prodResult.status, 'PENDING_ATTESTATION');
});

test('Ed25519 Authentic Verification: Case 7 — Boolean flag isAttested: true alone is strictly insufficient', () => {
  const result = validateCryptographicAttestation({
    verifierAuthority: 'DmWQhuVujHrJb4jFzo62UnCT3mwnx9GFtVdo8VUu82Wu',
    isAttested: true,
  });

  assert.equal(result.isValid, false);
  assert.equal(result.status, 'PENDING_ATTESTATION');
  assert.match(result.reason!, /isAttested=true is insufficient/);
});

test('Trust Registry Hardening: Attempting to tamper with authorities cannot compromise production verifier', () => {
  const unauthorizedKey = '4Z4k5ZqC8gUa4GfN7j2fJ9mZ7xY8uK6yH8qQ9sK2gP1b';

  // 1) Verify that unauthorized key is rejected by the production verifier
  assert.equal(isTrustedVerifierAuthority(unauthorizedKey), false);

  // 2) Attempt to mutate the exported TRUSTED_VERIFIER_AUTHORITIES array
  try {
    (TRUSTED_VERIFIER_AUTHORITIES as unknown as string[]).push(unauthorizedKey);
  } catch {
    // Expected in strict mode
  }

  // 3) Attempt to mutate through getProductionTrustedVerifierAuthorities copy
  const copy = getProductionTrustedVerifierAuthorities();
  try {
    (copy as unknown as string[]).push(unauthorizedKey);
  } catch {
    // Expected in strict mode
  }

  // 4) Verify that creating an isolated verifier with the unauthorized key does NOT compromise production
  const isolated = createIsolatedAttestationVerifier({
    trustedAuthorities: [unauthorizedKey],
  });
  assert.equal(isolated.isTrusted(unauthorizedKey), true);
  assert.equal(isTrustedVerifierAuthority(unauthorizedKey), false);

  // 5) validateCryptographicAttestation MUST continue rejecting an attestation from this unauthorized key
  const privKey = ed25519.utils.randomPrivateKey();
  const pubKeyBytes = ed25519.getPublicKey(privKey);
  const maliciousKey = encodeBase58(pubKeyBytes);

  const payload: AttestationPayload = {
    domain: 'conatus:attestation:v1',
    network: 'solana:localnet',
    subject: 'Agent1111111111111111111111111111111111111111',
    evidenceHash: 'e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855',
    nonce: 'nonce-tamper-guard-test',
    expiresAt: Math.floor(Date.now() / 1000) + 3600,
  };
  const signature = encodeBase58(ed25519.sign(serializeCanonicalAttestation(payload), privKey));

  const prodResult = validateCryptographicAttestation({
    verifierAuthority: maliciousKey,
    attestationSignature: signature,
    payload,
  });

  assert.equal(prodResult.isValid, false);
  assert.equal(prodResult.status, 'PENDING_ATTESTATION');
  assert.match(prodResult.reason!, /Untrusted or unregistered verifier authority/);
});

// ─────────────────────────────────────────────────────────────────────────────
// Canonical Serialization Negative Tests (Ambiguity & Collision Immunity)
// ─────────────────────────────────────────────────────────────────────────────

test('Canonical Serialization: Negative tests prove distinct payloads produce strictly different bytes and delimiter injection is impossible', () => {
  const basePayload: AttestationPayload = {
    domain: 'conatus:attestation:v1',
    network: 'solana:localnet',
    subject: 'Agent1111111111111111111111111111111111111111',
    evidenceHash: 'e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855',
    nonce: 'nonce-canonical-test-1',
    expiresAt: 1_800_000_000,
  };

  const bytesBase = serializeCanonicalAttestation(basePayload);

  // 1) Header checks: Magic 'CON1' (0x43, 0x4F, 0x4E, 0x01) and field count = 6
  assert.equal(bytesBase[0], 0x43); // 'C'
  assert.equal(bytesBase[1], 0x4F); // 'O'
  assert.equal(bytesBase[2], 0x4E); // 'N'
  assert.equal(bytesBase[3], 0x01); // Version 1
  assert.equal(bytesBase[4], 6);    // 6 fields

  // 2) Field boundary shifting test:
  // In delimiter-based formats (like query strings), domain='a' & network='bc' can collide with domain='ab' & network='c'.
  // Length-prefixed binary serialization must produce strictly distinct byte arrays.
  const payloadShifted: AttestationPayload = {
    ...basePayload,
    domain: 'conatus:attestation:v1:solana',
    network: 'localnet',
  };
  const bytesShifted = serializeCanonicalAttestation(payloadShifted);
  assert.notDeepEqual(bytesBase, bytesShifted);

  // 3) Delimiter injection test:
  // Attacker attempts to inject fake field assignments inside subject string
  const payloadInjected: AttestationPayload = {
    ...basePayload,
    subject: 'Agent1111111111111111111111111111111111111111&evidenceHash=0000000000000000000000000000000000000000000000000000000000000000',
  };
  const bytesInjected = serializeCanonicalAttestation(payloadInjected);
  assert.notDeepEqual(bytesBase, bytesInjected);

  // 4) Different nonces produce distinct bytes
  const payloadNonce2: AttestationPayload = {
    ...basePayload,
    nonce: 'nonce-canonical-test-2',
  };
  const bytesNonce2 = serializeCanonicalAttestation(payloadNonce2);
  assert.notDeepEqual(bytesBase, bytesNonce2);
});

test('Canonical Serialization: Negative tests validate semantic payload fields and reject malformed inputs', () => {
  const valid: AttestationPayload = {
    domain: 'conatus:attestation:v1',
    network: 'solana:localnet',
    subject: 'Agent1111111111111111111111111111111111111111',
    evidenceHash: 'e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855',
    nonce: 'valid-nonce-101',
    expiresAt: 1_800_000_000,
  };

  // 1) Empty domain
  assert.throws(
    () => serializeCanonicalAttestation({ ...valid, domain: '' }),
    InvalidAttestationPayloadError
  );

  // 2) Illegal control characters in domain
  assert.throws(
    () => serializeCanonicalAttestation({ ...valid, domain: 'conatus\x00attestation' }),
    InvalidAttestationPayloadError
  );

  // 3) Empty network
  assert.throws(
    () => serializeCanonicalAttestation({ ...valid, network: '   ' }),
    InvalidAttestationPayloadError
  );

  // 4) Subject too short
  assert.throws(
    () => serializeCanonicalAttestation({ ...valid, subject: 'short' }),
    InvalidAttestationPayloadError
  );

  // 5) Malformed evidenceHash (not valid 32-byte hex or base58 digest)
  assert.throws(
    () => serializeCanonicalAttestation({ ...valid, evidenceHash: 'not-a-crypto-digest' }),
    InvalidAttestationPayloadError
  );

  // 6) Negative or non-numeric expiresAt
  assert.throws(
    () => serializeCanonicalAttestation({ ...valid, expiresAt: -500 }),
    InvalidAttestationPayloadError
  );
  assert.throws(
    () => serializeCanonicalAttestation({ ...valid, expiresAt: NaN }),
    InvalidAttestationPayloadError
  );
});

// ─────────────────────────────────────────────────────────────────────────────
// Financial & Accounting Guardrails Tests
// ─────────────────────────────────────────────────────────────────────────────

test('Financial & Accounting Guardrails: Incompatible mints and monetary units are blocked in arithmetic operations', () => {
  const usdcMint = 'EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v';
  const demoMint = 'HTHpns7gqLAhSBhAzqxhYdyHv9HeXkkRW6aHQfdUjL1G';

  const metricUsdc = makeMetric(100, {
    ...PROVENANCE_SOURCES.ONCHAIN_SPL_BALANCE({ mint: usdcMint, slot: 100 }),
    mint: usdcMint,
    unit: 'USDC',
  });

  const metricDemo = makeMetric(50, {
    ...PROVENANCE_SOURCES.ONCHAIN_SPL_BALANCE({ mint: demoMint, slot: 100 }),
    mint: demoMint,
    unit: 'DEMO',
  });

  // Adding metrics with different token mints must throw
  assert.throws(
    () => {
      addMetrics(metricUsdc, metricDemo, 'Incompatible Mints Sum');
    },
    (err: unknown) => {
      assert.ok(err instanceof IncompatibleProvenanceAggregationError);
      assert.match((err as Error).message, /Incompatible token mints/);
      return true;
    }
  );

  // Summing an array of metrics with mismatched mints must throw
  assert.throws(
    () => {
      sumMetrics([metricUsdc, metricDemo], 'Mismatched Mint Array');
    },
    (err: unknown) => {
      assert.ok(err instanceof IncompatibleProvenanceAggregationError);
      assert.match((err as Error).message, /Incompatible token mints/);
      return true;
    }
  );
});

// ─────────────────────────────────────────────────────────────────────────────
// Typed Provenance Aggregation Protection Tests
// ─────────────────────────────────────────────────────────────────────────────

test('Typed Provenance Aggregation: addMetrics combines compatible metrics and blocks incompatible ones', () => {
  const onChain1: EconomicMetric<number> = makeMetric(10, PROVENANCE_SOURCES.ONCHAIN_SOL_BALANCE('Solana Localnet', 500));
  const onChain2: EconomicMetric<number> = makeMetric(25, PROVENANCE_SOURCES.ONCHAIN_SOL_BALANCE('Solana Localnet', 501));
  const simulated1: EconomicMetric<number> = makeMetric(18_420, PROVENANCE_SOURCES.SIMULATED_ATLAS_SNAPSHOT('Fleet Liquidity'));
  const simulated2: EconomicMetric<number> = makeMetric(5_000, PROVENANCE_SOURCES.SIMULATED_ATLAS_SNAPSHOT('Agent Reserve'));

  // 1) Compatible additions
  const combinedOnChain = addMetrics(onChain1, onChain2, 'Total Onchain Balance');
  assert.equal(combinedOnChain.value, 35);
  assert.equal(combinedOnChain.meta.provenance, 'ONCHAIN_VERIFIED');
  assert.equal(combinedOnChain.meta.status, 'VERIFIED');

  const combinedSimulated = addMetrics(simulated1, simulated2, 'Total Simulated');
  assert.equal(combinedSimulated.value, 23_420);
  assert.equal(combinedSimulated.meta.provenance, 'SIMULATED');
  assert.equal(combinedSimulated.meta.status, 'SIMULATED_PROJECTION');

  // 2) Incompatible addition: mixing on-chain and simulated metrics strictly throws
  assert.throws(
    () => {
      addMetrics(onChain1, simulated1, 'Illegal Aggregation');
    },
    (err: unknown) => {
      assert.ok(err instanceof IncompatibleProvenanceAggregationError);
      assert.match((err as Error).message, /Cannot aggregate metrics with incompatible provenances/);
      return true;
    }
  );
});

test('Typed Provenance Aggregation: sumMetrics and averageMetrics validate all operands across array', () => {
  const simA = makeMetric(100, PROVENANCE_SOURCES.SIMULATED_ATLAS_SNAPSHOT('A'));
  const simB = makeMetric(200, PROVENANCE_SOURCES.SIMULATED_ATLAS_SNAPSHOT('B'));
  const simC = makeMetric(300, PROVENANCE_SOURCES.SIMULATED_ATLAS_SNAPSHOT('C'));
  const onChainReal = makeMetric(50, PROVENANCE_SOURCES.ONCHAIN_SOL_BALANCE('Solana Localnet', 100));

  // Compatible sum and average
  const sum = sumMetrics([simA, simB, simC], 'Clean Simulated Sum');
  assert.equal(sum.value, 600);
  assert.equal(sum.meta.provenance, 'SIMULATED');

  const avg = averageMetrics([simA, simB, simC], 'Clean Simulated Average');
  assert.equal(avg.value, 200);

  // Incompatible sum: array containing a hidden verified metric amongst simulated ones is intercepted
  assert.throws(
    () => {
      sumMetrics([simA, simB, onChainReal, simC], 'Hidden Contamination');
    },
    (err: unknown) => {
      assert.ok(err instanceof IncompatibleProvenanceAggregationError);
      return true;
    }
  );
});

test('Typed Provenance Aggregation: reduceMetrics reduces compatible operands and rejects mixed operands', () => {
  const m1 = makeMetric(10, PROVENANCE_SOURCES.SIMULATED_ATLAS_SNAPSHOT('1'));
  const m2 = makeMetric(20, PROVENANCE_SOURCES.SIMULATED_ATLAS_SNAPSHOT('2'));
  const real = makeMetric(5, PROVENANCE_SOURCES.ONCHAIN_SOL_BALANCE('Solana Localnet', 100));

  const reduced = reduceMetrics([m1, m2], (acc, v) => acc * v, 1, 'Product Reduction');
  assert.equal(reduced.value, 200);

  assert.throws(() => {
    reduceMetrics([m1, real], (acc, v) => acc + v, 0, 'Contaminated Reduction');
  }, IncompatibleProvenanceAggregationError);
});

test('Typed Provenance Aggregation: assertCoexistenceOnly permits coexistence on same dashboard in segregated buckets', () => {
  const onChainMetric = makeMetric(10, PROVENANCE_SOURCES.ONCHAIN_SOL_BALANCE('Solana Localnet', 500));
  const simulatedMetric = makeMetric(18_420, PROVENANCE_SOURCES.SIMULATED_ATLAS_SNAPSHOT('Macro'));

  assert.doesNotThrow(() => {
    assertCoexistenceOnly([onChainMetric, simulatedMetric], 'Treasury Overview Dashboard');
  });
});

test('PROVENANCE_SOURCES: Off-chain algorithmic evaluation is distinguished from attested oracle', () => {
  const evalMeta = PROVENANCE_SOURCES.OFFCHAIN_EVALUATION({
    engineName: 'AeroSettle Matching Engine',
    status: 'PENDING_ATTESTATION',
  });
  assert.equal(evalMeta.provenance, 'EXTERNAL_VERIFIED');
  assert.equal(evalMeta.status, 'PENDING_ATTESTATION');
  assert.match(evalMeta.source, /Algorithmic Evaluation/);
});

test('PROVENANCE_SOURCES: Atlas scenario and fleet models are SIMULATED and SIMULATED_PROJECTION', () => {
  const macroMeta = PROVENANCE_SOURCES.SIMULATED_ATLAS_SNAPSHOT('Active Agents');
  assert.equal(macroMeta.provenance, 'SIMULATED');
  assert.equal(macroMeta.status, 'SIMULATED_PROJECTION');
  assert.match(macroMeta.source, /Atlas/);

  const agentModel = PROVENANCE_SOURCES.SIMULATED_AGENT_ECONOMICS('Kestrel-7');
  assert.equal(agentModel.provenance, 'SIMULATED');
  assert.equal(agentModel.status, 'SIMULATED_PROJECTION');

  const fleetModel = PROVENANCE_SOURCES.SIMULATED_FLEET_PROJECTION();
  assert.equal(fleetModel.provenance, 'SIMULATED');
  assert.equal(fleetModel.status, 'SIMULATED_PROJECTION');
});

test('Guardrail: assertNoSilentAggregation allows coexistence of verified and simulated metrics but blocks incompatible aggregation', () => {
  const verifiedBalance = 10;
  const simulatedPortfolio = 18_420;

  // 1) Coexistence: Showing on-chain balance (10) and simulated portfolio (18,420) simultaneously in separate buckets does NOT throw
  assert.doesNotThrow(() => {
    assertNoSilentAggregation(verifiedBalance, simulatedPortfolio, 'Treasury Segregated View');
  });

  assert.doesNotThrow(() => {
    assertNoSilentAggregation(simulatedPortfolio, { verified: verifiedBalance, simulated: simulatedPortfolio }, 'WalletPage Portfolio Total');
  });

  assert.doesNotThrow(() => {
    assertNoSilentAggregation(verifiedBalance, { verified: verifiedBalance, simulated: simulatedPortfolio }, 'WalletPage Verified Holdings');
  });

  // When one of them is zero, segregation is maintained and no error is thrown
  assert.doesNotThrow(() => {
    assertNoSilentAggregation(verifiedBalance, 0, 'Clean Verified Balance');
  });
  assert.doesNotThrow(() => {
    assertNoSilentAggregation(0, simulatedPortfolio, 'Clean Simulated Balance');
  });

  // 2) Incompatible aggregation: Combining or folding verified (10) and simulated (18,420) into a single aggregate (18,430) DOES throw
  const foldedIncompatibleSum = verifiedBalance + simulatedPortfolio; // 18,430

  assert.throws(
    () => {
      assertNoSilentAggregation(
        foldedIncompatibleSum,
        { verified: verifiedBalance, simulated: simulatedPortfolio },
        'Treasury Folded Aggregate Total',
        true
      );
    },
    {
      name: 'Error',
      message: /\[Conatus Provenance Guardrail Violation\] Incompatible economic aggregation in "Treasury Folded Aggregate Total"/,
    }
  );

  assert.throws(
    () => {
      assertNoSilentAggregation(
        verifiedBalance,
        simulatedPortfolio,
        foldedIncompatibleSum,
        'Treasury Folded Aggregate Form 2',
        true
      );
    },
    {
      name: 'Error',
      message: /\[Conatus Provenance Guardrail Violation\] Incompatible economic aggregation in "Treasury Folded Aggregate Form 2"/,
    }
  );
});

test('Segregation: segregateByProvenance partitions items into isolated buckets without data loss', () => {
  const items = [
    { id: 'live-sol', provenance: 'ONCHAIN_VERIFIED' as const, amount: 1.5 },
    { id: 'live-spl', provenance: 'ONCHAIN_VERIFIED' as const, amount: 250 },
    { id: 'telemetry', provenance: 'EXTERNAL_VERIFIED' as const, amount: 98.4 },
    { id: 'sim-revenue', provenance: 'SIMULATED' as const, amount: 3200 },
    { id: 'sim-escrow', provenance: 'SIMULATED' as const, amount: 18420 },
  ];

  const { onChainVerified, externalVerified, simulated } = segregateByProvenance(items);

  assert.equal(onChainVerified.length, 2);
  assert.equal(externalVerified.length, 1);
  assert.equal(simulated.length, 2);

  assert.equal(onChainVerified[0].id, 'live-sol');
  assert.equal(onChainVerified[1].id, 'live-spl');
  assert.equal(externalVerified[0].id, 'telemetry');
  assert.equal(simulated[0].id, 'sim-revenue');
  assert.equal(simulated[1].id, 'sim-escrow');
});

test('makeMetric bundles values with metadata', () => {
  const metric = makeMetric(5400, PROVENANCE_SOURCES.SIMULATED_FLEET_PROJECTION());
  assert.equal(metric.value, 5400);
  assert.equal(metric.meta.provenance, 'SIMULATED');
  assert.equal(metric.meta.status, 'SIMULATED_PROJECTION');
});

test('Visuals & i18n: getProvenanceVisuals strictly prevents unverified metrics from displaying as verified', () => {
  // UNAVAILABLE
  const unavail = getProvenanceVisuals('ONCHAIN_VERIFIED', 'en', 'UNAVAILABLE');
  assert.equal(unavail.tone, 'error');
  assert.equal(unavail.label, 'Unavailable');
  assert.equal(unavail.iconName, 'alert');
  assert.equal(unavail.badgeClass, 'provenance-badge-unavailable');

  // PENDING_VALIDATION
  const pending = getProvenanceVisuals('ONCHAIN_VERIFIED', 'es', 'PENDING_VALIDATION');
  assert.equal(pending.tone, 'accent');
  assert.equal(pending.label, 'Validación Pendiente');
  assert.equal(pending.iconName, 'clock');
  assert.equal(pending.badgeClass, 'provenance-badge-pending');

  // PENDING_ATTESTATION
  const pendingAttestation = getProvenanceVisuals('EXTERNAL_VERIFIED', 'es', 'PENDING_ATTESTATION');
  assert.equal(pendingAttestation.tone, 'accent');
  assert.equal(pendingAttestation.label, 'Atestación Pendiente');
  assert.equal(pendingAttestation.iconName, 'shield');
  assert.equal(pendingAttestation.badgeClass, 'provenance-badge-pending');

  // STALE
  const stale = getProvenanceVisuals('ONCHAIN_VERIFIED', 'en', 'STALE');
  assert.equal(stale.tone, 'warning');
  assert.equal(stale.label, 'Stale Data');
  assert.equal(stale.badgeClass, 'provenance-badge-stale');

  // VERIFIED: Only here is Verified displayed
  const verifiedOnChain = getProvenanceVisuals('ONCHAIN_VERIFIED', 'en', 'VERIFIED');
  assert.equal(verifiedOnChain.tone, 'success');
  assert.equal(verifiedOnChain.label, 'On-chain Verified');
  assert.equal(verifiedOnChain.iconName, 'check');
});

test('Visuals & i18n: getStatusLabel and getStatusTone format all 6 validation states accurately', () => {
  assert.equal(getStatusLabel('VERIFIED', 'en'), 'Verified');
  assert.equal(getStatusLabel('VERIFIED', 'es'), 'Verificado');
  assert.equal(getStatusTone('VERIFIED'), 'success');

  assert.equal(getStatusLabel('PENDING_ATTESTATION', 'en'), 'Pending Attestation');
  assert.equal(getStatusLabel('PENDING_ATTESTATION', 'es'), 'Atestación Pendiente');
  assert.equal(getStatusTone('PENDING_ATTESTATION'), 'accent');

  assert.equal(getStatusLabel('PENDING_VALIDATION', 'en'), 'Pending Validation');
  assert.equal(getStatusLabel('PENDING_VALIDATION', 'es'), 'Validación Pendiente');
  assert.equal(getStatusTone('PENDING_VALIDATION'), 'accent');

  assert.equal(getStatusLabel('STALE', 'en'), 'Stale Data');
  assert.equal(getStatusLabel('STALE', 'es'), 'Dato Obsoleto');
  assert.equal(getStatusTone('STALE'), 'warning');

  assert.equal(getStatusLabel('UNAVAILABLE', 'en'), 'Unavailable');
  assert.equal(getStatusLabel('UNAVAILABLE', 'es'), 'No Disponible');
  assert.equal(getStatusTone('UNAVAILABLE'), 'error');

  assert.equal(getStatusLabel('SIMULATED_PROJECTION', 'en'), 'Simulated Projection');
  assert.equal(getStatusLabel('SIMULATED_PROJECTION', 'es'), 'Proyección Simulada');
  assert.equal(getStatusTone('SIMULATED_PROJECTION'), 'warning');
});
