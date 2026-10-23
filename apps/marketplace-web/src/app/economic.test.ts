import test from 'node:test';
import assert from 'node:assert/strict';
import { ed25519 } from '@noble/curves/ed25519';
import { MarketplaceApiError } from '@aerosettle/marketplace-sdk';
import type { AgentSolvencyAssessment, MarketplaceClient } from '@aerosettle/marketplace-sdk';
import { encodeBase58 } from './provenance.ts';
import { MINT, PROGRAM_ID } from './config.ts';
import {
  assessmentFor, contextKey, contextsOf, formatBaseUnits, formatUnits,
  isProductiveAssessment, loadOwnerEconomy, ownerAuthHeaders,
} from './economic.ts';

const seed = new Uint8Array(32).fill(7);
const owner = encodeBase58(ed25519.getPublicKey(seed));
const account = encodeBase58(ed25519.getPublicKey(new Uint8Array(32).fill(8)));
const context = {
  agent_account: account,
  network: 'solana:localnet',
  genesis_hash: 'HP9XKTusRPGC78EFDpR9xdEq6simL2vqyDdrMvn6Vacg',
  program_id: PROGRAM_ID.toBase58(),
  token_mint: MINT.toBase58(),
};
const meta = { program_id: PROGRAM_ID.toBase58() };
const signer = {
  publicKey: owner,
  signMessage: async (message: Uint8Array) => ed25519.sign(message, seed),
};

function assessment(status: 'VALID' | 'INSUFFICIENT_DATA', provenance: string) {
  return {
    ...context,
    calculation_status: status,
    provenance,
    data_coverage_status: status === 'VALID' ? 'COMPLETE' : 'INCOMPLETE',
    exclusion_reasons: status === 'VALID' ? [] : ['productive_economic_origin_verification_unavailable'],
  } as AgentSolvencyAssessment;
}

function clientFor(overrides: Record<string, unknown> = {}) {
  const calls: Array<{ method: string; headers: Record<string, string> }> = [];
  const capture = (method: string, options: { authHeaders?: Record<string, string> }) => {
    calls.push({ method, headers: options.authHeaders ?? {} });
  };
  const client = {
    getAgentEconomicSummary: async (_account: string, _filters: unknown, options: { authHeaders?: Record<string, string> }) => {
      capture('summary', options);
      return { data: [{ ...context, total_income_reconciled_str: '9007199254740993' }], meta };
    },
    getAgentSolvency: async (_account: string, _filters: unknown, options: { authHeaders?: Record<string, string> }) => {
      capture('solvency', options);
      return { data: [assessment('INSUFFICIENT_DATA', 'HISTORICAL_UNVERIFIED')], meta };
    },
    getAgentSolvencyHistory: async (_account: string, _filters: unknown, options: { authHeaders?: Record<string, string> }) => {
      capture('history', options);
      return { data: [], meta };
    },
    listAgentCosts: async (_account: string, _filters: unknown, options: { authHeaders?: Record<string, string> }) => {
      capture('costs', options);
      return { data: [], page: { has_more: false }, meta };
    },
    listAgentReserves: async (_account: string, _filters: unknown, options: { authHeaders?: Record<string, string> }) => {
      capture('reserves', options);
      return { data: [], meta };
    },
    listEconomicMovements: async (_account: string, _filters: unknown, options: { authHeaders?: Record<string, string> }) => {
      capture('movements', options);
      return { data: [], page: { has_more: false }, meta };
    },
    ...overrides,
  } as unknown as MarketplaceClient;
  return { client, calls };
}

test('owner challenge is authentic, scoped to agent, reused in memory, and rejects another wallet', async () => {
  const signal = new AbortController().signal;
  const first = await ownerAuthHeaders(account, owner, signer, signal);
  const second = await ownerAuthHeaders(account, owner, signer, signal);
  assert.deepEqual(first, second);
  const message = new TextEncoder().encode(`conatus:economic-auth:v1:${first['X-Timestamp']}:${account}`);
  // A valid Ed25519 signer produced the header, not an asserted owner string.
  // @ts-expect-error bs58 lacks bundled TypeScript declarations in this workspace
  const { default: bs58 } = await import('bs58');
  assert.equal(ed25519.verify(bs58.decode(first['X-Signature']), message, ed25519.getPublicKey(seed)), true);
  await assert.rejects(ownerAuthHeaders(account, 'another-owner', signer, signal), /FORBIDDEN/);
  const aborted = new AbortController(); aborted.abort();
  await assert.rejects(ownerAuthHeaders(account, owner, signer, aborted.signal), /AbortError/);
});

test('private economy uses six signed SDK reads and keeps exact context and u64 strings', async () => {
  const { client, calls } = clientFor();
  const result = await loadOwnerEconomy(client, account, owner, signer, new AbortController().signal);
  assert.equal(calls.length, 6);
  assert.equal(new Set(calls.map((call) => call.headers['X-Signature'])).size, 1);
  assert.equal(contextsOf(result).length, 1);
  assert.equal(assessmentFor(result, context)?.calculation_status, 'INSUFFICIENT_DATA');
  assert.equal(result.summaries[0].total_income_reconciled_str, '9007199254740993');
  assert.equal(formatBaseUnits('9007199254740993', MINT.toBase58()), '9007199254.740993 USDC');
  assert.equal(formatUnits('1000000001', 9), '1.000000001');
  assert.equal(isProductiveAssessment(result.assessments[0]), false);
});

test('incompatible monetary context, wrong program, network error and stale request fail closed', async () => {
  const wrongRow = clientFor({
    getAgentEconomicSummary: async () => ({
      data: [{ ...context, token_mint: 'different-mint' }], meta,
    }),
  });
  const snapshot = await loadOwnerEconomy(wrongRow.client, account, owner, signer, new AbortController().signal);
  assert.equal(contextsOf(snapshot).length, 2);
  assert.notEqual(contextKey(contextsOf(snapshot)[0]), contextKey(contextsOf(snapshot)[1]));

  const wrongProgram = clientFor({
    getAgentEconomicSummary: async () => ({ data: [{ ...context, program_id: 'wrong-program' }], meta }),
  });
  await assert.rejects(loadOwnerEconomy(wrongProgram.client, account, owner, signer, new AbortController().signal), /incomplete or incompatible/);

  const networkError = clientFor({
    getAgentEconomicSummary: async () => { throw new Error('network unavailable'); },
  });
  await assert.rejects(loadOwnerEconomy(networkError.client, account, owner, signer, new AbortController().signal), /network unavailable/);

  const unauthorized = clientFor({
    getAgentEconomicSummary: async () => { throw new MarketplaceApiError(403, 'FORBIDDEN', 'Owner changed'); },
  });
  await assert.rejects(loadOwnerEconomy(unauthorized.client, account, owner, signer, new AbortController().signal), /403 FORBIDDEN/);

  const contextOnlyInMovement = clientFor({
    getAgentEconomicSummary: async () => ({ data: [], meta }),
    getAgentSolvency: async () => ({ data: [], meta }),
    listEconomicMovements: async () => ({
      data: [{ ...context, movement_id: 'm1' }], page: { has_more: false }, meta,
    }),
  });
  const movementSnapshot = await loadOwnerEconomy(contextOnlyInMovement.client, account, owner, signer, new AbortController().signal);
  assert.equal(contextsOf(movementSnapshot).length, 1);

  const mixedAssets = clientFor({
    getAgentSolvency: async () => ({ data: [{ calculation_status: 'MIXED_ASSET_CONTEXT' }], meta }),
  });
  const mixedSnapshot = await loadOwnerEconomy(mixedAssets.client, account, owner, signer, new AbortController().signal);
  assert.equal(mixedSnapshot.mixedAssetContext, true);
  assert.equal(mixedSnapshot.assessments.length, 0);

  const controller = new AbortController();
  controller.abort();
  await assert.rejects(loadOwnerEconomy(clientFor().client, account, owner, signer, controller.signal), /AbortError/);
});

test('productive badge requires valid status, complete coverage and verified lineage', () => {
  assert.equal(isProductiveAssessment(assessment('INSUFFICIENT_DATA', 'LIVE_RPC_AND_EXTERNAL_ATTESTED')), false);
  assert.equal(isProductiveAssessment(assessment('VALID', 'SYNTHETIC_TEST')), false);
  assert.equal(isProductiveAssessment(assessment('VALID', 'LIVE_RPC_AND_EXTERNAL_ATTESTED')), true);
  assert.equal(isProductiveAssessment({ ...assessment('VALID', 'LIVE_RPC'), calculation_status: 'UNDEFINED_RATIO' }), false);
});
