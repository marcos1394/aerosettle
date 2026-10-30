'use strict';

// Independent Devnet-only test funding and token mint plan. Nothing submits by default.
const fs = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');
const {createRequire} = require('node:module');
const repo = path.resolve(__dirname, '../../..');
const fromBootstrap = createRequire(path.join(repo, 'tools/bootstrap/package.json'));
const {Connection, Keypair, PublicKey, SystemProgram, Transaction,
  VersionedTransaction, sendAndConfirmTransaction} = fromBootstrap('@solana/web3.js');
const bs58 = fromBootstrap('bs58');
const {getAssociatedTokenAddressSync, createAssociatedTokenAccountIdempotentInstruction,
  createMintToCheckedInstruction, TOKEN_PROGRAM_ID, ASSOCIATED_TOKEN_PROGRAM_ID,
  getAccount, getMint} = fromBootstrap('@solana/spl-token');
const {inspect: inspectProtocol} = require('./protocol_config.cjs');

const RPC = 'https://api.devnet.solana.com';
const GENESIS = 'EtWTRABZaYq6iMfeYKouRu166VU2xqa1wcaWoxPkrZBG';
const PAYER = 'HRwPNBPzArvdCULMH1EFuUpxGw31CbRjyf1cGBz2zE2x';
const MINT = 'HpfaV9oRuTN1b3ktDKvJoWqUWFZ1o9VFmhejxxqQ1vyh';
const AUTHORITY = '4om6LcFXaZ2Wtbn3P2ZvvyqssXFQs1xjNmE2Fnj7mRHa';
const TOKEN_AMOUNT = 7_100_000n;
const FUNDING_EACH = 100_000_000;
const MAX_FEE = 20_000;
const connection = new Connection(RPC, 'finalized');
const sha = x => crypto.createHash('sha256').update(x).digest();
const canonical = x => JSON.stringify(x, Object.keys(x).sort());
const required = (ok, message) => { if (!ok) throw Error(message); };
const ids = JSON.parse(fs.readFileSync(path.join(repo, 'evidence/con36/test-identities.json')));
const scenarios = JSON.parse(fs.readFileSync(path.join(repo, 'evidence/con36/scenario-plan.json')));
const protocolPlan = JSON.parse(fs.readFileSync(path.join(repo, 'evidence/con36/protocol-config-plan.json')));
const mint = new PublicKey(MINT);
const payerPk = new PublicKey(PAYER);
const creator = new PublicKey(ids.roles.creator);
const owner = new PublicKey(ids.roles.agent_owner);
const creatorAta = getAssociatedTokenAddressSync(mint, creator, false, TOKEN_PROGRAM_ID);
const ownerAta = getAssociatedTokenAddressSync(mint, owner, false, TOKEN_PROGRAM_ID);

async function inspect() {
  const protocol = await inspectProtocol();
  required(await connection.getGenesisHash() === GENESIS,
    'Test mint network mismatch');
  required(scenarios.required_mint_supply_base_units === Number(TOKEN_AMOUNT) &&
    scenarios.mint_pubkey === MINT && ids.genesis_hash === GENESIS,
    'CON-36 scenario or identity plan mismatch');
  const creatorBalance = await connection.getBalance(creator, 'finalized');
  const ownerBalance = await connection.getBalance(owner, 'finalized');
  const creatorAccount = await connection.getAccountInfo(creatorAta, 'finalized');
  const ownerAccount = await connection.getAccountInfo(ownerAta, 'finalized');
  const ataRent = await connection.getMinimumBalanceForRentExemption(165, 'finalized');
  return {protocol, creatorBalance, ownerBalance, creatorAccount, ownerAccount, ataRent};
}

function plan(current) {
  const body = {schema_version: 1, status: 'PREPARED_NOT_AUTHORIZED',
    environment: 'devnet', network: 'solana:devnet', rpc_url: RPC,
    genesis_hash: GENESIS, program_id: scenarios.program_id,
    protocol_config_approval_id: protocolPlan.approval_id,
    mint_pubkey: MINT, mint_authority_pubkey: AUTHORITY, mint_decimals: 6,
    token_program: TOKEN_PROGRAM_ID.toBase58(),
    fee_payer_pubkey: PAYER,
    creator_pubkey: creator.toBase58(), agent_owner_pubkey: owner.toBase58(),
    creator_ata: creatorAta.toBase58(), agent_owner_ata: ownerAta.toBase58(),
    creator_funding_lamports: FUNDING_EACH,
    agent_owner_funding_lamports: FUNDING_EACH,
    mint_base_units: Number(TOKEN_AMOUNT), ata_rent_lamports_each: current.ataRent,
    max_fee_lamports: MAX_FEE,
    max_payer_debit_lamports: FUNDING_EACH * 2 + current.ataRent * 2 + MAX_FEE,
    actions: ['FUND_CREATOR', 'FUND_AGENT_OWNER', 'CREATE_CREATOR_ATA',
      'CREATE_AGENT_OWNER_ATA', 'MINT_TEST_TOKENS'],
    transaction_submitted: false};
  return {...body, approval_id: sha(canonical(body)).toString('hex')};
}

function validatePlan(prepared, current) {
  required(canonical(prepared) === canonical(plan(current)),
    'Test asset plan differs from current Devnet and public identities');
  required(current.protocol.mintSupply === '0' &&
    current.creatorBalance === 0 && current.ownerBalance === 0 &&
    !current.creatorAccount && !current.ownerAccount, 'Test accounts already funded or created');
  required(current.protocol.payer >= prepared.max_payer_debit_lamports,
    'Fee payer lacks bounded test SOL');
}

function keypair(filename, expected, backupName = filename) {
  const localDir = path.join(repo, 'target/deploy/con35-private');
  const backupDir = path.join(process.env.HOME,
    'Library/Application Support/CONATUS/con35-devnet-wallet-backup');
  const local = path.join(localDir, filename);
  const backup = path.join(backupDir, backupName);
  required((fs.statSync(localDir).mode & 0o077) === 0 &&
    (fs.statSync(backupDir).mode & 0o077) === 0 &&
    (fs.statSync(local).mode & 0o077) === 0 &&
    (fs.statSync(backup).mode & 0o077) === 0 &&
    fs.readFileSync(local).equals(fs.readFileSync(backup)),
    'Test signer backup missing, unprotected or different');
  const wallet = Keypair.fromSecretKey(Uint8Array.from(JSON.parse(fs.readFileSync(local))));
  required(wallet.publicKey.toBase58() === expected, 'Test signer identity mismatch');
  return wallet;
}

function instructions(prepared) {
  return [SystemProgram.transfer({fromPubkey: payerPk, toPubkey: creator,
    lamports: prepared.creator_funding_lamports}),
  SystemProgram.transfer({fromPubkey: payerPk, toPubkey: owner,
    lamports: prepared.agent_owner_funding_lamports}),
  createAssociatedTokenAccountIdempotentInstruction(payerPk,
    creatorAta, creator, mint, TOKEN_PROGRAM_ID, ASSOCIATED_TOKEN_PROGRAM_ID),
  createAssociatedTokenAccountIdempotentInstruction(payerPk,
    ownerAta, owner, mint, TOKEN_PROGRAM_ID, ASSOCIATED_TOKEN_PROGRAM_ID),
  createMintToCheckedInstruction(mint, creatorAta, new PublicKey(AUTHORITY),
    TOKEN_AMOUNT, 6, [], TOKEN_PROGRAM_ID)];
}

function build(prepared, payer, authority, blockhash) {
  required(payer.publicKey.toBase58() === PAYER &&
    authority.publicKey.toBase58() === AUTHORITY, 'Test asset signer mismatch');
  const tx = new Transaction({feePayer: payer.publicKey, recentBlockhash: blockhash});
  tx.add(...instructions(prepared));
  tx.sign(payer, authority);
  return tx;
}

async function simulate(prepared, current) {
  validatePlan(prepared, current);
  const payer = keypair('fee-payer.json', PAYER);
  const authority = keypair('test-mint-authority.json', AUTHORITY);
  const {blockhash} = await connection.getLatestBlockhash('finalized');
  const tx = build(prepared, payer, authority, blockhash);
  const fee = await connection.getFeeForMessage(tx.compileMessage(), 'finalized');
  required(Number.isInteger(fee.value) && fee.value <= MAX_FEE,
    'Test asset transaction fee exceeds approved maximum');
  const signed = new VersionedTransaction(tx.compileMessage());
  signed.sign([payer, authority]);
  const simulation = await connection.simulateTransaction(signed,
    {sigVerify: true, commitment: 'finalized'});
  required(!simulation.value.err,
    `Test asset simulation failed: ${JSON.stringify(simulation.value.err)} ${JSON.stringify(simulation.value.logs)}`);
  return {approval_id: prepared.approval_id, simulated: true, submitted: false,
    fee_quote_lamports: fee.value,
    ata_rent_lamports_each: current.ataRent,
    max_payer_debit_lamports: prepared.max_payer_debit_lamports,
    mint_base_units: prepared.mint_base_units,
    units_consumed: simulation.value.unitsConsumed, logs: simulation.value.logs};
}

function approvalValid(prepared, argument, environment) {
  return argument === prepared.approval_id &&
    environment.CON36_APPROVED_TEST_ASSET_ID === prepared.approval_id;
}

async function verify(prepared, signature) {
  required(canonical(prepared) === canonical(plan({ataRent: prepared.ata_rent_lamports_each})),
    'Test asset public approval plan integrity mismatch');
  required(/^[1-9A-HJ-NP-Za-km-z]{80,90}$/.test(signature), 'Invalid signature');
  required(await connection.getGenesisHash() === GENESIS, 'Devnet genesis changed');
  const status = (await connection.getSignatureStatuses([signature],
    {searchTransactionHistory: true})).value[0];
  required(status?.confirmationStatus === 'finalized' && status.err === null,
    'Test asset transaction is not finalized');
  const tx = await connection.getTransaction(signature,
    {commitment: 'finalized', maxSupportedTransactionVersion: 0});
  required(tx && tx.slot === status.slot && tx.meta?.err === null &&
    tx.transaction.signatures[0] === signature &&
    tx.transaction.message.accountKeys[0].toBase58() === PAYER &&
    tx.transaction.message.instructions.length === 5 &&
    tx.meta.fee <= prepared.max_fee_lamports &&
    tx.meta.preBalances[0] - tx.meta.postBalances[0] <=
      prepared.max_payer_debit_lamports,
    'Test asset transaction evidence mismatch');
  const keys = tx.transaction.message.accountKeys.map(x => x.toBase58());
  const balancePair = address => {
    const index = keys.indexOf(address);
    required(index >= 0, `Account missing from test asset transaction: ${address}`);
    return [tx.meta.preBalances[index], tx.meta.postBalances[index]];
  };
  const payerBalances = balancePair(PAYER);
  const creatorBalances = balancePair(creator.toBase58());
  const ownerBalances = balancePair(owner.toBase58());
  const creatorAtaBalances = balancePair(creatorAta.toBase58());
  const ownerAtaBalances = balancePair(ownerAta.toBase58());
  required(payerBalances[0] - payerBalances[1] ===
    prepared.creator_funding_lamports + prepared.agent_owner_funding_lamports +
    prepared.ata_rent_lamports_each * 2 + tx.meta.fee &&
    creatorBalances[0] === 0 && creatorBalances[1] === prepared.creator_funding_lamports &&
    ownerBalances[0] === 0 && ownerBalances[1] === prepared.agent_owner_funding_lamports &&
    creatorAtaBalances[0] === 0 && creatorAtaBalances[1] === prepared.ata_rent_lamports_each &&
    ownerAtaBalances[0] === 0 && ownerAtaBalances[1] === prepared.ata_rent_lamports_each,
    'Historical test SOL and ATA rent balances differ from approved plan');
  const expected = instructions(prepared);
  tx.transaction.message.instructions.forEach((instruction, index) => {
    const matching = expected[index];
    required(keys[instruction.programIdIndex] === matching.programId.toBase58() &&
      instruction.accounts.map(i => keys[i]).join(',') ===
        matching.keys.map(x => x.pubkey.toBase58()).join(',') &&
      Buffer.from(bs58.decode(instruction.data)).equals(matching.data),
    `Test asset instruction ${index} differs from approved plan`);
  });
  const mintInfo = await getMint(connection, mint, 'finalized', TOKEN_PROGRAM_ID);
  const source = await getAccount(connection, creatorAta, 'finalized', TOKEN_PROGRAM_ID);
  const destination = await getAccount(connection, ownerAta, 'finalized', TOKEN_PROGRAM_ID);
  const tokenBalance = (items, address) => items.find(x =>
    keys[x.accountIndex] === address)?.uiTokenAmount?.amount;
  required(tokenBalance(tx.meta.postTokenBalances || [], creatorAta.toBase58()) ===
    TOKEN_AMOUNT.toString() &&
    tokenBalance(tx.meta.postTokenBalances || [], ownerAta.toBase58()) === '0' &&
    tokenBalance(tx.meta.preTokenBalances || [], creatorAta.toBase58()) === undefined &&
    tokenBalance(tx.meta.preTokenBalances || [], ownerAta.toBase58()) === undefined,
    'Historical SPL minting balances differ from approved plan');
  required(mintInfo.decimals === 6 && mintInfo.mintAuthority?.toBase58() === AUTHORITY &&
    mintInfo.supply === TOKEN_AMOUNT && source.mint.toBase58() === MINT &&
    source.owner.toBase58() === creator.toBase58() &&
    destination.mint.toBase58() === MINT && destination.owner.toBase58() === owner.toBase58(),
    'On-chain SPL test accounts differ from prepared plan');
  return {approval_id: prepared.approval_id, signature, slot: status.slot,
    fee_lamports: tx.meta.fee,
    payer_debit_lamports: payerBalances[0] - payerBalances[1],
    creator_funding_lamports: creatorBalances[1],
    agent_owner_funding_lamports: ownerBalances[1],
    ata_rent_lamports_each: prepared.ata_rent_lamports_each,
    mint_pubkey: MINT,
    minted_base_units: TOKEN_AMOUNT.toString(), creator_ata: creatorAta.toBase58(),
    agent_owner_ata: ownerAta.toBase58(), genesis_hash: GENESIS,
    verification_status: 'VERIFIED'};
}

async function main() {
  const action = process.argv[2] || 'inspect';
  required(['inspect', 'prepare', 'simulate', 'submit', 'verify'].includes(action),
    'Usage: node asset_funding.cjs inspect|prepare|simulate|submit|verify [plan] [approval-or-signature]');
  const file = process.argv[3] || path.join(repo, 'evidence/con36/test-asset-plan.json');
  if (action === 'inspect') {
    const current = await inspect();
    console.log(JSON.stringify({genesis_hash: GENESIS, mint_pubkey: MINT,
      mint_supply: current.protocol.mintSupply,
      creator_lamports: current.creatorBalance,
      agent_owner_lamports: current.ownerBalance,
      creator_ata_exists: !!current.creatorAccount,
      agent_owner_ata_exists: !!current.ownerAccount,
      ata_rent_lamports_each: current.ataRent}, null, 2));
    return;
  }
  if (action === 'verify') {
    const prepared = JSON.parse(fs.readFileSync(file));
    console.log(JSON.stringify(await verify(prepared, process.argv[4] || ''), null, 2));
    return;
  }
  const current = await inspect();
  if (action === 'prepare') {
    const prepared = plan(current);
    validatePlan(prepared, current);
    const bytes = JSON.stringify(prepared, null, 2) + '\n';
    if (fs.existsSync(file)) required(fs.readFileSync(file, 'utf8') === bytes,
      'Existing test asset plan differs');
    else fs.writeFileSync(file, bytes, {flag: 'wx', mode: 0o644});
    console.log(JSON.stringify({plan_path: file, approval_id: prepared.approval_id,
      transaction_submitted: false}, null, 2));
    return;
  }
  const prepared = JSON.parse(fs.readFileSync(file));
  validatePlan(prepared, current);
  if (action === 'simulate') {
    console.log(JSON.stringify(await simulate(prepared, current), null, 2));
    return;
  }
  required(approvalValid(prepared, process.argv[4], process.env),
    'Exact CON-36 test asset approval required');
  await simulate(prepared, current);
  const payer = keypair('fee-payer.json', PAYER);
  const authority = keypair('test-mint-authority.json', AUTHORITY);
  const {blockhash} = await connection.getLatestBlockhash('finalized');
  const signature = await sendAndConfirmTransaction(connection,
    build(prepared, payer, authority, blockhash), [payer, authority],
    {commitment: 'finalized'});
  console.log(JSON.stringify({signature, approval_id: prepared.approval_id,
    status: 'SUBMITTED; run verify against real RPC'}, null, 2));
}

if (require.main === module) main().catch(error => { console.error(error.message); process.exitCode = 1; });
module.exports = {plan, validatePlan, instructions, build, approvalValid};
