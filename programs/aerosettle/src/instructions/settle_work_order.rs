use anchor_lang::prelude::*;

use anchor_spl::token::{self, Mint, Token, TokenAccount, TransferChecked};

use crate::{
    allocation_for_verification, verified_operator_payout, IdentityError, ProtocolConfig,
    WorkOrderAccount, WorkOrderError, WorkOrderStatus, AEROSETTLE_PROTOCOL_VERSION,
    ESCROW_VAULT_SEED, PROTOCOL_CONFIG_SEED, WORK_ORDER_SEED,
};

#[derive(Accounts)]
pub struct SettleWorkOrder<'info> {
    #[account(
        seeds = [PROTOCOL_CONFIG_SEED],
        bump = protocol_config.bump,
        constraint =
            protocol_config.protocol_version
                == AEROSETTLE_PROTOCOL_VERSION
                @ IdentityError::UnsupportedProtocolVersion
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
        has_one = protocol_config
            @ WorkOrderError::InvalidProtocolConfig
    )]
    pub work_order: Account<'info, WorkOrderAccount>,

    #[account(
        mut,
        seeds = [
            ESCROW_VAULT_SEED,
            work_order.key().as_ref()
        ],
        bump,
        constraint =
            escrow_vault.owner == escrow_vault.key()
                @ WorkOrderError::SettlementInvalidVaultAuthority,
        constraint =
            escrow_vault.mint == mint.key()
                @ WorkOrderError::SettlementInvalidMint
    )]
    pub escrow_vault: Account<'info, TokenAccount>,

    #[account(
        constraint =
            mint.key() == work_order.token_mint
                @ WorkOrderError::SettlementInvalidMint
    )]
    pub mint: Account<'info, Mint>,

    #[account(
        mut,
        constraint =
            operator_token_account.owner
                == work_order.settlement_beneficiary
                @ WorkOrderError::SettlementInvalidBeneficiary,
        constraint =
            operator_token_account.mint == mint.key()
                @ WorkOrderError::SettlementInvalidMint
    )]
    pub operator_token_account: Account<'info, TokenAccount>,

    #[account(
        mut,
        constraint =
            creator_refund_token_account.owner
                == work_order.creator
                @ WorkOrderError::SettlementInvalidCreatorRefund,
        constraint =
            creator_refund_token_account.mint == mint.key()
                @ WorkOrderError::SettlementInvalidMint
    )]
    pub creator_refund_token_account: Account<'info, TokenAccount>,

    pub token_program: Program<'info, Token>,
}

pub fn handle_settle_work_order(ctx: Context<SettleWorkOrder>) -> Result<()> {
    let order = &ctx.accounts.work_order;

    require!(
        order.status == WorkOrderStatus::Verified,
        WorkOrderError::SettlementNotVerified
    );

    require!(
        order.verification_attestation_hash != [0u8; 32],
        WorkOrderError::SettlementMissingAttestation
    );

    require!(
        order.settlement_beneficiary != Pubkey::default(),
        WorkOrderError::SettlementInvalidBeneficiary
    );

    require_keys_eq!(
        order.escrow_vault,
        ctx.accounts.escrow_vault.key(),
        WorkOrderError::SettlementInvalidVault
    );

    require_keys_eq!(
        order.token_program,
        ctx.accounts.token_program.key(),
        WorkOrderError::SettlementInvalidTokenProgram
    );

    let verification_status = order
        .verification_status
        .as_ref()
        .ok_or(error!(WorkOrderError::SettlementMissingVerification))?;

    let operator_payout = verified_operator_payout(
        &order.payment_model,
        verification_status,
        order.total_amount,
        order.completion_bps,
    )
    .ok_or(error!(WorkOrderError::SettlementInvalidCompletion))?;

    let allocation =
        allocation_for_verification(verification_status, order.total_amount, operator_payout)
            .ok_or(error!(WorkOrderError::SettlementArithmeticOverflow))?;

    require!(
        allocation.conserves_value(order.total_amount),
        WorkOrderError::SettlementArithmeticOverflow
    );

    let vault_balance = ctx.accounts.escrow_vault.amount;

    require!(
        vault_balance >= order.total_amount,
        WorkOrderError::SettlementInsufficientVault
    );

    // A third party could donate tokens to the vault.
    // Preserve the agent's contracted payout and return
    // the surplus to the WorkOrder creator.
    let surplus = vault_balance
        .checked_sub(order.total_amount)
        .ok_or(error!(WorkOrderError::SettlementArithmeticOverflow))?;

    let creator_refund = allocation
        .creator_refund
        .checked_add(surplus)
        .ok_or(error!(WorkOrderError::SettlementArithmeticOverflow))?;

    let total_distribution = allocation
        .operator_amount
        .checked_add(creator_refund)
        .ok_or(error!(WorkOrderError::SettlementArithmeticOverflow))?;

    require!(
        total_distribution == vault_balance,
        WorkOrderError::SettlementArithmeticOverflow
    );

    let operator_key = ctx.accounts.operator_token_account.key();

    let creator_refund_key = ctx.accounts.creator_refund_token_account.key();

    let vault_key = ctx.accounts.escrow_vault.key();

    require!(
        operator_key != vault_key && creator_refund_key != vault_key,
        WorkOrderError::SettlementInvalidDestination
    );

    let same_destination = operator_key == creator_refund_key;

    let operator_before = ctx.accounts.operator_token_account.amount;

    let creator_before = ctx.accounts.creator_refund_token_account.amount;

    // Calculate expected recipient balances before
    // performing either CPI.
    let expected_operator = operator_before
        .checked_add(if same_destination {
            vault_balance
        } else {
            allocation.operator_amount
        })
        .ok_or(error!(WorkOrderError::SettlementArithmeticOverflow))?;

    let expected_creator = if same_destination {
        expected_operator
    } else {
        creator_before
            .checked_add(creator_refund)
            .ok_or(error!(WorkOrderError::SettlementArithmeticOverflow))?
    };

    let work_order_key = ctx.accounts.work_order.key();
    let bump = [ctx.bumps.escrow_vault];

    let signer_seeds: &[&[u8]] = &[ESCROW_VAULT_SEED, work_order_key.as_ref(), &bump];

    let signer = &[signer_seeds];

    let token_program = ctx.accounts.token_program.key();

    let decimals = ctx.accounts.mint.decimals;

    // CPI 1: pay the economic beneficiary frozen at claim.
    if allocation.operator_amount > 0 {
        let transfer = TransferChecked {
            from: ctx.accounts.escrow_vault.to_account_info(),
            mint: ctx.accounts.mint.to_account_info(),
            to: ctx.accounts.operator_token_account.to_account_info(),
            authority: ctx.accounts.escrow_vault.to_account_info(),
        };

        token::transfer_checked(
            CpiContext::new_with_signer(token_program, transfer, signer),
            allocation.operator_amount,
            decimals,
        )?;
    }

    // CPI 2: refund unearned escrow plus any surplus.
    if creator_refund > 0 {
        let transfer = TransferChecked {
            from: ctx.accounts.escrow_vault.to_account_info(),
            mint: ctx.accounts.mint.to_account_info(),
            to: ctx.accounts.creator_refund_token_account.to_account_info(),
            authority: ctx.accounts.escrow_vault.to_account_info(),
        };

        token::transfer_checked(
            CpiContext::new_with_signer(token_program, transfer, signer),
            creator_refund,
            decimals,
        )?;
    }

    // Verify the actual SPL Token balances.
    ctx.accounts.escrow_vault.reload()?;
    ctx.accounts.operator_token_account.reload()?;
    ctx.accounts.creator_refund_token_account.reload()?;

    require!(
        ctx.accounts.escrow_vault.amount == 0,
        WorkOrderError::SettlementBalanceMismatch
    );

    require!(
        ctx.accounts.operator_token_account.amount == expected_operator,
        WorkOrderError::SettlementBalanceMismatch
    );

    require!(
        ctx.accounts.creator_refund_token_account.amount == expected_creator,
        WorkOrderError::SettlementBalanceMismatch
    );

    // Mark settled only after both CPIs and all balance
    // validations succeed.
    let order = &mut ctx.accounts.work_order;

    order.status = WorkOrderStatus::Settled;
    order.settled_at = Clock::get()?.unix_timestamp;

    msg!(
        "AeroSettle settlement completed: operator={}, creator_refund={}, surplus={}",
        allocation.operator_amount,
        creator_refund,
        surplus
    );

    Ok(())
}
