import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { readFileSync, writeFileSync } from 'node:fs';
import { join, resolve } from 'node:path';
import { DEVNET_MANIFEST } from '../src/config/environments.ts';

export const sha256 = (value) => createHash('sha256').update(value).digest('hex');

export function inspectSnapshot(raw) {
  const value = JSON.parse(raw);
  const meta = value.metadata;
  assert.equal(value.schema_version, 1);
  assert.equal(meta.network, DEVNET_MANIFEST.network);
  assert.equal(meta.genesis_hash, DEVNET_MANIFEST.genesis_hash);
  assert.equal(meta.program_id, DEVNET_MANIFEST.program_id);
  assert.equal(meta.idl_sha256, DEVNET_MANIFEST.idl_sha256);
  assert.equal(meta.binary_sha256, '6cf3412c55c38e91b2ba0039aea24d58782c5db0d18759ffdab1c88788cdc3a2');
  assert.equal(meta.deployment_id, '06c7dfa7528460969a5ca1e8bd001f9c9f1f1f0df3d69fe36649e413e0b14ae6');
  assert.equal(meta.mint, DEVNET_MANIFEST.token_mint);
  assert.equal(meta.token_program, DEVNET_MANIFEST.token_program);
  assert.equal(meta.mint_authority, '4om6LcFXaZ2Wtbn3P2ZvvyqssXFQs1xjNmE2Fnj7mRHa');
  assert.equal(meta.mint_decimals, DEVNET_MANIFEST.token_decimals);
  assert.equal(meta.source_rpc, DEVNET_MANIFEST.rpc_endpoint);
  assert.equal(meta.commitment, 'finalized');
  assert.equal(meta.provenance, 'RELEASE_BOUND_RPC_SNAPSHOT');
  assert.equal(meta.atomic_snapshot, false);
  assert.ok(Array.isArray(value.agents) && Array.isArray(value.work_orders));
  assert.equal(meta.agent_count, value.agents.length);
  assert.equal(meta.work_order_count, value.work_orders.length);
  assert.ok(value.agents.length <= 500 && value.work_orders.length <= 500);
  assert.ok(Number.isInteger(meta.slot_min) && Number.isInteger(meta.slot_max) &&
    meta.slot_min <= meta.slot_max && meta.slot_max <= meta.observed_slot);
  const start = Date.parse(meta.generated_at), end = Date.parse(meta.expires_at);
  assert.ok(Number.isFinite(start) && Number.isFinite(end) && end > start &&
    end - start <= 86_400_000, 'SNAPSHOT_EXPIRY_INVALID');
  return { snapshot_sha256: sha256(raw), expires_at: meta.expires_at,
    agent_count: meta.agent_count, work_order_count: meta.work_order_count };
}

export function inspectWorker(worker) {
  const match = worker.match(/const SNAPSHOT_JSON = ("[^\n]*");\nconst SNAPSHOT_SHA256 = '([a-f0-9]{64})';/);
  assert.ok(match, 'SNAPSHOT_WORKER_INVALID');
  const raw = JSON.parse(match[1]);
  const inspection = inspectSnapshot(raw);
  assert.equal(match[2], inspection.snapshot_sha256, 'SNAPSHOT_HASH_MISMATCH');
  return inspection;
}

export function packageSnapshot(folder, snapshotFile) {
  const root = resolve(folder);
  const raw = readFileSync(snapshotFile, 'utf8');
  const inspection = inspectSnapshot(raw);
  assert.ok(Date.now() < Date.parse(inspection.expires_at), 'SNAPSHOT_ALREADY_EXPIRED');
  const template = readFileSync(new URL('../staging/con59-worker.mjs', import.meta.url), 'utf8');
  const worker = template.replaceAll('__SNAPSHOT_JSON__', JSON.stringify(raw))
    .replaceAll('__SNAPSHOT_SHA256__', inspection.snapshot_sha256);
  assert.deepEqual(inspectWorker(worker), inspection);
  writeFileSync(join(root, '_worker.js'), worker);
  writeFileSync(join(root, '_routes.json'), JSON.stringify({ version: 1,
    include: ['/api/*'], exclude: [] }) + '\n');
  return inspection;
}

if (process.argv[1] && resolve(process.argv[1]) === resolve(new URL(import.meta.url).pathname)) {
  const [folder, snapshotFile] = process.argv.slice(2);
  assert.ok(folder && snapshotFile, 'Usage: con59-package.mjs DIST SNAPSHOT_JSON');
  console.log(JSON.stringify(packageSnapshot(folder, snapshotFile)));
}
