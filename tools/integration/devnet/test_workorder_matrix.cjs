'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const crypto = require('node:crypto');
const {createRequire} = require('node:module');
const path = require('node:path');
const fromBootstrap = createRequire(path.resolve(__dirname, '../../bootstrap/package.json'));
const {Keypair} = fromBootstrap('@solana/web3.js');
const {spec, steps, transactionInstruction, manifest, expectedFailure,
  attestationHash} = require('./workorder_matrix.cjs');

test('seven WorkOrders give exactly eight economic outcomes', () => {
  const cases = [
    ['E2E-01-full', 7, ['duplicate']],
    ['E2E-02-zero', 7, []],
    ['E2E-03-proportional', 8, ['donate']],
    ['E2E-04-invalid-shared', 8, ['invalid_shared']],
    ['E2E-05-valid-shared', 7, []],
    ['E2E-06-invalid-mint', 8, ['wrong_mint']],
    ['E2E-07-wrong-beneficiary', 8, ['wrong_beneficiary']],
  ];
  for (const [name, count, extras] of cases) {
    const planned = steps(spec(name));
    assert.equal(planned.length, count);
    assert.equal(planned.at(-1), name === 'E2E-01-full' ? 'duplicate' : 'settle');
    for (const phase of extras) assert.ok(planned.includes(phase));
  }
  assert.equal(expectedFailure('invalid_shared'), 'SettlementInvalidCreatorRefund');
  assert.equal(expectedFailure('wrong_beneficiary'), 'SettlementInvalidBeneficiary');
  assert.equal(expectedFailure('wrong_mint'), 'InvalidTokenMint');
  assert.equal(expectedFailure('duplicate'), 'SettlementNotVerified');
});

test('phase manifest binds Devnet, exact instruction, payer and maximum debit', () => {
  const s = spec('E2E-02-zero');
  const ix = transactionInstruction(s, 'create', 1793390703, null);
  const payer = Keypair.generate();
  const plan = manifest(s, 'create', ix, payer, 3_622_040);
  assert.equal(plan.network, 'solana:devnet');
  assert.equal(plan.test_mint, s.token_mint);
  assert.equal(plan.amount_base_units, 1_000_000);
  assert.equal(plan.max_payer_debit_lamports, 3_642_040);
  assert.equal(plan.instruction_program,
    'CeA1P1NSuPLUH31KsT4j3pZeBsknQZ3NSC6GUAqcsCLy');
  assert.equal(plan.instruction_accounts[1].pubkey, s.work_order_pda);
  assert.equal(plan.payer, payer.publicKey.toBase58());
  const {manifest_id, ...body} = plan;
  assert.equal(manifest_id,
    crypto.createHash('sha256').update(JSON.stringify(body)).digest('hex'));
  assert.notEqual(manifest(s, 'create', ix, payer, 3_622_041).manifest_id,
    manifest_id);
});

test('attestation commitment binds verifier, completion and timestamp', () => {
  const s = spec('E2E-03-proportional');
  const receipt = crypto.createHash('sha256').update('receipt').digest();
  const evidence = crypto.createHash('sha256').update('evidence').digest();
  const first = attestationHash(s, receipt, evidence, 6000, 1793390703);
  assert.equal(first.length, 32);
  assert.notDeepEqual(first, attestationHash(s, receipt, evidence, 6001, 1793390703));
  assert.notDeepEqual(first, attestationHash(s, receipt, evidence, 6000, 1793390704));
});
