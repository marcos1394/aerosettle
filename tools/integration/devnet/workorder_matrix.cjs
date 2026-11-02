'use strict';

// Approval-gated, resumable Devnet transaction runner. Never used by CI to submit.
const fs = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');
const {createRequire} = require('node:module');
const repo = path.resolve(__dirname, '../../..');
const fromBootstrap = createRequire(path.join(repo, 'tools/bootstrap/package.json'));
const {Connection, PublicKey, SystemProgram, Transaction, VersionedTransaction,
  SYSVAR_CLOCK_PUBKEY} =
  fromBootstrap('@solana/web3.js');
const {getAccount, createTransferCheckedInstruction, TOKEN_PROGRAM_ID, NATIVE_MINT} =
  fromBootstrap('@solana/spl-token');
const bs58 = fromBootstrap('bs58');
const {programId, instruction} = require('./abi.cjs');
const {identicalProtectedCopies} = require('./prepare_wallets.cjs');
const scenarioPlan = JSON.parse(fs.readFileSync(path.join(repo, 'evidence/con36/scenario-plan.json')));
const firstCreation = JSON.parse(fs.readFileSync(path.join(repo, 'evidence/con36/e2e-01-create-plan.json')));
const rpc = new Connection('https://api.devnet.solana.com', 'finalized');
const GENESIS = 'EtWTRABZaYq6iMfeYKouRu166VU2xqa1wcaWoxPkrZBG';
const MINT = 'HpfaV9oRuTN1b3ktDKvJoWqUWFZ1o9VFmhejxxqQ1vyh';
const CONFIG = 'C8HiYzxKjRcDFHoWSZ84smUsxnMQ7ipxPnQ96GK5qZVn';
const MAX_FEE = 20_000;
const sha = x => crypto.createHash('sha256').update(x).digest();
const required = (condition, message) => { if (!condition) throw Error(message); };
const pub = x => new PublicKey(x);
const reportDir = path.join(repo, 'evidence/con36/matrix');
const plansDir = path.join(reportDir, 'plans');
const phases = ['create', 'wrong_mint', 'fund', 'donate', 'register', 'claim',
  'submit', 'verify', 'invalid_shared', 'wrong_beneficiary', 'settle', 'duplicate'];
const expectedStatus = {create: null, wrong_mint: 0, fund: 0, donate: 1,
  register: 1, claim: 1, submit: 2, verify: 3,
  invalid_shared: 4, wrong_beneficiary: 4, settle: 4, duplicate: 5};
const afterStatus = {create: 0, wrong_mint: 0, fund: 1, donate: 1,
  register: 1, claim: 2, submit: 3, verify: 4,
  invalid_shared: 4, wrong_beneficiary: 4, settle: 5, duplicate: 5};

function key(role, expected) {
  const binding = JSON.parse(fs.readFileSync(path.join(repo,
    `target/deploy/con36-private/${role}.binding.json`)));
  required(binding.environment === 'devnet' && binding.genesis_hash === GENESIS &&
    binding.role === role && binding.pubkey === expected,
  `Protected ${role} binding mismatch`);
  const wallet = identicalProtectedCopies(`${role}.json`);
  required(wallet.publicKey.toBase58() === expected, `${role} wallet mismatch`);
  return wallet;
}

function spec(name) {
  const result = scenarioPlan.scenarios.find(x => x.scenario === name);
  required(result && scenarioPlan.genesis_hash === GENESIS &&
    scenarioPlan.program_id === programId.toBase58() &&
    scenarioPlan.mint_pubkey === MINT &&
    scenarioPlan.protocol_config_pda === CONFIG &&
    result.token_mint === MINT && result.token_program === TOKEN_PROGRAM_ID.toBase58(),
  'Devnet scenario identity mismatch');
  return result;
}

function steps(s) {
  const list = [];
  if (s.scenario !== 'E2E-01-full') list.push('create');
  if (s.negative_attempt === 'WrongMintOnFund') list.push('wrong_mint');
  list.push('fund');
  if (s.donated_surplus_base_units) list.push('donate');
  list.push('register', 'claim', 'submit', 'verify');
  if (s.negative_attempt === 'SettlementInvalidCreatorRefund') list.push('invalid_shared');
  if (s.negative_attempt === 'SettlementInvalidBeneficiary') list.push('wrong_beneficiary');
  list.push('settle');
  if (s.scenario === 'E2E-01-full') list.push('duplicate');
  return list;
}

function reportPath(s) { return path.join(reportDir, `${s.scenario}.json`); }
function readReport(s) {
  const file = reportPath(s);
  return fs.existsSync(file) ? JSON.parse(fs.readFileSync(file)) :
    {schema_version: 1, network: 'solana:devnet', genesis_hash: GENESIS,
      program_id: programId.toBase58(), scenario: s.scenario,
      work_order_pda: s.work_order_pda, token_mint: MINT, events: []};
}
function saveReport(s, report) {
  fs.mkdirSync(reportDir, {recursive: true});
  const temp = `${reportPath(s)}.tmp`;
  fs.writeFileSync(temp, JSON.stringify(report, null, 2) + '\n', {mode: 0o644});
  fs.renameSync(temp, reportPath(s));
}

async function chain() {
  const genesis = await rpc.getGenesisHash();
  required(genesis === GENESIS, 'Devnet genesis changed');
  const program = await rpc.getAccountInfo(programId, 'finalized');
  required(program?.executable, 'Approved program missing');
  const mint = await rpc.getParsedAccountInfo(pub(MINT), 'finalized');
  required(mint.value?.owner.equals(TOKEN_PROGRAM_ID) &&
    mint.value.data.parsed?.info?.decimals === 6 &&
    mint.value.data.parsed.info.mintAuthority ===
      '4om6LcFXaZ2Wtbn3P2ZvvyqssXFQs1xjNmE2Fnj7mRHa',
  'Approved test mint changed');
  const config = await rpc.getAccountInfo(pub(CONFIG), 'finalized');
  required(config?.owner.equals(programId) && config.data.length === 155 &&
    config.data[146] === 0 &&
    config.data.subarray(41, 73).equals(pub(GENESIS).toBuffer()),
  'Approved ProtocolConfig missing, paused or wrong network');
  const clock = await rpc.getAccountInfo(SYSVAR_CLOCK_PUBKEY, 'finalized');
  required(clock?.data.length >= 40, 'Devnet Clock missing');
  return Number(clock.data.readBigInt64LE(32));
}

async function order(s) {
  const account = await rpc.getAccountInfo(pub(s.work_order_pda), 'finalized');
  if (!account) return null;
  required(account.owner.equals(programId) && account.data.length === 585 &&
    account.data.subarray(0, 8).equals(sha('account:WorkOrderAccount').subarray(0, 8)),
  'WorkOrder account owner or layout mismatch');
  const d = account.data;
  required(new PublicKey(d.subarray(9, 41)).toBase58() === CONFIG &&
    d.subarray(41, 73).toString('hex') === s.work_order_id_hex &&
    new PublicKey(d.subarray(73, 105)).toBase58() === s.creator_pubkey &&
    new PublicKey(d.subarray(154, 186)).toBase58() === MINT &&
    d.readBigUInt64LE(186) === BigInt(s.escrow_funding_base_units) &&
    new PublicKey(d.subarray(195, 227)).toBase58() === s.verifier_pubkey,
  'WorkOrder immutable identity or terms mismatch');
  // Borsh Option<VerificationStatus> occupies one byte for None and two for
  // Some; the allocated account space reserves the maximum, not a fixed body.
  required(d[532] === 0 || d[532] === 1,
    'Unexpected WorkOrder verification option layout');
  const completionOffset = d[532] === 0 ? 533 : 534;
  return {status: d[307], claimedAgent: new PublicKey(d.subarray(308, 340)).toBase58(),
    beneficiary: new PublicKey(d.subarray(340, 372)).toBase58(),
    receiptHash: d.subarray(372, 404), evidenceHash: d.subarray(404, 436),
    completionBps: d.readUInt16LE(completionOffset),
    claimedAt: Number(d.readBigInt64LE(completionOffset + 2 + 8 + 8)),
    vault: new PublicKey(d.subarray(227, 259)).toBase58(),
    tokenProgram: new PublicKey(d.subarray(259, 291)).toBase58()};
}

async function token(address) {
  const t = await getAccount(rpc, pub(address), 'finalized', TOKEN_PROGRAM_ID);
  required(t.mint.toBase58() === MINT, 'Token account mint mismatch');
  return {owner: t.owner.toBase58(), amount: t.amount};
}

function attestationHash(s, receipt, manifest, bps, time) {
  const amount = Buffer.alloc(2); amount.writeUInt16LE(bps);
  const at = Buffer.alloc(8); at.writeBigInt64LE(BigInt(time));
  return sha(Buffer.concat([Buffer.from('AEROSETTLE:VERIFICATION_ATTESTATION:V1\0'),
    Buffer.from([1]), Buffer.from(s.work_order_id_hex, 'hex'), receipt, manifest,
    pub(s.verifier_pubkey).toBuffer(), Buffer.from([0]), amount, at]));
}

function transactionInstruction(s, phase, now, o) {
  const base = {protocol_config: CONFIG, work_order: s.work_order_pda};
  const creator = s.creator_pubkey;
  const owner = s.agent_owner_pubkey;
  const device = s.device_pubkey;
  const baseHash = Buffer.from(s.work_order_id_hex, 'hex');
  if (phase === 'create') return instruction('create_work_order',
    {...base, creator, system_program: SystemProgram.programId},
    {args: {work_order_id: baseHash, work_type: 'Inspection',
      required_capabilities: 33n, evidence_requirements: 71n,
      manifest_hash: sha(`CON36:WORK_MANIFEST:${s.scenario}:V1`),
      settlement: {token_mint: MINT, total_amount: 1_000_000n,
        payment_model: s.payment_model, verifier: s.verifier_pubkey},
      execution_deadline: BigInt(firstCreation.execution_deadline_unix),
      verification_deadline: BigInt(firstCreation.verification_deadline_unix)}});
  if (phase === 'fund' || phase === 'wrong_mint') return instruction('fund_work_order',
    {...base, creator, mint: phase === 'wrong_mint' ? NATIVE_MINT : MINT,
      creator_token_account: s.creator_source_and_refund_ata,
      escrow_vault: s.escrow_vault, token_program: TOKEN_PROGRAM_ID,
      system_program: SystemProgram.programId});
  if (phase === 'donate') return createTransferCheckedInstruction(
    pub(s.creator_source_and_refund_ata), pub(MINT), pub(s.escrow_vault),
    pub(creator), s.donated_surplus_base_units, 6);
  if (phase === 'register') return instruction('register_agent',
    {protocol_config: CONFIG, agent_account: s.agent_account_pda,
      owner, system_program: SystemProgram.programId},
    {agent_id: Buffer.from(s.agent_id_hex, 'hex'), signing_authority: device,
      agent_type: 'Drone', capabilities: 33n | (1n << 15n),
      metadata_hash: sha(`CON36:AGENT_METADATA:${s.scenario}:V1`)});
  if (phase === 'claim') return instruction('claim_work_order',
    {...base, agent_account: s.agent_account_pda, agent_signer: device});
  if (phase === 'submit') {
    required(o?.claimedAt > 0 && o.claimedAt <= now,
      'Claim timestamp unavailable for execution');
    return instruction('submit_execution',
      {...base, agent_account: s.agent_account_pda, agent_signer: device},
      {args: {execution_receipt_hash: sha(`CON36:RECEIPT:${s.scenario}:V1`),
        evidence_manifest_hash: sha(`CON36:EVIDENCE:${s.scenario}:V1`),
        provided_evidence: 71n, execution_started_at: BigInt(o.claimedAt),
        execution_ended_at: BigInt(o.claimedAt), signature_sequence: 0n}});
  }
  if (phase === 'verify') return instruction('verify_execution',
    {...base, verifier: s.verifier_pubkey},
    {args: {verification_attestation_hash: attestationHash(s,
      o.receiptHash, o.evidenceHash, s.completion_bps, now),
      status: 'Accepted', completion_bps: s.completion_bps,
      verified_at: BigInt(now)}});
  if (['settle', 'invalid_shared', 'wrong_beneficiary', 'duplicate'].includes(phase)) {
    const operator = phase === 'wrong_beneficiary' ?
      s.creator_source_and_refund_ata : s.operator_payout_ata;
    const refund = phase === 'invalid_shared' ?
      s.operator_payout_ata : s.creator_source_and_refund_ata;
    return instruction('settle_work_order', {...base, escrow_vault: s.escrow_vault,
      mint: MINT, operator_token_account: operator,
      creator_refund_token_account: refund, token_program: TOKEN_PROGRAM_ID});
  }
  throw Error(`Unknown phase ${phase}`);
}

function phaseSigners(s, phase) {
  if (phase === 'register') return [s.agent_owner_pubkey === s.creator_pubkey ?
    key('creator', s.creator_pubkey) : key('agent_owner', s.agent_owner_pubkey)];
  if (phase === 'claim' || phase === 'submit') return [key(
    s.scenario === 'E2E-05-valid-shared' ? 'shared_device' : 'device', s.device_pubkey)];
  if (phase === 'verify') return [key('verifier', s.verifier_pubkey)];
  return [];
}

function feePayer(s, phase) {
  return phase === 'register' ? phaseSigners(s, phase)[0] : key('creator', s.creator_pubkey);
}

async function rentCap(phase) {
  if (phase === 'create') return rpc.getMinimumBalanceForRentExemption(585, 'finalized');
  if (phase === 'fund') return rpc.getMinimumBalanceForRentExemption(165, 'finalized');
  if (phase === 'register') return rpc.getMinimumBalanceForRentExemption(196, 'finalized');
  return 0;
}

function manifest(s, phase, ix, payer, rent) {
  const body = {schema_version: 1, network: 'solana:devnet', genesis_hash: GENESIS,
    program_id: programId.toBase58(), test_mint: MINT, scenario: s.scenario,
    phase, work_order_pda: s.work_order_pda, agent_account_pda: s.agent_account_pda,
    escrow_vault: s.escrow_vault, creator: s.creator_pubkey,
    beneficiary: s.agent_owner_pubkey, payment_model: s.payment_model,
    completion_bps: s.completion_bps,
    amount_base_units: s.escrow_funding_base_units,
    donated_surplus_base_units: s.donated_surplus_base_units,
    expected_operator_payout_base_units: s.operator_payout_base_units,
    expected_creator_refund_base_units: s.creator_refund_base_units,
    payer: payer.publicKey.toBase58(),
    instruction_program: ix.programId.toBase58(),
    instruction_accounts: ix.keys.map(k => ({pubkey: k.pubkey.toBase58(),
      is_signer: k.isSigner, is_writable: k.isWritable})),
    instruction_data_hex: ix.data.toString('hex'),
    max_fee_lamports: MAX_FEE, max_rent_lamports: rent,
    max_payer_debit_lamports: MAX_FEE + rent,
    expected_pre_status: expectedStatus[phase],
    expected_post_status: afterStatus[phase]};
  return {...body, manifest_id: sha(JSON.stringify(body)).toString('hex')};
}

function saveManifest(m) {
  fs.mkdirSync(plansDir, {recursive: true});
  const file = path.join(plansDir, `${m.scenario}-${m.phase}.json`);
  if (fs.existsSync(file)) {
    const old = JSON.parse(fs.readFileSync(file));
    required(old.manifest_id === m.manifest_id,
      `Existing transaction manifest differs: ${file}`);
  } else fs.writeFileSync(file, JSON.stringify(m, null, 2) + '\n',
    {flag: 'wx', mode: 0o644});
  return file;
}

function expectedFailure(phase) {
  return {wrong_mint: 'InvalidTokenMint', invalid_shared: 'SettlementInvalidCreatorRefund',
    wrong_beneficiary: 'SettlementInvalidBeneficiary',
    duplicate: 'SettlementNotVerified'}[phase] || null;
}

async function finalized(signature) {
  for (let attempt = 0; attempt < 90; attempt++) {
    const status = (await rpc.getSignatureStatuses([signature],
      {searchTransactionHistory: true})).value[0];
    if (status?.confirmationStatus === 'finalized') {
      const tx = await rpc.getTransaction(signature,
        {commitment: 'finalized', maxSupportedTransactionVersion: 0});
      required(tx && tx.slot === status.slot &&
        tx.transaction.signatures[0] === signature,
      'Finalized transaction unavailable or inconsistent');
      return {status, tx};
    }
    await new Promise(resolve => setTimeout(resolve, 1000));
  }
  throw Error(`Transaction not finalized after 90 seconds: ${signature}`);
}

async function executePhase(s, phase, report, submit) {
  required(phases.includes(phase), 'Unknown matrix phase');
  const now = await chain();
  const o = await order(s);
  required(o?.status === expectedStatus[phase] ||
    (phase === 'create' && o === null),
  `${s.scenario}/${phase}: unexpected current WorkOrder status`);
  if (o?.status >= 2) required(o.claimedAgent === s.agent_account_pda &&
    o.beneficiary === s.agent_owner_pubkey,
  'Frozen agent or beneficiary identity mismatch');
  if (phase === 'fund') required(!(await rpc.getAccountInfo(pub(s.escrow_vault), 'finalized')),
    'Escrow vault already exists');
  if (phase === 'register') required(!(await rpc.getAccountInfo(pub(s.agent_account_pda), 'finalized')),
    'Agent account already exists');
  const settlementPhase = ['settle', 'invalid_shared', 'wrong_beneficiary',
    'duplicate'].includes(phase);
  const operatorAddress = phase === 'wrong_beneficiary' ?
    s.creator_source_and_refund_ata : s.operator_payout_ata;
  const refundAddress = phase === 'invalid_shared' ?
    s.operator_payout_ata : s.creator_source_and_refund_ata;
  const beforeTokens = settlementPhase ? {
    vault: await token(s.escrow_vault),
    operator: await token(operatorAddress),
    refund: await token(refundAddress),
  } : null;
  if (settlementPhase && phase === 'settle') required(
    beforeTokens.operator.owner === s.agent_owner_pubkey &&
    beforeTokens.refund.owner === s.creator_pubkey &&
    beforeTokens.vault.owner === s.escrow_vault &&
    beforeTokens.vault.amount === BigInt(s.escrow_funding_base_units +
      s.donated_surplus_base_units),
  'Settlement destination owner or escrow balance mismatch');
  const payer = feePayer(s, phase);
  const signers = [...new Map([payer, ...phaseSigners(s, phase)]
    .map(k => [k.publicKey.toBase58(), k])).values()];
  let argumentTime = now;
  if (phase === 'verify') {
    const previous = path.join(plansDir, `${s.scenario}-${phase}.json`);
    if (fs.existsSync(previous)) {
      const pinned = JSON.parse(fs.readFileSync(previous));
      const payload = Buffer.from(pinned.instruction_data_hex, 'hex');
      argumentTime = Number(payload.readBigInt64LE(payload.length - 8));
      required(Number.isSafeInteger(argumentTime) && argumentTime >= o.claimedAt &&
        argumentTime <= now, 'Pinned verification timestamp invalid');
    }
  }
  const ix = transactionInstruction(s, phase, argumentTime, o);
  const rent = await rentCap(phase);
  required(await rpc.getBalance(payer.publicKey, 'finalized') >= rent + MAX_FEE,
    'Test SOL payer balance below bounded debit');
  const blockhash = (await rpc.getLatestBlockhash('finalized')).blockhash;
  const m = manifest(s, phase, ix, payer, rent);
  const tx = new Transaction({feePayer: payer.publicKey, recentBlockhash: blockhash}).add(ix);
  tx.sign(...signers);
  const fee = (await rpc.getFeeForMessage(tx.compileMessage(), 'finalized')).value;
  required(Number.isSafeInteger(fee) && fee <= MAX_FEE,
    `${phase}: fee quote above cap`);
  const signed = new VersionedTransaction(tx.compileMessage());
  signed.sign(signers);
  const sim = await rpc.simulateTransaction(signed, {sigVerify: true,
    commitment: 'finalized'});
  const failure = expectedFailure(phase);
  const logs = sim.value.logs || [];
  if (failure) required(sim.value.err && logs.join('\n').includes(failure),
    `${phase}: expected ${failure} rejection absent in simulation`);
  else required(!sim.value.err,
    `${phase}: Devnet simulation failed ${JSON.stringify(sim.value.err)} ${logs.join('\n')}`);
  const manifestFile = saveManifest(m);
  const summary = {scenario: s.scenario, phase, manifest_id: m.manifest_id,
    manifest_file: path.relative(repo, manifestFile), expected_failure: failure,
    simulated: true, simulation_units: sim.value.unitsConsumed,
    fee_quote_lamports: fee, max_payer_debit_lamports: m.max_payer_debit_lamports};
  if (!submit) return summary;
  required(process.env.CON36_AUTHORIZED_MATRIX === 'true',
    'User authorization gate for state-changing CON-36 matrix is absent');
  const signature = bs58.encode(tx.signature);
  report.events.push({...summary, signature, state: 'SUBMITTING'});
  saveReport(s, report);
  const sent = await rpc.sendRawTransaction(tx.serialize(), {skipPreflight: true,
    maxRetries: 5});
  required(sent === signature, 'Signed and submitted transaction signatures differ');
  const {status, tx: historical} = await finalized(signature);
  required(historical.meta.fee <= MAX_FEE &&
    (!!historical.meta.err) === !!failure &&
    (!!status.err) === !!failure,
  `${phase}: finalized transaction fee or error differs`);
  if (failure) required(historical.meta.logMessages?.join('\n').includes(failure),
    `${phase}: finalized Anchor rejection differs from ${failure}`);
  const after = await order(s);
  required(after?.status === afterStatus[phase],
    `${phase}: WorkOrder status after finalization differs`);
  if (phase === 'fund') required(after.vault === s.escrow_vault &&
    after.tokenProgram === TOKEN_PROGRAM_ID.toBase58() &&
    (await token(s.escrow_vault)).amount === BigInt(s.escrow_funding_base_units),
  'Funded escrow amount or identity differs');
  if (phase === 'claim') required(after.beneficiary === s.agent_owner_pubkey &&
    after.claimedAgent === s.agent_account_pda,
  'Claim did not freeze approved beneficiary');
  if (phase === 'verify') required(after.completionBps === s.completion_bps,
    'On-chain completion BPS differs');
  if (phase === 'settle') required((await token(s.escrow_vault)).amount === 0n,
    'Settlement did not drain escrow');
  const afterTokens = settlementPhase ? {
    vault: await token(s.escrow_vault),
    operator: await token(operatorAddress),
    refund: await token(refundAddress),
  } : null;
  if (settlementPhase) {
    const sameDestination = operatorAddress === refundAddress;
    const expectedOperatorDelta = failure ? 0n : sameDestination ?
      beforeTokens.vault.amount : BigInt(s.operator_payout_base_units);
    const expectedRefundDelta = failure ? 0n : sameDestination ?
      beforeTokens.vault.amount : BigInt(s.creator_refund_base_units);
    required(afterTokens.operator.amount - beforeTokens.operator.amount ===
      expectedOperatorDelta &&
      afterTokens.refund.amount - beforeTokens.refund.amount ===
      expectedRefundDelta &&
      afterTokens.vault.amount === (failure ? beforeTokens.vault.amount : 0n),
    `${phase}: SPL settlement balances do not conserve approved value`);
  }
  const event = report.events.at(-1);
  Object.assign(event, {state: failure ? 'FINALIZED_REJECTED' : 'FINALIZED',
    slot: historical.slot, fee_lamports: historical.meta.fee,
    transaction_error: historical.meta.err,
    anchor_error_code: failure,
    post_status_index: after.status,
    pre_token_balances: historical.meta.preTokenBalances || [],
    post_token_balances: historical.meta.postTokenBalances || [],
    settlement_balances_before: beforeTokens ? Object.fromEntries(
      Object.entries(beforeTokens).map(([name, value]) =>
        [name, value.amount.toString()])) : null,
    settlement_balances_after: afterTokens ? Object.fromEntries(
      Object.entries(afterTokens).map(([name, value]) =>
        [name, value.amount.toString()])) : null,
    log_messages: historical.meta.logMessages || []});
  saveReport(s, report);
  return event;
}

async function runScenario(s, submit, selectedPhase = null) {
  const report = readReport(s);
  required(report.scenario === s.scenario && report.genesis_hash === GENESIS &&
    report.work_order_pda === s.work_order_pda, 'Scenario report identity mismatch');
  const result = [];
  for (const phase of steps(s)) {
    if (selectedPhase && phase !== selectedPhase) continue;
    const old = report.events.find(x => x.phase === phase);
    if (old) {
      required(old.state === 'FINALIZED' || old.state === 'FINALIZED_REJECTED',
        `${phase}: prior submission uncertain; inspect signature ${old.signature}`);
      result.push({phase, state: old.state, signature: old.signature});
      continue;
    }
    const event = await executePhase(s, phase, report, submit);
    result.push(event);
    console.log(JSON.stringify(event));
    if (!submit || selectedPhase) break;
  }
  return result;
}

async function main() {
  const action = process.argv[2] || 'inspect';
  required(['inspect', 'simulate', 'submit'].includes(action),
    'Usage: node workorder_matrix.cjs inspect|simulate|submit SCENARIO');
  const s = spec(process.argv[3] || 'E2E-01-full');
  const selectedPhase = process.argv[4] || null;
  required(!selectedPhase || steps(s).includes(selectedPhase),
    'Selected phase is not part of this scenario');
  if (action === 'inspect') {
    const now = await chain();
    const o = await order(s);
    console.log(JSON.stringify({scenario: s.scenario, chain_unix_time: now,
      status_index: o?.status ?? null, beneficiary: o?.beneficiary ?? null,
      steps: steps(s), report: readReport(s)}, null, 2));
    return;
  }
  await runScenario(s, action === 'submit', selectedPhase);
}

if (require.main === module) main().catch(error => {
  console.error(error.stack || error.message);
  process.exitCode = 1;
});
module.exports = {spec, steps, transactionInstruction, manifest,
  expectedFailure, attestationHash};
