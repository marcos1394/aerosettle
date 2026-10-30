'use strict';

// Creates isolated CON-36 test identities. No RPC calls or transactions.
const fs = require('node:fs');
const path = require('node:path');
const {createRequire} = require('node:module');
const fromBootstrap = createRequire(path.resolve(__dirname, '../../bootstrap/package.json'));
const {Keypair} = fromBootstrap('@solana/web3.js');

const repo = path.resolve(__dirname, '../../..');
const local = path.join(repo, 'target/deploy/con36-private');
const backup = path.join(process.env.HOME,
  'Library/Application Support/CONATUS/con36-wallet-backup');
const publicPath = path.join(repo, 'evidence/con36/test-identities.json');
const GENESIS = 'EtWTRABZaYq6iMfeYKouRu166VU2xqa1wcaWoxPkrZBG';
const roles = ['creator', 'agent_owner', 'device', 'shared_device', 'verifier'];
const required = (ok, message) => { if (!ok) throw Error(message); };

function protectedDir(dir) {
  fs.mkdirSync(dir, {recursive: true, mode: 0o700});
  required((fs.statSync(dir).mode & 0o077) === 0, 'Private directory permissions too broad');
}

function identicalProtectedCopies(name) {
  const a = path.join(local, name);
  const b = path.join(backup, name);
  required(fs.existsSync(a) && fs.existsSync(b), 'Private wallet or backup missing');
  required((fs.statSync(a).mode & 0o077) === 0 && (fs.statSync(b).mode & 0o077) === 0,
    'Private wallet permissions too broad');
  const left = fs.readFileSync(a);
  const right = fs.readFileSync(b);
  required(left.equals(right), 'Private wallet and backup differ');
  return Keypair.fromSecretKey(Uint8Array.from(JSON.parse(left)));
}

function run() {
  protectedDir(local);
  protectedDir(backup);
  const keys = {};
  for (const role of roles) {
    const name = `${role}.json`;
    const a = path.join(local, name);
    const b = path.join(backup, name);
    if (!fs.existsSync(a) && !fs.existsSync(b)) {
      const keypair = Keypair.generate();
      const bytes = JSON.stringify(Array.from(keypair.secretKey)) + '\n';
      fs.writeFileSync(a, bytes, {flag: 'wx', mode: 0o600});
      fs.writeFileSync(b, bytes, {flag: 'wx', mode: 0o600});
    }
    keys[role] = identicalProtectedCopies(name).publicKey.toBase58();
  }
  const manifest = {schema_version: 1, environment: 'devnet', network: 'solana:devnet',
    genesis_hash: GENESIS, program_id: 'CeA1P1NSuPLUH31KsT4j3pZeBsknQZ3NSC6GUAqcsCLy',
    mint_pubkey: 'HpfaV9oRuTN1b3ktDKvJoWqUWFZ1o9VFmhejxxqQ1vyh',
    roles: keys, private_keys_committed: false, transactions_submitted: false};
  const serialized = JSON.stringify(manifest, null, 2) + '\n';
  fs.mkdirSync(path.dirname(publicPath), {recursive: true});
  if (fs.existsSync(publicPath)) required(fs.readFileSync(publicPath, 'utf8') === serialized,
    'Public identity manifest changed');
  else fs.writeFileSync(publicPath, serialized, {flag: 'wx', mode: 0o644});
  console.log(JSON.stringify({public_manifest: publicPath, roles: keys,
    backups_verified: true, transactions_submitted: false}, null, 2));
}

if (require.main === module) {
  try { run(); } catch (error) { console.error(error.message); process.exitCode = 1; }
}
module.exports = {roles, identicalProtectedCopies};
