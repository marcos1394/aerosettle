'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const {plan, validatePlan, instructions, approvalValid} = require('./asset_funding.cjs');

const current = () => ({protocol: {payer: 7_416_208_160, mintSupply: '0'},
  creatorBalance: 0, ownerBalance: 0, creatorAccount: null,
  ownerAccount: null, ataRent: 1_488_440});

test('asset plan binds seven-order supply and exact Devnet-only spend ceiling', () => {
  const prepared = plan(current());
  assert.equal(prepared.network, 'solana:devnet');
  assert.equal(prepared.mint_base_units, 7_100_000);
  assert.equal(prepared.max_payer_debit_lamports, 202_996_880);
  assert.equal(prepared.transaction_submitted, false);
  validatePlan(prepared, current());
  for (const delta of [{genesis_hash: 'other'}, {mint_pubkey: 'other'},
    {mint_base_units: 7_100_001}, {creator_pubkey: 'other'},
    {max_payer_debit_lamports: 300_000_000}, {approval_id: 'CON35'}]) {
    assert.throws(() => validatePlan({...prepared, ...delta}, current()),
      /plan differs/);
  }
});

test('funded or created accounts, insufficient payer and old approval fail closed', () => {
  const prepared = plan(current());
  assert.throws(() => validatePlan(prepared, {...current(), creatorBalance: 1}),
    /already funded/);
  assert.throws(() => validatePlan(prepared, {...current(), ownerAccount: {}}),
    /already funded/);
  assert.throws(() => validatePlan(prepared, {...current(), protocol: {payer: 0, mintSupply: '0'}}),
    /lacks bounded test SOL/);
  assert.equal(approvalValid(prepared, prepared.approval_id, {}), false);
  assert.equal(approvalValid(prepared, '06c7dfa7528460969a5ca1e8bd001f9c9f1f1f0df3d69fe36649e413e0b14ae6',
    {CON36_APPROVED_TEST_ASSET_ID: prepared.approval_id}), false);
  assert.equal(approvalValid(prepared, prepared.approval_id,
    {CON36_APPROVED_TEST_ASSET_ID: prepared.approval_id}), true);
});

test('only the five planned funding, ATA and checked mint instructions are built', () => {
  const prepared = plan(current());
  const ix = instructions(prepared);
  assert.equal(ix.length, 5);
  assert.equal(ix[0].data.readBigUInt64LE(4), 100_000_000n);
  assert.equal(ix[1].data.readBigUInt64LE(4), 100_000_000n);
  assert.equal(ix[2].data.toString('hex'), '01');
  assert.equal(ix[3].data.toString('hex'), '01');
  assert.equal(ix[4].programId.toBase58(), prepared.token_program);
  assert.equal(ix[4].data[0], 14); // SPL Token MintToChecked
  assert.equal(ix[4].data.readBigUInt64LE(1), 7_100_000n);
  assert.equal(ix[4].data[9], 6);
});
