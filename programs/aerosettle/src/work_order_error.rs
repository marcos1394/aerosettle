use anchor_lang::prelude::*;

#[error_code]
pub enum WorkOrderError {
    #[msg("Work order ID cannot be zero.")]
    InvalidWorkOrderId,

    #[msg("Work order manifest hash cannot be zero.")]
    InvalidManifestHash,

    #[msg("Work order must require at least one capability.")]
    NoRequiredCapabilities,

    #[msg("Work order must require at least one evidence type.")]
    NoEvidenceRequirements,

    #[msg("Settlement token mint cannot be the default public key.")]
    InvalidTokenMint,

    #[msg("Verifier cannot be the default public key.")]
    InvalidVerifier,

    #[msg("Settlement amount must be greater than zero.")]
    InvalidSettlementAmount,

    #[msg("Execution deadline must be before verification deadline.")]
    InvalidDeadline,

    #[msg("Execution deadline must be in the future.")]
    ExecutionDeadlineInPast,

    #[msg("Work order is not open for claims.")]
    WorkOrderNotOpen,

    #[msg("Work order execution deadline has passed.")]
    WorkOrderExpired,

    #[msg("Agent is not active.")]
    AgentNotActive,

    #[msg("Agent does not satisfy the required capabilities.")]
    IncompatibleAgent,

    #[msg("Signer is not the registered device signing authority.")]
    InvalidAgentSigner,

    #[msg("Work order does not belong to the supplied protocol configuration.")]
    InvalidProtocolConfig,

    #[msg("Work order is not in Draft state.")]
    WorkOrderNotDraft,

    #[msg("Only the WorkOrder creator may fund escrow.")]
    UnauthorizedCreator,

    #[msg("Token program does not own the supplied mint.")]
    InvalidTokenProgram,

    #[msg("Creator token account has insufficient funds.")]
    InsufficientEscrowFunds,

    #[msg("Escrow vault did not receive the exact required amount.")]
    EscrowFundingMismatch,

    #[msg("Work order is not in Claimed state.")]
    WorkOrderNotClaimed,

    #[msg("Agent is not the agent that claimed this WorkOrder.")]
    ClaimedAgentMismatch,

    #[msg("Execution receipt hash cannot be zero.")]
    InvalidExecutionReceiptHash,

    #[msg("Evidence manifest hash cannot be zero.")]
    InvalidEvidenceManifestHash,

    #[msg("Submitted evidence does not satisfy WorkOrder requirements.")]
    MissingRequiredEvidence,

    #[msg("Execution time range is invalid.")]
    InvalidExecutionTimeRange,

    #[msg("Execution cannot begin before the WorkOrder was claimed.")]
    ExecutionStartedBeforeClaim,

    #[msg("Execution completed after the WorkOrder execution deadline.")]
    ExecutionAfterDeadline,

    #[msg("Execution end timestamp cannot be in the future.")]
    ExecutionEndInFuture,

    #[msg("Execution submission occurred after the verification deadline.")]
    SubmissionAfterVerificationDeadline,

    #[msg("Signature sequence does not match the agent's expected sequence.")]
    InvalidSignatureSequence,

    #[msg("Agent signature sequence overflow.")]
    SignatureSequenceOverflow,

    #[msg("Work order is not in Submitted state.")]
    WorkOrderNotSubmitted,

    #[msg("Signer is not the verifier assigned to this WorkOrder.")]
    UnauthorizedVerifier,

    #[msg("Verification attestation hash cannot be zero.")]
    InvalidVerificationAttestationHash,

    #[msg("Verification decision contains an invalid completion percentage.")]
    InvalidVerificationCompletion,

    #[msg("Verification timestamp precedes physical execution completion.")]
    VerificationBeforeExecutionEnd,

    #[msg("Verification timestamp cannot be in the future.")]
    VerificationTimestampInFuture,

    #[msg("Verification occurred after the WorkOrder verification deadline.")]
    VerificationAfterDeadline,

    #[msg("Verification attestation commitment does not match the supplied hash.")]
    VerificationCommitmentMismatch,

    #[msg("Settlement validation failed: SettlementNotVerified")]
    SettlementNotVerified,
    #[msg("Settlement validation failed: SettlementMissingAttestation")]
    SettlementMissingAttestation,
    #[msg("Settlement validation failed: SettlementMissingVerification")]
    SettlementMissingVerification,
    #[msg("Settlement validation failed: SettlementInvalidCompletion")]
    SettlementInvalidCompletion,
    #[msg("Settlement validation failed: SettlementInvalidBeneficiary")]
    SettlementInvalidBeneficiary,
    #[msg("Settlement validation failed: SettlementInvalidCreatorRefund")]
    SettlementInvalidCreatorRefund,
    #[msg("Settlement validation failed: SettlementInvalidVaultAuthority")]
    SettlementInvalidVaultAuthority,
    #[msg("Settlement validation failed: SettlementInvalidVault")]
    SettlementInvalidVault,
    #[msg("Settlement validation failed: SettlementInvalidMint")]
    SettlementInvalidMint,
    #[msg("Settlement validation failed: SettlementInvalidTokenProgram")]
    SettlementInvalidTokenProgram,
    #[msg("Settlement validation failed: SettlementInvalidDestination")]
    SettlementInvalidDestination,
    #[msg("Settlement validation failed: SettlementInsufficientVault")]
    SettlementInsufficientVault,
    #[msg("Settlement validation failed: SettlementArithmeticOverflow")]
    SettlementArithmeticOverflow,
    #[msg("Settlement validation failed: SettlementBalanceMismatch")]
    SettlementBalanceMismatch,
    #[msg("WorkOrder must be Settled before its token vault can be closed.")]
    SettlementNotSettled,
}
