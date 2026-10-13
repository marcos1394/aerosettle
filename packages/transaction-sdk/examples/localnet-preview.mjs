import fs from 'node:fs';
import crypto from 'node:crypto';
import path from 'node:path';
import { execFileSync } from 'node:child_process';

import {
  Connection,
  PublicKey,
  SYSVAR_CLOCK_PUBKEY,
  Transaction,
} from '@solana/web3.js';

import {
  buildUnsignedInspection,
  PROGRAM_ID,
  LOCALNET_GENESIS,
} from '../dist/index.js';

const root = path.resolve(
  import.meta.dirname,
  '../../..'
);

const rpcUrl = 'http://127.0.0.1:8899';

const connection = new Connection(
  rpcUrl,
  'confirmed'
);

const mint = new PublicKey(
  'HTHpns7gqLAhSBhAzqxhYdyHv9HeXkkRW6aHQfdUjL1G'
);

const verifier = new PublicKey(
  'DmWQhuVujHrJb4jFzo62UnCT3mwnx9GFtVdo8VUu82Wu'
);

const idl = JSON.parse(
  fs.readFileSync(
    path.join(
      root, 'target/idl/aerosettle.discovery.json'
    ),
    'utf8'
  )
);

const masks = JSON.parse(
  fs.readFileSync(
    path.join(
      root,
      '.aerosettle-local/bootstrap-capabilities.json'
    ),
    'utf8'
  )
);

const evidence = JSON.parse(
  fs.readFileSync(
    path.join(
      root,
      '.aerosettle-local/bootstrap-evidence.json'
    ),
    'utf8'
  )
);

async function main() {
  console.log('=== AEROSETTLE TRANSACTION PREVIEW ===');

  const genesis = await connection.getGenesisHash();

  if (genesis !== LOCALNET_GENESIS) {
    throw new Error(
      'El RPC apunta a otro ledger'
    );
  }

  const deployed = await connection.getAccountInfo(
    PROGRAM_ID, 'confirmed'
  );

  if (!deployed?.executable) {
    throw new Error(
      'AeroSettle no está desplegado en Localnet'
    );
  }

  const ownerAddress = execFileSync(
    'solana',
    ['address'],
    {encoding: 'utf8'}
  ).trim();

  const creator = new PublicKey(ownerAddress);

  const clock = await connection.getAccountInfo(
    SYSVAR_CLOCK_PUBKEY,
    'confirmed'
  );

  if (!clock || clock.data.length < 40) {
    throw new Error('Clock sysvar inválida');
  }

  const chainNow = clock.data.readBigInt64LE(32);

  const latest = await connection.getLatestBlockhash(
    'confirmed'
  );

  const workOrderId = crypto.randomBytes(32);

  const manifestHash = crypto
    .createHash('sha256')
    .update(
      'aerosettle:localnet:synthetic-inspection:'
      + workOrderId.toString('hex')
    )
    .digest();

  const plan = buildUnsignedInspection({
    idl,
    genesisHash: genesis,
    creator,
    tokenMint: mint,
    verifier,
    workOrderId,
    manifestHash,
    requiredCapabilities:
      BigInt(masks.aerial) | BigInt(masks.gps),
    evidenceRequirements:
      BigInt(evidence.mask),
    totalAmount: 10_000_000n,
    chainNow,
    executionDeadline: chainNow + 7200n,
    verificationDeadline: chainNow + 14400n,
    recentBlockhash: latest.blockhash,
  });

  // Verify the unsigned wire representation.
  const decoded = Transaction.from(
    Buffer.from(plan.unsignedBase64, 'base64')
  );

  if (
    decoded.instructions.length !== 1 ||
    !decoded.instructions[0].programId.equals(
      PROGRAM_ID
    ) ||
    decoded.signatures.some(
      item => item.signature !== null
    ) ||
    !decoded.feePayer?.equals(creator)
  ) {
    throw new Error(
      'La transacción no cumple el contrato unsigned'
    );
  }

  console.log('Genesis:', genesis);
  console.log('Creator:', creator.toBase58());
  console.log('WorkOrder propuesta:', plan.review.workOrder);
  console.log(
    'Monto base:',
    plan.review.totalAmountBaseUnits
  );
  console.log(
    'Capacidades:',
    plan.review.requiredCapabilities
  );
  console.log(
    'Execution deadline:',
    plan.review.executionDeadline
  );
  console.log('Número de instrucciones:', 1);
  console.log('Firmas aplicadas:', 0);

  const output = path.join(
    root,
    '.aerosettle-local/unsigned-create-inspection-preview.json'
  );

  fs.mkdirSync(
    path.dirname(output),
    {recursive: true}
  );

  fs.writeFileSync(
    output,
    JSON.stringify({
      schema: 'aerosettle.localnet.unsigned-preview.v1',
      synthetic: true,
      broadcasted: false,
      review: plan.review,
      unsignedTransactionBase64: plan.unsignedBase64,
      lastValidBlockHeight:
        latest.lastValidBlockHeight,
    }, null, 2) + '\n',
    {mode: 0o600}
  );

  console.log('Preview:', output);
  console.log('✅ EPIC 3.4.1 UNSIGNED PREVIEW VERIFIED');
  console.log('✅ NO TRANSACTION BROADCAST');
}

main().catch(error => {
  console.error('PREVIEW ERROR:', error.message);
  process.exitCode = 1;
});
