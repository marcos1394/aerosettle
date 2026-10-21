'use strict';

const fs = require('node:fs');
const path = require('node:path');
const os = require('node:os');
const crypto = require('node:crypto');
const cp = require('node:child_process');

const {
  Connection, Keypair, PublicKey, SystemProgram,
  Transaction, TransactionInstruction,
  sendAndConfirmTransaction,
} = require('@solana/web3.js');

const {
  TOKEN_PROGRAM_ID, getAccount, getMint,
  createAccount, getOrCreateAssociatedTokenAccount,
} = require('@solana/spl-token');

const RPC = 'http://127.0.0.1:8899';
const TAG = 'target-submitted';

const TARGET =
  'EnkZQWDqF5HeFeusZ7xnj7tngVN9xASofmKvXtDLeqbx';

const PROGRAM =
  'CeA1P1NSuPLUH31KsT4j3pZeBsknQZ3NSC6GUAqcsCLy';

const GENESIS =
  'HP9XKTusRPGC78EFDpR9xdEq6simL2vqyDdrMvn6Vacg';

const AMOUNT = 10_000_000n;

const MODE = process.argv[2] || '--inspect';

const MODES = [
  '--inspect', '--prepare', '--negative', '--simulate',
  '--settle', '--verify', '--simulate-close', '--close', '--verify-close',
];

if (!MODES.includes(MODE)) {
  throw Error('Modo inválido: ' + MODE);
}

const idl = JSON.parse(
  fs.readFileSync(
    'target/idl/aerosettle.discovery.json', 'utf8'
  )
);

if (idl.address !== PROGRAM) {
  throw Error('Program ID del IDL incorrecto');
}

const norm = s => String(s)
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

function disc(item) {
  const data = item.discriminator;

  if (
    !Array.isArray(data) ||
    data.length !== 8 ||
    data.some(
      x => !Number.isInteger(x) || x < 0 || x > 255
    )
  ) {
    throw Error('Discriminador inválido: ' + item.name);
  }

  return Buffer.from(data);
}

const settleIx = exactly(
  idl.instructions, 'settle_work_order'
);

const closeIx = exactly(
  idl.instructions, 'close_settled_vault'
);

function validateInstruction(ix, expected) {
  if (
    !Array.isArray(ix.args) ||
    ix.args.length !== 0 ||
    !Array.isArray(ix.accounts) ||
    ix.accounts.length !== expected.length ||
    ix.accounts.some(x => Array.isArray(x.accounts))
  ) {
    throw Error('IDL incompatible: ' + ix.name);
  }

  const actual = ix.accounts.map(
    x => norm(x.name)
  );

  if (
    new Set(actual).size !== expected.length ||
    expected.some(x => !actual.includes(norm(x)))
  ) {
    throw Error(
      'Cuentas incompatibles: ' + ix.name +
      ' -> ' + JSON.stringify(actual)
    );
  }

  if (
    ix.accounts.some(x =>
      x.signer === true || x.isSigner === true
    )
  ) {
    throw Error(
      'Firma inesperada en instrucción: ' + ix.name
    );
  }

  disc(ix);
}

validateInstruction(settleIx, [
  'protocol_config',
  'work_order',
  'escrow_vault',
  'mint',
  'operator_token_account',
  'creator_refund_token_account',
  'token_program',
]);

validateInstruction(closeIx, [
  'protocol_config',
  'work_order',
  'escrow_vault',
  'mint',
  'creator',
  'creator_refund_token_account',
  'token_program',
]);

const programId = new PublicKey(PROGRAM);
const connection = new Connection(RPC, 'confirmed');

const wallet = Keypair.fromSecretKey(
  Uint8Array.from(JSON.parse(
    fs.readFileSync(
      path.join(os.homedir(), '.config/solana/id.json'),
      'utf8'
    )
  ))
);

const hash = data =>
  crypto.createHash('sha256')
    .update(data)
    .digest('hex');

const suffix = hash(
  GENESIS + wallet.publicKey.toBase58() + TAG
).slice(0, 12);

const directory =
  '.aerosettle-local/bootstrap/keys';

const payoutFile =
  `${directory}/settlement-payout-${suffix}.json`;

const wrongFile =
  `${directory}/settlement-wrong-${suffix}.json`;

const baselineFile =
  `.aerosettle-local/settlement-baseline-${TAG}.json`;

const closeFile =
  `.aerosettle-local/vault-close-${TAG}.json`;

function readOrCreateKey(file, create) {
  if (fs.existsSync(file)) {
    const values = JSON.parse(
      fs.readFileSync(file, 'utf8')
    );

    if (
      !Array.isArray(values) ||
      values.length !== 64 ||
      values.some(x =>
        !Number.isInteger(x) || x < 0 || x > 255
      )
    ) {
      throw Error('Keypair inválido: ' + file);
    }

    return Keypair.fromSecretKey(
      Uint8Array.from(values)
    );
  }

  if (!create) return null;

  fs.mkdirSync(directory, {
    recursive: true,
    mode: 0o700,
  });

  fs.chmodSync(directory, 0o700);

  const pair = Keypair.generate();

  fs.writeFileSync(
    file,
    JSON.stringify(Array.from(pair.secretKey)) + '\n',
    {
      flag: 'wx',
      mode: 0o600,
    }
  );

  return pair;
}

function readContext() {
  cp.execFileSync(
    'python3.11',
    ['tools/settlement/target_settlement_context.py'],
    {stdio: 'inherit'}
  );

  return JSON.parse(
    fs.readFileSync(
      `.aerosettle-local/settlement-context-${TAG}.json`,
      'utf8'
    )
  );
}

function makeIx(definition, mapping) {
  const keys = definition.accounts.map(meta => {
    const address = mapping[norm(meta.name)];

    if (!address) {
      throw Error(
        'Cuenta desconocida: ' + meta.name
      );
    }

    if (
      meta.address &&
      meta.address !== address.toBase58()
    ) {
      throw Error(
        'Dirección fija incorrecta: ' + meta.name
      );
    }

    return {
      pubkey: address,
      isSigner: false,
      isWritable: Boolean(
        meta.writable ?? meta.isMut
      ),
    };
  });

  return new TransactionInstruction({
    programId,
    keys,
    data: disc(definition),
  });
}

async function simulate(instruction) {
  const latest = await connection.getLatestBlockhash(
    'confirmed'
  );

  const tx = new Transaction({
    feePayer: wallet.publicKey,
    recentBlockhash: latest.blockhash,
  }).add(instruction);

  return (
    await connection.simulateTransaction(
      tx, [wallet]
    )
  ).value;
}

async function send(instruction) {
  return sendAndConfirmTransaction(
    connection,
    new Transaction().add(instruction),
    [wallet],
    {
      commitment: 'confirmed',
      preflightCommitment: 'confirmed',
    }
  );
}

function saveOnce(file, data) {
  if (fs.existsSync(file)) {
    const original = JSON.parse(
      fs.readFileSync(file, 'utf8')
    );

    if (
      original.genesis !== data.genesis ||
      original.order !== data.order ||
      original.payout !== data.payout ||
      original.refund !== data.refund
    ) {
      throw Error(
        'Snapshot incompatible: ' + file
      );
    }

    return original;
  }

  fs.writeFileSync(
    file,
    JSON.stringify(data, null, 2) + '\n',
    {flag: 'wx', mode: 0o600}
  );

  return data;
}

function loadBaseline() {
  if (!fs.existsSync(baselineFile)) {
    throw Error(
      'Falta baseline; no se verificará dinero sin estado previo'
    );
  }

  return JSON.parse(
    fs.readFileSync(baselineFile, 'utf8')
  );
}

async function tokenAt(address, owner, mint) {
  const account = await getAccount(
    connection, address, 'confirmed',
    TOKEN_PROGRAM_ID
  );

  if (
    !account.owner.equals(owner) ||
    !account.mint.equals(mint)
  ) {
    throw Error(
      'Cuenta SPL con owner/mint inesperados: ' +
      address.toBase58()
    );
  }

  return account;
}

async function main() {
  if (
    await connection.getGenesisHash() !== GENESIS
  ) {
    throw Error('Ledger equivocado');
  }

  const deployed = await connection.getAccountInfo(
    programId, 'confirmed'
  );

  if (!deployed?.executable) {
    throw Error('AeroSettle no está desplegado');
  }

  const ctx = readContext();

  if (ctx.work_order !== TARGET) {
    throw Error('Target WorkOrder incorrecta');
  }

  const creator = new PublicKey(ctx.creator);
  const beneficiary = new PublicKey(
    ctx.settlement_beneficiary
  );
  const mint = new PublicKey(ctx.token_mint);

  if (
    ctx.genesis !== GENESIS ||
    ctx.owner !== wallet.publicKey.toBase58() ||
    !['Fixed', 'Proportional'].includes(ctx.payment_model) ||
    BigInt(ctx.total_amount) !== AMOUNT
  ) {
    throw Error('Contexto económico incompatible');
  }

  const [config] = PublicKey.findProgramAddressSync(
    [Buffer.from('protocol_config')], programId
  );

  const workOrder = new PublicKey(
    ctx.work_order
  );

  if (ctx.protocol_config !== config.toBase58()) {
    throw Error('ProtocolConfig incorrecto');
  }

  const [vault] = PublicKey.findProgramAddressSync(
    [
      Buffer.from('escrow'),
      workOrder.toBuffer(),
    ],
    programId
  );

  if (
    ctx.escrow_vault !== vault.toBase58() ||
    ctx.token_program !== TOKEN_PROGRAM_ID.toBase58()
  ) {
    throw Error('Vault o Token Program incompatible');
  }

  const mintState = await getMint(
    connection, mint, 'confirmed',
    TOKEN_PROGRAM_ID
  );

  if (mintState.decimals !== 6) {
    throw Error('El mint no tiene 6 decimales');
  }

  const payoutKey = readOrCreateKey(
    payoutFile, MODE === '--prepare'
  );

  const wrongKey = readOrCreateKey(
    wrongFile, MODE === '--prepare'
  );

  const refundAddress = await (
    async () => {
      const {
        getAssociatedTokenAddressSync
      } = require('@solana/spl-token');

      return getAssociatedTokenAddressSync(
        mint, creator, false, TOKEN_PROGRAM_ID
      );
    }
  )();

  console.log('\n=== AEROSETTLE SETTLEMENT ===');
  console.log('Mode:', MODE);
  console.log('Status:', ctx.status);
  console.log('WorkOrder:', workOrder.toBase58());
  console.log('Escrow:', vault.toBase58());
  console.log('Mint:', mint.toBase58());
  console.log('Creator:', creator.toBase58());
  console.log('Beneficiary:', beneficiary.toBase58());
  console.log('Amount:', AMOUNT.toString());

  if (MODE === '--inspect') {
    console.log('Payout:', payoutKey?.publicKey.toBase58() || '(pendiente)');
    console.log('Refund:', refundAddress.toBase58());
    console.log('✅ IDL y contexto económico inspeccionados');
    return;
  }

  if (MODE === '--prepare') {
    if (ctx.status !== 'Verified') {
      throw Error('La orden ya no está Verified');
    }

    for (const [pair, owner] of [
      [payoutKey, beneficiary],
      [wrongKey, SystemProgram.programId],
    ]) {
      const existing = await connection.getAccountInfo(
        pair.publicKey, 'confirmed'
      );

      if (!existing) {
        await createAccount(
          connection,
          wallet,
          mint,
          owner,
          pair,
          {commitment: 'confirmed'},
          TOKEN_PROGRAM_ID
        );
      }

      await tokenAt(pair.publicKey, owner, mint);
    }

    const refund = await getOrCreateAssociatedTokenAccount(
      connection,
      wallet,
      mint,
      creator,
      false,
      'confirmed',
      {commitment: 'confirmed'},
      TOKEN_PROGRAM_ID
    );

    if (!refund.address.equals(refundAddress)) {
      throw Error('ATA de reembolso inesperada');
    }

    console.log('Payout:', payoutKey.publicKey.toBase58());
    console.log('Refund:', refundAddress.toBase58());
    console.log('Wrong destination:', wrongKey.publicKey.toBase58());
    console.log('✅ Cuentas SPL preparadas');
    return;
  }

  if (!payoutKey || !wrongKey) {
    throw Error('Ejecuta --prepare primero');
  }

  const payout = payoutKey.publicKey;
  const wrong = wrongKey.publicKey;
  const refund = refundAddress;

  if (payout.equals(refund)) {
    throw Error('Payout y refund no pueden ser la misma cuenta');
  }

  await tokenAt(payout, beneficiary, mint);
  await tokenAt(refund, creator, mint);
  await tokenAt(wrong, SystemProgram.programId, mint);

  const mapping = {
    protocolconfig: config,
    workorder: workOrder,
    escrowvault: vault,
    mint,
    operatortokenaccount: payout,
    creatorrefundtokenaccount: refund,
    creator,
    tokenprogram: TOKEN_PROGRAM_ID,
  };

  const settleInstruction = makeIx(
    settleIx, mapping
  );

  if (MODE === '--negative') {
    if (ctx.status !== 'Verified') {
      throw Error('Se esperaba Verified');
    }

    const malicious = makeIx(
      settleIx,
      {...mapping, operatortokenaccount: wrong}
    );

    const result = await simulate(malicious);

    console.log(
      'Negative simulation:',
      JSON.stringify(result.err)
    );

    const logs = (result.logs || []).join('\n');
    console.log(logs);

    if (
      !result.err ||
      !/beneficiary|operator|destination|settlementinvalid/i.test(
        logs
      )
    ) {
      throw Error(
        'No se confirmó un rechazo por destino económico incorrecto'
      );
    }

    console.log('✅ Desvío de pago rechazado por el contrato');
    return;
  }

  if (MODE === '--settle' || MODE === '--simulate') {
    if (ctx.status === 'Settled') {
      console.log('Orden ya Settled; no se liquida dos veces');
      return;
    }

    if (ctx.status !== 'Verified') {
      throw Error('Se requiere estado Verified');
    }

    const vaultState = await tokenAt(
      vault, vault, mint
    );

    if (vaultState.amount !== AMOUNT) {
      throw Error('Escrow no contiene exactamente 10 tokens');
    }

    const payoutBefore = (
      await tokenAt(payout, beneficiary, mint)
    ).amount;

    const refundBefore = (
      await tokenAt(refund, creator, mint)
    ).amount;

    const simulation = await simulate(
      settleInstruction
    );

    if (simulation.err) {
      console.log(
        (simulation.logs || []).join('\n')
      );

      throw Error('Settlement simulation falló');
    }

    const baseline = saveOnce(baselineFile, {
      genesis: GENESIS,
      order: workOrder.toBase58(),
      payout: payout.toBase58(),
      refund: refund.toBase58(),
      payout_before: payoutBefore.toString(),
      refund_before: refundBefore.toString(),
      vault_before: vaultState.amount.toString(),
      amount: AMOUNT.toString(),
    });

    if (
      BigInt(baseline.payout_before) !== payoutBefore ||
      BigInt(baseline.refund_before) !== refundBefore ||
      BigInt(baseline.vault_before) !== vaultState.amount
    ) {
      throw Error(
        'Los saldos cambiaron respecto del baseline guardado'
      );
    }

    console.log('✅ Simulación positiva aprobada');
    console.log('Baseline:', baselineFile);

    if (MODE === '--simulate') {
      console.log('✅ Settlement simulation passed');
      console.log('Transactions sent: 0');
      return;
    }

    const signature = await send(
      settleInstruction
    );

    console.log('Transaction:', signature);
    console.log('✅ Settlement enviado');
  }

  if (
    MODE === '--verify' ||
    MODE === '--settle' ||
    MODE === '--close' ||
    MODE === '--simulate-close' ||
    MODE === '--verify-close'
  ) {
    const latest = MODE === '--settle'
      ? readContext()
      : ctx;

    if (latest.status !== 'Settled') {
      throw Error('WorkOrder no está Settled');
    }

    const baseline = loadBaseline();

    if (
      baseline.genesis !== GENESIS ||
      baseline.order !== workOrder.toBase58() ||
      baseline.payout !== payout.toBase58() ||
      baseline.refund !== refund.toBase58() ||
      BigInt(baseline.vault_before) !== AMOUNT
    ) {
      throw Error('Baseline incompatible');
    }

    const payoutAfter = (
      await tokenAt(payout, beneficiary, mint)
    ).amount;

    const refundAfter = (
      await tokenAt(refund, creator, mint)
    ).amount;

    const paid =
      payoutAfter - BigInt(baseline.payout_before);

    const refunded =
      refundAfter - BigInt(baseline.refund_before);

    console.log('Pago al operador:', paid.toString());
    console.log('Reembolso al creador:', refunded.toString());

    if (paid !== AMOUNT || refunded !== 0n) {
      throw Error(
        'La distribución no corresponde a Fixed + Accepted 100%'
      );
    }

    const vaultInfo = await connection.getAccountInfo(
      vault, 'confirmed'
    );

    if (
      MODE === '--verify-close' ||
      MODE === '--close' && !vaultInfo
    ) {
      if (vaultInfo) {
        throw Error('El vault todavía existe');
      }

      console.log('✅ Vault cerrado');
      console.log('✅ Distribution conservada');
      return;
    }

    if (!vaultInfo) {
      throw Error('Vault ausente; usa --verify-close');
    }

    const vaultState = await tokenAt(
      vault, vault, mint
    );

    if (vaultState.amount !== 0n) {
      throw Error('El escrow no quedó vacío');
    }

    console.log('✅ WorkOrder Settled');
    console.log('✅ Escrow vacío');
    console.log('✅ Payout y refund comprobados');

    if (
      MODE !== '--close' &&
      MODE !== '--simulate-close'
    ) return;

    const closeInstruction = makeIx(
      closeIx, mapping
    );

    const simulation = await simulate(
      closeInstruction
    );

    if (simulation.err) {
      console.log(
        (simulation.logs || []).join('\n')
      );
      throw Error('Simulación de cierre falló');
    }

    console.log('✅ Vault close simulation passed');

    if (MODE === '--simulate-close') {
      console.log('Transactions sent: 0');
      return;
    }

    const creatorBefore = await connection.getBalance(
      creator, 'confirmed'
    );

    const closeProof = saveOnce(closeFile, {
      genesis: GENESIS,
      order: workOrder.toBase58(),
      payout: payout.toBase58(),
      refund: refund.toBase58(),
      vault_rent: String(vaultInfo.lamports),
      creator_lamports_before: String(creatorBefore),
    });

    console.log(
      'Renta SOL del vault:',
      closeProof.vault_rent,
      'lamports'
    );

    const signature = await send(
      closeInstruction
    );

    console.log('Close transaction:', signature);

    const remaining = await connection.getAccountInfo(
      vault, 'confirmed'
    );

    if (remaining !== null) {
      throw Error('Vault sigue existiendo después del cierre');
    }

    console.log('✅ Vault SPL cerrado');
    console.log('✅ Renta liberada al creador');
  }
}

main().catch(async error => {
  console.error('SETTLEMENT ERROR:', error.message);

  if (Array.isArray(error.logs)) {
    console.error(error.logs.join('\n'));
  } else if (typeof error.getLogs === 'function') {
    try {
      console.error(
        (await error.getLogs(connection)).join('\n')
      );
    } catch {
      // RPC logs no disponibles.
    }
  }

  process.exitCode = 1;
});
