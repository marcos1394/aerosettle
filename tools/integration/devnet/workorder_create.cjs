'use strict';

// First CON-36 WorkOrder stage. Submission requires a separate exact approval;
// inspection, preparation, simulation and verification never submit transactions.
const fs = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');
const {createRequire} = require('node:module');
const repo = path.resolve(__dirname, '../../..');
const fromBootstrap = createRequire(path.join(repo, 'tools/bootstrap/package.json'));
const {Connection, PublicKey, SystemProgram, Transaction, VersionedTransaction,
  SYSVAR_CLOCK_PUBKEY, sendAndConfirmTransaction} = fromBootstrap('@solana/web3.js');
const bs58 = fromBootstrap('bs58');
const {getAccount, TOKEN_PROGRAM_ID} = fromBootstrap('@solana/spl-token');
const {instruction, programId} = require('./abi.cjs');
const {inspect: inspectDeployment} = require('./protocol_config.cjs');
const {identicalProtectedCopies} = require('./prepare_wallets.cjs');

const RPC = 'https://api.devnet.solana.com';
const GENESIS = 'EtWTRABZaYq6iMfeYKouRu166VU2xqa1wcaWoxPkrZBG';
const MAX_FEE = 10_000;
const WORK_ORDER_SPACE = 585;
const SCENARIO = 'E2E-01-full';
const SECONDS_DAY = 86_400;
const sha = x => crypto.createHash('sha256').update(x).digest();
const canonical = x => JSON.stringify(x, Object.keys(x).sort());
const required = (ok, message) => { if (!ok) throw Error(message); };
const scenarioPlan = JSON.parse(fs.readFileSync(path.join(repo,
  'evidence/con36/scenario-plan.json')));
const identities = JSON.parse(fs.readFileSync(path.join(repo,
  'evidence/con36/test-identities.json')));
const scenario = scenarioPlan.scenarios.find(x => x.scenario === SCENARIO);
const connection = new Connection(RPC, 'finalized');

function expectedBody(preparedAt, rent) {
  required(scenario && scenario.payment_model === 'Fixed' &&
    scenario.escrow_funding_base_units === 1_000_000 &&
    scenario.operator_payout_base_units === 1_000_000,
    'E2E-01 scenario plan mismatch');
  required(scenarioPlan.genesis_hash === GENESIS &&
    scenarioPlan.program_id === programId.toBase58() &&
    identities.roles.creator === scenario.creator_pubkey &&
    identities.roles.verifier === scenario.verifier_pubkey,
    'Approved Devnet identity mismatch');
  const manifest = sha(`CON36:WORK_MANIFEST:${SCENARIO}:V1`).toString('hex');
  return {schema_version: 1, status: 'PREPARED_NOT_AUTHORIZED',
    environment: 'devnet', network: 'solana:devnet', rpc_url: RPC,
    genesis_hash: GENESIS, program_id: programId.toBase58(),
    protocol_config_pda: scenarioPlan.protocol_config_pda,
    test_mint_pubkey: scenario.token_mint, token_program: TOKEN_PROGRAM_ID.toBase58(),
    scenario: SCENARIO, work_order_pda: scenario.work_order_pda,
    work_order_id_hex: scenario.work_order_id_hex,
    creator_pubkey: scenario.creator_pubkey,
    verifier_pubkey: scenario.verifier_pubkey,
    creator_source_ata: scenario.creator_source_and_refund_ata,
    payment_model: scenario.payment_model,
    total_amount_base_units: scenario.escrow_funding_base_units,
    work_type: 'Inspection', required_capabilities: 33,
    evidence_requirements: 71, manifest_hash_hex: manifest,
    prepared_at_unix: preparedAt,
    execution_deadline_unix: preparedAt + 14 * SECONDS_DAY,
    verification_deadline_unix: preparedAt + 15 * SECONDS_DAY,
    work_order_rent_lamports: rent,
    max_fee_lamports: MAX_FEE,
    max_creator_debit_lamports: rent + MAX_FEE,
    expected_initial_status: 'Draft',
    transaction_submitted: false};
}

function makePlan(preparedAt, rent) {
  const body = expectedBody(preparedAt, rent);
  return {...body, approval_id: sha(canonical(body)).toString('hex')};
}

function validatePlan(plan, observed) {
  required(Number.isSafeInteger(plan.prepared_at_unix) &&
    Number.isSafeInteger(plan.work_order_rent_lamports) &&
    canonical(plan) === canonical(makePlan(plan.prepared_at_unix,
      plan.work_order_rent_lamports)),
  'WorkOrder creation manifest integrity mismatch');
  required(observed.genesis === GENESIS && !observed.order &&
    observed.protocol && observed.protocol.owner.toBase58() === programId.toBase58(),
  'Devnet identity or WorkOrder account state mismatch');
  const raw = observed.protocol.data;
  required(raw.length === 155 && raw[8] === 1 && raw[146] === 0 &&
    new PublicKey(raw.subarray(9, 41)).toBase58() ===
      '27cyzd58RswQRbSuR3cKh4xv2gWgZ7awb3tUtoT7hYLB' &&
    raw.subarray(41, 73).toString('hex') ===
      'ce59db5080fc2c6d3bcf7ca90712d3c2e5e6c28f27f0dfbb9953bdb0894c03ab' &&
    raw.subarray(105, 137).toString('hex') ===
      '06c7dfa7528460969a5ca1e8bd001f9c9f1f1f0df3d69fe36649e413e0b14ae6',
  'ProtocolConfig identity, authority or active status changed');
  required(observed.rent === plan.work_order_rent_lamports &&
    observed.now > plan.prepared_at_unix - 300 &&
    observed.now < plan.execution_deadline_unix - 3600,
  'WorkOrder rent or deadline no longer valid');
  required(observed.creatorBalance >= plan.max_creator_debit_lamports &&
    observed.sourceAmount >= BigInt(plan.total_amount_base_units),
  'Creator lacks bounded SOL or approved test tokens');
}

async function inspect() {
  const deployment = await inspectDeployment();
  const genesis = await connection.getGenesisHash();
  const protocol = await connection.getAccountInfo(
    new PublicKey(scenarioPlan.protocol_config_pda), 'finalized');
  const order = await connection.getAccountInfo(
    new PublicKey(scenario.work_order_pda), 'finalized');
  const clock = await connection.getAccountInfo(SYSVAR_CLOCK_PUBKEY, 'finalized');
  required(clock?.data.length >= 40, 'Devnet Clock sysvar missing');
  const now = Number(clock.data.readBigInt64LE(32));
  const rent = await connection.getMinimumBalanceForRentExemption(WORK_ORDER_SPACE, 'finalized');
  const creatorBalance = await connection.getBalance(new PublicKey(scenario.creator_pubkey), 'finalized');
  const source = await getAccount(connection,
    new PublicKey(scenario.creator_source_and_refund_ata), 'finalized', TOKEN_PROGRAM_ID);
  required(source.owner.toBase58() === scenario.creator_pubkey &&
    source.mint.toBase58() === scenario.token_mint,
    'Creator test token account identity mismatch');
  return {deployment, genesis, protocol, order, now, rent, creatorBalance,
    sourceAmount: source.amount};
}

function createInstruction(plan) {
  return instruction('create_work_order', {
    protocol_config: plan.protocol_config_pda,
    work_order: plan.work_order_pda,
    creator: plan.creator_pubkey,
    system_program: SystemProgram.programId,
  }, {args: {
    work_order_id: Buffer.from(plan.work_order_id_hex, 'hex'),
    work_type: plan.work_type,
    required_capabilities: BigInt(plan.required_capabilities),
    evidence_requirements: BigInt(plan.evidence_requirements),
    manifest_hash: Buffer.from(plan.manifest_hash_hex, 'hex'),
    settlement: {token_mint: plan.test_mint_pubkey,
      total_amount: BigInt(plan.total_amount_base_units),
      payment_model: plan.payment_model,
      verifier: plan.verifier_pubkey},
    execution_deadline: BigInt(plan.execution_deadline_unix),
    verification_deadline: BigInt(plan.verification_deadline_unix),
  }});
}

function creatorKeypair() {
  const bindingPath = path.join(repo, 'target/deploy/con36-private/creator.binding.json');
  const binding = JSON.parse(fs.readFileSync(bindingPath));
  required(binding.environment === 'devnet' && binding.genesis_hash === GENESIS &&
    binding.role === 'creator' && binding.pubkey === scenario.creator_pubkey,
    'Protected creator binding mismatch');
  const wallet = identicalProtectedCopies('creator.json');
  required(wallet.publicKey.toBase58() === scenario.creator_pubkey,
    'Protected creator wallet mismatch');
  return wallet;
}

function build(plan, creator, blockhash) {
  required(creator.publicKey.toBase58() === plan.creator_pubkey,
    'WorkOrder creator signer mismatch');
  const tx = new Transaction({feePayer: creator.publicKey, recentBlockhash: blockhash});
  tx.add(createInstruction(plan));
  tx.sign(creator);
  return tx;
}

async function simulate(plan, observed) {
  validatePlan(plan, observed);
  const creator = creatorKeypair();
  const {blockhash} = await connection.getLatestBlockhash('finalized');
  const tx = build(plan, creator, blockhash);
  const fee = await connection.getFeeForMessage(tx.compileMessage(), 'finalized');
  required(Number.isSafeInteger(fee.value) && fee.value <= plan.max_fee_lamports,
    'WorkOrder creation fee exceeds approved maximum');
  const signed = new VersionedTransaction(tx.compileMessage());
  signed.sign([creator]);
  const result = await connection.simulateTransaction(signed,
    {sigVerify: true, commitment: 'finalized'});
  required(!result.value.err,
    `WorkOrder creation simulation failed: ${JSON.stringify(result.value.err)} ${JSON.stringify(result.value.logs)}`);
  return {approval_id: plan.approval_id, simulated: true, submitted: false,
    scenario: plan.scenario, work_order_pda: plan.work_order_pda,
    fee_quote_lamports: fee.value, rent_lamports: observed.rent,
    max_creator_debit_lamports: plan.max_creator_debit_lamports,
    units_consumed: result.value.unitsConsumed};
}

async function verify(plan, observed, signature) {
  required(canonical(plan) === canonical(makePlan(plan.prepared_at_unix,
    plan.work_order_rent_lamports)), 'WorkOrder approval manifest integrity mismatch');
  required(/^[1-9A-HJ-NP-Za-km-z]{80,90}$/.test(signature), 'Invalid signature');
  required(observed.genesis === GENESIS, 'Devnet genesis mismatch');
  const status = (await connection.getSignatureStatuses([signature],
    {searchTransactionHistory: true})).value[0];
  required(status?.confirmationStatus === 'finalized' && status.err === null,
    'WorkOrder creation transaction is not finalized');
  const tx = await connection.getTransaction(signature,
    {commitment: 'finalized', maxSupportedTransactionVersion: 0});
  required(tx && tx.slot === status.slot && tx.meta?.err === null &&
    tx.transaction.signatures[0] === signature &&
    tx.meta.fee <= plan.max_fee_lamports &&
    tx.transaction.message.instructions.length === 1,
    'WorkOrder creation transaction evidence mismatch');
  const keys = tx.transaction.message.accountKeys.map(x => x.toBase58());
  const actual = tx.transaction.message.instructions[0];
  const expected = createInstruction(plan);
  required(keys[0] === plan.creator_pubkey &&
    keys[actual.programIdIndex] === expected.programId.toBase58() &&
    actual.accounts.map(index => keys[index]).join(',') ===
      expected.keys.map(x => x.pubkey.toBase58()).join(',') &&
    Buffer.from(bs58.decode(actual.data)).equals(expected.data),
  'Finalized WorkOrder creation differs from approved accounts or payload');
  const creatorIndex = keys.indexOf(plan.creator_pubkey);
  const orderIndex = keys.indexOf(plan.work_order_pda);
  required(creatorIndex >= 0 && orderIndex >= 0 &&
    tx.meta.preBalances[creatorIndex] - tx.meta.postBalances[creatorIndex] ===
      plan.work_order_rent_lamports + tx.meta.fee &&
    tx.meta.preBalances[orderIndex] === 0 &&
    tx.meta.postBalances[orderIndex] === plan.work_order_rent_lamports,
  'Finalized WorkOrder SOL balances differ from approved plan');
  const account = observed.order;
  required(account?.owner.toBase58() === plan.program_id &&
    account.data.length === WORK_ORDER_SPACE &&
    account.data.subarray(0, 8).equals(sha('account:WorkOrderAccount').subarray(0, 8)),
  'WorkOrder PDA missing or wrong owner/layout');
  const data = account.data;
  required(data[8] === 1 &&
    new PublicKey(data.subarray(9, 41)).toBase58() === plan.protocol_config_pda &&
    data.subarray(41, 73).toString('hex') === plan.work_order_id_hex &&
    new PublicKey(data.subarray(73, 105)).toBase58() === plan.creator_pubkey &&
    data[105] === 0 && data.readBigUInt64LE(106) === BigInt(plan.required_capabilities) &&
    data.readBigUInt64LE(114) === BigInt(plan.evidence_requirements) &&
    data.subarray(122, 154).toString('hex') === plan.manifest_hash_hex &&
    new PublicKey(data.subarray(154, 186)).toBase58() === plan.test_mint_pubkey &&
    data.readBigUInt64LE(186) === BigInt(plan.total_amount_base_units) &&
    data[194] === 0 &&
    new PublicKey(data.subarray(195, 227)).toBase58() === plan.verifier_pubkey &&
    data.readBigInt64LE(291) === BigInt(plan.execution_deadline_unix) &&
    data.readBigInt64LE(299) === BigInt(plan.verification_deadline_unix),
  'On-chain WorkOrder immutable terms differ from approved plan');
  return {approval_id: plan.approval_id, signature, slot: tx.slot,
    fee_lamports: tx.meta.fee,
    creator_debit_lamports: plan.work_order_rent_lamports + tx.meta.fee,
    work_order_pda: plan.work_order_pda,
    current_status_index: data[307],
    amount_base_units: plan.total_amount_base_units,
    mint_pubkey: plan.test_mint_pubkey,
    genesis_hash: GENESIS, verification_status: 'VERIFIED'};
}

async function main() {
  const action = process.argv[2] || 'inspect';
  const file = process.argv[3] || path.join(repo,
    'evidence/con36/e2e-01-create-plan.json');
  required(['inspect', 'prepare', 'simulate', 'submit', 'verify'].includes(action),
    'Usage: node workorder_create.cjs inspect|prepare|simulate|submit|verify [plan] [approval-or-signature]');
  const observed = await inspect();
  if (action === 'inspect') {
    console.log(JSON.stringify({network: 'solana:devnet', genesis_hash: observed.genesis,
      protocol_config_present: !!observed.protocol,
      work_order_pda: scenario.work_order_pda,
      work_order_present: !!observed.order,
      creator_lamports: observed.creatorBalance,
      creator_source_base_units: observed.sourceAmount.toString(),
      work_order_rent_lamports: observed.rent,
      chain_unix_time: observed.now}, null, 2));
    return;
  }
  if (action === 'prepare') {
    const plan = makePlan(observed.now, observed.rent);
    validatePlan(plan, observed);
    const bytes = JSON.stringify(plan, null, 2) + '\n';
    if (fs.existsSync(file)) required(fs.readFileSync(file, 'utf8') === bytes,
      'Existing WorkOrder creation manifest differs');
    else fs.writeFileSync(file, bytes, {flag: 'wx', mode: 0o644});
    console.log(JSON.stringify({path: file, approval_id: plan.approval_id,
      transaction_submitted: false}, null, 2));
    return;
  }
  const plan = JSON.parse(fs.readFileSync(file));
  if (action === 'verify') {
    console.log(JSON.stringify(await verify(plan, observed, process.argv[4] || ''), null, 2));
    return;
  }
  validatePlan(plan, observed);
  if (action === 'simulate') {
    console.log(JSON.stringify(await simulate(plan, observed), null, 2));
    return;
  }
  required(process.argv[4] === plan.approval_id &&
    process.env.CON36_APPROVED_WORKORDER_CREATE_ID === plan.approval_id,
  'Exact separate WorkOrder creation approval required');
  await simulate(plan, observed);
  const creator = creatorKeypair();
  const {blockhash} = await connection.getLatestBlockhash('finalized');
  const signature = await sendAndConfirmTransaction(connection,
    build(plan, creator, blockhash), [creator], {commitment: 'finalized'});
  console.log(JSON.stringify({approval_id: plan.approval_id, signature,
    status: 'SUBMITTED; verify finalized WorkOrder account before further transactions'}, null, 2));
}

if (require.main === module) main().catch(error => {
  console.error(error.message);
  process.exitCode = 1;
});
module.exports = {makePlan, validatePlan, createInstruction};
