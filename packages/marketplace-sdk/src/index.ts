/** EPIC 3.3.4 — read-only SDK. No wallets or transaction methods. */

export type U64String = string;

export interface Agent {
  agent_account: string;
  agent_id: string;
  protocol_config: string;
  capabilities: U64String;
  active: boolean;
  status: string;
  [field: string]: unknown;
}

export interface WorkOrder {
  work_order_account: string;
  protocol_config: string;
  required_capabilities: U64String;
  execution_deadline: number;
  status: string;
  is_open: boolean;
  discoverable: boolean;
  [field: string]: unknown;
}

export interface ApiMeta {
  program_id: string;
  commitment: string;
  chain_now_unix: number;
  atomic_snapshot: boolean;
  read_only: true;
  matching_engine: 'rust-epic-3.1';
  rpc_context_slots: Record<string, unknown>;
}

export interface PageInfo {
  limit: number;
  has_more: boolean;
  next_cursor: string | null;
}

export interface Page<T> {
  data: T[];
  count: number;
  total_count: number;
  page: PageInfo;
  meta: ApiMeta;
}

export interface Detail<T> {
  data: T;
  meta: ApiMeta;
}

export interface Rejection {
  code: string;
  missing_mask?: U64String;
}

export interface MatchEvaluation {
  agent_account: string;
  eligible: boolean;
  rejection: Rejection | null;
}

export interface MatchResult {
  work_order: WorkOrder;
  eligible_agents: Agent[];
  evaluations: MatchEvaluation[];
}

export interface MarketplaceView {
  protocol_config: string;
  paused: boolean;
  agents: Agent[];
  work_orders: WorkOrder[];
  eligible_agents_by_order: Record<string, string[]>;
}

export interface Health {
  status: 'ok';
  service: string;
  genesis: string;
}

export type AgentStatus =
  | 'Active'
  | 'OwnerSuspended'
  | 'AdminSuspended'
  | 'Revoked';

export type OrderStatus =
  | 'Draft'
  | 'Open'
  | 'Claimed'
  | 'Submitted'
  | 'Verified'
  | 'Settled';

export type MovementNature =
  | 'INCOME'
  | 'EXPENSE'
  | 'RESERVE'
  | 'ADJUSTMENT'
  | 'PROVISION'
  | 'INTERNAL_TRANSFER'
  | 'CAPITAL_INVESTMENT';

export type CostCategory =
  | 'ENERGY_FUEL'
  | 'MAINTENANCE'
  | 'CONNECTIVITY_COMPUTE'
  | 'SUBSCRIPTIONS'
  | 'INSURANCE'
  | 'DEPRECIATION_REPLACEMENT'
  | 'OTHER';

export type CostNature =
  | 'REALIZED'
  | 'ESTIMATED'
  | 'ACCRUED_LIABILITY';

export type ReserveType =
  | 'MAINTENANCE'
  | 'HARDWARE_REPLACEMENT'
  | 'OPERATIONAL_CONTINUITY'
  | 'CONTINGENCY';

export type ReserveStatus =
  | 'ACTIVE'
  | 'DEPLETED'
  | 'CLOSED'
  | 'PENDING_RESOLUTION';

export type ReserveAction =
  | 'ALLOCATE'
  | 'CONSUME'
  | 'RELEASE';

export type MovementStatus =
  | 'PROVISIONAL'
  | 'RECONCILED'
  | 'REVERTED';

export type ProvenanceSource =
  | 'ONCHAIN_VERIFIED'
  | 'EXTERNAL_VERIFIED'
  | 'SIMULATED'
  | 'MANUAL_ENTRY'
  | 'SETTLEMENT_EVENT';

export interface EconomicMovement {
  movement_id: string;
  journal_entry_id?: string | null;
  idempotency_key: string;
  agent_id: string;
  agent_account: string;
  owner_pubkey: string;
  work_order_account?: string | null;
  work_order_id?: string | null;
  network: string;
  genesis_hash: string;
  program_id: string;
  token_mint: string;
  amount_base_units: number;
  amount_str: string;
  nature: MovementNature;
  status: MovementStatus;
  provenance_source: ProvenanceSource;
  evidence_hash?: string | null;
  attestation_id?: string | null;
  tx_signature?: string | null;
  external_ref?: string | null;
  registered_at: number;
  observed_at: number;
  reversal_of_movement_id?: string | null;
  metadata: Record<string, unknown>;
}

export interface BalanceReport {
  agent_account: string;
  network: string;
  genesis_hash?: string;
  program_id?: string;
  token_mint: string;
  reconciled_balance: number;
  provisional_balance: number;
  reserved_balance: number;
  reconciled_balance_str: string;
  provisional_balance_str: string;
  reserved_balance_str: string;
  total_effective_balance: number;
  total_effective_balance_str: string;
  movement_count: number;
}

export interface AgentCost {
  cost_id: string;
  idempotency_key: string;
  agent_id: string;
  agent_account: string;
  owner_pubkey: string;
  category: CostCategory;
  cost_nature: CostNature;
  economic_period: string;
  network: string;
  genesis_hash?: string;
  program_id?: string;
  token_mint: string;
  amount_base_units: number;
  amount_str: string;
  status: MovementStatus;
  provenance_source: ProvenanceSource;
  created_at: number;
  incurred_at: number;
  journal_entry_id?: string | null;
  movement_id?: string | null;
  evidence_hash?: string | null;
  evidence_url?: string | null;
  attestation_id?: string | null;
  description?: string | null;
  reversal_of_cost_id?: string | null;
  metadata: Record<string, unknown>;
}

export interface AgentReserve {
  reserve_id: string;
  idempotency_key: string;
  agent_id: string;
  agent_account: string;
  owner_pubkey: string;
  reserve_type: ReserveType;
  network: string;
  genesis_hash?: string;
  program_id?: string;
  token_mint: string;
  target_amount_base_units: number;
  target_amount_str: string;
  current_reserved_base_units: number;
  current_reserved_str: string;
  status: ReserveStatus;
  created_at: number;
  updated_at: number;
  description?: string | null;
  metadata: Record<string, unknown>;
}

export interface ReserveTransaction {
  transaction_id: string;
  reserve_id: string;
  idempotency_key: string;
  action: ReserveAction;
  amount_base_units: number;
  amount_str: string;
  created_at: number;
  associated_cost_id?: string | null;
  journal_entry_id?: string | null;
  movement_id?: string | null;
  metadata: Record<string, unknown>;
}

export interface AgentEconomicSummary {
  agent_account: string;
  network: string;
  genesis_hash?: string;
  program_id?: string;
  token_mint: string;
  total_income_reconciled: number;
  total_income_provisional: number;
  total_expenses_realized: number;
  total_obligations_accrued: number;
  total_estimated_costs: number;
  total_capital_reserved: number;
  available_balance: number;
  total_effective_balance: number;
  total_income_reconciled_str: string;
  total_income_provisional_str: string;
  total_expenses_realized_str: string;
  total_obligations_accrued_str: string;
  total_estimated_costs_str: string;
  total_capital_reserved_str: string;
  available_balance_str: string;
  total_effective_balance_str: string;
  costs_by_category: Record<string, number>;
  reserves_by_type: Record<string, number>;
}

export interface CostFilters extends Paging {
  category?: CostCategory;
  cost_nature?: CostNature;
  period?: string;
  status?: MovementStatus;
  mint?: string;
  network?: string;
  genesis?: string;
  program_id?: string;
  provenance_source?: ProvenanceSource;
  fromTs?: number;
  toTs?: number;
}

export interface ReserveFilters {
  reserve_type?: ReserveType;
  status?: ReserveStatus;
  mint?: string;
  network?: string;
  genesis?: string;
  program_id?: string;
}

export interface EconomicSummaryFilters {
  mint?: string;
  network?: string;
  genesis?: string;
  program_id?: string;
  period?: string;
}

export type SolvencyCalculationStatus = 'VALID' | 'INSUFFICIENT_DATA' | 'UNDEFINED_RATIO' | 'STALE_DATA' | 'MIXED_ASSET_CONTEXT' | 'ERROR';
export type SustainabilityClass = 'AT_RISK' | 'STABLE' | 'THRIVING' | 'UNDETERMINED';
export interface SolvencyEvidenceReference { kind: string; id: string; evidence_hash: string }
export interface AgentSolvencyAssessment {
  assessment_id: string;
  agent_account: string;
  network: string;
  genesis_hash: string;
  program_id: string;
  token_mint: string;
  window_start: number;
  window_end: number;
  calculated_at: number;
  methodology_version: string;
  threshold_config_version: string;
  conatus_ratio: string | null;
  operating_margin: string | null;
  operating_surplus_base_units_str: string | null;
  available_liquidity_base_units_str: string | null;
  total_reserved_base_units_str: string | null;
  accrued_liabilities_base_units_str: string | null;
  reserve_target_base_units_str: string | null;
  reserve_gap_base_units_str: string | null;
  eligible_liquid_capital_base_units_str: string | null;
  runway_days: string | null;
  sustainability_class: SustainabilityClass;
  calculation_status: SolvencyCalculationStatus;
  data_coverage_status: string;
  input_revenue_count: number;
  input_expense_count: number;
  verified_revenue_base_units_str: string;
  verified_opex_base_units_str: string;
  exclusion_reasons: string[];
  evidence_references: SolvencyEvidenceReference[];
  input_hash: string;
  provenance: string;
  net_worth_verified_base_units_str: string | null;
  provisional_book_value_base_units_str: string | null;
}
export interface MixedAssetContext {
  calculation_status: 'MIXED_ASSET_CONTEXT';
  sustainability_class: 'UNDETERMINED';
  conatus_ratio: null;
  window_start: number;
  window_end: number;
  contexts: Array<{ network: string; genesis_hash: string; program_id: string; token_mint: string }>;
}
export interface SolvencyMethodology {
  methodology_version: string;
  threshold_config_version: string;
  thresholds: { stable: string; thriving: string };
  window_semantics: string;
  revenue_timestamp: string;
  opex_timestamp: string;
  zero_coverage: string;
  ratio: string;
  runway: string;
  precision: string;
  freshness_seconds: number;
  exclusions: string[];
}
export interface SolvencyFilters {
  mint?: string; network?: string; genesis?: string; program_id?: string;
  window?: 7 | 30 | 90; fromTs?: number; toTs?: number; consolidated?: boolean;
}

export interface EconomicMovementFilters extends Paging {
  nature?: MovementNature;
  status?: MovementStatus;
  mint?: string;
  network?: string;
  fromTs?: number;
  toTs?: number;
}

export interface RecordMovementInput {
  idempotency_key: string;
  agent_account: string;
  token_mint: string;
  amount_base_units: number | string;
  nature: MovementNature;
  status?: MovementStatus;
  provenance_source?: ProvenanceSource;
  work_order_account?: string;
  work_order_id?: string;
  evidence_hash?: string;
  attestation_id?: string;
  tx_signature?: string;
  external_ref?: string;
  observed_at?: number;
  metadata?: Record<string, unknown>;
}

export type U64Input = string | bigint;

export interface Paging {
  limit?: number;
  cursor?: string;
}

export interface AgentFilters extends Paging {
  status?: AgentStatus;
  active?: boolean;
  capabilitiesAll?: U64Input;
}

export interface OrderFilters extends Paging {
  status?: OrderStatus;
  discoverable?: boolean;
  requiredCapabilitiesAll?: U64Input;
}

export interface ClientOptions {
  baseUrl?: string;
  fetchImpl?: typeof fetch;
  timeoutMs?: number;
}

export class MarketplaceApiError extends Error {
  readonly status: number;
  readonly code: string;

  constructor(status: number, code: string, message: string) {
    super(message);
    this.name = 'MarketplaceApiError';
    this.status = status;
    this.code = code;
  }
}

export class MarketplaceContractError extends Error {
  constructor(message: string) {
    super(message);
    this.name = 'MarketplaceContractError';
  }
}

const isObj = (value: unknown): value is Record<string, unknown> =>
  typeof value === 'object' &&
  value !== null &&
  !Array.isArray(value);

const fail = (description: string): never => {
  throw new MarketplaceContractError(description);
};

const nonempty = (value: unknown, name: string): string =>
  typeof value === 'string' && value.length > 0
    ? value
    : fail(`Invalid ${name}`);

const boolean = (value: unknown, name: string): boolean =>
  typeof value === 'boolean'
    ? value
    : fail(`Invalid ${name}`);

const integer = (value: unknown, name: string): number =>
  typeof value === 'number' && Number.isSafeInteger(value)
    ? value
    : fail(`Invalid ${name}`);

const u64 = (value: unknown, name: string): U64String => {
  const s = nonempty(value, name);

  if (
    !/^(0|[1-9][0-9]*)$/.test(s) ||
    BigInt(s) > 18446744073709551615n
  ) {
    fail(`Invalid ${name}`);
  }

  return s;
};

const object = (
  value: unknown,
  name: string
): Record<string, unknown> =>
  isObj(value) ? value : fail(`Invalid ${name}`);

const array = (value: unknown, name: string): unknown[] =>
  Array.isArray(value)
    ? value
    : fail(`Invalid ${name}`);

function agent(raw: unknown): Agent {
  const a = object(raw, 'agent');

  nonempty(a.agent_account, 'agent_account');
  nonempty(a.agent_id, 'agent_id');
  nonempty(a.protocol_config, 'protocol_config');
  u64(a.capabilities, 'capabilities');
  boolean(a.active, 'active');
  nonempty(a.status, 'agent status');

  return a as unknown as Agent;
}

function order(raw: unknown): WorkOrder {
  const o = object(raw, 'work order');

  nonempty(o.work_order_account, 'work_order_account');
  nonempty(o.protocol_config, 'protocol_config');
  u64(o.required_capabilities, 'required_capabilities');
  integer(o.execution_deadline, 'execution_deadline');
  nonempty(o.status, 'order status');
  boolean(o.is_open, 'is_open');
  boolean(o.discoverable, 'discoverable');

  return o as unknown as WorkOrder;
}

function economicMovement(raw: unknown): EconomicMovement {
  const m = object(raw, 'economic movement');

  nonempty(m.movement_id, 'movement_id');
  nonempty(m.idempotency_key, 'idempotency_key');
  nonempty(m.agent_id, 'agent_id');
  nonempty(m.agent_account, 'agent_account');
  nonempty(m.network, 'network');
  nonempty(m.genesis_hash, 'genesis_hash');
  nonempty(m.program_id, 'program_id');
  nonempty(m.token_mint, 'token_mint');
  integer(m.amount_base_units, 'amount_base_units');
  nonempty(m.amount_str, 'amount_str');
  nonempty(m.nature, 'nature');
  nonempty(m.status, 'status');
  nonempty(m.provenance_source, 'provenance_source');
  integer(m.registered_at, 'registered_at');
  integer(m.observed_at, 'observed_at');

  return m as unknown as EconomicMovement;
}

function balanceReport(raw: unknown): BalanceReport {
  const b = object(raw, 'balance report');

  nonempty(b.agent_account, 'agent_account');
  nonempty(b.network, 'network');
  nonempty(b.token_mint, 'token_mint');
  integer(b.reconciled_balance, 'reconciled_balance');
  integer(b.provisional_balance, 'provisional_balance');
  integer(b.reserved_balance, 'reserved_balance');
  nonempty(b.reconciled_balance_str, 'reconciled_balance_str');
  nonempty(b.provisional_balance_str, 'provisional_balance_str');
  nonempty(b.reserved_balance_str, 'reserved_balance_str');
  integer(b.total_effective_balance, 'total_effective_balance');
  nonempty(b.total_effective_balance_str, 'total_effective_balance_str');
  integer(b.movement_count, 'movement_count');

  return b as unknown as BalanceReport;
}

function agentCost(raw: unknown): AgentCost {
  const c = object(raw, 'agent cost');
  nonempty(c.cost_id, 'cost_id');
  nonempty(c.idempotency_key, 'idempotency_key');
  nonempty(c.agent_id, 'agent_id');
  nonempty(c.agent_account, 'agent_account');
  nonempty(c.category, 'category');
  nonempty(c.cost_nature, 'cost_nature');
  nonempty(c.economic_period, 'economic_period');
  nonempty(c.network, 'network');
  nonempty(c.token_mint, 'token_mint');
  integer(c.amount_base_units, 'amount_base_units');
  nonempty(c.amount_str, 'amount_str');
  nonempty(c.status, 'status');
  nonempty(c.provenance_source, 'provenance_source');
  integer(c.created_at, 'created_at');
  integer(c.incurred_at, 'incurred_at');
  return c as unknown as AgentCost;
}

function agentReserve(raw: unknown): AgentReserve {
  const r = object(raw, 'agent reserve');
  nonempty(r.reserve_id, 'reserve_id');
  nonempty(r.idempotency_key, 'idempotency_key');
  nonempty(r.agent_id, 'agent_id');
  nonempty(r.agent_account, 'agent_account');
  nonempty(r.reserve_type, 'reserve_type');
  nonempty(r.network, 'network');
  nonempty(r.token_mint, 'token_mint');
  integer(r.target_amount_base_units, 'target_amount_base_units');
  integer(r.current_reserved_base_units, 'current_reserved_base_units');
  nonempty(r.status, 'status');
  integer(r.created_at, 'created_at');
  integer(r.updated_at, 'updated_at');
  return r as unknown as AgentReserve;
}

function agentEconomicSummary(raw: unknown): AgentEconomicSummary {
  const s = object(raw, 'economic summary');
  nonempty(s.agent_account, 'agent_account');
  nonempty(s.network, 'network');
  nonempty(s.token_mint, 'token_mint');
  integer(s.total_income_reconciled, 'total_income_reconciled');
  integer(s.total_income_provisional, 'total_income_provisional');
  integer(s.total_expenses_realized, 'total_expenses_realized');
  integer(s.total_obligations_accrued, 'total_obligations_accrued');
  integer(s.total_estimated_costs, 'total_estimated_costs');
  integer(s.total_capital_reserved, 'total_capital_reserved');
  integer(s.available_balance, 'available_balance');
  integer(s.total_effective_balance, 'total_effective_balance');
  return s as unknown as AgentEconomicSummary;
}

function solvencyAssessment(raw: unknown): AgentSolvencyAssessment | MixedAssetContext {
  const a = object(raw, 'solvency assessment');
  const status = nonempty(a.calculation_status, 'calculation_status');
  if (!['VALID', 'INSUFFICIENT_DATA', 'UNDEFINED_RATIO', 'STALE_DATA', 'MIXED_ASSET_CONTEXT', 'ERROR'].includes(status)) fail('Invalid solvency status');
  if (status === 'MIXED_ASSET_CONTEXT') {
    array(a.contexts, 'contexts');
    return a as unknown as MixedAssetContext;
  }
  for (const key of ['assessment_id', 'agent_account', 'network', 'genesis_hash', 'program_id', 'token_mint', 'methodology_version', 'threshold_config_version', 'input_hash', 'provenance']) nonempty(a[key], key);
  for (const key of ['window_start', 'window_end', 'calculated_at', 'input_revenue_count', 'input_expense_count']) integer(a[key], key);
  for (const key of ['verified_revenue_base_units_str', 'verified_opex_base_units_str']) u64(a[key], key);
  for (const key of ['reserve_target_base_units_str', 'reserve_gap_base_units_str']) if (a[key] !== null) u64(a[key], key);
  for (const key of ['operating_surplus_base_units_str', 'available_liquidity_base_units_str', 'total_reserved_base_units_str', 'accrued_liabilities_base_units_str', 'eligible_liquid_capital_base_units_str', 'net_worth_verified_base_units_str', 'provisional_book_value_base_units_str']) {
    if (a[key] !== null && (typeof a[key] !== 'string' || !/^-?(0|[1-9][0-9]*)$/.test(a[key] as string))) fail(`Invalid ${key}`);
  }
  for (const key of ['conatus_ratio', 'operating_margin', 'runway_days']) {
    if (a[key] !== null && (typeof a[key] !== 'string' || !/^-?(0|[1-9][0-9]*)(\.[0-9]+)?$/.test(a[key] as string))) fail(`Invalid ${key}`);
  }
  if (!['AT_RISK', 'STABLE', 'THRIVING', 'UNDETERMINED'].includes(nonempty(a.sustainability_class, 'sustainability_class'))) fail('Invalid sustainability class');
  array(a.exclusion_reasons, 'exclusion_reasons');
  array(a.evidence_references, 'evidence_references').forEach((rawRef) => {
    const ref = object(rawRef, 'evidence reference');
    nonempty(ref.kind, 'evidence kind'); nonempty(ref.id, 'evidence id'); nonempty(ref.evidence_hash, 'evidence hash');
  });
  return a as unknown as AgentSolvencyAssessment;
}

function meta(raw: unknown): ApiMeta {
  const m = object(raw, 'metadata');

  nonempty(m.program_id, 'program_id');
  nonempty(m.commitment, 'commitment');
  integer(m.chain_now_unix, 'chain_now_unix');
  boolean(m.atomic_snapshot, 'atomic_snapshot');

  if (
    m.read_only !== true ||
    m.matching_engine !== 'rust-epic-3.1'
  ) {
    fail('Unexpected matching authority');
  }

  object(m.rpc_context_slots, 'rpc_context_slots');

  return m as unknown as ApiMeta;
}

function detail<T>(
  raw: unknown,
  parser: (raw: unknown) => T
): Detail<T> {
  const r = object(raw, 'detail response');

  return {
    data: parser(r.data),
    meta: meta(r.meta),
  };
}

function page<T>(
  raw: unknown,
  parser: (raw: unknown) => T
): Page<T> {
  const r = object(raw, 'page response');
  const rows = array(r.data, 'data').map(parser);
  const pagination = object(r.page, 'page');

  const count = integer(r.count, 'count');
  const totalCount = integer(r.total_count, 'total_count');
  const limit = integer(pagination.limit, 'limit');
  const hasMore = boolean(pagination.has_more, 'has_more');
  const next = pagination.next_cursor;

  if (
    count !== rows.length ||
    count < 0 ||
    totalCount < count ||
    limit < 1 ||
    limit > 100 ||
    !(
      next === null ||
      (typeof next === 'string' && next.length > 0)
    ) ||
    hasMore !== (typeof next === 'string') ||
    (hasMore && !rows.length)
  ) {
    fail('Invalid pagination contract');
  }

  return {
    data: rows,
    count,
    total_count: totalCount,
    page: {
      limit,
      has_more: hasMore,
      next_cursor: next as string | null,
    },
    meta: meta(r.meta),
  };
}

function pubkey(value: string): string {
  if (!/^[1-9A-HJ-NP-Za-km-z]{32,44}$/.test(value)) {
    throw new RangeError('Invalid Solana pubkey');
  }

  return value;
}

function mask(value: U64Input): string {
  if (typeof value === 'bigint') {
    if (value < 0n || value > 18446744073709551615n) {
      throw new RangeError('Mask out of u64 range');
    }

    return value.toString();
  }

  if (
    typeof value !== 'string' ||
    !/^(0|[1-9][0-9]*)$/.test(value) ||
    BigInt(value) > 18446744073709551615n
  ) {
    throw new RangeError('Invalid u64 mask');
  }

  return value;
}

function queryParam(
  params: URLSearchParams,
  name: string,
  value: string | number | boolean | undefined
) {
  if (value !== undefined) {
    params.set(name, String(value));
  }
}

function paging(params: URLSearchParams, filters: Paging) {
  if (filters.limit !== undefined) {
    if (
      !Number.isInteger(filters.limit) ||
      filters.limit < 1 ||
      filters.limit > 100
    ) {
      throw new RangeError('limit must be 1..100');
    }

    params.set('limit', String(filters.limit));
  }

  if (filters.cursor !== undefined) {
    if (!filters.cursor || filters.cursor.length > 2048) {
      throw new RangeError('Invalid cursor');
    }

    params.set('cursor', filters.cursor);
  }
}

export class MarketplaceClient {
  private readonly baseUrl: string;
  private readonly fetcher: typeof fetch;
  private readonly timeoutMs: number;

  constructor(options: ClientOptions = {}) {
    const parsed = new URL(
      options.baseUrl ?? 'http://127.0.0.1:8787'
    );

    if (
      !['http:', 'https:'].includes(parsed.protocol) ||
      parsed.username ||
      parsed.password ||
      parsed.pathname !== '/' ||
      parsed.search ||
      parsed.hash
    ) {
      throw new TypeError('Expected API origin URL');
    }

    if (
      parsed.protocol === 'http:' &&
      !['127.0.0.1', 'localhost', '[::1]'].includes(
        parsed.hostname
      )
    ) {
      throw new TypeError('Remote API requires HTTPS');
    }

    this.baseUrl = parsed.origin;
    this.fetcher = options.fetchImpl ?? globalThis.fetch.bind(globalThis);
    this.timeoutMs = options.timeoutMs ?? 10000;

    if (
      !Number.isSafeInteger(this.timeoutMs) ||
      this.timeoutMs < 1 ||
      this.timeoutMs > 120000
    ) {
      throw new RangeError('timeoutMs must be 1..120000');
    }
  }

  private async exec(
    method: 'GET' | 'POST',
    path: string,
    params?: URLSearchParams,
    bodyData?: unknown,
    signal?: AbortSignal,
    extraHeaders?: Record<string, string>
  ): Promise<unknown> {
    const url = new URL(path, this.baseUrl);

    if (params) {
      url.search = params.toString();
    }

    const controller = new AbortController();

    const onAbort = () =>
      controller.abort(signal?.reason);

    if (signal?.aborted) {
      onAbort();
    } else {
      signal?.addEventListener(
        'abort',
        onAbort,
        { once: true }
      );
    }

    const timer = setTimeout(
      () => controller.abort(new Error('API request timeout')),
      this.timeoutMs
    );

    const headers: Record<string, string> = { ...extraHeaders };
    let body: string | undefined;
    if (bodyData !== undefined) {
      headers['Content-Type'] = 'application/json';
      body = JSON.stringify(bodyData);
    }

    try {
      const response = await this.fetcher(url, {
        method,
        headers,
        body,
        signal: controller.signal,
        redirect: 'error',
      });

      const declaredLength = Number(
        response.headers.get('content-length') ?? '0'
      );

      if (declaredLength > 2_000_000) {
        fail('Response body too large');
      }

      const rawText = await response.text();

      if (rawText.length > 2_000_000) {
        fail('Response body too large');
      }

      let data: unknown;

      try {
        data = JSON.parse(rawText) as unknown;
      } catch {
        return fail('Response was not valid JSON');
      }

      if (!response.ok) {
        const error =
          isObj(data) && isObj(data.error)
            ? data.error
            : {};

        throw new MarketplaceApiError(
          response.status,
          typeof error.code === 'string'
            ? error.code
            : 'HTTP_ERROR',
          typeof error.message === 'string'
            ? error.message
            : `HTTP ${response.status}`
        );
      }

      return data;
    } finally {
      clearTimeout(timer);
      signal?.removeEventListener('abort', onAbort);
    }
  }

  private async get(
    path: string,
    params?: URLSearchParams,
    signal?: AbortSignal,
    headers?: Record<string, string>
  ): Promise<unknown> {
    return this.exec('GET', path, params, undefined, signal, headers);
  }

  private async post(
    path: string,
    bodyData: unknown,
    signal?: AbortSignal,
    headers?: Record<string, string>
  ): Promise<unknown> {
    return this.exec('POST', path, undefined, bodyData, signal, headers);
  }

  async health(signal?: AbortSignal): Promise<Health> {
    const value = object(
      await this.get('/health', undefined, signal),
      'health'
    );

    if (value.status !== 'ok') {
      fail('Unexpected health status');
    }

    return {
      status: 'ok',
      service: nonempty(value.service, 'service'),
      genesis: nonempty(value.genesis, 'genesis'),
    };
  }

  async getOpenApi(
    signal?: AbortSignal
  ): Promise<Record<string, unknown>> {
    const spec = object(
      await this.get('/openapi.json', undefined, signal),
      'OpenAPI'
    );

    if (spec.openapi !== '3.1.1') {
      fail('Unsupported OpenAPI version');
    }

    object(spec.paths, 'OpenAPI paths');

    return spec;
  }

  async listAgents(
    filters: AgentFilters = {},
    signal?: AbortSignal
  ): Promise<Page<Agent>> {
    const p = new URLSearchParams();

    queryParam(p, 'status', filters.status);
    queryParam(p, 'active', filters.active);

    if (filters.capabilitiesAll !== undefined) {
      p.set(
        'capabilities_all',
        mask(filters.capabilitiesAll)
      );
    }

    paging(p, filters);

    return page(
      await this.get('/v1/agents', p, signal),
      agent
    );
  }

  async listWorkOrders(
    filters: OrderFilters = {},
    signal?: AbortSignal
  ): Promise<Page<WorkOrder>> {
    const p = new URLSearchParams();

    queryParam(p, 'status', filters.status);
    queryParam(p, 'discoverable', filters.discoverable);

    if (
      filters.requiredCapabilitiesAll !== undefined
    ) {
      p.set(
        'required_capabilities_all',
        mask(filters.requiredCapabilitiesAll)
      );
    }

    paging(p, filters);

    return page(
      await this.get('/v1/work-orders', p, signal),
      order
    );
  }

  async getAgent(
    account: string,
    signal?: AbortSignal
  ): Promise<Detail<Agent>> {
    return detail(
      await this.get(
        `/v1/agents/${pubkey(account)}`,
        undefined,
        signal
      ),
      agent
    );
  }

  async getWorkOrder(
    account: string,
    signal?: AbortSignal
  ): Promise<Detail<WorkOrder>> {
    return detail(
      await this.get(
        `/v1/work-orders/${pubkey(account)}`,
        undefined,
        signal
      ),
      order
    );
  }

  async getMatches(
    account: string,
    signal?: AbortSignal
  ): Promise<Detail<MatchResult>> {
    return detail(
      await this.get(
        `/v1/work-orders/${pubkey(account)}/matches`,
        undefined,
        signal
      ),
      raw => {
        const result = object(raw, 'match result');

        const evaluations = array(
          result.evaluations,
          'evaluations'
        ).map(item => {
          const entry = object(item, 'evaluation');

          const reason =
            entry.rejection === null
              ? null
              : object(entry.rejection, 'rejection');

          if (reason) {
            nonempty(reason.code, 'rejection code');

            if (reason.missing_mask !== undefined) {
              u64(reason.missing_mask, 'missing_mask');
            }
          }

          return {
            agent_account: nonempty(
              entry.agent_account,
              'agent_account'
            ),
            eligible: boolean(entry.eligible, 'eligible'),
            rejection: reason as Rejection | null,
          };
        });

        if (
          evaluations.some(
            e => e.eligible !== (e.rejection === null)
          )
        ) {
          fail('Invalid matching decision');
        }

        return {
          work_order: order(result.work_order),
          eligible_agents: array(
            result.eligible_agents,
            'eligible_agents'
          ).map(agent),
          evaluations,
        };
      }
    );
  }

  async getMarketplace(
    signal?: AbortSignal
  ): Promise<Detail<MarketplaceView>> {
    return detail(
      await this.get('/v1/marketplace', undefined, signal),
      raw => {
        const data = object(raw, 'marketplace');

        const mapping = object(
          data.eligible_agents_by_order,
          'eligible_agents_by_order'
        );

        const eligible: Record<string, string[]> = {};

        for (const [key, value] of Object.entries(mapping)) {
          eligible[key] = array(
            value,
            'eligible account list'
          ).map(item => nonempty(item, 'agent account'));
        }

        return {
          protocol_config: nonempty(
            data.protocol_config,
            'protocol_config'
          ),
          paused: boolean(data.paused, 'paused'),
          agents: array(data.agents, 'agents').map(agent),
          work_orders: array(
            data.work_orders,
            'work_orders'
          ).map(order),
          eligible_agents_by_order: eligible,
        };
      }
    );
  }

  async listEconomicMovements(
    account: string,
    filters: EconomicMovementFilters = {},
    options: { ownerPubkey?: string; signal?: AbortSignal } = {}
  ): Promise<Page<EconomicMovement>> {
    const p = new URLSearchParams();
    if (filters.nature) p.set('nature', filters.nature);
    if (filters.status) p.set('status', filters.status);
    if (filters.mint) p.set('mint', filters.mint);
    if (filters.network) p.set('network', filters.network);
    if (filters.fromTs !== undefined) p.set('from_ts', String(filters.fromTs));
    if (filters.toTs !== undefined) p.set('to_ts', String(filters.toTs));
    paging(p, filters);

    const headers: Record<string, string> = {};
    if (options.ownerPubkey) {
      headers['X-Owner-Pubkey'] = options.ownerPubkey;
    }

    return page(
      await this.get(
        `/v1/agents/${pubkey(account)}/economic-movements`,
        p,
        options.signal,
        headers
      ),
      economicMovement
    );
  }

  async getAgentBalances(
    account: string,
    filters: { mint?: string; network?: string; genesis?: string; program_id?: string } = {},
    options: { ownerPubkey?: string; signal?: AbortSignal } = {}
  ): Promise<Detail<BalanceReport[]>> {
    const p = new URLSearchParams();
    if (filters.mint) p.set('mint', filters.mint);
    if (filters.network) p.set('network', filters.network);
    if (filters.genesis) p.set('genesis', filters.genesis);
    if (filters.program_id) p.set('program_id', filters.program_id);

    const headers: Record<string, string> = {};
    if (options.ownerPubkey) {
      headers['X-Owner-Pubkey'] = options.ownerPubkey;
    }

    return detail(
      await this.get(
        `/v1/agents/${pubkey(account)}/balances`,
        p,
        options.signal,
        headers
      ),
      raw => array(raw, 'balance reports').map(balanceReport)
    );
  }

  async getEconomicMovement(
    movementId: string,
    options: { ownerPubkey?: string; signal?: AbortSignal } = {}
  ): Promise<Detail<EconomicMovement>> {
    const headers: Record<string, string> = {};
    if (options.ownerPubkey) {
      headers['X-Owner-Pubkey'] = options.ownerPubkey;
    }

    return detail(
      await this.get(
        `/v1/economic-movements/${encodeURIComponent(movementId)}`,
        undefined,
        options.signal,
        headers
      ),
      economicMovement
    );
  }

  async recordEconomicMovement(
    movement: RecordMovementInput,
    options: { ownerPubkey?: string; signal?: AbortSignal } = {}
  ): Promise<Detail<EconomicMovement>> {
    const headers: Record<string, string> = {};
    if (options.ownerPubkey) {
      headers['X-Owner-Pubkey'] = options.ownerPubkey;
    }

    return detail(
      await this.post(
        '/v1/economic-movements',
        movement,
        options.signal,
        headers
      ),
      economicMovement
    );
  }

  async revertEconomicMovement(
    movementId: string,
    reason: string,
    options: { ownerPubkey?: string; signal?: AbortSignal } = {}
  ): Promise<Detail<{ reverted: EconomicMovement; compensating: EconomicMovement }>> {
    const headers: Record<string, string> = {};
    if (options.ownerPubkey) {
      headers['X-Owner-Pubkey'] = options.ownerPubkey;
    }

    return detail(
      await this.post(
        `/v1/economic-movements/${encodeURIComponent(movementId)}/revert`,
        { reason },
        options.signal,
        headers
      ),
      raw => {
        const obj = object(raw, 'revert response');
        return {
          reverted: economicMovement(obj.reverted),
          compensating: economicMovement(obj.compensating),
        };
      }
    );
  }

  async listAgentCosts(
    account: string,
    filters: CostFilters = {},
    options: { ownerPubkey?: string; signal?: AbortSignal } = {}
  ): Promise<Page<AgentCost>> {
    const p = new URLSearchParams();
    if (filters.category) p.set('category', filters.category);
    if (filters.cost_nature) p.set('cost_nature', filters.cost_nature);
    if (filters.period) p.set('period', filters.period);
    if (filters.status) p.set('status', filters.status);
    if (filters.mint) p.set('mint', filters.mint);
    if (filters.network) p.set('network', filters.network);
    if (filters.genesis) p.set('genesis', filters.genesis);
    if (filters.program_id) p.set('program_id', filters.program_id);
    if (filters.provenance_source) p.set('provenance_source', filters.provenance_source);
    if (filters.fromTs !== undefined) p.set('from_ts', String(filters.fromTs));
    if (filters.toTs !== undefined) p.set('to_ts', String(filters.toTs));
    paging(p, filters);

    const headers: Record<string, string> = {};
    if (options.ownerPubkey) {
      headers['X-Owner-Pubkey'] = options.ownerPubkey;
    }

    return page(
      await this.get(
        `/v1/agents/${pubkey(account)}/costs`,
        p,
        options.signal,
        headers
      ),
      agentCost
    );
  }

  async getCost(
    costId: string,
    options: { ownerPubkey?: string; signal?: AbortSignal } = {}
  ): Promise<Detail<AgentCost>> {
    const headers: Record<string, string> = {};
    if (options.ownerPubkey) {
      headers['X-Owner-Pubkey'] = options.ownerPubkey;
    }

    return detail(
      await this.get(
        `/v1/costs/${encodeURIComponent(costId)}`,
        undefined,
        options.signal,
        headers
      ),
      agentCost
    );
  }

  async listAgentReserves(
    account: string,
    filters: ReserveFilters = {},
    options: { ownerPubkey?: string; signal?: AbortSignal } = {}
  ): Promise<Detail<AgentReserve[]>> {
    const p = new URLSearchParams();
    if (filters.reserve_type) p.set('reserve_type', filters.reserve_type);
    if (filters.status) p.set('status', filters.status);
    if (filters.mint) p.set('mint', filters.mint);
    if (filters.network) p.set('network', filters.network);
    if (filters.genesis) p.set('genesis', filters.genesis);
    if (filters.program_id) p.set('program_id', filters.program_id);

    const headers: Record<string, string> = {};
    if (options.ownerPubkey) {
      headers['X-Owner-Pubkey'] = options.ownerPubkey;
    }

    return detail(
      await this.get(
        `/v1/agents/${pubkey(account)}/reserves`,
        p,
        options.signal,
        headers
      ),
      raw => array(raw, 'agent reserves').map(agentReserve)
    );
  }

  async getReserve(
    reserveId: string,
    options: { ownerPubkey?: string; signal?: AbortSignal } = {}
  ): Promise<Detail<AgentReserve>> {
    const headers: Record<string, string> = {};
    if (options.ownerPubkey) {
      headers['X-Owner-Pubkey'] = options.ownerPubkey;
    }

    return detail(
      await this.get(
        `/v1/reserves/${encodeURIComponent(reserveId)}`,
        undefined,
        options.signal,
        headers
      ),
      agentReserve
    );
  }

  async getAgentEconomicSummary(
    account: string,
    filters: EconomicSummaryFilters = {},
    options: { ownerPubkey?: string; signal?: AbortSignal } = {}
  ): Promise<Detail<AgentEconomicSummary[]>> {
    const p = new URLSearchParams();
    if (filters.mint) p.set('mint', filters.mint);
    if (filters.network) p.set('network', filters.network);
    if (filters.genesis) p.set('genesis', filters.genesis);
    if (filters.program_id) p.set('program_id', filters.program_id);
    if (filters.period) p.set('period', filters.period);

    const headers: Record<string, string> = {};
    if (options.ownerPubkey) {
      headers['X-Owner-Pubkey'] = options.ownerPubkey;
    }

    return detail(
      await this.get(
        `/v1/agents/${pubkey(account)}/economic-summary`,
        p,
        options.signal,
        headers
      ),
      raw => array(raw, 'agent economic summaries').map(agentEconomicSummary)
    );
  }

  async getAgentSolvency(
    account: string,
    filters: SolvencyFilters = {},
    options: { authHeaders?: Record<string, string>; signal?: AbortSignal } = {}
  ): Promise<Detail<Array<AgentSolvencyAssessment | MixedAssetContext>>> {
    const p = new URLSearchParams();
    if (filters.mint) p.set('mint', filters.mint);
    if (filters.network) p.set('network', filters.network);
    if (filters.genesis) p.set('genesis_hash', filters.genesis);
    if (filters.program_id) p.set('program_id', filters.program_id);
    if (filters.window) p.set('window', String(filters.window));
    if (filters.fromTs !== undefined) p.set('from_ts', String(filters.fromTs));
    if (filters.toTs !== undefined) p.set('to_ts', String(filters.toTs));
    if (filters.consolidated !== undefined) p.set('consolidated', String(filters.consolidated));
    return detail(await this.get(`/v1/agents/${pubkey(account)}/solvency`, p, options.signal, options.authHeaders),
      raw => array(raw, 'solvency assessments').map(solvencyAssessment));
  }

  async getAgentSolvencyHistory(
    account: string,
    filters: Pick<SolvencyFilters, 'mint' | 'network' | 'genesis' | 'program_id'> & { limit?: number } = {},
    options: { authHeaders?: Record<string, string>; signal?: AbortSignal } = {}
  ): Promise<Detail<AgentSolvencyAssessment[]>> {
    const p = new URLSearchParams();
    if (filters.mint) p.set('mint', filters.mint);
    if (filters.network) p.set('network', filters.network);
    if (filters.genesis) p.set('genesis_hash', filters.genesis);
    if (filters.program_id) p.set('program_id', filters.program_id);
    if (filters.limit !== undefined) p.set('limit', String(filters.limit));
    return detail(await this.get(`/v1/agents/${pubkey(account)}/solvency/history`, p, options.signal, options.authHeaders),
      raw => array(raw, 'solvency history').map((r) => {
        const a = solvencyAssessment(r);
        if (a.calculation_status === 'MIXED_ASSET_CONTEXT') fail('Mixed context in history');
        return a as AgentSolvencyAssessment;
      }));
  }

  async getSolvencyMethodology(
    account: string,
    options: { authHeaders?: Record<string, string>; signal?: AbortSignal } = {}
  ): Promise<Detail<SolvencyMethodology>> {
    return detail(await this.get(`/v1/agents/${pubkey(account)}/solvency/methodology`, undefined, options.signal, options.authHeaders), raw => {
      const m = object(raw, 'solvency methodology');
      nonempty(m.methodology_version, 'methodology_version');
      nonempty(m.threshold_config_version, 'threshold_config_version');
      object(m.thresholds, 'thresholds');
      return m as unknown as SolvencyMethodology;
    });
  }

  async *iterateAgents(
    filters: Omit<AgentFilters, 'cursor'> = {},
    signal?: AbortSignal
  ): AsyncGenerator<Agent> {
    let cursor: string | undefined;
    const seen = new Set<string>();
    const cursors = new Set<string>();

    do {
      const result = await this.listAgents(
        { ...filters, cursor },
        signal
      );

      for (const item of result.data) {
        if (seen.has(item.agent_account)) {
          fail('Repeated agent across pages');
        }

        seen.add(item.agent_account);
        yield item;
      }

      cursor = result.page.next_cursor ?? undefined;

      if (cursor && cursors.has(cursor)) {
        fail('Repeated pagination cursor');
      }

      if (cursor) cursors.add(cursor);
    } while (cursor);
  }

  async *iterateWorkOrders(
    filters: Omit<OrderFilters, 'cursor'> = {},
    signal?: AbortSignal
  ): AsyncGenerator<WorkOrder> {
    let cursor: string | undefined;
    const seen = new Set<string>();
    const cursors = new Set<string>();

    do {
      const result = await this.listWorkOrders(
        { ...filters, cursor },
        signal
      );

      for (const item of result.data) {
        if (seen.has(item.work_order_account)) {
          fail('Repeated WorkOrder across pages');
        }

        seen.add(item.work_order_account);
        yield item;
      }

      cursor = result.page.next_cursor ?? undefined;

      if (cursor && cursors.has(cursor)) {
        fail('Repeated pagination cursor');
      }

      if (cursor) cursors.add(cursor);
    } while (cursor);
  }
}
