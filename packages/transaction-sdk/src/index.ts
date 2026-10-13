import {
  PublicKey,
  SystemProgram,
  Transaction,
  TransactionInstruction,
} from '@solana/web3.js';

export const PROGRAM_ID = new PublicKey(
  'CeA1P1NSuPLUH31KsT4j3pZeBsknQZ3NSC6GUAqcsCLy'
);

export const LOCALNET_GENESIS =
  'HP9XKTusRPGC78EFDpR9xdEq6simL2vqyDdrMvn6Vacg';

const U64_MAX = (1n << 64n) - 1n;
const I64_MAX = (1n << 63n) - 1n;

type AccountMetaDefinition = {
  name: string;
  signer?: boolean;
  isSigner?: boolean;
  writable?: boolean;
  isMut?: boolean;
  address?: string;
};

type IdlField = {
  name: string;
  type: unknown;
};

type IdlDefinition = {
  name: string;
  type: {
    kind: string;
    fields?: IdlField[];
    variants?: Array<{
      name: string;
      fields?: unknown[];
    }>;
  };
};

type IdlInstruction = {
  name: string;
  discriminator: number[];
  accounts: AccountMetaDefinition[];
  args: IdlField[];
};

export type TransactionIdl = {
  address: string;
  instructions: IdlInstruction[];
  types: IdlDefinition[];
};

export interface CreateInspectionInput {
  idl: TransactionIdl;
  genesisHash: string;
  creator: PublicKey;
  tokenMint: PublicKey;
  verifier: PublicKey;
  workOrderId: Uint8Array;
  manifestHash: Uint8Array;
  requiredCapabilities: bigint;
  evidenceRequirements: bigint;
  totalAmount: bigint;
  chainNow: bigint;
  executionDeadline: bigint;
  verificationDeadline: bigint;
  recentBlockhash: string;
}

export interface CreateInspectionReview {
  network: 'localnet';
  programId: string;
  creator: string;
  protocolConfig: string;
  workOrder: string;
  workOrderIdHex: string;
  manifestHashHex: string;
  tokenMint: string;
  verifier: string;
  workType: 'Inspection';
  paymentModel: 'Fixed';
  requiredCapabilities: string;
  evidenceRequirements: string;
  totalAmountBaseUnits: string;
  executionDeadline: string;
  verificationDeadline: string;
  blockhash: string;
}

export interface CreateInspectionPlan {
  transaction: Transaction;
  unsignedBase64: string;
  review: CreateInspectionReview;
}

export interface ExternalWallet {
  publicKey: PublicKey;
  signTransaction(transaction: Transaction): Promise<Transaction>;
}

const normalize = (name: string): string =>
  name.split('::').at(-1)!
    .replace(/[^a-zA-Z0-9]/g, '')
    .toLowerCase();

function unique<T extends { name: string }>(
  items: T[],
  name: string
): T {
  if (!Array.isArray(items)) {
    throw new Error(`Missing IDL collection: ${name}`);
  }

  const matches = items.filter(
    item => normalize(item.name) === normalize(name)
  );

  if (matches.length !== 1) {
    throw new Error(`Invalid or ambiguous IDL entry: ${name}`);
  }

  return matches[0]!;
}

function checkFields(
  fields: IdlField[],
  expected: string[]
): void {
  const actual = fields.map(
    field => normalize(field.name)
  );

  if (
    actual.length !== expected.length ||
    new Set(actual).size !== expected.length ||
    expected.some(
      name => !actual.includes(normalize(name))
    )
  ) {
    throw new Error(
      `Unexpected IDL fields: ${actual.join(',')}`
    );
  }
}

function bytes32(value: Uint8Array, label: string): Buffer {
  if (!(value instanceof Uint8Array) || value.length !== 32) {
    throw new Error(`${label} must be 32 bytes`);
  }

  const result = Buffer.from(value);

  if (result.every(byte => byte === 0)) {
    throw new Error(`${label} cannot be zero`);
  }

  return result;
}

function u64(value: bigint): Buffer {
  if (typeof value !== 'bigint' ||
      value < 0n || value > U64_MAX) {
    throw new RangeError('Invalid u64');
  }

  const result = Buffer.alloc(8);
  result.writeBigUInt64LE(value);
  return result;
}

function i64(value: bigint): Buffer {
  if (
    typeof value !== 'bigint' ||
    value < -I64_MAX - 1n ||
    value > I64_MAX
  ) {
    throw new RangeError('Invalid i64');
  }

  const result = Buffer.alloc(8);
  result.writeBigInt64LE(value);
  return result;
}

function discriminator(entry: IdlInstruction): Buffer {
  const values = entry.discriminator;

  if (
    !Array.isArray(values) ||
    values.length !== 8 ||
    values.some(
      byte =>
        !Number.isInteger(byte) ||
        byte < 0 ||
        byte > 255
    )
  ) {
    throw new Error('Invalid Anchor instruction discriminator');
  }

  return Buffer.from(values);
}

function encodeValue(
  idl: TransactionIdl,
  type: unknown,
  value: unknown
): Buffer {
  if (type === 'u64') return u64(value as bigint);
  if (type === 'i64') return i64(value as bigint);

  if (type === 'pubkey' || type === 'publicKey') {
    if (!(value instanceof PublicKey)) {
      throw new Error('Expected PublicKey');
    }
    return value.toBuffer();
  }

  if (!type || typeof type !== 'object') {
    throw new Error('Unsupported Borsh type');
  }

  const definition = type as {
    array?: unknown[];
    defined?: string | { name: string };
  };

  if (definition.array !== undefined) {
    if (
      !Array.isArray(definition.array) ||
      definition.array[0] !== 'u8' ||
      definition.array[1] !== 32
    ) {
      throw new Error('Unsupported Borsh array');
    }

    return bytes32(value as Uint8Array, 'IDL bytes32');
  }

  const typeName =
    typeof definition.defined === 'string'
      ? definition.defined
      : definition.defined?.name;

  if (!typeName) {
    throw new Error('Unsupported defined type');
  }

  const schema = unique(idl.types, typeName).type;

  if (schema.kind === 'enum') {
    if (
      !Array.isArray(schema.variants) ||
      schema.variants.length > 255 ||
      schema.variants.some(v => (v.fields?.length ?? 0) > 0)
    ) {
      throw new Error(`Unsupported enum: ${typeName}`);
    }

    const index = schema.variants.findIndex(
      variant =>
        normalize(variant.name) === normalize(String(value))
    );

    if (index < 0) {
      throw new Error(`Unknown enum variant: ${String(value)}`);
    }

    return Buffer.from([index]);
  }

  if (schema.kind === 'struct') {
    if (
      !Array.isArray(schema.fields) ||
      !value ||
      typeof value !== 'object' ||
      Array.isArray(value)
    ) {
      throw new Error(`Invalid struct: ${typeName}`);
    }

    const values = value as Record<string, unknown>;

    checkFields(
      schema.fields,
      Object.keys(values)
    );

    return Buffer.concat(
      schema.fields.map(field => {
        const name = Object.keys(values).find(
          key => normalize(key) === normalize(field.name)
        );

        if (!name) {
          throw new Error(`Missing field: ${field.name}`);
        }

        return encodeValue(
          idl,
          field.type,
          values[name]
        );
      })
    );
  }

  throw new Error(`Unsupported IDL type: ${typeName}`);
}

export function buildUnsignedInspection(
  input: CreateInspectionInput
): CreateInspectionPlan {
  if (input.idl.address !== PROGRAM_ID.toBase58()) {
    throw new Error('Wrong program ID');
  }

  if (input.genesisHash !== LOCALNET_GENESIS) {
    throw new Error('Wrong Localnet genesis');
  }

  if (
    input.creator.equals(SystemProgram.programId) ||
    input.tokenMint.equals(SystemProgram.programId) ||
    input.verifier.equals(SystemProgram.programId)
  ) {
    throw new Error('Invalid default public key');
  }

  const orderId = bytes32(
    input.workOrderId, 'workOrderId'
  );

  const manifest = bytes32(
    input.manifestHash, 'manifestHash'
  );

  for (const value of [
    input.requiredCapabilities,
    input.evidenceRequirements,
    input.totalAmount,
  ]) {
    if (typeof value !== 'bigint' || value <= 0n || value > U64_MAX) {
      throw new RangeError('Invalid economic or capability value');
    }
  }

  for (const value of [
    input.chainNow,
    input.executionDeadline,
    input.verificationDeadline,
  ]) {
    i64(value);
  }

  if (
    input.executionDeadline <= input.chainNow ||
    input.verificationDeadline <= input.executionDeadline
  ) {
    throw new RangeError('Invalid WorkOrder deadlines');
  }

  // Confirm blockhash has the Solana blockhash shape.
  new PublicKey(input.recentBlockhash);

  const create = unique(
    input.idl.instructions,
    'create_work_order'
  );

  checkFields(create.args, ['args']);

  const argType = create.args[0]!.type as {
    defined?: string | { name: string };
  };

  const argName =
    typeof argType?.defined === 'string'
      ? argType.defined
      : argType?.defined?.name;

  if (normalize(argName ?? '') !== 'createworkorderargs') {
    throw new Error('Unexpected CreateWorkOrderArgs');
  }

  const createSchema = unique(
    input.idl.types,
    'CreateWorkOrderArgs'
  ).type;

  const settlementSchema = unique(
    input.idl.types,
    'SettlementTerms'
  ).type;

  if (
    createSchema.kind !== 'struct' ||
    settlementSchema.kind !== 'struct' ||
    !createSchema.fields ||
    !settlementSchema.fields
  ) {
    throw new Error('Unexpected IDL structs');
  }

  checkFields(createSchema.fields, [
    'work_order_id',
    'work_type',
    'required_capabilities',
    'evidence_requirements',
    'manifest_hash',
    'settlement',
    'execution_deadline',
    'verification_deadline',
  ]);

  checkFields(settlementSchema.fields, [
    'token_mint',
    'total_amount',
    'payment_model',
    'verifier',
  ]);

  const [configPda] = PublicKey.findProgramAddressSync(
    [Buffer.from('protocol_config')],
    PROGRAM_ID
  );

  const [workOrderPda] = PublicKey.findProgramAddressSync(
    [
      Buffer.from('work_order'),
      configPda.toBuffer(),
      input.creator.toBuffer(),
      orderId,
    ],
    PROGRAM_ID
  );

  const mapping: Record<string, PublicKey> = {
    protocolconfig: configPda,
    workorder: workOrderPda,
    creator: input.creator,
    systemprogram: SystemProgram.programId,
  };

  if (
    !Array.isArray(create.accounts) ||
    create.accounts.length !== 4 ||
    new Set(
      create.accounts.map(meta => normalize(meta.name))
    ).size !== 4 ||
    Object.keys(mapping).some(
      name => !create.accounts.some(
        meta => normalize(meta.name) === name
      )
    )
  ) {
    throw new Error('Unexpected create_work_order accounts');
  }

  const keys = create.accounts.map(meta => {
    const name = normalize(meta.name);
    const pubkey = mapping[name]!;

    const isSigner = Boolean(
      meta.signer ?? meta.isSigner
    );

    const isWritable = Boolean(
      meta.writable ?? meta.isMut
    );

    if (
      (meta.address && meta.address !== pubkey.toBase58()) ||
      isSigner !== (name === 'creator') ||
      (name === 'workorder' && !isWritable) ||
      (name === 'creator' && !isWritable) ||
      (name === 'systemprogram' && isWritable)
    ) {
      throw new Error(`Unsafe account metadata: ${name}`);
    }

    return { pubkey, isSigner, isWritable };
  });

  const data = Buffer.concat([
    discriminator(create),
    encodeValue(input.idl, create.args[0]!.type, {
      work_order_id: orderId,
      work_type: 'Inspection',
      required_capabilities: input.requiredCapabilities,
      evidence_requirements: input.evidenceRequirements,
      manifest_hash: manifest,
      settlement: {
        token_mint: input.tokenMint,
        total_amount: input.totalAmount,
        payment_model: 'Fixed',
        verifier: input.verifier,
      },
      execution_deadline: input.executionDeadline,
      verification_deadline: input.verificationDeadline,
    }),
  ]);

  const transaction = new Transaction({
    feePayer: input.creator,
    recentBlockhash: input.recentBlockhash,
  }).add(
    new TransactionInstruction({
      programId: PROGRAM_ID,
      keys,
      data,
    })
  );

  const unsignedBase64 = transaction.serialize({
    requireAllSignatures: false,
    verifySignatures: false,
  }).toString('base64');

  return {
    transaction,
    unsignedBase64,
    review: {
      network: 'localnet',
      programId: PROGRAM_ID.toBase58(),
      creator: input.creator.toBase58(),
      protocolConfig: configPda.toBase58(),
      workOrder: workOrderPda.toBase58(),
      workOrderIdHex: orderId.toString('hex'),
      manifestHashHex: manifest.toString('hex'),
      tokenMint: input.tokenMint.toBase58(),
      verifier: input.verifier.toBase58(),
      workType: 'Inspection',
      paymentModel: 'Fixed',
      requiredCapabilities:
        input.requiredCapabilities.toString(),
      evidenceRequirements:
        input.evidenceRequirements.toString(),
      totalAmountBaseUnits:
        input.totalAmount.toString(),
      executionDeadline:
        input.executionDeadline.toString(),
      verificationDeadline:
        input.verificationDeadline.toString(),
      blockhash: input.recentBlockhash,
    },
  };
}

/**
 * Wallet integration boundary:
 * signs an EXACT copy of the reviewed transaction.
 * Does not broadcast, confirm, or persist a transaction.
 */
export async function signReviewedTransaction(
  plan: CreateInspectionPlan,
  wallet: ExternalWallet
): Promise<Transaction> {
  if (
    !wallet.publicKey.equals(plan.transaction.feePayer!) ||
    !wallet.signTransaction
  ) {
    throw new Error('Connected wallet is not the creator');
  }

  const originalMessage = Buffer.from(
    plan.transaction.serializeMessage()
  );

  const copy = Transaction.from(
    Buffer.from(plan.unsignedBase64, 'base64')
  );

  if (!Buffer.from(copy.serializeMessage()).equals(originalMessage)) {
    throw new Error('Unsigned transaction was modified');
  }

  const signed = await wallet.signTransaction(copy);

  if (
    !(signed instanceof Transaction) ||
    !Buffer.from(signed.serializeMessage()).equals(originalMessage) ||
    !signed.verifySignatures(true)
  ) {
    throw new Error('Wallet changed the message or signature is invalid');
  }

  return signed;
}
