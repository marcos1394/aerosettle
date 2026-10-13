import { useEffect, useState } from 'react';

import {
  useConnection,
  useWallet,
} from '@solana/wallet-adapter-react';

import {
  WalletMultiButton,
} from '@solana/wallet-adapter-react-ui';

import {
  PublicKey,
  Transaction,
} from '@solana/web3.js';

import {
  MarketplaceClient,
} from '@aerosettle/marketplace-sdk';

import {
  buildUnsignedInspection,
  signReviewedTransaction,
  LOCALNET_GENESIS,
  PROGRAM_ID,
  type CreateInspectionPlan,
  type TransactionIdl,
} from '@aerosettle/transaction-sdk';

import localIdl from './localnet-idl.json';
import evidence from './localnet-evidence.json';

const IDL = localIdl as unknown as TransactionIdl;

const MINT = new PublicKey(
  'HTHpns7gqLAhSBhAzqxhYdyHv9HeXkkRW6aHQfdUjL1G'
);

const VERIFIER = new PublicKey(
  'DmWQhuVujHrJb4jFzo62UnCT3mwnx9GFtVdo8VUu82Wu'
);

const RPC = 'http://127.0.0.1:8899';

const marketplace = new MarketplaceClient({
  baseUrl: window.location.origin,
  timeoutMs: 10000,
});

type Prepared = {
  plan: CreateInspectionPlan;
  lastValidBlockHeight: number;
  creator: string;
  feeLamports: number;
};

type Completion = {
  signature: string;
  order: string;
  status: string;
};

function assertDraftStatus(status: string) {
  if (status !== 'Draft') {
    throw new Error(
      `La WorkOrder no quedó Draft: ${status}`
    );
  }
}

function short(value: string) {
  return value.length < 18
    ? value
    : `${value.slice(0, 8)}...${value.slice(-8)}`;
}

async function simulateUnsigned(
  unsignedBase64: string
): Promise<void> {
  const response = await fetch('/solana-rpc', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({
      jsonrpc: '2.0',
      id: 1,
      method: 'simulateTransaction',
      params: [
        unsignedBase64,
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
    throw new Error(
      `Error RPC de simulación: HTTP ${response.status}`
    );
  }

  const result = await response.json() as {
    error?: { message?: string };
    result?: {
      value?: {
        err: unknown;
        logs?: string[];
      };
    };
  };

  if (result.error) {
    throw new Error(
      result.error.message ?? 'RPC simulation failed'
    );
  }

  if (!result.result?.value) {
    throw new Error(
      'Simulación RPC sin resultado válido'
    );
  }

  if (result.result.value.err !== null) {
    throw new Error(
      'El programa rechazó la simulación:\n'
      + JSON.stringify(result.result.value.err)
      + '\n'
      + (result.result.value.logs ?? []).join('\n')
    );
  }
}

async function fetchCreatedOrder(
  address: string
): Promise<string> {
  // The indexer makes live RPC reads, but a subsequent
  // read may briefly observe an earlier commitment.
  for (let attempt = 0; attempt < 6; attempt++) {
    try {
      const result = await marketplace.getWorkOrder(
        address
      );

      return result.data.status;
    } catch (error) {
      if (
        !(error instanceof Error) ||
        !('status' in error) ||
        error.status !== 404
      ) {
        throw error;
      }

      await new Promise(resolve =>
        setTimeout(resolve, 400)
      );
    }
  }

  throw new Error(
    'Transacción confirmada, pero Discovery aún no encuentra la WorkOrder'
  );
}

export function App() {
  const { connection } = useConnection();

  const {
    publicKey,
    connected,
    signTransaction,
  } = useWallet();

  const [amountText, setAmountText] = useState('10');
  const [prepared, setPrepared] =
    useState<Prepared | null>(null);

  const [completed, setCompleted] =
    useState<Completion | null>(null);

  const [busy, setBusy] = useState(false);
  const [step, setStep] = useState(
    'Conecta una wallet para iniciar.'
  );
  const [error, setError] = useState('');

  const address = publicKey?.toBase58() ?? null;

  useEffect(() => {
    setPrepared(null);
    setCompleted(null);
    setError('');
  }, [address]);

  async function checkLocalnet() {
    const genesis = await connection.getGenesisHash();

    if (genesis !== LOCALNET_GENESIS) {
      throw new Error(
        'RPC no corresponde al ledger Localnet esperado'
      );
    }

    const info = await connection.getAccountInfo(
      PROGRAM_ID, 'confirmed'
    );

    if (!info?.executable) {
      throw new Error(
        'El programa AeroSettle no está desplegado'
      );
    }

    const health = await marketplace.health();

    if (health.genesis !== LOCALNET_GENESIS) {
      throw new Error(
        'Marketplace API consulta otro ledger'
      );
    }
  }

  async function prepare() {
    if (!publicKey) {
      setError('Primero conecta una wallet');
      return;
    }

    setBusy(true);
    setError('');
    setPrepared(null);
    setCompleted(null);

    try {
      setStep('Validando Localnet y Marketplace API...');
      await checkLocalnet();

      if (
        !/^[1-9][0-9]*$/.test(amountText) ||
        amountText.length > 4
      ) {
        throw new Error(
          'Indica una cantidad entera entre 1 y 1000 tokens'
        );
      }

      const tokens = BigInt(amountText);

      if (tokens < 1n || tokens > 1000n) {
        throw new Error(
          'Cantidad fuera del rango 1–1000'
        );
      }

      const balance = await connection.getBalance(
        publicKey,
        'confirmed'
      );

      // A conservative development guard, not a rent quotation.
      if (balance < 10_000_000) {
        throw new Error(
          'La wallet necesita al menos 0.01 SOL de prueba. '
          + 'Usa solana airdrop en Localnet.'
        );
      }

      const clockId = new PublicKey(
        'SysvarC1ock11111111111111111111111111111111'
      );

      const clock = await connection.getAccountInfo(
        clockId, 'confirmed'
      );

      if (!clock || clock.data.length < 40) {
        throw new Error('Clock sysvar inválida');
      }

      const now = clock.data.readBigInt64LE(32);

      const workOrderId = crypto.getRandomValues(
        new Uint8Array(32)
      );

      const manifest = new TextEncoder().encode(
        'aerosettle:synthetic-draft:'
        + Array.from(workOrderId)
          .map(x => x.toString(16).padStart(2, '0'))
          .join('')
      );

      const manifestHash = new Uint8Array(
        await crypto.subtle.digest('SHA-256', manifest)
      );

      const latest =
        await connection.getLatestBlockhash(
          'confirmed'
        );

      const plan = buildUnsignedInspection({
        idl: IDL,
        genesisHash: LOCALNET_GENESIS,
        creator: publicKey,
        tokenMint: MINT,
        verifier: VERIFIER,
        workOrderId,
        manifestHash,
        requiredCapabilities: 33n,
        evidenceRequirements: BigInt(evidence.mask),
        totalAmount: tokens * 1_000_000n,
        chainNow: now,
        executionDeadline: now + 14_400n,
        verificationDeadline: now + 28_800n,
        recentBlockhash: latest.blockhash,
      });

      const existing = await connection.getAccountInfo(
        new PublicKey(plan.review.workOrder),
        'confirmed'
      );

      if (existing) {
        throw new Error(
          'La WorkOrder propuesta ya existe'
        );
      }

      setStep('Simulando instrucción sin firmas...');

      await simulateUnsigned(
        plan.unsignedBase64
      );

      const estimatedFee =
        await connection.getFeeForMessage(
          plan.transaction.compileMessage(),
          'confirmed'
        );

      if (estimatedFee.value === null) {
        throw new Error(
          'No fue posible estimar la comisión'
        );
      }

      setPrepared({
        plan,
        lastValidBlockHeight:
          latest.lastValidBlockHeight,
        creator: publicKey.toBase58(),
        feeLamports: estimatedFee.value,
      });

      setStep(
        'Simulación aprobada. Revisa los datos y autoriza la creación.'
      );
    } catch (cause) {
      setError(
        cause instanceof Error
          ? cause.message
          : String(cause)
      );
      setStep('Preparación detenida.');
    } finally {
      setBusy(false);
    }
  }

  async function testWalletSignature() {
    if (!prepared || !publicKey || !signTransaction) {
      setError('Conecta Phantom y prepara primero la WorkOrder.');
      return;
    }

    setBusy(true);
    setError('');

    try {
      if (
        !connected ||
        publicKey.toBase58() !== prepared.creator
      ) {
        throw new Error(
          'La wallet cambió. Prepara otra transacción.'
        );
      }

      await checkLocalnet();

      const height = await connection.getBlockHeight(
        'confirmed'
      );

      if (height >= prepared.lastValidBlockHeight - 5) {
        setPrepared(null);
        throw new Error(
          'El blockhash está por vencer. Prepara nuevamente.'
        );
      }

      const existing = await connection.getAccountInfo(
        new PublicKey(prepared.plan.review.workOrder),
        'confirmed'
      );

      if (existing) {
        throw new Error(
          'La WorkOrder ya existe. No se requiere una firma nueva.'
        );
      }

      setStep(
        'Phantom solicitará una firma. Esta prueba NO enviará transacciones.'
      );

      const signed = await signReviewedTransaction(
        prepared.plan,
        {
          publicKey,
          signTransaction: async (
            transaction: Transaction
          ) => signTransaction(transaction),
        }
      );

      const creatorSignature = signed.signatures.find(
        entry => entry.publicKey.equals(publicKey)
      );

      if (!creatorSignature?.signature) {
        throw new Error(
          'Phantom no devolvió la firma requerida.'
        );
      }

      setStep(
        '✅ Firma Phantom verificada. '
        + 'El mensaje no fue alterado y NO se transmitió. '
        + 'Puedes autorizar la creación mientras el blockhash siga vigente.'
      );
    } catch (cause) {
      setError(
        cause instanceof Error ? cause.message : String(cause)
      );
      setStep('Prueba de firma no completada. No se envió nada.');
    } finally {
      setBusy(false);
    }
  }

  async function signAndCreate() {
    if (
      !prepared ||
      !publicKey ||
      !signTransaction
    ) {
      setError(
        'No hay transacción preparada o wallet compatible'
      );
      return;
    }

    setBusy(true);
    setError('');

    try {
      if (
        !connected ||
        publicKey.toBase58() !== prepared.creator
      ) {
        throw new Error(
          'La wallet cambió. Debes preparar otra transacción.'
        );
      }

      setStep('Comprobando red y vigencia de la transacción...');

      await checkLocalnet();

      const height =
        await connection.getBlockHeight('confirmed');

      if (
        height >= prepared.lastValidBlockHeight - 5
      ) {
        setPrepared(null);

        throw new Error(
          'Blockhash próximo a vencer. Prepara nuevamente.'
        );
      }

      const pda = new PublicKey(
        prepared.plan.review.workOrder
      );

      if (
        await connection.getAccountInfo(
          pda, 'confirmed'
        )
      ) {
        throw new Error(
          'La WorkOrder ya existe. No se enviará otra transacción.'
        );
      }

      setStep('Solicitando firma a la wallet...');

      const signed = await signReviewedTransaction(
        prepared.plan,
        {
          publicKey,
          signTransaction: async (
            transaction: Transaction
          ) => signTransaction(transaction),
        }
      );

      // The transaction's message is verified by
      // signReviewedTransaction before this point.
      setStep('Enviando transacción firmada a Localnet...');

      const signature =
        await connection.sendRawTransaction(
          signed.serialize(),
          {
            skipPreflight: false,
            preflightCommitment: 'confirmed',
            maxRetries: 3,
          }
        );

      setStep('Esperando confirmación de Solana...');

      const confirmation =
        await connection.confirmTransaction(
          {
            signature,
            blockhash:
              prepared.plan.review.blockhash,
            lastValidBlockHeight:
              prepared.lastValidBlockHeight,
          },
          'confirmed'
        );

      if (confirmation.value.err !== null) {
        throw new Error(
          'La transacción fue rechazada: '
          + JSON.stringify(confirmation.value.err)
        );
      }

      const account = await connection.getAccountInfo(
        pda,
        'confirmed'
      );

      if (
        !account ||
        !account.owner.equals(PROGRAM_ID)
      ) {
        throw new Error(
          'La cuenta de WorkOrder no pertenece a AeroSettle'
        );
      }

      setStep('Consultando WorkOrder mediante Marketplace API...');

      const status = await fetchCreatedOrder(
        pda.toBase58()
      );

      assertDraftStatus(status);

      setCompleted({
        signature,
        order: pda.toBase58(),
        status,
      });

      setPrepared(null);
      setStep('WorkOrder creada y verificada.');
    } catch (cause) {
      setError(
        cause instanceof Error
          ? cause.message
          : String(cause)
      );

      setStep(
        'No se pudo completar o verificar la operación. '
        + 'Consulta la cuenta antes de intentar otra transacción.'
      );
    } finally {
      setBusy(false);
    }
  }

  const review = prepared?.plan.review;

  return (
    <main className="layout">
      <header className="header">
        <div>
          <div className="eyebrow">AEROSETTLE • LOCALNET</div>
          <h1>Marketplace Console</h1>
          <p>
            Publicación de inspecciones mediante
            una wallet externa.
          </p>
        </div>
        <WalletMultiButton />
      </header>

      <section className="notice">
        <strong>Entorno de desarrollo</strong>
        <span>
          RPC: {RPC}. Esta pantalla sólo crea órdenes Draft.
          No financia escrow ni representa una ejecución física.
        </span>
      </section>

      <div className="columns">
        <section className="panel">
          <h2>1. Nueva inspección</h2>

          <div className="field">
            <label>Wallet creadora</label>
            <div className="readonly">
              {address ?? 'Sin conectar'}
            </div>
          </div>

          <div className="field">
            <label>Tipo de trabajo</label>
            <div className="readonly">
              Inspection • Aerial + GPS
            </div>
          </div>

          <div className="field">
            <label>
              Recompensa ofrecida (tokens demo)
            </label>
            <input
              type="number"
              min="1"
              max="1000"
              step="1"
              value={amountText}
              onChange={event => {
                setAmountText(event.target.value);
                setPrepared(null);
              }}
            />
          </div>

          <div className="field">
            <label>Mint de Localnet</label>
            <div className="readonly small">
              {MINT.toBase58()}
            </div>
          </div>

          <div className="field">
            <label>Verificador designado</label>
            <div className="readonly small">
              {VERIFIER.toBase58()}
            </div>
          </div>

          <p className="hint">
            Ejecución: 4 horas. Verificación: 8 horas.
            El monto se registra en la WorkOrder,
            pero no se transfiere hasta Funding.
          </p>

          <button
            className="primary"
            disabled={!connected || busy}
            onClick={() => void prepare()}
          >
            {busy
              ? 'Procesando...'
              : 'Preparar y simular WorkOrder'}
          </button>
        </section>

        <section className="panel">
          <h2>2. Revisión y autorización</h2>

          {!review && !completed && (
            <p className="placeholder">
              Prepara una inspección para mostrar
              la instrucción y sus parámetros.
            </p>
          )}

          {review && (
            <>
              <dl className="review">
                <dt>Red</dt>
                <dd>{review.network}</dd>

                <dt>Programa</dt>
                <dd>{short(review.programId)}</dd>

                <dt>WorkOrder PDA</dt>
                <dd className="small">
                  {review.workOrder}
                </dd>

                <dt>Tipo</dt>
                <dd>{review.workType}</dd>

                <dt>Pago</dt>
                <dd>{review.paymentModel}</dd>

                <dt>Monto base</dt>
                <dd>{review.totalAmountBaseUnits}</dd>

                <dt>Capacidades</dt>
                <dd>{review.requiredCapabilities}</dd>

                <dt>Comisión estimada</dt>
                <dd>{prepared?.feeLamports} lamports</dd>

                <dt>Instrucciones</dt>
                <dd>1 • create_work_order</dd>
              </dl>

              <p className="success">
                Simulación RPC correcta. Falta la firma.
              </p>

              <button
                className="primary"
                disabled={busy || !signTransaction}
                onClick={() => void testWalletSignature()}
              >
                Probar firma (sin enviar)
              </button>

              <p className="hint">
                Esta operación sólo verifica la compatibilidad
                de Phantom y la integridad de la firma.
                No escribe ninguna cuenta en Solana.
              </p>

              <button
                className="primary"
                disabled={busy || !signTransaction}
                onClick={() => void signAndCreate()}
              >
                Autorizar y crear Draft
              </button>

              <p className="hint">
                Al seleccionar este botón, la wallet
                solicitará tu autorización y después
                enviaremos la transacción a Localnet.
              </p>
            </>
          )}

          {completed && (
            <div className="completed">
              <h3>WorkOrder creada</h3>
              <p>Estado: <strong>{completed.status}</strong></p>
              <p>Cuenta: {completed.order}</p>
              <p>Firma: {completed.signature}</p>
              <p>
                Escrow: todavía no financiado.
              </p>
            </div>
          )}
        </section>
      </div>

      <section className="status panel">
        <strong>Estado de operación</strong>
        <p>{step}</p>
        {error && (
          <pre className="error">{error}</pre>
        )}
      </section>
    </main>
  );
}
