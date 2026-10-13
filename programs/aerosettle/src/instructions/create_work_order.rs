use anchor_lang::prelude::*;

use crate::{
    CreateWorkOrderArgs, IdentityError, ProtocolConfig, WorkOrderAccount, WorkOrderError,
    WorkOrderStatus, AEROSETTLE_PROTOCOL_VERSION, PROTOCOL_CONFIG_SEED, WORK_ORDER_SEED,
};

#[derive(Accounts)]
#[instruction(args: CreateWorkOrderArgs)]
pub struct CreateWorkOrder<'info> {
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
        init,
        payer = creator,
        space = WorkOrderAccount::SPACE,
        seeds = [
            WORK_ORDER_SEED,
            protocol_config.key().as_ref(),
            creator.key().as_ref(),
            args.work_order_id.as_ref()
        ],
        bump
    )]
    pub work_order: Account<'info, WorkOrderAccount>,

    #[account(mut)]
    pub creator: Signer<'info>,

    pub system_program: Program<'info, System>,
}

pub fn handle_create_work_order(
    ctx: Context<CreateWorkOrder>,
    args: CreateWorkOrderArgs,
) -> Result<()> {
    require!(
        args.work_order_id != [0u8; 32],
        WorkOrderError::InvalidWorkOrderId
    );

    require!(
        args.required_capabilities != 0,
        WorkOrderError::NoRequiredCapabilities
    );

    require!(
        args.evidence_requirements != 0,
        WorkOrderError::NoEvidenceRequirements
    );

    require!(
        args.manifest_hash != [0u8; 32],
        WorkOrderError::InvalidManifestHash
    );

    require!(
        args.settlement.token_mint != Pubkey::default(),
        WorkOrderError::InvalidTokenMint
    );

    require!(
        args.settlement.verifier != Pubkey::default(),
        WorkOrderError::InvalidVerifier
    );

    require!(
        args.settlement.total_amount > 0,
        WorkOrderError::InvalidSettlementAmount
    );

    require!(
        args.execution_deadline < args.verification_deadline,
        WorkOrderError::InvalidDeadline
    );

    let now = Clock::get()?.unix_timestamp;

    require!(
        args.execution_deadline > now,
        WorkOrderError::ExecutionDeadlineInPast
    );

    let order = &mut ctx.accounts.work_order;

    order.protocol_version = AEROSETTLE_PROTOCOL_VERSION;

    order.protocol_config = ctx.accounts.protocol_config.key();

    order.work_order_id = args.work_order_id;

    order.creator = ctx.accounts.creator.key();

    order.work_type = args.work_type;

    order.required_capabilities = args.required_capabilities;

    order.evidence_requirements = args.evidence_requirements;

    order.manifest_hash = args.manifest_hash;

    order.token_mint = args.settlement.token_mint;

    order.total_amount = args.settlement.total_amount;

    order.payment_model = args.settlement.payment_model;

    order.verifier = args.settlement.verifier;

    order.execution_deadline = args.execution_deadline;

    order.verification_deadline = args.verification_deadline;

    // Critical invariant:
    // creation does NOT make work economically claimable.
    order.status = WorkOrderStatus::Draft;

    order.claimed_agent = Pubkey::default();
    order.settlement_beneficiary = Pubkey::default();

    order.execution_receipt_hash = [0u8; 32];

    order.evidence_manifest_hash = [0u8; 32];

    order.verification_attestation_hash = [0u8; 32];

    order.completion_bps = 0;

    order.created_at = now;
    order.claimed_at = 0;
    order.submitted_at = 0;
    order.verified_at = 0;
    order.settled_at = 0;

    order.bump = ctx.bumps.work_order;

    msg!(
        "AeroSettle WorkOrder created as Draft: {}",
        ctx.accounts.work_order.key()
    );

    Ok(())
}
