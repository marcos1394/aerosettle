'use strict';

const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const crypto = require('node:crypto');

const {
  Connection, Keypair, PublicKey, SystemProgram,
  Transaction, TransactionInstruction,
  sendAndConfirmTransaction,
} = require('@solana/web3.js');

const RPC = 'http://127.0.0.1:8899';
const PROGRAM_ID =
  'CeA1P1NSuPLUH31KsT4j3pZeBsknQZ3NSC6GUAqcsCLy';

const mode = process.argv[2] || '--inspect';

if (!['--inspect', '--send'].includes(mode)) {
  throw new Error(
    'Uso: node tools/bootstrap/register_agents.cjs --inspect|--send'
  );
}

const idl = JSON.parse(
  fs.readFileSync(
    'target/idl/aerosettle.discovery.json', 'utf8'
  )
);

if (idl.address !== PROGRAM_ID) {
  throw new Error('IDL del programa equivocado');
}

const capabilityValues = JSON.parse(
  fs.readFileSync(
    '.aerosettle-local/bootstrap-capabilities.json',
    'utf8'
  )
);

const key = name => String(name)
  .split('::').at(-1)
  .replace(/[^a-zA-Z0-9]/g, '')
  .toLowerCase();

const hash = value =>
  crypto.createHash('sha256').update(value).digest();

function one(items, name) {
  const matches = items.filter(
    item => key(item.name) === key(name)
  );

  if (matches.length !== 1) {
    throw new Error(
      `IDL ${name}: ${matches.length} coincidencias`
    );
  }

  return matches[0];
}

function bytes8(item, label) {
  const values = item.discriminator;

  if (
    !Array.isArray(values) ||
    values.length !== 8 ||
    values.some(x =>
      !Number.isInteger(x) || x < 0 || x > 255
    )
  ) {
    throw new Error(`Discriminador inválido: ${label}`);
  }

  return Buffer.from(values);
}

function array32(type) {
  return type &&
    typeof type === 'object' &&
    Array.isArray(type.array) &&
    type.array[0] === 'u8' &&
    type.array[1] === 32;
}

function definedAgentType(type) {
  if (!type || typeof type !== 'object') {
    return false;
  }

  const defined = type.defined;
  const name = typeof defined === 'string'
    ? defined : defined?.name;

  return Boolean(name && key(name) === 'agenttype');
}

const ix = one(idl.instructions, 'register_agent');
const configSchema = one(idl.accounts, 'ProtocolConfig');
const agentSchema = one(idl.accounts, 'AgentAccount');

const agentEnum = one(idl.types, 'AgentType').type;

if (
  agentEnum.kind !== 'enum' ||
  !Array.isArray(agentEnum.variants)
) {
  throw new Error('AgentType no es un enum válido');
}

const variants = agentEnum.variants;

if (variants.some(v => v.fields?.length)) {
  throw new Error(
    'AgentType contiene variantes con campos no soportados'
  );
}

const droneIndex = variants.findIndex(
  v => key(v.name) === 'drone'
);

const sensorCandidates = [
  'iot', 'iotdevice', 'iotsensor', 'sensor',
  'sensornode', 'environmentalsensor',
  'industrialiot', 'industrialsensor',
  'edgesensor', 'edgedevice', 'iotagent',
];

const selectedSensorType =
  process.env.AEROSETTLE_SENSOR_TYPE;

const sensorIndex = variants.findIndex(v =>
  selectedSensorType
    ? key(v.name) === key(selectedSensorType)
    : sensorCandidates.includes(key(v.name))
);

console.log(
  'AgentType disponibles:',
  variants.map(v => v.name).join(', ')
);

if (
  droneIndex < 0 ||
  sensorIndex < 0 ||
  droneIndex === sensorIndex
) {
  throw new Error(
    'No se encontró un tipo Drone y Sensor/IoT distinto. ' +
    'Revisa AgentType y selecciona el tipo IoT con ' +
    'AEROSETTLE_SENSOR_TYPE.'
  );
}

const expectedArgs = {
  agentid: 'array32',
  signingauthority: 'pubkey',
  agenttype: 'enum',
  capabilities: 'u64',
  metadatahash: 'array32',
};

if (
  !Array.isArray(ix.args) ||
  ix.args.length !== 5 ||
  new Set(ix.args.map(a => key(a.name))).size !== 5
) {
  throw new Error(
    'register_agent tiene argumentos inesperados'
  );
}

for (const arg of ix.args) {
  const kind = expectedArgs[key(arg.name)];

  const valid =
    kind === 'array32' ? array32(arg.type) :
    kind === 'enum' ? definedAgentType(arg.type) :
    kind === 'pubkey' ?
      ['pubkey', 'publicKey'].includes(arg.type) :
    kind === 'u64' ? arg.type === 'u64' : false;

  if (!valid) {
    throw new Error(
      `Argumento incompatible ${arg.name}: ` +
      JSON.stringify(arg.type)
    );
  }
}

const expectedAccounts = [
  'protocolconfig',
  'agentaccount',
  'owner',
  'systemprogram',
];

if (
  !Array.isArray(ix.accounts) ||
  ix.accounts.length !== 4 ||
  expectedAccounts.some(name =>
    ix.accounts.filter(
      account => key(account.name) === name
    ).length !== 1
  )
) {
  throw new Error(
    'Cuentas register_agent inesperadas: ' +
    JSON.stringify(ix.accounts)
  );
}

function capability(name) {
  const mask = BigInt(capabilityValues[name]);

  if (
    mask <= 0n ||
    mask > (1n << 64n) - 1n ||
    (mask & (mask - 1n)) !== 0n
  ) {
    throw new Error(`Máscara inválida: ${name}`);
  }

  return mask;
}

const droneMask =
  capability('aerial') |
  capability('gps') |
  capability('telemetry');

const sensorMask = capability('telemetry');

if ((droneMask & ~sensorMask) === 0n) {
  throw new Error(
    'Las capacidades no distinguen ambos agentes'
  );
}

const programId = new PublicKey(PROGRAM_ID);

const walletFile = path.join(
  os.homedir(),
  '.config/solana/id.json'
);

const wallet = Keypair.fromSecretKey(
  Uint8Array.from(
    JSON.parse(fs.readFileSync(walletFile, 'utf8'))
  )
);

const connection = new Connection(RPC, 'confirmed');

function deviceKeypair(file) {
  if (fs.existsSync(file)) {
    const values = JSON.parse(
      fs.readFileSync(file, 'utf8')
    );

    if (!Array.isArray(values) || values.length !== 64) {
      throw new Error('Clave de dispositivo inválida');
    }

    return Keypair.fromSecretKey(
      Uint8Array.from(values)
    );
  }

  const pair = Keypair.generate();

  fs.writeFileSync(
    file,
    JSON.stringify(Array.from(pair.secretKey)) + '\n',
    { mode: 0o600, flag: 'wx' }
  );

  return pair;
}

function encodeArg(name, profile, variantIndex) {
  switch (key(name)) {
    case 'agentid':
      return profile.agentId;

    case 'signingauthority':
      return profile.signingAuthority.toBuffer();

    case 'agenttype':
      return Buffer.from([variantIndex]);

    case 'capabilities': {
      const data = Buffer.alloc(8);
      data.writeBigUInt64LE(profile.mask);
      return data;
    }

    case 'metadatahash':
      return profile.metadataHash;

    default:
      throw new Error(`Argumento inesperado: ${name}`);
  }
}

async function main() {
  const deployed = await connection.getAccountInfo(
    programId, 'confirmed'
  );

  if (!deployed?.executable) {
    throw new Error('AeroSettle no está desplegado');
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
      bytes8(configSchema, 'ProtocolConfig')
    )
  ) {
    throw new Error(
      'ProtocolConfig no inicializado o inválido'
    );
  }

  const genesis = await connection.getGenesisHash();

  const namespace = hash(
    `${genesis}:${wallet.publicKey.toBase58()}`
  ).toString('hex').slice(0, 16);

  const deviceDirectory = path.resolve(
    '.aerosettle-local/bootstrap/keys'
  );

  if (mode === '--send') {
    fs.mkdirSync(
      deviceDirectory,
      { recursive: true, mode: 0o700 }
    );
    fs.chmodSync(deviceDirectory, 0o700);
  }

  const profiles = [
    {
      name: 'drone-a',
      typeIndex: droneIndex,
      mask: droneMask,
    },
    {
      name: 'sensor-b',
      typeIndex: sensorIndex,
      mask: sensorMask,
    },
  ];

  console.log('RPC:', RPC);
  console.log('Genesis:', genesis);
  console.log('Owner:', wallet.publicKey.toBase58());
  console.log('Protocol PDA:', configPda.toBase58());

  for (const profile of profiles) {
    const agentId = hash(
      'aerosettle:bootstrap:agent:v1:' +
      `${genesis}:${wallet.publicKey.toBase58()}:` +
      profile.name
    );

    const [agentPda] =
      PublicKey.findProgramAddressSync(
        [
          Buffer.from('agent'),
          configPda.toBuffer(),
          agentId,
        ],
        programId
      );

    const existing = await connection.getAccountInfo(
      agentPda, 'confirmed'
    );

    if (
      existing &&
      (
        !existing.owner.equals(programId) ||
        !existing.data.subarray(0, 8).equals(
          bytes8(agentSchema, 'AgentAccount')
        )
      )
    ) {
      throw new Error(
        'AgentAccount existente inválida: ' +
        agentPda.toBase58()
      );
    }

    console.log(
      `\n${profile.name} | ` +
      `AgentType=${variants[profile.typeIndex].name} | ` +
      `Capabilities=${profile.mask.toString()}`
    );

    console.log('Agent ID:', agentId.toString('hex'));
    console.log('Agent PDA:', agentPda.toBase58());
    console.log(
      'Estado:',
      existing ? 'Ya registrado' : 'Pendiente'
    );

    if (mode === '--inspect' || existing) {
      continue;
    }

    const signer = deviceKeypair(
      path.join(
        deviceDirectory,
        `${profile.name}-${namespace}.json`
      )
    );

    const metadataHash = hash(JSON.stringify({
      protocol: 'aerosettle',
      version: 1,
      demo: true,
      localnet_genesis: genesis,
      name: profile.name,
      agent_type: variants[profile.typeIndex].name,
      capabilities: profile.mask.toString(),
    }));

    const mappedAccounts = {
      protocolconfig: configPda,
      agentaccount: agentPda,
      owner: wallet.publicKey,
      systemprogram: SystemProgram.programId,
    };

    const keys = ix.accounts.map(account => {
      const pubkey = mappedAccounts[key(account.name)];

      if (!pubkey) {
        throw new Error(
          `Cuenta no soportada: ${account.name}`
        );
      }

      if (
        account.address &&
        account.address !== pubkey.toBase58()
      ) {
        throw new Error(
          `Dirección IDL incompatible: ${account.name}`
        );
      }

      return {
        pubkey,
        isSigner: Boolean(
          account.signer ?? account.isSigner
        ),
        isWritable: Boolean(
          account.writable ?? account.isMut
        ),
      };
    });

    const ownerMeta = keys.find(
      item => item.pubkey.equals(wallet.publicKey)
    );

    const agentMeta = keys.find(
      item => item.pubkey.equals(agentPda)
    );

    if (
      !ownerMeta?.isSigner ||
      !ownerMeta?.isWritable ||
      !agentMeta?.isWritable ||
      agentMeta.isSigner
    ) {
      throw new Error(
        'Metadatos de cuentas incompatibles'
      );
    }

    const data = Buffer.concat([
      bytes8(ix, 'register_agent'),
      ...ix.args.map(arg =>
        encodeArg(arg.name, {
          agentId,
          signingAuthority: signer.publicKey,
          mask: profile.mask,
          metadataHash,
        }, profile.typeIndex)
      ),
    ]);

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
      agentPda, 'confirmed'
    );

    if (
      !created ||
      !created.owner.equals(programId) ||
      !created.data.subarray(0, 8).equals(
        bytes8(agentSchema, 'AgentAccount')
      )
    ) {
      throw new Error(
        'Transacción confirmada pero AgentAccount inválida'
      );
    }

    console.log('Transaction:', signature);
    console.log(
      'Device signer:',
      signer.publicKey.toBase58()
    );
    console.log('✅ AgentAccount creada');
  }

  if (mode === '--inspect') {
    console.log(
      '\n✅ Inspección completada. Usa --send para registrar.'
    );
  }
}

main().catch(async error => {
  console.error('REGISTER ERROR:', error.message);

  if (Array.isArray(error.logs)) {
    console.error(error.logs.join('\n'));
  } else if (typeof error.getLogs === 'function') {
    try {
      console.error(
        (await error.getLogs(connection)).join('\n')
      );
    } catch {
      // El RPC puede no proporcionar logs.
    }
  }

  process.exitCode = 1;
});
