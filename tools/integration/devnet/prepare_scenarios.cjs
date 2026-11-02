'use strict';

// Deterministic public scenario inventory. This tool never connects to RPC or signs.
const fs = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');
const {createRequire} = require('node:module');
const repo = path.resolve(__dirname, '../../..');
const fromBootstrap = createRequire(path.join(repo, 'tools/bootstrap/package.json'));
const {PublicKey} = fromBootstrap('@solana/web3.js');
const {getAssociatedTokenAddressSync, TOKEN_PROGRAM_ID} = fromBootstrap('@solana/spl-token');
const identities = JSON.parse(fs.readFileSync(path.join(repo, 'evidence/con36/test-identities.json')));
const protocol = JSON.parse(fs.readFileSync(path.join(repo, 'evidence/con36/protocol-config-plan.json')));
const required = (ok, message) => { if (!ok) throw Error(message); };
const sha = x => crypto.createHash('sha256').update(x).digest();
const program = new PublicKey(protocol.program_id);
const config = new PublicKey(protocol.protocol_config_pda);
const mint = new PublicKey(protocol.test_mint_pubkey);
const creator = new PublicKey(identities.roles.creator);
const owner = new PublicKey(identities.roles.agent_owner);
const creatorAta = getAssociatedTokenAddressSync(mint, creator, false, TOKEN_PROGRAM_ID);
const ownerAta = getAssociatedTokenAddressSync(mint, owner, false, TOKEN_PROGRAM_ID);
const pda = seeds => PublicKey.findProgramAddressSync(seeds, program)[0].toBase58();

function make() {
  required(identities.genesis_hash === protocol.genesis_hash &&
    identities.program_id === protocol.program_id &&
    identities.mint_pubkey === protocol.test_mint_pubkey,
    'Test identities differ from approved Devnet plan');
  const specs = [
    {name: 'E2E-01-full', model: 'Fixed', bps: 10000, operator: 1000000},
    {name: 'E2E-02-zero', model: 'Fixed', bps: 6000, operator: 0},
    {name: 'E2E-03-proportional', model: 'Proportional', bps: 6000, operator: 600000, surplus: 100000},
    {name: 'E2E-04-invalid-shared', model: 'Proportional', bps: 6000, operator: 600000,
      negative: 'SettlementInvalidCreatorRefund'},
    {name: 'E2E-05-valid-shared', model: 'Proportional', bps: 6000, operator: 600000, shared: true},
    {name: 'E2E-06-invalid-mint', model: 'Fixed', bps: 10000, operator: 1000000,
      negative: 'WrongMintOnFund'},
    {name: 'E2E-07-wrong-beneficiary', model: 'Fixed', bps: 10000, operator: 1000000,
      negative: 'SettlementInvalidBeneficiary'},
  ];
  const scenarios = specs.map(spec => {
    const orderId = sha(`CON36:${protocol.genesis_hash}:${protocol.approved_con35_deployment_id}:${spec.name}`);
    const agentId = sha(`CON36:agent:${protocol.genesis_hash}:${spec.name}`);
    const order = pda([Buffer.from('work_order'), config.toBuffer(), creator.toBuffer(), orderId]);
    const vault = pda([Buffer.from('escrow'), new PublicKey(order).toBuffer()]);
    const agent = pda([Buffer.from('agent'), config.toBuffer(), agentId]);
    const beneficiary = spec.shared ? creator : owner;
    const operatorAta = spec.shared ? creatorAta : ownerAta;
    return {scenario: spec.name, work_order_id_hex: orderId.toString('hex'),
      agent_id_hex: agentId.toString('hex'), work_order_pda: order, escrow_vault: vault,
      agent_account_pda: agent, creator_pubkey: creator.toBase58(),
      agent_owner_pubkey: beneficiary.toBase58(),
      device_pubkey: spec.shared ? identities.roles.shared_device : identities.roles.device,
      verifier_pubkey: identities.roles.verifier,
      creator_source_and_refund_ata: creatorAta.toBase58(),
      operator_payout_ata: operatorAta.toBase58(),
      token_mint: mint.toBase58(), token_program: TOKEN_PROGRAM_ID.toBase58(),
      payment_model: spec.model, completion_bps: spec.bps,
      escrow_funding_base_units: 1000000, donated_surplus_base_units: spec.surplus || 0,
      operator_payout_base_units: spec.operator,
      creator_refund_base_units: 1000000 - spec.operator + (spec.surplus || 0),
      negative_attempt: spec.negative || null,
      final_settlement_after_negative: !!spec.negative,
      same_operator_and_refund_destination: !!spec.shared};
  });
  const output = {
    schema_version: 1, status: 'PREPARED_NOT_AUTHORIZED',
    network: 'solana:devnet', genesis_hash: protocol.genesis_hash,
    program_id: protocol.program_id, protocol_config_pda: config.toBase58(),
    mint_pubkey: mint.toBase58(), mint_decimals: 6,
    total_funding_base_units: 7000000, total_surplus_base_units: 100000,
    required_mint_supply_base_units: 7100000,
    E2E_08_duplicate_settlement_target: scenarios[0].work_order_pda,
    scenarios,
    transactions_submitted: false,
  };
  required(scenarios.reduce((sum, item) => sum + item.escrow_funding_base_units +
    item.donated_surplus_base_units, 0) === output.required_mint_supply_base_units,
    'Mint supply accounting mismatch');
  for (const scenario of scenarios) required(scenario.operator_payout_base_units +
    scenario.creator_refund_base_units === scenario.escrow_funding_base_units +
    scenario.donated_surplus_base_units, 'Settlement conservation mismatch');
  return output;
}

function main() {
  const output = make();
  const file = path.join(repo, 'evidence/con36/scenario-plan.json');
  const bytes = JSON.stringify(output, null, 2) + '\n';
  if (fs.existsSync(file)) required(fs.readFileSync(file, 'utf8') === bytes,
    'Scenario plan already exists with different identities');
  else fs.writeFileSync(file, bytes, {flag: 'wx', mode: 0o644});
  console.log(JSON.stringify({file, scenarios: output.scenarios.length,
    required_mint_supply_base_units: output.required_mint_supply_base_units,
    transactions_submitted: false}));
}

if (require.main === module) {
  try { main(); } catch (error) { console.error(error.message); process.exitCode = 1; }
}
module.exports = {make};
