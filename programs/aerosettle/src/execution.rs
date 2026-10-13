use anchor_lang::prelude::*;

/// Data committed on-chain when a physical agent finishes execution.
///
/// Large telemetry/images/video remain off-chain. AeroSettle persists
/// their cryptographic commitments and enough metadata to enforce the
/// WorkOrder lifecycle.
#[derive(AnchorSerialize, AnchorDeserialize, Clone, Debug, PartialEq, Eq)]
pub struct SubmitExecutionArgs {
    /// Commitment produced by ExecutionReceipt::commitment_hash().
    pub execution_receipt_hash: [u8; 32],

    /// Commitment produced by EvidenceManifest::commitment_hash().
    pub evidence_manifest_hash: [u8; 32],

    /// EvidenceRequirement bitmask actually supplied.
    pub provided_evidence: u64,

    /// Physical execution interval.
    pub execution_started_at: i64,
    pub execution_ended_at: i64,

    /// Must equal AgentAccount.next_signature_sequence.
    ///
    /// Successful submission atomically consumes this sequence.
    pub signature_sequence: u64,
}
