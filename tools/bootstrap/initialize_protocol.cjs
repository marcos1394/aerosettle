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

const IDL_FILE = path.resolve(
  'target/idl/aerosettle.discovery.json'
);

const WALLET_FILE = path.join(
  os.homedir(), '.config/solana/id.json'
);

const mode = process.argv[2] || '--inspect';

if (!['--inspect', '--send'].includes(mode)) {
  console.error(
    'Uso: node tools/bootstrap/initialize_protocol.cjs --inspect|--send'
  );
  process.exit(2);
}

const key = name => String(name)
  .split('::')
  .at(-1)
  .replace(/[^a-z0-9]/gi, '')
  .toLowerCase();

function findOne(array, name) {
  const matches = array.filter(
    x => key(x.name) === key(name)
  );

  if (matches.length !== 1) {
    throw new Error(
      `IDL: ${name} encontrado ${matches.length} veces`
    );
  }

  return matches[0];
}

function bytes32(label, genesis) {
  return crypto.createHash('sha256')
    .update(`aerosettle:localnet:${label}:v1:${genesis}`)
    .digest();
}

function isByteArray32(type) {
  return type &&
    typeof type === 'object' &&
    Array.isArray(type.array) &&
    type.array.length === 2 &&
    type.array[0] === 'u8' &&
    type.array[1] === 32;
}

function discriminator(item, label) {
  const d = item.discriminator;

  if (
    !Array.isArray(d) ||
    d.length !== 8 ||
    d.some(x =>
      !Number.isInteger(x) || x < 0 || x > 255
    )
  ) {
    throw new Error(
      `IDL: discriminador inválido para ${label}`
    );
  }

  return Buffer.from(d);
}

async function main() {
  if (!fs.existsSync(IDL_FILE)) {
    throw new Error(`No existe ${IDL_FILE}`);
  }

  if (!fs.existsSync(WALLET_FILE)) {
    throw new Error(`No existe ${WALLET_FILE}`);
  }

  const idl = JSON.parse(
    fs.readFileSync(IDL_FILE, 'utf8')
  );

  if (idl.address !== PROGRAM_ID) {
    throw new Error('Program ID distinto al esperado');
  }

  const ix = findOne(
    idl.instructions || [],
    'initialize_protocol'
  );

  const accountType = findOne(
    idl.accounts || [],
    'ProtocolConfig'
  );

  const accountDisc = discriminator(
    accountType, 'ProtocolConfig'
  );

  const instructionDisc = discriminator(
    ix, 'initialize_protocol'
  );

  const typeNames = (ix.args || []).map(
    x => key(x.name)
  );

  if (
    ix.args?.length !== 2 ||
    !typeNames.includes('networkid') ||
    !typeNames.includes('deploymentid') ||
    !ix.args.every(arg => isByteArray32(arg.type))
  ) {
    throw new Error(
      'IDL: argumentos distintos de los esperados: ' +
      JSON.stringify(ix.args)
    );
  }

  const programId = new PublicKey(PROGRAM_ID);

  const wallet = Keypair.fromSecretKey(
    Uint8Array.from(
      JSON.parse(fs.readFileSync(WALLET_FILE, 'utf8'))
    )
  );

  const connection = new Connection(RPC, 'confirmed');

  const info = await connection.getAccountInfo(
    programId, 'confirmed'
  );

  if (!info?.executable) {
    throw new Error(
      'Programa no desplegado en el RPC local'
    );
  }

  const [configPda] =
    PublicKey.findProgramAddressSync(
      [Buffer.from('protocol_config')],
      programId
    );

  const mapping = {
    protocolconfig: configPda,
    authority: wallet.publicKey,
    admin: wallet.publicKey,
    payer: wallet.publicKey,
    initializer: wallet.publicKey,
    owner: wallet.publicKey,
    signer: wallet.publicKey,
    systemprogram: SystemProgram.programId,
  };

  if (
    !Array.isArray(ix.accounts) ||
    ix.accounts.some(a => Array.isArray(a.accounts))
  ) {
    throw new Error(
      'IDL: estructura de cuentas inesperada'
    );
  }

  const keys = ix.accounts.map(a => {
    const pubkey = mapping[key(a.name)];

    if (!pubkey) {
      throw new Error(
        `IDL: cuenta desconocida ${a.name}`
      );
    }

    if (
      a.address &&
      a.address !== pubkey.toBase58()
    ) {
      throw new Error(
        `IDL: dirección fija inesperada para ${a.name}`
      );
    }

    const isSigner =
      a.signer === true || a.isSigner === true;

    const isWritable =
      a.writable === true || a.isMut === true;

    if (
      isSigner &&
      !pubkey.equals(wallet.publicKey)
    ) {
      throw new Error(
        `IDL: firmante inesperado ${a.name}`
      );
    }

    return { pubkey, isSigner, isWritable };
  });

  if (
    keys.filter(x => x.pubkey.equals(configPda)).length !== 1 ||
    !keys.some(x =>
      x.pubkey.equals(configPda) && x.isWritable
    ) ||
    !keys.some(x =>
      x.pubkey.equals(wallet.publicKey) && x.isSigner
    )
  ) {
    throw new Error(
      'IDL: metadatos de cuentas incompatibles'
    );
  }

  const existing = await connection.getAccountInfo(
    configPda, 'confirmed'
  );

  if (existing) {
    if (
      !existing.owner.equals(programId) ||
      !existing.data.subarray(0, 8).equals(accountDisc)
    ) {
      throw new Error(
        'ProtocolConfig existente con datos inválidos'
      );
    }
  }

  const genesis = await connection.getGenesisHash();

  console.log('RPC:', RPC);
  console.log('Program ID:', PROGRAM_ID);
  console.log('Genesis:', genesis);
  console.log('Wallet:', wallet.publicKey.toBase58());
  console.log('ProtocolConfig PDA:', configPda.toBase58());

  console.log(
    'IDL arguments:',
    ix.args.map(a => `${a.name}: [u8;32]`).join(', ')
  );

  console.log(
    'IDL accounts:',
    ix.accounts.map(a => a.name).join(', ')
  );

  if (existing) {
    console.log(
      '✅ ProtocolConfig ya existe. No se envió transacción.'
    );
    return;
  }

  if (mode === '--inspect') {
    console.log(
      '✅ Inspección correcta. Puedes ejecutar --send.'
    );
    return;
  }

  const values = {
    networkid: bytes32('network', genesis),
    deploymentid: bytes32('deployment', genesis),
  };

  const data = Buffer.concat([
    instructionDisc,
    ...ix.args.map(a => values[key(a.name)])
  ]);

  const instruction = new TransactionInstruction({
    programId,
    keys,
    data,
  });

  try {
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
      configPda, 'confirmed'
    );

    if (
      !created ||
      !created.owner.equals(programId) ||
      !created.data.subarray(0, 8).equals(accountDisc)
    ) {
      throw new Error(
        'Transacción confirmada pero ProtocolConfig no es válido'
      );
    }

    console.log('✅ ProtocolConfig inicializado y verificado');
    console.log('Signature:', signature);
  } catch (error) {
    console.error(
      'Error de inicialización:', error.message
    );

    if (Array.isArray(error.logs)) {
      console.error(error.logs.join('\n'));
    }

    throw error;
  }
}

main().catch(error => {
  console.error('BOOTSTRAP ERROR:', error.message);
  process.exitCode = 1;
});
