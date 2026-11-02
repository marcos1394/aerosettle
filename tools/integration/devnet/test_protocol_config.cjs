'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const {createRequire} = require('node:module');
const path = require('node:path');
const fromBootstrap = createRequire(path.resolve(__dirname, '../../bootstrap/package.json'));
const {Keypair, PublicKey} = fromBootstrap('@solana/web3.js');
const {plan, validatePlan, buildTransaction, approvalValid, approvedEvidence} =
  require('./protocol_config.cjs');

const current = () => ({evidence: approvedEvidence(), protocol: null,
  payer: 7_416_208_160, admin: 0, rent: 1_437_640, systemRent: 650_240});

test('plan is deterministic and binds Devnet genesis, deployment and spending cap', () => {
  const first = plan(current());
  assert.deepEqual(first, plan(current()));
  assert.equal(first.network_id_hex,
    new PublicKey(first.genesis_hash).toBuffer().toString('hex'));
  assert.equal(first.protocol_deployment_id_hex, first.approved_con35_deployment_id);
  assert.equal(first.max_payer_debit_lamports,
    first.funding_lamports + first.max_fee_lamports);
  validatePlan(first, current());
  for (const change of [
    {genesis_hash: 'wrong'}, {program_id: 'wrong'}, {test_mint_pubkey: 'wrong'},
    {protocol_admin_pubkey: 'wrong'}, {funding_lamports: 1},
    {max_payer_debit_lamports: 100_000_000}, {approval_id: 'CON35'},
  ]) {
    assert.throws(() => validatePlan({...first, ...change}, current()),
      /Prepared plan differs/);
  }
});

test('missing rent, existing config, or changed administrator balance fails closed', () => {
  const first = plan(current());
  assert.throws(() => validatePlan(first, {...current(), protocol: {}}),
    /already initialized/);
  assert.throws(() => validatePlan(first, {...current(), admin: 1}),
    /Admin balance changed/);
  assert.throws(() => validatePlan(first, {...current(), payer: 0}),
    /lacks test SOL/);
  const insufficient = {...current(), rent: 2_500_000};
  assert.throws(() => validatePlan(plan(insufficient), insufficient),
    /lacks rent/);
});

test('submission requires this exact CON-36 approval in both channels', () => {
  const first = plan(current());
  assert.equal(approvalValid(first, undefined, {}), false);
  assert.equal(approvalValid(first, first.approval_id, {}), false);
  assert.equal(approvalValid(first, '06c7dfa7528460969a5ca1e8bd001f9c9f1f1f0df3d69fe36649e413e0b14ae6',
    {CON36_APPROVED_PROTOCOL_CONFIG_ID: first.approval_id}), false);
  assert.equal(approvalValid(first, first.approval_id,
    {CON36_APPROVED_PROTOCOL_CONFIG_ID: first.approval_id}), true);
});

test('transaction contains only bounded test funding and exact initialization payload', () => {
  const first = plan(current());
  const payer = Keypair.generate();
  const admin = Keypair.generate();
  const blockhash = Keypair.generate().publicKey.toBase58();
  const tx = buildTransaction(first, payer, admin, blockhash);
  assert.equal(tx.instructions.length, 2);
  assert.equal(tx.instructions[0].programId.toBase58(),
    '11111111111111111111111111111111');
  assert.equal(tx.instructions[0].data.readBigUInt64LE(4), 3_000_000n);
  assert.equal(tx.instructions[1].programId.toBase58(), first.program_id);
  assert.equal(tx.instructions[1].keys[0].pubkey.toBase58(), first.protocol_config_pda);
  assert.equal(tx.instructions[1].data.subarray(8, 40).toString('hex'), first.network_id_hex);
  assert.equal(tx.instructions[1].data.subarray(40, 72).toString('hex'),
    first.protocol_deployment_id_hex);
});
