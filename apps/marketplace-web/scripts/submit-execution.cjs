'use strict';
const fs = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');
const { spawnSync } = require('node:child_process');
const {
  Connection, Keypair, PublicKey, Transaction, TransactionInstruction,
} = require('@solana/web3.js');

const ROOT = path.resolve(__dirname, '../../..');
const RPC = 'http://127.0.0.1:8899';
const API = 'http://127.0.0.1:8787';
const GENESIS = 'HP9XKTusRPGC78EFDpR9xdEq6simL2vqyDdrMvn6Vacg';
const PROGRAM = 'CeA1P1NSuPLUH31KsT4j3pZeBsknQZ3NSC6GUAqcsCLy';
const CONFIG = 'C8HiYzxKjRcDFHoWSZ84smUsxnMQ7ipxPnQ96GK5qZVn';
const AGENT = 'DcusvnYAdFFKzNDVzUkUvmgZ9fDhzszeRR5Fj8F5dMbB';
const OWNER = '8rPDpYsLZxNBm8Q8GKSKki8Ag6dodkasedhUT9x3Ec1D';
const DEVICE = 'C5kqBc9ntqCAqSNDN3ywdK3Hkay29zixMsxrvesQLtnt';
const KEY_FILE = path.join(ROOT, '.aerosettle-local/drone-a-device.json');
const IDL_FILE = path.join(ROOT, 'target/idl/aerosettle.discovery.json');
const GATE_FILE = path.join(ROOT, '.aerosettle-local/execution-gate.json');
const EVIDENCE_DIR = path.join(ROOT, '.aerosettle-local/evidence');
const EXPECTED_FIELDS = [
  ['execution_receipt_hash', 'u8x32'],
  ['evidence_manifest_hash', 'u8x32'],
  ['provided_evidence', 'u64'],
  ['execution_started_at', 'i64'],
  ['execution_ended_at', 'i64'],
  ['signature_sequence', 'u64'],
];
function check(ok, message) { if (!ok) throw Error(message); }
function argMode() {
  const argv = process.argv.slice(2);
  let order = null, mode = 'simulate';
  for (let i = 0; i < argv.length; i++) {
    if (argv[i] === '--work-order') {
      check(!order && argv[i + 1], 'Falta --work-order PDA');
      order = argv[++i];
    } else if (argv[i] === '--prepare' || argv[i] === '--send') {
      check(mode === 'simulate', 'Modos excluyentes');
      mode = argv[i].substring(2);
    } else throw Error(`Argumento desconocido: ${argv[i]}`);
  }
  check(order, 'Uso: node submit-execution.cjs --work-order <PDA> [--prepare|--send]');
  check(new PublicKey(order).toBase58() === order, 'WorkOrder inválida');
  return { order, mode };
}
const sha256 = bytes => crypto.createHash('sha256').update(bytes).digest();
function stable(value) {
  if (Array.isArray(value)) return value.map(stable);
  if (value && typeof value === 'object') return Object.fromEntries(
    Object.keys(value).sort().map(k => [k, stable(value[k])])
  );
  return value;
}
function canonicalBytes(value) { return Buffer.from(JSON.stringify(stable(value)), 'utf8'); }
function hashHex(obj) { return sha256(canonicalBytes(obj)).toString('hex'); }
function loadDevice() {
  const bytes = JSON.parse(fs.readFileSync(KEY_FILE, 'utf8'));
  check(Array.isArray(bytes) && bytes.length === 64, 'Keypair del dron inválido');
  const key = Keypair.fromSecretKey(Uint8Array.from(bytes));
  check(key.publicKey.toBase58() === DEVICE, 'No es la wallet de Drone A');
  return key;
}
function validateIdl() {
  const idl = JSON.parse(fs.readFileSync(IDL_FILE, 'utf8'));
  check(idl.address === PROGRAM, 'IDL Program ID incorrecto');
  const all = idl.instructions.filter(ix => ix.name === 'submit_execution');
  check(all.length === 1, 'submit_execution ausente o duplicada');
  const ix = all[0];
  const accounts = [
    ['protocol_config', false, false],
    ['work_order', false, true],
    ['agent_account', false, true],
    ['agent_signer', true, false],
  ];
  check(ix.accounts.length === accounts.length, 'Cantidad de cuentas IDL inesperada');
  for (let n = 0; n < accounts.length; n++) {
    const [name, signer, writable] = accounts[n], actual = ix.accounts[n];
    check(actual.name === name && Boolean(actual.signer) === signer &&
      Boolean(actual.writable) === writable, `AccountMeta inválida: ${name}`);
  }
  check(ix.args.length === 1 && ix.args[0].name === 'args', 'Args inesperados');
  check(ix.args[0].type?.defined?.name === 'aerosettle::execution::SubmitExecutionArgs',
    'Tipo SubmitExecutionArgs inesperado');
  const def = idl.types.filter(t => t.name === 'aerosettle::execution::SubmitExecutionArgs');
  check(def.length === 1 && def[0].type?.kind === 'struct', 'Tipo Borsh no encontrado');
  const fields = def[0].type.fields;
  check(fields.length === EXPECTED_FIELDS.length, 'Longitud de SubmitExecutionArgs inválida');
  for (let i = 0; i < fields.length; i++) {
    const [name, type] = EXPECTED_FIELDS[i];
    const found = fields[i];
    check(found.name === name, `Orden de Borsh incorrecto: ${name}`);
    if (type === 'u8x32') {
      check(JSON.stringify(found.type) === JSON.stringify({ array: ['u8', 32] }),
        `Tipo incorrecto ${name}`);
    } else check(found.type === type, `Tipo incorrecto ${name}`);
  }
  const disc = sha256(Buffer.from('global:submit_execution')).subarray(0, 8);
  check(Buffer.from(ix.discriminator).equals(disc), 'Discriminador Anchor incompatible');
  return disc;
}
function liveGate(order) {
  const run = spawnSync('python3.11', ['tools/execution/submission_gate.py'], {
    cwd: ROOT, env: { ...process.env, AEROSETTLE_WORK_ORDER: order },
    encoding: 'utf8', timeout: 30000, maxBuffer: 1024 * 1024,
  });
  check(run.status === 0, `Submission Gate falló:\n${run.stderr}\n${run.stdout}`);
  const gate = JSON.parse(fs.readFileSync(GATE_FILE, 'utf8'));
  check(gate.genesis === GENESIS && gate.work_order === order &&
    gate.agent === AGENT && gate.device === DEVICE,
    'El Submission Gate no corresponde a esta misión o red');
  check(gate.execution_window_open && gate.submission_window_open,
    'Ventana de ejecución/submission vencida: crear nueva WorkOrder de desarrollo');
  check(Number.isSafeInteger(gate.chain_now) && Number.isSafeInteger(gate.claimed_at),
    'Reloj de la cadena no verificable');
  check(typeof gate.evidence_requirements === 'number' &&
    Number.isSafeInteger(gate.evidence_requirements) && gate.evidence_requirements > 0,
    'evidence_requirements no está en el reporte del Gate');
  check(Number.isSafeInteger(gate.next_signature_sequence), 'Secuencia no verificable');
  const gateFields = gate.submit_execution_fields;

  check(
    Array.isArray(gateFields) &&
    gateFields.length === EXPECTED_FIELDS.length,
    'Submission Gate: cantidad de campos Borsh inesperada'
  );

  for (let i = 0; i < EXPECTED_FIELDS.length; i++) {
    const [name, type] = EXPECTED_FIELDS[i];
    const field = gateFields[i];

    check(
      field && field.name === name,
      `Submission Gate: campo Borsh ${i + 1} incorrecto; esperado ${name}`
    );

    if (type === 'u8x32') {
      const array = field.type?.array;

      check(
        Array.isArray(array) &&
        array.length === 2 &&
        array[0] === 'u8' &&
        array[1] === 32,
        `Submission Gate: ${name} debe ser [u8; 32]`
      );
    } else {
      check(
        field.type === type,
        `Submission Gate: tipo incorrecto para ${name}, esperado ${type}`
      );
    }
  }
  return gate;
}
function paths(order) {
  return {
    manifest: path.join(EVIDENCE_DIR, `${order}.demo-manifest.json`),
    receipt: path.join(EVIDENCE_DIR, `${order}.demo-receipt.json`),
  };
}
function prepare(order, gate) {
  check(gate.chain_now >= gate.claimed_at && gate.chain_now <= gate.execution_deadline,
    'No se puede iniciar ahora una ejecución sintética dentro del plazo');
  fs.mkdirSync(EVIDENCE_DIR, { recursive: true, mode: 0o700 });
  const files = paths(order);
  check(!fs.existsSync(files.manifest) && !fs.existsSync(files.receipt),
    'Los archivos de evidencia ya existen; no se sobrescribirán');
  const bits = [];
  let mask = BigInt(gate.evidence_requirements);
  for (let bit = 0; bit < 64; bit++) {
    if ((mask & (1n << BigInt(bit))) !== 0n) bits.push(bit);
  }
  const manifest = {
    schema_version: 'aerosettle.evidence.synthetic.v1',
    network: 'localnet',
    execution_mode: 'SYNTHETIC_INTEGRATION_TEST',
    is_physical_execution: false,
    work_order: order,
    agent_account: AGENT,
    device_signing_authority: DEVICE,
    provided_evidence: mask.toString(),
    evidence_entries: bits.map(bit => ({
      requirement_bit: bit,
      source: 'SYNTHETIC_TEST_FIXTURE',
      physical_measurement: null,
      real_artifact: null,
      note: 'Marker de prueba; no constituye evidencia física',
    })),
    execution_started_at: gate.chain_now,
    execution_ended_at: gate.chain_now,
    note: 'Fechas corresponden a la creación del fixture, no a una inspección real',
  };
  const manifest_hash = hashHex(manifest);
  const receipt = {
    schema_version: 'aerosettle.execution-receipt.synthetic.v1',
    network: 'localnet',
    execution_mode: 'SYNTHETIC_INTEGRATION_TEST',
    work_order: order,
    agent_account: AGENT,
    device_signing_authority: DEVICE,
    evidence_manifest_sha256: manifest_hash,
    provided_evidence: mask.toString(),
    execution_started_at: manifest.execution_started_at,
    execution_ended_at: manifest.execution_ended_at,
    signature_sequence: String(gate.next_signature_sequence),
  };
  fs.writeFileSync(files.manifest, JSON.stringify(manifest, null, 2) + '\n', { flag: 'wx', mode: 0o600 });
  fs.writeFileSync(files.receipt, JSON.stringify(receipt, null, 2) + '\n', { flag: 'wx', mode: 0o600 });
  console.log('✅ Expediente DEMO preparado (datos sintéticos, no sensores reales)');
  console.log('Manifest:', files.manifest);
  console.log('Manifest hash:', manifest_hash);
  console.log('Receipt:', files.receipt);
  console.log('Receipt hash:', hashHex(receipt));
  console.log('Evidence mask:', mask.toString(), 'bits:', bits.join(', '));
  console.log('Execution time:', gate.chain_now);
  console.log('Transactions sent: 0');
}
function loadPrepared(order, gate) {
  const files = paths(order);
  const manifest = JSON.parse(fs.readFileSync(files.manifest, 'utf8'));
  const receipt = JSON.parse(fs.readFileSync(files.receipt, 'utf8'));
  check(manifest.network === 'localnet' && receipt.network === 'localnet' &&
    manifest.execution_mode === 'SYNTHETIC_INTEGRATION_TEST' &&
    receipt.execution_mode === 'SYNTHETIC_INTEGRATION_TEST' &&
    manifest.is_physical_execution === false,
    'Este script sólo permite fixtures sintéticos Localnet');
  check(manifest.work_order === order && receipt.work_order === order &&
    manifest.agent_account === AGENT && receipt.agent_account === AGENT &&
    manifest.device_signing_authority === DEVICE && receipt.device_signing_authority === DEVICE,
    'La evidencia no corresponde a WorkOrder / Agent / dispositivo');
  const manifestHash = hashHex(manifest);
  const receiptHash = hashHex(receipt);
  check(receipt.evidence_manifest_sha256 === manifestHash, 'Hashes de manifiesto inconsistentes');
  check(receipt.provided_evidence === manifest.provided_evidence &&
    receipt.execution_started_at === manifest.execution_started_at &&
    receipt.execution_ended_at === manifest.execution_ended_at,
    'Tiempos/máscara no coinciden entre manifiesto y recibo');
  const provided = BigInt(receipt.provided_evidence);
  const required = BigInt(gate.evidence_requirements);
  check(provided > 0n && (provided & required) === required,
    'Evidencia no cubre la máscara requerida');
  const seq = BigInt(receipt.signature_sequence);
  check(seq === BigInt(gate.next_signature_sequence), 'La secuencia ya cambió: no reintentar');
  const started = BigInt(receipt.execution_started_at);
  const ended = BigInt(receipt.execution_ended_at);
  check(started >= BigInt(gate.claimed_at) && started <= ended &&
    ended <= BigInt(gate.execution_deadline) && ended <= BigInt(gate.chain_now) &&
    BigInt(gate.chain_now) <= BigInt(gate.verification_deadline),
    'Tiempos no satisfacen las restricciones on-chain');
  check(/^[a-f0-9]{64}$/.test(manifestHash) && /^[a-f0-9]{64}$/.test(receiptHash),
    'Hashes SHA-256 inválidos');
  return { manifestHash, receiptHash, provided, started, ended, seq };
}
function borshArgs(evidence, discriminator) {
  const u64 = number => { const b = Buffer.alloc(8); b.writeBigUInt64LE(number); return b; };
  const i64 = number => { const b = Buffer.alloc(8); b.writeBigInt64LE(number); return b; };
  const data = Buffer.concat([
    discriminator,
    Buffer.from(evidence.receiptHash, 'hex'),
    Buffer.from(evidence.manifestHash, 'hex'),
    u64(evidence.provided),
    i64(evidence.started),
    i64(evidence.ended),
    u64(evidence.seq),
  ]);
  check(data.length === 104, 'Layout Borsh de 104 bytes inesperado');
  return data;
}
async function simulateSigned(tx) {
  const response = await fetch(RPC, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      jsonrpc: '2.0', id: 1, method: 'simulateTransaction',
      params: [tx.serialize().toString('base64'), {
        encoding: 'base64', commitment: 'confirmed',
        sigVerify: true, replaceRecentBlockhash: false,
      }],
    }),
  });
  check(response.ok, `Error de simulación HTTP ${response.status}`);
  const body = await response.json();
  check(!body.error, `RPC simulation error: ${JSON.stringify(body.error)}`);
  const output = body.result?.value;
  check(output, 'Sin resultado de simulación');
  console.log('=== SUBMIT EXECUTION SIMULATION LOGS ===');
  for (const line of output.logs || []) console.log(line);
  check(output.err == null, `Simulación de Submission fallida: ${JSON.stringify(output.err)}`);
  console.log('✅ SUBMISSION SIMULATION PASSED');
}
async function fetchOrderStatus(order) {
  const response = await fetch(`${API}/v1/work-orders/${order}`, { cache: 'no-store' });
  check(response.ok, `Marketplace API error ${response.status}`);
  const body = await response.json();
  check(body.meta?.program_id === PROGRAM && body.data?.work_order_account === order,
    'Respuesta Marketplace API inconsistente');
  return body.data.status;
}
async function main() {
  const { order, mode } = argMode();
  const connection = new Connection(RPC, 'confirmed');
  check(await connection.getGenesisHash() === GENESIS, 'Genesis de red incorrecto');
  const discriminator = validateIdl();
  const device = loadDevice();
  const gate = liveGate(order);
  check(gate.next_signature_sequence >= 0, 'Secuencia negativa');
  const deviceBalance = await connection.getBalance(device.publicKey, 'confirmed');
  check(deviceBalance >= 100000, 'Drone A no tiene SOL suficiente para comisiones');
  console.log(`=== AEROSETTLE SUBMIT EXECUTION (${mode.toUpperCase()}) ===`);
  console.log('WorkOrder:', order, 'Agent:', AGENT);
  console.log('Chain time:', gate.chain_now);
  console.log('Execution deadline:', gate.execution_deadline);
  console.log('Verification deadline:', gate.verification_deadline);
  console.log('Required evidence:', gate.evidence_requirements);
  console.log('Next sequence:', gate.next_signature_sequence);
  if (mode === 'prepare') return prepare(order, gate);
  const evidence = loadPrepared(order, gate);
  const agentInfo = await connection.getAccountInfo(new PublicKey(AGENT), 'confirmed');
  check(agentInfo && agentInfo.owner.toBase58() === PROGRAM, 'AgentAccount inválido');
  const agentRaw = Buffer.from(agentInfo.data);
  check(agentRaw.length >= 196 &&
    agentRaw.subarray(0, 8).equals(sha256('account:AgentAccount').subarray(0, 8)),
    'Discriminador o longitud de AgentAccount inválidos');
  check(new PublicKey(agentRaw.subarray(73, 105)).toBase58() === OWNER &&
    new PublicKey(agentRaw.subarray(105, 137)).toBase58() === DEVICE,
    'Owner o Signing Authority del agente cambió');
  check(agentRaw.readBigUInt64LE(179) === evidence.seq,
    'Nonce on-chain difiere de Submission Gate');
  const [configInfo, orderInfo] = await Promise.all([
    connection.getAccountInfo(new PublicKey(CONFIG), 'confirmed'),
    connection.getAccountInfo(new PublicKey(order), 'confirmed'),
  ]);
  check(configInfo?.owner.toBase58() === PROGRAM && orderInfo?.owner.toBase58() === PROGRAM,
    'Cuentas de protocolo incorrectas');
  const beforeOrder = Buffer.from(orderInfo.data);
  const latest = await connection.getLatestBlockhash('confirmed');
  const transaction = new Transaction({ feePayer: device.publicKey, recentBlockhash: latest.blockhash }).add(
    new TransactionInstruction({
      programId: new PublicKey(PROGRAM),
      keys: [
        { pubkey: new PublicKey(CONFIG), isSigner: false, isWritable: false },
        { pubkey: new PublicKey(order), isSigner: false, isWritable: true },
        { pubkey: new PublicKey(AGENT), isSigner: false, isWritable: true },
        { pubkey: device.publicKey, isSigner: true, isWritable: false },
      ],
      data: borshArgs(evidence, discriminator),
    })
  );
  transaction.sign(device);
  check(transaction.verifySignatures(true), 'Firma de Drone A inválida');
  await simulateSigned(transaction);
  if (mode !== 'send') {
    console.log('✅ PREFLIGHT APPROVED, no transactions sent');
    console.log('To submit, rerun with --send');
    return;
  }
  // Guard close to send: fresh on-chain status, sequence, clock.
  const latestGate = liveGate(order);
  loadPrepared(order, latestGate);
  const [freshOrder, freshAgent] = await Promise.all([
    connection.getAccountInfo(new PublicKey(order), 'confirmed'),
    connection.getAccountInfo(new PublicKey(AGENT), 'confirmed'),
  ]);
  check(freshOrder && freshAgent && Buffer.from(freshOrder.data).equals(beforeOrder) &&
    Buffer.from(freshAgent.data).equals(agentRaw),
    'WorkOrder o agente cambiaron desde preflight');
  check((await connection.isBlockhashValid(latest.blockhash, 'confirmed')).value,
    'Blockhash expiró. Vuelve a ejecutar.');
  let signature = null;
  try {
    signature = await connection.sendRawTransaction(transaction.serialize(), {
      skipPreflight: false, preflightCommitment: 'confirmed', maxRetries: 2,
    });
    console.log('Signature:', signature);
    const confirmation = await connection.confirmTransaction({
      signature,
      blockhash: latest.blockhash,
      lastValidBlockHeight: latest.lastValidBlockHeight,
    }, 'confirmed');
    check(confirmation.value.err == null,
      `Transacción con error: ${JSON.stringify(confirmation.value.err)}`);
    const [status, newAgent, newOrder] = await Promise.all([
      fetchOrderStatus(order),
      connection.getAccountInfo(new PublicKey(AGENT), 'confirmed'),
      connection.getAccountInfo(new PublicKey(order), 'confirmed'),
    ]);
    check(status === 'Submitted', `API indica ${status} en lugar de Submitted`);
    check(newAgent && newOrder, 'Cuentas desaparecieron tras enviar');
    check(Buffer.from(newAgent.data).readBigUInt64LE(179) === evidence.seq + 1n,
      'Secuencia del agente no incrementó');
    check(!Buffer.from(newOrder.data).equals(beforeOrder),
      'WorkOrder no cambió');
    console.log('✅ SUBMISSION CONFIRMADA ON-CHAIN');
    console.log('Status: Submitted');
    console.log('Agent sequence:', (evidence.seq + 1n).toString());
    console.log('Evidence manifest SHA-256:', evidence.manifestHash);
    console.log('Execution receipt SHA-256:', evidence.receiptHash);
    console.log('Signature:', signature);
  } catch (error) {
    console.error('⚠️ Submission pudo haberse transmitido; consultar estado antes de reintentar.');
    if (signature) console.error('Signature:', signature);
    throw error;
  }
}
main().catch(error => { console.error('❌', error.message); process.exitCode = 1; });
