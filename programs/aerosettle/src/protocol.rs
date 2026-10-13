use anchor_lang::prelude::*;

/// Current canonical version of the AeroSettle protocol.
pub const AEROSETTLE_PROTOCOL_VERSION: u8 = 1;

/// Number of capability bits available in protocol v1.
pub const MAX_CAPABILITY_BITS: usize = 64;

/// Generic classification of an intelligent physical or edge agent.
///
/// IMPORTANT:
/// Variant ordering is part of the serialized protocol representation.
/// Do not reorder existing variants in protocol v1.
#[derive(AnchorSerialize, AnchorDeserialize, Clone, Copy, Debug, PartialEq, Eq)]
pub enum AgentType {
    Drone,
    Ugv,
    Amr,
    RobotArm,
    Camera,
    IotSensor,
    Vehicle,
    IndustrialMachine,
    EdgeCompute,
    EnergyAsset,
}

/// A capability that an AeroSettle agent can expose.
///
/// On-chain these are represented as bits inside a u64.
/// Rich technical details live in the off-chain Agent Manifest.
#[derive(AnchorSerialize, AnchorDeserialize, Clone, Copy, Debug, PartialEq, Eq)]
pub enum Capability {
    AerialMobility,
    GroundMobility,
    RgbVision,
    ThermalVision,
    MultispectralVision,
    Gps,
    RtkGps,
    EnvironmentalSensing,
    ObjectDetection,
    EdgeInference,
    PhysicalManipulation,
    Transport,
    EnergySupply,
    ColdChainMonitoring,
    Mapping,
    Telemetry,
}

impl Capability {
    /// Stable bit assignment for protocol v1.
    ///
    /// Never reuse an assigned bit for another capability.
    pub const fn bit(self) -> u64 {
        match self {
            Self::AerialMobility => 1 << 0,
            Self::GroundMobility => 1 << 1,
            Self::RgbVision => 1 << 2,
            Self::ThermalVision => 1 << 3,
            Self::MultispectralVision => 1 << 4,
            Self::Gps => 1 << 5,
            Self::RtkGps => 1 << 6,
            Self::EnvironmentalSensing => 1 << 7,
            Self::ObjectDetection => 1 << 8,
            Self::EdgeInference => 1 << 9,
            Self::PhysicalManipulation => 1 << 10,
            Self::Transport => 1 << 11,
            Self::EnergySupply => 1 << 12,
            Self::ColdChainMonitoring => 1 << 13,
            Self::Mapping => 1 << 14,
            Self::Telemetry => 1 << 15,
        }
    }
}

/// Canonical protocol-level representation of an AeroSettle agent.
///
/// This is intentionally NOT an Anchor account yet.
/// EPIC 1 will wrap it in the persistent AgentAccount PDA.
#[derive(AnchorSerialize, AnchorDeserialize, Clone, Debug, PartialEq, Eq)]
pub struct PhysicalAgent {
    /// Schema version used to serialize this object.
    pub protocol_version: u8,

    /// Stable application-level ID.
    ///
    /// Independent from the Solana PDA address.
    pub agent_id: [u8; 32],

    /// Wallet that owns or controls the agent.
    pub owner: Pubkey,

    /// General hardware/agent classification.
    pub agent_type: AgentType,

    /// Capability bitmask.
    pub capabilities: u64,

    /// SHA-256 commitment of the canonical off-chain Agent Manifest.
    pub metadata_hash: [u8; 32],
}

impl PhysicalAgent {
    pub fn new(
        agent_id: [u8; 32],
        owner: Pubkey,
        agent_type: AgentType,
        capabilities: u64,
        metadata_hash: [u8; 32],
    ) -> Self {
        Self {
            protocol_version: AEROSETTLE_PROTOCOL_VERSION,
            agent_id,
            owner,
            agent_type,
            capabilities,
            metadata_hash,
        }
    }

    pub const fn has_capability(&self, capability: Capability) -> bool {
        self.capabilities & capability.bit() != 0
    }

    pub fn add_capability(&mut self, capability: Capability) {
        self.capabilities |= capability.bit();
    }

    pub fn remove_capability(&mut self, capability: Capability) {
        self.capabilities &= !capability.bit();
    }

    pub const fn satisfies(&self, required_capabilities: u64) -> bool {
        self.capabilities & required_capabilities == required_capabilities
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn protocol_version_is_one() {
        assert_eq!(AEROSETTLE_PROTOCOL_VERSION, 1);
    }

    #[test]
    fn capability_bits_are_unique() {
        let capabilities = [
            Capability::AerialMobility,
            Capability::GroundMobility,
            Capability::RgbVision,
            Capability::ThermalVision,
            Capability::MultispectralVision,
            Capability::Gps,
            Capability::RtkGps,
            Capability::EnvironmentalSensing,
            Capability::ObjectDetection,
            Capability::EdgeInference,
            Capability::PhysicalManipulation,
            Capability::Transport,
            Capability::EnergySupply,
            Capability::ColdChainMonitoring,
            Capability::Mapping,
            Capability::Telemetry,
        ];

        let mut combined = 0u64;

        for capability in capabilities {
            let bit = capability.bit();

            assert_ne!(bit, 0);
            assert_eq!(combined & bit, 0, "capability bit collision detected");

            combined |= bit;
        }
    }

    #[test]
    fn drone_can_expose_multiple_capabilities() {
        let capabilities = Capability::AerialMobility.bit()
            | Capability::RgbVision.bit()
            | Capability::Gps.bit()
            | Capability::Telemetry.bit();

        let agent = PhysicalAgent::new(
            [1u8; 32],
            Pubkey::new_unique(),
            AgentType::Drone,
            capabilities,
            [2u8; 32],
        );

        assert!(agent.has_capability(Capability::AerialMobility));
        assert!(agent.has_capability(Capability::RgbVision));
        assert!(agent.has_capability(Capability::Gps));
        assert!(agent.has_capability(Capability::Telemetry));

        assert!(!agent.has_capability(Capability::ThermalVision));
        assert!(!agent.has_capability(Capability::GroundMobility));
    }

    #[test]
    fn iot_agent_can_add_and_remove_capabilities() {
        let mut agent = PhysicalAgent::new(
            [3u8; 32],
            Pubkey::new_unique(),
            AgentType::IotSensor,
            Capability::EnvironmentalSensing.bit(),
            [4u8; 32],
        );

        assert!(agent.has_capability(Capability::EnvironmentalSensing));

        assert!(!agent.has_capability(Capability::ColdChainMonitoring));

        agent.add_capability(Capability::ColdChainMonitoring);

        assert!(agent.has_capability(Capability::ColdChainMonitoring));

        agent.remove_capability(Capability::EnvironmentalSensing);

        assert!(!agent.has_capability(Capability::EnvironmentalSensing));

        assert!(agent.has_capability(Capability::ColdChainMonitoring));
    }

    #[test]
    fn agent_matches_required_capabilities() {
        let capabilities = Capability::AerialMobility.bit()
            | Capability::ThermalVision.bit()
            | Capability::Gps.bit()
            | Capability::Telemetry.bit();

        let agent = PhysicalAgent::new(
            [5u8; 32],
            Pubkey::new_unique(),
            AgentType::Drone,
            capabilities,
            [6u8; 32],
        );

        let thermal_inspection_requirements = Capability::AerialMobility.bit()
            | Capability::ThermalVision.bit()
            | Capability::Gps.bit();

        assert!(agent.satisfies(thermal_inspection_requirements));

        let multispectral_requirements = Capability::AerialMobility.bit()
            | Capability::MultispectralVision.bit()
            | Capability::Gps.bit();

        assert!(!agent.satisfies(multispectral_requirements));
    }

    #[test]
    fn zero_requirements_are_always_satisfied() {
        let agent = PhysicalAgent::new(
            [7u8; 32],
            Pubkey::new_unique(),
            AgentType::EdgeCompute,
            Capability::EdgeInference.bit(),
            [8u8; 32],
        );

        assert!(agent.satisfies(0));
    }
}
