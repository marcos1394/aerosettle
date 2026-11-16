# CON-58 — Cloudflare Pages Free Devnet staging

## Published state

The read-only Devnet frontend is live at [conatus-devnet-staging.pages.dev](https://conatus-devnet-staging.pages.dev/). The exclusive Cloudflare Pages **Direct Upload** project `conatus-devnet-staging` belongs to account `54cb929430c4a02b90d6ea3ce356d0d9` and uses production branch `staging`. The authorized account owner confirmed the **Free** plan. Wrangler OAuth identified the account, and the Pages API independently confirmed the project, subdomain and branch. The OAuth scope cannot read billing subscriptions (403); the Free-plan statement rests on the owner's confirmation. No domain, card or paid service was added.

Current deployment `e0b5976d-7927-4823-b972-ff66f5a9d451` serves release `26567e73323def9e3dd370ddcd24d97d26968e3c45a6b6dc432e31208802a517` from commit `a23057f8a46f946c1fe7c1420a4e9e5e7e3ebbed`, artifact digest `e78c5b3676bd8b4bc4b54039644605b24671111698fea32f8754e60661d2aaf4`. Its Devnet identity remains genesis `EtWTRABZaYq6iMfeYKouRu166VU2xqa1wcaWoxPkrZBG`, program `CeA1P1NSuPLUH31KsT4j3pZeBsknQZ3NSC6GUAqcsCLy`, test mint `HpfaV9oRuTN1b3ktDKvJoWqUWFZ1o9VFmhejxxqQ1vyh`, manifest SHA-256 `db8d0bf22b0e9102d9464d9f35c6732a8e0e9e444fe459ead4a75a1fc8469592` and IDL SHA-256 `a6e436aa1c6468b4f518b742e40a2664e38dcdf7bc1419e53e1624444888e15d`.

The real browser displayed `DEGRADED READ ONLY`, `LIVE_DEVNET_READ_ONLY` and `READY_FOR_READ_ONLY_PREVIEW` after checking the IDL and live Devnet RPC. The Marketplace Devnet API is not configured, so catalog and economic history remain unavailable until CON-55/CON-59. Wallet connection, signing, WorkOrders, payments and Mainnet are absent from the Devnet build; financial actions remain disabled. No Solana transaction was sent. See [`../../evidence/con58/cloudflare-pages.json`](../../evidence/con58/cloudflare-pages.json) and [`../../evidence/con58/status.json`](../../evidence/con58/status.json).

## Release and deployment procedure

The build checker excludes Localnet fixtures, secrets, source maps, symlinks and financial modules. `release.json` binds the exact commit, Devnet identity, IDL, JS bundle, timestamp and every file hash. `verifyRelease()` rechecks all bytes immediately before upload. A changed byte needs a new release ID and new human approval. Cloudflare credentials remain in the operator's encrypted Wrangler profile and macOS Keychain, outside Git, GitHub Actions, Jira and deployment logs.

Wrangler 4.162.0 tried to delegate a new Pages project to Workers. The project was created once with `wrangler pages project create conatus-devnet-staging --production-branch staging --force`, which explicitly bypassed Workers. Subsequent uploads use the existing Pages project without `--force`. Do not run `wrangler deploy`, which targets Workers.

An authorized operator uses the terminal wrapper with the verified CI artifact and approved release ID. The wrapper reads the Pages project through Cloudflare's authenticated API, checks the exact account, project, `pages.dev` URL and `staging` branch, and requires `CON58_APPROVED_DESTINATION` to match the account/project/release tuple before invoking Wrangler. It never prints the OAuth token. The commands below use placeholders intentionally; obtain the artifact and approval for the exact release before running `deploy`.

```bash
node --experimental-strip-types apps/marketplace-web/scripts/con58-release.mjs \
  verify ABSOLUTE_ARTIFACT_DIR APPROVED_RELEASE_ID RELEASE_COMMIT_SHA

node --experimental-strip-types apps/marketplace-web/scripts/con58-pages-deploy.mjs \
  preflight ABSOLUTE_ARTIFACT_DIR APPROVED_RELEASE_ID RELEASE_COMMIT_SHA \
  54cb929430c4a02b90d6ea3ce356d0d9 conatus-devnet-staging \
  https://conatus-devnet-staging.pages.dev/ ABSOLUTE_WRANGLER_BIN

CON58_APPROVED_DESTINATION=54cb929430c4a02b90d6ea3ce356d0d9/conatus-devnet-staging/APPROVED_RELEASE_ID \
node --experimental-strip-types apps/marketplace-web/scripts/con58-pages-deploy.mjs \
  deploy ABSOLUTE_ARTIFACT_DIR APPROVED_RELEASE_ID RELEASE_COMMIT_SHA \
  54cb929430c4a02b90d6ea3ce356d0d9 conatus-devnet-staging \
  https://conatus-devnet-staging.pages.dev/ ABSOLUTE_WRANGLER_BIN
```

The PR workflow still performs `VALIDATE` and `PREPARE` with read-only GitHub permissions, pinned Actions and no hosting credential. Its `DEPLOY` dispatch fails closed; terminal deployment is separate. CON-46 workflow controls were retained.

## Live checks and CSP correction

HTTPS returned 200. The response included HSTS, `nosniff`, `no-referrer`, `DENY`, restrictive Permissions Policy, `noindex` and a CSP limited to self-hosted static resources and `https://api.devnet.solana.com` for connections. HTML, IDL, evidence and release metadata use `no-store`; hashed CSS/JS use immutable caching. The served HTML, IDL, evidence, CSS and JS hashes matched the release. The browser had no console errors, and a 390×844 viewport had no horizontal overflow. The browser verified genesis, executable program, upgrade authority and SPL test mint via RPC. These observations are recorded in the evidence JSON.

The first two deployments exposed a real CSP defect: `connect-src` omitted `'self'`, blocking the same-origin IDL fetch. The UI correctly failed closed with `IDL_UNAVAILABLE`. Commit `a23057f8a46f946c1fe7c1420a4e9e5e7e3ebbed` added `'self'` while retaining only the approved Devnet RPC as an external connection, and extended the CSP regression test. The corrected release was separately approved and deployed, then passed the live browser check.

The CON-46 gitleaks inventory flagged the public SPL test mint in the evidence JSON as a generic API key. Its historical finding was added to the baseline by exact commit/file/line fingerprint, with a redacted value. The current evidence names the value `spl_test_mint_pubkey` to prevent a recurring false positive; no scanner rule or scope was disabled.

## Rollback evidence

Two initial compatible production deployments were published: `8927927d-5ab5-4b65-a36a-2059b5210fc3` for release `4bdc413e…` and `827e2583-d121-4608-9e80-f99a3d7ec678` for release `4ffbae97…`. Their app files and artifact digest were identical; the latter changed only `release.json`. The primary URL was observed serving `4ffbae97…`. The approved Pages rollback API then returned HTTP 200 for target `8927927d-5ab5-4b65-a36a-2059b5210fc3`, and the primary URL was observed serving `4bdc413e…` again. These initial versions are retained as evidence only: their CSP blocks the IDL, so they are **not** future recovery targets for a healthy preview.

The operational rollback test used two **healthy** versions. Deployment `7823a285-1fff-4744-bcc3-1cef5dbf0997` served release `0860b5d…`, which differed from corrected release `26567e7…` only in `release.json`; both passed the same approved header and file checks. The primary URL was observed serving `0860b5d…`. The Pages rollback API returned HTTP 200 for the exact corrected target `e0b5976d-7927-4823-b972-ff66f5a9d451`. The primary URL then served `26567e7…`, and a fresh browser check again reached `DEGRADED READ ONLY / LIVE_DEVNET_READ_ONLY / READY_FOR_READ_ONLY_PREVIEW`. The corrected release is current. Future rollbacks must still verify a compatible package and repeat live smoke checks.

## References

- [Cloudflare Pages Direct Upload](https://developers.cloudflare.com/pages/get-started/direct-upload/)
- [Pages rollback behavior](https://developers.cloudflare.com/pages/configuration/rollbacks/) and [rollback API](https://developers.cloudflare.com/api/resources/pages/subresources/projects/subresources/deployments/methods/rollback/)
- [Cloudflare Pages Free limits](https://developers.cloudflare.com/pages/platform/limits/)
