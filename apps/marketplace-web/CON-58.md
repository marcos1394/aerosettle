# CON-58 — Devnet staging and preview delivery

## Current state

`PENDING_APPROVAL`: the approved Devnet frontend can be built, checked and packaged as an immutable release. No hosting account, staging project, domain, deployment credential or protected deployment environment is configured in this repository. There is no public URL to verify, and no staging deployment or rollback has occurred. A passing PR workflow prepares an artifact; it does not publish a site. The associated evidence is in [`../../evidence/con58/status.json`](../../evidence/con58/status.json).

CON-53's `origin/master` merge `3779b199b48a7707b67931fdb94484591fe30619` is the base. The release is `DEVNET_STAGING`, with genesis `EtWTRABZaYq6iMfeYKouRu166VU2xqa1wcaWoxPkrZBG`, program `CeA1P1NSuPLUH31KsT4j3pZeBsknQZ3NSC6GUAqcsCLy` and test mint `HpfaV9oRuTN1b3ktDKvJoWqUWFZ1o9VFmhejxxqQ1vyh`. `MAINNET` remains disabled. The entry graph is the CON-53 read-only Devnet app. It has no wallet, signing, transaction submission or financial action. The live UI reports `DEGRADED_READ_ONLY / API_NOT_CONFIGURED` only after it verifies Devnet RPC identity. `READY_FOR_TRANSACTIONS` is always false. CON-55 and CON-59 must supply and verify a Marketplace Devnet API before any stronger readiness claim.

## Hosting decision and trust boundary

The repository has no hosting configuration or authorized account for Cloudflare Pages, Firebase Hosting or Vercel. Cloudflare Pages Direct Upload is a **candidate** because it accepts a prebuilt static directory, supports custom headers and domains, and provides deployment rollback. Firebase Hosting and Vercel also support static previews, but choosing either requires a project, operator access and an approved domain. No provider has been selected on behalf of an unknown account. No production or third-party project may be reused.

The `_headers` file is prepared for Cloudflare Pages. Its CSP allows only the approved Devnet RPC as a network destination; it denies framing and form submission, applies noindex, and keeps HTML, IDL and evidence uncached while immutable hashed assets may be cached. These are **artifact assertions** until a host serves them. If another provider is selected, translate the header rules and verify the actual HTTP response before publication.

The Vite Devnet build disables the general `public/` copy and emits only the approved Devnet IDL and the image referenced by page metadata. This prevents `localnet-idl.json` from appearing in a Devnet artifact. The release checker rejects any Localnet or secret file, source map, symlink or forbidden financial module and hashes every file. `release.json` binds the exact commit, identity, IDL, JS bundle, timestamp and file digest. Any changed byte requires a new release ID and approval.

## CI, approval and deployment procedure

`.github/workflows/con58-devnet-staging.yml` has `VALIDATE`, `PREPARE` and `DEPLOY` dispatch choices. PRs run the first two with pinned Actions and read-only permissions. They run SDK/frontend tests, CON-46 security gates, typecheck, Devnet build and package verification; they upload the immutable artifact. The `DEPLOY` dispatch deliberately fails with `PENDING_APPROVAL`. It cannot use a PR event to obtain hosting credentials. The existing CON-46 workflow policy forbids `secrets.` in workflows; any future protected deploy workflow must first be reviewed against that policy rather than weakening it silently.

Before implementing or running deployment, an operator must provide the **staging-only** hosting account ID, project, public HTTPS domain and a minimum-scope credential through a protected environment; verify ownership via the provider API; identify a prior compatible deployment for rollback; and approve the exact release ID and target. The packaged release can be checked locally:

```bash
npm run build:devnet --prefix apps/marketplace-web
node --experimental-strip-types apps/marketplace-web/scripts/verify-build.mjs devnet
node --experimental-strip-types apps/marketplace-web/scripts/con58-release.mjs prepare apps/marketplace-web/dist-devnet COMMIT_SHA ISO_UTC_TIMESTAMP
node --experimental-strip-types apps/marketplace-web/scripts/con58-release.mjs verify apps/marketplace-web/dist-devnet RELEASE_ID COMMIT_SHA
```

`validateDeployContext()` checks approval ID and expected host binding offline. It is **not** proof of provider ownership or a deploy command. After access is configured, the operator must compare the provider API's account/project/domain with the approved values, verify the uploaded bytes against `artifact_digest`, deploy only the prepared directory, and record provider deployment ID, URL, time and actor. The deployment should be held in a protected environment for human approval. The workflow should fail closed on missing or mismatched bindings.

## Required live smoke and readiness

After an actual deployment, use a real browser at the public HTTPS URL to verify certificate, responsive rendering, CORS access to the approved Solana Devnet RPC, correct program/genesis/mint/IDL and visible read-only status. Inspect network and JS for wallet, signatures, financial endpoints and Localnet fixtures. Inspect actual response headers and cache behavior on HTML, IDL, evidence and hashed assets. Exercise RPC 429, unavailable and TLS failures in controlled browser tests; these must remove `RPC_VERIFIED` and `READY_FOR_READ_ONLY_PREVIEW` while leaving financial readiness false. Node mock tests are recorded as simulated failures, not live browser evidence. Record timestamp, release ID, commit, URL, headers, RPC response and reviewer in `evidence/con58/`.

## Rollback

Keep prior verified staging release manifests and provider deployment IDs. `rollback-plan` checks the prior release ID and artifact digest, Devnet identity and approved IDL, project/domain, reason and approval ID. It only prepares a plan; it sends no Solana transaction. An operator must verify the prior package and provider target, approve the rollback, use the provider's release rollback mechanism, then repeat the live smoke checks. It must never point at production. `ROLLBACK_TESTED` stays false until a real staging rollback is exercised and recorded.

## Evidence interpretation

`CON58_BUILD_VERIFIED` describes a local/offline build check only. `DEVNET_IDENTITY_VERIFIED` requires a current live RPC check or later live browser evidence; a pinned manifest alone does not count. `STAGING_DEPLOYED`, `PUBLIC_URL_VERIFIED`, `HTTPS_VERIFIED`, `SECURITY_HEADERS_VERIFIED` and `ROLLBACK_TESTED` remain false until each corresponding real-world action succeeds. The package's `publication_status` remains `PENDING_APPROVAL` even when the package is verified offline.

## External documentation

- [Cloudflare Pages Direct Upload](https://developers.cloudflare.com/pages/get-started/direct-upload/), [headers](https://developers.cloudflare.com/pages/configuration/headers/), [custom domains](https://developers.cloudflare.com/pages/configuration/custom-domains/), [rollback](https://developers.cloudflare.com/pages/configuration/rollbacks/) and [limits](https://developers.cloudflare.com/pages/platform/limits/).
