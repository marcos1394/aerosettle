import assert from 'node:assert/strict';
import { execFileSync, spawnSync } from 'node:child_process';
import { resolve } from 'node:path';
import { verifyRelease, validateDeployContext } from '../staging/release.mjs';

const [operation, folder, releaseId, commit, accountId, project, expectedUrl, wrangler] = process.argv.slice(2);
const usage = 'Usage: con58-pages-deploy.mjs preflight|deploy DIR RELEASE_ID COMMIT ACCOUNT_ID PROJECT HTTPS_PAGES_DEV_URL WRANGLER_BIN';

try {
  assert.ok(['preflight', 'deploy'].includes(operation), usage);
  assert.ok([folder, releaseId, commit, accountId, project, expectedUrl, wrangler].every(Boolean), usage);
  assert.match(accountId, /^[a-f0-9]{32}$/);
  assert.match(project, /^[a-z0-9][a-z0-9-]*$/);
  assert.equal(expectedUrl, `https://${project}.pages.dev/`, 'PAGES_DOMAIN_MISMATCH');
  assert.equal(resolve(folder), folder, 'ARTIFACT_PATH_NOT_ABSOLUTE');
  const release = await verifyRelease(folder, releaseId, commit);
  if (release.snapshot_expires_at)
    assert.ok(Date.now() < Date.parse(release.snapshot_expires_at), 'SNAPSHOT_EXPIRED');

  // Wrangler keeps its OAuth credential in the OS keychain. Capture it in memory only.
  const credential = JSON.parse(execFileSync(wrangler, ['auth', 'token', '--json'],
    { encoding: 'utf8', stdio: ['ignore', 'pipe', 'ignore'], cwd: '/private/tmp' }));
  assert.ok(credential.token, 'CLOUDFLARE_SESSION_MISSING');
  const response = await fetch(`https://api.cloudflare.com/client/v4/accounts/${accountId}/pages/projects/${project}`,
    { headers: { Authorization: `Bearer ${credential.token}` } });
  assert.equal(response.status, 200, 'CLOUDFLARE_PROJECT_LOOKUP_FAILED');
  const body = await response.json();
  assert.equal(body.success, true, 'CLOUDFLARE_PROJECT_LOOKUP_FAILED');
  const live = body.result;
  assert.equal(live.name, project, 'HOST_PROJECT_MISMATCH');
  assert.equal(live.subdomain, new URL(expectedUrl).hostname, 'STAGING_DOMAIN_MISMATCH');
  assert.ok(live.domains.includes(live.subdomain), 'STAGING_DOMAIN_MISMATCH');
  assert.equal(live.production_branch, 'staging', 'STAGING_BRANCH_MISMATCH');

  if (operation === 'preflight') {
    console.log(JSON.stringify({ status: 'PREFLIGHT_VERIFIED', account_id: accountId,
      project, url: expectedUrl, release_id: release.release_id,
      artifact_digest: release.artifact_digest, commit_sha: release.commit_sha }));
  } else {
    const approval = `${accountId}/${project}/${releaseId}`;
    assert.equal(process.env.CON58_APPROVED_DESTINATION, approval, 'DEPLOY_APPROVAL_MISSING');
    validateDeployContext(release, { approved_release_id: releaseId, account_id: accountId,
      project, url: expectedUrl, verified_project: live.name,
      verified_url: `https://${live.subdomain}/`, credentials_present: true,
      environment_approved: true });
    const result = spawnSync(wrangler, ['pages', 'deploy', folder, '--project-name', project,
      '--branch', 'staging', '--commit-hash', commit,
      '--commit-message', `CON-58 release ${releaseId}`],
    { stdio: 'inherit', cwd: '/private/tmp',
      env: { ...process.env, CLOUDFLARE_ACCOUNT_ID: accountId } });
    assert.equal(result.status, 0, 'CLOUDFLARE_DEPLOY_FAILED');
  }
} catch (error) {
  console.error(error.message);
  process.exitCode = 1;
}
