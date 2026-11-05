// Independent Node.js A2A 1.0 JSON-RPC client for the offline CON-41 demo.
const { URL } = require('node:url');

async function main() {
  const endpoint = new URL(process.env.CON41_TASK_URL || '');
  if (!['127.0.0.1', 'localhost'].includes(endpoint.hostname) ||
      endpoint.protocol !== 'http:' || endpoint.pathname !== '/a2a/task-rpc') {
    throw new Error('LOOPBACK_ONLY');
  }
  const state = process.env.CON41_STATE;
  if (!['WORKING', 'INPUT_REQUIRED', 'COMPLETED', 'CANCELED'].includes(state)) {
    throw new Error('INVALID_STATE');
  }
  const taskId = process.env.CON41_TASK_ID;
  const contextId = process.env.CON41_CONTEXT_ID;
  const key = process.env.CON41_IDEMPOTENCY_KEY;
  if (![taskId, contextId, key].every(value => /^[A-Za-z0-9_.:-]{1,128}$/.test(value || ''))) {
    throw new Error('INVALID_ID');
  }
  const message = {
    messageId: `node-${key}`, taskId, contextId, role: 'ROLE_AGENT',
    parts: [{text: `Node agent reports ${state}`}],
    metadata: {conatus: {state, idempotency_key: key}},
  };
  if (state === 'INPUT_REQUIRED') {
    message.parts.push({raw: Buffer.from('{"partial":true}').toString('base64'),
      mediaType: 'application/json'});
  }
  const response = await fetch(endpoint, {
    method: 'POST',
    headers: {'Content-Type': 'application/json', 'A2A-Version': '1.0',
      'Authorization': `Bearer ${process.env.CON41_TOKEN}`},
    body: JSON.stringify({jsonrpc: '2.0', id: 1, method: 'SendMessage',
      params: {message}}),
    redirect: 'error',
  });
  const body = await response.json();
  if (!response.ok || body.error || !body.result?.task) {
    throw new Error(`A2A_REQUEST_FAILED:${body.error?.message || response.status}`);
  }
  process.stdout.write(JSON.stringify({task_id: body.result.task.id,
    state: body.result.task.status.state,
    artifact_count: body.result.task.artifacts?.length || 0}) + '\n');
}

main().catch(error => {
  process.stderr.write(`${error.message}\n`);
  process.exitCode = 1;
});
