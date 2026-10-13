import test from 'node:test';
import assert from 'node:assert/strict';

import {
  Keypair,
  PublicKey,
  Transaction,
} from '@solana/web3.js';

import {
  buildUnsignedInspection,
  signReviewedTransaction,
  LOCALNET_GENESIS,
  PROGRAM_ID,
} from '../dist/index.js';

const creator = Keypair.generate();
const mint = Keypair.generate().publicKey;
const verifier = Keypair.generate().publicKey;

const bytes = value => new Uint8Array(32).fill(value);

function idl() {
  return {
    address: PROGRAM_ID.toBase58(),
    instructions: [{
      name: 'create_work_order',
      discriminator: [1, 2, 3, 4, 5, 6, 7, 8],
      accounts: [
        {
          name: 'protocol_config',
          signer: false,
          writable: false
        },
        {
          name: 'work_order',
          signer: false,
          writable: true
        },
        {
          name: 'creator',
          signer: true,
          writable: true
        },
        {
          name: 'system_program',
          signer: false,
          writable: false
        }
      ],
      args: [{
        name: 'args',
        type: { defined: { name: 'CreateWorkOrderArgs' } }
      }]
    }],
    types: [
      {
        name: 'CreateWorkOrderArgs',
        type: {
          kind: 'struct',
          fields: [
            { name: 'work_order_id', type: { array: ['u8', 32] } },
            { name: 'work_type', type: { defined: { name: 'WorkType' } } },
            { name: 'required_capabilities', type: 'u64' },
            { name: 'evidence_requirements', type: 'u64' },
            { name: 'manifest_hash', type: { array: ['u8', 32] } },
            { name: 'settlement', type: { defined: { name: 'SettlementTerms' } } },
            { name: 'execution_deadline', type: 'i64' },
            { name: 'verification_deadline', type: 'i64' }
          ]
        }
      },
      {
        name: 'SettlementTerms',
        type: {
          kind: 'struct',
          fields: [
            { name: 'token_mint', type: 'pubkey' },
            { name: 'total_amount', type: 'u64' },
            { name: 'payment_model', type: { defined: { name: 'PaymentModel' } } },
            { name: 'verifier', type: 'pubkey' }
          ]
        }
      },
      {
        name: 'WorkType',
        type: {
          kind: 'enum',
          variants: [
            { name: 'Delivery' },
            { name: 'Inspection' }
          ]
        }
      },
      {
        name: 'PaymentModel',
        type: {
          kind: 'enum',
          variants: [
            { name: 'Fixed' },
            { name: 'Proportional' }
          ]
        }
      }
    ]
  };
}

function input() {
  return {
    idl: idl(),
    genesisHash: LOCALNET_GENESIS,
    creator: creator.publicKey,
    tokenMint: mint,
    verifier,
    workOrderId: bytes(11),
    manifestHash: bytes(22),
    requiredCapabilities: 33n,
    evidenceRequirements: 15n,
    totalAmount: 10_000_000n,
    chainNow: 1000n,
    executionDeadline: 3000n,
    verificationDeadline: 6000n,
    recentBlockhash: new PublicKey(bytes(9)).toBase58(),
  };
}

test('builds exactly one unsigned Anchor instruction', () => {
  const plan = buildUnsignedInspection(input());
  const tx = Transaction.from(
    Buffer.from(plan.unsignedBase64, 'base64')
  );

  assert.equal(tx.instructions.length, 1);
  assert.equal(
    tx.instructions[0].programId.toBase58(),
    PROGRAM_ID.toBase58()
  );
  assert.equal(tx.instructions[0].data.length, 178);
  assert.equal(tx.signatures.length, 1);
  assert.equal(tx.signatures[0].signature, null);
});

test('WorkOrder PDA and preview are deterministic', () => {
  const a = buildUnsignedInspection(input());
  const b = buildUnsignedInspection(input());

  assert.equal(
    a.review.workOrder,
    b.review.workOrder
  );

  assert.equal(a.unsignedBase64, b.unsignedBase64);
  assert.equal(a.review.totalAmountBaseUnits, '10000000');
  assert.equal(a.review.requiredCapabilities, '33');
});

test('creator is the only required signer', () => {
  const plan = buildUnsignedInspection(input());

  const keys = plan.transaction.instructions[0].keys;
  const signers = keys.filter(item => item.isSigner);

  assert.equal(signers.length, 1);
  assert.equal(
    signers[0].pubkey.toBase58(),
    creator.publicKey.toBase58()
  );
});

test('wrong genesis and wrong program are rejected', () => {
  assert.throws(
    () => buildUnsignedInspection({
      ...input(),
      genesisHash: 'wrong',
    }),
    /genesis/
  );

  assert.throws(
    () => buildUnsignedInspection({
      ...input(),
      idl: {
        ...idl(),
        address: mint.toBase58()
      },
    }),
    /program ID/
  );
});

test('invalid amounts, masks and deadlines are rejected', () => {
  assert.throws(
    () => buildUnsignedInspection({
      ...input(),
      totalAmount: 0n
    })
  );

  assert.throws(
    () => buildUnsignedInspection({
      ...input(),
      requiredCapabilities: 2n ** 64n
    })
  );

  assert.throws(
    () => buildUnsignedInspection({
      ...input(),
      verificationDeadline: 2000n
    })
  );
});

test('unsafe account metadata is rejected', () => {
  const schema = idl();

  schema.instructions[0].accounts[2].signer = false;

  assert.throws(
    () => buildUnsignedInspection({
      ...input(),
      idl: schema
    }),
    /Unsafe account metadata/
  );
});

test('missing IDL fields are rejected', () => {
  const schema = idl();

  schema.types[0].type.fields.pop();

  assert.throws(
    () => buildUnsignedInspection({
      ...input(),
      idl: schema
    }),
    /Unexpected IDL fields/
  );
});

test('external wallet signs but does not broadcast', async () => {
  const plan = buildUnsignedInspection(input());

  const wallet = {
    publicKey: creator.publicKey,
    async signTransaction(tx) {
      tx.sign(creator);
      return tx;
    }
  };

  const signed = await signReviewedTransaction(
    plan, wallet
  );

  assert.equal(signed.verifySignatures(), true);
  assert.equal(
    signed.instructions.length,
    plan.transaction.instructions.length
  );

  assert.equal(
    plan.transaction.signatures.every(
      item => item.signature === null
    ),
    true
  );
});

test('message mutation by wallet is rejected', async () => {
  const plan = buildUnsignedInspection(input());

  const wallet = {
    publicKey: creator.publicKey,
    async signTransaction(tx) {
      tx.recentBlockhash =
        Keypair.generate().publicKey.toBase58();

      tx.sign(creator);
      return tx;
    }
  };

  await assert.rejects(
    signReviewedTransaction(plan, wallet),
    /changed the message/
  );
});

test('wrong wallet cannot sign the reviewed plan', async () => {
  const plan = buildUnsignedInspection(input());

  const other = Keypair.generate();

  await assert.rejects(
    signReviewedTransaction(plan, {
      publicKey: other.publicKey,
      async signTransaction(tx) {
        tx.sign(other);
        return tx;
      }
    }),
    /not the creator/
  );
});
