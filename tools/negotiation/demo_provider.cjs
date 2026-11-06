// Offline fixture provider implemented in Node.js. Seed 0x02 is public test data.
const crypto = require('node:crypto');
const fs = require('node:fs');
const seed = Buffer.alloc(32, 2);
const pkcs8 = Buffer.concat([
  Buffer.from('302e020100300506032b657004220420', 'hex'), seed,
]);
const key = crypto.createPrivateKey({ key: pkcs8, format: 'der', type: 'pkcs8' });
const alphabet = '123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz';
function base58(bytes) {
  let n = BigInt('0x' + bytes.toString('hex'));
  let result = '';
  while (n > 0n) {
    const r = Number(n % 58n);
    result = alphabet[r] + result;
    n /= 58n;
  }
  for (const byte of bytes) {
    if (byte !== 0) break;
    result = '1' + result;
  }
  return result;
}
function canonical(value) {
  if (Array.isArray(value)) return '[' + value.map(canonical).join(',') + ']';
  if (value !== null && typeof value === 'object') return '{' +
    Object.keys(value).sort().map(k => JSON.stringify(k) + ':' + canonical(value[k])).join(',') + '}';
  return JSON.stringify(value);
}
const message = JSON.parse(fs.readFileSync(0, 'utf8'));
delete message.signature;
const bytes = Buffer.from('CONATUS-AGENT-NEGOTIATION-v1\n' + canonical(message));
message.signature = base58(crypto.sign(null, bytes, key));
process.stdout.write(JSON.stringify(message));
