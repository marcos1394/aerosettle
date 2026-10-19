import test from 'node:test';
import assert from 'node:assert/strict';
import { ed25519 } from '@noble/curves/ed25519';
import {
  PROVENANCE_SOURCES,
  assertNoSilentAggregation,
  segregateByProvenance,
  type EconomicMetricMetadata,
  type AttestationPayload,
  serializeCanonicalAttestation,
  encodeBase58,
  _registerTestVerifierAuthority,
} from './provenance.ts';

// ─────────────────────────────────────────────────────────────────────────────
// 1. Overview Integration Tests: RPC Success, Failure, and Mixed Sources
// ─────────────────────────────────────────────────────────────────────────────

test('Integration [Overview]: RPC Success cleanly segregates on-chain verified from simulated snapshot', () => {
  // Simulating live RPC fetch response
  const liveRpcData = {
    agents: {
      data: [
        { agent_id: 'agent-live-1', active: true },
        { agent_id: 'agent-live-2', active: false },
      ],
    },
    missions: {
      data: [
        { work_order_account: 'wo-1', status: 'Open' },
        { work_order_account: 'wo-2', status: 'Submitted' },
      ],
    },
    observedAt: '2026-10-18T21:00:00.000Z',
    slot: 48920,
  };

  const snapshotAgents = 8;
  const liveActiveCount = liveRpcData.agents.data.filter((a) => a.active).length;

  // On-chain metric
  const liveMetric: EconomicMetricMetadata = PROVENANCE_SOURCES.ONCHAIN_AGENT_REGISTRY(
    'Solana Localnet',
    'VERIFIED',
    liveRpcData.slot
  );
  assert.equal(liveMetric.provenance, 'ONCHAIN_VERIFIED');
  assert.equal(liveMetric.status, 'VERIFIED');
  assert.equal(liveMetric.period, 'Slot 48920 (Ledger State)');

  // Macro simulated metric
  const macroMetric: EconomicMetricMetadata = PROVENANCE_SOURCES.SIMULATED_ATLAS_SNAPSHOT('Macro Agents');
  assert.equal(macroMetric.provenance, 'SIMULATED');
  assert.equal(macroMetric.status, 'SIMULATED_PROJECTION');

  // Verify that live active count and snapshot agents can coexist without error when segregated
  assert.doesNotThrow(() => {
    assertNoSilentAggregation(liveActiveCount, snapshotAgents, 'Overview Agent Population');
  });

  // But arithmetic aggregation (e.g. 2 + 8 = 10 into a single combined count) is strictly blocked
  const illegalFoldedCount = liveActiveCount + snapshotAgents;
  assert.throws(() => {
    assertNoSilentAggregation(
      illegalFoldedCount,
      { verified: liveActiveCount, simulated: snapshotAgents },
      'Overview Agent Population Folding',
      true
    );
  }, /\[Conatus Provenance Guardrail Violation\]/);
});

test('Integration [Overview]: RPC Failure marks on-chain sources as UNAVAILABLE without corrupting snapshot', () => {
  const rpcError = 'RPC Node connection refused on http://127.0.0.1:8899';
  const resourceState = { loading: false, error: rpcError, data: undefined };

  const onChainBadgeMeta = PROVENANCE_SOURCES.ONCHAIN_AGENT_REGISTRY(
    'Solana Localnet',
    resourceState.loading
      ? 'PENDING_VALIDATION'
      : resourceState.error
        ? 'UNAVAILABLE'
        : 'VERIFIED'
  );

  assert.equal(onChainBadgeMeta.provenance, 'ONCHAIN_VERIFIED');
  assert.equal(onChainBadgeMeta.status, 'UNAVAILABLE');

  // Snapshot remains unaffected and clearly identified as SIMULATED
  const fallbackSnapshotMeta = PROVENANCE_SOURCES.SIMULATED_ATLAS_SNAPSHOT('Active Agents');
  assert.equal(fallbackSnapshotMeta.provenance, 'SIMULATED');
  assert.equal(fallbackSnapshotMeta.status, 'SIMULATED_PROJECTION');
});

// ─────────────────────────────────────────────────────────────────────────────
// 2. Fleet Integration Tests: Identity vs Financial Metrics & Zero Aggregation
// ─────────────────────────────────────────────────────────────────────────────

test('Integration [Fleet]: On-chain registered agent identity is ONCHAIN_VERIFIED, but financial metrics are SIMULATED', () => {
  const onChainRegisteredAgent = {
    id: 'agent-pda-99',
    account: '4k3Dyjzvzp8eMZWUXbBCjEvwSkkk59S5iCNLY3QrkX6R',
    onChain: true,
    revenue30d: 3120, // Simulated financial model projection
    treasury: 4250,   // Simulated reserve
  };

  // 1) Identity check: on-chain account exists on ledger
  const identityMeta = PROVENANCE_SOURCES.ONCHAIN_AGENT_REGISTRY('Solana Localnet', 'VERIFIED');
  assert.equal(identityMeta.provenance, 'ONCHAIN_VERIFIED');
  assert.equal(identityMeta.status, 'VERIFIED');

  // 2) Financial metrics check: MUST be SIMULATED
  const financialMeta = PROVENANCE_SOURCES.SIMULATED_FLEET_PROJECTION();
  assert.equal(financialMeta.provenance, 'SIMULATED');
  assert.equal(financialMeta.status, 'SIMULATED_PROJECTION');
  assert.match(financialMeta.source, /Operator Fleet Model/);

  // 3) Guardrail check: Coexistence on screen of on-chain account (100) and simulated revenue (3120) does not throw
  const verifiedLedgerBalance = 100;
  assert.doesNotThrow(() => {
    assertNoSilentAggregation(verifiedLedgerBalance, onChainRegisteredAgent.revenue30d, 'Fleet Agent Coexistence');
  });

  // Attempting to fold simulated revenue into verified ledger balances is blocked
  const illegalAggregate = verifiedLedgerBalance + onChainRegisteredAgent.revenue30d;
  assert.throws(() => {
    assertNoSilentAggregation(
      illegalAggregate,
      { verified: verifiedLedgerBalance, simulated: onChainRegisteredAgent.revenue30d },
      'Fleet Agent Revenue Folding',
      true
    );
  }, /\[Conatus Provenance Guardrail Violation\]/);
});

test('Integration [Fleet]: All 5 Fleet Macro KPIs are strictly marked SIMULATED', () => {
  const kpiMetas = [
    PROVENANCE_SOURCES.SIMULATED_FLEET_PROJECTION(), // Fleet revenue (30d)
    PROVENANCE_SOURCES.SIMULATED_FLEET_PROJECTION(), // Operating costs (30d)
    PROVENANCE_SOURCES.SIMULATED_FLEET_PROJECTION(), // Net margin (30d)
    PROVENANCE_SOURCES.SIMULATED_FLEET_PROJECTION(), // Fleet Conatus ratio
    PROVENANCE_SOURCES.SIMULATED_FLEET_PROJECTION(), // Combined treasury & runway
  ];

  for (const meta of kpiMetas) {
    assert.equal(meta.provenance, 'SIMULATED');
    assert.equal(meta.status, 'SIMULATED_PROJECTION');
  }
});

// ─────────────────────────────────────────────────────────────────────────────
// 3. Treasury (WalletPage) Integration Tests: Slots, Commitments & Errors
// ─────────────────────────────────────────────────────────────────────────────

test('Integration [Treasury]: Confirmed slot and commitment are verified and displayed', () => {
  const mintAddress = 'HTHpns7gqLAhSBhAzqxhYdyHv9HeXkkRW6aHQfdUjL1G';
  const confirmedSlot = 51200;
  const commitment = 'confirmed';

  const splMeta = PROVENANCE_SOURCES.ONCHAIN_SPL_BALANCE({
    mint: mintAddress,
    network: 'Solana Localnet',
    slot: confirmedSlot,
    commitment,
    status: 'VERIFIED',
  });

  assert.equal(splMeta.provenance, 'ONCHAIN_VERIFIED');
  assert.equal(splMeta.status, 'VERIFIED');
  assert.equal(splMeta.period, `Slot ${confirmedSlot} (${commitment})`);
  assert.equal(splMeta.network, 'Solana Localnet');

  const solMeta = PROVENANCE_SOURCES.ONCHAIN_SOL_BALANCE({
    network: 'Solana Localnet',
    slot: confirmedSlot,
    commitment,
    status: 'VERIFIED',
  });

  assert.equal(solMeta.provenance, 'ONCHAIN_VERIFIED');
  assert.equal(solMeta.status, 'VERIFIED');
  assert.equal(solMeta.period, `Slot ${confirmedSlot} (${commitment})`);
});

test('Integration [Treasury]: RPC Failure assigns UNAVAILABLE status to on-chain balances', () => {
  const mintAddress = 'HTHpns7gqLAhSBhAzqxhYdyHv9HeXkkRW6aHQfdUjL1G';
  const rpcError = 'RPC Node failed to respond within 5000ms';

  const splErrorMeta = PROVENANCE_SOURCES.ONCHAIN_SPL_BALANCE({
    mint: mintAddress,
    network: 'Solana Localnet',
    status: 'UNAVAILABLE',
    error: rpcError,
  });

  assert.equal(splErrorMeta.provenance, 'ONCHAIN_VERIFIED');
  assert.equal(splErrorMeta.status, 'UNAVAILABLE');
  assert.match(splErrorMeta.source, /RPC Node failed to respond/);
  assert.equal(splErrorMeta.period, 'RPC Query Error');
});

test('Integration [Treasury]: Stale slot data is marked with STALE validation status', () => {
  const mintAddress = 'HTHpns7gqLAhSBhAzqxhYdyHv9HeXkkRW6aHQfdUjL1G';
  const staleSlot = 12000; // Old slot

  const staleMeta = PROVENANCE_SOURCES.ONCHAIN_SPL_BALANCE({
    mint: mintAddress,
    network: 'Solana Localnet',
    slot: staleSlot,
    status: 'STALE',
  });

  assert.equal(staleMeta.provenance, 'ONCHAIN_VERIFIED');
  assert.equal(staleMeta.status, 'STALE');
});

test('Integration [Treasury]: Live token balance is strictly segregated from simulated portfolio total', () => {
  const liveVerifiedTokenBalance = 450; // Real SPL tokens in localnet account
  const simulatedAvailable = 18_420;   // Atlas scenario available
  const portfolioTotal = 32_800;       // Simulated portfolio valuation

  // Coexistence of live token balance (450) and simulated portfolio total (32,800) in separate panels does NOT throw
  assert.doesNotThrow(() => {
    assertNoSilentAggregation(liveVerifiedTokenBalance, simulatedAvailable, 'WalletPage Portfolio Coexistence');
    assertNoSilentAggregation(portfolioTotal, { verified: liveVerifiedTokenBalance, simulated: simulatedAvailable }, 'WalletPage Portfolio Total');
  });

  // Assert guardrail prevents combining live tokens with simulated totals into a single aggregate
  const illegalMergedSum = liveVerifiedTokenBalance + simulatedAvailable;
  assert.throws(() => {
    assertNoSilentAggregation(illegalMergedSum, { verified: liveVerifiedTokenBalance, simulated: simulatedAvailable }, 'WalletPage Portfolio Available', true);
  }, /\[Conatus Provenance Guardrail Violation\]/);

  assert.throws(() => {
    assertNoSilentAggregation(liveVerifiedTokenBalance + portfolioTotal, { verified: liveVerifiedTokenBalance, simulated: portfolioTotal }, 'WalletPage Portfolio Total', true);
  }, /\[Conatus Provenance Guardrail Violation\]/);
});

// ─────────────────────────────────────────────────────────────────────────────
// 4. Attestation Verification Tests: Requirement for Cryptographic Signature
// ─────────────────────────────────────────────────────────────────────────────

test('Integration [Attestation]: External telemetry without cryptographic signature is PENDING_ATTESTATION', () => {
  // An external data record appearing in a catalog without an enclave signature
  const catalogEntry = {
    source: 'Edge Robot Camera Telemetry',
    verifier: '9y3Dyjzvzp8eMZWUXbBCjEvwSkkk59S5iCNLY3QrkX6R',
  };

  const metadata = PROVENANCE_SOURCES.EXTERNAL_TELEMETRY({
    verifierAuthority: catalogEntry.verifier,
    // attestationSignature is missing!
  });

  assert.equal(metadata.provenance, 'EXTERNAL_VERIFIED');
  assert.equal(metadata.status, 'PENDING_ATTESTATION');
  assert.notEqual(metadata.status, 'VERIFIED');
});

test('Integration [Attestation]: External telemetry WITH verified cryptographic signature achieves VERIFIED status', () => {
  // Generate ephemeral keypair representing a registered hardware enclave authority
  const privKey = ed25519.utils.randomPrivateKey();
  const pubKeyBytes = ed25519.getPublicKey(privKey);
  const trustedVerifier = encodeBase58(pubKeyBytes);

  const unregister = _registerTestVerifierAuthority(trustedVerifier);

  try {
    const payload: AttestationPayload = {
      domain: 'conatus:attestation:v1',
      network: 'solana:localnet',
      subject: 'AgentEnclave111111111111111111111111111111111',
      evidenceHash: 'e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855',
      nonce: 'integration-nonce-success-101',
      expiresAt: Math.floor(Date.now() / 1000) + 7200,
    };

    const canonicalBytes = serializeCanonicalAttestation(payload);
    const signatureBytes = ed25519.sign(canonicalBytes, privKey);
    const validSignature = encodeBase58(signatureBytes);

    const metadata = PROVENANCE_SOURCES.EXTERNAL_TELEMETRY({
      verifierAuthority: trustedVerifier,
      attestationSignature: validSignature,
      payload,
      verifiedAt: '2026-10-18T20:50:00Z',
    });

    assert.equal(metadata.provenance, 'EXTERNAL_VERIFIED');
    assert.equal(metadata.status, 'VERIFIED');
    assert.equal(metadata.period, 'Attested 2026-10-18T20:50:00Z');
    assert.match(metadata.source, /Hardware Enclave Ed25519/);
  } finally {
    unregister();
  }
});
