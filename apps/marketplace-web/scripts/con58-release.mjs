import { readFileSync } from 'node:fs';
import { prepareRelease, validateRollbackTarget, verifyRelease } from '../staging/release.mjs';

const [operation, ...args] = process.argv.slice(2);
try {
  if (operation === 'prepare' && args.length === 3) {
    const release = await prepareRelease(args[0], args[1], args[2]);
    console.log(JSON.stringify(release));
  } else if (operation === 'verify' && args.length === 3) {
    const release = await verifyRelease(args[0], args[1], args[2]);
    console.log(JSON.stringify({ release_id: release.release_id, artifact_digest: release.artifact_digest,
      commit_sha: release.commit_sha, status: 'VERIFIED_OFFLINE' }));
  } else if (operation === 'rollback-plan' && args.length === 3) {
    const current = JSON.parse(readFileSync(args[0], 'utf8'));
    const previous = JSON.parse(readFileSync(args[1], 'utf8'));
    const context = JSON.parse(readFileSync(args[2], 'utf8'));
    validateRollbackTarget(current, previous, context);
    console.log(JSON.stringify({ status: 'PENDING_APPROVAL', previous_release_id: previous.release_id,
      previous_artifact_digest: previous.artifact_digest, project: context.project,
      url: context.url, reason: context.reason, approval_id: context.approval_id,
      transactions_sent: 0 }));
  } else {
    throw new Error('Usage: con58-release.mjs prepare DIR COMMIT ISO_TIMESTAMP | verify DIR RELEASE_ID COMMIT | rollback-plan CURRENT.json PREVIOUS.json CONTEXT.json');
  }
} catch (error) {
  console.error(error.message);
  process.exitCode = 1;
}
