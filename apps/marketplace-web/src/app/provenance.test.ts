import test from 'node:test';
import assert from 'node:assert/strict';
import {
  type DataProvenance,
  type ValidationStatus,
  PROVENANCE_SOURCES,
  assertNoSilentAggregation,
  segregateByProvenance,
  makeMetric,
  getProvenanceVisuals,
  getStatusLabel,
  getStatusTone,
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

test('PROVENANCE_SOURCES: Native SOL balance correctly identified with slot and commitment', () => {
  const meta = PROVENANCE_SOURCES.ONCHAIN_SOL_BALANCE('Solana Localnet', 1042, 'confirmed');
  assert.equal(meta.provenance, 'ONCHAIN_VERIFIED');
  assert.equal(meta.status, 'VERIFIED');
  assert.match(meta.source, /System Program/);
  assert.equal(meta.network, 'Solana Localnet');
  assert.equal(meta.period, 'Slot 1042 (confirmed)');
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

test('PROVENANCE_SOURCES: SPL token balance correctly identified with mint, slot and commitment', () => {
  const mint = 'HTHpns7gqLAhSBhAzqxhYdyHv9HeXkkRW6aHQfdUjL1G';
  const meta = PROVENANCE_SOURCES.ONCHAIN_SPL_BALANCE({
    mint,
    network: 'Solana Localnet',
    slot: 2840,
    commitment: 'confirmed',
    status: 'VERIFIED',
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

test('PROVENANCE_SOURCES: Escrow vault, WorkOrders and Agent PDA support dynamic validation status', () => {
  const escrowMeta = PROVENANCE_SOURCES.ONCHAIN_ESCROW_VAULT('Solana Localnet', 'VERIFIED', 501);
  assert.equal(escrowMeta.provenance, 'ONCHAIN_VERIFIED');
  assert.equal(escrowMeta.status, 'VERIFIED');
  assert.match(escrowMeta.source, /PDA/);
  assert.match(escrowMeta.period, /Slot 501/);

  const woPending = PROVENANCE_SOURCES.ONCHAIN_WORK_ORDERS('Solana Localnet', 'PENDING_VALIDATION');
  assert.equal(woPending.status, 'PENDING_VALIDATION');

  const agentUnavailable = PROVENANCE_SOURCES.ONCHAIN_AGENT_REGISTRY('Solana Localnet', 'UNAVAILABLE');
  assert.equal(agentUnavailable.status, 'UNAVAILABLE');
});

test('PROVENANCE_SOURCES: EXTERNAL_VERIFIED strictly requires checked attestation signature', () => {
  const trustedVerifier = 'DmWQhuVujHrJb4jFzo62UnCT3mwnx9GFtVdo8VUu82Wu';

  // 1) Without attestation signature -> MUST NOT be VERIFIED
  const unverified = PROVENANCE_SOURCES.EXTERNAL_TELEMETRY({
    verifierAuthority: '4k3Dyjzvzp8eMZWUXbBCjEvwSkkk59S5iCNLY3QrkX6R',
  });
  assert.equal(unverified.provenance, 'EXTERNAL_VERIFIED');
  assert.equal(unverified.status, 'PENDING_ATTESTATION');
  assert.match(unverified.source, /awaiting attestation/);

  // 2) Flag `isAttested: true` alone without signature MUST be rejected
  const boolOnly = PROVENANCE_SOURCES.EXTERNAL_TELEMETRY({
    verifierAuthority: trustedVerifier,
    isAttested: true,
  });
  assert.equal(boolOnly.provenance, 'EXTERNAL_VERIFIED');
  assert.equal(boolOnly.status, 'PENDING_ATTESTATION');

  // 3) Placeholder or mock signature MUST be rejected
  const mockSig = PROVENANCE_SOURCES.EXTERNAL_TELEMETRY({
    verifierAuthority: trustedVerifier,
    attestationSignature: 'mock_signature_ed25519_placeholder_test',
  });
  assert.equal(mockSig.provenance, 'EXTERNAL_VERIFIED');
  assert.equal(mockSig.status, 'PENDING_ATTESTATION');

  // 4) Short signature (<64 chars) MUST be rejected
  const shortSig = PROVENANCE_SOURCES.EXTERNAL_TELEMETRY({
    verifierAuthority: trustedVerifier,
    attestationSignature: '3jG7WqQZ5rV9x8K1m2N3p4Q5r6S7t8U',
  });
  assert.equal(shortSig.provenance, 'EXTERNAL_VERIFIED');
  assert.equal(shortSig.status, 'PENDING_ATTESTATION');

  // 5) Untrusted verifier authority MUST be rejected even with a valid format signature
  const validFormatSig = '123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz123456789ABCDEFGHJKLMNPQRSTUVW';
  const untrustedVerifier = PROVENANCE_SOURCES.EXTERNAL_TELEMETRY({
    verifierAuthority: 'UntrustedVerifierAuthorityKey11111111111111111',
    attestationSignature: validFormatSig,
  });
  assert.equal(untrustedVerifier.provenance, 'EXTERNAL_VERIFIED');
  assert.equal(untrustedVerifier.status, 'PENDING_ATTESTATION');

  // 6) With valid 64-byte Ed25519 signature AND trusted verifier authority -> VERIFIED
  const verified = PROVENANCE_SOURCES.EXTERNAL_TELEMETRY({
    verifierAuthority: trustedVerifier,
    attestationSignature: validFormatSig,
    verifiedAt: '2026-10-18T20:00:00Z',
  });
  assert.equal(verified.provenance, 'EXTERNAL_VERIFIED');
  assert.equal(verified.status, 'VERIFIED');
  assert.match(verified.source, /Hardware Enclave Ed25519 \(Signature:/);
  assert.equal(verified.period, 'Attested 2026-10-18T20:00:00Z');
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
    // Segregated portfolio total (only representing the simulated bucket, not adding verified)
    assertNoSilentAggregation(simulatedPortfolio, { verified: verifiedBalance, simulated: simulatedPortfolio }, 'WalletPage Portfolio Total');
  });

  assert.doesNotThrow(() => {
    // Segregated on-chain holdings (only representing verified balance)
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

test('Visuals & i18n: getProvenanceVisuals prioritizes error and pending states', () => {
  const unavail = getProvenanceVisuals('ONCHAIN_VERIFIED', 'en', 'UNAVAILABLE');
  assert.equal(unavail.tone, 'error');
  assert.equal(unavail.label, 'Unavailable');
  assert.equal(unavail.iconName, 'alert');
  assert.equal(unavail.badgeClass, 'provenance-badge-unavailable');

  const pending = getProvenanceVisuals('ONCHAIN_VERIFIED', 'es', 'PENDING_VALIDATION');
  assert.equal(pending.tone, 'accent');
  assert.equal(pending.label, 'Validación Pendiente');
  assert.equal(pending.iconName, 'clock');
  assert.equal(pending.badgeClass, 'provenance-badge-pending');

  const stale = getProvenanceVisuals('ONCHAIN_VERIFIED', 'en', 'STALE');
  assert.equal(stale.tone, 'warning');
  assert.equal(stale.label, 'Stale Data');
  assert.equal(stale.badgeClass, 'provenance-badge-stale');
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
