import { useCopy, useI18n } from '../../app/i18n';
import { useEffect, useState } from 'react';
import { Link, useSearchParams } from 'react-router';
import { CopyAddress, DataGrid, Icon, PageHeader } from '../../components/ui';
import { EmbodimentGlyph, SustainabilityBadge } from '../../components/ui/viz';
import { api as marketplace, verifyMeta } from '../../app/api';
import { MINT, VERIFIER } from '../../app/config';
import { SETTLEMENT_SYMBOL, agentById, usd } from '../../app/atlas';

import { useConnection, useWallet } from '@solana/wallet-adapter-react';

import { WalletControl } from '../../components/ui/WalletControl';

import { PublicKey, Transaction } from '@solana/web3.js';

import {
  buildUnsignedInspection,
  signReviewedTransaction,
  LOCALNET_GENESIS,
  PROGRAM_ID,
  type CreateInspectionPlan,
  type TransactionIdl,
} from '@aerosettle/transaction-sdk';

import localIdl from '../../localnet-idl.json';
import evidence from '../../localnet-evidence.json';
import '../../styles/missions.css';

const IDL = localIdl as unknown as TransactionIdl;

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
    throw new Error(`La WorkOrder no quedó Draft: ${status}`);
  }
}

async function simulateUnsigned(unsignedBase64: string): Promise<void> {
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
    throw new Error(`Error RPC de simulación: HTTP ${response.status}`);
  }

  const result = (await response.json()) as {
    error?: { message?: string };
    result?: {
      value?: {
        err: unknown;
        logs?: string[];
      };
    };
  };

  if (result.error) {
    throw new Error(result.error.message ?? 'RPC simulation failed');
  }

  if (!result.result?.value) {
    throw new Error('Simulación RPC sin resultado válido');
  }

  if (result.result.value.err !== null) {
    throw new Error(
      'El programa rechazó la simulación:\n' +
        JSON.stringify(result.result.value.err) +
        '\n' +
        (result.result.value.logs ?? []).join('\n')
    );
  }
}

async function fetchCreatedOrder(address: string): Promise<string> {
  // The indexer makes live RPC reads, but a subsequent
  // read may briefly observe an earlier commitment.
  for (let attempt = 0; attempt < 6; attempt++) {
    try {
      const result = await marketplace.getWorkOrder(address);
      verifyMeta(result.meta);
      if (result.data.work_order_account !== address)
        throw new Error('La API devolvió otra WorkOrder.');
      return result.data.status;
    } catch (error) {
      if (
        !(error instanceof Error) ||
        !('status' in error) ||
        error.status !== 404
      ) {
        throw error;
      }

      await new Promise((resolve) => setTimeout(resolve, 400));
    }
  }

  throw new Error(
    'Transacción confirmada, pero Discovery aún no encuentra la WorkOrder'
  );
}

export default function CreateMission() {
  const { t, locale } = useI18n();
  const c = useCopy();
  const [params, setParams] = useSearchParams();
  const hiredAgent = agentById(params.get('agent') ?? '');

  const [page, setPage] = useState(0);
  const [simulated, setSimulated] = useState(false);
  const { connection } = useConnection();

  const { publicKey, connected, signTransaction } = useWallet();

  const [amountText, setAmountText] = useState('10');
  const [prepared, setPrepared] = useState<Prepared | null>(null);

  const [completed, setCompleted] = useState<Completion | null>(null);

  const [busy, setBusy] = useState(false);
  const [step, setStep] = useState('Conecta una wallet para iniciar.');
  const [error, setError] = useState('');

  const address = publicKey?.toBase58() ?? null;

  useEffect(() => {
    setPrepared(null);
    setCompleted(null);
    setSimulated(false);
    setPage(0);
    setError('');
  }, [address]);

  async function checkLocalnet() {
    const genesis = await connection.getGenesisHash();

    if (genesis !== LOCALNET_GENESIS) {
      throw new Error('RPC no corresponde al ledger esperado de la red');
    }

    const info = await connection.getAccountInfo(PROGRAM_ID, 'confirmed');

    if (!info?.executable) {
      throw new Error('El programa del protocolo no está desplegado');
    }

    const health = await marketplace.health();

    if (health.genesis !== LOCALNET_GENESIS) {
      throw new Error('Marketplace API consulta otro ledger');
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
      setStep(
        c(
          'Validating Solana network and Marketplace API…',
          'Validando la red Solana y Marketplace API…'
        )
      );
      await checkLocalnet();

      if (!/^[1-9][0-9]*$/.test(amountText) || amountText.length > 4) {
        throw new Error('Indica una cantidad entera entre 1 y 1000 tokens');
      }

      const tokens = BigInt(amountText);

      if (tokens < 1n || tokens > 1000n) {
        throw new Error('Cantidad fuera del rango 1–1000');
      }

      const balance = await connection.getBalance(publicKey, 'confirmed');

      // A conservative guard, not a rent quotation.
      if (balance < 10_000_000) {
        throw new Error(
          'La wallet necesita al menos 0.01 SOL para cubrir renta y comisión de red.'
        );
      }

      const clockId = new PublicKey(
        'SysvarC1ock11111111111111111111111111111111'
      );

      const clock = await connection.getAccountInfo(clockId, 'confirmed');

      if (!clock || clock.data.length < 40) {
        throw new Error('Clock sysvar inválida');
      }

      const now = clock.data.readBigInt64LE(32);

      const workOrderId = crypto.getRandomValues(new Uint8Array(32));

      const manifest = new TextEncoder().encode(
        'aerosettle:synthetic-draft:' +
          Array.from(workOrderId)
            .map((x) => x.toString(16).padStart(2, '0'))
            .join('')
      );

      const manifestHash = new Uint8Array(
        await crypto.subtle.digest('SHA-256', manifest)
      );

      const latest = await connection.getLatestBlockhash('confirmed');

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
        throw new Error('La WorkOrder propuesta ya existe');
      }

      // Review the exact unsigned SDK plan before the separate simulation step.

      const estimatedFee = await connection.getFeeForMessage(
        plan.transaction.compileMessage(),
        'confirmed'
      );

      if (estimatedFee.value === null) {
        throw new Error('No fue posible estimar la comisión');
      }

      setPrepared({
        plan,
        lastValidBlockHeight: latest.lastValidBlockHeight,
        creator: publicKey.toBase58(),
        feeLamports: estimatedFee.value,
      });

      setStep(
        'Instrucción preparada. Revisa la PDA y los parámetros antes de simular.'
      );
      setSimulated(false);
      setPage(2);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : String(cause));
      setStep('Preparación detenida.');
    } finally {
      setBusy(false);
    }
  }

  async function simulateReviewed() {
    if (!prepared || busy) return;
    setBusy(true);
    setError('');
    setSimulated(false);
    try {
      await checkLocalnet();
      if (
        address !== prepared.creator ||
        (await connection.getBlockHeight('confirmed')) >=
          prepared.lastValidBlockHeight - 5
      )
        throw new Error(
          'Wallet distinta o blockhash por vencer. Vuelve a preparar.'
        );
      await simulateUnsigned(prepared.plan.unsignedBase64);
      setSimulated(true);
      setStep('Simulación aprobada. No se ha enviado ninguna transacción.');
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : String(cause));
    } finally {
      setBusy(false);
    }
  }

  async function testWalletSignature() {
    if (!simulated || !prepared || !publicKey || !signTransaction) {
      setError('Conecta Phantom y prepara primero la WorkOrder.');
      return;
    }

    setBusy(true);
    setError('');

    try {
      if (!connected || publicKey.toBase58() !== prepared.creator) {
        throw new Error('La wallet cambió. Prepara otra transacción.');
      }

      await checkLocalnet();

      const height = await connection.getBlockHeight('confirmed');

      if (height >= prepared.lastValidBlockHeight - 5) {
        setPrepared(null);
        throw new Error('El blockhash está por vencer. Prepara nuevamente.');
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
        'Phantom solicitará una firma. Esta verificación NO enviará transacciones.'
      );

      const signed = await signReviewedTransaction(prepared.plan, {
        publicKey,
        signTransaction: async (transaction: Transaction) =>
          signTransaction(transaction),
      });

      const creatorSignature = signed.signatures.find((entry) =>
        entry.publicKey.equals(publicKey)
      );

      if (!creatorSignature?.signature) {
        throw new Error('Phantom no devolvió la firma requerida.');
      }

      setStep(
        '✅ Firma Phantom verificada. ' +
          'El mensaje no fue alterado y NO se transmitió. ' +
          'Puedes autorizar la creación mientras el blockhash siga vigente.'
      );
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : String(cause));
      setStep('Verificación de firma no completada. No se envió nada.');
    } finally {
      setBusy(false);
    }
  }

  async function signAndCreate() {
    if (!simulated || !prepared || !publicKey || !signTransaction) {
      setError('No hay transacción preparada o wallet compatible');
      return;
    }

    setBusy(true);
    setError('');

    try {
      if (!connected || publicKey.toBase58() !== prepared.creator) {
        throw new Error('La wallet cambió. Debes preparar otra transacción.');
      }

      setStep('Comprobando red y vigencia de la transacción...');

      await checkLocalnet();

      const height = await connection.getBlockHeight('confirmed');

      if (height >= prepared.lastValidBlockHeight - 5) {
        setPrepared(null);

        throw new Error('Blockhash próximo a vencer. Prepara nuevamente.');
      }

      const pda = new PublicKey(prepared.plan.review.workOrder);

      if (await connection.getAccountInfo(pda, 'confirmed')) {
        throw new Error(
          'La WorkOrder ya existe. No se enviará otra transacción.'
        );
      }

      setStep('Solicitando firma a la wallet...');

      const signed = await signReviewedTransaction(prepared.plan, {
        publicKey,
        signTransaction: async (transaction: Transaction) =>
          signTransaction(transaction),
      });

      // Revalidate after the wallet prompt too: the user may leave it open.
      await checkLocalnet();
      const [validHash, currentHeight, existingAfterSignature] =
        await Promise.all([
          connection.isBlockhashValid(prepared.plan.review.blockhash, {
            commitment: 'confirmed',
          }),
          connection.getBlockHeight('confirmed'),
          connection.getAccountInfo(pda, 'confirmed'),
        ]);
      if (
        !validHash.value ||
        currentHeight >= prepared.lastValidBlockHeight - 5 ||
        existingAfterSignature
      ) {
        setPrepared(null);
        setSimulated(false);
        setPage(1);
        throw new Error(
          'El estado o blockhash cambió durante la firma. Prepara otra instrucción.'
        );
      }
      // The transaction's message is verified by
      // signReviewedTransaction before this point.
      setStep(
        c(
          'Broadcasting signed transaction to Solana…',
          'Enviando transacción firmada a Solana…'
        )
      );

      const signature = await connection.sendRawTransaction(
        signed.serialize(),
        {
          skipPreflight: false,
          preflightCommitment: 'confirmed',
          maxRetries: 3,
        }
      );

      setStep('Esperando confirmación de Solana...');

      const confirmation = await connection.confirmTransaction(
        {
          signature,
          blockhash: prepared.plan.review.blockhash,
          lastValidBlockHeight: prepared.lastValidBlockHeight,
        },
        'confirmed'
      );

      if (confirmation.value.err !== null) {
        throw new Error(
          'La transacción fue rechazada: ' +
            JSON.stringify(confirmation.value.err)
        );
      }

      const account = await connection.getAccountInfo(pda, 'confirmed');

      if (!account || !account.owner.equals(PROGRAM_ID)) {
        throw new Error('La cuenta de WorkOrder no pertenece al programa');
      }

      setStep('Consultando WorkOrder mediante Marketplace API...');

      const status = await fetchCreatedOrder(pda.toBase58());

      assertDraftStatus(status);

      setCompleted({
        signature,
        order: pda.toBase58(),
        status,
      });

      setPrepared(null);
      setPage(4);
      setStep('WorkOrder creada y verificada.');
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : String(cause));

      setStep(
        'No se pudo completar o verificar la operación. ' +
          'Consulta la cuenta antes de intentar otra transacción.'
      );
    } finally {
      setBusy(false);
    }
  }

  const review = prepared?.plan.review;
  const steps = [
    'Definición',
    'Condiciones',
    'Revisión',
    'Simulación y firma',
    'Resultado',
  ];
  return (
    <>
      <PageHeader
        eyebrow={c('NEW MISSION · SOLANA', 'NUEVA MISIÓN · SOLANA')}
        title={c('Post a mission', 'Publicar una misión')}
        description={c(
          'Configure the operational parameters, simulate the instruction, and publish an on-chain work order on Solana.',
          'Configura los parámetros operativos, simula la instrucción y publica una orden de trabajo on-chain en Solana.'
        )}
      />

      {hiredAgent && (
        <section
          className="hiring-banner"
          aria-label={c('Selected agent', 'Agente seleccionado')}
        >
          <div className="hiring-banner-info">
            <EmbodimentGlyph
              embodiment={hiredAgent.embodiment}
              tone={hiredAgent.sustainability}
              size={48}
            />
            <div>
              <span className="eyebrow" style={{ marginBottom: 4 }}>
                {c('PRESELECTED AGENT', 'AGENTE PRESELECCIONADO')}
              </span>
              <strong>
                {c('Hiring', 'Contratando a')} {hiredAgent.name}
              </strong>
              <small>
                {hiredAgent.model} · {hiredAgent.city}, {hiredAgent.country} ·{' '}
                {c('Standard rate:', 'Tarifa estándar:')}{' '}
                {usd(hiredAgent.rate, locale)} {SETTLEMENT_SYMBOL}
              </small>
            </div>
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
            <SustainabilityBadge value={hiredAgent.sustainability} />
            <Link className="button" to={`/app/agents/${hiredAgent.id}`}>
              {c('View agent', 'Ver agente')}
            </Link>
            <button
              type="button"
              className="button"
              onClick={() => setParams({})}
              aria-label={c('Clear selected agent', 'Quitar agente seleccionado')}
            >
              <Icon name="close" />
            </button>
          </div>
        </section>
      )}

      <ol className="wizard-steps" aria-label={t('Pasos de creación')}>
        {steps.map((label, index) => (
          <li
            key={label}
            className={page === index ? 'current' : ''}
            aria-current={page === index ? 'step' : undefined}
          >
            <span>{index + 1}</span>
            {t(label)}
          </li>
        ))}
      </ol>
      <div className="wizard-layout">
        <section className="panel wizard-content">
          {page === 0 && (
            <>
              <span className="eyebrow">{t('PASO 01 / DEFINICIÓN')}</span>
              <h2>
                {c(
                  'Aerial inspection work order',
                  'Orden de inspección aérea'
                )}
              </h2>
              <p>
                {c(
                  'Creates an on-chain Inspection work order requiring aerial mobility and GPS telemetry, committing the cryptographic manifest digest.',
                  'Crea una orden de trabajo on-chain de tipo Inspection con movilidad aérea y telemetría GPS, comprometiendo el resumen criptográfico del manifiesto.'
                )}
              </p>
              <DataGrid
                items={[
                  [t('Tipo'), t('Inspection')],
                  [t('Capacidades'), t('Movilidad aérea + GPS (mask 33)')],
                  [t('Evidencia requerida'), String(evidence.mask)],
                ]}
              />
              <p className="hint">
                {c(
                  'Publishing the work order commits the contract parameters on Solana before escrow funding and agent claim.',
                  'Publicar la orden compromete los parámetros del contrato en Solana antes del fondeo en custodia y la reclamación del agente.'
                )}
              </p>
              <button className="primary" onClick={() => setPage(1)}>
                {t('Continuar a condiciones →')}
              </button>
            </>
          )}
          {page === 1 && (
            <>
              <span className="eyebrow">{t('PASO 02 / CONDICIONES')}</span>
              <h2>{t('Recompensa y ventanas')}</h2>
              <label>
                {c(
                  `Offered reward (${SETTLEMENT_SYMBOL})`,
                  `Recompensa ofrecida (${SETTLEMENT_SYMBOL})`
                )}
                <input
                  type="number"
                  min="1"
                  max="1000"
                  step="1"
                  value={amountText}
                  onChange={(event) => {
                    setAmountText(event.target.value);
                    setPrepared(null);
                    setSimulated(false);
                  }}
                />
              </label>
              <DataGrid
                items={[
                  [t('Modelo de pago'), t('Fixed')],
                  [
                    t('Ejecución'),
                    t('4 horas desde el clock on-chain al preparar'),
                  ],
                  [
                    t('Verificación'),
                    t('8 horas desde el clock on-chain al preparar'),
                  ],
                  [
                    c('Settlement mint', 'Mint de liquidación'),
                    <CopyAddress value={MINT.toBase58()} />,
                  ],
                  [
                    t('Verificador'),
                    <CopyAddress value={VERIFIER.toBase58()} />,
                  ],
                ]}
              />
              {!connected && (
                <div className="notice">
                  <p>
                    {c(
                      'Connect a wallet to prepare the instruction and verify your SOL balance for network fees.',
                      'Conecta una wallet para preparar la instrucción y comprobar el saldo SOL para comisiones de red.'
                    )}
                  </p>
                  <WalletControl />
                </div>
              )}
              <div className="actions">
                <button disabled={busy} onClick={() => setPage(0)}>
                  {t('Atrás')}
                </button>
                <button
                  className="primary"
                  disabled={!connected || busy}
                  onClick={() => void prepare()}
                >
                  {busy
                    ? t('Preparando…')
                    : t('Preparar instrucción sin enviar')}
                </button>
              </div>
            </>
          )}
          {page === 2 && review && (
            <>
              <span className="eyebrow">{t('PASO 03 / REVISIÓN')}</span>
              <h2>{t('Revisa la instrucción')}</h2>
              <DataGrid
                items={[
                  [t('Red'), 'Solana'],
                  [t('Programa'), <CopyAddress value={review.programId} />],
                  ['Work Order PDA', <CopyAddress value={review.workOrder} />],
                  [t('Tipo de trabajo'), review.workType],
                  [t('Pago'), review.paymentModel],
                  [t('Monto (unidades base)'), review.totalAmountBaseUnits],
                  [t('Capacidades'), review.requiredCapabilities],
                  [t('Comisión estimada'), `${prepared.feeLamports} lamports`],
                  [t('Instrucción'), '1 · create_work_order'],
                ]}
              />
              <div className="actions">
                <button disabled={busy} onClick={() => setPage(1)}>
                  {t('Editar condiciones')}
                </button>
                <button className="primary" onClick={() => setPage(3)}>
                  {t('Revisado · continuar')}
                </button>
              </div>
            </>
          )}
          {page === 3 && (
            <>
              <span className="eyebrow">{t('PASO 04 / AUTORIZACIÓN')}</span>
              <h2>{t('Simula antes de firmar')}</h2>
              <p>
                {c(
                  'First simulate the unsigned message. Then authorize broadcast with your wallet to create the Draft work order on Solana.',
                  'Primero se simula el mensaje sin firmas. Después, la wallet puede autorizar su envío a Solana para crear la cuenta Draft.'
                )}
              </p>
              <div className="actions vertical">
                <button
                  disabled={busy || !prepared}
                  onClick={() => void simulateReviewed()}
                >
                  {t('1. Simular sin transacción')}
                </button>
                <button
                  disabled={busy || !prepared || !simulated || !signTransaction}
                  onClick={() => void testWalletSignature()}
                >
                  {c(
                    '2. Verify signature without broadcasting (optional)',
                    '2. Verificar firma sin enviar (opcional)'
                  )}
                </button>
                <button
                  className="primary"
                  disabled={busy || !prepared || !simulated || !signTransaction}
                  onClick={() => void signAndCreate()}
                >
                  {t('3. Firmar y enviar · crear Draft')}
                </button>
              </div>
              <p className="hint">
                {c(
                  'Creating a Draft covers network fees and account rent in SOL. Escrow funding takes place in the next stage.',
                  'Crear la orden Draft cubre la comisión de red y la renta de cuenta en SOL. El fondeo en custodia se realiza en el siguiente paso.'
                )}
              </p>
              <button disabled={busy} onClick={() => setPage(prepared ? 2 : 1)}>
                {t('Volver a')} {prepared ? t('revisión') : t('preparar')}
              </button>
            </>
          )}
          {page === 4 && completed && (
            <div className="completed">
              <span className="eyebrow">{t('PASO 05 / CONFIRMADO')}</span>
              <h2>
                {c(
                  'Your mission is live on Solana.',
                  'Tu misión ya está publicada en Solana.'
                )}
              </h2>
              <DataGrid
                items={[
                  [t('Estado verificado'), completed.status],
                  [t('Cuenta'), <CopyAddress value={completed.order} />],
                  [
                    t('Firma confirmada'),
                    <CopyAddress
                      label={t('firma')}
                      value={completed.signature}
                    />,
                  ],
                  ['Escrow', t('Todavía no financiado')],
                ]}
              />
              <Link
                className="button primary"
                to={`/app/missions/${completed.order}`}
              >
                {t('Abrir misión →')}
              </Link>
            </div>
          )}
        </section>
        <aside className="panel wizard-summary">
          <h3>{t('Antes de empezar')}</h3>
          <p>{t('Crear Draft registra las condiciones del trabajo.')}</p>
          <div className="notice">
            {t(
              'Funding es un paso separado. Encontrarás esa acción en Escrow & Settlement de la misión.'
            )}
          </div>
          <span className="micro">{t('WALLET CREADORA')}</span>
          {address ? (
            <CopyAddress value={address} />
          ) : (
            <p>{t('Sin conectar')}</p>
          )}
          <p className="hint">
            {t(
              'El SDK conserva la revisión de IDL, genesis, PDA, blockhash y firmas.'
            )}
          </p>
        </aside>
      </div>
      <section className="operation-status" aria-live="polite">
        <strong>{t('Estado de operación')}</strong>
        <p>{t(step)}</p>
        {error && (
          <div role="alert">
            <p>
              {t(
                'No se pudo completar esta operación. Revisa el estado antes de reintentar.'
              )}
            </p>
            <details>
              <summary>{t('Diagnóstico')}</summary>
              <pre>{error}</pre>
            </details>
          </div>
        )}
      </section>
    </>
  );
}
