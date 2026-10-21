import { Buffer } from 'buffer';
import { PublicKey, type AccountInfo, type Connection } from '@solana/web3.js';
import localIdl from '../localnet-idl.json';
import { PROGRAM_ID } from './config';
// Read-only IDL decoding. This module never constructs, signs or sends instructions.
type Type =
  | string
  | { array: [string, number] }
  | { defined: { name: string } }
  | { option: Type };
type Definition = {
  name: string;
  type: {
    kind: string;
    fields?: { name: string; type: Type }[];
    variants?: { name: string; fields?: unknown[] }[];
  };
};
const definitions = localIdl.types as Definition[];
const encoder = new TextEncoder();
export async function decodeAccount(
  info: AccountInfo<Buffer> | null,
  address: string,
  kind: 'AgentAccount' | 'WorkOrderAccount'
): Promise<Record<string, string | null>> {
  if (!info || !info.owner.equals(PROGRAM_ID) || info.executable)
    throw new Error('Cuenta ausente o propietario on-chain incompatible.');
  if (localIdl.address !== PROGRAM_ID.toBase58())
    throw new Error('IDL incompatible con el programa.');
  const definition = definitions.find(
    (x) => x.name.split('::').at(-1) === kind
  );
  const declared = localIdl.accounts.find(
    (x) => x.name.split('::').at(-1) === kind
  );
  const digest = Buffer.from(
    await crypto.subtle.digest('SHA-256', encoder.encode(`account:${kind}`))
  ).subarray(0, 8);
  if (
    !definition?.type.fields ||
    !declared ||
    !digest.equals(Buffer.from(declared.discriminator)) ||
    !digest.equals(info.data.subarray(0, 8))
  )
    throw new Error('Discriminador de cuenta incompatible.');
  let offset = 8;
  function take(length: number) {
    if (offset + length > info!.data.length)
      throw new Error('Cuenta truncada.');
    const bytes = info!.data.subarray(offset, offset + length);
    offset += length;
    return bytes;
  }
  function decode(type: Type): string | null {
    if (typeof type === 'string') {
      if (type === 'pubkey') return new PublicKey(take(32)).toBase58();
      if (type === 'u8') return String(take(1)[0]);
      if (type === 'u16') return String(take(2).readUInt16LE());
      if (type === 'u64') return take(8).readBigUInt64LE().toString();
      if (type === 'i64') return take(8).readBigInt64LE().toString();
    } else if (
      'array' in type &&
      type.array[0] === 'u8' &&
      type.array[1] === 32
    )
      return take(32).toString('hex');
    else if ('option' in type) {
      const tag = take(1)[0];
      if (tag === 0) return null;
      if (tag === 1) return decode(type.option);
      throw new Error('Option IDL inválida.');
    } else if ('defined' in type) {
      const entry = definitions.find((x) => x.name === type.defined.name);
      const variant =
        entry?.type.kind === 'enum'
          ? entry.type.variants?.[take(1)[0]]
          : undefined;
      if (variant && !variant.fields?.length) return variant.name;
    }
    throw new Error('Esquema IDL no soportado.');
  }
  const result = Object.fromEntries(
    definition.type.fields.map((f) => [f.name, decode(f.type)])
  );
  if (result.protocol_version !== '1')
    throw new Error('Versión de cuenta incompatible.');
  // Anchor may allocate padding for an unused Option variant; nonzero trailing bytes are never ignored.
  if (info.data.subarray(offset).some((byte) => byte !== 0))
    throw new Error('Datos adicionales incompatibles con el IDL.');
  const [config] = PublicKey.findProgramAddressSync(
    [encoder.encode('protocol_config')],
    PROGRAM_ID
  );
  if (result.protocol_config !== config.toBase58())
    throw new Error('ProtocolConfig incompatible.');
  const id = result[kind === 'AgentAccount' ? 'agent_id' : 'work_order_id'];
  if (!id || !/^[a-f0-9]{64}$/.test(id))
    throw new Error('Identificador on-chain inválido.');
  const seeds =
    kind === 'AgentAccount'
      ? [encoder.encode('agent'), config.toBuffer(), Buffer.from(id, 'hex')]
      : [
          encoder.encode('work_order'),
          config.toBuffer(),
          new PublicKey(result.creator!).toBuffer(),
          Buffer.from(id, 'hex'),
        ];
  const [derived, bump] = PublicKey.findProgramAddressSync(seeds, PROGRAM_ID);
  if (derived.toBase58() !== address || result.bump !== String(bump))
    throw new Error('PDA de cuenta incompatible.');
  return result;
}
export async function readAccount(
  connection: Connection,
  address: string,
  kind: 'AgentAccount' | 'WorkOrderAccount'
) {
  return decodeAccount(
    await connection.getAccountInfo(new PublicKey(address), 'confirmed'),
    address,
    kind
  );
}
