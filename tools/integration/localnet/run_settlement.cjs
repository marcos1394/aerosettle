'use strict';

// Fresh test identities only. Usage: node run_settlement.cjs execute|verify REPORT.json
const fs = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');
const {createRequire} = require('node:module');
const repo = path.resolve(__dirname, '../../..');
const fromBootstrap = createRequire(path.join(repo, 'tools/bootstrap/package.json'));
const {
  Connection, Keypair, PublicKey, SystemProgram, Transaction,
  TransactionInstruction, sendAndConfirmTransaction, SYSVAR_CLOCK_PUBKEY,
} = fromBootstrap('@solana/web3.js');
const {
  TOKEN_PROGRAM_ID, createMint, createAccount, mintToChecked, getAccount,
} = fromBootstrap('@solana/spl-token');

const action = process.argv[2];
const reportPath = process.argv[3];
const rpcUrl = process.env.CON34_RPC_URL || 'http://127.0.0.1:18899';
if (!['execute', 'verify'].includes(action) || !reportPath ||
    !/^http:\/\/(127\.0\.0\.1|localhost):\d+$/.test(rpcUrl)) {
  throw Error('Usage: CON34_RPC_URL=http://127.0.0.1:18899 node run_settlement.cjs execute|verify REPORT.json');
}
const idl = JSON.parse(fs.readFileSync(path.join(__dirname, 'aerosettle-idl.json')));
const programId = new PublicKey(idl.address);
const connection = new Connection(rpcUrl, 'confirmed');
const norm = x => String(x).split('::').at(-1).replace(/[^a-z0-9]/gi, '').toLowerCase();
const one = (items, name) => {
  const matches = items.filter(x => norm(x.name) === norm(name));
  if (matches.length !== 1) throw Error(`IDL ${name}: ${matches.length} matches`);
  return matches[0];
};
const sha = data => crypto.createHash('sha256').update(data).digest();
const pda = seeds => PublicKey.findProgramAddressSync(seeds, programId)[0];
const byte32 = x => { const b = Buffer.from(x); if (b.length !== 32) throw Error('bytes32'); return b; };
function encode(type, value) {
  if (typeof type === 'string') {
    if (type === 'pubkey') return new PublicKey(value).toBuffer();
    const size = {u8: 1, u16: 2, u32: 4, u64: 8, i64: 8}[type];
    if (!size) throw Error(`Unsupported IDL type ${type}`);
    const b = Buffer.alloc(size); const n = BigInt(value);
    if (n < (type === 'i64' ? -(1n << 63n) : 0n) ||
        n >= (type === 'i64' ? (1n << 63n) : (1n << BigInt(size * 8)))) throw Error(`${type} range`);
    if (type === 'i64') b.writeBigInt64LE(n);
    else if (size === 8) b.writeBigUInt64LE(n);
    else if (size === 4) b.writeUInt32LE(Number(n));
    else if (size === 2) b.writeUInt16LE(Number(n));
    else b.writeUInt8(Number(n));
    return b;
  }
  if (type.array?.[0] === 'u8' && type.array[1] === 32) return byte32(value);
  const defined = type.defined?.name || type.defined;
  const def = one(idl.types, defined).type;
  if (def.kind === 'enum') {
    const index = def.variants.findIndex(x => norm(x.name) === norm(value));
    if (index < 0 || def.variants[index].fields) throw Error(`Enum ${defined}`);
    return Buffer.from([index]);
  }
  if (def.kind === 'struct') return Buffer.concat(def.fields.map(f => {
    const k = Object.keys(value).find(x => norm(x) === norm(f.name));
    if (!k) throw Error(`Missing ${f.name}`);
    return encode(f.type, value[k]);
  }));
  throw Error(`Unsupported IDL definition ${defined}`);
}
function instruction(name, accounts, args = {}) {
  const def = one(idl.instructions, name);
  const expectedDisc = sha(Buffer.from(`global:${name}`)).subarray(0, 8);
  const disc = Buffer.from(def.discriminator);
  if (!disc.equals(expectedDisc)) throw Error(`IDL discriminator mismatch: ${name}`);
  const data = Buffer.concat([disc, ...def.args.map(a => {
    const key = Object.keys(args).find(x => norm(x) === norm(a.name));
    if (!key) throw Error(`Missing instruction argument ${a.name}`);
    return encode(a.type, args[key]);
  })]);
  const keys = def.accounts.map(a => {
    const key = Object.keys(accounts).find(x => norm(x) === norm(a.name));
    if (!key) throw Error(`Missing account ${a.name}`);
    const pubkey = new PublicKey(accounts[key]);
    if (a.address && a.address !== pubkey.toBase58()) throw Error(`IDL address mismatch: ${a.name}`);
    return {pubkey, isSigner: !!a.signer, isWritable: !!a.writable};
  });
  return new TransactionInstruction({programId, keys, data});
}
async function send(ix, payer, signers = []) {
  const tx = new Transaction().add(ix);
  const unique = [...new Map([payer, ...signers].map(k => [k.publicKey.toBase58(), k])).values()];
  return sendAndConfirmTransaction(connection, tx, unique, {commitment: 'confirmed'});
}
async function finalized(signature) {
  for (let i = 0; i < 90; i++) {
    const status = (await connection.getSignatureStatuses([signature], {searchTransactionHistory: true})).value[0];
    if (status?.err) throw Error(`Transaction failed: ${JSON.stringify(status.err)}`);
    if (status?.confirmationStatus === 'finalized') return status;
    await new Promise(resolve => setTimeout(resolve, 1000));
  }
  throw Error(`Transaction not finalized: ${signature}`);
}
async function chainNow() {
  const info = await connection.getAccountInfo(SYSVAR_CLOCK_PUBKEY, 'confirmed');
  if (!info || info.data.length < 40) throw Error('Missing Clock sysvar');
  return info.data.readBigInt64LE(32);
}
async function balance(pubkey) { return (await getAccount(connection, pubkey, 'confirmed')).amount; }
function attestationHash(orderId, receipt, manifest, verifier, bps, verifiedAt) {
  const b = Buffer.alloc(2); b.writeUInt16LE(bps);
  const t = Buffer.alloc(8); t.writeBigInt64LE(verifiedAt);
  return sha(Buffer.concat([
    Buffer.from('AEROSETTLE:VERIFICATION_ATTESTATION:V1\0'),
    Buffer.from([1]), orderId, receipt, manifest, verifier.toBuffer(),
    Buffer.from([0]), b, t,
  ]));
}
async function execute() {
  if (fs.existsSync(reportPath)) throw Error('Report path already exists; use a new isolated run');
  const genesis = await connection.getGenesisHash();
  const program = await connection.getAccountInfo(programId, 'finalized');
  if (!program?.executable) throw Error('AeroSettle SBF is not deployed on local validator');
  const creator = Keypair.generate();
  const verifier = Keypair.generate();
  const config = pda([Buffer.from('protocol_config')]);
  const air = await connection.requestAirdrop(creator.publicKey, 20_000_000_000);
  await finalized(air);
  let sig;
  if (!(await connection.getAccountInfo(config, 'finalized'))) {
    sig = await send(instruction('initialize_protocol', {
      protocol_config: config, authority: creator.publicKey, system_program: SystemProgram.programId,
    }, {network_id: Buffer.alloc(32, 9), deployment_id: Buffer.alloc(32, 10)}), creator);
    await finalized(sig);
  }
  process.stdout.write('ProtocolConfig ready\n');
  const mint = await createMint(connection, creator, creator.publicKey, null, 6);
  process.stdout.write(`Mint ${mint.toBase58()} created\n`);
  const source = await createAccount(connection, creator, mint, creator.publicKey);
  process.stdout.write(`Source ${source.toBase58()} created\n`);
  await mintToChecked(connection, creator, mint, source, creator, 50_000_000n, 6);
  const allCases = [
    {name: 'full', model: 'Fixed', bps: 10_000, expected: 10_000_000n},
    {name: 'zero', model: 'Fixed', bps: 6_000, expected: 0n},
    {name: 'proportional', model: 'Proportional', bps: 6_000, expected: 6_000_000n},
    {name: 'invalid_shared', model: 'Proportional', bps: 6_000, expected: 6_000_000n, invalid: true},
    {name: 'valid_shared', model: 'Proportional', bps: 6_000, expected: 6_000_000n, shared: true},
  ];
  const selected = process.env.CON34_SCENARIOS?.split(',') || allCases.map(x => x.name);
  if (selected.length === 0 || selected.some(name => !allCases.some(x => x.name === name))) {
    throw Error('CON34_SCENARIOS contains an unknown or empty scenario');
  }
  const cases = allCases.filter(x => selected.includes(x.name));
  const evidence = [];
  for (const spec of cases) {
    process.stdout.write(`Starting ${spec.name}\n`);
    const owner = spec.shared ? creator : Keypair.generate();
    const device = Keypair.generate();
    if (owner !== creator) await finalized(await connection.requestAirdrop(owner.publicKey, 2_000_000_000));
    const destination = await createAccount(connection, creator, mint, owner.publicKey, Keypair.generate());
    const refund = spec.shared || spec.invalid ? destination :
      await createAccount(connection, creator, mint, creator.publicKey, Keypair.generate());
    const orderId = sha(Buffer.from(`CON-34:${genesis}:${spec.name}:${crypto.randomUUID()}`));
    const agentId = sha(Buffer.from(`CON-34:agent:${genesis}:${spec.name}:${crypto.randomUUID()}`));
    const order = pda([Buffer.from('work_order'), config.toBuffer(), creator.publicKey.toBuffer(), orderId]);
    const vault = pda([Buffer.from('escrow'), order.toBuffer()]);
    const agent = pda([Buffer.from('agent'), config.toBuffer(), agentId]);
    const now = await chainNow();
    const createArgs = {
      work_order_id: orderId, work_type: 'Inspection', required_capabilities: 1n | 32n,
      evidence_requirements: 1n | 2n | 4n | 64n,
      manifest_hash: sha(Buffer.from(`CON-34:manifest:${spec.name}`)),
      settlement: {token_mint: mint, total_amount: 10_000_000n,
        payment_model: spec.model, verifier: verifier.publicKey},
      execution_deadline: now + 3600n, verification_deadline: now + 7200n,
    };
    await finalized(await send(instruction('create_work_order', {
      protocol_config: config, work_order: order, creator: creator.publicKey,
      system_program: SystemProgram.programId,
    }, {args: createArgs}), creator));
    await finalized(await send(instruction('fund_work_order', {
      protocol_config: config, work_order: order, creator: creator.publicKey, mint,
      creator_token_account: source, escrow_vault: vault,
      token_program: TOKEN_PROGRAM_ID, system_program: SystemProgram.programId,
    }), creator));
    await finalized(await send(instruction('register_agent', {
      protocol_config: config, agent_account: agent, owner: owner.publicKey,
      system_program: SystemProgram.programId,
    }, {agent_id: agentId, signing_authority: device.publicKey,
      agent_type: 'Drone', capabilities: 1n | 32n | (1n << 15n),
      metadata_hash: sha(Buffer.from(`CON-34:agent:${spec.name}`))}), creator, [owner]));
    await finalized(await send(instruction('claim_work_order', {
      protocol_config: config, work_order: order, agent_account: agent,
      agent_signer: device.publicKey,
    }), creator, [device]));
    const started = await chainNow();
    const receipt = sha(Buffer.from(`CON-34:receipt:${spec.name}`));
    const manifest = sha(Buffer.from(`CON-34:evidence:${spec.name}`));
    await finalized(await send(instruction('submit_execution', {
      protocol_config: config, work_order: order, agent_account: agent,
      agent_signer: device.publicKey,
    }, {args: {execution_receipt_hash: receipt, evidence_manifest_hash: manifest,
      provided_evidence: createArgs.evidence_requirements,
      execution_started_at: started, execution_ended_at: started,
      signature_sequence: 0n}}), creator, [device]));
    const verifiedAt = await chainNow();
    await finalized(await send(instruction('verify_execution', {
      protocol_config: config, work_order: order, verifier: verifier.publicKey,
    }, {args: {verification_attestation_hash: attestationHash(orderId, receipt, manifest,
      verifier.publicKey, spec.bps, verifiedAt), status: 'Accepted',
      completion_bps: spec.bps, verified_at: verifiedAt}}), creator, [verifier]));
    const before = {vault: String(await balance(vault)), operator: String(await balance(destination)),
      refund: String(await balance(refund))};
    const settle = instruction('settle_work_order', {
      protocol_config: config, work_order: order, escrow_vault: vault, mint,
      operator_token_account: destination, creator_refund_token_account: refund,
      token_program: TOKEN_PROGRAM_ID,
    });
    if (spec.invalid) {
      let rejection;
      try { await send(settle, creator); } catch (error) { rejection = error; }
      const rejectionText = [rejection?.message, ...(rejection?.transactionLogs || [])].join('\n');
      if (!rejectionText.includes('SettlementInvalidCreatorRefund') ||
          await balance(vault) !== 10_000_000n ||
          await balance(destination) !== BigInt(before.operator)) {
        throw Error(`Invalid shared destination did not produce the expected atomic Anchor rejection: ${rejectionText}`);
      }
      evidence.push({scenario: spec.name, result: 'ANCHOR_REJECTED',
        anchor_error_code: 'SettlementInvalidCreatorRefund', work_order_pda: order.toBase58(),
        escrow_vault: vault.toBase58(), mint: mint.toBase58(), initial_balances: before});
      continue;
    }
    sig = await send(settle, creator);
    const status = await finalized(sig);
    const tx = await connection.getTransaction(sig, {commitment: 'finalized', maxSupportedTransactionVersion: 0});
    if (!tx || tx.meta?.err || tx.slot !== status.slot) throw Error('Finalized transaction missing');
    const after = {vault: String(await balance(vault)), operator: String(await balance(destination)),
      refund: String(await balance(refund))};
    const payout = spec.expected;
    const total = 10_000_000n;
    if (BigInt(after.vault) !== 0n || BigInt(after.operator) - BigInt(before.operator) !==
        (spec.shared ? total : payout) ||
        (!spec.shared && BigInt(after.refund) - BigInt(before.refund) !== total - payout)) {
      throw Error(`SPL balance mismatch: ${spec.name}`);
    }
    evidence.push({scenario: spec.name, result: 'FINALIZED', network: 'solana:localnet', rpc_url: rpcUrl,
      genesis_hash: genesis, program_id: programId.toBase58(), transaction_signature: sig,
      slot: tx.slot, block_time: tx.blockTime, commitment: 'finalized', transaction_error: null,
      work_order_pda: order.toBase58(), agent_account: agent.toBase58(),
      escrow_vault: vault.toBase58(), mint: mint.toBase58(), creator: creator.publicKey.toBase58(),
      settlement_beneficiary: owner.publicKey.toBase58(), operator_token_account: destination.toBase58(),
      creator_refund_token_account: refund.toBase58(), initial_balances: before,
      final_balances: after, expected_payout: String(payout), creator_refund: String(total - payout)});
    process.stdout.write(`${spec.name}: ${sig} finalized at slot ${tx.slot}\n`);
  }
  fs.mkdirSync(path.dirname(reportPath), {recursive: true});
  fs.writeFileSync(reportPath, JSON.stringify({environment: 'isolated-localnet', genesis_hash: genesis,
    program_id: programId.toBase58(), scenarios: evidence}, null, 2) + '\n', {flag: 'wx', mode: 0o600});
}
async function verify() {
  const report = JSON.parse(fs.readFileSync(reportPath));
  const genesis = await connection.getGenesisHash();
  if (genesis !== report.genesis_hash || report.program_id !== programId.toBase58()) throw Error('Network identity changed');
  for (const item of report.scenarios.filter(x => x.result === 'FINALIZED')) {
    const status = await finalized(item.transaction_signature);
    const tx = await connection.getTransaction(item.transaction_signature,
      {commitment: 'finalized', maxSupportedTransactionVersion: 0});
    if (!tx || tx.meta?.err || tx.slot !== item.slot || status.slot !== item.slot) throw Error(`Lost transaction ${item.scenario}`);
    const order = await connection.getAccountInfo(new PublicKey(item.work_order_pda), 'finalized');
    if (!order || !order.owner.equals(programId)) throw Error(`Lost WorkOrder ${item.scenario}`);
    if (String(await balance(new PublicKey(item.escrow_vault))) !== item.final_balances.vault ||
        String(await balance(new PublicKey(item.operator_token_account))) !== item.final_balances.operator) {
      throw Error(`Changed token balance ${item.scenario}`);
    }
  }
  process.stdout.write(`Verified ${report.scenarios.filter(x => x.result === 'FINALIZED').length} finalized transactions after recovery\n`);
}
(action === 'execute' ? execute() : verify()).catch(error => {console.error(error); process.exitCode = 1;});
