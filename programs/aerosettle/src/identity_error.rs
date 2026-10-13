use anchor_lang::prelude::*;

#[error_code]
pub enum IdentityError {
    #[msg("Network ID cannot be zero.")]
    InvalidNetworkId,

    #[msg("Deployment ID cannot be zero.")]
    InvalidDeploymentId,

    #[msg("The protocol is currently paused.")]
    ProtocolPaused,

    #[msg("Unsupported AeroSettle protocol version.")]
    UnsupportedProtocolVersion,

    #[msg("Agent ID cannot be zero.")]
    InvalidAgentId,

    #[msg("Signing authority cannot be the default public key.")]
    InvalidSigningAuthority,

    #[msg("An agent must expose at least one capability.")]
    NoCapabilities,

    #[msg("Agent metadata hash cannot be zero.")]
    InvalidMetadataHash,

    #[msg("Agent counter overflow.")]
    AgentCounterOverflow,

    #[msg("Actor is not authorized to perform this operation.")]
    UnauthorizedActor,

    #[msg("Agent has been permanently revoked.")]
    AgentRevoked,

    #[msg("Invalid agent status transition.")]
    InvalidStatusTransition,

    #[msg("New owner cannot equal the current owner.")]
    InvalidNewOwner,

    #[msg("The requested update does not change the current value.")]
    NoOpUpdate,

    #[msg("Agent does not belong to the supplied protocol configuration.")]
    InvalidProtocolConfig,
}
