'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const {createRequire} = require('node:module');
const fromBootstrap = createRequire(path.resolve(__dirname, '../../bootstrap/package.json'));
const {PublicKey} = fromBootstrap('@solana/web3.js');
const {makePlan, validatePlan, createInstruction} = require('./workorder_create.cjs');

const committed = JSON.parse(fs.readFileSync(path.resolve(__dirname,
  '../../../evidence/con36/e2e-01-create-plan.json')));
function observed() {
  const raw = Buffer.alloc(155);
  raw[8] = 1;
  new PublicKey('27cyzd58RswQRbSuR3cKh4xv2gWgZ7awb3tUtoT7hYLB')
    .toBuffer().copy(raw, 9);
  Buffer.from('ce59db5080fc2c6d3bcf7ca90712d3c2e5e6c28f27f0dfbb9953bdb0894c03ab',
    'hex').copy(raw, 41);
  Buffer.from('06c7dfa7528460969a5ca1e8bd001f9c9f1f1f0df3d69fe36649e413e0b14ae6',
    'hex').copy(raw, 105);
  return {genesis: committed.genesis_hash, order: null,
    protocol: {owner: new PublicKey(committed.program_id), data: raw},
    now: committed.prepared_at_unix + 60,
    rent: committed.work_order_rent_lamports,
    creatorBalance: 100_000_000,
    sourceAmount: 7_100_000n};
}

test('prepared plan binds one Devnet WorkOrder and has no transaction approval', () => {
  assert.deepEqual(makePlan(committed.prepared_at_unix,
    committed.work_order_rent_lamports), committed);
  assert.equal(committed.status, 'PREPARED_NOT_AUTHORIZED');
  assert.equal(committed.transaction_submitted, false);
  assert.equal(committed.max_creator_debit_lamports,
    committed.work_order_rent_lamports + committed.max_fee_lamports);
  validatePlan(committed, observed());
});

test('mutated identity, amount, deadline, or approval cannot be replayed', () => {
  for (const change of [
    {genesis_hash: 'wrong'}, {program_id: 'wrong'},
    {test_mint_pubkey: 'wrong'}, {creator_pubkey: 'wrong'},
    {total_amount_base_units: 2_000_000},
    {verification_deadline_unix: committed.verification_deadline_unix + 1},
    {approval_id: '5dbc0681980e3fcf78ad35f1548ccf6dd0751eb3a697b6dcc0bc0a6f137c21a6'},
  ]) assert.throws(() => validatePlan({...committed, ...change}, observed()),
    /manifest integrity mismatch/);
});

test('missing or altered live evidence fails closed', () => {
  const current = observed();
  for (const change of [
    {genesis: 'wrong'}, {order: {}}, {creatorBalance: 0},
    {sourceAmount: 999_999n}, {rent: current.rent + 1},
    {now: committed.execution_deadline_unix},
  ]) assert.throws(() => validatePlan(committed, {...current, ...change}));
  const badProtocol = observed();
  badProtocol.protocol.data[146] = 1;
  assert.throws(() => validatePlan(committed, badProtocol), /ProtocolConfig identity/);
});

test('only the approved Anchor instruction and accounts are encoded', () => {
  const ix = createInstruction(committed);
  assert.equal(ix.programId.toBase58(), committed.program_id);
  assert.deepEqual(ix.keys.map(x => x.pubkey.toBase58()), [
    committed.protocol_config_pda,
    committed.work_order_pda,
    committed.creator_pubkey,
    '11111111111111111111111111111111',
  ]);
  assert.equal(ix.keys.filter(x => x.isSigner).length, 1);
  assert.equal(ix.keys.find(x => x.isSigner).pubkey.toBase58(),
    committed.creator_pubkey);
  assert.ok(ix.data.includes(Buffer.from(committed.work_order_id_hex, 'hex')));
  assert.ok(ix.data.includes(Buffer.from(committed.manifest_hash_hex, 'hex')));
  assert.ok(ix.data.includes(new PublicKey(committed.test_mint_pubkey).toBuffer()));
  assert.ok(ix.data.includes(new PublicKey(committed.verifier_pubkey).toBuffer()));
});
