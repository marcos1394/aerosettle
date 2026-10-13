use anchor_lang::prelude::*;

use crate::{AgentType, DeploymentContext, PhysicalAgent};

/// Singleton configuration PDA for one AeroSettle deployment.
pub const PROTOCOL_CONFIG_SEED: &[u8] = b"protocol_config";

/// Prefix used for Physical Agent identity PDAs.
pub const AGENT_SEED: &[u8] = b"agent";

/// Persistent configuration for one AeroSettle deployment.
///
/// PDA:
/// [b"protocol_config"]
#[account]
pub struct ProtocolConfig {
    pub protocol_version: u8,

    /// Administrative authority for this deployment.
    pub authority: Pubkey,

    /// Cluster/network identity.
    pub network_id: [u8; 32],

    /// Program ID this deployment belongs to.
    pub program_id: Pubkey,

    /// Unique identity for this deployment instance.
    pub deployment_id: [u8; 32],

    pub bump: u8,

    /// Number of agents successfully registered.
    pub agent_count: u64,

    /// Emergency/configuration pause flag.
    pub paused: bool,

    /// Unix timestamp when the deployment was initialized.
    pub created_at: i64,
}

impl ProtocolConfig {
    /// Serialized account body, excluding Anchor discriminator.
    pub const DATA_LEN: usize = 1  // protocol_version
        + 32 // authority
        + 32 // network_id
        + 32 // program_id
        + 32 // deployment_id
        + 1  // bump
        + 8  // agent_count
        + 1  // paused
        + 8; // created_at

    /// Anchor account discriminator + data.
    pub const SPACE: usize = 8 + Self::DATA_LEN;

    pub fn deployment_context(&self) -> DeploymentContext {
        DeploymentContext::new(self.network_id, self.program_id, self.deployment_id)
    }
}

/// Lifecycle state of a registered physical agent.
///
/// Variant order is persistent protocol data.
/// Never reorder existing variants in protocol v1.
#[derive(AnchorSerialize, AnchorDeserialize, Clone, Copy, Debug, PartialEq, Eq)]
pub enum AgentStatus {
    Active,
    OwnerSuspended,
    AdminSuspended,
    Revoked,
}

/// Persistent on-chain identity of one intelligent machine.
///
/// PDA:
/// [
///     b"agent",
///     protocol_config,
///     agent_id
/// ]
///
/// Notice that owner is intentionally NOT part of the PDA.
///
/// This allows ownership to change later without changing the
/// machine's canonical AeroSettle identity.
#[account]
pub struct AgentAccount {
    pub protocol_version: u8,

    /// Deployment this agent belongs to.
    pub protocol_config: Pubkey,

    /// Stable machine/application identity.
    pub agent_id: [u8; 32],

    /// Economic/legal owner of the agent.
    pub owner: Pubkey,

    /// Public key used by the physical device to sign execution data.
    ///
    /// It is deliberately separate from owner.
    pub signing_authority: Pubkey,

    pub agent_type: AgentType,

    /// Capability bitset defined by AeroSettle protocol v1.
    pub capabilities: u64,

    /// Commitment of canonical off-chain Agent Manifest.
    pub metadata_hash: [u8; 32],

    pub status: AgentStatus,

    /// Monotonic sequence reserved for replay protection.
    ///
    /// Later instructions will derive/consume signature nonces using
    /// this sequence.
    pub next_signature_sequence: u64,

    pub bump: u8,

    pub registered_at: i64,
}

impl AgentAccount {
    pub const DATA_LEN: usize = 1  // protocol_version
        + 32 // protocol_config
        + 32 // agent_id
        + 32 // owner
        + 32 // signing_authority
        + 1  // AgentType
        + 8  // capabilities
        + 32 // metadata_hash
        + 1  // AgentStatus
        + 8  // next_signature_sequence
        + 1  // bump
        + 8; // registered_at

    pub const SPACE: usize = 8 + Self::DATA_LEN;

    pub const fn is_active(&self) -> bool {
        matches!(self.status, AgentStatus::Active)
    }

    pub const fn is_suspended(&self) -> bool {
        matches!(
            self.status,
            AgentStatus::OwnerSuspended | AgentStatus::AdminSuspended
        )
    }

    pub const fn is_revoked(&self) -> bool {
        matches!(self.status, AgentStatus::Revoked)
    }

    /// Protocol-level projection used by matching/economic logic.
    pub fn as_physical_agent(&self) -> PhysicalAgent {
        PhysicalAgent::new(
            self.agent_id,
            self.owner,
            self.agent_type,
            self.capabilities,
            self.metadata_hash,
        )
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::{Capability, AEROSETTLE_PROTOCOL_VERSION};

    fn pubkey(value: u8) -> Pubkey {
        Pubkey::new_from_array([value; 32])
    }

    #[test]
    fn account_sizes_are_stable() {
        assert_eq!(ProtocolConfig::DATA_LEN, 147);

        assert_eq!(ProtocolConfig::SPACE, 155);

        assert_eq!(AgentAccount::DATA_LEN, 188);

        assert_eq!(AgentAccount::SPACE, 196);
    }

    #[test]
    fn protocol_config_builds_deployment_context() {
        let config = ProtocolConfig {
            protocol_version: AEROSETTLE_PROTOCOL_VERSION,
            authority: pubkey(1),
            network_id: [2u8; 32],
            program_id: pubkey(3),
            deployment_id: [4u8; 32],
            bump: 250,
            agent_count: 0,
            paused: false,
            created_at: 100,
        };

        let context = config.deployment_context();

        assert_eq!(context.network_id, config.network_id);

        assert_eq!(context.program_id, config.program_id);

        assert_eq!(context.deployment_id, config.deployment_id);
    }

    #[test]
    fn agent_projects_to_protocol_physical_agent() {
        let account = AgentAccount {
            protocol_version: AEROSETTLE_PROTOCOL_VERSION,
            protocol_config: pubkey(1),
            agent_id: [2u8; 32],
            owner: pubkey(3),
            signing_authority: pubkey(4),
            agent_type: AgentType::Drone,
            capabilities: Capability::AerialMobility.bit()
                | Capability::Gps.bit()
                | Capability::Telemetry.bit(),
            metadata_hash: [5u8; 32],
            status: AgentStatus::Active,
            next_signature_sequence: 0,
            bump: 200,
            registered_at: 100,
        };

        assert!(account.is_active());

        let agent = account.as_physical_agent();

        assert_eq!(agent.agent_id, account.agent_id);

        assert_eq!(agent.owner, account.owner);

        assert!(agent.has_capability(Capability::AerialMobility));

        assert!(agent.has_capability(Capability::Gps));
    }

    #[test]
    fn lifecycle_status_helpers_are_consistent() {
        let mut account = AgentAccount {
            protocol_version: AEROSETTLE_PROTOCOL_VERSION,
            protocol_config: pubkey(1),
            agent_id: [2u8; 32],
            owner: pubkey(3),
            signing_authority: pubkey(4),
            agent_type: AgentType::Drone,
            capabilities: Capability::Gps.bit(),
            metadata_hash: [5u8; 32],
            status: AgentStatus::Active,
            next_signature_sequence: 0,
            bump: 200,
            registered_at: 100,
        };

        assert!(account.is_active());
        assert!(!account.is_suspended());
        assert!(!account.is_revoked());

        account.status = AgentStatus::OwnerSuspended;

        assert!(!account.is_active());
        assert!(account.is_suspended());
        assert!(!account.is_revoked());

        account.status = AgentStatus::AdminSuspended;

        assert!(!account.is_active());
        assert!(account.is_suspended());
        assert!(!account.is_revoked());

        account.status = AgentStatus::Revoked;

        assert!(!account.is_active());
        assert!(!account.is_suspended());
        assert!(account.is_revoked());
    }
}
