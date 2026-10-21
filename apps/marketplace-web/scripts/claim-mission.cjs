const fs = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');

const {
  Connection,
  Keypair,
  PublicKey,
  Transaction,
  TransactionInstruction,
} = require('@solana/web3.js');

const ROOT = path.resolve(__dirname, '../../..');

const RPC = 'http://127.0.0.1:8899';
const API = 'http://127.0.0.1:8787';

const GENESIS =
  'HP9XKTusRPGC78EFDpR9xdEq6simL2vqyDdrMvn6Vacg';

const PROGRAM =
  'CeA1P1NSuPLUH31KsT4j3pZeBsknQZ3NSC6GUAqcsCLy';

const CONFIG =
  'C8HiYzxKjRcDFHoWSZ84smUsxnMQ7ipxPnQ96GK5qZVn';

const AGENT =
  'DcusvnYAdFFKzNDVzUkUvmgZ9fDhzszeRR5Fj8F5dMbB';

const OWNER =
  '8rPDpYsLZxNBm8Q8GKSKki8Ag6dodkasedhUT9x3Ec1D';

const CREATOR =
  '9aA2jeb1Cds7m4VMhYRpGCv9UJzdREZBZAVEYmBxAzeZ';

const DEVICE =
  'C5kqBc9ntqCAqSNDN3ywdK3Hkay29zixMsxrvesQLtnt';

const KEY_FILE = path.join(
  ROOT,
  '.aerosettle-local/drone-a-device.json'
);

const IDL_FILE = path.join(
  ROOT,
  'target/idl/aerosettle.discovery.json'
);

const ACCOUNT_RULES = [
  ['protocol_config', false, false],
  ['work_order', false, true],
  ['agent_account', false, false],
  ['agent_signer', true, false],
];

function assert(condition, message) {
  if (!condition) throw new Error(message);
}

function parseArgs() {
  const args = process.argv.slice(2);

  let workOrder = null;
  let send = false;

  for (let i = 0; i < args.length; i++) {
    if (args[i] === '--work-order') {
      assert(!workOrder, 'WorkOrder duplicada');
      assert(args[i + 1], 'Falta WorkOrder PDA');
      workOrder = args[++i];
    } else if (args[i] === '--send') {
      assert(!send, '--send duplicado');
      send = true;
    } else {
      throw new Error(
        `Argumento desconocido: ${args[i]}`
      );
    }
  }

  assert(
    workOrder,
    'Uso: node claim-mission.cjs ' +
    '--work-order <PDA> [--send]'
  );

  const pubkey = new PublicKey(workOrder);

  assert(
    pubkey.toBase58() === workOrder,
    'WorkOrder PDA inválida'
  );

  return { workOrder, send };
}

function sha256(data) {
  return crypto
    .createHash('sha256')
    .update(data)
    .digest();
}

function validateIdl() {
  const idl = JSON.parse(
    fs.readFileSync(IDL_FILE, 'utf8')
  );

  assert(
    idl.address === PROGRAM,
    'Program ID incompatible con el IDL'
  );

  const instructions = idl.instructions.filter(
    item => item.name === 'claim_work_order'
  );

  assert(
    instructions.length === 1,
    'claim_work_order ausente o duplicada en IDL'
  );

  const ix = instructions[0];

  assert(
    Array.isArray(ix.args) && ix.args.length === 0,
    'Claim tiene argumentos inesperados'
  );

  assert(
    Array.isArray(ix.accounts) &&
    ix.accounts.length === ACCOUNT_RULES.length,
    'Número de cuentas Claim incorrecto'
  );

  for (let i = 0; i < ACCOUNT_RULES.length; i++) {
    const [name, signer, writable] = ACCOUNT_RULES[i];
    const actual = ix.accounts[i];

    assert(
      actual.name === name &&
      Boolean(actual.signer) === signer &&
      Boolean(actual.writable) === writable,
      `AccountMeta incompatible: ${name}`
    );
  }

  const expected = sha256(
    'global:claim_work_order'
  ).subarray(0, 8);

  assert(
    Array.isArray(ix.discriminator) &&
    Buffer.from(ix.discriminator).equals(expected),
    'Discriminador Anchor inconsistente'
  );

  return expected;
}

function loadDevice() {
  assert(
    fs.existsSync(KEY_FILE),
    'No existe la wallet del dispositivo'
  );

  const secret = JSON.parse(
    fs.readFileSync(KEY_FILE, 'utf8')
  );

  assert(
    Array.isArray(secret) &&
    secret.length === 64,
    'Keypair de dispositivo inválido'
  );

  const device = Keypair.fromSecretKey(
    Uint8Array.from(secret)
  );

  assert(
    device.publicKey.toBase58() === DEVICE,
    'La wallet no corresponde a Drone A'
  );

  return device;
}

function decodeAgent(info) {
  assert(
    info && info.owner.toBase58() === PROGRAM,
    'AgentAccount no pertenece al programa'
  );

  const data = Buffer.from(info.data);

  assert(
    data.length >= 196,
    'AgentAccount demasiado pequeña'
  );

  assert(
    data.subarray(0, 8).equals(
      sha256('account:AgentAccount').subarray(0, 8)
    ),
    'Discriminador AgentAccount incorrecto'
  );

  const pubkey = (from, to) =>
    new PublicKey(
      data.subarray(from, to)
    ).toBase58();

  return {
    protocol: pubkey(9, 41),
    owner: pubkey(73, 105),
    signer: pubkey(105, 137),
    capabilities: data.readBigUInt64LE(138),
    raw: data,
  };
}

async function fetchJson(url) {
  const response = await fetch(url, {
    cache: 'no-store',
  });

  assert(
    response.ok,
    `HTTP ${response.status}: ${url}`
  );

  return response.json();
}

async function inspectMission(connection, workOrder) {
  const [orderPayload, agentsPayload] =
    await Promise.all([
      fetchJson(
        `${API}/v1/work-orders/${workOrder}`
      ),
      fetchJson(`${API}/v1/agents`),
    ]);

  const order = orderPayload.data;
  const meta = orderPayload.meta;

  assert(
    meta?.program_id === PROGRAM,
    'Marketplace API usa otro programa'
  );

  assert(
    Number.isSafeInteger(meta.chain_now_unix),
    'Clock on-chain no verificable'
  );

  assert(
    order?.work_order_account === workOrder,
    'WorkOrder incorrecta'
  );

  assert(
    order.creator === CREATOR,
    'La WorkOrder no pertenece a nuestro cliente DEMO'
  );

  assert(
    order.protocol_config === CONFIG,
    'ProtocolConfig inesperada'
  );

  assert(
    order.status === 'Open' &&
    order.is_open === true &&
    order.discoverable === true,
    'La misión no está Open y discoverable'
  );

  assert(
    Number(order.execution_deadline)
      - meta.chain_now_unix > 120,
    'La misión venció o tiene menos de 2 minutos'
  );

  const agents = agentsPayload.data;

  assert(
    agentsPayload.meta?.program_id === PROGRAM &&
    Array.isArray(agents) &&
    agentsPayload.page?.has_more === false,
    'Lista de agentes inválida o incompleta'
  );

  const agent = agents.find(
    item => item.agent_account === AGENT
  );

  assert(
    agent &&
    agent.active === true &&
    agent.status === 'Active',
    'Drone A no está activo'
  );

  assert(
    agent.protocol_config === CONFIG,
    'El agente pertenece a otro protocolo'
  );

  const required = BigInt(
    order.required_capabilities
  );

  const available = BigInt(
    agent.capabilities
  );

  assert(
    required > 0n &&
    (available & required) === required,
    'Las capacidades del dron no cumplen la misión'
  );

  const [configInfo, orderInfo, agentInfo] =
    await Promise.all([
      connection.getAccountInfo(
        new PublicKey(CONFIG), 'confirmed'
      ),
      connection.getAccountInfo(
        new PublicKey(workOrder), 'confirmed'
      ),
      connection.getAccountInfo(
        new PublicKey(AGENT), 'confirmed'
      ),
    ]);

  assert(
    configInfo &&
    configInfo.owner.toBase58() === PROGRAM,
    'ProtocolConfig on-chain inválida'
  );

  assert(
    orderInfo &&
    orderInfo.owner.toBase58() === PROGRAM,
    'WorkOrder on-chain inválida'
  );

  const decoded = decodeAgent(agentInfo);

  assert(
    decoded.protocol === CONFIG &&
    decoded.owner === OWNER &&
    decoded.signer === DEVICE,
    'La autoridad o propietario del dron cambió'
  );

  assert(
    decoded.capabilities === available,
    'Capacidades API / Solana incompatibles'
  );

  return {
    order,
    agent,
    remaining:
      Number(order.execution_deadline) -
      meta.chain_now_unix,
    orderRaw: Buffer.from(orderInfo.data),
    agentRaw: decoded.raw,
  };
}

function makeTransaction(
  device,
  workOrder,
  discriminator,
  blockhash
) {
  const instruction = new TransactionInstruction({
    programId: new PublicKey(PROGRAM),
    keys: [
      {
        pubkey: new PublicKey(CONFIG),
        isSigner: false,
        isWritable: false,
      },
      {
        pubkey: new PublicKey(workOrder),
        isSigner: false,
        isWritable: true,
      },
      {
        pubkey: new PublicKey(AGENT),
        isSigner: false,
        isWritable: false,
      },
      {
        pubkey: device.publicKey,
        isSigner: true,
        isWritable: false,
      },
    ],
    data: discriminator,
  });

  return new Transaction({
    feePayer: device.publicKey,
    recentBlockhash: blockhash,
  }).add(instruction);
}

async function simulate(tx) {
  const raw = tx.serialize({
    requireAllSignatures: false,
    verifySignatures: false,
  });

  const response = await fetch(RPC, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({
      jsonrpc: '2.0',
      id: 1,
      method: 'simulateTransaction',
      params: [
        raw.toString('base64'),
        {
          encoding: 'base64',
          commitment: 'confirmed',
          sigVerify: false,
          replaceRecentBlockhash: false,
        },
      ],
    }),
  });

  assert(
    response.ok,
    `Simulación HTTP ${response.status}`
  );

  const payload = await response.json();

  assert(
    !payload.error,
    JSON.stringify(payload.error)
  );

  const result = payload.result?.value;

  assert(result, 'Simulación sin resultado');

  console.log('\n=== CLAIM SIMULATION LOGS ===');

  for (const line of result.logs || []) {
    console.log(line);
  }

  assert(
    result.err == null,
    'CLAIM SIMULATION FAILED: ' +
      JSON.stringify(result.err)
  );

  console.log('\n✅ CLAIM SIMULATION PASSED');
}

async function main() {
  const { workOrder, send } = parseArgs();

  const connection = new Connection(
    RPC, 'confirmed'
  );

  const genesis = await connection.getGenesisHash();

  assert(
    genesis === GENESIS,
    'Genesis Hash incorrecto'
  );

  const discriminator = validateIdl();
  const device = loadDevice();

  const balance = await connection.getBalance(
    device.publicKey, 'confirmed'
  );

  assert(
    balance >= 100000,
    'Drone A necesita SOL para pagar la comisión'
  );

  const before = await inspectMission(
    connection, workOrder
  );

  console.log('=== AEROSETTLE AGENT CLAIM ===');
  console.log('Mode:', send ? 'SEND' : 'SIMULATE ONLY');
  console.log('WorkOrder:', workOrder);
  console.log('Agent:', AGENT);
  console.log('Device:', DEVICE);
  console.log('Owner:', OWNER);
  console.log('Required:',
    before.order.required_capabilities);
  console.log('Available:',
    before.agent.capabilities);
  console.log('Remaining seconds:', before.remaining);

  const latest = await connection.getLatestBlockhash(
    'confirmed'
  );

  const tx = makeTransaction(
    device,
    workOrder,
    discriminator,
    latest.blockhash
  );

  await simulate(tx);

  if (!send) {
    console.log('\n✅ CLAIM PREFLIGHT APPROVED');
    console.log('Transactions sent: 0');
    console.log('Para Claim: repite con --send');
    return;
  }

  // Segunda auditoría antes de modificar estado.
  const fresh = await inspectMission(
    connection, workOrder
  );

  assert(
    fresh.orderRaw.equals(before.orderRaw) &&
    fresh.agentRaw.equals(before.agentRaw),
    'Cambió WorkOrder o AgentAccount. Repite preflight.'
  );

  const height = await connection.getBlockHeight(
    'confirmed'
  );

  const valid = await connection.isBlockhashValid(
    latest.blockhash,
    { commitment: 'confirmed' }
  );

  assert(
    valid.value &&
    height < latest.lastValidBlockHeight - 8,
    'Blockhash por vencer. Repite el comando.'
  );

  tx.sign(device);

  assert(
    tx.verifySignatures(true),
    'Firma de Drone A inválida'
  );

  console.log('\n=== SENDING CLAIM ===');

  let mayHaveSent = false;
  let signature;

  try {
    mayHaveSent = true;

    signature = await connection.sendRawTransaction(
      tx.serialize(),
      {
        skipPreflight: false,
        preflightCommitment: 'confirmed',
        maxRetries: 2,
      }
    );

    console.log('Signature:', signature);

    const confirmation =
      await connection.confirmTransaction(
        {
          signature,
          blockhash: latest.blockhash,
          lastValidBlockHeight:
            latest.lastValidBlockHeight,
        },
        'confirmed'
      );

    assert(
      confirmation.value.err == null,
      'Claim confirmó con error: ' +
        JSON.stringify(confirmation.value.err)
    );

    const after = await fetchJson(
      `${API}/v1/work-orders/${workOrder}`
    );

    assert(
      after.data?.status === 'Claimed',
      'La transacción confirmó, pero Claim no se ' +
        'refleja como Claimed en Marketplace API'
    );

    if (after.data.claimed_agent != null) {
      assert(
        after.data.claimed_agent === AGENT,
        'La WorkOrder fue reclamada por otro agente'
      );
    }

    console.log('\n✅ CLAIM CONFIRMADO ON-CHAIN');
    console.log('WorkOrder status: Claimed');
    console.log('Agent:', AGENT);
    console.log('Device signer:', DEVICE);
    console.log('Economic beneficiary:', OWNER);
    console.log('Signature:', signature);

  } catch (error) {
    if (mayHaveSent) {
      console.error(
        '⚠️ Claim pudo haberse transmitido. ' +
        'Consulta la WorkOrder antes de reintentar.'
      );

      if (signature) {
        console.error(
          'Signature:', signature
        );
      }
    }

    throw error;
  }
}

main().catch(error => {
  console.error('\n❌', error.message);
  process.exitCode = 1;
});
