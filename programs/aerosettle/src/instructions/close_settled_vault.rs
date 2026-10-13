use anchor_lang::prelude::*;
use anchor_spl::token::{self, CloseAccount, Mint, Token, TokenAccount, TransferChecked};

use crate::{
    IdentityError, ProtocolConfig, WorkOrderAccount, WorkOrderError, WorkOrderStatus,
    AEROSETTLE_PROTOCOL_VERSION, ESCROW_VAULT_SEED, PROTOCOL_CONFIG_SEED, WORK_ORDER_SEED,
};

/// Reclaim SPL account rent after successful settlement.
///
/// Anyone may execute this instruction; the refund recipients are bound to
/// on-chain WorkOrder fields, never supplied as arbitrary destinations.
#[derive(Accounts)]
pub struct CloseSettledVault<'info> {
    #[account(
        seeds = [PROTOCOL_CONFIG_SEED],
        bump = protocol_config.bump,
        constraint = protocol_config.protocol_version == AEROSETTLE_PROTOCOL_VERSION
            @ IdentityError::UnsupportedProtocolVersion,
    )]
    pub protocol_config: Account<'info, ProtocolConfig>,

    #[account(
        seeds = [
            WORK_ORDER_SEED,
            protocol_config.key().as_ref(),
            work_order.creator.as_ref(),
            work_order.work_order_id.as_ref()
        ],
        bump = work_order.bump,
        has_one = protocol_config @ WorkOrderError::InvalidProtocolConfig,
    )]
    pub work_order: Account<'info, WorkOrderAccount>,

    #[account(
        mut,
        seeds = [ESCROW_VAULT_SEED, work_order.key().as_ref()],
        bump,
        constraint = work_order.escrow_vault == escrow_vault.key()
            @ WorkOrderError::SettlementInvalidVault,
        constraint = escrow_vault.owner == escrow_vault.key()
            @ WorkOrderError::SettlementInvalidVaultAuthority,
        constraint = escrow_vault.mint == work_order.token_mint
            @ WorkOrderError::SettlementInvalidMint,
    )]
    pub escrow_vault: Account<'info, TokenAccount>,

    #[account(address = work_order.token_mint @ WorkOrderError::SettlementInvalidMint)]
    pub mint: Account<'info, Mint>,

    /// CHECK: Only receives the reclaimed lamports. The address must exactly
    /// equal the persisted WorkOrder.creator; it never signs this instruction.
    #[account(
        mut,
        address = work_order.creator @ WorkOrderError::SettlementInvalidCreatorRefund,
    )]
    pub creator: UncheckedAccount<'info>,

    #[account(
        mut,
        constraint = creator_refund_token_account.owner == work_order.creator
            @ WorkOrderError::SettlementInvalidCreatorRefund,
        constraint = creator_refund_token_account.mint == work_order.token_mint
            @ WorkOrderError::SettlementInvalidMint,
    )]
    pub creator_refund_token_account: Account<'info, TokenAccount>,

    #[account(
        constraint = token_program.key() == work_order.token_program
            @ WorkOrderError::SettlementInvalidTokenProgram,
    )]
    pub token_program: Program<'info, Token>,
}

pub fn handle_close_settled_vault(ctx: Context<CloseSettledVault>) -> Result<()> {
    require!(
        ctx.accounts.work_order.status == WorkOrderStatus::Settled,
        WorkOrderError::SettlementNotSettled
    );

    require_keys_neq!(
        ctx.accounts.escrow_vault.key(),
        ctx.accounts.creator_refund_token_account.key(),
        WorkOrderError::SettlementInvalidDestination
    );

    let work_order_key = ctx.accounts.work_order.key();
    let bump_seed = [ctx.bumps.escrow_vault];
    let signer_seeds: &[&[u8]] = &[ESCROW_VAULT_SEED, work_order_key.as_ref(), &bump_seed];
    let signer = &[signer_seeds];
    let token_program = ctx.accounts.token_program.key();

    // Tokens sent after settlement cannot be allowed to block reclamation.
    // Refund them to the original creator, never to an arbitrary caller.
    let leftover = ctx.accounts.escrow_vault.amount;
    if leftover > 0 {
        let before = ctx.accounts.creator_refund_token_account.amount;
        let expected = before
            .checked_add(leftover)
            .ok_or(error!(WorkOrderError::SettlementArithmeticOverflow))?;

        let transfer = TransferChecked {
            from: ctx.accounts.escrow_vault.to_account_info(),
            mint: ctx.accounts.mint.to_account_info(),
            to: ctx.accounts.creator_refund_token_account.to_account_info(),
            authority: ctx.accounts.escrow_vault.to_account_info(),
        };
        token::transfer_checked(
            CpiContext::new_with_signer(token_program, transfer, signer),
            leftover,
            ctx.accounts.mint.decimals,
        )?;

        ctx.accounts.escrow_vault.reload()?;
        ctx.accounts.creator_refund_token_account.reload()?;
        require!(
            ctx.accounts.creator_refund_token_account.amount == expected,
            WorkOrderError::SettlementBalanceMismatch
        );
    }

    require!(
        ctx.accounts.escrow_vault.amount == 0,
        WorkOrderError::SettlementBalanceMismatch
    );

    // CloseAccount transfers the vault's rent-exempt lamports to the
    // persisted creator. It is authorized by the same self-owned PDA.
    let close = CloseAccount {
        account: ctx.accounts.escrow_vault.to_account_info(),
        destination: ctx.accounts.creator.to_account_info(),
        authority: ctx.accounts.escrow_vault.to_account_info(),
    };
    token::close_account(CpiContext::new_with_signer(token_program, close, signer))?;

    msg!(
        "AeroSettle escrow vault closed for work order {}; post-settlement refund={}",
        work_order_key,
        leftover
    );
    Ok(())
}
