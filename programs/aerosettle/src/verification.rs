use anchor_lang::prelude::*;

use crate::VerificationStatus;

/// Data supplied by the authorized verifier.
///
/// `verified_at` is part of the signed/canonical attestation rather than
/// being generated from the current Solana Clock. The program still checks
/// that it is not in the future and falls inside the valid verification
/// window.
#[derive(AnchorSerialize, AnchorDeserialize, Clone, Debug, PartialEq, Eq)]
pub struct VerifyExecutionArgs {
    pub verification_attestation_hash: [u8; 32],
    pub status: VerificationStatus,
    pub completion_bps: u16,
    pub verified_at: i64,
}
