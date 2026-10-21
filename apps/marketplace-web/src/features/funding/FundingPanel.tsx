import { useCopy, useI18n } from '../../app/i18n';
import { SETTLEMENT_SYMBOL } from '../../app/atlas';
import { useEffect, useState } from 'react';
import { Buffer } from 'buffer';
import { useConnection, useWallet } from '@solana/wallet-adapter-react';
import {
  PublicKey,
  Transaction,
  TransactionInstruction,
} from '@solana/web3.js';

import {
  MINT as DEMO_MINT,
  LOCALNET_GENESIS,
  PROGRAM_ID,
  TOKEN_PROGRAM,
} from '../../app/config';
import { api, verifyMeta } from '../../app/api';
import { CopyAddress } from '../../components/ui';

const GENESIS = LOCALNET_GENESIS;
const PROGRAM = PROGRAM_ID.toBase58();
const MINT = DEMO_MINT.toBase58();
const TOKEN = TOKEN_PROGRAM.toBase58();

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

function validate(r: Report, wallet: string, order: string): void {
  if (
    r.schema_version !== 'aerosettle.funding_preflight.v1' ||
    r.network !== 'Localnet ONLY' ||
    r.genesis !== GENESIS ||
    r.program_id !== PROGRAM ||
    r.wallet !== wallet ||
    r.mint !== MINT ||
    r.order_status !== 'Draft' ||
    r.work_order !== order ||
    !r.ready_for_funding ||
    r.escrow_exists !== false ||
    r.mint_decimals !== 6 ||
    r.instruction_data_hex !== DISCRIMINATOR
  ) {
    throw new Error('Preflight no válido para esta orden, wallet o red.');
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

  const address = (name: string) => metas.find((m) => m.name === name)?.pubkey;

  if (
    address('creator') !== wallet ||
    address('work_order') !== r.work_order ||
    address('creator_token_account') !== r.creator_token_account ||
    address('escrow_vault') !== r.escrow_vault ||
    address('mint') !== MINT ||
    address('token_program') !== TOKEN ||
    address('system_program') !== '11111111111111111111111111111111'
  ) {
    throw new Error('Las direcciones no corresponden al Funding.');
  }
}

async function loadReport(wallet: string, order: string): Promise<Report> {
  const params = new URLSearchParams({
    wallet,
    work_order: order,
  });

  const response = await fetch(`/funding-api/preflight?${params}`, {
    cache: 'no-store',
  });

  const payload = (await response.json()) as {
    ready?: boolean;
    report?: Report;
    error?: string;
  };

  if (!response.ok || !payload.report) {
    throw new Error(payload.error ?? `Funding API HTTP ${response.status}`);
  }

  return payload.report;
}

function makeTransaction(report: Report, blockhash: string): Transaction {
  const instruction = new TransactionInstruction({
    programId: new PublicKey(PROGRAM),
    keys: report.account_metas!.map((m) => ({
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

  const data = (await response.json()) as {
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
        JSON.stringify(result.err) +
        '\n' +
        (result.logs ?? []).slice(-10).join('\n')
    );
  }

  return result.logs ?? [];
}

export default function FundingPanel({
  workOrderPda,
  onFunded,
}: {
  workOrderPda: string;
  onFunded: () => void;
}) {
  const { t } = useI18n();
  const c = useCopy();

  const { connection } = useConnection();
  const { publicKey, connected, signTransaction } = useWallet();

  const wallet = publicKey?.toBase58() ?? '';

  const order = workOrderPda;
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
    if ((await connection.getGenesisHash()) !== GENESIS) {
      throw new Error(
        c(
          'RPC endpoint does not match the verified protocol genesis.',
          'El endpoint RPC no coincide con el genesis verificado del protocolo.'
        )
      );
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

      if (fresh.work_order !== order)
        throw new Error('Preflight de otra misión.');
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
      validate(fresh, wallet, order);
      setReport(fresh);

      const latest = await connection.getLatestBlockhash('confirmed');

      const transaction = makeTransaction(fresh, latest.blockhash);

      const logs = await simulate(transaction);

      setPlan({
        report: fresh,
        transaction,
        fingerprint: fingerprint(fresh),
        blockhash: latest.blockhash,
        lastValidBlockHeight: latest.lastValidBlockHeight,
        logs,
      });

      setStatus('✅ Simulación aprobada. Todavía no se enviaron tokens.');
    } catch (e) {
      setError(describe(e));
    } finally {
      setBusy(false);
    }
  }

  async function fund(): Promise<void> {
    if (!plan || !publicKey || !connected || !signTransaction || busy) return;

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
      validate(before, wallet, order);

      if (fingerprint(before) !== plan.fingerprint) {
        throw new Error('Cambió la orden. Vuelve a simular.');
      }

      // Renovar el blockhash después del preflight.
      // Nunca firmar la transacción antigua del preview.
      setStatus('Actualizando blockhash y simulando Funding...');

      const latest = await connection.getLatestBlockhash('confirmed');

      const unsigned = makeTransaction(before, latest.blockhash);

      // Simular exactamente el mensaje que se firmará.
      await simulate(unsigned);

      const original = Buffer.from(unsigned.serializeMessage());

      setStatus('Solicitando firma a la wallet...');

      const signed = await signTransaction(unsigned);

      if (
        !Buffer.from(signed.serializeMessage()).equals(original) ||
        !signed.verifySignatures(true)
      ) {
        throw new Error('Firma inválida o mensaje modificado.');
      }

      await checkNetwork();

      const after = await loadReport(wallet, order.trim());
      validate(after, wallet, order);

      if (fingerprint(after) !== plan.fingerprint) {
        throw new Error('Cambió el estado durante la firma.');
      }

      const validHash = await connection.isBlockhashValid(latest.blockhash, {
        commitment: 'confirmed',
      });

      const currentHeight = await connection.getBlockHeight('confirmed');

      if (
        !validHash.value ||
        currentHeight >= latest.lastValidBlockHeight - 8
      ) {
        throw new Error(
          'El blockhash renovado perdió vigencia. ' +
            'Repite la simulación y autorización.'
        );
      }

      setStatus(
        c(
          'Submitting funding transaction…',
          'Enviando transacción de financiamiento…'
        )
      );
      mayHaveSent = true;

      const sig = await connection.sendRawTransaction(signed.serialize(), {
        skipPreflight: false,
        preflightCommitment: 'confirmed',
        maxRetries: 1,
      });

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
        throw new Error(JSON.stringify(confirmation.value.err));
      }

      const vault = new PublicKey(plan.report.escrow_vault!);
      const info = await connection.getAccountInfo(vault, 'confirmed');

      if (
        !info ||
        !info.owner.equals(new PublicKey(TOKEN)) ||
        info.data.length !== 165
      ) {
        throw new Error('Escrow SPL no verificable.');
      }

      const data = Buffer.from(info.data);

      if (
        !new PublicKey(data.subarray(0, 32)).equals(new PublicKey(MINT)) ||
        !new PublicKey(data.subarray(32, 64)).equals(vault)
      ) {
        throw new Error('Mint o autoridad del escrow incorrectos.');
      }

      const deposited = data.readBigUInt64LE(64);

      if (deposited !== BigInt(plan.report.amount_base_units!)) {
        throw new Error('Saldo escrow distinto del monto esperado.');
      }

      const payload = await api.getWorkOrder(order);
      verifyMeta(payload.meta);
      if (
        payload.data.work_order_account !== order ||
        payload.data.status !== 'Open'
      ) {
        throw new Error(
          'Funding confirmado; estado Open no verificado en API.'
        );
      }

      setPlan(null);
      setStatus('✅ Funding confirmado. WorkOrder Open.');
      onFunded();
    } catch (e) {
      if (mayHaveSent) {
        setPlan(null);
      }

      setError(
        describe(e) +
          (mayHaveSent
            ? '\nLa transacción pudo enviarse. ' +
              'Verifica el escrow antes de reintentar.'
            : '\nNo se envió ninguna transacción.')
      );
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="funding-panel">
      <p className="funding-eyebrow">
        {c('ESCROW FUNDING', 'FINANCIAMIENTO EN ESCROW')}
      </p>

      <h2>{t('Funding de WorkOrder')}</h2>

      <p>
        {c(
          `Lock ${SETTLEMENT_SYMBOL} in the protocol escrow vault to open this Draft mission for execution.`,
          `Deposita ${SETTLEMENT_SYMBOL} en el escrow del protocolo para abrir esta misión en estado Draft.`
        )}
      </p>

      {!connected ? (
        <p>
          {t(
            'Conecta la wallet creadora para inspeccionar y financiar esta misión.'
          )}
        </p>
      ) : (
        <>
          <label className="funding-field">
            {t('Wallet creadora')}
            <CopyAddress value={wallet} />
          </label>

          <div className="funding-field">
            {t('Work Order')} <CopyAddress value={order} />
          </div>

          <div className="funding-actions">
            <button disabled={busy} onClick={() => void verify()}>
              {t('1. Verificar preflight')}
            </button>

            <button
              disabled={busy || !report?.ready_for_funding}
              onClick={() => void prepare()}
            >
              {t('2. Simular Funding')}
            </button>

            <button
              className="funding-primary"
              disabled={busy || !plan || !signTransaction}
              onClick={() => void fund()}
            >
              {t('3. Autorizar y financiar')}
            </button>
          </div>

          {report && (
            <div className="funding-review">
              <div>
                <span>{t('Estado')}</span>
                <strong>{t(report.order_status ?? '—')}</strong>
              </div>
              <div>
                <span>{t('Monto')}</span>
                <strong>
                  {report.amount_tokens ?? '—'} {SETTLEMENT_SYMBOL}
                </strong>
              </div>
              <div>
                <span>{t('Cuenta SPL origen')}</span>
                {report.creator_token_account ? (
                  <CopyAddress value={report.creator_token_account} />
                ) : (
                  '—'
                )}
              </div>
              <div>
                <span>{t('Escrow PDA')}</span>
                {report.escrow_vault ? (
                  <CopyAddress value={report.escrow_vault} />
                ) : (
                  '—'
                )}
              </div>
              <div>
                <span>{t('Preflight')}</span>
                <strong>
                  {report.ready_for_funding ? t('Ready') : t('Not ready')}
                </strong>
              </div>
            </div>
          )}

          {report?.notes?.map((note, i) => (
            <p key={i} className="funding-note">
              {note}
            </p>
          ))}

          {plan && (
            <p className="funding-success">
              {t('Simulación correcta (')}
              {plan.logs.length} {t('líneas). El próximo botón enviará')}{' '}
              {plan.report.amount_tokens} {SETTLEMENT_SYMBOL}.
            </p>
          )}

          {status && <p role="status">{t(status)}</p>}

          {error && (
            <div role="alert">
              <p>
                {t(
                  'No se pudo completar Funding. Comprueba el estado antes de reintentar.'
                )}
              </p>
              <details>
                <summary>{t('Diagnóstico de Funding')}</summary>
                <pre>{error}</pre>
              </details>
            </div>
          )}

          {signature && (
            <p className="funding-signature">
              {t('Firma enviada (consulta su estado en Transactions):')}{' '}
              <CopyAddress label={t('firma')} value={signature} />
            </p>
          )}
        </>
      )}

      <p className="funding-note">
        {c(
          'Funds are held by the protocol escrow until verification.',
          'Los fondos permanecen custodiados por el escrow del protocolo hasta la verificación.'
        )}
      </p>
    </section>
  );
}
