'use strict';

// Read-only ABI encoder shared by the approval-gated CON-36 Devnet runners.
const fs = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');
const {createRequire} = require('node:module');
const repo = path.resolve(__dirname, '../../..');
const fromBootstrap = createRequire(path.join(repo, 'tools/bootstrap/package.json'));
const {PublicKey, TransactionInstruction} = fromBootstrap('@solana/web3.js');
const idl = JSON.parse(fs.readFileSync(path.join(repo,
  'evidence/con35/artifacts/aerosettle-idl.json')));
const programId = new PublicKey('CeA1P1NSuPLUH31KsT4j3pZeBsknQZ3NSC6GUAqcsCLy');
if (idl.address !== programId.toBase58()) throw Error('Approved CON-35 IDL Program ID mismatch');
const norm = x => String(x).split('::').at(-1).replace(/[^a-z0-9]/gi, '').toLowerCase();
const one = (items, name) => {
  const matches = items.filter(x => norm(x.name) === norm(name));
  if (matches.length !== 1) throw Error(`Approved IDL ${name}: ${matches.length} matches`);
  return matches[0];
};
const sha = x => crypto.createHash('sha256').update(x).digest();
const byte32 = x => {
  const b = Buffer.from(x);
  if (b.length !== 32) throw Error('Expected 32-byte IDL argument');
  return b;
};

function encode(type, value) {
  if (typeof type === 'string') {
    if (type === 'pubkey') return new PublicKey(value).toBuffer();
    const size = {u8: 1, u16: 2, u32: 4, u64: 8, i64: 8}[type];
    if (!size) throw Error(`Unsupported IDL type ${type}`);
    const b = Buffer.alloc(size);
    const n = BigInt(value);
    if (n < (type === 'i64' ? -(1n << 63n) : 0n) ||
        n >= (type === 'i64' ? (1n << 63n) : (1n << BigInt(size * 8)))) {
      throw Error(`${type} out of range`);
    }
    if (type === 'i64') b.writeBigInt64LE(n);
    else if (size === 8) b.writeBigUInt64LE(n);
    else if (size === 4) b.writeUInt32LE(Number(n));
    else if (size === 2) b.writeUInt16LE(Number(n));
    else b.writeUInt8(Number(n));
    return b;
  }
  if (type.array?.[0] === 'u8' && type.array[1] === 32) return byte32(value);
  const defined = type.defined?.name || type.defined;
  const def = one(idl.types, defined).type;
  if (def.kind === 'enum') {
    const index = def.variants.findIndex(x => norm(x.name) === norm(value));
    if (index < 0 || def.variants[index].fields) throw Error(`Unsupported IDL enum ${defined}`);
    return Buffer.from([index]);
  }
  if (def.kind === 'struct') return Buffer.concat(def.fields.map(field => {
    const key = Object.keys(value).find(x => norm(x) === norm(field.name));
    if (!key) throw Error(`Missing IDL field ${field.name}`);
    return encode(field.type, value[key]);
  }));
  throw Error(`Unsupported IDL definition ${defined}`);
}

function instruction(name, accounts, args = {}) {
  const def = one(idl.instructions, name);
  const discriminator = sha(Buffer.from(`global:${name}`)).subarray(0, 8);
  if (!Buffer.from(def.discriminator).equals(discriminator)) {
    throw Error(`Approved IDL discriminator mismatch: ${name}`);
  }
  const data = Buffer.concat([discriminator, ...def.args.map(arg => {
    const key = Object.keys(args).find(x => norm(x) === norm(arg.name));
    if (!key) throw Error(`Missing instruction argument ${arg.name}`);
    return encode(arg.type, args[key]);
  })]);
  const keys = def.accounts.map(account => {
    const key = Object.keys(accounts).find(x => norm(x) === norm(account.name));
    if (!key) throw Error(`Missing account ${account.name}`);
    const pubkey = new PublicKey(accounts[key]);
    if (account.address && account.address !== pubkey.toBase58()) {
      throw Error(`Approved IDL fixed address mismatch: ${account.name}`);
    }
    return {pubkey, isSigner: !!account.signer, isWritable: !!account.writable};
  });
  return new TransactionInstruction({programId, keys, data});
}

module.exports = {idl, programId, norm, one, encode, instruction};
