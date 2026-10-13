use anchor_lang::prelude::*;

use crate::{
    AgentAccount, IdentityError, ProtocolConfig, WorkOrderAccount, WorkOrderError, WorkOrderStatus,
    AEROSETTLE_PROTOCOL_VERSION, AGENT_SEED, PROTOCOL_CONFIG_SEED, WORK_ORDER_SEED,
};

#[derive(Accounts)]
pub struct ClaimWorkOrder<'info> {
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
            agent_account.signing_authority
                == agent_signer.key()
                @ WorkOrderError::InvalidAgentSigner
    )]
    pub agent_account: Account<'info, AgentAccount>,

    pub agent_signer: Signer<'info>,
}

pub fn handle_claim_work_order(ctx: Context<ClaimWorkOrder>) -> Result<()> {
    let now = Clock::get()?.unix_timestamp;

    let order = &mut ctx.accounts.work_order;

    require!(
        order.status == WorkOrderStatus::Open,
        WorkOrderError::WorkOrderNotOpen
    );

    require!(
        now <= order.execution_deadline,
        WorkOrderError::WorkOrderExpired
    );

    let agent = &ctx.accounts.agent_account;

    require!(agent.is_active(), WorkOrderError::AgentNotActive);

    let physical_agent = agent.as_physical_agent();

    require!(
        order.is_compatible_with(&physical_agent),
        WorkOrderError::IncompatibleAgent
    );

    order.status = WorkOrderStatus::Claimed;

    order.claimed_agent = agent.key();
    order.settlement_beneficiary = ctx.accounts.agent_account.owner;

    order.claimed_at = now;

    msg!("WorkOrder {} claimed by agent {}", order.key(), agent.key());

    Ok(())
}
