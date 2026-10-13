pub mod commitment;
pub mod constants;
pub mod error;
pub mod escrow;
pub mod evidence;
pub mod execution;
pub mod identity;
pub mod identity_error;
pub mod instructions;
pub mod protocol;
pub mod signature;
pub mod state;
pub mod verification;
pub mod work_order;
pub mod work_order_account;
pub mod work_order_error;

use anchor_lang::prelude::*;

pub use commitment::*;
pub use constants::*;
pub use escrow::*;
pub use evidence::*;
pub use execution::*;
pub use identity::*;
pub use identity_error::*;
pub use instructions::*;
pub use protocol::*;
pub use signature::*;
pub use state::*;
pub use verification::*;
pub use work_order::*;
pub use work_order_account::*;
pub use work_order_error::*;

declare_id!("CeA1P1NSuPLUH31KsT4j3pZeBsknQZ3NSC6GUAqcsCLy");

pub mod settlement;
pub use settlement::*;

pub mod marketplace;
pub use marketplace::*;

#[program]
pub mod aerosettle {
    use super::*;

    pub fn initialize(ctx: Context<Initialize>) -> Result<()> {
        crate::instructions::initialize::handle_initialize(ctx)
    }

    pub fn increment(ctx: Context<Increment>) -> Result<()> {
        crate::instructions::increment::handle_increment(ctx)
    }

    pub fn initialize_protocol(
        ctx: Context<InitializeProtocol>,
        network_id: [u8; 32],
        deployment_id: [u8; 32],
    ) -> Result<()> {
        crate::instructions::initialize_protocol::handle_initialize_protocol(
            ctx,
            network_id,
            deployment_id,
        )
    }

    pub fn register_agent(
        ctx: Context<RegisterAgent>,
        agent_id: [u8; 32],
        signing_authority: Pubkey,
        agent_type: AgentType,
        capabilities: u64,
        metadata_hash: [u8; 32],
    ) -> Result<()> {
        crate::instructions::register_agent::handle_register_agent(
            ctx,
            agent_id,
            signing_authority,
            agent_type,
            capabilities,
            metadata_hash,
        )
    }

    pub fn suspend_agent(ctx: Context<ManageAgent>) -> Result<()> {
        crate::instructions::agent_lifecycle::handle_suspend_agent(ctx)
    }

    pub fn reactivate_agent(ctx: Context<ManageAgent>) -> Result<()> {
        crate::instructions::agent_lifecycle::handle_reactivate_agent(ctx)
    }

    pub fn revoke_agent(ctx: Context<ManageAgent>) -> Result<()> {
        crate::instructions::agent_lifecycle::handle_revoke_agent(ctx)
    }

    pub fn rotate_signing_authority(
        ctx: Context<OwnerManageAgent>,
        new_signing_authority: Pubkey,
    ) -> Result<()> {
        crate::instructions::agent_lifecycle::handle_rotate_signing_authority(
            ctx,
            new_signing_authority,
        )
    }

    pub fn update_agent_metadata(
        ctx: Context<OwnerManageAgent>,
        metadata_hash: [u8; 32],
    ) -> Result<()> {
        crate::instructions::agent_lifecycle::handle_update_agent_metadata(ctx, metadata_hash)
    }

    pub fn update_agent_capabilities(
        ctx: Context<OwnerManageAgent>,
        capabilities: u64,
    ) -> Result<()> {
        crate::instructions::agent_lifecycle::handle_update_agent_capabilities(ctx, capabilities)
    }

    pub fn transfer_agent_ownership(
        ctx: Context<TransferAgentOwnership>,
        new_signing_authority: Pubkey,
    ) -> Result<()> {
        crate::instructions::agent_lifecycle::handle_transfer_agent_ownership(
            ctx,
            new_signing_authority,
        )
    }

    pub fn create_work_order(
        ctx: Context<CreateWorkOrder>,
        args: CreateWorkOrderArgs,
    ) -> Result<()> {
        crate::instructions::create_work_order::handle_create_work_order(ctx, args)
    }

    pub fn claim_work_order(ctx: Context<ClaimWorkOrder>) -> Result<()> {
        crate::instructions::claim_work_order::handle_claim_work_order(ctx)
    }

    pub fn fund_work_order(ctx: Context<FundWorkOrder>) -> Result<()> {
        crate::instructions::fund_work_order::handle_fund_work_order(ctx)
    }

    pub fn submit_execution(
        ctx: Context<SubmitExecution>,
        args: SubmitExecutionArgs,
    ) -> Result<()> {
        crate::instructions::submit_execution::handle_submit_execution(ctx, args)
    }

    pub fn verify_execution(
        ctx: Context<VerifyExecution>,
        args: VerifyExecutionArgs,
    ) -> Result<()> {
        crate::instructions::verify_execution::handle_verify_execution(ctx, args)
    }

    pub fn settle_work_order(ctx: Context<SettleWorkOrder>) -> Result<()> {
        crate::instructions::settle_work_order::handle_settle_work_order(ctx)
    }

    pub fn close_settled_vault(ctx: Context<CloseSettledVault>) -> Result<()> {
        crate::instructions::close_settled_vault::handle_close_settled_vault(ctx)
    }
}
