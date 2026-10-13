'use strict';

const fs = require('node:fs');
const path = require('node:path');
const os = require('node:os');
const crypto = require('node:crypto');
const cp = require('node:child_process');

const {
  Connection,
  Keypair,
  PublicKey,
  Transaction,
  TransactionInstruction,
  sendAndConfirmTransaction,
} = require('@solana/web3.js');

const {
  getAccount,
  TOKEN_PROGRAM_ID,
} = require('@solana/spl-token');

const MODE = process.argv[2] || '--inspect';

const MODES = [
  '--inspect',
  '--negative',
  '--submit',
  '--verify',
];

if (!MODES.includes(MODE)) {
  throw Error(
    'Uso: --inspect | --negative | --submit | --verify'
  );
}

const RPC = 'http://127.0.0.1:8899';

const PROGRAM =
  'CeA1P1NSuPLUH31KsT4j3pZeBsknQZ3NSC6GUAqcsCLy';

const GENESIS =
  'HP9XKTusRPGC78EFDpR9xdEq6simL2vqyDdrMvn6Vacg';

const TAG =
  process.env.AEROSETTLE_ORDER_TAG ||
  'claim-v2';

if (!/^[a-zA-Z0-9_-]{1,40}$/.test(TAG)) {
  throw Error('Order tag inválido');
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

const nameKey = value =>
  String(value)
    .split('::')
    .at(-1)
    .replace(/[^a-z0-9]/gi, '')
    .toLowerCase();

function exactly(items, name) {
  const found = items.filter(
    item => nameKey(item.name) === nameKey(name)
  );

  if (found.length !== 1) {
    throw Error(
      `IDL ${name}: ${found.length} coincidencias`
    );
  }

  return found[0];
}

function validateDisc(values, label) {
  if (
    !Array.isArray(values) ||
    values.length !== 8 ||
    values.some(x =>
      !Number.isInteger(x) ||
      x < 0 ||
      x > 255
    )
  ) {
    throw Error(
      `Discriminador inválido: ${label}`
    );
  }

  return Buffer.from(values);
}

const ix = exactly(
  idl.instructions,
  'submit_execution'
);

const arg = exactly(
  ix.args || [],
  'args'
);

const definedName =
  arg.type?.defined?.name ||
  arg.type?.defined ||
  '';

if (
  ix.args.length !== 1 ||
  nameKey(definedName) !== 'submitexecutionargs'
) {
  throw Error(
    'Firma de submit_execution inesperada'
  );
}

const def = exactly(
  idl.types,
  'SubmitExecutionArgs'
).type;

if (
  def.kind !== 'struct' ||
  !Array.isArray(def.fields)
) {
  throw Error(
    'SubmitExecutionArgs debe ser struct'
  );
}

const expectedTypes = {
  executionreceipthash: 'bytes32',
  evidencemanifesthash: 'bytes32',
  providedevidence: 'u64',
  executionstartedat: 'i64',
  executionendedat: 'i64',
  signaturesequence: 'u64',
};

if (
  def.fields.length !== 6 ||
  new Set(
    def.fields.map(f => nameKey(f.name))
  ).size !== 6
) {
  throw Error(
    'Campos inesperados en SubmitExecutionArgs'
  );
}

for (const field of def.fields) {
  const wanted = expectedTypes[
    nameKey(field.name)
  ];

  const valid = wanted === 'bytes32'
    ? (
      Array.isArray(field.type?.array) &&
      field.type.array[0] === 'u8' &&
      field.type.array[1] === 32
    )
    : field.type === wanted;

  if (!valid) {
    throw Error(
      `Tipo incompatible: ${field.name}`
    );
  }
}

const accountNames = [
  'protocolconfig',
  'workorder',
  'agentaccount',
  'agentsigner',
];

if (
  !Array.isArray(ix.accounts) ||
  ix.accounts.length !== 4 ||
  ix.accounts.some(
    account => Array.isArray(account.accounts)
  ) ||
  new Set(
    ix.accounts.map(a => nameKey(a.name))
  ).size !== 4 ||
  accountNames.some(
    name => !ix.accounts.some(
      a => nameKey(a.name) === name
    )
  )
) {
  throw Error(
    'Cuentas SubmitExecution incompatibles'
  );
}

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

const hash = data =>
  crypto
    .createHash('sha256')
    .update(data)
    .digest();

const digest = value =>
  hash(
    Buffer.from(
      JSON.stringify(value),
      'utf8'
    )
  );

const U64_MAX = (1n << 64n) - 1n;

function encU64(value) {
  const number = BigInt(value);

  if (number < 0n || number > U64_MAX) {
    throw Error('u64 fuera de rango');
  }

  const output = Buffer.alloc(8);
  output.writeBigUInt64LE(number);

  return output;
}

function encI64(value) {
  const number = BigInt(value);

  if (
    number < -(1n << 63n) ||
    number >= (1n << 63n)
  ) {
    throw Error('i64 fuera de rango');
  }

  const output = Buffer.alloc(8);
  output.writeBigInt64LE(number);

  return output;
}

function enc32(value) {
  if (
    typeof value !== 'string' ||
    !/^[a-f0-9]{64}$/i.test(value)
  ) {
    throw Error('Hash de 32 bytes inválido');
  }

  return Buffer.from(value, 'hex');
}

const contextFile = path.join(
  '.aerosettle-local',
  `execution-context-${TAG}.json`
);

const proofFile = path.join(
  '.aerosettle-local',
  'bootstrap',
  'evidence',
  `execution-${TAG}.json`
);

function readContext() {
  cp.execFileSync(
    'python3.11',
    [
      'tools/bootstrap/execution_context.py',
    ],
    {
      stdio: 'inherit',
      env: {
        ...process.env,
        AEROSETTLE_ORDER_TAG: TAG,
      },
    }
  );

  return JSON.parse(
    fs.readFileSync(contextFile, 'utf8')
  );
}

function loadDevice(ctx) {
  const namespace = hash(
    `${GENESIS}:${ctx.owner}`
  ).toString('hex').slice(0, 16);

  const keyFile = path.join(
    '.aerosettle-local',
    'bootstrap',
    'keys',
    `drone-a-${namespace}.json`
  );

  const data = JSON.parse(
    fs.readFileSync(keyFile, 'utf8')
  );

  if (
    !Array.isArray(data) ||
    data.length !== 64 ||
    data.some(x =>
      !Number.isInteger(x) ||
      x < 0 ||
      x > 255
    )
  ) {
    throw Error('Clave privada del dron inválida');
  }

  const device = Keypair.fromSecretKey(
    Uint8Array.from(data)
  );

  if (
    device.publicKey.toBase58() !==
    ctx.signing_authority
  ) {
    throw Error(
      'Clave del dispositivo no coincide con on-chain'
    );
  }

  return device;
}

function buildPayload(ctx) {
  const claimedAt = BigInt(ctx.claimed_at);
  const now = BigInt(ctx.chain_now);
  const deadline = BigInt(
    ctx.execution_deadline
  );

  if (now > deadline) {
    throw Error(
      'EXPIRED: plazo de ejecución vencido'
    );
  }

  if (now <= claimedAt + 1n) {
    throw Error(
      'CLOCK: no hay ventana suficiente desde claim'
    );
  }

  const ended = now - 1n;

  const manifest = {
    schema: 'aerosettle.demo.evidence-manifest.v1',
    synthetic: true,
    work_order: ctx.work_order,
    device: ctx.signing_authority,
    provided_evidence: ctx.provided_evidence,
    sources: [
      'synthetic-telemetry',
      'synthetic-gps-trace',
      'synthetic-image-manifest',
      'transaction-device-signature',
    ],
  };

  const manifestHash = digest(
    manifest
  ).toString('hex');

  const receipt = {
    schema: 'aerosettle.demo.execution-receipt.v1',
    synthetic: true,
    work_order: ctx.work_order,
    agent_account: ctx.agent_account,
    manifest_hash: manifestHash,
    sequence: ctx.sequence,
    started_at: claimedAt.toString(),
    ended_at: ended.toString(),
  };

  return {
    schema: 'aerosettle.localnet.submit-execution.v1',
    genesis: GENESIS,
    work_order: ctx.work_order,
    agent_account: ctx.agent_account,
    signature_sequence: ctx.sequence,
    provided_evidence: ctx.provided_evidence,
    execution_started_at: claimedAt.toString(),
    execution_ended_at: ended.toString(),
    evidence_manifest: manifest,
    execution_receipt: receipt,
    evidence_manifest_hash: manifestHash,
    execution_receipt_hash:
      digest(receipt).toString('hex'),
    note:
      'Demo SHA-256 JSON hashes; not canonical production commitments or physical execution evidence.',
  };
}

function savedProof(ctx, create) {
  if (fs.existsSync(proofFile)) {
    const proof = JSON.parse(
      fs.readFileSync(proofFile, 'utf8')
    );

    if (
      proof.genesis !== GENESIS ||
      proof.work_order !== ctx.work_order ||
      proof.agent_account !== ctx.agent_account ||
      digest(proof.evidence_manifest).toString('hex') !==
        proof.evidence_manifest_hash ||
      digest(proof.execution_receipt).toString('hex') !==
        proof.execution_receipt_hash ||
      proof.execution_receipt.manifest_hash !==
        proof.evidence_manifest_hash
    ) {
      throw Error(
        'Evidencia local alterada o incompatible'
      );
    }

    return proof;
  }

  if (!create) {
    throw Error(
      `No existe evidencia local: ${proofFile}`
    );
  }

  const proof = buildPayload(ctx);

  fs.mkdirSync(
    path.dirname(proofFile),
    {
      recursive: true,
      mode: 0o700,
    }
  );

  fs.writeFileSync(
    proofFile,
    JSON.stringify(proof, null, 2) + '\n',
    {
      flag: 'wx',
      mode: 0o600,
    }
  );

  return proof;
}

function buildInstruction(
  ctx,
  device,
  proof,
  wrongSequence = false
) {
  const fields = {
    executionreceipthash:
      enc32(proof.execution_receipt_hash),
    evidencemanifesthash:
      enc32(proof.evidence_manifest_hash),
    providedevidence:
      encU64(proof.provided_evidence),
    executionstartedat:
      encI64(proof.execution_started_at),
    executionendedat:
      encI64(proof.execution_ended_at),
    signaturesequence:
      encU64(
        wrongSequence
          ? BigInt(proof.signature_sequence) + 1n
          : proof.signature_sequence
      ),
  };

  const mapping = {
    protocolconfig:
      new PublicKey(ctx.protocol_config),
    workorder:
      new PublicKey(ctx.work_order),
    agentaccount:
      new PublicKey(ctx.agent_account),
    agentsigner:
      device.publicKey,
  };

  const keys = ix.accounts.map(meta => ({
    pubkey: mapping[nameKey(meta.name)],
    isSigner: Boolean(
      meta.signer ?? meta.isSigner
    ),
    isWritable: Boolean(
      meta.writable ?? meta.isMut
    ),
  }));

  if (
    ix.accounts.some(
      meta =>
        meta.address &&
        meta.address !==
          mapping[nameKey(meta.name)]?.toBase58()
    )
  ) {
    throw Error(
      'Dirección fija del IDL incompatible'
    );
  }

  if (
    keys.some(k => !k.pubkey) ||
    !keys.some(
      k =>
        k.pubkey.equals(device.publicKey) &&
        k.isSigner
    ) ||
    !keys.some(
      k =>
        k.pubkey.equals(mapping.workorder) &&
        k.isWritable
    ) ||
    keys.some(
      k =>
        k.isSigner &&
        !k.pubkey.equals(device.publicKey)
    )
  ) {
    throw Error(
      'Metadatos de cuentas inesperados'
    );
  }

  return new TransactionInstruction({
    programId,
    keys,
    data: Buffer.concat([
      validateDisc(
        ix.discriminator,
        'submit_execution'
      ),
      ...def.fields.map(
        field => fields[nameKey(field.name)]
      ),
    ]),
  });
}

async function simulate(
  instruction,
  device
) {
  const latest =
    await connection.getLatestBlockhash(
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

async function verifyVault(ctx) {
  const [vaultPda] =
    PublicKey.findProgramAddressSync(
      [
        Buffer.from('escrow'),
        new PublicKey(
          ctx.work_order
        ).toBuffer(),
      ],
      programId
    );

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
    throw Error('Saldo o autoridad de escrow inesperados');
  }
}

async function main() {
  const ctx = readContext();

  if (
    ctx.genesis !== GENESIS ||
    wallet.publicKey.toBase58() !== ctx.owner
  ) {
    throw Error(
      'Genesis o propietario incompatible'
    );
  }

  const device = loadDevice(ctx);

  console.log('\n=== AEROSETTLE EXECUTION ===');
  console.log('Mode:', MODE);
  console.log('Order:', ctx.work_order);
  console.log('Status:', ctx.status);
  console.log('Sequence:', ctx.sequence);
  console.log('Chain now:', ctx.chain_now);
  console.log('Deadline:', ctx.execution_deadline);

  if (MODE === '--inspect') {
    console.log(
      'IDL SubmitExecutionArgs: OK'
    );

    console.log(
      'Device:',
      device.publicKey.toBase58()
    );

    if (ctx.status !== 'Claimed') {
      console.log(
        'La orden no está Claimed; no presentar nuevamente.'
      );
    } else if (
      BigInt(ctx.chain_now) >
      BigInt(ctx.execution_deadline)
    ) {
      console.log(
        'ATENCIÓN: la orden venció.'
      );
    } else {
      console.log(
        '✅ Lista para simulación'
      );
    }

    return;
  }

  if (MODE === '--verify') {
    if (ctx.status !== 'Submitted') {
      throw Error(
        'La orden todavía no está Submitted'
      );
    }

    const proof = savedProof(ctx, false);

    if (
      ctx.execution_receipt_hash !==
        proof.execution_receipt_hash ||
      ctx.evidence_manifest_hash !==
        proof.evidence_manifest_hash ||
      BigInt(ctx.sequence) !==
        BigInt(proof.signature_sequence) + 1n
    ) {
      throw Error(
        'Hashes o nonce on-chain no coinciden'
      );
    }

    await verifyVault(ctx);

    console.log(
      '✅ Submitted persistido; hashes, nonce y escrow verificados'
    );

    return;
  }

  if (ctx.status !== 'Claimed') {
    throw Error(
      'Sólo se permite submit desde Claimed'
    );
  }

  const proof = (
    MODE === '--negative' &&
    !fs.existsSync(proofFile)
  )
    ? buildPayload(ctx)
    : savedProof(
        ctx,
        MODE === '--submit'
      );

  if (
    BigInt(ctx.chain_now) >
    BigInt(ctx.execution_deadline)
  ) {
    throw Error(
      'EXPIRED: plazo vencido'
    );
  }

  if (
    BigInt(proof.signature_sequence) !==
    BigInt(ctx.sequence)
  ) {
    throw Error(
      'Nonce local y on-chain diferentes'
    );
  }

  if (
    BigInt(proof.execution_ended_at) >=
    BigInt(ctx.chain_now)
  ) {
    throw Error(
      'Execution receipt tiene fecha futura'
    );
  }

  // Negative simulation: incorrect sequence.
  const negative = await simulate(
    buildInstruction(
      ctx, device, proof, true
    ),
    device
  );

  console.log(
    'Negative simulation:',
    JSON.stringify(negative.err)
  );

  for (const line of negative.logs || []) {
    if (
      /error|sequence|signature|nonce/i.test(line)
    ) {
      console.log(line);
    }
  }

  if (
    !negative.err ||
    !/sequence|nonce|replay/i.test(
      (negative.logs || []).join(' ')
    )
  ) {
    throw Error(
      'No se confirmó rechazo antirreplay'
    );
  }

  console.log(
    '✅ Secuencia incorrecta rechazada'
  );

  if (MODE === '--negative') {
    return;
  }

  // Positive simulation.
  const instruction = buildInstruction(
    ctx, device, proof, false
  );

  const positive = await simulate(
    instruction, device
  );

  if (positive.err) {
    console.log(
      'Positive error:',
      JSON.stringify(positive.err)
    );

    console.log(
      (positive.logs || []).join('\n')
    );

    throw Error(
      'Simulación positiva falló; no se envió transacción'
    );
  }

  console.log(
    '✅ Simulación positiva aprobada'
  );

  const signature =
    await sendAndConfirmTransaction(
      connection,
      new Transaction().add(instruction),
      [wallet, device],
      {
        commitment: 'confirmed',
        preflightCommitment: 'confirmed',
      }
    );

  console.log(
    'Transaction:', signature
  );

  const after = readContext();

  if (
    after.status !== 'Submitted' ||
    after.execution_receipt_hash !==
      proof.execution_receipt_hash ||
    after.evidence_manifest_hash !==
      proof.evidence_manifest_hash ||
    BigInt(after.sequence) !==
      BigInt(proof.signature_sequence) + 1n
  ) {
    throw Error(
      'Transacción enviada pero estado/hashes/nonce sin verificar'
    );
  }

  await verifyVault(after);

  console.log(
    '✅ EPIC 3.2.6: Submitted on-chain'
  );

  console.log(
    '✅ Hashes, nonce antirreplay y escrow verificados'
  );
}

main().catch(async error => {
  console.error(
    'SUBMIT ERROR:', error.message
  );

  if (Array.isArray(error.logs)) {
    console.error(
      error.logs.join('\n')
    );
  } else if (
    typeof error.getLogs === 'function'
  ) {
    try {
      console.error(
        (
          await error.getLogs(connection)
        ).join('\n')
      );
    } catch {
      // RPC logs may be unavailable.
    }
  }

  process.exitCode = 1;
});
