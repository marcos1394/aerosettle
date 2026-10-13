use anchor_lang::prelude::*;

use crate::{
    AgentAccount, AgentStatus, IdentityError, ProtocolConfig, AEROSETTLE_PROTOCOL_VERSION,
    AGENT_SEED, PROTOCOL_CONFIG_SEED,
};

/// Context for lifecycle operations where either the owner or protocol
/// authority may be authorized depending on the transition.
#[derive(Accounts)]
pub struct ManageAgent<'info> {
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
            AGENT_SEED,
            protocol_config.key().as_ref(),
            agent_account.agent_id.as_ref()
        ],
        bump = agent_account.bump,
        has_one =
            protocol_config
                @ IdentityError::InvalidProtocolConfig
    )]
    pub agent_account: Account<'info, AgentAccount>,

    pub actor: Signer<'info>,
}

/// Operations reserved to the current agent owner.
#[derive(Accounts)]
pub struct OwnerManageAgent<'info> {
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
            AGENT_SEED,
            protocol_config.key().as_ref(),
            agent_account.agent_id.as_ref()
        ],
        bump = agent_account.bump,
        has_one =
            protocol_config
                @ IdentityError::InvalidProtocolConfig,
        constraint =
            agent_account.owner == owner.key()
                @ IdentityError::UnauthorizedActor
    )]
    pub agent_account: Account<'info, AgentAccount>,

    pub owner: Signer<'info>,
}

/// Ownership transfer requires explicit acceptance by both parties.
#[derive(Accounts)]
pub struct TransferAgentOwnership<'info> {
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
            AGENT_SEED,
            protocol_config.key().as_ref(),
            agent_account.agent_id.as_ref()
        ],
        bump = agent_account.bump,
        has_one =
            protocol_config
                @ IdentityError::InvalidProtocolConfig,
        constraint =
            agent_account.owner == current_owner.key()
                @ IdentityError::UnauthorizedActor
    )]
    pub agent_account: Account<'info, AgentAccount>,

    pub current_owner: Signer<'info>,

    /// The receiving owner must explicitly sign the transfer.
    pub new_owner: Signer<'info>,
}

pub fn handle_suspend_agent(ctx: Context<ManageAgent>) -> Result<()> {
    let actor = ctx.accounts.actor.key();

    let protocol_authority = ctx.accounts.protocol_config.authority;

    let agent = &mut ctx.accounts.agent_account;

    require!(!agent.is_revoked(), IdentityError::AgentRevoked);

    if actor == protocol_authority {
        require!(
            agent.status != AgentStatus::AdminSuspended,
            IdentityError::InvalidStatusTransition
        );

        agent.status = AgentStatus::AdminSuspended;

        return Ok(());
    }

    if actor == agent.owner {
        require!(
            agent.status == AgentStatus::Active,
            IdentityError::InvalidStatusTransition
        );

        agent.status = AgentStatus::OwnerSuspended;

        return Ok(());
    }

    err!(IdentityError::UnauthorizedActor)
}

pub fn handle_reactivate_agent(ctx: Context<ManageAgent>) -> Result<()> {
    let actor = ctx.accounts.actor.key();

    let protocol_authority = ctx.accounts.protocol_config.authority;

    let agent = &mut ctx.accounts.agent_account;

    require!(!agent.is_revoked(), IdentityError::AgentRevoked);

    match agent.status {
        AgentStatus::OwnerSuspended => {
            require!(actor == agent.owner, IdentityError::UnauthorizedActor);

            agent.status = AgentStatus::Active;
        }

        AgentStatus::AdminSuspended => {
            require!(
                actor == protocol_authority,
                IdentityError::UnauthorizedActor
            );

            agent.status = AgentStatus::Active;
        }

        AgentStatus::Active | AgentStatus::Revoked => {
            return err!(IdentityError::InvalidStatusTransition);
        }
    }

    Ok(())
}

pub fn handle_revoke_agent(ctx: Context<ManageAgent>) -> Result<()> {
    require!(
        ctx.accounts.actor.key() == ctx.accounts.protocol_config.authority,
        IdentityError::UnauthorizedActor
    );

    let agent = &mut ctx.accounts.agent_account;

    require!(!agent.is_revoked(), IdentityError::AgentRevoked);

    agent.status = AgentStatus::Revoked;

    Ok(())
}

pub fn handle_rotate_signing_authority(
    ctx: Context<OwnerManageAgent>,
    new_signing_authority: Pubkey,
) -> Result<()> {
    let agent = &mut ctx.accounts.agent_account;

    require!(!agent.is_revoked(), IdentityError::AgentRevoked);

    require!(
        new_signing_authority != Pubkey::default(),
        IdentityError::InvalidSigningAuthority
    );

    require!(
        new_signing_authority != agent.signing_authority,
        IdentityError::NoOpUpdate
    );

    agent.signing_authority = new_signing_authority;

    Ok(())
}

pub fn handle_update_agent_metadata(
    ctx: Context<OwnerManageAgent>,
    metadata_hash: [u8; 32],
) -> Result<()> {
    let agent = &mut ctx.accounts.agent_account;

    require!(!agent.is_revoked(), IdentityError::AgentRevoked);

    require!(
        metadata_hash != [0u8; 32],
        IdentityError::InvalidMetadataHash
    );

    require!(
        metadata_hash != agent.metadata_hash,
        IdentityError::NoOpUpdate
    );

    agent.metadata_hash = metadata_hash;

    Ok(())
}

pub fn handle_update_agent_capabilities(
    ctx: Context<OwnerManageAgent>,
    capabilities: u64,
) -> Result<()> {
    let agent = &mut ctx.accounts.agent_account;

    require!(!agent.is_revoked(), IdentityError::AgentRevoked);

    require!(capabilities != 0, IdentityError::NoCapabilities);

    require!(
        capabilities != agent.capabilities,
        IdentityError::NoOpUpdate
    );

    agent.capabilities = capabilities;

    Ok(())
}

pub fn handle_transfer_agent_ownership(
    ctx: Context<TransferAgentOwnership>,
    new_signing_authority: Pubkey,
) -> Result<()> {
    let agent = &mut ctx.accounts.agent_account;

    require!(!agent.is_revoked(), IdentityError::AgentRevoked);

    let new_owner = ctx.accounts.new_owner.key();

    require!(new_owner != agent.owner, IdentityError::InvalidNewOwner);

    require!(
        new_signing_authority != Pubkey::default(),
        IdentityError::InvalidSigningAuthority
    );

    // Ownership and device authorization move atomically.
    //
    // The previous owner's device key therefore cannot continue
    // authorizing new work after the transfer.
    agent.owner = new_owner;

    agent.signing_authority = new_signing_authority;

    Ok(())
}
