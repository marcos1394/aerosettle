use anchor_lang::prelude::*;

use anchor_spl::token_interface::{self, Mint, TokenAccount, TokenInterface, TransferChecked};

use crate::{
    IdentityError, ProtocolConfig, WorkOrderAccount, WorkOrderError, WorkOrderStatus,
    AEROSETTLE_PROTOCOL_VERSION, ESCROW_VAULT_SEED, PROTOCOL_CONFIG_SEED, WORK_ORDER_SEED,
};

#[derive(Accounts)]
pub struct FundWorkOrder<'info> {
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
        has_one =
            creator
                @ WorkOrderError::UnauthorizedCreator,
        constraint =
            work_order.status
                == WorkOrderStatus::Draft
                @ WorkOrderError::WorkOrderNotDraft
    )]
    pub work_order: Account<'info, WorkOrderAccount>,

    #[account(mut)]
    pub creator: Signer<'info>,

    #[account(
        constraint =
            mint.key() == work_order.token_mint
                @ WorkOrderError::InvalidTokenMint,
        constraint =
            *mint.to_account_info().owner
                == token_program.key()
                @ WorkOrderError::InvalidTokenProgram
    )]
    pub mint: InterfaceAccount<'info, Mint>,

    #[account(
        mut,
        token::mint = mint,
        token::authority = creator,
        token::token_program = token_program,
        constraint =
            creator_token_account.amount
                >= work_order.total_amount
                @ WorkOrderError::InsufficientEscrowFunds
    )]
    pub creator_token_account: InterfaceAccount<'info, TokenAccount>,

    /// Program-controlled token vault.
    ///
    /// Its address and its token authority are the same PDA.
    #[account(
        init,
        payer = creator,
        token::mint = mint,
        token::authority = escrow_vault,
        token::token_program = token_program,
        seeds = [
            ESCROW_VAULT_SEED,
            work_order.key().as_ref()
        ],
        bump
    )]
    pub escrow_vault: InterfaceAccount<'info, TokenAccount>,

    pub token_program: Interface<'info, TokenInterface>,

    pub system_program: Program<'info, System>,
}

pub fn handle_fund_work_order(ctx: Context<FundWorkOrder>) -> Result<()> {
    let now = Clock::get()?.unix_timestamp;

    require!(
        now <= ctx.accounts.work_order.execution_deadline,
        WorkOrderError::WorkOrderExpired
    );

    let amount = ctx.accounts.work_order.total_amount;

    let decimals = ctx.accounts.mint.decimals;

    let cpi_accounts = TransferChecked {
        from: ctx.accounts.creator_token_account.to_account_info(),

        mint: ctx.accounts.mint.to_account_info(),

        to: ctx.accounts.escrow_vault.to_account_info(),

        authority: ctx.accounts.creator.to_account_info(),
    };

    let cpi_context = CpiContext::new(ctx.accounts.token_program.key(), cpi_accounts);

    token_interface::transfer_checked(cpi_context, amount, decimals)?;

    // CPI changed token state. Reload before inspecting it.
    ctx.accounts.escrow_vault.reload()?;

    // This deliberately rejects fee-on-transfer assets.
    //
    // AeroSettle v1 requires that the vault receives exactly the
    // economic amount declared in SettlementTerms.
    require!(
        ctx.accounts.escrow_vault.amount == amount,
        WorkOrderError::EscrowFundingMismatch
    );

    let order = &mut ctx.accounts.work_order;

    order.escrow_vault = ctx.accounts.escrow_vault.key();

    order.token_program = ctx.accounts.token_program.key();

    order.funded_at = now;

    // This is the ONLY transition implemented so far
    // that makes a WorkOrder claimable.
    order.status = WorkOrderStatus::Open;

    msg!(
        "WorkOrder {} funded with {} base units; status=Open",
        order.key(),
        amount
    );

    Ok(())
}
