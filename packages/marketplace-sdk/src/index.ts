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

  private async get(
    path: string,
    params?: URLSearchParams,
    signal?: AbortSignal
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

    try {
      const response = await this.fetcher(url, {
        method: 'GET',
        signal: controller.signal,
        redirect: 'error',
      });

      const declaredLength = Number(
        response.headers.get('content-length') ?? '0'
      );

      if (declaredLength > 2_000_000) {
        fail('Response body too large');
      }

      const body = await response.text();

      if (body.length > 2_000_000) {
        fail('Response body too large');
      }

      let data: unknown;

      try {
        data = JSON.parse(body) as unknown;
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
