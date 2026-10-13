use anchor_lang::prelude::*;

use crate::{
    AgentAccount, IdentityError, ProtocolConfig, SubmitExecutionArgs, WorkOrderAccount,
    WorkOrderError, WorkOrderStatus, AEROSETTLE_PROTOCOL_VERSION, AGENT_SEED, PROTOCOL_CONFIG_SEED,
    WORK_ORDER_SEED,
};

#[derive(Accounts)]
pub struct SubmitExecution<'info> {
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
                @ WorkOrderError::InvalidProtocolConfig
    )]
    pub work_order: Account<'info, WorkOrderAccount>,

    #[account(
        mut,
        seeds = [
            AGENT_SEED,
            protocol_config.key().as_ref(),
            agent_account.agent_id.as_ref()
        ],
        bump = agent_account.bump,
        has_one =
            protocol_config
                @ WorkOrderError::InvalidProtocolConfig,
        constraint =
            work_order.claimed_agent
                == agent_account.key()
                @ WorkOrderError::ClaimedAgentMismatch,
        constraint =
            agent_account.signing_authority
                == agent_signer.key()
                @ WorkOrderError::InvalidAgentSigner
    )]
    pub agent_account: Account<'info, AgentAccount>,

    pub agent_signer: Signer<'info>,
}

pub fn handle_submit_execution(
    ctx: Context<SubmitExecution>,
    args: SubmitExecutionArgs,
) -> Result<()> {
    let now = Clock::get()?.unix_timestamp;

    let order = &ctx.accounts.work_order;

    require!(
        order.status == WorkOrderStatus::Claimed,
        WorkOrderError::WorkOrderNotClaimed
    );

    require!(
        ctx.accounts.agent_account.is_active(),
        WorkOrderError::AgentNotActive
    );

    require!(
        args.execution_receipt_hash != [0u8; 32],
        WorkOrderError::InvalidExecutionReceiptHash
    );

    require!(
        args.evidence_manifest_hash != [0u8; 32],
        WorkOrderError::InvalidEvidenceManifestHash
    );

    require!(
        order.has_required_evidence(args.provided_evidence),
        WorkOrderError::MissingRequiredEvidence
    );

    require!(
        args.execution_started_at <= args.execution_ended_at,
        WorkOrderError::InvalidExecutionTimeRange
    );

    require!(
        args.execution_started_at >= order.claimed_at,
        WorkOrderError::ExecutionStartedBeforeClaim
    );

    require!(
        args.execution_ended_at <= order.execution_deadline,
        WorkOrderError::ExecutionAfterDeadline
    );

    require!(
        args.execution_ended_at <= now,
        WorkOrderError::ExecutionEndInFuture
    );

    require!(
        now <= order.verification_deadline,
        WorkOrderError::SubmissionAfterVerificationDeadline
    );

    require!(
        args.signature_sequence == ctx.accounts.agent_account.next_signature_sequence,
        WorkOrderError::InvalidSignatureSequence
    );

    let next_sequence = ctx
        .accounts
        .agent_account
        .next_signature_sequence
        .checked_add(1)
        .ok_or(WorkOrderError::SignatureSequenceOverflow)?;

    // All validations have passed. From here the transition and nonce
    // consumption happen atomically inside this Solana transaction.
    let order = &mut ctx.accounts.work_order;

    order.execution_receipt_hash = args.execution_receipt_hash;

    order.evidence_manifest_hash = args.evidence_manifest_hash;

    order.execution_signer = ctx.accounts.agent_signer.key();

    order.execution_sequence = args.signature_sequence;

    order.provided_evidence = args.provided_evidence;

    order.execution_started_at = args.execution_started_at;

    order.execution_ended_at = args.execution_ended_at;

    order.submitted_at = now;

    order.status = WorkOrderStatus::Submitted;

    ctx.accounts.agent_account.next_signature_sequence = next_sequence;

    msg!(
        "WorkOrder {} execution submitted by agent {}; sequence={}",
        order.key(),
        ctx.accounts.agent_account.key(),
        args.signature_sequence
    );

    Ok(())
}
