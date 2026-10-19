import { useCopy, useI18n } from '../../app/i18n';
import { useEffect, useState } from 'react';
import { Buffer } from 'buffer';

import {
  PublicKey,
  Transaction,
  TransactionInstruction,
} from '@solana/web3.js';

import { useConnection, useWallet } from '@solana/wallet-adapter-react';

import { type Agent, type WorkOrder } from '@aerosettle/marketplace-sdk';

import { LOCALNET_GENESIS, PROGRAM_ID } from '@aerosettle/transaction-sdk';

import localIdl from '../../localnet-idl.json';
import { api as API } from '../../app/api';
import { CopyAddress } from '../../components/ui';

type AccountMeta = {
  name: string;
  signer?: boolean;
  isSigner?: boolean;
  writable?: boolean;
  isMut?: boolean;
  address?: string;
};

type IdlItem = {
  name: string;
  discriminator: number[];
  accounts?: AccountMeta[];
  args?: unknown[];
};

type ClaimIdl = {
  address: string;
  instructions: IdlItem[];
  accounts: IdlItem[];
};

type Props = {
  agent: Agent | null;
  mission: WorkOrder | null;
  onClaimed: () => void;
};

type Inspection = {
  authority: string;
  owner: string;
  orderSnapshot: string;
  agentSnapshot: string;
  remaining: number;
};

type Prepared = Inspection & {
  order: string;
  agent: string;
  unsignedBase64: string;
  messageBase64: string;
  blockhash: string;
  lastValidBlockHeight: number;
};

const IDL = localIdl as unknown as ClaimIdl;

const CLOCK = new PublicKey('SysvarC1ock11111111111111111111111111111111');

const encoder = new TextEncoder();

function normalize(name: string): string {
  return name
    .split('::')
    .at(-1)!
    .replace(/[^a-zA-Z0-9]/g, '')
    .toLowerCase();
}

function requireValid(
  condition: unknown,
  explanation: string
): asserts condition {
  if (!condition) throw new Error(explanation);
}

function unique(items: IdlItem[], name: string): IdlItem {
  const matching = items.filter(
    (item) => normalize(item.name) === normalize(name)
  );

  requireValid(matching.length === 1, `IDL incompatible: ${name}`);

  return matching[0]!;
}

function hex(data: Uint8Array): string {
  return Buffer.from(data).toString('hex');
}

async function verifyDiscriminator(
  value: number[],
  canonicalName: string
): Promise<Buffer> {
  requireValid(
    Array.isArray(value) &&
      value.length === 8 &&
      value.every((x) => Number.isInteger(x) && x >= 0 && x <= 255),
    `Discriminador inválido: ${canonicalName}`
  );

  const digest = new Uint8Array(
    await crypto.subtle.digest('SHA-256', encoder.encode(canonicalName))
  );

  const expected = Buffer.from(digest.subarray(0, 8));
  const actual = Buffer.from(value);

  requireValid(
    actual.equals(expected),
    `Discriminador no canónico: ${canonicalName}`
  );

  return actual;
}

async function claimDiscriminator(): Promise<Buffer> {
  requireValid(
    IDL.address === PROGRAM_ID.toBase58(),
    'Program ID incompatible con el IDL'
  );

  const instruction = unique(IDL.instructions, 'claim_work_order');

  const expected: Array<[string, boolean, boolean]> = [
    ['protocol_config', false, false],
    ['work_order', false, true],
    ['agent_account', false, false],
    ['agent_signer', true, false],
  ];

  requireValid(
    Array.isArray(instruction.args) &&
      instruction.args.length === 0 &&
      Array.isArray(instruction.accounts) &&
      instruction.accounts.length === expected.length,
    'ClaimWorkOrder tiene una estructura inesperada'
  );

  for (let i = 0; i < expected.length; i++) {
    const meta = instruction.accounts[i]!;
    const [name, signer, writable] = expected[i]!;

    requireValid(
      normalize(meta.name) === normalize(name) &&
        Boolean(meta.signer ?? meta.isSigner) === signer &&
        Boolean(meta.writable ?? meta.isMut) === writable,
      `Metadatos incompatibles en ClaimWorkOrder: ${name}`
    );
  }

  return verifyDiscriminator(
    instruction.discriminator,
    'global:claim_work_order'
  );
}

function bytes32(value: string, label: string): Buffer {
  requireValid(/^[a-f0-9]{64}$/i.test(value), `${label} no contiene 32 bytes`);

  return Buffer.from(value, 'hex');
}

function address(data: Buffer, start: number): PublicKey {
  return new PublicKey(data.subarray(start, start + 32));
}

async function decodeAgent(
  accountData: Buffer,
  agent: Agent,
  config: PublicKey
): Promise<{ authority: string; owner: string }> {
  const definition = unique(IDL.accounts, 'AgentAccount');

  const discriminator = await verifyDiscriminator(
    definition.discriminator,
    'account:AgentAccount'
  );

  requireValid(
    accountData.length === 196 &&
      accountData.subarray(0, 8).equals(discriminator) &&
      accountData[8] === 1,
    'AgentAccount no corresponde al esquema v1'
  );

  const agentId = bytes32(agent.agent_id, 'Agent ID');

  const [derivedAgent] = PublicKey.findProgramAddressSync(
    [encoder.encode('agent'), config.toBuffer(), agentId],
    PROGRAM_ID
  );

  requireValid(
    derivedAgent.toBase58() === agent.agent_account &&
      address(accountData, 9).equals(config) &&
      accountData.subarray(41, 73).equals(agentId),
    'PDA o identidad del agente incompatible'
  );

  const capabilityMask = accountData.readBigUInt64LE(138).toString();

  // AgentStatus::Active es la primera variante de v1.
  requireValid(
    accountData[178] === 0 &&
      agent.active === true &&
      agent.status === 'Active' &&
      capabilityMask === agent.capabilities,
    'Estado o capacidades del agente cambiaron'
  );

  return {
    owner: address(accountData, 73).toBase58(),
    authority: address(accountData, 105).toBase58(),
  };
}

async function simulateClaim(unsignedBase64: string): Promise<string[]> {
  const response = await fetch('/solana-rpc', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
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

  requireValid(response.ok, 'RPC de simulación no disponible');

  const payload = (await response.json()) as {
    error?: { message?: string };
    result?: {
      value?: {
        err: unknown;
        logs?: string[];
      };
    };
  };

  requireValid(!payload.error, payload.error?.message ?? 'Error del simulador');

  const result = payload.result?.value;

  requireValid(result, 'RPC no devolvió la simulación');

  requireValid(
    result.err === null,
    'ClaimWorkOrder rechazado: ' +
      JSON.stringify(result.err) +
      '\n' +
      (result.logs ?? []).slice(-8).join('\n')
  );

  return result.logs ?? [];
}

function describe(cause: unknown): string {
  return cause instanceof Error ? cause.message : String(cause);
}

export default function ClaimMissionPanel({
  agent,
  mission,
  onClaimed,
}: Props) {
  const { t } = useI18n();
  const c = useCopy();

  const { connection } = useConnection();

  const { connected, publicKey, signTransaction } = useWallet();

  const wallet = publicKey?.toBase58() ?? '';

  const [prepared, setPrepared] = useState<Prepared | null>(null);
  const [busy, setBusy] = useState(false);
  const [step, setStep] = useState('Selecciona un agente y una misión.');
  const [error, setError] = useState('');
  const [signature, setSignature] = useState('');

  useEffect(() => {
    setPrepared(null);
    setSignature('');
    setError('');
    setStep('Preflight pendiente.');
  }, [
    agent?.agent_account,
    mission?.work_order_account,
    wallet,
    mission?.status,
  ]);

  async function inspect(): Promise<Inspection> {
    requireValid(agent && mission, 'Selecciona agente y misión');

    const genesis = await connection.getGenesisHash();
    const health = await API.health();

    requireValid(
      genesis === LOCALNET_GENESIS && health.genesis === LOCALNET_GENESIS,
      'La red no coincide con el ledger de protocolo esperado'
    );

    const [program, matches, orderInfo, agentInfo, clockInfo] =
      await Promise.all([
        connection.getAccountInfo(PROGRAM_ID, 'confirmed'),
        API.getMatches(mission.work_order_account),
        connection.getAccountInfo(
          new PublicKey(mission.work_order_account),
          'confirmed'
        ),
        connection.getAccountInfo(
          new PublicKey(agent.agent_account),
          'confirmed'
        ),
        connection.getAccountInfo(CLOCK, 'confirmed'),
      ]);

    requireValid(
      program?.executable && matches.meta.program_id === PROGRAM_ID.toBase58(),
      'Programa o Marketplace API incompatibles'
    );

    const order = matches.data.work_order;

    requireValid(
      order.work_order_account === mission.work_order_account &&
        order.status === 'Open' &&
        order.is_open &&
        order.discoverable,
      'La misión ya no está abierta para Claim'
    );

    const eligibility = matches.data.evaluations.find(
      (item) => item.agent_account === agent.agent_account
    );

    const eligibleAgent = matches.data.eligible_agents.find(
      (item) => item.agent_account === agent.agent_account
    );

    requireValid(
      eligibility?.eligible === true &&
        eligibility.rejection === null &&
        eligibleAgent?.active === true &&
        eligibleAgent.status === 'Active',
      'El motor del protocolo no autoriza este agente para la misión'
    );

    // Narrow nullable RPC responses before accessing account data.
    requireValid(orderInfo !== null, 'WorkOrder no encontrada on-chain');

    requireValid(agentInfo !== null, 'AgentAccount no encontrada on-chain');

    requireValid(clockInfo !== null, 'Clock sysvar no disponible');

    requireValid(
      orderInfo.owner.equals(PROGRAM_ID) &&
        agentInfo.owner.equals(PROGRAM_ID) &&
        clockInfo.data.length >= 40,
      'Cuentas on-chain inválidas'
    );

    const [config] = PublicKey.findProgramAddressSync(
      [encoder.encode('protocol_config')],
      PROGRAM_ID
    );

    requireValid(
      order.protocol_config === config.toBase58() &&
        eligibleAgent.protocol_config === config.toBase58(),
      'ProtocolConfig incompatible'
    );

    const creator = new PublicKey(String(order.creator));

    const [derivedOrder] = PublicKey.findProgramAddressSync(
      [
        encoder.encode('work_order'),
        config.toBuffer(),
        creator.toBuffer(),
        bytes32(String(order.work_order_id), 'Work Order ID'),
      ],
      PROGRAM_ID
    );

    requireValid(
      derivedOrder.toBase58() === mission.work_order_account,
      'PDA de WorkOrder inválida'
    );

    const identity = await decodeAgent(
      Buffer.from(agentInfo.data),
      eligibleAgent,
      config
    );

    const chainNow = Number(clockInfo.data.readBigInt64LE(32));

    const remaining = order.execution_deadline - chainNow;

    requireValid(
      Number.isSafeInteger(chainNow) && remaining > 120,
      'La misión venció o quedan menos de 120 segundos'
    );

    const required = BigInt(order.required_capabilities);
    const available = BigInt(eligibleAgent.capabilities);

    requireValid(
      required > 0n && (required & available) === required,
      'El agente no reúne las capacidades necesarias'
    );

    return {
      authority: identity.authority,
      owner: identity.owner,
      remaining,
      orderSnapshot: hex(orderInfo.data),
      agentSnapshot: hex(agentInfo.data),
    };
  }

  async function prepare() {
    if (!agent || !mission) return;

    setBusy(true);
    setError('');
    setPrepared(null);
    setSignature('');

    try {
      setStep('Validando identidad y matching...');

      const inspection = await inspect();
      const discriminator = await claimDiscriminator();

      const signer = new PublicKey(inspection.authority);
      const [config] = PublicKey.findProgramAddressSync(
        [encoder.encode('protocol_config')],
        PROGRAM_ID
      );

      const balance = await connection.getBalance(signer, 'confirmed');

      requireValid(
        balance >= 100_000,
        'La autoridad del dispositivo necesita SOL para cubrir la comisión de red'
      );

      const latest = await connection.getLatestBlockhash('confirmed');

      const transaction = new Transaction({
        feePayer: signer,
        recentBlockhash: latest.blockhash,
      }).add(
        new TransactionInstruction({
          programId: PROGRAM_ID,
          keys: [
            { pubkey: config, isSigner: false, isWritable: false },
            {
              pubkey: new PublicKey(mission.work_order_account),
              isSigner: false,
              isWritable: true,
            },
            {
              pubkey: new PublicKey(agent.agent_account),
              isSigner: false,
              isWritable: false,
            },
            { pubkey: signer, isSigner: true, isWritable: false },
          ],
          data: discriminator,
        })
      );

      const unsignedBase64 = transaction
        .serialize({
          requireAllSignatures: false,
          verifySignatures: false,
        })
        .toString('base64');

      setStep('Simulando ClaimWorkOrder...');

      await simulateClaim(unsignedBase64);

      setPrepared({
        ...inspection,
        order: mission.work_order_account,
        agent: agent.agent_account,
        unsignedBase64,
        messageBase64: Buffer.from(transaction.serializeMessage()).toString(
          'base64'
        ),
        blockhash: latest.blockhash,
        lastValidBlockHeight: latest.lastValidBlockHeight,
      });

      setStep(
        'Simulación aprobada. La firma solo se habilita ' +
          'para la autoridad registrada del dispositivo.'
      );
    } catch (cause) {
      setError(describe(cause));
      setStep('Preflight detenido; no se envió ninguna transacción.');
    } finally {
      setBusy(false);
    }
  }

  async function claim() {
    if (!prepared || !agent || !mission) return;

    setBusy(true);
    setError('');

    let mayHaveSent = false;

    try {
      requireValid(
        connected &&
          publicKey?.toBase58() === prepared.authority &&
          typeof signTransaction === 'function',
        'La wallet conectada no es el agent_signer registrado'
      );

      setStep('Revalidando WorkOrder y AgentAccount...');

      const fresh = await inspect();

      requireValid(
        fresh.orderSnapshot === prepared.orderSnapshot &&
          fresh.agentSnapshot === prepared.agentSnapshot &&
          fresh.authority === prepared.authority &&
          prepared.order === mission.work_order_account &&
          prepared.agent === agent.agent_account,
        'Cambió el estado on-chain. Ejecuta otro preflight.'
      );

      const [validHash, height] = await Promise.all([
        connection.isBlockhashValid(prepared.blockhash, {
          commitment: 'confirmed',
        }),
        connection.getBlockHeight('confirmed'),
      ]);

      requireValid(
        validHash.value && height < prepared.lastValidBlockHeight - 8,
        'Blockhash por vencer. Prepara otra transacción.'
      );

      const unsigned = Transaction.from(
        Buffer.from(prepared.unsignedBase64, 'base64')
      );

      requireValid(
        Buffer.from(unsigned.serializeMessage()).toString('base64') ===
          prepared.messageBase64,
        'La transacción difiere de la simulada'
      );

      setStep('Solicitando firma a la autoridad del agente...');

      const signed = await signTransaction!(unsigned);

      requireValid(
        signed instanceof Transaction &&
          Buffer.from(signed.serializeMessage()).toString('base64') ===
            prepared.messageBase64 &&
          signed.verifySignatures(true),
        'Firma inválida o mensaje modificado por la wallet'
      );

      // Recheck after the external wallet prompt as well.
      const afterSignature = await inspect();
      const [stillValid, heightAfterSignature] = await Promise.all([
        connection.isBlockhashValid(prepared.blockhash, {
          commitment: 'confirmed',
        }),
        connection.getBlockHeight('confirmed'),
      ]);
      requireValid(
        afterSignature.orderSnapshot === prepared.orderSnapshot &&
          afterSignature.agentSnapshot === prepared.agentSnapshot &&
          afterSignature.authority === prepared.authority &&
          stillValid.value &&
          heightAfterSignature < prepared.lastValidBlockHeight - 8,
        'El estado o blockhash cambió durante la firma. Prepara otro Claim.'
      );
      setStep(
        c(
          'Broadcasting ClaimWorkOrder to Solana…',
          'Transmitiendo ClaimWorkOrder a Solana…'
        )
      );
      mayHaveSent = true;

      const sig = await connection.sendRawTransaction(signed.serialize(), {
        skipPreflight: false,
        preflightCommitment: 'confirmed',
        maxRetries: 2,
      });

      setSignature(sig);
      setPrepared(null);

      setStep('Esperando confirmación...');

      const confirmation = await connection.confirmTransaction(
        {
          signature: sig,
          blockhash: prepared.blockhash,
          lastValidBlockHeight: prepared.lastValidBlockHeight,
        },
        'confirmed'
      );

      requireValid(
        confirmation.value.err === null,
        'Claim confirmó con error: ' + JSON.stringify(confirmation.value.err)
      );

      const result = await API.getWorkOrder(mission.work_order_account);

      requireValid(
        result.meta.program_id === PROGRAM_ID.toBase58() &&
          result.data.work_order_account === mission.work_order_account &&
          result.data.status === 'Claimed',
        'La transacción confirmó, pero Discovery no devuelve Claimed'
      );

      setStep('✅ ClaimWorkOrder confirmada on-chain.');
      onClaimed();
    } catch (cause) {
      setError(describe(cause));

      setStep(
        mayHaveSent
          ? 'Puede existir una transacción enviada. ' +
              'Comprueba el estado de la orden antes de reintentar.'
          : 'No se transmitió ninguna transacción.'
      );
    } finally {
      setBusy(false);
    }
  }

  const walletAuthorized = Boolean(
    connected && wallet && prepared && wallet === prepared.authority
  );

  return (
    <div className="claim-mission-panel">
      <div className="claim-mission-eyebrow">
        {c('AUTONOMOUS CONTRACTING · SOLANA', 'CONTRATACIÓN AUTÓNOMA · SOLANA')}
      </div>

      <h3>{t('Claim Mission')}</h3>
      <p>
        {t(
          'Valida el agente, simula la reclamación y exige la firma del dispositivo autorizado.'
        )}
      </p>

      <div className="claim-mission-details">
        <span>{t('Wallet conectada')}</span>
        {wallet ? <CopyAddress value={wallet} /> : t('Sin conectar')}

        <span>{t('Agent signer requerido')}</span>
        {prepared ? (
          <CopyAddress value={prepared.authority} />
        ) : (
          t('Pendiente de preflight')
        )}

        <span>{t('Beneficiario económico')}</span>
        {prepared ? (
          <CopyAddress value={prepared.owner} />
        ) : (
          t('Pendiente de preflight')
        )}

        <span>{t('Tiempo restante (chain)')}</span>
        <strong>
          {prepared
            ? t('{seconds} seconds at preparation', {
                seconds: prepared.remaining,
              })
            : '—'}
        </strong>
      </div>

      <button
        className="claim-mission-preview"
        disabled={
          busy ||
          !mission ||
          !agent ||
          mission.status !== 'Open' ||
          !mission.discoverable
        }
        onClick={() => void prepare()}
      >
        {busy ? t('Procesando…') : t('Preflight + Simular Claim')}
      </button>

      {prepared && (
        <button
          className="claim-mission-send"
          disabled={!walletAuthorized || busy || !signTransaction}
          onClick={() => void claim()}
        >
          {t('Autorizar ClaimWorkOrder')}
        </button>
      )}

      {prepared && !walletAuthorized && (
        <p className="claim-mission-warning">
          {t(
            'La wallet actual no corresponde a la autoridad de firma del agente. Puedes inspeccionar y simular, pero no reclamar esta misión con esa wallet.'
          )}
        </p>
      )}

      <p className="claim-mission-step">{t(step)}</p>

      {error && (
        <div role="alert">
          <p>
            {t('Claim no se completó. Revisa el estado antes de reintentar.')}
          </p>
          <details>
            <summary>{t('Diagnóstico de Claim')}</summary>
            <pre>{error}</pre>
          </details>
        </div>
      )}

      {signature && (
        <div className="claim-mission-signature">
          <strong>{t('Transacción enviada')}</strong>
          <CopyAddress label={t('firma')} value={signature} />
        </div>
      )}

      <p className="claim-mission-note">
        {t(
          'El preflight y la simulación no envían transacciones. El botón de autorización sí puede modificar el estado on-chain y requiere una firma externa válida.'
        )}
      </p>
    </div>
  );
}
