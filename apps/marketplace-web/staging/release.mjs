import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { copyFileSync, existsSync, lstatSync, readFileSync, readdirSync, writeFileSync } from 'node:fs';
import { join, relative, resolve, sep } from 'node:path';
import { DEVNET_MANIFEST } from '../src/config/environments.ts';
import { verifyManifest } from '../src/config/manifest.ts';
import { inspectWorker } from '../scripts/con59-package.mjs';

const expectedHeaders = new URL('./_headers', import.meta.url);
const forbiddenBundle = ['signTransaction', 'sendTransaction', 'LocalnetDevWalletAdapter',
  'localnet-idl.json', 'dev-signer', 'funding-api', 'PhantomWalletAdapter'];
const sha256 = (value) => createHash('sha256').update(value).digest('hex');
const compare = (a, b) => a < b ? -1 : a > b ? 1 : 0;
const canonical = (value) => JSON.stringify(value, (_, item) =>
  item && typeof item === 'object' && !Array.isArray(item)
    ? Object.fromEntries(Object.entries(item).sort(([a], [b]) => compare(a, b))) : item);

function collectFiles(root, folder = root) {
  const files = [];
  for (const name of readdirSync(folder).sort()) {
    const full = join(folder, name);
    const info = lstatSync(full);
    assert.ok(!info.isSymbolicLink(), 'STAGING_SYMLINK_FORBIDDEN');
    if (info.isDirectory()) files.push(...collectFiles(root, full));
    else {
      assert.ok(info.isFile(), 'STAGING_NON_FILE_FORBIDDEN');
      const path = relative(root, full).split(sep).join('/');
      assert.ok(!/(^|\/)(?:\.env|.*keypair.*|.*secret.*|.*localnet.*|.*\.map)$/.test(path),
        `STAGING_FILE_FORBIDDEN:${path}`);
      if (path !== 'release.json') files.push({ path, sha256: sha256(readFileSync(full)), size: info.size });
    }
  }
  return files.sort((a, b) => compare(a.path, b.path));
}

export function verifyHeaders(text) {
  const blocks = new Map();
  let path;
  for (const raw of text.split(/\r?\n/)) {
    if (!raw.trim() || raw.trim().startsWith('#')) continue;
    if (!/^\s/.test(raw)) {
      path = raw.trim();
      assert.ok(path.startsWith('/') && !blocks.has(path), 'HEADER_RULE_INVALID');
      blocks.set(path, new Map());
    } else {
      assert.ok(path, 'HEADER_RULE_INVALID');
      const match = raw.trim().match(/^([A-Za-z-]+):\s*(.+)$/);
      assert.ok(match, 'HEADER_RULE_INVALID');
      const name = match[1].toLowerCase();
      assert.ok(!blocks.get(path).has(name), 'HEADER_DUPLICATE');
      blocks.get(path).set(name, match[2]);
    }
  }
  const common = blocks.get('/*');
  assert.ok(common, 'SECURITY_HEADERS_MISSING');
  for (const name of ['content-security-policy', 'x-content-type-options', 'referrer-policy',
    'permissions-policy', 'strict-transport-security', 'x-frame-options', 'x-robots-tag'])
    assert.ok(common.has(name), `SECURITY_HEADER_MISSING:${name}`);
  const csp = common.get('content-security-policy');
  assert.ok(csp.includes("default-src 'none'") && csp.includes("script-src 'self'") &&
    csp.includes("frame-ancestors 'none'") && csp.includes("connect-src 'self' https://api.devnet.solana.com") &&
    !/\*|unsafe-inline|unsafe-eval|http:\/\//.test(csp), 'CSP_TOO_PERMISSIVE');
  assert.equal(common.get('x-content-type-options'), 'nosniff');
  assert.equal(common.get('referrer-policy'), 'no-referrer');
  assert.equal(common.get('x-frame-options'), 'DENY');
  assert.match(common.get('strict-transport-security'), /^max-age=\d+$/);
  for (const route of ['/', '/index.html', '/idl/*', '/release.json', '/con53-evidence.json'])
    assert.equal(blocks.get(route)?.get('cache-control'), 'no-store', `CACHE_INVALID:${route}`);
  assert.equal(blocks.get('/assets/*')?.get('cache-control'),
    'public, max-age=31536000, immutable', 'CACHE_INVALID:assets');
  assert.ok(!common.has('cache-control'), 'CACHE_OVERLAP');
  return true;
}

async function inspectBuild(folder) {
  const root = resolve(folder);
  assert.ok(existsSync(join(root, 'index.html')), 'BUILD_MISSING');
  const idl = readFileSync(join(root, 'idl/devnet-idl.json'), 'utf8');
  await verifyManifest(DEVNET_MANIFEST, idl);
  const evidence = JSON.parse(readFileSync(join(root, 'con53-evidence.json'), 'utf8'));
  assert.equal(evidence.target, 'devnet');
  assert.equal(evidence.DEVNET_MANIFEST_VERIFIED, true);
  assert.equal(evidence.DEVNET_READ_ONLY, true);
  assert.equal(evidence.MAINNET_ENABLED, false);
  assert.equal(evidence.TRANSACTION_SIGNING_ENABLED, false);
  assert.equal(evidence.STAGING_PUBLIC_DEPLOYED, false);
  assert.equal(evidence.manifest_sha256, DEVNET_MANIFEST.manifest_sha256);
  assert.equal(evidence.idl_sha256, DEVNET_MANIFEST.idl_sha256);
  const assets = readdirSync(join(root, 'assets')).filter((name) => name.endsWith('.js')).sort();
  assert.ok(assets.length > 0, 'BUNDLE_MISSING');
  const bundle = assets.map((name) => readFileSync(join(root, 'assets', name), 'utf8')).join('\n');
  assert.equal(sha256(bundle), evidence.bundle_sha256, 'BUNDLE_HASH_MISMATCH');
  assert.ok(bundle.includes('devnet-app') && bundle.includes(DEVNET_MANIFEST.token_mint),
    'DEVNET_ENTRY_MISSING');
  for (const capability of forbiddenBundle)
    assert.ok(!bundle.includes(capability), `FINANCIAL_CAPABILITY_FORBIDDEN:${capability}`);
  const headers = readFileSync(join(root, '_headers'), 'utf8');
  verifyHeaders(headers);
  assert.equal(headers, readFileSync(expectedHeaders, 'utf8'), 'HEADERS_NOT_APPROVED');
  const worker = readFileSync(join(root, '_worker.js'), 'utf8');
  const snapshot = inspectWorker(worker);
  assert.ok(Date.now() < Date.parse(snapshot.expires_at), 'SNAPSHOT_EXPIRED');
  assert.deepEqual(JSON.parse(readFileSync(join(root, '_routes.json'), 'utf8')),
    { version: 1, include: ['/api/*'], exclude: [] }, 'FUNCTION_ROUTES_INVALID');
  return { root, files: collectFiles(root), bundle_sha256: evidence.bundle_sha256, snapshot };
}

export async function prepareRelease(folder, commitSha, buildTimestamp) {
  assert.match(commitSha, /^[a-f0-9]{40}$/, 'COMMIT_INVALID');
  assert.equal(new Date(buildTimestamp).toISOString(), buildTimestamp, 'TIMESTAMP_INVALID');
  const root = resolve(folder);
  assert.ok(!existsSync(join(root, 'release.json')), 'RELEASE_ALREADY_PREPARED');
  copyFileSync(expectedHeaders, join(root, '_headers'));
  const build = await inspectBuild(root);
  const release = {
    schema_version: 1,
    commit_sha: commitSha,
    environment: 'DEVNET_STAGING',
    network: DEVNET_MANIFEST.network,
    genesis_hash: DEVNET_MANIFEST.genesis_hash,
    program_id: DEVNET_MANIFEST.program_id,
    token_mint: DEVNET_MANIFEST.token_mint,
    manifest_sha256: DEVNET_MANIFEST.manifest_sha256,
    idl_sha256: DEVNET_MANIFEST.idl_sha256,
    bundle_sha256: build.bundle_sha256,
    snapshot_sha256: build.snapshot.snapshot_sha256,
    snapshot_expires_at: build.snapshot.expires_at,
    build_timestamp: buildTimestamp,
    artifact_digest: sha256(canonical(build.files)),
    files: build.files,
    publication_status: 'PENDING_APPROVAL',
    transactions_sent: 0,
  };
  release.release_id = sha256(canonical(release));
  writeFileSync(join(root, 'release.json'), JSON.stringify(release, null, 2) + '\n');
  return release;
}

export async function verifyRelease(folder, expectedId, expectedCommit) {
  const root = resolve(folder);
  const release = JSON.parse(readFileSync(join(root, 'release.json'), 'utf8'));
  assert.match(expectedId, /^[a-f0-9]{64}$/, 'RELEASE_ID_INVALID');
  assert.equal(release.release_id, expectedId, 'RELEASE_ID_MISMATCH');
  assert.equal(release.commit_sha, expectedCommit, 'COMMIT_MISMATCH');
  assert.equal(release.environment, 'DEVNET_STAGING');
  assert.equal(release.network, DEVNET_MANIFEST.network);
  assert.equal(release.genesis_hash, DEVNET_MANIFEST.genesis_hash);
  assert.equal(release.program_id, DEVNET_MANIFEST.program_id);
  assert.equal(release.token_mint, DEVNET_MANIFEST.token_mint);
  assert.equal(release.manifest_sha256, DEVNET_MANIFEST.manifest_sha256);
  assert.equal(release.idl_sha256, DEVNET_MANIFEST.idl_sha256);
  assert.equal(release.publication_status, 'PENDING_APPROVAL');
  assert.equal(release.transactions_sent, 0);
  const { release_id: _id, ...unsigned } = release;
  assert.equal(sha256(canonical(unsigned)), expectedId, 'RELEASE_METADATA_TAMPERED');
  const build = await inspectBuild(root);
  assert.deepEqual(build.files, release.files, 'ARTIFACT_FILES_CHANGED');
  assert.equal(sha256(canonical(build.files)), release.artifact_digest, 'ARTIFACT_DIGEST_MISMATCH');
  assert.equal(build.bundle_sha256, release.bundle_sha256, 'BUNDLE_HASH_MISMATCH');
  assert.equal(build.snapshot.snapshot_sha256, release.snapshot_sha256, 'SNAPSHOT_HASH_MISMATCH');
  assert.equal(build.snapshot.expires_at, release.snapshot_expires_at, 'SNAPSHOT_EXPIRY_MISMATCH');
  return release;
}

export function validateDeployContext(release, context) {
  assert.equal(context.approved_release_id, release.release_id, 'APPROVAL_ID_MISMATCH');
  assert.match(context.account_id ?? '', /^[a-f0-9]{32}$/, 'HOST_ACCOUNT_MISSING');
  assert.match(context.project ?? '', /^[a-z0-9][a-z0-9-]*$/, 'HOST_PROJECT_MISSING');
  assert.match(context.url ?? '', /^https:\/\/[a-z0-9.-]+\/?$/, 'STAGING_URL_INVALID');
  const host = new URL(context.url).hostname;
  assert.ok(host !== 'localhost' && !host.endsWith('.localhost') &&
    !host.includes('mainnet') && !host.includes('prod'), 'STAGING_DOMAIN_INVALID');
  assert.equal(context.verified_project, context.project, 'HOST_PROJECT_MISMATCH');
  assert.equal(context.verified_url, context.url, 'STAGING_DOMAIN_MISMATCH');
  assert.equal(context.credentials_present, true, 'HOST_CREDENTIALS_MISSING');
  assert.equal(context.environment_approved, true, 'DEPLOY_APPROVAL_MISSING');
  return true;
}

export function validateRollbackTarget(current, previous, context) {
  assert.notEqual(current.release_id, previous.release_id, 'ROLLBACK_TARGET_SAME_RELEASE');
  for (const key of ['environment', 'network', 'genesis_hash', 'program_id', 'token_mint',
    'manifest_sha256', 'idl_sha256'])
    assert.equal(previous[key], current[key], `ROLLBACK_CONTEXT_MISMATCH:${key}`);
  assert.match(previous.artifact_digest, /^[a-f0-9]{64}$/, 'ROLLBACK_DIGEST_INVALID');
  assert.equal(context.previous_release_id, previous.release_id, 'ROLLBACK_ID_MISMATCH');
  assert.equal(context.previous_artifact_digest, previous.artifact_digest, 'ROLLBACK_HASH_MISMATCH');
  assert.equal(context.project, context.verified_project, 'HOST_PROJECT_MISMATCH');
  assert.equal(context.url, context.verified_url, 'STAGING_DOMAIN_MISMATCH');
  assert.ok(context.reason?.trim(), 'ROLLBACK_REASON_MISSING');
  assert.ok(context.approval_id?.trim(), 'ROLLBACK_APPROVAL_MISSING');
  return true;
}
