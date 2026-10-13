use anchor_lang::prelude::*;

use crate::{IdentityError, ProtocolConfig, AEROSETTLE_PROTOCOL_VERSION, PROTOCOL_CONFIG_SEED};

#[derive(Accounts)]
pub struct InitializeProtocol<'info> {
    #[account(
        init,
        payer = authority,
        space = ProtocolConfig::SPACE,
        seeds = [PROTOCOL_CONFIG_SEED],
        bump
    )]
    pub protocol_config: Account<'info, ProtocolConfig>,

    #[account(mut)]
    pub authority: Signer<'info>,

    pub system_program: Program<'info, System>,
}

pub fn handle_initialize_protocol(
    ctx: Context<InitializeProtocol>,
    network_id: [u8; 32],
    deployment_id: [u8; 32],
) -> Result<()> {
    require!(network_id != [0u8; 32], IdentityError::InvalidNetworkId);

    require!(
        deployment_id != [0u8; 32],
        IdentityError::InvalidDeploymentId
    );

    let now = Clock::get()?.unix_timestamp;

    let config = &mut ctx.accounts.protocol_config;

    config.protocol_version = AEROSETTLE_PROTOCOL_VERSION;

    config.authority = ctx.accounts.authority.key();

    config.network_id = network_id;

    config.program_id = *ctx.program_id;

    config.deployment_id = deployment_id;

    config.bump = ctx.bumps.protocol_config;

    config.agent_count = 0;
    config.paused = false;
    config.created_at = now;

    msg!(
        "AeroSettle protocol initialized: version={}",
        AEROSETTLE_PROTOCOL_VERSION
    );

    Ok(())
}
