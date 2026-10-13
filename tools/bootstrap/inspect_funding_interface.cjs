const fs = require('node:fs');
const path = require('node:path');

const root = process.cwd();

const normalize = value =>
  String(value)
    .split('::').at(-1)
    .replace(/[^a-zA-Z0-9]/g, '')
    .toLowerCase();

const paths = [
  'target/idl/aerosettle.discovery.json',
  'target/idl/aerosettle.json',
];

console.log('=== AEROSETTLE FUNDING INTERFACE ===');

let found = false;

for (const filename of paths) {
  const absolute = path.join(root, filename);

  if (!fs.existsSync(absolute)) continue;

  const idl = JSON.parse(
    fs.readFileSync(absolute, 'utf8')
  );

  const ix = (idl.instructions ?? []).find(
    item => normalize(item.name) === 'fundworkorder'
  );

  console.log('\nIDL:', filename);
  console.log('Program:', idl.address);

  if (!ix) {
    console.log('fund_work_order: No incluida');
    continue;
  }

  found = true;

  console.log('Instruction:', ix.name);
  console.log('Discriminator:', ix.discriminator);
  console.log('\nAccounts:');

  for (const [i, account] of ix.accounts.entries()) {
    console.log(
      `${i + 1}. ${account.name}`,
      'signer:',
      account.signer ?? account.isSigner ?? false,
      'writable:',
      account.writable ?? account.isMut ?? false
    );
  }

  console.log('\nArguments:');
  console.log(JSON.stringify(ix.args ?? [], null, 2));
}

console.log('\n=== RUST IMPLEMENTATION REFERENCES ===');

const locations = [
  'programs/aerosettle/src',
  'programs/aerosettle/tests'
];

function inspect(directory) {
  if (!fs.existsSync(directory)) return;

  for (const item of fs.readdirSync(
    directory,
    { withFileTypes: true }
  )) {
    const filename = path.join(directory, item.name);

    if (item.isDirectory()) {
      inspect(filename);
      continue;
    }

    if (!filename.endsWith('.rs')) continue;

    const text = fs.readFileSync(filename, 'utf8');

    if (
      text.includes('fund_work_order') ||
      text.includes('FundWorkOrder')
    ) {
      console.log(filename);
    }
  }
}

for (const directory of locations) {
  inspect(directory);
}

if (!found) {
  console.log(
    '\n⚠️ Funding no está descrito en los IDL disponibles.'
  );
  console.log(
    'Se deberá reconstruir su definición desde Rust '
    + 'antes de generar la transacción.'
  );
} else {
  console.log('\n✅ FUNDING IDL INTERFACE FOUND');
}

console.log('\n✅ READ-ONLY INSPECTION COMPLETED');
