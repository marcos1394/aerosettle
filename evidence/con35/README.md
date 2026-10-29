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

The approved binary and IDL came from the [successful two-build preparation run](https://github.com/marcos1394/aerosettle/actions/runs/40627013459). The local `post-deploy-verification` command checked finalized signature status and transaction contents through JSON-RPC, canonical ProgramData, upgrade authority, exact deployed SBF bytes with zero padding, and the ProtocolConfig PDA status. It produced a sealed `VERIFIED` manifest. The PR workflow repeats those checks independently using the preparation artifact and this public evidence record; its run and uploaded result are linked from PR #18.

The initial CLI attempt over the public RPC created a buffer but exhausted write retries. The buffer remained under the intended upgrade authority, so the same approved deployment was resumed using Agave's TPU transport. The final deployment consumed the buffer. No Mainnet transaction was sent. ProtocolConfig is not initialized, so this record proves the deployed program and authority, not a Devnet WorkOrder cycle.
