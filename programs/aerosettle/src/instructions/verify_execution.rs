use anchor_lang::prelude::*;

use crate::{
    CanonicalCommitment, IdentityError, ProtocolConfig, VerificationAttestation,
    VerifyExecutionArgs, WorkOrderAccount, WorkOrderError, WorkOrderStatus,
    AEROSETTLE_PROTOCOL_VERSION, PROTOCOL_CONFIG_SEED, WORK_ORDER_SEED,
};

#[derive(Accounts)]
pub struct VerifyExecution<'info> {
    #[account(
        seeds = [PROTOCOL_CONFIG_SEED],
        bump = protocol_config.bump,
        constraint =
            protocol_config.protocol_version
                == AEROSETTLE_PROTOCOL_VERSION
                @ IdentityError::UnsupportedProtocolVersion,
        constraint =
            !protocol_config.paused
                @ IdentityError::ProtocolPaused
    )]
    pub protocol_config: Account<'info, ProtocolConfig>,

    #[account(
        mut,
        seeds = [
            WORK_ORDER_SEED,
            protocol_config.key().as_ref(),
            work_order.creator.as_ref(),
            work_order.work_order_id.as_ref()
        ],
        bump = work_order.bump,
        has_one =
            protocol_config
                @ WorkOrderError::InvalidProtocolConfig,
        constraint =
            work_order.verifier
                == verifier.key()
                @ WorkOrderError::UnauthorizedVerifier
    )]
    pub work_order: Account<'info, WorkOrderAccount>,

    pub verifier: Signer<'info>,
}

pub fn handle_verify_execution(
    ctx: Context<VerifyExecution>,
    args: VerifyExecutionArgs,
) -> Result<()> {
    let now = Clock::get()?.unix_timestamp;

    let order = &ctx.accounts.work_order;

    require!(
        order.status == WorkOrderStatus::Submitted,
        WorkOrderError::WorkOrderNotSubmitted
    );

    require!(
        now <= order.verification_deadline,
        WorkOrderError::VerificationAfterDeadline
    );

    require!(
        args.verification_attestation_hash != [0u8; 32],
        WorkOrderError::InvalidVerificationAttestationHash
    );

    require!(
        args.verified_at >= order.execution_ended_at,
        WorkOrderError::VerificationBeforeExecutionEnd
    );

    require!(
        args.verified_at <= now,
        WorkOrderError::VerificationTimestampInFuture
    );

    require!(
        args.verified_at <= order.verification_deadline,
        WorkOrderError::VerificationAfterDeadline
    );

    // Reconstruct the exact protocol-level attestation that the verifier
    // claims to have committed to.
    let attestation = VerificationAttestation::new(
        order.work_order_id,
        order.execution_receipt_hash,
        order.evidence_manifest_hash,
        ctx.accounts.verifier.key(),
        args.status,
        args.completion_bps,
        args.verified_at,
    );

    require!(
        attestation.has_valid_completion(),
        WorkOrderError::InvalidVerificationCompletion
    );

    let expected_hash = attestation.commitment_hash();

    require!(
        expected_hash == args.verification_attestation_hash,
        WorkOrderError::VerificationCommitmentMismatch
    );

    let order = &mut ctx.accounts.work_order;

    order.verification_attestation_hash = expected_hash;

    order.verification_status = Some(args.status);

    order.completion_bps = args.completion_bps;

    order.verified_at = args.verified_at;

    order.status = WorkOrderStatus::Verified;

    msg!(
        "WorkOrder {} verified; completion_bps={}",
        order.key(),
        order.completion_bps
    );

    Ok(())
}
