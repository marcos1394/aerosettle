# CON-54 — Secure Wallet Standard identity in the Devnet marketplace

## Scope and baseline

This branch starts from `origin/master` merge `58fe919420b6b803c1439c01ecb4bd31068edaa8` (CON-55). It adds wallet discovery and public-account identity to the isolated premium Devnet entry. The Localnet `Providers.tsx` and `WalletControl.tsx` remain separate and unchanged. Public agent and WorkOrder browsing never requires a wallet. No signing, transaction creation, broadcasting, funding, settlement or economic authorization is enabled by a connection.

## Dependencies and architecture

The Devnet entry uses the Wallet Standard registry directly: `@wallet-standard/app` **1.1.1** for `getWallets()` and `@wallet-standard/base` **1.1.1** for its wallet/account interfaces. Both are Apache-2.0 packages already present in the lockfile as transitive dependencies before this change; they are now explicit exact dependencies. This avoids importing the Localnet Solana wallet-adapter React provider and its transaction surface into the Devnet bundle. The Wallet Standard project defines the [app registry and registration events](https://github.com/wallet-standard/wallet-standard/blob/master/packages/core/app/src/wallets.ts) and [wallet/account interfaces](https://github.com/wallet-standard/wallet-standard/blob/master/packages/core/base/src/wallet.ts).

`src/devnet/wallet/standard.ts` owns a small identity state machine and validates advertised wallets before offering connection. It requires Wallet Standard 1.0, `standard:connect`, `standard:disconnect`, `standard:events` and announced `solana:devnet` support. A wallet's name is rendered as escaped text; its untrusted icon is never loaded. A public account must have a canonical 32-byte base58 address matching the 32-byte `publicKey`, and its chains must include Devnet and remain a subset of the wallet's announced chains. The UI never requests a seed, private key, message signature or transaction signature.

`WalletIdentitySession` discovers registration/unregistration, connects only after a user click, exposes manual reconnection, handles `standard:events` account/chain/feature changes, invalidates changed identities, allows explicit choice among multiple authorized accounts, and discards late async responses after disconnect or wallet removal. It does not persist wallet choice, accounts or permissions. Disconnect clears local identity even if the extension's cleanup call fails; an extension may retain its own authorization. No automatic prompt or silent connection occurs on page load.

The React context and accessible dialog are in `src/devnet/wallet/WalletIdentity.tsx` and `WalletConnect.tsx`. A Devnet-only stylesheet adapts the premium header and mobile dialog. The mock browser capture in `evidence/con54/browser-smoke.json` proves the visible flow at 390 px; its two PNG files are explicitly labeled **simulated**. Phantom and Solflare are listed when they register compatible Wallet Standard objects. No real Phantom or Solflare extension was available in the test browser, so a real-extension connect claim is intentionally absent.

## Network and permissions

The app still independently pins Devnet genesis `EtWTRABZaYq6iMfeYKouRu166VU2xqa1wcaWoxPkrZBG`, program `CeA1P1NSuPLUH31KsT4j3pZeBsknQZ3NSC6GUAqcsCLy`, approved IDL and test mint through CON-53/55 verification. Announced `wallet.chains` and `account.chains` describe **support**, not the active chain. Standard connection exposes no portable active-network proof, so a connected account remains `NETWORK_UNVERIFIED` even when it supports `solana:devnet`. An account or chain announcement without Devnet is rejected as `WRONG_NETWORK`. A chain change invalidates the selected identity, and an incompatible announcement blocks reconnect until a compatible change is reported. No Mainnet path exists.

`permissions.ts` sets `PUBLIC_READ`, `WALLET_CONNECT` and informational `TRANSACTION_PREVIEW` only. `WALLET_IDENTITY_VERIFIED`, `TRANSACTION_SIGNING`, `TRANSACTION_SUBMISSION` and `FINANCIAL_AUTHORIZATION` remain false. The preview shows the approved network, program and test mint, while transaction type, fee, requested authority and recipient are `INSUFFICIENT_DATA`. It makes no RPC fee estimate and offers no action button. A future transaction HU must prove the wallet's active chain and define separate human review and signing policy.

## Validation and threat model

- Positive mocks: Phantom and Solflare discovery, explicit connect, manual reconnect, public key validation, multiple-account selection, disconnect and mobile layout.
- Negative mocks: Mainnet-only announcement, unsupported lifecycle feature, malformed/mismatched public key, authorization rejection, account and network change, duplicate events, wallet removal, stale connection response and malicious advertised name. Error messages use fixed codes rather than extension-supplied detail.
- The Devnet build gate requires only `standard:connect`, `standard:disconnect` and `standard:events`. It continues to reject wallet-adapter providers, signing/send features, Mainnet strings, Localnet fixtures and the existing forbidden financial paths. The Localnet build remains separate.
- The local mock browser loaded a 390 px viewport with `scrollWidth=390`, found the simulated option, made zero connection calls before the click, connected once, showed `NETWORK_UNVERIFIED`, exposed zero signing buttons, disconnected once and sent zero Solana transactions. See `evidence/con54/browser-smoke.json` and the two PNG screenshots.
- Offline `npm audit` on the web lockfile reported zero cached advisories; CI security gates provide the online check. This offline result alone is not a claim that future advisories cannot appear.

## Release boundary and remaining work

The existing Cloudflare Pages release remains unchanged. This PR does **not** deploy. A new Devnet release needs a verified snapshot, source commit, artifact hashes, release ID and separate approval for the exact Cloudflare account/project/URL before any Direct Upload. The CON-59 snapshot renewal is independent; the current release snapshot expires 2026-11-26 23:20:38 UTC. No wallet with real funds, Solana transaction or production infrastructure is used. Review and real Phantom/Solflare extension testing remain before any staging publication. Do not merge or close Jira automatically.
