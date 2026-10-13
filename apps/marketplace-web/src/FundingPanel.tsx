import { useEffect, useState } from 'react';
import { Buffer } from 'buffer';
import {
  useConnection,
  useWallet,
} from '@solana/wallet-adapter-react';
import {
  PublicKey,
  Transaction,
  TransactionInstruction,
} from '@solana/web3.js';

import './funding-panel.css';

const GENESIS =
  'HP9XKTusRPGC78EFDpR9xdEq6simL2vqyDdrMvn6Vacg';
const PROGRAM =
  'CeA1P1NSuPLUH31KsT4j3pZeBsknQZ3NSC6GUAqcsCLy';
const MINT =
  'HTHpns7gqLAhSBhAzqxhYdyHv9HeXkkRW6aHQfdUjL1G';
const TOKEN =
  'TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA';

// Primeros 8 bytes de SHA256("global:fund_work_order")
const DISCRIMINATOR = '78737931fa111259';

const ACCOUNT_RULES: Array<[string, boolean, boolean]> = [
  ['protocol_config', false, false],
  ['work_order', false, true],
  ['creator', true, true],
  ['mint', false, false],
  ['creator_token_account', false, true],
  ['escrow_vault', false, true],
  ['token_program', false, false],
  ['system_program', false, false],
];

type Meta = {
  name: string;
  pubkey: string | null;
  is_signer: boolean;
  is_writable: boolean;
};

type Report = {
  schema_version: string;
  network: string;
  genesis: string;
  program_id: string;
  wallet: string;
  mint: string;
  instruction_data_hex: string;
  ready_for_funding: boolean;
  work_order?: string;
  order_status?: string;
  amount_base_units?: string;
  amount_tokens?: string;
  mint_decimals?: number;
  creator_token_account?: string | null;
  escrow_vault?: string;
  escrow_exists?: boolean;
  execution_deadline?: number;
  account_metas?: Meta[];
  notes?: string[];
};

type Plan = {
  report: Report;
  transaction: Transaction;
  fingerprint: string;
  blockhash: string;
  lastValidBlockHeight: number;
  logs: string[];
};

function describe(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

function fingerprint(r: Report): string {
  return JSON.stringify({
    wallet: r.wallet,
    order: r.work_order,
    amount: r.amount_base_units,
    source: r.creator_token_account,
    escrow: r.escrow_vault,
    deadline: r.execution_deadline,
    accounts: r.account_metas,
  });
}

function validate(r: Report, wallet: string): void {
  if (
    r.schema_version !== 'aerosettle.funding_preflight.v1' ||
    r.network !== 'Localnet ONLY' ||
    r.genesis !== GENESIS ||
    r.program_id !== PROGRAM ||
    r.wallet !== wallet ||
    r.mint !== MINT ||
    r.order_status !== 'Draft' ||
    !r.ready_for_funding ||
    r.escrow_exists !== false ||
    r.mint_decimals !== 6 ||
    r.instruction_data_hex !== DISCRIMINATOR
  ) {
    throw new Error(
      'Preflight no válido para esta orden, wallet o red.'
    );
  }

  if (
    !r.amount_base_units ||
    !/^[1-9][0-9]*$/.test(r.amount_base_units) ||
    BigInt(r.amount_base_units) >= 2n ** 64n
  ) {
    throw new Error('Monto SPL inválido.');
  }

  const metas = r.account_metas;

  if (!metas || metas.length !== ACCOUNT_RULES.length) {
    throw new Error('Las ocho cuentas de Funding no coinciden.');
  }

  for (let i = 0; i < ACCOUNT_RULES.length; i++) {
    const [name, signer, writable] = ACCOUNT_RULES[i];
    const meta = metas[i];

    if (
      meta.name !== name ||
      meta.is_signer !== signer ||
      meta.is_writable !== writable ||
      !meta.pubkey
    ) {
      throw new Error(`Cuenta Funding #${i + 1} inválida.`);
    }

    new PublicKey(meta.pubkey);
  }

  const address = (name: string) =>
    metas.find(m => m.name === name)?.pubkey;

  if (
    address('creator') !== wallet ||
    address('work_order') !== r.work_order ||
    address('creator_token_account') !== r.creator_token_account ||
    address('escrow_vault') !== r.escrow_vault ||
    address('mint') !== MINT ||
    address('token_program') !== TOKEN ||
    address('system_program') !==
      '11111111111111111111111111111111'
  ) {
    throw new Error('Las direcciones no corresponden al Funding.');
  }
}

async function loadReport(
  wallet: string,
  order: string
): Promise<Report> {
  const params = new URLSearchParams({
    wallet,
    work_order: order,
  });

  const response = await fetch(
    `/funding-api/preflight?${params}`,
    { cache: 'no-store' }
  );

  const payload = await response.json() as {
    ready?: boolean;
    report?: Report;
    error?: string;
  };

  if (!response.ok || !payload.report) {
    throw new Error(
      payload.error ?? `Funding API HTTP ${response.status}`
    );
  }

  return payload.report;
}

function makeTransaction(
  report: Report,
  blockhash: string
): Transaction {
  const instruction = new TransactionInstruction({
    programId: new PublicKey(PROGRAM),
    keys: report.account_metas!.map(m => ({
      pubkey: new PublicKey(m.pubkey!),
      isSigner: m.is_signer,
      isWritable: m.is_writable,
    })),
    data: Buffer.from(DISCRIMINATOR, 'hex'),
  });

  return new Transaction({
    feePayer: new PublicKey(report.wallet),
    recentBlockhash: blockhash,
  }).add(instruction);
}

async function simulate(tx: Transaction): Promise<string[]> {
  const raw = Buffer.from(
    tx.serialize({
      requireAllSignatures: false,
      verifySignatures: false,
    })
  ).toString('base64');

  const response = await fetch('/solana-rpc', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      jsonrpc: '2.0',
      id: 1,
      method: 'simulateTransaction',
      params: [
        raw,
        {
          encoding: 'base64',
          commitment: 'confirmed',
          sigVerify: false,
          replaceRecentBlockhash: false,
        },
      ],
    }),
  });

  if (!response.ok) {
    throw new Error(`RPC HTTP ${response.status}`);
  }

  const data = await response.json() as {
    error?: { message?: string };
    result?: {
      value?: {
        err?: unknown;
        logs?: string[] | null;
      };
    };
  };

  if (data.error) {
    throw new Error(data.error.message ?? 'Error RPC');
  }

  const result = data.result?.value;

  if (!result) {
    throw new Error('Simulación sin resultado.');
  }

  if (result.err != null) {
    throw new Error(
      'Simulación fallida: ' +
      JSON.stringify(result.err) + '\n' +
      (result.logs ?? []).slice(-10).join('\n')
    );
  }

  return result.logs ?? [];
}

export default function FundingPanel() {
  const { connection } = useConnection();
  const { publicKey, connected, signTransaction } = useWallet();

  const wallet = publicKey?.toBase58() ?? '';

  const [order, setOrder] = useState('');
  const [report, setReport] = useState<Report | null>(null);
  const [plan, setPlan] = useState<Plan | null>(null);

  const [busy, setBusy] = useState(false);
  const [status, setStatus] = useState('');
  const [error, setError] = useState('');
  const [signature, setSignature] = useState('');

  useEffect(() => {
    setReport(null);
    setPlan(null);
    setStatus('');
    setError('');
    setSignature('');
  }, [wallet, order]);

  async function checkNetwork(): Promise<void> {
    if (await connection.getGenesisHash() !== GENESIS) {
      throw new Error('RPC no corresponde a AeroSettle Localnet.');
    }
  }

  async function verify(): Promise<void> {
    if (!connected || !wallet) return;

    setBusy(true);
    setError('');
    setPlan(null);

    try {
      if (!order.trim()) {
        throw new Error('Introduce la WorkOrder PDA.');
      }

      await checkNetwork();

      const fresh = await loadReport(wallet, order.trim());

      setReport(fresh);
      setStatus(
        fresh.ready_for_funding
          ? '✅ Preflight aprobado.'
          : 'Preflight no aprobado. Revisa las observaciones.'
      );
    } catch (e) {
      setReport(null);
      setError(describe(e));
    } finally {
      setBusy(false);
    }
  }

  async function prepare(): Promise<void> {
    if (!connected || !wallet) return;

    setBusy(true);
    setError('');
    setPlan(null);

    try {
      await checkNetwork();

      const fresh = await loadReport(wallet, order.trim());
      validate(fresh, wallet);
      setReport(fresh);

      const latest = await connection.getLatestBlockhash(
        'confirmed'
      );

      const transaction = makeTransaction(
        fresh, latest.blockhash
      );

      const logs = await simulate(transaction);

      setPlan({
        report: fresh,
        transaction,
        fingerprint: fingerprint(fresh),
        blockhash: latest.blockhash,
        lastValidBlockHeight: latest.lastValidBlockHeight,
        logs,
      });

      setStatus(
        '✅ Simulación aprobada. Todavía no se enviaron tokens.'
      );
    } catch (e) {
      setError(describe(e));
    } finally {
      setBusy(false);
    }
  }

  async function fund(): Promise<void> {
    if (
      !plan ||
      !publicKey ||
      !connected ||
      !signTransaction ||
      busy
    ) return;

    setBusy(true);
    setError('');
    setSignature('');

    let mayHaveSent = false;

    try {
      if (publicKey.toBase58() !== plan.report.wallet) {
        throw new Error('La wallet cambió.');
      }

      await checkNetwork();

      const before = await loadReport(wallet, order.trim());
      validate(before, wallet);

      if (fingerprint(before) !== plan.fingerprint) {
        throw new Error(
          'Cambió la orden. Vuelve a simular.'
        );
      }

      // Renovar el blockhash después del preflight.
      // Nunca firmar la transacción antigua del preview.
      setStatus(
        'Actualizando blockhash y simulando Funding...'
      );

      const latest = await connection.getLatestBlockhash(
        'confirmed'
      );

      const unsigned = makeTransaction(
        before,
        latest.blockhash
      );

      // Simular exactamente el mensaje que se firmará.
      await simulate(unsigned);

      const original = Buffer.from(
        unsigned.serializeMessage()
      );

      setStatus('Solicitando firma a la wallet...');

      const signed = await signTransaction(unsigned);

      if (
        !Buffer.from(signed.serializeMessage()).equals(original) ||
        !signed.verifySignatures(true)
      ) {
        throw new Error(
          'Firma inválida o mensaje modificado.'
        );
      }

      await checkNetwork();

      const after = await loadReport(wallet, order.trim());
      validate(after, wallet);

      if (fingerprint(after) !== plan.fingerprint) {
        throw new Error(
          'Cambió el estado durante la firma.'
        );
      }

      const validHash = await connection.isBlockhashValid(
        latest.blockhash,
        'confirmed'
      );

      const currentHeight = await connection.getBlockHeight(
        'confirmed'
      );

      if (
        !validHash.value ||
        currentHeight >= latest.lastValidBlockHeight - 8
      ) {
        throw new Error(
          'El blockhash renovado perdió vigencia. '
          + 'Repite la simulación y autorización.'
        );
      }

      setStatus('Enviando Funding a Localnet...');
      mayHaveSent = true;

      const sig = await connection.sendRawTransaction(
        signed.serialize(),
        {
          skipPreflight: false,
          preflightCommitment: 'confirmed',
          maxRetries: 1,
        }
      );

      setSignature(sig);

      const confirmation = await connection.confirmTransaction(
        {
          signature: sig,
          blockhash: latest.blockhash,
          lastValidBlockHeight: latest.lastValidBlockHeight,
        },
        'confirmed'
      );

      if (confirmation.value.err != null) {
        throw new Error(
          JSON.stringify(confirmation.value.err)
        );
      }

      const vault = new PublicKey(plan.report.escrow_vault!);
      const info = await connection.getAccountInfo(
        vault, 'confirmed'
      );

      if (
        !info ||
        !info.owner.equals(new PublicKey(TOKEN)) ||
        info.data.length !== 165
      ) {
        throw new Error('Escrow SPL no verificable.');
      }

      const data = Buffer.from(info.data);

      if (
        !new PublicKey(data.subarray(0, 32))
          .equals(new PublicKey(MINT)) ||
        !new PublicKey(data.subarray(32, 64))
          .equals(vault)
      ) {
        throw new Error(
          'Mint o autoridad del escrow incorrectos.'
        );
      }

      const deposited = data.readBigUInt64LE(64);

      if (
        deposited !== BigInt(plan.report.amount_base_units!)
      ) {
        throw new Error(
          'Saldo escrow distinto del monto esperado.'
        );
      }

      const response = await fetch(
        `/v1/work-orders/${plan.report.work_order}`,
        { cache: 'no-store' }
      );

      if (!response.ok) {
        throw new Error(
          'Funding confirmado; Marketplace API no disponible.'
        );
      }

      const payload = await response.json() as {
        data?: { status?: string };
      };

      if (payload.data?.status !== 'Open') {
        throw new Error(
          'Funding confirmado; estado Open no verificado en API.'
        );
      }

      setPlan(null);
      setStatus(
        '✅ Funding confirmado. WorkOrder Open. '
        + 'Escrow: ' + plan.report.amount_tokens + ' DEMO.'
      );

    } catch (e) {
      if (mayHaveSent) {
        setPlan(null);
      }

      setError(
        describe(e) +
        (mayHaveSent
          ? '\nLa transacción pudo enviarse. '
            + 'Verifica el escrow antes de reintentar.'
          : '\nNo se envió ninguna transacción.')
      );

    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="funding-panel">
      <p className="funding-eyebrow">
        AEROSETTLE / EPIC 3.4.3 / LOCALNET
      </p>

      <h2>Funding de WorkOrder</h2>

      <p>
        Financia una inspección Draft con tokens DEMO
        mediante el escrow del protocolo.
      </p>

      {!connected ? (
        <p>Conecta AeroSettle Localnet Dev.</p>
      ) : (
        <>
          <label className="funding-field">
            Wallet creadora
            <code>{wallet}</code>
          </label>

          <label className="funding-field">
            WorkOrder PDA
            <input
              value={order}
              spellCheck={false}
              placeholder="Introduce una nueva WorkOrder Draft"
              onChange={e => setOrder(e.target.value.trim())}
            />
          </label>

          <div className="funding-actions">
            <button disabled={busy} onClick={() => void verify()}>
              1. Verificar preflight
            </button>

            <button
              disabled={busy || !report?.ready_for_funding}
              onClick={() => void prepare()}
            >
              2. Simular Funding
            </button>

            <button
              className="funding-primary"
              disabled={busy || !plan || !signTransaction}
              onClick={() => void fund()}
            >
              3. Autorizar y financiar
            </button>
          </div>

          {report && (
            <div className="funding-review">
              <div>
                <span>Estado</span>
                <strong>{report.order_status ?? '—'}</strong>
              </div>
              <div>
                <span>Monto</span>
                <strong>{report.amount_tokens ?? '—'} DEMO</strong>
              </div>
              <div>
                <span>Cuenta SPL origen</span>
                <code>{report.creator_token_account ?? '—'}</code>
              </div>
              <div>
                <span>Escrow PDA</span>
                <code>{report.escrow_vault ?? '—'}</code>
              </div>
              <div>
                <span>Preflight</span>
                <strong>
                  {report.ready_for_funding ? 'READY' : 'NOT READY'}
                </strong>
              </div>
            </div>
          )}

          {report?.notes?.map((note, i) => (
            <p key={i} className="funding-note">{note}</p>
          ))}

          {plan && (
            <p className="funding-success">
              Simulación correcta ({plan.logs.length} líneas).
              El próximo botón enviará {plan.report.amount_tokens} DEMO.
            </p>
          )}

          {status && <p role="status">{status}</p>}

          {error && (
            <pre className="funding-error" role="alert">
              {error}
            </pre>
          )}

          {signature && (
            <p className="funding-signature">
              Firma: <code>{signature}</code>
            </p>
          )}
        </>
      )}

      <p className="funding-note">
        Entorno de pruebas. No utilizar activos reales.
      </p>
    </section>
  );
}
