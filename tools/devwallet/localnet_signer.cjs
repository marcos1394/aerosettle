'use strict';

const http = require('node:http');
const fs = require('node:fs');
const path = require('node:path');
const { createRequire } = require('node:module');
const { createHash } = require('node:crypto');

const ROOT = path.resolve(__dirname, '../..');

const fromWeb = createRequire(
  path.join(ROOT, 'apps/marketplace-web/package.json')
);

const {
  Connection,
  Keypair,
  PublicKey,
  Transaction,
} = fromWeb('@solana/web3.js');

const RPC = 'http://127.0.0.1:8899';
const PORT = 8799;
const APP_ORIGIN = 'http://127.0.0.1:5173';

const GENESIS =
  'HP9XKTusRPGC78EFDpR9xdEq6simL2vqyDdrMvn6Vacg';

const PROGRAM_ID = new PublicKey(
  'CeA1P1NSuPLUH31KsT4j3pZeBsknQZ3NSC6GUAqcsCLy'
);

const KEY_FILE = path.join(
  ROOT,
  '.aerosettle-local/dev-signer-wallet.json'
);

const connection = new Connection(RPC, 'confirmed');

const ALLOWED = [
  'create_work_order',
  'fund_work_order',
].map(name =>
  createHash('sha256')
    .update(`global:${name}`)
    .digest()
    .subarray(0, 8)
    .toString('hex')
);

function reply(res, status, data) {
  res.writeHead(status, {
    'Content-Type': 'application/json',
    'Cache-Control': 'no-store',
    'X-Content-Type-Options': 'nosniff',
  });

  res.end(JSON.stringify(data));
}

function getWallet() {
  fs.mkdirSync(path.dirname(KEY_FILE), {
    recursive: true,
    mode: 0o700,
  });

  if (!fs.existsSync(KEY_FILE)) {
    const wallet = Keypair.generate();

    fs.writeFileSync(
      KEY_FILE,
      JSON.stringify(Array.from(wallet.secretKey)),
      { flag: 'wx', mode: 0o600 }
    );
  }

  if ((fs.statSync(KEY_FILE).mode & 0o077) !== 0) {
    throw new Error(
      'Ejecuta chmod 600 .aerosettle-local/dev-signer-wallet.json'
    );
  }

  const secret = JSON.parse(
    fs.readFileSync(KEY_FILE, 'utf8')
  );

  if (!Array.isArray(secret) || secret.length !== 64) {
    throw new Error('Wallet local inválida');
  }

  return Keypair.fromSecretKey(
    Uint8Array.from(secret)
  );
}

async function checkNetwork() {
  const actual = await connection.getGenesisHash();

  if (actual !== GENESIS) {
    throw new Error(
      'Genesis inesperado. Firma bloqueada.'
    );
  }
}

async function handle(req, res, wallet) {
  if (req.headers.host !== `127.0.0.1:${PORT}`) {
    return reply(res, 403, {
      error: 'Host no autorizado',
    });
  }

  const origin = req.headers.origin;

  if (origin && origin !== APP_ORIGIN) {
    return reply(res, 403, {
      error: 'Origin no autorizado',
    });
  }

  try {
    if (
      req.method === 'GET' &&
      req.url === '/health'
    ) {
      await checkNetwork();

      return reply(res, 200, {
        status: 'ok',
        service: 'aerosettle-dev-signer',
        genesis: GENESIS,
      });
    }

    if (
      req.method === 'GET' &&
      req.url === '/public-key'
    ) {
      await checkNetwork();

      return reply(res, 200, {
        publicKey: wallet.publicKey.toBase58(),
        genesis: GENESIS,
        network: 'localnet',
      });
    }

    if (
      req.method !== 'POST' ||
      req.url !== '/sign'
    ) {
      return reply(res, 404, {
        error: 'No encontrado',
      });
    }

    if (
      origin !== APP_ORIGIN ||
      req.headers['x-aerosettle-dev-signer']
        !== 'localnet-v1' ||
      !String(
        req.headers['content-type'] || ''
      ).startsWith('application/json')
    ) {
      return reply(res, 403, {
        error: 'Solicitud no autorizada',
      });
    }

    let body = '';

    for await (const chunk of req) {
      body += chunk;

      if (body.length > 16000) {
        return reply(res, 413, {
          error: 'Transacción demasiado grande',
        });
      }
    }

    const payload = JSON.parse(body);

    if (
      typeof payload.transaction !== 'string' ||
      !/^[A-Za-z0-9+/]+={0,2}$/.test(
        payload.transaction
      )
    ) {
      return reply(res, 400, {
        error: 'Transacción base64 inválida',
      });
    }

    await checkNetwork();

    const tx = Transaction.from(
      Buffer.from(payload.transaction, 'base64')
    );

    if (
      !tx.feePayer?.equals(wallet.publicKey) ||
      tx.instructions.length !== 1
    ) {
      return reply(res, 403, {
        error: 'Fee payer o instrucciones no permitidas',
      });
    }

    const instruction = tx.instructions[0];

    const discriminator = instruction.data
      .subarray(0, 8)
      .toString('hex');

    if (
      !instruction.programId.equals(PROGRAM_ID) ||
      !ALLOWED.includes(discriminator)
    ) {
      return reply(res, 403, {
        error: 'Instrucción no permitida',
      });
    }

    const signers = instruction.keys.filter(
      account => account.isSigner
    );

    if (
      signers.length !== 1 ||
      !signers[0].pubkey.equals(wallet.publicKey)
    ) {
      return reply(res, 403, {
        error: 'Firmantes inesperados',
      });
    }

    const valid = await connection.isBlockhashValid(
      tx.recentBlockhash,
      'confirmed'
    );

    if (!valid.value) {
      return reply(res, 409, {
        error: 'Blockhash no válido en Localnet',
      });
    }

    tx.sign(wallet);

    return reply(res, 200, {
      signedTransaction: tx
        .serialize()
        .toString('base64'),
    });

  } catch (error) {
    console.error(
      '[dev-signer]',
      error instanceof Error
        ? error.message
        : String(error)
    );

    return reply(res, 500, {
      error: error instanceof Error
        ? error.message
        : 'Error interno',
    });
  }
}

async function main() {
  await checkNetwork();

  const wallet = getWallet();

  http.createServer(
    (req, res) => {
      void handle(req, res, wallet);
    }
  ).listen(PORT, '127.0.0.1', () => {
    console.log(
      '✅ AeroSettle Localnet Dev Signer activo'
    );

    console.log(
      'Wallet:', wallet.publicKey.toBase58()
    );

    console.log(
      'Servicio: http://127.0.0.1:8799'
    );

    console.log(
      'Red: Localnet exclusivo'
    );
  });
}

main().catch(error => {
  console.error('❌', error.message);
  process.exitCode = 1;
});
