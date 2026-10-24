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
  read_only: boolean;
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
  amount_base_units: number | null;
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
  genesis_hash: string;
  program_id: string;
  token_mint: string;
  reconciled_balance: number | null;
  provisional_balance: number | null;
  reserved_balance: number | null;
  reconciled_balance_str: string;
  provisional_balance_str: string;
  reserved_balance_str: string;
  total_effective_balance: number | null;
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
  genesis_hash: string;
  program_id: string;
  token_mint: string;
  amount_base_units: number | null;
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
  genesis_hash: string;
  program_id: string;
  token_mint: string;
  target_amount_base_units: number | null;
  target_amount_str: string;
  current_reserved_base_units: number | null;
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
  genesis_hash: string;
  program_id: string;
  token_mint: string;
  total_income_reconciled: number | null;
  total_income_provisional: number | null;
  total_expenses_realized: number | null;
  total_obligations_accrued: number | null;
  total_estimated_costs: number | null;
  total_capital_reserved: number | null;
  available_balance: number | null;
  total_effective_balance: number | null;
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
  verified_revenue_base_units_str: string | null;
  verified_opex_base_units_str: string | null;
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

export interface PrivateEconomicRequestOptions {
  ownerPubkey?: string;
  authHeaders?: Record<string, string>;
  signal?: AbortSignal;
}

export type BudgetPolicyStatus = 'DRAFT' | 'ACTIVE' | 'PAUSED' | 'REVOKED';

export interface AssetBudgetRule {
  token_mint: string;
  max_per_operation_base_units_str: U64String;
  max_daily_spend_base_units_str: U64String;
  minimum_reserve_base_units_str: U64String;
  enabled: boolean;
}

export interface BudgetReserveComparison {
  token_mint: string;
  policy_minimum_reserve_base_units_str: U64String;
  accounting_reserved_base_units_str: U64String;
  reserve_shortfall_base_units_str: U64String;
  ledger_available_balance_str: string | null;
  ledger_accrued_obligations_base_units_str: string | null;
  policy_target_is_not_locked_funds: true;
}

export interface AgentBudgetPolicy {
  policy_id: string;
  agent_account: string;
  agent_id: string;
  owner_pubkey: string;
  network: string;
  genesis_hash: string;
  program_id: string;
  version: number;
  status: BudgetPolicyStatus;
  effective_status: BudgetPolicyStatus | 'EXPIRED';
  asset_rules: AssetBudgetRule[];
  allowed_recipients: string[];
  valid_from: number;
  expires_at: number;
  created_at: number;
  created_by: string;
  revision_reason: string | null;
  policy_hash: string;
  idempotency_key: string;
  action: 'CREATE' | 'UPDATE' | 'ACTIVATE' | 'PAUSE' | 'RESUME' | 'REVOKE';
  is_currently_valid: boolean;
  reserve_comparison?: BudgetReserveComparison[];
}

export type BudgetPolicyVersion = AgentBudgetPolicy;
export type BudgetPolicyEvent = Pick<AgentBudgetPolicy, 'version' | 'action' | 'created_at' | 'created_by' | 'policy_hash'>;

export interface BudgetPolicyMutationControl {
  expected_version: number;
  idempotency_key: string;
  nonce: string;
  revision_reason?: string;
}

export interface BudgetPolicyConfiguration {
  network: string;
  genesis_hash: string;
  program_id: string;
  asset_rules: AssetBudgetRule[];
  allowed_recipients: string[];
  valid_from: number;
  expires_at: number;
}

export type BudgetPolicyMutationRequest = BudgetPolicyMutationControl & BudgetPolicyConfiguration;
export interface SignedPolicyRequestOptions {
  authHeaders: Record<string, string>;
  signal?: AbortSignal;
}

export interface SpendingProposal {
  proposal_id: string;
  idempotency_key: string;
  nonce: string;
  agent_account: string;
  agent_id: string;
  requester_pubkey: string;
  network: string;
  genesis_hash: string;
  program_id: string;
  token_mint: string;
  recipient_pubkey: string;
  amount_base_units_str: U64String;
  purpose: string;
  requested_at: number;
  expected_policy_id: string;
  expected_policy_version: number;
  expected_policy_hash: string;
  metadata: Record<string, unknown>;
}

export type SpendingEvaluationRequest = SpendingProposal;
export interface SpendingDecisionReason { code: string; }
export interface SpendingBudgetSnapshot {
  daily_window_start_utc: number;
  daily_window_end_utc: number;
  daily_limit_base_units_str: string | null;
  daily_used_base_units_str: string | null;
  daily_committed_base_units_str: string | null;
  daily_remaining_base_units_str: string | null;
}
export interface SpendingDecision extends SpendingBudgetSnapshot {
  decision_id: string;
  proposal_id: string;
  agent_account: string;
  decision: 'ALLOW' | 'DENY' | 'REQUIRE_APPROVAL';
  reason_codes: string[];
  reason_details: SpendingDecisionReason[];
  policy_id: string | null;
  policy_version: number | null;
  policy_hash: string | null;
  network: string;
  genesis_hash: string;
  program_id: string;
  token_mint: string;
  requested_amount_base_units_str: U64String;
  minimum_reserve_base_units_str: string | null;
  accounting_reserved_base_units_str: string | null;
  available_liquidity_base_units_str: string | null;
  accrued_obligations_base_units_str: string | null;
  economic_evidence_status: string;
  economic_snapshot_hash: string;
  evaluated_at: number;
  expires_at: number;
  decision_engine_version: string;
  is_executable: false;
  historical: boolean;
  is_currently_applicable: boolean;
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

function exactLegacyAmount(row: Record<string, unknown>, numberKey: string, stringKey: string, signed = false): void {
  const exact = signed ? nonempty(row[stringKey], stringKey) : u64(row[stringKey], stringKey);
  if (signed && !/^-?(0|[1-9][0-9]*)$/.test(exact)) fail(`Invalid ${stringKey}`);
  const legacy = row[numberKey];
  if (typeof legacy !== 'number')
    fail(`Invalid ${numberKey}`);
  if (!Number.isFinite(legacy) || !Number.isInteger(legacy))
    fail(`Invalid ${numberKey}`);
  if (!Number.isSafeInteger(legacy)) {
    row[numberKey] = null;
  } else if (BigInt(legacy as number) !== BigInt(exact)) {
    fail(`Mismatched ${numberKey} and ${stringKey}`);
  }
}

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
  exactLegacyAmount(m, 'amount_base_units', 'amount_str');
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
  nonempty(b.genesis_hash, 'genesis_hash');
  nonempty(b.program_id, 'program_id');
  nonempty(b.token_mint, 'token_mint');
  for (const name of ['reconciled_balance', 'provisional_balance', 'reserved_balance', 'total_effective_balance'])
    exactLegacyAmount(b, name, `${name}_str`, true);
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
  nonempty(c.genesis_hash, 'genesis_hash');
  nonempty(c.program_id, 'program_id');
  nonempty(c.token_mint, 'token_mint');
  exactLegacyAmount(c, 'amount_base_units', 'amount_str');
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
  nonempty(r.genesis_hash, 'genesis_hash');
  nonempty(r.program_id, 'program_id');
  nonempty(r.token_mint, 'token_mint');
  exactLegacyAmount(r, 'target_amount_base_units', 'target_amount_str');
  exactLegacyAmount(r, 'current_reserved_base_units', 'current_reserved_str');
  nonempty(r.status, 'status');
  integer(r.created_at, 'created_at');
  integer(r.updated_at, 'updated_at');
  return r as unknown as AgentReserve;
}

function agentEconomicSummary(raw: unknown): AgentEconomicSummary {
  const s = object(raw, 'economic summary');
  nonempty(s.agent_account, 'agent_account');
  nonempty(s.network, 'network');
  nonempty(s.genesis_hash, 'genesis_hash');
  nonempty(s.program_id, 'program_id');
  nonempty(s.token_mint, 'token_mint');
  for (const name of ['total_income_reconciled', 'total_income_provisional',
    'total_expenses_realized', 'total_obligations_accrued', 'total_estimated_costs',
    'total_capital_reserved', 'available_balance', 'total_effective_balance'])
    exactLegacyAmount(s, name, `${name}_str`, name === 'available_balance' || name === 'total_effective_balance');
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
  for (const key of ['verified_revenue_base_units_str', 'verified_opex_base_units_str']) {
    if (a[key] === null && status === 'ERROR') continue;
    u64(a[key], key);
  }
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

function meta(raw: unknown, expectedReadOnly = true): ApiMeta {
  const m = object(raw, 'metadata');

  nonempty(m.program_id, 'program_id');
  nonempty(m.commitment, 'commitment');
  integer(m.chain_now_unix, 'chain_now_unix');
  boolean(m.atomic_snapshot, 'atomic_snapshot');

  if (
    m.read_only !== expectedReadOnly ||
    m.matching_engine !== 'rust-epic-3.1'
  ) {
    fail('Unexpected matching authority');
  }

  object(m.rpc_context_slots, 'rpc_context_slots');

  return m as unknown as ApiMeta;
}

function budgetPolicy(raw: unknown): AgentBudgetPolicy {
  const p = object(raw, 'budget policy');
  for (const key of ['policy_id', 'agent_account', 'agent_id', 'owner_pubkey',
    'network', 'genesis_hash', 'program_id', 'policy_hash', 'created_by',
    'idempotency_key', 'action']) nonempty(p[key], key);
  const version = integer(p.version, 'version');
  if (version < 1 || !['DRAFT', 'ACTIVE', 'PAUSED', 'REVOKED'].includes(nonempty(p.status, 'status')) ||
    !['DRAFT', 'ACTIVE', 'PAUSED', 'REVOKED', 'EXPIRED'].includes(nonempty(p.effective_status, 'effective_status')))
    fail('Invalid policy status or version');
  for (const key of ['valid_from', 'expires_at', 'created_at']) integer(p[key], key);
  boolean(p.is_currently_valid, 'is_currently_valid');
  if (p.revision_reason !== null && p.revision_reason !== undefined && typeof p.revision_reason !== 'string')
    fail('Invalid revision_reason');
  for (const rawRule of array(p.asset_rules, 'asset_rules')) {
    const rule = object(rawRule, 'asset rule');
    nonempty(rule.token_mint, 'token_mint');
    for (const key of ['max_per_operation_base_units_str', 'max_daily_spend_base_units_str',
      'minimum_reserve_base_units_str']) u64(rule[key], key);
    boolean(rule.enabled, 'enabled');
  }
  array(p.allowed_recipients, 'allowed_recipients').forEach((value) => nonempty(value, 'recipient'));
  if (p.reserve_comparison !== undefined) {
    for (const rawComparison of array(p.reserve_comparison, 'reserve_comparison')) {
      const comparison = object(rawComparison, 'reserve comparison');
      nonempty(comparison.token_mint, 'token_mint');
      for (const key of ['policy_minimum_reserve_base_units_str', 'accounting_reserved_base_units_str',
        'reserve_shortfall_base_units_str']) u64(comparison[key], key);
      if (comparison.policy_target_is_not_locked_funds !== true) fail('Invalid reserve classification');
    }
  }
  return p as unknown as AgentBudgetPolicy;
}

function budgetPolicyMutationDetail(raw: unknown): Detail<AgentBudgetPolicy> {
  const r = object(raw, 'policy mutation response');
  return { data: budgetPolicy(r.data), meta: meta(r.meta, false) };
}

function canonicalPolicyJson(value: unknown): string {
  if (Array.isArray(value)) return `[${value.map(canonicalPolicyJson).join(',')}]`;
  if (value !== null && typeof value === 'object') {
    return `{${Object.keys(value).sort().filter((key) => (value as Record<string, unknown>)[key] !== undefined)
      .map((key) => `${JSON.stringify(key)}:${canonicalPolicyJson((value as Record<string, unknown>)[key])}`).join(',')}}`;
  }
  const encoded = JSON.stringify(value);
  return encoded === undefined ? fail('Invalid policy JSON value') : encoded;
}

export async function budgetPolicyMutationMessage(method: 'POST' | 'PUT', account: string,
  path: string, owner: string, timestamp: number, body: BudgetPolicyMutationControl): Promise<Uint8Array> {
  if (!path.startsWith(`/v1/agents/${pubkey(account)}/budget-policy`)) throw new RangeError('Invalid policy mutation path');
  const bytes = new TextEncoder().encode(canonicalPolicyJson(body));
  const hash = await crypto.subtle.digest('SHA-256', bytes);
  const hex = Array.from(new Uint8Array(hash), (byte) => byte.toString(16).padStart(2, '0')).join('');
  return new TextEncoder().encode(`conatus:budget-policy-mutation:v1:${timestamp}:${account}:${owner}:${method}:${path}:${hex}:${body.nonce}:${body.idempotency_key}:${body.expected_version}`);
}

export async function spendingEvaluationMessage(account: string, requester: string,
  timestamp: number, body: SpendingEvaluationRequest): Promise<Uint8Array> {
  const path = `/v1/agents/${pubkey(account)}/spending-evaluations`;
  if (body.agent_account !== account || body.requester_pubkey !== requester) throw new RangeError('Proposal identity mismatch');
  u64(body.amount_base_units_str, 'amount_base_units_str');
  const bytes = new TextEncoder().encode(canonicalPolicyJson(body));
  const hash = await crypto.subtle.digest('SHA-256', bytes);
  const hex = Array.from(new Uint8Array(hash), (byte) => byte.toString(16).padStart(2, '0')).join('');
  return new TextEncoder().encode(`conatus:spending-evaluation:v1:${timestamp}:${account}:${requester}:POST:${path}:${hex}:${body.nonce}:${body.idempotency_key}:${body.expected_policy_id}:${body.expected_policy_version}:${body.expected_policy_hash}`);
}

function spendingDecision(raw: unknown): SpendingDecision {
  const d = object(raw, 'spending decision');
  for (const key of ['decision_id', 'proposal_id', 'agent_account', 'network', 'genesis_hash',
    'program_id', 'token_mint', 'economic_evidence_status', 'economic_snapshot_hash',
    'decision_engine_version']) nonempty(d[key], key);
  if (!['ALLOW', 'DENY', 'REQUIRE_APPROVAL'].includes(nonempty(d.decision, 'decision'))) fail('Invalid spending decision');
  if (d.policy_id !== null) nonempty(d.policy_id, 'policy_id');
  if (d.policy_hash !== null) nonempty(d.policy_hash, 'policy_hash');
  if (d.policy_version !== null) integer(d.policy_version, 'policy_version');
  for (const key of ['evaluated_at', 'expires_at', 'daily_window_start_utc', 'daily_window_end_utc']) integer(d[key], key);
  u64(d.requested_amount_base_units_str, 'requested_amount_base_units_str');
  for (const key of ['daily_limit_base_units_str', 'daily_used_base_units_str',
    'daily_committed_base_units_str', 'daily_remaining_base_units_str',
    'minimum_reserve_base_units_str', 'accounting_reserved_base_units_str',
    'available_liquidity_base_units_str', 'accrued_obligations_base_units_str']) {
    if (d[key] !== null && (typeof d[key] !== 'string' || !/^(0|[1-9][0-9]*)$/.test(d[key] as string)))
      fail(`Invalid ${key}`);
  }
  array(d.reason_codes, 'reason_codes').forEach((code) => nonempty(code, 'reason code'));
  array(d.reason_details, 'reason_details').forEach((reason) => nonempty(object(reason, 'reason').code, 'reason code'));
  if (d.is_executable !== false) fail('Spending decision cannot be executable');
  boolean(d.historical, 'historical');
  boolean(d.is_currently_applicable, 'is_currently_applicable');
  return d as unknown as SpendingDecision;
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
    method: 'GET' | 'POST' | 'PUT',
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

  private async put(
    path: string,
    bodyData: unknown,
    signal?: AbortSignal,
    headers?: Record<string, string>
  ): Promise<unknown> {
    return this.exec('PUT', path, undefined, bodyData, signal, headers);
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
    options: PrivateEconomicRequestOptions = {}
  ): Promise<Page<EconomicMovement>> {
    const p = new URLSearchParams();
    if (filters.nature) p.set('nature', filters.nature);
    if (filters.status) p.set('status', filters.status);
    if (filters.mint) p.set('mint', filters.mint);
    if (filters.network) p.set('network', filters.network);
    if (filters.fromTs !== undefined) p.set('from_ts', String(filters.fromTs));
    if (filters.toTs !== undefined) p.set('to_ts', String(filters.toTs));
    paging(p, filters);

    const headers: Record<string, string> = { ...options.authHeaders };
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
    options: PrivateEconomicRequestOptions = {}
  ): Promise<Detail<BalanceReport[]>> {
    const p = new URLSearchParams();
    if (filters.mint) p.set('mint', filters.mint);
    if (filters.network) p.set('network', filters.network);
    if (filters.genesis) p.set('genesis', filters.genesis);
    if (filters.program_id) p.set('program_id', filters.program_id);

    const headers: Record<string, string> = { ...options.authHeaders };
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
    options: PrivateEconomicRequestOptions = {}
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

    const headers: Record<string, string> = { ...options.authHeaders };
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
    options: PrivateEconomicRequestOptions = {}
  ): Promise<Detail<AgentReserve[]>> {
    const p = new URLSearchParams();
    if (filters.reserve_type) p.set('reserve_type', filters.reserve_type);
    if (filters.status) p.set('status', filters.status);
    if (filters.mint) p.set('mint', filters.mint);
    if (filters.network) p.set('network', filters.network);
    if (filters.genesis) p.set('genesis', filters.genesis);
    if (filters.program_id) p.set('program_id', filters.program_id);

    const headers: Record<string, string> = { ...options.authHeaders };
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
    options: PrivateEconomicRequestOptions = {}
  ): Promise<Detail<AgentEconomicSummary[]>> {
    const p = new URLSearchParams();
    if (filters.mint) p.set('mint', filters.mint);
    if (filters.network) p.set('network', filters.network);
    if (filters.genesis) p.set('genesis', filters.genesis);
    if (filters.program_id) p.set('program_id', filters.program_id);
    if (filters.period) p.set('period', filters.period);

    const headers: Record<string, string> = { ...options.authHeaders };
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

  async getAgentBudgetPolicy(account: string, options: { authHeaders?: Record<string, string>; signal?: AbortSignal } = {}): Promise<Detail<AgentBudgetPolicy>> {
    return detail(await this.get(`/v1/agents/${pubkey(account)}/budget-policy`, undefined, options.signal, options.authHeaders), budgetPolicy);
  }

  async listAgentBudgetPolicyHistory(account: string, options: { authHeaders?: Record<string, string>; signal?: AbortSignal } = {}): Promise<Detail<BudgetPolicyVersion[]>> {
    return detail(await this.get(`/v1/agents/${pubkey(account)}/budget-policy/history`, undefined, options.signal, options.authHeaders),
      raw => array(raw, 'policy history').map(budgetPolicy));
  }

  async getAgentBudgetPolicyVersion(account: string, version: number, options: { authHeaders?: Record<string, string>; signal?: AbortSignal } = {}): Promise<Detail<BudgetPolicyVersion>> {
    if (!Number.isSafeInteger(version) || version < 1) throw new RangeError('Invalid policy version');
    return detail(await this.get(`/v1/agents/${pubkey(account)}/budget-policy/${version}`, undefined, options.signal, options.authHeaders), budgetPolicy);
  }

  private policyHeaders(options: SignedPolicyRequestOptions): Record<string, string> {
    const headers = options.authHeaders;
    if (!headers?.['X-Signer-Pubkey'] || !headers['X-Timestamp'] || !headers['X-Signature'])
      throw new TypeError('Signed policy mutation headers are required');
    return headers;
  }

  async createAgentBudgetPolicy(account: string, body: BudgetPolicyMutationRequest, options: SignedPolicyRequestOptions): Promise<Detail<AgentBudgetPolicy>> {
    return budgetPolicyMutationDetail(await this.post(`/v1/agents/${pubkey(account)}/budget-policy`, body, options.signal, this.policyHeaders(options)));
  }

  async updateAgentBudgetPolicy(account: string, body: BudgetPolicyMutationRequest, options: SignedPolicyRequestOptions): Promise<Detail<AgentBudgetPolicy>> {
    return budgetPolicyMutationDetail(await this.put(`/v1/agents/${pubkey(account)}/budget-policy`, body, options.signal, this.policyHeaders(options)));
  }

  private async policyAction(account: string, action: 'activate' | 'pause' | 'resume' | 'revoke',
    body: BudgetPolicyMutationControl, options: SignedPolicyRequestOptions): Promise<Detail<AgentBudgetPolicy>> {
    return budgetPolicyMutationDetail(await this.post(`/v1/agents/${pubkey(account)}/budget-policy/${action}`, body, options.signal, this.policyHeaders(options)));
  }

  async activateAgentBudgetPolicy(account: string, body: BudgetPolicyMutationControl, options: SignedPolicyRequestOptions): Promise<Detail<AgentBudgetPolicy>> {
    return this.policyAction(account, 'activate', body, options);
  }
  async pauseAgentBudgetPolicy(account: string, body: BudgetPolicyMutationControl, options: SignedPolicyRequestOptions): Promise<Detail<AgentBudgetPolicy>> {
    return this.policyAction(account, 'pause', body, options);
  }
  async resumeAgentBudgetPolicy(account: string, body: BudgetPolicyMutationControl, options: SignedPolicyRequestOptions): Promise<Detail<AgentBudgetPolicy>> {
    return this.policyAction(account, 'resume', body, options);
  }
  async revokeAgentBudgetPolicy(account: string, body: BudgetPolicyMutationControl, options: SignedPolicyRequestOptions): Promise<Detail<AgentBudgetPolicy>> {
    return this.policyAction(account, 'revoke', body, options);
  }

  async evaluateAgentSpending(account: string, body: SpendingEvaluationRequest,
    options: SignedPolicyRequestOptions): Promise<Detail<SpendingDecision>> {
    if (body.agent_account !== account || !body.proposal_id || !body.idempotency_key || !body.nonce)
      throw new TypeError('Invalid spending proposal identity');
    u64(body.amount_base_units_str, 'amount_base_units_str');
    const raw = await this.post(`/v1/agents/${pubkey(account)}/spending-evaluations`, body,
      options.signal, this.policyHeaders(options));
    const response = object(raw, 'spending evaluation response');
    return { data: spendingDecision(response.data), meta: meta(response.meta, false) };
  }

  async listAgentSpendingEvaluations(account: string,
    options: { authHeaders?: Record<string, string>; signal?: AbortSignal } = {}): Promise<Detail<SpendingDecision[]>> {
    return detail(await this.get(`/v1/agents/${pubkey(account)}/spending-evaluations`, undefined,
      options.signal, options.authHeaders), raw => array(raw, 'spending decisions').map(spendingDecision));
  }

  async getAgentSpendingEvaluation(account: string, decisionId: string,
    options: { authHeaders?: Record<string, string>; signal?: AbortSignal } = {}): Promise<Detail<SpendingDecision>> {
    if (!/^sd_[0-9a-f]{32}$/.test(decisionId)) throw new RangeError('Invalid decision ID');
    return detail(await this.get(`/v1/agents/${pubkey(account)}/spending-evaluations/${decisionId}`,
      undefined, options.signal, options.authHeaders), spendingDecision);
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
