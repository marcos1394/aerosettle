'use strict';

const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const crypto = require('node:crypto');
const {execFileSync} = require('node:child_process');

const {
  Connection, Keypair, PublicKey, Transaction,
  TransactionInstruction, sendAndConfirmTransaction,
  SYSVAR_CLOCK_PUBKEY,
} = require('@solana/web3.js');

const {
  getAccount, TOKEN_PROGRAM_ID
} = require('@solana/spl-token');

const RPC = 'http://127.0.0.1:8899';

const PROGRAM =
  'CeA1P1NSuPLUH31KsT4j3pZeBsknQZ3NSC6GUAqcsCLy';

const GENESIS =
  'HP9XKTusRPGC78EFDpR9xdEq6simL2vqyDdrMvn6Vacg';

const ORDER_TAG =
  process.env.AEROSETTLE_ORDER_TAG || 'v1';

const mode = process.argv[2] || '--inspect';

const modes = [
  '--inspect',
  '--negative',
  '--claim',
  '--verify'
];

if (!modes.includes(mode)) {
  throw Error(`Modo inválido: ${mode}`);
}

if (!/^[a-zA-Z0-9_-]{1,40}$/.test(ORDER_TAG)) {
  throw Error('AEROSETTLE_ORDER_TAG inválido');
}

const idl = JSON.parse(
  fs.readFileSync(
    'target/idl/aerosettle.discovery.json',
    'utf8'
  )
);

if (idl.address !== PROGRAM) {
  throw Error('IDL Program ID incorrecto');
}

const short = s => String(s)
  .split('::')
  .at(-1)
  .replace(/[^a-z0-9]/gi, '')
  .toLowerCase();

const findOne = (xs, name) => {
  const found = xs.filter(
    x => short(x.name) === short(name)
  );

  if (found.length !== 1) {
    throw Error(
      `IDL: ${name} tiene ${found.length} definiciones`
    );
  }

  return found[0];
};

const bytes8 = entry => {
  const xs = entry.discriminator;

  if (
    !Array.isArray(xs) ||
    xs.length !== 8 ||
    xs.some(x =>
      !Number.isInteger(x) || x < 0 || x > 255
    )
  ) {
    throw Error(
      `Discriminador IDL inválido: ${entry.name}`
    );
  }

  return Buffer.from(xs);
};

const hash = s => crypto
  .createHash('sha256')
  .update(s)
  .digest();

const programId = new PublicKey(PROGRAM);

const connection = new Connection(
  RPC, 'confirmed'
);

const wallet = Keypair.fromSecretKey(
  Uint8Array.from(
    JSON.parse(
      fs.readFileSync(
        path.join(
          os.homedir(),
          '.config/solana/id.json'
        ),
        'utf8'
      )
    )
  )
);

const ix = findOne(
  idl.instructions,
  'claim_work_order'
);

const orderSchema = findOne(
  idl.accounts,
  'WorkOrderAccount'
);

const agentSchema = findOne(
  idl.accounts,
  'AgentAccount'
);

if (
  !Array.isArray(ix.args) ||
  ix.args.length !== 0
) {
  throw Error(
    'claim_work_order requiere argumentos no contemplados'
  );
}

const expectedAccounts = [
  'protocol_config',
  'work_order',
  'agent_account',
  'agent_signer'
];

if (
  !Array.isArray(ix.accounts) ||
  ix.accounts.length !== 4 ||
  ix.accounts.some(a => Array.isArray(a.accounts)) ||
  expectedAccounts.some(n =>
    ix.accounts.filter(
      a => short(a.name) === short(n)
    ).length !== 1
  )
) {
  throw Error(
    'IDL ClaimWorkOrder incompatible: ' +
    JSON.stringify(ix.accounts)
  );
}

function readDevice(name, namespace) {
  const location = path.join(
    '.aerosettle-local',
    'bootstrap',
    'keys',
    `${name}-${namespace}.json`
  );

  if (!fs.existsSync(location)) {
    throw Error(
      `Falta la clave local de ${name}: ${location}`
    );
  }

  const content = JSON.parse(
    fs.readFileSync(location, 'utf8')
  );

  if (
    !Array.isArray(content) ||
    content.length !== 64 ||
    content.some(v =>
      !Number.isInteger(v) || v < 0 || v > 255
    )
  ) {
    throw Error(`Keypair corrupto: ${name}`);
  }

  return Keypair.fromSecretKey(
    Uint8Array.from(content)
  );
}

function buildInstruction(
  config, order, agent, device
) {
  const mapping = {
    protocolconfig: config,
    workorder: order,
    agentaccount: agent,
    agentsigner: device.publicKey,
  };

  const keys = ix.accounts.map(a => {
    const pubkey = mapping[short(a.name)];

    if (
      !pubkey ||
      (
        a.address &&
        a.address !== pubkey.toBase58()
      )
    ) {
      throw Error(
        `Cuenta incorrecta en IDL: ${a.name}`
      );
    }

    return {
      pubkey,
      isSigner: Boolean(
        a.signer ?? a.isSigner
      ),
      isWritable: Boolean(
        a.writable ?? a.isMut
      ),
    };
  });

  const signerMeta = keys.find(
    a => a.pubkey.equals(device.publicKey)
  );

  const orderMeta = keys.find(
    a => a.pubkey.equals(order)
  );

  if (
    !signerMeta?.isSigner ||
    !orderMeta?.isWritable ||
    keys.some(
      a => a.isSigner &&
      !a.pubkey.equals(device.publicKey)
    )
  ) {
    throw Error(
      'Metadatos de firma/escritura incompatibles'
    );
  }

  return new TransactionInstruction({
    programId,
    keys,
    data: bytes8(ix),
  });
}

async function simulateClaim(instruction, device) {
  const latest = await connection.getLatestBlockhash(
    'confirmed'
  );

  const transaction = new Transaction({
    feePayer: wallet.publicKey,
    recentBlockhash: latest.blockhash,
  }).add(instruction);

  return (
    await connection.simulateTransaction(
      transaction,
      [wallet, device]
    )
  ).value;
}

function dumpLogs(result) {
  console.log(
    'Simulation error:',
    JSON.stringify(result.err)
  );

  for (const line of result.logs || []) {
    console.log('  ' + line);
  }
}

function captureState() {
  const file =
    '.aerosettle-local/discovery-claim.json';

  execFileSync(
    'python3.11',
    [
      'tools/discovery/agent_discovery.py',
      '--rpc-url', RPC,
      '--idl',
      'target/idl/aerosettle.discovery.json',
      '--commitment', 'confirmed',
      '--output', file,
    ],
    {stdio: 'inherit'}
  );

  return JSON.parse(
    fs.readFileSync(file, 'utf8')
  );
}

async function main() {
  if (
    (await connection.getGenesisHash()) !== GENESIS
  ) {
    throw Error(
      'Genesis inesperado: comprueba el ledger'
    );
  }

  const deployed = await connection.getAccountInfo(
    programId, 'confirmed'
  );

  if (!deployed?.executable) {
    throw Error('Programa no desplegado');
  }

  const [configPda] =
    PublicKey.findProgramAddressSync(
      [Buffer.from('protocol_config')],
      programId
    );

  const configInfo = await connection.getAccountInfo(
    configPda, 'confirmed'
  );

  if (
    !configInfo ||
    !configInfo.owner.equals(programId)
  ) {
    throw Error('ProtocolConfig no válido');
  }

  const owner = wallet.publicKey.toBase58();

  const orderId = hash(
    `aerosettle:inspection:order:${ORDER_TAG}:${GENESIS}:${owner}`
  );

  const [orderPda] =
    PublicKey.findProgramAddressSync(
      [
        Buffer.from('work_order'),
        configPda.toBuffer(),
        wallet.publicKey.toBuffer(),
        orderId,
      ],
      programId
    );

  const [vaultPda] =
    PublicKey.findProgramAddressSync(
      [
        Buffer.from('escrow'),
        orderPda.toBuffer(),
      ],
      programId
    );

  const namespace = hash(
    `${GENESIS}:${owner}`
  ).toString('hex').slice(0, 16);

  const agents = {};

  for (const name of ['drone-a', 'sensor-b']) {
    const agentId = hash(
      `aerosettle:bootstrap:agent:v1:${GENESIS}:${owner}:${name}`
    );

    const [pda] =
      PublicKey.findProgramAddressSync(
        [
          Buffer.from('agent'),
          configPda.toBuffer(),
          agentId,
        ],
        programId
      );

    const device = readDevice(
      name, namespace
    );

    const info = await connection.getAccountInfo(
      pda, 'confirmed'
    );

    if (
      !info ||
      !info.owner.equals(programId) ||
      !info.data.subarray(0, 8).equals(
        bytes8(agentSchema)
      )
    ) {
      throw Error(
        `AgentAccount inválida: ${name}`
      );
    }

    agents[name] = {pda, device};
  }

  const rawOrder = await connection.getAccountInfo(
    orderPda, 'confirmed'
  );

  if (
    !rawOrder ||
    !rawOrder.owner.equals(programId) ||
    !rawOrder.data.subarray(0, 8).equals(
      bytes8(orderSchema)
    )
  ) {
    throw Error(
      `No existe WorkOrder válida para ${ORDER_TAG}`
    );
  }

  const state = captureState();

  const order = state.work_orders.find(
    item =>
      item.work_order_account ===
      orderPda.toBase58()
  );

  if (!order) {
    throw Error(
      'La WorkOrder no aparece en Discovery'
    );
  }

  const clock = await connection.getAccountInfo(
    SYSVAR_CLOCK_PUBKEY,
    'confirmed'
  );

  if (
    !clock ||
    clock.data.length < 40
  ) {
    throw Error('Clock sysvar inválida');
  }

  const nowUnix = clock.data.readBigInt64LE(32);

  const deadline = BigInt(
    String(order.execution_deadline)
  );

  const secondsRemaining =
    deadline - nowUnix;

  console.log('\n=== AEROSETTLE CLAIM ===');

  console.log(
    'Modo:', mode,
    '| Orden:', ORDER_TAG
  );

  console.log(
    'WorkOrder PDA:', orderPda.toBase58()
  );

  console.log(
    'Drone PDA:',
    agents['drone-a'].pda.toBase58()
  );

  console.log(
    'Sensor PDA:',
    agents['sensor-b'].pda.toBase58()
  );

  console.log(
    'Estado:', order.status,
    '| Segundos restantes:',
    secondsRemaining.toString()
  );

  if (mode === '--verify') {
    if (
      order.status !== 'Claimed' ||
      order.is_open
    ) {
      throw Error(
        'WorkOrder todavía no está Claimed'
      );
    }

    const vault = await getAccount(
      connection,
      vaultPda,
      'confirmed',
      TOKEN_PROGRAM_ID
    );

    if (
      vault.amount !== 10_000_000n ||
      !vault.owner.equals(vaultPda)
    ) {
      throw Error(
        'Escrow cambió inesperadamente después del claim'
      );
    }

    console.log(
      '✅ WorkOrder Claimed confirmada en RPC'
    );

    console.log(
      '✅ Escrow intacto: 10 tokens'
    );

    return;
  }

  if (order.status === 'Claimed') {
    console.log(
      'Orden ya Claimed. Usa --verify.'
    );
    return;
  }

  if (
    state.protocol_paused ||
    order.status !== 'Open' ||
    !order.is_open
  ) {
    throw Error(
      'La orden no está Open o el protocolo está pausado'
    );
  }

  if (secondsRemaining <= 0n) {
    throw Error(
      'WORKORDER_EXPIRADA: crea una nueva orden antes del claim'
    );
  }

  const eligible =
    state.eligible_agents_by_order[
      orderPda.toBase58()
    ] || [];

  if (
    eligible.length !== 1 ||
    eligible[0] !==
      agents['drone-a'].pda.toBase58() ||
    !state.agents.some(a =>
      a.agent_account ===
        agents['sensor-b'].pda.toBase58() &&
      a.active
    )
  ) {
    throw Error(
      'El matching no selecciona únicamente al Drone A'
    );
  }

  if (mode === '--inspect') {
    console.log(
      '✅ IDL, agentes, dispositivos y ventana verificados'
    );
    return;
  }

  // NEGATIVE TEST: Sensor B
  const sensorIx = buildInstruction(
    configPda,
    orderPda,
    agents['sensor-b'].pda,
    agents['sensor-b'].device
  );

  const negative = await simulateClaim(
    sensorIx,
    agents['sensor-b'].device
  );

  if (negative.err === null) {
    throw Error(
      'FALLO CRÍTICO: el sensor pudo reclamar en simulación'
    );
  }

  dumpLogs(negative);

  const allLogs =
    (negative.logs || []).join(' ');

  if (
    !/capabilit|incompat|eligib|matching|required/i.test(
      allLogs
    )
  ) {
    throw Error(
      'El sensor fue rechazado, pero no se confirmó ' +
      'que fuera por capacidades. Revisa los logs.'
    );
  }

  console.log(
    '✅ Sensor B rechazado por incompatibilidad'
  );

  if (mode === '--negative') {
    return;
  }

  // POSITIVE TEST: Drone A
  const droneIx = buildInstruction(
    configPda,
    orderPda,
    agents['drone-a'].pda,
    agents['drone-a'].device
  );

  const positive = await simulateClaim(
    droneIx,
    agents['drone-a'].device
  );

  if (positive.err !== null) {
    dumpLogs(positive);

    throw Error(
      'La simulación del dron falló. No se envió transacción.'
    );
  }

  console.log(
    '✅ Simulación positiva del dron aprobada'
  );

  const signature = await sendAndConfirmTransaction(
    connection,
    new Transaction().add(droneIx),
    [
      wallet,
      agents['drone-a'].device
    ],
    {
      commitment: 'confirmed',
      preflightCommitment: 'confirmed',
    }
  );

  console.log(
    'Transaction:', signature
  );

  const updated = captureState();

  const updatedOrder = updated.work_orders.find(
    item =>
      item.work_order_account ===
      orderPda.toBase58()
  );

  if (
    updatedOrder?.status !== 'Claimed'
  ) {
    throw Error(
      'Transacción confirmada, pero Discovery no observa Claimed'
    );
  }

  console.log(
    '✅ EPIC 3.2.5: Claim real confirmado para Drone A'
  );
}

main().catch(error => {
  console.error(
    'CLAIM ERROR:', error.message
  );

  if (Array.isArray(error.logs)) {
    console.error(
      error.logs.join('\n')
    );
  }

  process.exitCode = 1;
});
