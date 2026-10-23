import type {
  AgentCost,
  AgentEconomicSummary,
  AgentReserve,
  AgentSolvencyAssessment,
  EconomicMovement,
  MarketplaceClient,
  PrivateEconomicRequestOptions,
} from '@aerosettle/marketplace-sdk';
import { MarketplaceApiError } from '@aerosettle/marketplace-sdk';
// @ts-expect-error bs58 lacks bundled TypeScript declarations in this workspace
import bs58 from 'bs58';
import { MINT, PROGRAM_ID } from './config.ts';
import { SETTLEMENT_SYMBOL } from './atlas.ts';

export interface EconomicContext {
  agent_account: string;
  network: string;
  genesis_hash: string;
  program_id: string;
  token_mint: string;
}

export interface OwnerSigner {
  publicKey: string;
  signMessage(message: Uint8Array): Promise<Uint8Array>;
}

export interface EconomicSnapshot {
  account: string;
  summaries: AgentEconomicSummary[];
  assessments: AgentSolvencyAssessment[];
  mixedAssetContext: boolean;
  history: AgentSolvencyAssessment[];
  costs: AgentCost[];
  costsHasMore: boolean;
  reserves: AgentReserve[];
  movements: EconomicMovement[];
  movementsHasMore: boolean;
  observedAt: string;
}

const authCache = new Map<string, { expiresAt: number; headers: Record<string, string> }>();
const pendingAuth = new Map<string, Promise<Record<string, string>>>();

function assertActive(signal: AbortSignal): void {
  if (signal.aborted) throw new DOMException('Request cancelled', 'AbortError');
}

export async function ownerAuthHeaders(
  agentAccount: string,
  owner: string,
  signer: OwnerSigner,
  signal: AbortSignal,
): Promise<Record<string, string>> {
  if (signer.publicKey !== owner) throw new Error('FORBIDDEN: connected wallet is not the current agent owner');
  assertActive(signal);
  const key = `${owner}:${agentAccount}`;
  const cached = authCache.get(key);
  if (cached && cached.expiresAt > Date.now()) return { ...cached.headers };
  let pending = pendingAuth.get(key);
  if (!pending) {
    pending = (async () => {
      const timestamp = Math.floor(Date.now() / 1000);
      const challenge = new TextEncoder().encode(`conatus:economic-auth:v1:${timestamp}:${agentAccount}`);
      const signature = await signer.signMessage(challenge);
      const headers = {
        'X-Signer-Pubkey': owner,
        'X-Timestamp': String(timestamp),
        'X-Signature': bs58.encode(signature),
      };
      // Credentials remain only in memory and expire before the API's five minute window.
      authCache.set(key, { expiresAt: (timestamp + 240) * 1000, headers });
      return headers;
    })();
    pendingAuth.set(key, pending);
    void pending.finally(() => pendingAuth.delete(key)).catch(() => undefined);
  }
  const headers = await pending;
  assertActive(signal);
  return { ...headers };
}

export function contextKey(context: EconomicContext): string {
  return [context.agent_account, context.network, context.genesis_hash,
    context.program_id, context.token_mint].join('|');
}

export function sameContext(a: EconomicContext, b: EconomicContext): boolean {
  return contextKey(a) === contextKey(b);
}

function requireContext(row: EconomicContext, account: string): void {
  if (row.agent_account !== account || !row.network || !row.genesis_hash ||
      !row.program_id || !row.token_mint || row.program_id !== PROGRAM_ID.toBase58()) {
    throw new Error('Economic response has an incomplete or incompatible monetary context');
  }
}

export async function loadOwnerEconomy(
  client: MarketplaceClient,
  account: string,
  owner: string,
  signer: OwnerSigner,
  signal: AbortSignal,
): Promise<EconomicSnapshot> {
  const authHeaders = await ownerAuthHeaders(account, owner, signer, signal);
  const options: PrivateEconomicRequestOptions = { authHeaders, signal };
  const [summary, solvency, history, costs, reserves, movements] = await Promise.all([
    client.getAgentEconomicSummary(account, {}, options),
    client.getAgentSolvency(account, { window: 30 }, { authHeaders, signal }),
    client.getAgentSolvencyHistory(account, { limit: 10 }, { authHeaders, signal }),
    client.listAgentCosts(account, { limit: 50 }, options),
    client.listAgentReserves(account, {}, options),
    client.listEconomicMovements(account, { limit: 50 }, options),
  ]).catch((cause: unknown) => {
    if (cause instanceof MarketplaceApiError && (cause.status === 401 || cause.status === 403)) {
      authCache.delete(`${owner}:${account}`);
      throw new Error(`${cause.status} ${cause.code}: ${cause.message}`);
    }
    throw cause;
  });
  assertActive(signal);
  for (const response of [summary, solvency, history, costs, reserves, movements]) {
    if (response.meta.program_id !== PROGRAM_ID.toBase58())
      throw new Error('Economic API program does not match the connected application');
  }
  const assessments = solvency.data.filter((item): item is AgentSolvencyAssessment =>
    item.calculation_status !== 'MIXED_ASSET_CONTEXT');
  for (const row of [...summary.data, ...assessments, ...history.data, ...costs.data,
    ...reserves.data, ...movements.data]) requireContext(row as EconomicContext, account);
  return {
    account,
    summaries: summary.data,
    assessments,
    mixedAssetContext: solvency.data.some((item) => item.calculation_status === 'MIXED_ASSET_CONTEXT'),
    history: history.data,
    costs: costs.data,
    costsHasMore: costs.page.has_more,
    reserves: reserves.data,
    movements: movements.data,
    movementsHasMore: movements.page.has_more,
    observedAt: new Date().toISOString(),
  };
}

export function contextsOf(snapshot: EconomicSnapshot): EconomicContext[] {
  const contexts = new Map<string, EconomicContext>();
  for (const row of [
    ...snapshot.summaries, ...snapshot.assessments, ...snapshot.history,
    ...snapshot.costs, ...snapshot.reserves, ...snapshot.movements,
  ]) {
    const context = row as EconomicContext;
    contexts.set(contextKey(context), context);
  }
  return [...contexts.values()];
}

export function assessmentFor(snapshot: EconomicSnapshot, context: EconomicContext): AgentSolvencyAssessment | undefined {
  return snapshot.assessments.find((item) => sameContext(item, context));
}

export function summaryFor(snapshot: EconomicSnapshot, context: EconomicContext): AgentEconomicSummary | undefined {
  return snapshot.summaries.find((item) => sameContext(item as EconomicContext, context));
}

export function isProductiveAssessment(assessment: AgentSolvencyAssessment): boolean {
  return assessment.calculation_status === 'VALID' &&
    assessment.data_coverage_status === 'COMPLETE' &&
    assessment.exclusion_reasons.length === 0 &&
    (assessment.provenance === 'LIVE_RPC' ||
     assessment.provenance === 'EXTERNAL_ATTESTED' ||
     assessment.provenance === 'LIVE_RPC_AND_EXTERNAL_ATTESTED');
}

export function formatBaseUnits(value: string | null | undefined, mint: string): string {
  if (value == null || !/^-?(0|[1-9][0-9]*)$/.test(value)) return '—';
  if (mint !== MINT.toBase58()) return `${value} base units`;
  return `${formatUnits(value, 6)} ${SETTLEMENT_SYMBOL}`;
}

export function formatUnits(value: string, decimals: number): string {
  if (!/^-?(0|[1-9][0-9]*)$/.test(value) || !Number.isInteger(decimals) || decimals < 0 || decimals > 18) return '—';
  const amount = BigInt(value);
  const sign = amount < 0n ? '-' : '';
  const positive = amount < 0n ? -amount : amount;
  const scale = 10n ** BigInt(decimals);
  const whole = positive / scale;
  const fraction = decimals ? (positive % scale).toString().padStart(decimals, '0').replace(/0+$/, '') : '';
  return `${sign}${whole}${fraction ? `.${fraction}` : ''}`;
}
