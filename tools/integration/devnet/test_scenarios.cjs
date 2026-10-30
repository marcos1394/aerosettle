'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const {make} = require('./prepare_scenarios.cjs');

test('seven isolated WorkOrders cover the eight scenario outcomes', () => {
  const plan = make();
  assert.equal(plan.status, 'PREPARED_NOT_AUTHORIZED');
  assert.equal(plan.scenarios.length, 7);
  assert.equal(new Set(plan.scenarios.map(x => x.work_order_pda)).size, 7);
  assert.equal(new Set(plan.scenarios.map(x => x.escrow_vault)).size, 7);
  assert.equal(new Set(plan.scenarios.map(x => x.agent_account_pda)).size, 7);
  assert.equal(plan.E2E_08_duplicate_settlement_target, plan.scenarios[0].work_order_pda);
  assert.equal(plan.required_mint_supply_base_units, 7_100_000);
  assert.equal(plan.transactions_submitted, false);
});

test('payout, refunds, donated surplus and shared destinations conserve value', () => {
  const plan = make();
  const byName = Object.fromEntries(plan.scenarios.map(x => [x.scenario, x]));
  assert.equal(byName['E2E-01-full'].operator_payout_base_units, 1_000_000);
  assert.equal(byName['E2E-02-zero'].operator_payout_base_units, 0);
  assert.equal(byName['E2E-03-proportional'].operator_payout_base_units, 600_000);
  assert.equal(byName['E2E-03-proportional'].creator_refund_base_units, 500_000);
  assert.equal(byName['E2E-04-invalid-shared'].negative_attempt,
    'SettlementInvalidCreatorRefund');
  assert.equal(byName['E2E-05-valid-shared'].operator_payout_ata,
    byName['E2E-05-valid-shared'].creator_source_and_refund_ata);
  assert.equal(byName['E2E-07-wrong-beneficiary'].negative_attempt,
    'SettlementInvalidBeneficiary');
  for (const item of plan.scenarios) {
    assert.equal(item.operator_payout_base_units + item.creator_refund_base_units,
      item.escrow_funding_base_units + item.donated_surplus_base_units);
    assert.equal(item.token_mint, plan.mint_pubkey);
  }
});
