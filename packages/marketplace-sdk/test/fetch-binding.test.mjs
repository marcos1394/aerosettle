import test from 'node:test';
import assert from 'node:assert/strict';

import {
  MarketplaceClient
} from '../dist/index.js';

test('native fetch preserves globalThis receiver', async () => {
  const originalFetch = globalThis.fetch;

  let called = false;

  try {
    globalThis.fetch = function (input, init) {
      assert.equal(
        this,
        globalThis,
        'fetch must retain its native receiver'
      );

      assert.equal(init.method, 'GET');

      called = true;

      return Promise.resolve(
        new Response(
          JSON.stringify({
            status: 'ok',
            service: 'aerosettle-marketplace',
            genesis:
              'HP9XKTusRPGC78EFDpR9xdEq6simL2vqyDdrMvn6Vacg'
          }),
          {
            status: 200,
            headers: {
              'content-type': 'application/json'
            }
          }
        )
      );
    };

    const client = new MarketplaceClient();

    const result = await client.health();

    assert.equal(result.status, 'ok');
    assert.equal(called, true);

  } finally {
    globalThis.fetch = originalFetch;
  }
});
