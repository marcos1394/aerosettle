# CON-35 Devnet deployment evidence

The program compiled from source commit `b95c7bfd7c760558a0a7b87ee25b0a4b67aa6f14` was deployed to Solana Devnet under the approved deployment ID `06c7dfa7528460969a5ca1e8bd001f9c9f1f1f0df3d69fe36649e413e0b14ae6`. The [public evidence record](devnet-deployment.json) contains the exact program, transaction, slot, authority, ProgramData address and artifact hashes.

| Check | Verified value |
| --- | --- |
| Genesis | `EtWTRABZaYq6iMfeYKouRu166VU2xqa1wcaWoxPkrZBG` |
| Program ID | `CeA1P1NSuPLUH31KsT4j3pZeBsknQZ3NSC6GUAqcsCLy` |
| Upgrade authority | `DdHrtAxE5SwcVQUgoKRzoWatZ5yw9UdtBQnRwBizPK2D` |
| Finalized transaction | [`3FdinSa8F8VBsP3a1fM6so64K9X7QBUbR5Ay7z6Zv32mXQJx27SWhGddPK67pnLN5KBEYTkX25DsQgZWLdWfVDEA`](https://explorer.solana.com/tx/3FdinSa8F8VBsP3a1fM6so64K9X7QBUbR5Ay7z6Zv32mXQJx27SWhGddPK67pnLN5KBEYTkX25DsQgZWLdWfVDEA?cluster=devnet) |
| Slot | `516258865` |
| ProgramData | `7kYZxnujXJ9sKGhG9CbDwThJECb693WvvqVFHGmNSsrr` |
| SBF SHA-256 | `6cf3412c55c38e91b2ba0039aea24d58782c5db0d18759ffdab1c88788cdc3a2` |
| IDL SHA-256 | `a6e436aa1c6468b4f518b742e40a2664e38dcdf7bc1419e53e1624444888e15d` |
| ProtocolConfig PDA | `C8HiYzxKjRcDFHoWSZ84smUsxnMQ7ipxPnQ96GK5qZVn` (uninitialized) |

The exact approved [SBF](artifacts/aerosettle.so), [IDL](artifacts/aerosettle-idl.json), [reproducibility attestation](artifacts/reproducibility.json) and [prepared manifest](artifacts/manifest.json) are public in this directory. Two isolated local builds matched byte for byte. The local `post-deploy-verification` command checked finalized signature status and transaction contents through JSON-RPC, canonical ProgramData, upgrade authority, exact deployed SBF bytes with zero padding, and the ProtocolConfig PDA status. It produced a sealed `VERIFIED` manifest. The PR workflow repeats those checks independently against the public exact artifact and uploads its result.

The earlier [Linux CI preparation run](https://github.com/marcos1394/aerosettle/actions/runs/40627013459) passed its own two-build comparison and generated the same IDL, but its SBF SHA-256 was `584ca1c7024673baf0cb716573fe62dc13e5301dc3973fd6c18cecc1726cb451`. GitHub Actions checked out a temporary PR merge commit `7127038be7799e3d101d6a7da7967582fd04e5fc` for that run. Neither its binary hash nor its deployment ID matches the approved macOS build from source commit `b95c7bfd7c760558a0a7b87ee25b0a4b67aa6f14`. The preparation workflow now checks out the PR head for future runs. Cross-platform byte equality is not claimed. The deployed binary is verified against the exact public artifact above.

The initial CLI attempt over the public RPC created a buffer but exhausted write retries. The buffer remained under the intended upgrade authority, so the same approved deployment was resumed using Agave's TPU transport. The final deployment consumed the buffer. No Mainnet transaction was sent. ProtocolConfig is not initialized, so this record proves the deployed program and authority, not a Devnet WorkOrder cycle.
