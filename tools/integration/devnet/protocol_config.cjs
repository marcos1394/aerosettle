'use strict';

// CON-36: exact, approval-gated ProtocolConfig initialization on Solana Devnet.
// prepare and simulate never submit a transaction.
const fs = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');
const {createRequire} = require('node:module');

const repo = path.resolve(__dirname, '../../..');
const fromBootstrap = createRequire(path.join(repo, 'tools/bootstrap/package.json'));
const {Connection, Keypair, PublicKey, SystemProgram, Transaction, TransactionInstruction,
  VersionedTransaction,
  sendAndConfirmTransaction} = fromBootstrap('@solana/web3.js');
const bs58 = fromBootstrap('bs58');

const RPC = 'https://api.devnet.solana.com';
const GENESIS = 'EtWTRABZaYq6iMfeYKouRu166VU2xqa1wcaWoxPkrZBG';
const PROGRAM = 'CeA1P1NSuPLUH31KsT4j3pZeBsknQZ3NSC6GUAqcsCLy';
const MINT = 'HpfaV9oRuTN1b3ktDKvJoWqUWFZ1o9VFmhejxxqQ1vyh';
const ADMIN = '27cyzd58RswQRbSuR3cKh4xv2gWgZ7awb3tUtoT7hYLB';
const PAYER = 'HRwPNBPzArvdCULMH1EFuUpxGw31CbRjyf1cGBz2zE2x';
const FUNDING_LAMPORTS = 3_000_000;
const MAX_FEE_LAMPORTS = 20_000;
const sha = x => crypto.createHash('sha256').update(x).digest();
const canonical = value => JSON.stringify(value, Object.keys(value).sort());
const required = (ok, message) => { if (!ok) throw Error(message); };
const idlPath = path.join(repo, 'evidence/con35/artifacts/aerosettle-idl.json');
const deploymentPath = path.join(repo, 'evidence/con35/devnet-deployment.json');
const binaryPath = path.join(repo, 'evidence/con35/artifacts/aerosettle.so');
const privateDir = path.join(repo, 'target/deploy/con35-private');
const connection = new Connection(RPC, 'finalized');

function approvedEvidence() {
  const deployment = JSON.parse(fs.readFileSync(deploymentPath));
  const idl = JSON.parse(fs.readFileSync(idlPath));
  const idlHash = sha(fs.readFileSync(idlPath)).toString('hex');
  const binaryHash = sha(fs.readFileSync(binaryPath)).toString('hex');
  required(deployment.verification_status === 'VERIFIED' &&
    deployment.genesis_hash === GENESIS && deployment.program_id === PROGRAM &&
    deployment.deployment_id === '06c7dfa7528460969a5ca1e8bd001f9c9f1f1f0df3d69fe36649e413e0b14ae6' &&
    deployment.binary_sha256 === binaryHash && deployment.idl_sha256 === idlHash &&
    idl.address === PROGRAM, 'CON-35 approved deployment evidence mismatch');
  const ix = idl.instructions.find(x => x.name === 'initialize_protocol');
  required(ix && ix.args.length === 2 && ix.args[0].name === 'network_id' &&
    ix.args[1].name === 'deployment_id' &&
    ix.args.every(x => x.type.array?.[0] === 'u8' && x.type.array[1] === 32),
    'InitializeProtocol IDL mismatch');
  required(Buffer.from(ix.discriminator).equals(sha('global:initialize_protocol').subarray(0, 8)),
    'InitializeProtocol discriminator mismatch');
  required(ix.accounts.length === 3 && ix.accounts[0].name === 'protocol_config' &&
    ix.accounts[1].name === 'authority' && ix.accounts[2].name === 'system_program',
    'InitializeProtocol account order mismatch');
  return {deployment, ix, binaryHash, idlHash};
}

function configPda() {
  return PublicKey.findProgramAddressSync([Buffer.from('protocol_config')], new PublicKey(PROGRAM))[0];
}

async function inspect() {
  const evidence = approvedEvidence();
  required(await connection.getGenesisHash() === GENESIS, 'Devnet genesis mismatch');
  const program = await connection.getAccountInfo(new PublicKey(PROGRAM), 'finalized');
  required(program?.executable && program.owner.toBase58() ===
    'BPFLoaderUpgradeab1e11111111111111111111111', 'Approved program unavailable');
  const programData = new PublicKey(program.data.subarray(4, 36));
  required(programData.toBase58() === evidence.deployment.program_data_address,
    'ProgramData identity changed');
  const data = await connection.getAccountInfo(programData, 'finalized');
  required(data?.data[12] === 1 && new PublicKey(data.data.subarray(13, 45)).toBase58() ===
    evidence.deployment.upgrade_authority_pubkey, 'Upgrade authority changed');
  const binary = fs.readFileSync(binaryPath);
  const deployed = data.data.subarray(45);
  required(deployed.subarray(0, binary.length).equals(binary) &&
    deployed.subarray(binary.length).every(x => x === 0), 'On-chain SBF mismatch');
  const mint = await connection.getAccountInfo(new PublicKey(MINT), 'finalized');
  required(mint?.owner.toBase58() === 'TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA' &&
    mint.data.length === 82 && mint.data[44] === 6 &&
    new PublicKey(mint.data.subarray(4, 36)).toBase58() ===
    '4om6LcFXaZ2Wtbn3P2ZvvyqssXFQs1xjNmE2Fnj7mRHa',
    'Approved test mint state changed');
  const protocol = await connection.getAccountInfo(configPda(), 'finalized');
  const payer = await connection.getBalance(new PublicKey(PAYER), 'finalized');
  const admin = await connection.getBalance(new PublicKey(ADMIN), 'finalized');
  const rent = await connection.getMinimumBalanceForRentExemption(155, 'finalized');
  const systemRent = await connection.getMinimumBalanceForRentExemption(0, 'finalized');
  return {evidence, protocol, payer, admin, rent, systemRent,
    mintSupply: mint.data.readBigUInt64LE(36).toString()};
}

function plan(data) {
  const {deployment, binaryHash, idlHash} = data.evidence;
  const networkId = new PublicKey(GENESIS).toBuffer().toString('hex');
  // The CON-35 fingerprint is an already approved, unique deployment instance ID.
  // This choice follows DeploymentContext semantics; it is not a Program ID alias.
  const body = {
    schema_version: 1, environment: 'devnet', network: 'solana:devnet', rpc_url: RPC,
    genesis_hash: GENESIS, program_id: PROGRAM,
    program_data_address: deployment.program_data_address,
    upgrade_authority_pubkey: deployment.upgrade_authority_pubkey,
    approved_sbf_sha256: binaryHash, approved_idl_sha256: idlHash,
    approved_con35_deployment_id: deployment.deployment_id,
    network_id_hex: networkId, protocol_deployment_id_hex: deployment.deployment_id,
    protocol_config_pda: configPda().toBase58(),
    protocol_admin_pubkey: ADMIN, fee_payer_pubkey: PAYER,
    test_mint_pubkey: MINT, test_mint_decimals: 6,
    action: 'FUND_ADMIN_AND_INITIALIZE_PROTOCOL', funding_lamports: FUNDING_LAMPORTS,
    max_fee_lamports: MAX_FEE_LAMPORTS,
    max_payer_debit_lamports: FUNDING_LAMPORTS + MAX_FEE_LAMPORTS,
    rent_lamports: data.rent, admin_system_rent_lamports: data.systemRent,
  };
  return {...body, approval_id: sha(canonical(body)).toString('hex')};
}

function validatePlan(actual, current) {
  const expected = plan(current);
  required(canonical(actual) === canonical(expected), 'Prepared plan differs from live Devnet state');
  required(current.protocol === null, 'ProtocolConfig already initialized');
  required(current.admin === 0, 'Admin balance changed; reprepare the funding plan');
  required(current.admin + actual.funding_lamports >= current.rent + current.systemRent,
    'Admin lacks rent after funding and ProtocolConfig creation');
  required(current.payer >= actual.max_payer_debit_lamports, 'Fee payer lacks test SOL');
}

function safeKeypair(filename, expected) {
  const dir = fs.statSync(privateDir);
  const filepath = path.join(privateDir, filename);
  const file = fs.statSync(filepath);
  const backupDir = path.join(process.env.HOME,
    'Library/Application Support/CONATUS/con35-devnet-wallet-backup');
  const backupPath = path.join(backupDir, filename);
  const backupDirectory = fs.statSync(backupDir);
  const backup = fs.statSync(backupPath);
  required((dir.mode & 0o077) === 0 && (file.mode & 0o077) === 0,
    'Private wallet permissions too broad');
  required((backupDirectory.mode & 0o077) === 0 && (backup.mode & 0o077) === 0 &&
    sha(fs.readFileSync(filepath)).equals(sha(fs.readFileSync(backupPath))),
    'Private wallet backup missing, unprotected or different');
  const role = filename === 'fee-payer.json' ? 'fee_payer' : 'protocol_admin';
  const binding = JSON.parse(fs.readFileSync(path.join(privateDir, `${role}.binding.json`)));
  required(binding.environment === 'devnet' && binding.genesis_hash === GENESIS &&
    binding.pubkey === expected && binding.role === role, 'Wallet binding mismatch');
  const keypair = Keypair.fromSecretKey(Uint8Array.from(JSON.parse(fs.readFileSync(filepath))));
  required(keypair.publicKey.toBase58() === expected, 'Wallet identity mismatch');
  return keypair;
}

function buildTransaction(actual, payer, admin, blockhash) {
  const transfer = SystemProgram.transfer({fromPubkey: payer.publicKey,
    toPubkey: admin.publicKey, lamports: actual.funding_lamports});
  const init = new TransactionInstruction({programId: new PublicKey(PROGRAM),
    keys: [
      {pubkey: configPda(), isSigner: false, isWritable: true},
      {pubkey: admin.publicKey, isSigner: true, isWritable: true},
      {pubkey: SystemProgram.programId, isSigner: false, isWritable: false},
    ],
    data: Buffer.concat([sha('global:initialize_protocol').subarray(0, 8),
      Buffer.from(actual.network_id_hex, 'hex'),
      Buffer.from(actual.protocol_deployment_id_hex, 'hex')]),
  });
  const tx = new Transaction({feePayer: payer.publicKey, recentBlockhash: blockhash});
  tx.add(transfer, init);
  tx.sign(payer, admin);
  return tx;
}

function approvalValid(prepared, argument, environment) {
  return typeof argument === 'string' && argument === prepared.approval_id &&
    environment.CON36_APPROVED_PROTOCOL_CONFIG_ID === prepared.approval_id;
}

async function simulate(actual, current) {
  validatePlan(actual, current);
  const payer = safeKeypair('fee-payer.json', PAYER);
  const admin = safeKeypair('protocol-admin.json', ADMIN);
  const {blockhash} = await connection.getLatestBlockhash('finalized');
  const tx = buildTransaction(actual, payer, admin, blockhash);
  const fee = await connection.getFeeForMessage(tx.compileMessage(), 'finalized');
  required(Number.isInteger(fee.value) && fee.value <= MAX_FEE_LAMPORTS,
    'Quoted fee exceeds approval limit');
  const signed = new VersionedTransaction(tx.compileMessage());
  signed.sign([payer, admin]);
  const result = await connection.simulateTransaction(signed, {sigVerify: true,
    commitment: 'finalized'});
  required(!result.value.err, `Simulation failed: ${JSON.stringify(result.value.err)} ${JSON.stringify(result.value.logs)}`);
  return {approval_id: actual.approval_id, simulated: true, submitted: false,
    fee_quote_lamports: fee.value, rent_lamports: current.rent,
    funding_lamports: FUNDING_LAMPORTS, max_payer_debit_lamports: actual.max_payer_debit_lamports,
    units_consumed: result.value.unitsConsumed, logs: result.value.logs};
}

async function verify(prepared, current, signature) {
  required(canonical(prepared) === canonical(plan({evidence: current.evidence,
    rent: prepared.rent_lamports,
    systemRent: prepared.admin_system_rent_lamports})),
  'ProtocolConfig public approval plan integrity mismatch');
  required(/^[1-9A-HJ-NP-Za-km-z]{80,90}$/.test(signature), 'Invalid signature');
  const status = (await connection.getSignatureStatuses([signature],
    {searchTransactionHistory: true})).value[0];
  required(status?.confirmationStatus === 'finalized' && status.err === null,
    'Initialization transaction is not finalized and successful');
  const tx = await connection.getTransaction(signature,
    {commitment: 'finalized', maxSupportedTransactionVersion: 0});
  required(tx && tx.slot === status.slot && tx.meta?.err === null &&
    tx.transaction.signatures[0] === signature && tx.meta.fee <= prepared.max_fee_lamports,
    'Initialization transaction evidence mismatch');
  const keys = tx.transaction.message.accountKeys.map(x => x.toBase58());
  const instructions = tx.transaction.message.instructions;
  required(keys[0] === PAYER && instructions.length === 2 &&
    tx.meta.fee + prepared.funding_lamports <= prepared.max_payer_debit_lamports,
    'Transaction fee payer, instruction count or debit exceeds approved plan');
  const balancePair = address => {
    const index = keys.indexOf(address);
    required(index >= 0, `Initialization account missing from transaction: ${address}`);
    return [tx.meta.preBalances[index], tx.meta.postBalances[index]];
  };
  const payerBalances = balancePair(PAYER);
  const adminBalances = balancePair(ADMIN);
  const protocolBalances = balancePair(prepared.protocol_config_pda);
  required(payerBalances[0] - payerBalances[1] ===
    prepared.funding_lamports + tx.meta.fee &&
    adminBalances[0] === 0 &&
    adminBalances[1] === prepared.funding_lamports - prepared.rent_lamports &&
    protocolBalances[0] === 0 && protocolBalances[1] === prepared.rent_lamports,
    'Initialization SOL balances differ from approved plan');
  const init = instructions.find(x => keys[x.programIdIndex] === PROGRAM);
  required(init && init.accounts.map(i => keys[i]).join(',') ===
    [prepared.protocol_config_pda, ADMIN, SystemProgram.programId.toBase58()].join(','),
    'Initialization accounts do not match approved plan');
  const expectedData = Buffer.concat([sha('global:initialize_protocol').subarray(0, 8),
    Buffer.from(prepared.network_id_hex, 'hex'),
    Buffer.from(prepared.protocol_deployment_id_hex, 'hex')]);
  required(Buffer.from(bs58.decode(init.data)).equals(expectedData),
    'Initialization payload differs from approved plan');
  const transfer = instructions.find(x => keys[x.programIdIndex] === SystemProgram.programId.toBase58());
  const transferData = transfer && Buffer.from(bs58.decode(transfer.data));
  required(transferData?.readUInt32LE(0) === 2 &&
    transferData.readBigUInt64LE(4) === BigInt(prepared.funding_lamports) &&
    transfer.accounts.map(i => keys[i]).join(',') === `${PAYER},${ADMIN}`,
    'Funding transfer differs from approved plan');
  required(current.protocol?.owner.toBase58() === PROGRAM && current.protocol.data.length === 155,
    'ProtocolConfig missing or wrong owner');
  const raw = current.protocol.data;
  required(raw.subarray(0, 8).equals(sha('account:ProtocolConfig').subarray(0, 8)) &&
    raw[8] === 1 && new PublicKey(raw.subarray(9, 41)).toBase58() === ADMIN &&
    raw.subarray(41, 73).toString('hex') === prepared.network_id_hex &&
    new PublicKey(raw.subarray(73, 105)).toBase58() === PROGRAM &&
    raw.subarray(105, 137).toString('hex') === prepared.protocol_deployment_id_hex &&
    raw[137] === 255 && [0, 1].includes(raw[146]),
    'ProtocolConfig on-chain state differs from approved plan');
  return {approval_id: prepared.approval_id, signature, slot: status.slot,
    fee_lamports: tx.meta.fee,
    payer_debit_lamports: payerBalances[0] - payerBalances[1],
    admin_post_balance_lamports: adminBalances[1],
    protocol_config_rent_lamports: protocolBalances[1],
    protocol_config_pda: prepared.protocol_config_pda,
    current_agent_count: raw.readBigUInt64LE(138).toString(),
    current_paused: raw[146] === 1,
    network_id_hex: prepared.network_id_hex,
    protocol_deployment_id_hex: prepared.protocol_deployment_id_hex,
    verification_status: 'VERIFIED', genesis_hash: GENESIS, network: 'solana:devnet'};
}

async function main() {
  const action = process.argv[2] || 'inspect';
  const file = process.argv[3] || path.join(repo, 'evidence/con36/protocol-config-plan.json');
  required(['inspect', 'prepare', 'simulate', 'submit', 'verify'].includes(action),
    'Usage: node protocol_config.cjs inspect|prepare|simulate|submit|verify [plan-file] [approval-id]');
  const current = await inspect();
  if (action === 'inspect') {
    console.log(JSON.stringify({genesis_hash: GENESIS, program_id: PROGRAM,
      test_mint_pubkey: MINT, test_mint_supply: current.mintSupply,
      protocol_config_pda: configPda().toBase58(),
      protocol_config_initialized: !!current.protocol,
      fee_payer_balance_lamports: current.payer,
      protocol_admin_balance_lamports: current.admin,
      protocol_config_rent_lamports: current.rent,
      admin_system_rent_lamports: current.systemRent}, null, 2));
    return;
  }
  if (action === 'prepare') {
    const prepared = plan(current);
    validatePlan(prepared, current);
    fs.mkdirSync(path.dirname(file), {recursive: true});
    const serialized = JSON.stringify(prepared, null, 2) + '\n';
    if (fs.existsSync(file)) required(fs.readFileSync(file, 'utf8') === serialized,
      'Existing immutable plan differs');
    else fs.writeFileSync(file, serialized, {flag: 'wx', mode: 0o644});
    console.log(JSON.stringify({plan_path: file, approval_id: prepared.approval_id,
      transaction_submitted: false}, null, 2));
    return;
  }
  const prepared = JSON.parse(fs.readFileSync(file));
  if (action !== 'verify') validatePlan(prepared, current);
  if (action === 'simulate') {
    console.log(JSON.stringify(await simulate(prepared, current), null, 2));
    return;
  }
  if (action === 'submit') {
    required(approvalValid(prepared, process.argv[4], process.env),
      'Exact human approval ID required');
    const simulation = await simulate(prepared, current);
    required(simulation.simulated, 'Simulation gate failed');
    const payer = safeKeypair('fee-payer.json', PAYER);
    const admin = safeKeypair('protocol-admin.json', ADMIN);
    const {blockhash} = await connection.getLatestBlockhash('finalized');
    const tx = buildTransaction(prepared, payer, admin, blockhash);
    const signature = await sendAndConfirmTransaction(connection, tx, [payer, admin],
      {commitment: 'finalized'});
    console.log(JSON.stringify({signature, approval_id: prepared.approval_id,
      status: 'SUBMITTED; run verify against real RPC'}, null, 2));
    return;
  }
  required(action === 'verify' && !!process.argv[4], 'Finalized signature required');
  console.log(JSON.stringify(await verify(prepared, current, process.argv[4]), null, 2));
}

if (require.main === module) main().catch(error => { console.error(error.message); process.exitCode = 1; });
module.exports = {plan, validatePlan, buildTransaction, approvalValid, approvedEvidence, inspect};
