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
  | 'ADJUSTMENT';

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
    filters: { mint?: string; network?: string } = {},
    options: { ownerPubkey?: string; signal?: AbortSignal } = {}
  ): Promise<Detail<BalanceReport[]>> {
    const p = new URLSearchParams();
    if (filters.mint) p.set('mint', filters.mint);
    if (filters.network) p.set('network', filters.network);

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
