# CON-55 — Premium Devnet marketplace and verified agent catalog

## Status

Implementation is prepared on `feat/con-55-premium-devnet-agent-catalog` from the merged CON-59 baseline. The Devnet build is read-only and uses the existing Conatus visual system. This branch does **not** publish to Cloudflare Pages. A new CON-55 release ID and exact destination require separate human approval. The currently public CON-59 snapshot has expired; its API correctly returns 503. Until a new approved release is published, the public site cannot demonstrate a current catalog.

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
- Browser preview: landing and AppShell were inspected at desktop and 390 px mobile width. English and Spanish navigation, mobile drawer, readable unavailable-state card and persistent landing passed. The local preview could not show a current catalog: the public API snapshot expired, and the canonical Pages API intentionally rejects a localhost origin. Browser captures were inspected in the development session; no screenshot file is committed.
- `evidence/con55/browser-e2e.json` records the preview observations and explicitly leaves current-catalog and detail E2E pending an authorized release. It does not claim screenshot artifacts.
- `evidence/con55/historical-schema-proof.json` validates the previous CON-59 finalized snapshot's **historical schema** (7 AgentAccounts and 7 WorkOrders). This file is test evidence only and must never be presented as current.
- `.github/workflows/con55-premium-devnet-marketplace.yml` runs web/SDK, Python integration/security, typecheck, Devnet build, security bundle gate and `git diff --check` with read-only permissions and no PR deployment path.

## Remaining gates

1. Prepare a fresh finalized Devnet snapshot and release from a clean final commit; record exact hashes and release ID.
2. Obtain human approval for the exact release and Cloudflare account/project/URL before upload. No deployment is authorized by this document.
3. After publication, verify a **current** 7/7 catalog (or the real current counts), agent and WorkOrder details, filters, responsive screenshots, CSP/headers and recovery from stale to fresh in a browser. Capture reviewable screenshot artifacts.
4. Review the PR and CI. Do not merge or close Jira automatically.

The preview remains Cloudflare Pages Free, `pages.dev`, read-only, Devnet-only and non-financial. The CON-59 Free-tier quota risk acceptance applies only to this staging preview and does not grant authority for transactions or a new deployment.
