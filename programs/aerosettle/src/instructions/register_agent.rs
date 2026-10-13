use anchor_lang::prelude::*;

use crate::{
    AgentAccount, AgentStatus, AgentType, IdentityError, ProtocolConfig,
    AEROSETTLE_PROTOCOL_VERSION, AGENT_SEED, PROTOCOL_CONFIG_SEED,
};

#[derive(Accounts)]
#[instruction(agent_id: [u8; 32])]
pub struct RegisterAgent<'info> {
    #[account(
        mut,
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
        payer = owner,
        space = AgentAccount::SPACE,
        seeds = [
            AGENT_SEED,
            protocol_config.key().as_ref(),
            agent_id.as_ref()
        ],
        bump
    )]
    pub agent_account: Account<'info, AgentAccount>,

    #[account(mut)]
    pub owner: Signer<'info>,

    pub system_program: Program<'info, System>,
}

#[allow(clippy::too_many_arguments)]
pub fn handle_register_agent(
    ctx: Context<RegisterAgent>,
    agent_id: [u8; 32],
    signing_authority: Pubkey,
    agent_type: AgentType,
    capabilities: u64,
    metadata_hash: [u8; 32],
) -> Result<()> {
    require!(agent_id != [0u8; 32], IdentityError::InvalidAgentId);

    require!(
        signing_authority != Pubkey::default(),
        IdentityError::InvalidSigningAuthority
    );

    require!(capabilities != 0, IdentityError::NoCapabilities);

    require!(
        metadata_hash != [0u8; 32],
        IdentityError::InvalidMetadataHash
    );

    let now = Clock::get()?.unix_timestamp;

    let config_key = ctx.accounts.protocol_config.key();

    let current_count = ctx.accounts.protocol_config.agent_count;

    ctx.accounts.protocol_config.agent_count = current_count
        .checked_add(1)
        .ok_or(IdentityError::AgentCounterOverflow)?;

    let agent = &mut ctx.accounts.agent_account;

    agent.protocol_version = AEROSETTLE_PROTOCOL_VERSION;

    agent.protocol_config = config_key;

    agent.agent_id = agent_id;

    agent.owner = ctx.accounts.owner.key();

    agent.signing_authority = signing_authority;

    agent.agent_type = agent_type;

    agent.capabilities = capabilities;

    agent.metadata_hash = metadata_hash;

    agent.status = AgentStatus::Active;

    agent.next_signature_sequence = 0;

    agent.bump = ctx.bumps.agent_account;

    agent.registered_at = now;

    msg!(
        "AeroSettle agent registered: {}",
        ctx.accounts.agent_account.key()
    );

    Ok(())
}
