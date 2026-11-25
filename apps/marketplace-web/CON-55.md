# CON-55 — Premium Devnet marketplace and verified agent catalog

## Status

Implementation is published on `feat/con-55-premium-devnet-agent-catalog` from the merged CON-59 baseline. The Devnet build is read-only and uses the existing Conatus visual system. The first approved release `e0b023220c7285f0f51a9e8d83cee9a43a9c3249c6cad04b044187a78b8fb159` was verified in a browser, then correctly returned HTTP 503 after its snapshot expired on 2026-11-21. On 2026-11-25 the user separately approved renewal release `dd3eacff186d64a1f724be6413badb1c7d5009597558ba8524ef7cb82105c425` for the same exact Cloudflare Free staging destination. Deployment `3136ccb9-021b-4e4d-a523-1989b636cf4a` is the canonical active deployment at [conatus-devnet-staging.pages.dev](https://conatus-devnet-staging.pages.dev/). Its finalized snapshot contains seven agents and seven WorkOrders and expires 2026-11-26 23:20:38 UTC. Renewal after that time again requires a new release and exact approval.

## Frontend audit and reuse

| Existing surface | Decision | Reason / CON-55 use |
| --- | --- | --- |
| `app/Landing.tsx` | Reuse visual grammar, hero asset, `landing.css`, `useLandingMotion`; do not import component | Component reads `atlas.ts` and presents invented agents, revenue, settlement speed and SDK execution examples. New `devnet/DevnetApp.tsx` retains the typography, palette, hero art, animation and navigation with factual Devnet copy. |
| `components/layout/AppShell.tsx` | Reuse shell CSS, structure, brand, sidebar and topbar in isolated `DevnetApp.tsx` | Original imports `WalletControl`, `NetworkProvider`, `CommandMenu` and `atlas.ts`; those modules are absent from the Devnet entry graph. |
| `app/Overview.tsx` | Reuse dashboard layout and card classes in `devnet/pages/Overview.tsx` | Original aggregates Atlas and Localnet data, including invented economic KPIs. New dashboard uses verified account counts, network and snapshot slot only. |
| `features/agents/AgentsPage.tsx`, `AgentDetail.tsx` | Reuse marketplace toolbar, card, grid and detail styles | Original merges `AGENTS` fixtures with RPC data and imports wallet connection. New pages render only validated CON-59 AgentAccount rows and verified detail responses. |
| `features/missions/MissionsPage.tsx`, `MissionDetail.tsx` | Reuse mission card and detail styles | Original maps WorkOrders into invented titles, rewards and matching counts, and imports funding/claim flows. New pages show only published fields; absent reward, beneficiary and settlement evidence remain unavailable. |
| `features/discover`, `fleet`, `planner` | Keep in Localnet experience | These surfaces depend on demo content, account actions or unsupported claims. No navigation to them exists in Devnet. |
| `components/ui` | Brand/Icon/PageHeader visual markup copied into `devnet/ui.tsx` | The shared UI module imports the Localnet i18n catalog and configuration; this would embed fixtures and localhost RPC strings. The Devnet copy is minimal, presentational and has no wallet dependencies. |
| `styles/tokens.css`, `global.css`, `landing.css`, `agents.css`, `missions.css` | Reused directly | Preserves established palette, typography, responsive rules, cards and motion. `devnet-premium.css` supplies only read-only page adaptation. |
| `devnet/DevnetReadOnlyApp.tsx` | Kept as `/status` | Technical identity, hashes, slots and reasons stay accessible without dominating the landing. |

The original Localnet entry (`bootstrap.tsx`, `AppRoutes`, `Providers`) remains separate. The Devnet entry (`devnet-bootstrap.tsx`) imports `DevnetApp`, `DevnetDataProvider`, isolated i18n/UI, approved manifest and read-only adapter. It never imports the wallet provider, Localnet RPC or transaction SDK. `verify-build.mjs` rejects those strings in **all emitted JavaScript chunks**. The main JavaScript chunk is approximately 270 kB before gzip; feature pages are lazy chunks of about 3–5 kB each.

## Data contract and trust

The browser verifies the independently pinned CON-35 manifest and IDL against official Devnet RPC. It then reads `/api/ready`, `/api/v1/agents` and `/api/v1/workorders`. The adapter checks network, genesis, program ID, IDL hash, binary hash, deployment ID, test mint, mint authority, SPL Token Program, decimals, finalized commitment, provider, slot range, observed slot, generation/expiry times, snapshot hash, advisory flags and non-executable status. Every page must match the same snapshot and slot context. Pagination is bounded to ten 50-record pages per resource, matching the CON-59 maximum of 500. A missing page, repeated cursor, changed total or cross-page identity mismatch fails closed.

`catalog.ts` validates and whitelists AgentAccount and WorkOrder fields. It strips arbitrary profile, revenue, country, image and hardware metadata rather than rendering them. Detail routes call `/api/v1/agents/:pubkey` or `/api/v1/workorders/:pubkey`, revalidate the same provenance and compare the parsed record with the listed row. `/status` additionally checks `/api/v1/network` and `/api/v1/program`. No browser code performs an account scan or sends a Solana transaction.

Source labels are explicit: `ONCHAIN_VERIFIED` is used only for fields from the finalized release snapshot. `AGENT_CARD_SIGNED_CLAIM`, `UNVERIFIED_METADATA` and `DEMO_ONLY` are described in the catalog legend but are not joined into this catalog. An Agent Card cannot grant financial authority. Capability bits are on-chain declarations; they do not independently prove hardware or performance. The CON-59 public WorkOrder schema does not expose amount, beneficiary or settlement evidence, so those values are not inferred or displayed. Solana Explorer links always pin `cluster=devnet`.

## Routes and experience

- `/`: premium Conatus landing with original hero art and motion, bilingual navigation and clear Devnet/read-only provenance.
- `/app`: dashboard with verified agent/WorkOrder counts, network and snapshot slot; no synthetic economic chart.
- `/app/agents`, `/app/agents/:pubkey`: search, status/capability filters, deterministic sorting, grid/list, local pagination and verified identity fields.
- `/app/missions`, `/app/missions/:pubkey`: read-only WorkOrder listing and detail with state, creator, protocol, test mint and capability bits.
- `/status`: RPC/API/index state, approved IDs and hashes, slot range, expiry and retry.

The landing and shell remain usable when the index is missing. No stale accounts are shown as current. A provider poll checks for a renewed release every two minutes, while a timer clears catalog data at its exact expiry. The UI distinguishes loading, verified, stale, API unavailable and network/manifest mismatch states. It never falls back to Atlas or Localnet fixtures. English and Spanish are available in the isolated Devnet language provider. The reused motion helper respects reduced-motion preference.

## Validation and evidence

- `npm test --prefix apps/marketplace-web`: 72 tests passed. New cases cover independent manifest/IDL pins, wrong network/program/mint, cross-page provenance, pagination, arbitrary metadata stripping, missing records, API 503, and search/filter/sort over published fields.
- `npm test --prefix packages/marketplace-sdk`: 36 passed; `npm test --prefix packages/transaction-sdk`: 10 passed. Python Devnet integration: 32 passed; security: 7 passed. Workflow policy passed.
- `npm run build:localnet --prefix apps/marketplace-web`: passed, preserving the separate Localnet experience.
- `npm run build:devnet --prefix apps/marketplace-web` and `verify-build.mjs devnet`: passed; no wallet/transaction imports, Localnet RPC or Atlas agent fixtures in emitted JavaScript.
- Browser preview first demonstrated that the landing and AppShell remained usable while the old CON-59 snapshot returned HTTP 503. After the approved deployment, the public browser rendered `INDEX VERIFIED`, a 7/7 dashboard, all seven agents and WorkOrders, page 2 of each listing, matching account details, `/status` with `RPC_VERIFIED`, `API_VERIFIED` and `INDEX_FRESH`, and disabled financial actions. Mission status filtering and list mode passed. Spanish navigation and mobile drawer passed. At 390 px mobile and 768 px tablet widths, document scroll width equaled viewport width. Screenshots were captured and visually inspected in the browser session; no standalone screenshot file was exported.
- `evidence/con55/browser-e2e.json` records the live browser observations, `evidence/con55/public-probe.json` records 23 public HTTPS/API/security checks, and `evidence/con55/deployment-evidence.json` records the exact approved release, hashes and Cloudflare deployment ID. The release source commit is `22c1d848262f327837ebb3572876307f23b0e65c`; its artifact digest is `ffbee8031b7850d8de19a5d19ca40b222661a45f1cf802dcebc796185977b206` and snapshot SHA-256 is `1c167101e4e80ab5f64d3f2e36820b67bdb7d60bc981a423c69426cea360edd1`.
- Renewal evidence is in `evidence/con55/renewal-2026-11-25.json` and `evidence/con55/public-probe-renewal-2026-11-25.json`. The renewal source commit is `5435b21370337ebfa65ff20166983ba1092b0140`, artifact digest `da33d4113434575e6d9d1941b3d9e3d6c8f3533f1e231c36fb2681a101f6a0d2`, snapshot SHA-256 `fde2c3ce5504c9529015663534bf45c180487b2e05788026af411dc98e155e5d`, and canonical deployment ID `3136ccb9-021b-4e4d-a523-1989b636cf4a`. The JavaScript/CSS bundle SHA-256 `f5050de5a65374f4b4f285b67893fec7463ba6c0e01270e5cb99a508873ab4fa` is unchanged from the browser-tested first release; the renewal changes the release-bound snapshot and Worker bytes. The second 23-check public probe passed. No Solana transaction was sent.
- All seven PR workflows on `5435b21370337ebfa65ff20166983ba1092b0140` passed: CON-34, CON-36, CON-46, CON-53, CON-55, CON-58/59 and CON-59. The CON-36 read-only job needed one retry after official Devnet RPC returned HTTP 429; the retry passed without changing verification logic.
- `evidence/con55/historical-schema-proof.json` validates the previous CON-59 finalized snapshot's **historical schema** (7 AgentAccounts and 7 WorkOrders). This file is test evidence only and must never be presented as current.
- `.github/workflows/con55-premium-devnet-marketplace.yml` runs web/SDK, Python integration/security, typecheck, Devnet build, security bundle gate and `git diff --check` with read-only permissions and no PR deployment path.
- CON-46 Gitleaks flagged the approved public SPL test mint address in the new `devnet-manifest.ts` as a generic API key. The address is the same public mint already in the CON-35/58/59 evidence, not a credential. `tools/security/gitleaks-baseline.json` now contains only that exact commit/file/rule/line fingerprint; no detection rule was disabled. The full-history scan and seven security tests pass locally with this narrow correction.

## Remaining gates

1. Review the PR and its CI after the post-deployment evidence commit. Do not merge or close Jira automatically.
2. Renew the snapshot before its 24-hour expiry using the same human approval gate. The site will correctly return HTTP 503 after expiry until a renewed release is authorized and published.
3. Standalone screenshot files were not exported from the browser session. The tested browser states and viewport measurements are recorded in `evidence/con55/browser-e2e.json`; if image files are a mandatory review artifact, capture them separately before merge.

The preview remains Cloudflare Pages Free, `pages.dev`, read-only, Devnet-only and non-financial. The CON-59 Free-tier quota risk acceptance applies only to this staging preview and does not grant authority for transactions or a new deployment.
