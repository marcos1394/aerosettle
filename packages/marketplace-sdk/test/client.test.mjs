import test from 'node:test';
import assert from 'node:assert/strict';

import {
  MarketplaceClient,
  MarketplaceApiError,
  MarketplaceContractError
} from '../dist/index.js';

const DRONE =
  'DcusvnYAdFFKzNDVzUkUvmgZ9fDhzszeRR5Fj8F5dMbB';

const SENSOR =
  'FPbX4tQ2t9KSUDPix3NxBVEp2dD5LWoikhBVYYafU9H7';

const ORDER =
  'DcD34tC5THj7WkV9fzCYcpRSgUdt6wwybUFcG1YvSviy';

const CONFIG =
  '3qnN5ZjRL516znKdWHeEvSGLWL6sf4EoCPcG8e28je62';

const agent = (address, mask) => ({
  agent_account: address,
  agent_id: 'aa'.repeat(32),
  protocol_config: CONFIG,
  capabilities: mask,
  active: true,
  status: 'Active'
});

const workOrder = {
  work_order_account: ORDER,
  protocol_config: CONFIG,
  required_capabilities: '33',
  execution_deadline: 1791670039,
  status: 'Settled',
  is_open: false,
  discoverable: false
};

const meta = {
  program_id: CONFIG,
  commitment: 'confirmed',
  chain_now_unix: 1791669520,
  rpc_context_slots: { config: 1 },
  atomic_snapshot: false,
  read_only: true,
  matching_engine: 'rust-epic-3.1'
};

const page = (
  data,
  next = null,
  total = data.length
) => ({
  data,
  count: data.length,
  total_count: total,
  page: {
    limit: 1,
    has_more: next !== null,
    next_cursor: next
  },
  meta
});

const json = (body, status = 200) =>
  new Response(JSON.stringify(body), {
    status,
    headers: {
      'content-type': 'application/json'
    }
  });

const withFetch = handle =>
  new MarketplaceClient({
    fetchImpl: async (url, init) => {
      assert.equal(init.method, 'GET');
      return handle(new URL(url));
    }
  });

test('health and OpenAPI', async () => {
  const client = withFetch(url =>
    url.pathname === '/health'
      ? json({
          status: 'ok',
          service: 'marketplace',
          genesis: CONFIG
        })
      : json({
          openapi: '3.1.1',
          paths: {}
        })
  );

  assert.equal((await client.health()).status, 'ok');
  assert.equal(
    (await client.getOpenApi()).openapi,
    '3.1.1'
  );
});

test('u64 precision and agent filters', async () => {
  const max = '18446744073709551615';

  const client = withFetch(url => {
    assert.equal(url.pathname, '/v1/agents');
    assert.equal(
      url.searchParams.get('active'),
      'true'
    );
    assert.equal(
      url.searchParams.get('capabilities_all'),
      max
    );
    assert.equal(
      url.searchParams.get('limit'),
      '1'
    );

    return json(page([agent(DRONE, max)]));
  });

  const result = await client.listAgents({
    active: true,
    capabilitiesAll: BigInt(max),
    limit: 1
  });

  assert.equal(result.data[0].capabilities, max);
});

test('WorkOrders: filters and detail', async () => {
  const client = withFetch(url => {
    if (url.pathname === '/v1/work-orders') {
      assert.equal(
        url.searchParams.get('required_capabilities_all'),
        '33'
      );
      assert.equal(
        url.searchParams.get('status'),
        'Settled'
      );
      return json(page([workOrder]));
    }

    return json({ data: workOrder, meta });
  });

  const result = await client.listWorkOrders({
    status: 'Settled',
    requiredCapabilitiesAll: '33'
  });

  assert.equal(result.count, 1);
  assert.equal(
    (await client.getWorkOrder(ORDER)).data.status,
    'Settled'
  );
});

test('matching rejection is preserved', async () => {
  const client = withFetch(() =>
    json({
      meta,
      data: {
        work_order: workOrder,
        eligible_agents: [],
        evaluations: [
          {
            agent_account: DRONE,
            eligible: false,
            rejection: {
              code: 'WORK_ORDER_NOT_OPEN'
            }
          }
        ]
      }
    })
  );

  const result = await client.getMatches(ORDER);

  assert.equal(
    result.data.evaluations[0].rejection.code,
    'WORK_ORDER_NOT_OPEN'
  );
});

test('agent detail and marketplace view', async () => {
  const client = withFetch(url =>
    url.pathname === '/v1/marketplace'
      ? json({
          meta,
          data: {
            protocol_config: CONFIG,
            paused: false,
            agents: [agent(DRONE, '37')],
            work_orders: [workOrder],
            eligible_agents_by_order: {}
          }
        })
      : json({
          meta,
          data: agent(DRONE, '37')
        })
  );

  assert.equal(
    (await client.getAgent(DRONE)).data.agent_account,
    DRONE
  );

  assert.equal(
    (await client.getMarketplace()).data.work_orders[0].status,
    'Settled'
  );
});

test('automatic agent pagination', async () => {
  let calls = 0;

  const client = withFetch(url => {
    calls++;

    return json(
      url.searchParams.has('cursor')
        ? page([agent(SENSOR, '4')])
        : page([agent(DRONE, '37')], 'opaque', 2)
    );
  });

  const agents = [];

  for await (const item of client.iterateAgents({
    limit: 1
  })) {
    agents.push(item.agent_account);
  }

  assert.deepEqual(agents, [DRONE, SENSOR]);
  assert.equal(calls, 2);
});

test('automatic WorkOrder pagination', async () => {
  let calls = 0;

  const client = withFetch(url => {
    calls++;

    return json(
      url.searchParams.has('cursor')
        ? page([workOrder])
        : page(
            [{
              ...workOrder,
              work_order_account: DRONE
            }],
            'token',
            2
          )
    );
  });

  const orders = [];

  for await (const item of client.iterateWorkOrders({
    limit: 1
  })) {
    orders.push(item.work_order_account);
  }

  assert.deepEqual(orders, [DRONE, ORDER]);
  assert.equal(calls, 2);
});

test('409 STALE_CURSOR surfaces without retry', async () => {
  const client = withFetch(() =>
    json({
      error: {
        code: 'STALE_CURSOR',
        message: 'Results changed'
      }
    }, 409)
  );

  await assert.rejects(
    client.listAgents({ cursor: 'old' }),
    error =>
      error instanceof MarketplaceApiError &&
      error.code === 'STALE_CURSOR' &&
      error.status === 409
  );
});

test('invalid u64 and pagination are rejected', async () => {
  const invalid = withFetch(() =>
    json(
      page([
        agent(DRONE, 9007199254740993)
      ])
    )
  );

  await assert.rejects(
    invalid.listAgents(),
    MarketplaceContractError
  );

  const wrongCount = withFetch(() =>
    json({
      ...page([agent(DRONE, '37')]),
      count: 99
    })
  );

  await assert.rejects(
    wrongCount.listAgents(),
    MarketplaceContractError
  );
});

test('contradictory matching is rejected', async () => {
  const client = withFetch(() =>
    json({
      meta,
      data: {
        work_order: workOrder,
        eligible_agents: [],
        evaluations: [
          {
            agent_account: DRONE,
            eligible: true,
            rejection: {
              code: 'AGENT_INACTIVE'
            }
          }
        ]
      }
    })
  );

  await assert.rejects(
    client.getMatches(ORDER),
    MarketplaceContractError
  );
});

test('unsafe inputs are rejected', async () => {
  assert.throws(
    () => new MarketplaceClient({
      baseUrl: 'http://example.com:8787'
    }),
    TypeError
  );

  const client = withFetch(() => {
    throw new Error('Must not send request');
  });

  await assert.rejects(
    client.getAgent('not-base58'),
    RangeError
  );

  await assert.rejects(
    client.listAgents({ limit: 101 }),
    RangeError
  );

  await assert.rejects(
    client.listAgents({
      capabilitiesAll: 2n ** 64n
    }),
    RangeError
  );
});

test('duplicate accounts between pages fail closed', async () => {
  const client = withFetch(url =>
    json(
      url.searchParams.has('cursor')
        ? page([agent(DRONE, '37')])
        : page([agent(DRONE, '37')], 'more', 2)
    )
  );

  await assert.rejects(async () => {
    for await (const item of client.iterateAgents({
      limit: 1
    })) {
      void item;
    }
  }, MarketplaceContractError);
});

test('HTTP 405 is not retried', async () => {
  const client = withFetch(() =>
    json({
      error: {
        code: 'METHOD_NOT_ALLOWED',
        message: 'GET only'
      }
    }, 405)
  );

  await assert.rejects(
    client.health(),
    error =>
      error instanceof MarketplaceApiError &&
      error.status === 405
  );
});
