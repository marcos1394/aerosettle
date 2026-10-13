import assert from 'node:assert/strict';

import {
  MarketplaceClient,
  MarketplaceApiError
} from '../dist/index.js';

const EXPECTED_GENESIS =
  'HP9XKTusRPGC78EFDpR9xdEq6simL2vqyDdrMvn6Vacg';

const DRONE =
  'DcusvnYAdFFKzNDVzUkUvmgZ9fDhzszeRR5Fj8F5dMbB';

const SETTLED_ORDER =
  'DcD34tC5THj7WkV9fzCYcpRSgUdt6wwybUFcG1YvSviy';

const client = new MarketplaceClient({
  baseUrl: 'http://127.0.0.1:8787',
  timeoutMs: 10000
});

async function main() {
  console.log('=== AEROSETTLE SDK LIVE SMOKE ===');

  const health = await client.health();

  assert.equal(
    health.genesis,
    EXPECTED_GENESIS,
    'Unexpected Localnet ledger'
  );

  console.log('✅ RPC genesis verified');

  const openapi = await client.getOpenApi();

  assert.equal(openapi.openapi, '3.1.1');

  console.log('✅ OpenAPI contract available');

  const agents = [];

  for await (const agent of client.iterateAgents({
    limit: 1
  })) {
    agents.push(agent);
  }

  assert.equal(agents.length, 2);

  console.log('✅ Registered agents:', agents.length);

  const aerial = await client.listAgents({
    active: true,
    capabilitiesAll: 33n,
    limit: 10
  });

  assert.equal(aerial.total_count, 1);
  assert.equal(
    aerial.data[0].agent_account,
    DRONE
  );

  console.log('✅ Aerial capability filter selects Drone A');

  const order = await client.getWorkOrder(
    SETTLED_ORDER
  );

  assert.equal(order.data.status, 'Settled');
  assert.equal(order.data.discoverable, false);

  console.log('✅ Settled WorkOrder identified');

  const matches = await client.getMatches(
    SETTLED_ORDER
  );

  assert.equal(
    matches.data.eligible_agents.length,
    0
  );

  assert.ok(
    matches.data.evaluations.every(
      evaluation =>
        !evaluation.eligible &&
        evaluation.rejection?.code ===
          'WORK_ORDER_NOT_OPEN'
    )
  );

  assert.equal(
    matches.meta.matching_engine,
    'rust-epic-3.1'
  );

  console.log('✅ Rust matching rejects settled order');
  console.log('✅ EPIC 3.3.4 SDK LIVE SMOKE PASSED');
}

main().catch(error => {
  if (error instanceof MarketplaceApiError) {
    console.error(
      'API error:',
      error.status,
      error.code,
      error.message
    );
  } else {
    console.error(error);
  }

  process.exitCode = 1;
});
