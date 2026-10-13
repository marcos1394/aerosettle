const fs = require('node:fs');
const path = require('node:path');
const os = require('node:os');
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

const DEVICE_FILE = path.join(
  ROOT, '.aerosettle-local/drone-a-device.json'
);

const OWNER_FILE = path.join(
  os.homedir(), '.config/solana/id.json'
);

const IDL_FILE = path.join(
  ROOT, 'target/idl/aerosettle.discovery.json'
);

const SEND = process.argv.includes('--send');

function fail(message) {
  throw new Error(message);
}

function assert(condition, message) {
  if (!condition) fail(message);
}

function loadKeypair(filename) {
  assert(fs.existsSync(filename),
    `No existe keypair: ${filename}`);

  const secret = JSON.parse(
    fs.readFileSync(filename, 'utf8')
  );

  assert(
    Array.isArray(secret) && secret.length === 64,
    'Formato de keypair inesperado'
  );

  return Keypair.fromSecretKey(
    Uint8Array.from(secret)
  );
}

function readAgent(data) {
  assert(data.length >= 196,
    'AgentAccount demasiado pequeña');

  const discriminator = crypto
    .createHash('sha256')
    .update('account:AgentAccount')
    .digest()
    .subarray(0, 8);

  assert(
    data.subarray(0, 8).equals(discriminator),
    'Discriminador AgentAccount inválido'
  );

  const key = (from, to) =>
    new PublicKey(
      data.subarray(from, to)
    ).toBase58();

  return {
    protocolConfig: key(9, 41),
    owner: key(73, 105),
    signingAuthority: key(105, 137),
    capabilities: data.readBigUInt64LE(138),
  };
}

function validateIdl(idl) {
  assert(idl.address === PROGRAM,
    'El IDL no pertenece a AeroSettle');

  const matches = idl.instructions.filter(
    item => item.name === 'rotate_signing_authority'
  );

  assert(matches.length === 1,
    'Instrucción de rotación ausente o duplicada');

  const ix = matches[0];

  const expectedAccounts = [
    ['protocol_config', false, false],
    ['agent_account', false, true],
    ['owner', true, false],
  ];

  assert(ix.accounts.length === 3,
    'Número de cuentas incorrecto');

  for (let i = 0; i < 3; i++) {
    const [name, signer, writable] =
      expectedAccounts[i];

    const current = ix.accounts[i];

    assert(
      current.name === name &&
      Boolean(current.signer) === signer &&
      Boolean(current.writable) === writable,
      `AccountMeta inesperada: ${name}`
    );
  }

  assert(
    ix.args.length === 1 &&
    ix.args[0].name === 'new_signing_authority' &&
    ix.args[0].type === 'pubkey',
    'Argumento de rotación incompatible'
  );

  const discriminator = crypto
    .createHash('sha256')
    .update('global:rotate_signing_authority')
    .digest()
    .subarray(0, 8);

  assert(
    Array.isArray(ix.discriminator) &&
    Buffer.from(ix.discriminator).equals(discriminator),
    'Discriminador Anchor no coincide'
  );

  return discriminator;
}

async function simulate(tx) {
  const serialized = tx.serialize({
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
        serialized.toString('base64'),
        {
          encoding: 'base64',
          commitment: 'confirmed',
          sigVerify: false,
          replaceRecentBlockhash: false,
        },
      ],
    }),
  });

  assert(response.ok,
    `HTTP ${response.status} en simulación`);

  const payload = await response.json();

  assert(!payload.error,
    'Error RPC: ' + JSON.stringify(payload.error));

  const result = payload.result?.value;

  assert(result,
    'Simulación sin resultado');

  console.log('\n=== SIMULATION LOGS ===');

  for (const line of result.logs || []) {
    console.log(line);
  }

  assert(result.err == null,
    'SIMULACIÓN FALLÓ: ' + JSON.stringify(result.err));

  console.log('\n✅ SIMULACIÓN CORRECTA');
}

async function main() {
  assert(
    process.argv.every(
      (arg, index) =>
        index < 2 || arg === '--send'
    ),
    'Argumento desconocido'
  );

  const connection = new Connection(
    RPC, 'confirmed'
  );

  const genesis = await connection.getGenesisHash();

  assert(genesis === GENESIS,
    'Genesis Hash incorrecto. Operación bloqueada.');

  const idl = JSON.parse(
    fs.readFileSync(IDL_FILE, 'utf8')
  );

  const discriminator = validateIdl(idl);

  const owner = loadKeypair(OWNER_FILE);
  const device = loadKeypair(DEVICE_FILE);

  const ownerKey = owner.publicKey.toBase58();
  const deviceKey = device.publicKey.toBase58();

  assert(ownerKey === OWNER,
    'El keypair CLI no es el propietario del agente');

  assert(deviceKey !== OWNER && deviceKey !== CREATOR,
    'La wallet de dispositivo no está separada');

  const agentKey = new PublicKey(AGENT);

  const [configInfo, agentInfo] = await Promise.all([
    connection.getAccountInfo(
      new PublicKey(CONFIG), 'confirmed'
    ),
    connection.getAccountInfo(
      agentKey, 'confirmed'
    ),
  ]);

  assert(
    configInfo &&
    configInfo.owner.toBase58() === PROGRAM,
    'ProtocolConfig no válido'
  );

  assert(
    agentInfo &&
    agentInfo.owner.toBase58() === PROGRAM,
    'AgentAccount no válida'
  );

  const before = readAgent(
    Buffer.from(agentInfo.data)
  );

  assert(before.protocolConfig === CONFIG,
    'El agente pertenece a otro protocolo');

  assert(before.owner === OWNER,
    'La propiedad on-chain no coincide');

  assert(
    (before.capabilities & 33n) === 33n,
    'El agente no cubre capacidades 33'
  );

  console.log('=== AEROSETTLE DEVICE ROTATION ===');
  console.log('Mode:', SEND ? 'SEND' : 'SIMULATE ONLY');
  console.log('Genesis:', genesis);
  console.log('Agent:', AGENT);
  console.log('Owner:', ownerKey);
  console.log(
    'Current signer:', before.signingAuthority
  );
  console.log('New device signer:', deviceKey);
  console.log(
    'Capabilities:', before.capabilities.toString()
  );

  if (before.signingAuthority === deviceKey) {
    console.log('\n✅ Autoridad ya configurada');
    console.log('No se envió ninguna transacción');
    return;
  }

  const ownerBalance = await connection.getBalance(
    owner.publicKey, 'confirmed'
  );

  assert(ownerBalance >= 50000,
    'Owner sin SOL suficiente para comisiones');

  const { blockhash, lastValidBlockHeight } =
    await connection.getLatestBlockhash('confirmed');

  const data = Buffer.concat([
    discriminator,
    device.publicKey.toBuffer(),
  ]);

  assert(data.length === 40,
    'Instruction data debe tener 40 bytes');

  const instruction = new TransactionInstruction({
    programId: new PublicKey(PROGRAM),
    keys: [
      {
        pubkey: new PublicKey(CONFIG),
        isSigner: false,
        isWritable: false,
      },
      {
        pubkey: agentKey,
        isSigner: false,
        isWritable: true,
      },
      {
        pubkey: owner.publicKey,
        isSigner: true,
        isWritable: false,
      },
    ],
    data,
  });

  const tx = new Transaction({
    feePayer: owner.publicKey,
    recentBlockhash: blockhash,
  }).add(instruction);

  await simulate(tx);

  if (!SEND) {
    console.log('\n✅ PREFLIGHT APROBADO');
    console.log('No se firmó ni envió transacción');
    console.log(
      'Para autorizar: ejecutar de nuevo con --send'
    );
    return;
  }

  // Volver a consultar el agente antes de firmar.
  const freshInfo = await connection.getAccountInfo(
    agentKey, 'confirmed'
  );

  assert(
    freshInfo &&
    freshInfo.owner.toBase58() === PROGRAM,
    'AgentAccount cambió de propietario'
  );

  const fresh = readAgent(
    Buffer.from(freshInfo.data)
  );

  assert(
    fresh.owner === before.owner &&
    fresh.signingAuthority === before.signingAuthority &&
    fresh.capabilities === before.capabilities,
    'El agente cambió durante el preflight'
  );

  const currentHeight = await connection.getBlockHeight(
    'confirmed'
  );

  assert(
    currentHeight < lastValidBlockHeight - 8,
    'Blockhash por vencer. Ejecuta de nuevo.'
  );

  tx.sign(owner);

  assert(tx.verifySignatures(true),
    'Firma del propietario inválida');

  console.log('\n=== SENDING ROTATION ===');

  let signature;

  try {
    signature = await connection.sendRawTransaction(
      tx.serialize(),
      {
        skipPreflight: false,
        preflightCommitment: 'confirmed',
        maxRetries: 2,
      }
    );
  } catch (error) {
    console.error(
      '⚠️ Error durante el envío:', error.message
    );
    console.error(
      'Verifica on-chain antes de intentar nuevamente.'
    );
    throw error;
  }

  console.log('Signature:', signature);

  const confirmed = await connection.confirmTransaction(
    {
      signature,
      blockhash,
      lastValidBlockHeight,
    },
    'confirmed'
  );

  assert(
    confirmed.value.err == null,
    'La transacción confirmó con error: ' +
      JSON.stringify(confirmed.value.err)
  );

  const afterInfo = await connection.getAccountInfo(
    agentKey, 'confirmed'
  );

  assert(afterInfo,
    'AgentAccount no encontrada tras rotación');

  const after = readAgent(
    Buffer.from(afterInfo.data)
  );

  assert(
    after.signingAuthority === deviceKey,
    'La autoridad no coincide con el nuevo dispositivo'
  );

  assert(
    after.owner === OWNER &&
    after.capabilities === before.capabilities,
    'Owner o capacidades cambiaron inesperadamente'
  );

  console.log('\n✅ ROTACIÓN CONFIRMADA ON-CHAIN');
  console.log('Agent:', AGENT);
  console.log('Owner preserved:', after.owner);
  console.log(
    'New signing authority:', after.signingAuthority
  );
  console.log('Signature:', signature);
}

main().catch(error => {
  console.error('\n❌', error.message);
  process.exitCode = 1;
});
