import test from 'node:test';
import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { copyFileSync, mkdtempSync, mkdirSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import { join } from 'node:path';
import { tmpdir } from 'node:os';
import { DEVNET_MANIFEST } from '../src/config/environments.ts';
import { prepareRelease, validateDeployContext, validateRollbackTarget, verifyHeaders,
  verifyRelease } from './release.mjs';

const sha = (value) => createHash('sha256').update(value).digest('hex');
const commit = 'a'.repeat(40);
const stamp = '2026-11-15T00:00:00.000Z';
const headers = readFileSync(new URL('./_headers', import.meta.url), 'utf8');

function fixture() {
  const root = mkdtempSync(join(tmpdir(), 'con58-release-'));
  mkdirSync(join(root, 'assets'));
  mkdirSync(join(root, 'idl'));
  copyFileSync(new URL('../public/idl/devnet-idl.json', import.meta.url),
    join(root, 'idl/devnet-idl.json'));
  const bundle = `console.log('devnet-app ${DEVNET_MANIFEST.token_mint}')`;
  writeFileSync(join(root, 'assets/app.js'), bundle);
  writeFileSync(join(root, 'index.html'), '<script src="/assets/app.js"></script>');
  writeFileSync(join(root, 'con53-evidence.json'), JSON.stringify({
    target: 'devnet', DEVNET_MANIFEST_VERIFIED: true, DEVNET_READ_ONLY: true,
    MAINNET_ENABLED: false, TRANSACTION_SIGNING_ENABLED: false,
    STAGING_PUBLIC_DEPLOYED: false, manifest_sha256: DEVNET_MANIFEST.manifest_sha256,
    idl_sha256: DEVNET_MANIFEST.idl_sha256, bundle_sha256: sha(bundle),
  }));
  return root;
}

test('approved CSP, cache and security headers are narrow', () => {
  assert.equal(verifyHeaders(headers), true);
  assert.throws(() => verifyHeaders(headers.replace(
    "connect-src 'self' https://api.devnet.solana.com", 'connect-src *')), /CSP_TOO_PERMISSIVE/);
  assert.throws(() => verifyHeaders(headers.replace(
    "connect-src 'self' https://api.devnet.solana.com",
    'connect-src https://api.devnet.solana.com')), /CSP_TOO_PERMISSIVE/);
  assert.throws(() => verifyHeaders(headers.replace('X-Content-Type-Options: nosniff', '')),
    /SECURITY_HEADER_MISSING/);
  assert.throws(() => verifyHeaders(headers.replace('Cache-Control: no-store',
    'Cache-Control: public, max-age=3600')), /CACHE_INVALID/);
});

test('release binds commit, approved identity and every staged file', async () => {
  const root = fixture();
  try {
    const release = await prepareRelease(root, commit, stamp);
    assert.equal(release.environment, 'DEVNET_STAGING');
    assert.equal(release.publication_status, 'PENDING_APPROVAL');
    assert.equal(release.transactions_sent, 0);
    assert.equal((await verifyRelease(root, release.release_id, commit)).artifact_digest,
      release.artifact_digest);
    assert.rejects(verifyRelease(root, '0'.repeat(64), commit), /RELEASE_ID_MISMATCH/);
    writeFileSync(join(root, 'assets/app.js'), 'altered after approval');
    await assert.rejects(verifyRelease(root, release.release_id, commit),
      /BUNDLE_HASH_MISMATCH/);
  } finally { rmSync(root, { recursive: true, force: true }); }
});

test('altered IDL and unsafe headers fail release preparation', async () => {
  const root = fixture();
  try {
    writeFileSync(join(root, 'idl/devnet-idl.json'), '{}');
    await assert.rejects(prepareRelease(root, commit, stamp));
  } finally { rmSync(root, { recursive: true, force: true }); }
});

test('Localnet fixtures and financial signing code cannot enter the Devnet package', async () => {
  for (const [path, content, expected] of [
    ['idl/localnet-idl.json', '{}', /STAGING_FILE_FORBIDDEN/],
    ['assets/wallet.js', 'sendTransaction()', /FINANCIAL_CAPABILITY_FORBIDDEN/],
  ]) {
    const root = fixture();
    try {
      writeFileSync(join(root, path), content);
      if (path.startsWith('assets/')) {
        const evidencePath = join(root, 'con53-evidence.json');
        const evidence = JSON.parse(readFileSync(evidencePath, 'utf8'));
        evidence.bundle_sha256 = sha(readFileSync(join(root, 'assets/app.js'), 'utf8') + '\n' + content);
        writeFileSync(evidencePath, JSON.stringify(evidence));
      }
      await assert.rejects(prepareRelease(root, commit, stamp), expected);
    } finally { rmSync(root, { recursive: true, force: true }); }
  }
});

test('release verification rejects modified security headers', async () => {
  const root = fixture();
  try {
    const release = await prepareRelease(root, commit, stamp);
    writeFileSync(join(root, '_headers'), headers.replace('X-Frame-Options: DENY',
      'X-Frame-Options: SAMEORIGIN'));
    await assert.rejects(verifyRelease(root, release.release_id, commit), /SAMEORIGIN|HEADERS_NOT_APPROVED/);
  } finally { rmSync(root, { recursive: true, force: true }); }
});

test('deploy gate requires exact release approval, host identity and credentials', () => {
  const release = { release_id: 'a'.repeat(64) };
  const valid = { approved_release_id: release.release_id, account_id: 'b'.repeat(32),
    project: 'conatus-devnet-staging', verified_project: 'conatus-devnet-staging',
    url: 'https://staging.example.org', verified_url: 'https://staging.example.org',
    credentials_present: true, environment_approved: true };
  assert.equal(validateDeployContext(release, valid), true);
  for (const patch of [
    { approved_release_id: 'c'.repeat(64) }, { verified_project: 'other-project' },
    { verified_url: 'https://other.example.org' }, { credentials_present: false },
    { environment_approved: false }, { url: 'http://staging.example.org' },
    { url: 'https://prod.example.org' },
  ]) assert.throws(() => validateDeployContext(release, { ...valid, ...patch }));
});

test('rollback plan rejects incompatible identities and missing approval', () => {
  const current = { release_id: 'a'.repeat(64), environment: 'DEVNET_STAGING',
    network: 'solana:devnet', genesis_hash: DEVNET_MANIFEST.genesis_hash,
    program_id: DEVNET_MANIFEST.program_id, token_mint: DEVNET_MANIFEST.token_mint,
    manifest_sha256: DEVNET_MANIFEST.manifest_sha256, idl_sha256: DEVNET_MANIFEST.idl_sha256 };
  const previous = { ...current, release_id: 'b'.repeat(64), artifact_digest: 'c'.repeat(64) };
  const context = { previous_release_id: previous.release_id,
    previous_artifact_digest: previous.artifact_digest, project: 'conatus-devnet-staging',
    verified_project: 'conatus-devnet-staging', url: 'https://staging.example.org',
    verified_url: 'https://staging.example.org', reason: 'Restore prior verified build',
    approval_id: 'approved-incident-1' };
  assert.equal(validateRollbackTarget(current, previous, context), true);
  assert.throws(() => validateRollbackTarget(current,
    { ...previous, genesis_hash: 'other' }, context), /ROLLBACK_CONTEXT_MISMATCH/);
  assert.throws(() => validateRollbackTarget(current, previous,
    { ...context, approval_id: '' }), /ROLLBACK_APPROVAL_MISSING/);
  assert.throws(() => validateRollbackTarget(current, previous,
    { ...context, previous_artifact_digest: 'd'.repeat(64) }), /ROLLBACK_HASH_MISMATCH/);
});
