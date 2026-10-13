'use strict';

const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const crypto = require('node:crypto');
const {execFileSync} = require('node:child_process');

const {
  Connection, Keypair, PublicKey, SystemProgram,
  Transaction, TransactionInstruction,
  sendAndConfirmTransaction, SYSVAR_CLOCK_PUBKEY,
} = require('@solana/web3.js');

const {
  TOKEN_PROGRAM_ID, createMint, getMint,
  getOrCreateAssociatedTokenAccount,
  mintToChecked, getAccount,
} = require('@solana/spl-token');

const RPC = 'http://127.0.0.1:8899';
const PROGRAM = 'CeA1P1NSuPLUH31KsT4j3pZeBsknQZ3NSC6GUAqcsCLy';

const AMOUNT = 10_000_000n;
const DECIMALS = 6;

const mode = process.argv[2] || '--inspect';

if (![
  '--inspect', '--prepare', '--create', '--fund', '--verify'
].includes(mode)) {
  throw Error(
    'Uso: --inspect | --prepare | --create | --fund | --verify'
  );
}

const base = path.resolve('.aerosettle-local');

const idl = JSON.parse(
  fs.readFileSync(
    'target/idl/aerosettle.discovery.json', 'utf8'
  )
);

const caps = JSON.parse(
  fs.readFileSync(
    `${base}/bootstrap-capabilities.json`, 'utf8'
  )
);

const evidence = JSON.parse(
  fs.readFileSync(
    `${base}/bootstrap-evidence.json`, 'utf8'
  )
);

if (idl.address !== PROGRAM) {
  throw Error('IDL Program ID inesperado');
}

const key = n => String(n)
  .split('::').at(-1)
  .replace(/[^a-zA-Z0-9]/g, '')
  .toLowerCase();

function one(items, name) {
  const matches = items.filter(
    item => key(item.name) === key(name)
  );

  if (matches.length !== 1) {
    throw Error(
      `${name}: ${matches.length} coincidencias en IDL`
    );
  }

  return matches[0];
}

const hash = value => crypto
  .createHash('sha256')
  .update(value)
  .digest();

function disc(item) {
  const xs = item.discriminator;

  if (
    !Array.isArray(xs) ||
    xs.length !== 8 ||
    xs.some(x =>
      !Number.isInteger(x) || x < 0 || x > 255
    )
  ) {
    throw Error(`Discriminador inválido: ${item.name}`);
  }

  return Buffer.from(xs);
}

function u64(value) {
  const n = BigInt(value);

  if (n < 0n || n > 2n ** 64n - 1n) {
    throw Error('u64 fuera de rango');
  }

  const buffer = Buffer.alloc(8);
  buffer.writeBigUInt64LE(n);
  return buffer;
}

function i64(value) {
  const n = BigInt(value);

  if (
    n < -(2n ** 63n) ||
    n > 2n ** 63n - 1n
  ) {
    throw Error('i64 fuera de rango');
  }

  const buffer = Buffer.alloc(8);
  buffer.writeBigInt64LE(n);
  return buffer;
}

function array32(value) {
  const buffer = Buffer.from(value);

  if (buffer.length !== 32) {
    throw Error('Se requieren 32 bytes');
  }

  return buffer;
}

// Codificador Borsh guiado por los tipos del IDL.
function encode(type, value) {
  if (type === 'u64') return u64(value);
  if (type === 'i64') return i64(value);

  if (type === 'pubkey' || type === 'publicKey') {
    return new PublicKey(value).toBuffer();
  }

  if (type && typeof type === 'object') {
    if (
      Array.isArray(type.array) &&
      type.array[0] === 'u8' &&
      type.array[1] === 32
    ) {
      return array32(value);
    }

    const name = typeof type.defined === 'string'
      ? type.defined
      : type.defined?.name;

    if (name) {
      const definition = one(idl.types, name).type;

      if (definition.kind === 'enum') {
        if (
          !Array.isArray(definition.variants) ||
          definition.variants.length > 255 ||
          definition.variants.some(v => v.fields?.length)
        ) {
          throw Error(`Enum no soportado: ${name}`);
        }

        const index = definition.variants.findIndex(
          v => key(v.name) === key(value)
        );

        if (index < 0) {
          throw Error(
            `Variante ${value} no encontrada en ${name}`
          );
        }

        return Buffer.from([index]);
      }

      if (
        definition.kind === 'struct' &&
        Array.isArray(definition.fields)
      ) {
        if (!value || typeof value !== 'object') {
          throw Error(`Struct inválida: ${name}`);
        }

        const expected = definition.fields.map(
          field => key(field.name)
        );

        const provided = Object.keys(value);

        if (
          new Set(expected).size !== expected.length ||
          provided.some(
            field => !expected.includes(key(field))
          ) ||
          expected.some(
            field => !provided.some(
              actual => key(actual) === field
            )
          )
        ) {
          throw Error(`Campos inesperados en ${name}`);
        }

        return Buffer.concat(
          definition.fields.map(field => {
            const sourceKey = provided.find(
              item => key(item) === key(field.name)
            );

            return encode(
              field.type,
              value[sourceKey]
            );
          })
        );
      }

      throw Error(
        `Tipo definido no soportado: ${name}`
      );
    }
  }

  throw Error(
    `Tipo Borsh no soportado: ${JSON.stringify(type)}`
  );
}

function assertKeys(items, expected, label) {
  const actual = items.map(item => key(item.name));

  if (
    actual.length !== expected.length ||
    new Set(actual).size !== expected.length ||
    expected.some(
      name => !actual.includes(key(name))
    )
  ) {
    throw Error(
      `${label} difiere del contrato: ${actual}`
    );
  }
}

const createIx = one(
  idl.instructions, 'create_work_order'
);

const fundIx = one(
  idl.instructions, 'fund_work_order'
);

const orderSchema = one(
  idl.accounts, 'WorkOrderAccount'
);

const configSchema = one(
  idl.accounts, 'ProtocolConfig'
);

assertKeys(
  createIx.accounts,
  ['protocol_config', 'work_order', 'creator', 'system_program'],
  'create accounts'
);

assertKeys(
  fundIx.accounts,
  [
    'protocol_config', 'work_order', 'creator',
    'mint', 'creator_token_account', 'escrow_vault',
    'token_program', 'system_program'
  ],
  'fund accounts'
);

assertKeys(createIx.args, ['args'], 'create args');

if (fundIx.args.length !== 0) {
  throw Error('fund_work_order debe carecer de args');
}

const createArg = one(createIx.args, 'args');

const definedName = typeof createArg.type?.defined === 'string'
  ? createArg.type.defined
  : createArg.type?.defined?.name;

if (key(definedName || '') !== 'createworkorderargs') {
  throw Error('IDL CreateWorkOrderArgs incorrecto');
}

const orderDef = one(
  idl.types, 'CreateWorkOrderArgs'
).type;

const termsDef = one(
  idl.types, 'SettlementTerms'
).type;

if (
  orderDef.kind !== 'struct' ||
  termsDef.kind !== 'struct'
) {
  throw Error('Layouts de argumentos no válidos');
}

assertKeys(
  orderDef.fields,
  [
    'work_order_id', 'work_type',
    'required_capabilities', 'evidence_requirements',
    'manifest_hash', 'settlement',
    'execution_deadline', 'verification_deadline'
  ],
  'CreateWorkOrderArgs'
);

assertKeys(
  termsDef.fields,
  [
    'token_mint', 'total_amount',
    'payment_model', 'verifier'
  ],
  'SettlementTerms'
);

const required = BigInt(caps.aerial) | BigInt(caps.gps);
const drone = required | BigInt(caps.telemetry);
const sensor = BigInt(caps.telemetry);

if (
  required <= 0n ||
  (required & ~drone) !== 0n ||
  (required & ~sensor) === 0n
) {
  throw Error(
    'Las máscaras no discriminan Drone y Sensor'
  );
}

const neededEvidence = BigInt(evidence.mask);

if (
  neededEvidence <= 0n ||
  neededEvidence > 2n ** 64n - 1n
) {
  throw Error('Evidencias inválidas');
}

const programId = new PublicKey(PROGRAM);

const wallet = Keypair.fromSecretKey(
  Uint8Array.from(
    JSON.parse(
      fs.readFileSync(
        path.join(
          os.homedir(), '.config/solana/id.json'
        ),
        'utf8'
      )
    )
  )
);

const connection = new Connection(RPC, 'confirmed');

function accountMetas(items, mapping) {
  const keys = items.map(item => {
    const pubkey = mapping[key(item.name)];

    if (!pubkey) {
      throw Error(`Cuenta desconocida: ${item.name}`);
    }

    if (
      item.address &&
      item.address !== pubkey.toBase58()
    ) {
      throw Error(
        `Dirección fija inconsistente: ${item.name}`
      );
    }

    return {
      pubkey,
      isSigner: Boolean(
        item.signer ?? item.isSigner
      ),
      isWritable: Boolean(
        item.writable ?? item.isMut
      ),
    };
  });

  if (!keys.some(
    item => item.pubkey.equals(wallet.publicKey) &&
            item.isSigner
  )) {
    throw Error('Falta la firma del creator');
  }

  return keys;
}

function readKey(file) {
  if (!fs.existsSync(file)) return null;

  const xs = JSON.parse(
    fs.readFileSync(file, 'utf8')
  );

  if (
    !Array.isArray(xs) ||
    xs.length !== 64 ||
    xs.some(x =>
      !Number.isInteger(x) || x < 0 || x > 255
    )
  ) {
    throw Error(`Keypair inválido: ${file}`);
  }

  return Keypair.fromSecretKey(
    Uint8Array.from(xs)
  );
}

function makeKey(file) {
  const existing = readKey(file);

  if (existing) return existing;

  fs.mkdirSync(
    path.dirname(file),
    {recursive: true, mode: 0o700}
  );

  const pair = Keypair.generate();

  fs.writeFileSync(
    file,
    JSON.stringify(
      Array.from(pair.secretKey)
    ) + '\n',
    {flag: 'wx', mode: 0o600}
  );

  return pair;
}

async function snapshot() {
  const file = `${base}/discovery-marketplace.json`;

  execFileSync(
    'python3.11',
    [
      'tools/discovery/agent_discovery.py',
      '--rpc-url', RPC,
      '--idl', 'target/idl/aerosettle.discovery.json',
      '--commitment', 'confirmed',
      '--output', file
    ],
    {stdio: 'inherit'}
  );

  return JSON.parse(
    fs.readFileSync(file, 'utf8')
  );
}

async function main() {
  const programInfo = await connection.getAccountInfo(
    programId, 'confirmed'
  );

  if (!programInfo?.executable) {
    throw Error('Programa no desplegado en RPC local');
  }

  const [configPda] =
    PublicKey.findProgramAddressSync(
      [Buffer.from('protocol_config')],
      programId
    );

  const config = await connection.getAccountInfo(
    configPda, 'confirmed'
  );

  if (
    !config ||
    !config.owner.equals(programId) ||
    !config.data.subarray(0, 8).equals(
      disc(configSchema)
    )
  ) {
    throw Error('ProtocolConfig inválido');
  }

  const genesis = await connection.getGenesisHash();

  const fingerprint = hash(
    genesis + wallet.publicKey.toBase58()
  ).toString('hex').slice(0, 12);

  const mintFile =
    `${base}/bootstrap/keys/demo-mint-${fingerprint}.json`;

  const verifierFile =
    `${base}/bootstrap/keys/demo-verifier-${fingerprint}.json`;

  const mintSigner = readKey(mintFile);
  const verifier = readKey(verifierFile);

  const orderId = hash(
    `aerosettle:inspection:order:claim-v2:${genesis}:` +
    wallet.publicKey.toBase58()
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

  console.log('Mode:', mode);
  console.log('RPC:', RPC);
  console.log('Program:', PROGRAM);
  console.log('Genesis:', genesis);
  console.log('Owner:', wallet.publicKey.toBase58());
  console.log('WorkOrder PDA:', orderPda.toBase58());
  console.log('Escrow PDA:', vaultPda.toBase58());
  console.log('Required mask:', required.toString());
  console.log(
    'Mint:',
    mintSigner?.publicKey.toBase58() || '(not prepared)'
  );
  console.log(
    'Verifier:',
    verifier?.publicKey.toBase58() || '(not prepared)'
  );

  if (mode === '--inspect') {
    console.log(
      '✅ Inspección correcta. Sigue con --prepare.'
    );
    return;
  }

  if (mode === '--prepare') {
    const mint = makeKey(mintFile);
    makeKey(verifierFile);

    const mintInfo = await connection.getAccountInfo(
      mint.publicKey, 'confirmed'
    );

    if (!mintInfo) {
      await createMint(
        connection,
        wallet,
        wallet.publicKey,
        null,
        DECIMALS,
        mint,
        {commitment: 'confirmed'},
        TOKEN_PROGRAM_ID
      );
    }

    const mintState = await getMint(
      connection,
      mint.publicKey,
      'confirmed',
      TOKEN_PROGRAM_ID
    );

    if (
      mintState.decimals !== DECIMALS ||
      !mintState.mintAuthority?.equals(
        wallet.publicKey
      ) ||
      mintState.freezeAuthority
    ) {
      throw Error('Mint inesperado');
    }

    const ata = await getOrCreateAssociatedTokenAccount(
      connection,
      wallet,
      mint.publicKey,
      wallet.publicKey,
      false,
      'confirmed'
    );

    const tokenAccount = await getAccount(
      connection,
      ata.address,
      'confirmed'
    );

    if (tokenAccount.amount < AMOUNT) {
      await mintToChecked(
        connection,
        wallet,
        mint.publicKey,
        ata.address,
        wallet,
        AMOUNT - tokenAccount.amount,
        DECIMALS,
        [],
        {commitment: 'confirmed'}
      );
    }

    const after = await getAccount(
      connection,
      ata.address,
      'confirmed'
    );

    console.log(
      '✅ Mint preparado. Balance:',
      after.amount.toString(),
      'unidades base'
    );

    return;
  }

  if (!mintSigner || !verifier) {
    throw Error('Primero ejecuta --prepare');
  }

  await getMint(
    connection,
    mintSigner.publicKey,
    'confirmed',
    TOKEN_PROGRAM_ID
  );

  const orderInfo = await connection.getAccountInfo(
    orderPda, 'confirmed'
  );

  if (
    orderInfo &&
    (
      !orderInfo.owner.equals(programId) ||
      !orderInfo.data.subarray(0, 8).equals(
        disc(orderSchema)
      )
    )
  ) {
    throw Error(
      'WorkOrder con owner/discriminador inesperado'
    );
  }

  if (mode === '--create') {
    if (orderInfo) {
      console.log(
        '✅ WorkOrder ya existe. No se recreó.'
      );
      return;
    }

    const clock = await connection.getAccountInfo(
      SYSVAR_CLOCK_PUBKEY,
      'confirmed'
    );

    if (!clock || clock.data.length < 40) {
      throw Error('Clock sysvar no disponible');
    }

    const now = clock.data.readBigInt64LE(32);

    const args = {
      work_order_id: orderId,
      work_type: 'Inspection',
      required_capabilities: required,
      evidence_requirements: neededEvidence,
      manifest_hash: hash(
        `aerosettle:inspection:manifest:v1:${genesis}`
      ),
      settlement: {
        token_mint: mintSigner.publicKey,
        total_amount: AMOUNT,
        payment_model: 'Fixed',
        verifier: verifier.publicKey,
      },
      execution_deadline: now + 3600n,
      verification_deadline: now + 7200n,
    };

    const data = Buffer.concat([
      disc(createIx),
      encode(createArg.type, args),
    ]);

    const keys = accountMetas(
      createIx.accounts,
      {
        protocolconfig: configPda,
        workorder: orderPda,
        creator: wallet.publicKey,
        systemprogram: SystemProgram.programId,
      }
    );

    const instruction = new TransactionInstruction({
      programId,
      keys,
      data,
    });

    const signature = await sendAndConfirmTransaction(
      connection,
      new Transaction().add(instruction),
      [wallet],
      {
        commitment: 'confirmed',
        preflightCommitment: 'confirmed',
      }
    );

    const created = await connection.getAccountInfo(
      orderPda, 'confirmed'
    );

    if (
      !created ||
      !created.owner.equals(programId) ||
      !created.data.subarray(0, 8).equals(
        disc(orderSchema)
      )
    ) {
      throw Error('Draft no verificable');
    }

    console.log('✅ WorkOrder Draft creada');
    console.log('Signature:', signature);
    return;
  }

  if (!orderInfo) {
    throw Error(
      'WorkOrder aún no creada. Ejecuta --create.'
    );
  }

  if (mode === '--fund') {
    const state = await snapshot();

    const order = state.work_orders.find(
      item =>
        item.work_order_account === orderPda.toBase58()
    );

    if (!order) {
      throw Error(
        'La WorkOrder no aparece en Discovery'
      );
    }

    if (order.status === 'Open') {
      console.log(
        '✅ Orden ya Open. No se hizo otro depósito.'
      );
      return;
    }

    if (order.status !== 'Draft') {
      throw Error(
        `Estado no financiable: ${order.status}`
      );
    }

    const ata = await getOrCreateAssociatedTokenAccount(
      connection,
      wallet,
      mintSigner.publicKey,
      wallet.publicKey,
      false,
      'confirmed'
    );

    const source = await getAccount(
      connection,
      ata.address,
      'confirmed'
    );

    if (source.amount < AMOUNT) {
      throw Error(
        'Saldo insuficiente para escrow'
      );
    }

    const keys = accountMetas(
      fundIx.accounts,
      {
        protocolconfig: configPda,
        workorder: orderPda,
        creator: wallet.publicKey,
        mint: mintSigner.publicKey,
        creatortokenaccount: ata.address,
        escrowvault: vaultPda,
        tokenprogram: TOKEN_PROGRAM_ID,
        systemprogram: SystemProgram.programId,
      }
    );

    const instruction = new TransactionInstruction({
      programId,
      keys,
      data: disc(fundIx),
    });

    const signature = await sendAndConfirmTransaction(
      connection,
      new Transaction().add(instruction),
      [wallet],
      {
        commitment: 'confirmed',
        preflightCommitment: 'confirmed',
      }
    );

    const vault = await getAccount(
      connection,
      vaultPda,
      'confirmed',
      TOKEN_PROGRAM_ID
    );

    if (
      !vault.mint.equals(mintSigner.publicKey) ||
      !vault.owner.equals(vaultPda) ||
      vault.amount < AMOUNT
    ) {
      throw Error(
        'Escrow inválido después del depósito'
      );
    }

    console.log(
      '✅ 10 tokens depositados en escrow'
    );
    console.log('Signature:', signature);
    return;
  }

  if (mode === '--verify') {
    const state = await snapshot();

    const order = state.work_orders.find(
      item =>
        item.work_order_account === orderPda.toBase58()
    );

    if (
      !order ||
      !order.is_open ||
      order.status !== 'Open' ||
      state.protocol_paused
    ) {
      throw Error(
        'Orden no Open o protocolo pausado'
      );
    }

    if (
      BigInt(order.required_capabilities) !== required
    ) {
      throw Error('Capabilities inesperadas');
    }

    function agentAddress(name) {
      const agentId = hash(
        `aerosettle:bootstrap:agent:v1:${genesis}:` +
        `${wallet.publicKey.toBase58()}:${name}`
      );

      return PublicKey.findProgramAddressSync(
        [
          Buffer.from('agent'),
          configPda.toBuffer(),
          agentId,
        ],
        programId
      )[0].toBase58();
    }

    const dronePda = agentAddress('drone-a');
    const sensorPda = agentAddress('sensor-b');

    const agents = new Map(
      state.agents.map(item => [
        item.agent_account,
        item,
      ])
    );

    if (
      !agents.get(dronePda)?.active ||
      !agents.get(sensorPda)?.active
    ) {
      throw Error(
        'Faltan los dos agentes activos'
      );
    }

    const candidates =
      state.eligible_agents_by_order[
        orderPda.toBase58()
      ] || [];

    console.log('Drone A:', dronePda);
    console.log('Sensor B:', sensorPda);
    console.log('Eligible:', candidates);

    if (
      candidates.length !== 1 ||
      candidates[0] !== dronePda ||
      (
        BigInt(agents.get(sensorPda).capabilities) &
        required
      ) === required
    ) {
      throw Error('Matching incorrecto');
    }

    const vault = await getAccount(
      connection,
      vaultPda,
      'confirmed',
      TOKEN_PROGRAM_ID
    );

    if (
      vault.amount !== AMOUNT ||
      !vault.owner.equals(vaultPda)
    ) {
      throw Error(
        'Escrow no coincide con el contrato'
      );
    }

    console.log(
      '✅ EPIC 3.2.4 VALIDADA'
    );
    console.log(
      '✅ WorkOrder Open + Escrow real'
    );
    console.log(
      '✅ Drone elegible + Sensor descartado'
    );
  }
}

main().catch(async error => {
  console.error(
    'WORKORDER ERROR:', error.message
  );

  if (Array.isArray(error.logs)) {
    console.error(error.logs.join('\n'));
  } else if (typeof error.getLogs === 'function') {
    try {
      console.error(
        (await error.getLogs(connection)).join('\n')
      );
    } catch {
      // Algunos RPC no proporcionan logs.
    }
  }

  process.exitCode = 1;
});
