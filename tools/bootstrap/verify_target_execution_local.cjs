'use strict';

const fs = require('node:fs');
const path = require('node:path');
const os = require('node:os');
const crypto = require('node:crypto');
const cp = require('node:child_process');

const {
  Connection, Keypair, PublicKey, Transaction,
  TransactionInstruction, sendAndConfirmTransaction,
} = require('@solana/web3.js');

const {
  getAccount, TOKEN_PROGRAM_ID,
} = require('@solana/spl-token');

const RPC = 'http://127.0.0.1:8899';

const PROGRAM =
  'CeA1P1NSuPLUH31KsT4j3pZeBsknQZ3NSC6GUAqcsCLy';

const GENESIS =
  'HP9XKTusRPGC78EFDpR9xdEq6simL2vqyDdrMvn6Vacg';

const TAG = 'target-submitted';

const TARGET =
  'EnkZQWDqF5HeFeusZ7xnj7tngVN9xASofmKvXtDLeqbx';

const MODE = process.argv[2] || '--inspect';

if (!/^[A-Za-z0-9_-]{1,40}$/.test(TAG)) {
  throw Error('Order tag inválido');
}

if (![
  '--inspect', '--negative', '--simulate', '--send', '--verify'
].includes(MODE)) {
  throw Error('Uso: --inspect | --negative | --simulate | --send | --verify');
}

const idl = JSON.parse(
  fs.readFileSync(
    'target/idl/aerosettle.discovery.json', 'utf8'
  )
);

if (idl.address !== PROGRAM) {
  throw Error('Program ID del IDL incorrecto');
}

const norm = x => String(x)
  .split('::').at(-1)
  .replace(/[^A-Za-z0-9]/g, '')
  .toLowerCase();

function exactly(list, name) {
  const found = list.filter(
    x => norm(x.name) === norm(name)
  );

  if (found.length !== 1) {
    throw Error(
      `IDL ${name}: ${found.length} coincidencias`
    );
  }

  return found[0];
}

const ix = exactly(
  idl.instructions, 'verify_execution'
);

const args = exactly(ix.args || [], 'args');

if (
  (ix.args || []).length !== 1 ||
  norm(
    args.type?.defined?.name ||
    args.type?.defined || ''
  ) !== 'verifyexecutionargs'
) {
  throw Error(
    'Argumentos VerifyExecution incompatibles'
  );
}

const shape = exactly(
  idl.types, 'VerifyExecutionArgs'
).type;

const expected = {
  verificationattestationhash: 'hash',
  status: 'status',
  completionbps: 'u16',
  verifiedat: 'i64',
};

if (
  shape.kind !== 'struct' ||
  !Array.isArray(shape.fields) ||
  shape.fields.length !== 4 ||
  new Set(
    shape.fields.map(f => norm(f.name))
  ).size !== 4
) {
  throw Error(
    'Estructura VerifyExecutionArgs inesperada'
  );
}

for (const field of shape.fields) {
  const required = expected[norm(field.name)];

  let valid = false;

  if (required === 'hash') {
    valid =
      field.type?.array?.[0] === 'u8' &&
      field.type.array[1] === 32;
  } else if (required === 'status') {
    valid = norm(
      field.type?.defined?.name ||
      field.type?.defined || ''
    ) === 'verificationstatus';
  } else {
    valid =
      required !== undefined &&
      field.type === required;
  }

  if (!valid) {
    throw Error(
      `Campo IDL incompatible: ${field.name}`
    );
  }
}

const statusEnum = exactly(
  idl.types, 'VerificationStatus'
).type;

if (
  statusEnum.kind !== 'enum' ||
  !Array.isArray(statusEnum.variants) ||
  statusEnum.variants.length > 255 ||
  statusEnum.variants.some(
    variant => variant.fields?.length
  )
) {
  throw Error(
    'Enum VerificationStatus incompatible'
  );
}

const acceptedIndex =
  statusEnum.variants.findIndex(
    variant => norm(variant.name) === 'accepted'
  );

if (acceptedIndex < 0) {
  throw Error(
    'VerificationStatus::Accepted no encontrado'
  );
}

const requiredAccounts = [
  'protocolconfig',
  'workorder',
  'verifier',
];

if (
  !Array.isArray(ix.accounts) ||
  ix.accounts.length !== 3 ||
  ix.accounts.some(
    account => Array.isArray(account.accounts)
  ) ||
  new Set(
    ix.accounts.map(a => norm(a.name))
  ).size !== 3 ||
  requiredAccounts.some(
    name => !ix.accounts.some(
      account => norm(account.name) === name
    )
  )
) {
  throw Error(
    'Cuentas VerifyExecution inesperadas'
  );
}

function discriminator(item) {
  const data = item.discriminator;

  if (
    !Array.isArray(data) ||
    data.length !== 8 ||
    data.some(
      x => !Number.isInteger(x) || x < 0 || x > 255
    )
  ) {
    throw Error(
      `Discriminador inválido: ${item.name}`
    );
  }

  return Buffer.from(data);
}

function hex32(value) {
  if (
    typeof value !== 'string' ||
    !/^[a-f0-9]{64}$/i.test(value)
  ) {
    throw Error('Hash de 32 bytes inválido');
  }

  return Buffer.from(value, 'hex');
}

function i64(value) {
  const n = BigInt(value);

  if (
    n < -(1n << 63n) ||
    n >= (1n << 63n)
  ) {
    throw Error('Valor i64 inválido');
  }

  const result = Buffer.alloc(8);
  result.writeBigInt64LE(n);

  return result;
}

const programId = new PublicKey(PROGRAM);
const connection = new Connection(RPC, 'confirmed');

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

const fingerprint = crypto
  .createHash('sha256')
  .update(
    GENESIS + wallet.publicKey.toBase58()
  )
  .digest('hex')
  .slice(0, 12);

const verifierFile =
  `.aerosettle-local/bootstrap/keys/demo-verifier-${fingerprint}.json`;

const planFile =
  `.aerosettle-local/bootstrap/verification-plan-${TARGET}.json`;

function getVerifier() {
  if (!fs.existsSync(verifierFile)) {
    throw Error(
      'No existe la clave local del verificador: ' +
      verifierFile
    );
  }

  const values = JSON.parse(
    fs.readFileSync(verifierFile, 'utf8')
  );

  if (
    !Array.isArray(values) ||
    values.length !== 64 ||
    values.some(
      x => !Number.isInteger(x) || x < 0 || x > 255
    )
  ) {
    throw Error('Keypair del verificador inválido');
  }

  return Keypair.fromSecretKey(
    Uint8Array.from(values)
  );
}

function context() {
  cp.execFileSync(
    'python3.11',
    ['tools/verification/target_verification_context.py'],
    {
      stdio: 'inherit',
      env: {
        ...process.env,
        AEROSETTLE_ORDER_TAG: TAG,
      },
    }
  );

  return JSON.parse(
    fs.readFileSync(
      `.aerosettle-local/verification-context-target-${TARGET}.json`,
      'utf8'
    )
  );
}

function canonicalHash(ctx, verifiedAt) {
  const env = {
    ...process.env,
    AEROSETTLE_ATTEST_WORK_ORDER_ID:
      ctx.order_id_hex,
    AEROSETTLE_ATTEST_RECEIPT_HASH:
      ctx.execution_receipt_hash,
    AEROSETTLE_ATTEST_MANIFEST_HASH:
      ctx.evidence_manifest_hash,
    AEROSETTLE_ATTEST_VERIFIER:
      ctx.verifier,
    AEROSETTLE_ATTEST_VERIFIED_AT:
      String(verifiedAt),
  };

  const output = cp.execFileSync(
    'cargo',
    [
      'run',
      '--quiet',
      '-p', 'aerosettle',
      '--example', 'localnet_attestation_hash',
    ],
    {
      env,
      encoding: 'utf8',
    }
  );

  const matches = [
    ...output.matchAll(
      /AEROSETTLE_ATTESTATION_HASH=([a-f0-9]{64})/g
    ),
  ];

  if (matches.length !== 1) {
    throw Error(
      'El generador Rust no devolvió un hash canónico'
    );
  }

  return matches[0][1];
}

function loadPlan(ctx, create) {
  if (fs.existsSync(planFile)) {
    const plan = JSON.parse(
      fs.readFileSync(planFile, 'utf8')
    );

    if (
      plan.genesis !== GENESIS ||
      plan.work_order !== ctx.work_order ||
      plan.verifier !== ctx.verifier ||
      plan.status !== 'Accepted' ||
      plan.completion_bps !== 10000 ||
      !/^[a-f0-9]{64}$/.test(plan.hash)
    ) {
      throw Error(
        'Plan de atestación inconsistente'
      );
    }

    if (
      canonicalHash(ctx, plan.verified_at) !==
      plan.hash
    ) {
      throw Error(
        'El hash canónico del plan cambió'
      );
    }

    return plan;
  }

  if (!create) {
    throw Error(
      'No existe un plan de verificación local'
    );
  }

  const verifiedAt = BigInt(ctx.chain_now);

  if (
    ctx.status !== 'Submitted' ||
    verifiedAt < BigInt(ctx.submitted_at) ||
    verifiedAt > BigInt(ctx.verification_deadline)
  ) {
    throw Error(
      'Ventana de verificación cerrada'
    );
  }

  const plan = {
    genesis: GENESIS,
    work_order: ctx.work_order,
    verifier: ctx.verifier,
    status: 'Accepted',
    completion_bps: 10000,
    verified_at: String(verifiedAt),
    hash: canonicalHash(ctx, verifiedAt),
  };

  fs.mkdirSync(
    path.dirname(planFile),
    {
      recursive: true,
      mode: 0o700,
    }
  );

  fs.writeFileSync(
    planFile,
    JSON.stringify(plan, null, 2) + '\n',
    {
      mode: 0o600,
      flag: 'wx',
    }
  );

  return plan;
}

function instruction(
  ctx, signer, plan, alteredHash = false
) {
  const digest = hex32(plan.hash);

  if (alteredHash) {
    digest[0] ^= 1;
  }

  const fields = {
    verificationattestationhash: digest,
    status: Buffer.from([acceptedIndex]),
    completionbps: Buffer.from([
      0x10, 0x27,
    ]),
    verifiedat: i64(plan.verified_at),
  };

  const mapping = {
    protocolconfig:
      new PublicKey(ctx.protocol_config),
    workorder:
      new PublicKey(ctx.work_order),
    verifier:
      signer.publicKey,
  };

  const keys = ix.accounts.map(account => {
    const pubkey = mapping[
      norm(account.name)
    ];

    if (
      !pubkey ||
      (
        account.address &&
        account.address !== pubkey.toBase58()
      )
    ) {
      throw Error(
        `Cuenta VerifyExecution inválida: ${account.name}`
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

  if (
    !keys.some(
      k =>
        k.pubkey.equals(mapping.workorder) &&
        k.isWritable
    ) ||
    !keys.some(
      k =>
        k.pubkey.equals(signer.publicKey) &&
        k.isSigner
    ) ||
    keys.some(
      k =>
        k.isSigner &&
        !k.pubkey.equals(signer.publicKey)
    )
  ) {
    throw Error(
      'Permisos de firma inesperados'
    );
  }

  return new TransactionInstruction({
    programId,
    keys,
    data: Buffer.concat([
      discriminator(ix),
      ...shape.fields.map(
        field => fields[norm(field.name)]
      ),
    ]),
  });
}

async function simulate(instr, signer) {
  const latest =
    await connection.getLatestBlockhash(
      'confirmed'
    );

  const tx = new Transaction({
    feePayer: wallet.publicKey,
    recentBlockhash: latest.blockhash,
  }).add(instr);

  const signers =
    signer.publicKey.equals(wallet.publicKey)
      ? [wallet]
      : [wallet, signer];

  return (
    await connection.simulateTransaction(
      tx, signers
    )
  ).value;
}

async function vaultUnchanged(ctx) {
  const [vault] =
    PublicKey.findProgramAddressSync(
      [
        Buffer.from('escrow'),
        new PublicKey(
          ctx.work_order
        ).toBuffer(),
      ],
      programId
    );

  const account = await getAccount(
    connection,
    vault,
    'confirmed',
    TOKEN_PROGRAM_ID
  );

  if (
    !vault.equals(new PublicKey(ctx.escrow_vault)) ||
    !new PublicKey(ctx.token_program).equals(TOKEN_PROGRAM_ID) ||
    !account.owner.equals(vault) ||
    !account.mint.equals(new PublicKey(ctx.token_mint)) ||
    account.amount !== BigInt(ctx.total_amount)
  ) {
    throw Error(
      'Escrow incompatible con los términos on-chain'
    );
  }
}

async function main() {
  if (
    await connection.getGenesisHash() !== GENESIS
  ) {
    throw Error('Genesis distinto al esperado');
  }

  const deployed =
    await connection.getAccountInfo(
      programId,
      'confirmed'
    );

  if (!deployed?.executable) {
    throw Error('Programa no desplegado');
  }

  const ctx = context();
  const verifier = getVerifier();

  if (ctx.work_order !== TARGET) {
    throw Error('WorkOrder target incorrecta');
  }

  await vaultUnchanged(ctx);

  if (
    ctx.owner !== wallet.publicKey.toBase58() ||
    ctx.verifier !== verifier.publicKey.toBase58()
  ) {
    throw Error(
      'La clave del verificador no coincide con el contrato'
    );
  }

  console.log('\n=== AEROSETTLE VERIFICATION ===');
  console.log('Mode:', MODE);
  console.log('Order:', TAG);
  console.log('Status:', ctx.status);
  console.log('Verifier:', ctx.verifier);
  console.log('Chain time:', ctx.chain_now);
  console.log(
    'Verification deadline:',
    ctx.verification_deadline
  );

  if (MODE === '--verify') {
    if (ctx.status !== 'Verified') {
      throw Error(
        'La WorkOrder todavía no está Verified'
      );
    }

    const plan = loadPlan(ctx, false);

    if (
      ctx.verification_attestation_hash != null &&
      ctx.verification_attestation_hash !== plan.hash
    ) {
      throw Error(
        'Hash de atestación on-chain diferente'
      );
    }

    if (
      ctx.verification_status != null &&
      ctx.verification_status !== 'Accepted'
    ) {
      throw Error(
        'Estado de verificación inesperado'
      );
    }

    if (
      ctx.completion_bps != null &&
      ctx.completion_bps !== 10000
    ) {
      throw Error(
        'Porcentaje de ejecución inesperado'
      );
    }

    await vaultUnchanged(ctx);

    console.log(
      '✅ Verified on-chain; hash canónico validado; escrow intacto'
    );

    return;
  }

  if (ctx.status !== 'Submitted') {
    throw Error(
      'Se esperaba una WorkOrder Submitted'
    );
  }

  if (
    BigInt(ctx.chain_now) >
    BigInt(ctx.verification_deadline)
  ) {
    throw Error(
      'El plazo de verificación ya venció'
    );
  }

  // Independent target-order evidence audit.
  cp.execFileSync(
    'python3.11',
    ['tools/execution/verify_submission.py'],
    {
      stdio: 'inherit',
      env: {
        ...process.env,
        ORDER: TARGET,
      },
    }
  );

  const plan = loadPlan(ctx, true);

  if (
    BigInt(ctx.chain_now) <
      BigInt(plan.verified_at) ||
    BigInt(plan.verified_at) >
      BigInt(ctx.verification_deadline)
  ) {
    throw Error(
      'Timestamp de atestación fuera de la ventana'
    );
  }

  console.log(
    'Canonical attestation:', plan.hash
  );

  console.log(
    'Verified at:', plan.verified_at
  );

  if (MODE === '--inspect') {
    console.log(
      '✅ IDL, verificador, compromiso canónico y ventana validados'
    );

    return;
  }

  // Negative test: unauthorized verifier.
  const unauthorized = await simulate(
    instruction(ctx, wallet, plan),
    wallet
  );

  console.log(
    'Unauthorized verifier simulation:',
    JSON.stringify(unauthorized.err)
  );

  if (
    !unauthorized.err ||
    !/verifier|constraint|unauthor|invalid/i.test(
      (unauthorized.logs || []).join('\n')
    )
  ) {
    console.log(
      (unauthorized.logs || []).join('\n')
    );

    throw Error(
      'No se confirmó el rechazo del verificador no autorizado'
    );
  }

  // Negative test: tampered commitment.
  const tampered = await simulate(
    instruction(ctx, verifier, plan, true),
    verifier
  );

  console.log(
    'Tampered hash simulation:',
    JSON.stringify(tampered.err)
  );

  if (
    !tampered.err ||
    !/hash|attestation|commitment/i.test(
      (tampered.logs || []).join('\n')
    )
  ) {
    console.log(
      (tampered.logs || []).join('\n')
    );

    throw Error(
      'No se confirmó el rechazo del hash alterado'
    );
  }

  console.log(
    '✅ Verificador no autorizado rechazado'
  );

  console.log(
    '✅ Compromiso criptográfico alterado rechazado'
  );

  if (MODE === '--negative') {
    return;
  }

  // Positive test: valid verifier and canonical hash.
  const correctInstruction = instruction(
    ctx, verifier, plan
  );

  const positive = await simulate(
    correctInstruction,
    verifier
  );

  if (positive.err) {
    console.log(
      (positive.logs || []).join('\n')
    );

    throw Error(
      'Simulación positiva fallida. No se envió transacción.'
    );
  }

  console.log(
    '✅ Simulación positiva aprobada'
  );

  if (MODE === '--simulate') {
    console.log(
      '✅ Simulaciones negativas y positiva aprobadas'
    );
    console.log('Transactions sent: 0');
    return;
  }

  const signature =
    await sendAndConfirmTransaction(
      connection,
      new Transaction().add(
        correctInstruction
      ),
      [wallet, verifier],
      {
        commitment: 'confirmed',
        preflightCommitment: 'confirmed',
      }
    );

  console.log(
    'Transaction:', signature
  );

  const updated = context();

  if (updated.status !== 'Verified') {
    throw Error(
      'La transacción se confirmó, pero la orden no está Verified'
    );
  }

  if (
    updated.verification_attestation_hash != null &&
    updated.verification_attestation_hash !== plan.hash
  ) {
    throw Error(
      'Hash persistido incompatible'
    );
  }

  await vaultUnchanged(updated);

  console.log(
    '✅ EPIC 3.2.7: Verified on-chain'
  );

  console.log(
    '✅ Escrow intacto: 10 tokens'
  );
}

main().catch(async error => {
  console.error(
    'VERIFY ERROR:', error.message
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
      // Logs unavailable.
    }
  }

  process.exitCode = 1;
});
