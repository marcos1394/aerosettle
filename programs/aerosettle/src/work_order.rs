use anchor_lang::prelude::*;

use crate::{PhysicalAgent, AEROSETTLE_PROTOCOL_VERSION};

/// Maximum value for basis points: 100.00%.
pub const MAX_BASIS_POINTS: u16 = 10_000;

/// Classification of physical or digital work.
///
/// Variant ordering is protocol data.
/// Never reorder existing variants in protocol v1.
#[derive(AnchorSerialize, AnchorDeserialize, Clone, Copy, Debug, PartialEq, Eq)]
pub enum WorkType {
    Inspection,
    Monitoring,
    Mapping,
    Delivery,
    Transport,
    Measurement,
    Actuation,
    Manufacturing,
    Compute,
    EnergyService,
}

impl WorkType {
    /// Stable bit assignment used by EconomicPolicy.
    pub const fn bit(self) -> u64 {
        match self {
            Self::Inspection => 1 << 0,
            Self::Monitoring => 1 << 1,
            Self::Mapping => 1 << 2,
            Self::Delivery => 1 << 3,
            Self::Transport => 1 << 4,
            Self::Measurement => 1 << 5,
            Self::Actuation => 1 << 6,
            Self::Manufacturing => 1 << 7,
            Self::Compute => 1 << 8,
            Self::EnergyService => 1 << 9,
        }
    }
}

/// Evidence that can be required before a WorkOrder is settled.
///
/// Represented as a bitmask to make matching deterministic and compact.
#[derive(AnchorSerialize, AnchorDeserialize, Clone, Copy, Debug, PartialEq, Eq)]
pub enum EvidenceRequirement {
    Telemetry,
    GpsTrace,
    ImageManifest,
    VideoManifest,
    SensorReadings,
    AiInferenceResult,
    DeviceSignature,
    StartTimestamp,
    EndTimestamp,
}

impl EvidenceRequirement {
    pub const fn bit(self) -> u64 {
        match self {
            Self::Telemetry => 1 << 0,
            Self::GpsTrace => 1 << 1,
            Self::ImageManifest => 1 << 2,
            Self::VideoManifest => 1 << 3,
            Self::SensorReadings => 1 << 4,
            Self::AiInferenceResult => 1 << 5,
            Self::DeviceSignature => 1 << 6,
            Self::StartTimestamp => 1 << 7,
            Self::EndTimestamp => 1 << 8,
        }
    }
}

/// Settlement algorithm selected by the WorkOrder creator.
#[derive(AnchorSerialize, AnchorDeserialize, Clone, Copy, Debug, PartialEq, Eq)]
pub enum PaymentModel {
    /// Full amount is paid when the verifier accepts the work.
    Fixed,

    /// Amount is proportional to verified completion in basis points.
    Proportional,
}

/// Financial rules for a WorkOrder.
///
/// No token transfer occurs yet. EPIC 1/escrow will enforce these terms
/// on-chain.
#[derive(AnchorSerialize, AnchorDeserialize, Clone, Debug, PartialEq, Eq)]
pub struct SettlementTerms {
    /// Token mint used for settlement.
    pub token_mint: Pubkey,

    /// Maximum amount locked for this WorkOrder in token base units.
    pub total_amount: u64,

    /// Settlement algorithm.
    pub payment_model: PaymentModel,

    /// Oracle/verifier allowed to attest work completion.
    pub verifier: Pubkey,
}

impl SettlementTerms {
    pub const fn is_valid(&self) -> bool {
        self.total_amount > 0
    }

    /// Deterministic settlement calculation.
    ///
    /// Uses u128 internally to avoid overflow during multiplication.
    pub fn calculate_payout(&self, completion_bps: u16) -> Option<(u64, u64)> {
        if completion_bps > MAX_BASIS_POINTS {
            return None;
        }

        let payout = match self.payment_model {
            PaymentModel::Fixed => {
                if completion_bps == MAX_BASIS_POINTS {
                    self.total_amount
                } else {
                    0
                }
            }

            PaymentModel::Proportional => {
                let amount = (self.total_amount as u128)
                    .checked_mul(completion_bps as u128)?
                    .checked_div(MAX_BASIS_POINTS as u128)?;

                u64::try_from(amount).ok()?
            }
        };

        let refund = self.total_amount.checked_sub(payout)?;

        Some((payout, refund))
    }
}

/// Owner-defined deterministic policy controlling what an autonomous
/// agent is allowed to accept.
///
/// AI can recommend or select work, but it cannot bypass this policy.
#[derive(AnchorSerialize, AnchorDeserialize, Clone, Debug, PartialEq, Eq)]
pub struct EconomicPolicy {
    /// Bitmask of WorkType values the owner authorizes.
    pub allowed_work_types: u64,

    /// Minimum reward an agent is allowed to accept.
    pub min_reward: u64,

    /// Minimum required battery/energy state in basis points.
    ///
    /// 10_000 = 100%.
    pub min_energy_bps: u16,

    /// Maximum allowed execution duration in seconds.
    pub max_execution_seconds: u32,
}

impl EconomicPolicy {
    pub const fn allows_work_type(&self, work_type: WorkType) -> bool {
        self.allowed_work_types & work_type.bit() != 0
    }

    pub const fn is_valid(&self) -> bool {
        self.min_energy_bps <= MAX_BASIS_POINTS && self.max_execution_seconds > 0
    }
}

/// Canonical protocol representation of a unit of autonomous work.
///
/// This is intentionally not yet an Anchor account. The persistent PDA
/// will be introduced after the protocol model is stable.
#[derive(AnchorSerialize, AnchorDeserialize, Clone, Debug, PartialEq, Eq)]
pub struct WorkOrder {
    pub protocol_version: u8,

    /// Stable application-level WorkOrder ID.
    pub work_order_id: [u8; 32],

    /// Party requesting and funding the work.
    pub creator: Pubkey,

    pub work_type: WorkType,

    /// Capability bitmask required from the executing PhysicalAgent.
    pub required_capabilities: u64,

    /// Evidence bitmask required for verification.
    pub evidence_requirements: u64,

    /// SHA-256 commitment of the canonical off-chain Work Manifest.
    pub manifest_hash: [u8; 32],

    pub settlement: SettlementTerms,

    /// Last timestamp at which physical execution may complete.
    pub execution_deadline: i64,

    /// Last timestamp at which verification/settlement may occur.
    ///
    /// Must be strictly greater than execution_deadline.
    pub verification_deadline: i64,
}

impl WorkOrder {
    #[allow(clippy::too_many_arguments)]
    pub fn new(
        work_order_id: [u8; 32],
        creator: Pubkey,
        work_type: WorkType,
        required_capabilities: u64,
        evidence_requirements: u64,
        manifest_hash: [u8; 32],
        settlement: SettlementTerms,
        execution_deadline: i64,
        verification_deadline: i64,
    ) -> Self {
        Self {
            protocol_version: AEROSETTLE_PROTOCOL_VERSION,
            work_order_id,
            creator,
            work_type,
            required_capabilities,
            evidence_requirements,
            manifest_hash,
            settlement,
            execution_deadline,
            verification_deadline,
        }
    }

    pub const fn has_valid_deadlines(&self) -> bool {
        self.execution_deadline < self.verification_deadline
    }

    pub const fn requires_evidence(&self, requirement: EvidenceRequirement) -> bool {
        self.evidence_requirements & requirement.bit() != 0
    }

    pub const fn is_compatible_with(&self, agent: &PhysicalAgent) -> bool {
        agent.satisfies(self.required_capabilities)
    }

    pub const fn is_valid(&self) -> bool {
        self.has_valid_deadlines() && self.settlement.is_valid()
    }
}

/// Runtime context supplied when evaluating whether an autonomous agent
/// may accept a WorkOrder.
///
/// This is not persisted on-chain.
#[derive(AnchorSerialize, AnchorDeserialize, Clone, Copy, Debug, PartialEq, Eq)]
pub struct AgentRuntimeState {
    /// Current battery/energy level in basis points.
    pub energy_bps: u16,
}

impl EconomicPolicy {
    /// Deterministic authorization gate.
    ///
    /// This function represents an important AeroSettle invariant:
    ///
    /// AI may choose a candidate WorkOrder, but acceptance must pass
    /// deterministic owner policy.
    pub const fn authorizes(
        &self,
        agent: &PhysicalAgent,
        runtime: AgentRuntimeState,
        work_order: &WorkOrder,
    ) -> bool {
        if !self.is_valid() {
            return false;
        }

        if runtime.energy_bps > MAX_BASIS_POINTS {
            return false;
        }

        if runtime.energy_bps < self.min_energy_bps {
            return false;
        }

        if !self.allows_work_type(work_order.work_type) {
            return false;
        }

        if work_order.settlement.total_amount < self.min_reward {
            return false;
        }

        if !work_order.is_compatible_with(agent) {
            return false;
        }

        true
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::{AgentType, Capability};

    fn drone() -> PhysicalAgent {
        PhysicalAgent::new(
            [1u8; 32],
            Pubkey::new_unique(),
            AgentType::Drone,
            Capability::AerialMobility.bit()
                | Capability::ThermalVision.bit()
                | Capability::Gps.bit()
                | Capability::Telemetry.bit(),
            [2u8; 32],
        )
    }

    fn settlement(model: PaymentModel, amount: u64) -> SettlementTerms {
        SettlementTerms {
            token_mint: Pubkey::new_unique(),
            total_amount: amount,
            payment_model: model,
            verifier: Pubkey::new_unique(),
        }
    }

    fn thermal_inspection() -> WorkOrder {
        WorkOrder::new(
            [3u8; 32],
            Pubkey::new_unique(),
            WorkType::Inspection,
            Capability::AerialMobility.bit()
                | Capability::ThermalVision.bit()
                | Capability::Gps.bit(),
            EvidenceRequirement::Telemetry.bit()
                | EvidenceRequirement::GpsTrace.bit()
                | EvidenceRequirement::ImageManifest.bit()
                | EvidenceRequirement::DeviceSignature.bit(),
            [4u8; 32],
            settlement(PaymentModel::Proportional, 100_000_000),
            1_000,
            1_300,
        )
    }

    #[test]
    fn work_order_matches_compatible_agent() {
        let agent = drone();
        let order = thermal_inspection();

        assert!(order.is_compatible_with(&agent));
    }

    #[test]
    fn work_order_rejects_missing_capability() {
        let agent = PhysicalAgent::new(
            [5u8; 32],
            Pubkey::new_unique(),
            AgentType::Drone,
            Capability::AerialMobility.bit() | Capability::RgbVision.bit() | Capability::Gps.bit(),
            [6u8; 32],
        );

        let order = thermal_inspection();

        assert!(!order.is_compatible_with(&agent));
    }

    #[test]
    fn evidence_requirements_are_detectable() {
        let order = thermal_inspection();

        assert!(order.requires_evidence(EvidenceRequirement::Telemetry));

        assert!(order.requires_evidence(EvidenceRequirement::DeviceSignature));

        assert!(!order.requires_evidence(EvidenceRequirement::VideoManifest));
    }

    #[test]
    fn work_order_requires_verification_window() {
        let mut order = thermal_inspection();

        assert!(order.has_valid_deadlines());

        order.verification_deadline = order.execution_deadline;

        assert!(!order.has_valid_deadlines());
        assert!(!order.is_valid());
    }

    #[test]
    fn proportional_settlement_7350_bps() {
        let terms = settlement(PaymentModel::Proportional, 100_000_000);

        let (payout, refund) = terms.calculate_payout(7_350).unwrap();

        assert_eq!(payout, 73_500_000);
        assert_eq!(refund, 26_500_000);

        assert_eq!(payout + refund, terms.total_amount);
    }

    #[test]
    fn proportional_settlement_100_percent() {
        let terms = settlement(PaymentModel::Proportional, 100_000_000);

        let (payout, refund) = terms.calculate_payout(10_000).unwrap();

        assert_eq!(payout, 100_000_000);
        assert_eq!(refund, 0);
    }

    #[test]
    fn proportional_settlement_zero_percent() {
        let terms = settlement(PaymentModel::Proportional, 100_000_000);

        let (payout, refund) = terms.calculate_payout(0).unwrap();

        assert_eq!(payout, 0);
        assert_eq!(refund, 100_000_000);
    }

    #[test]
    fn invalid_basis_points_are_rejected() {
        let terms = settlement(PaymentModel::Proportional, 100_000_000);

        assert_eq!(terms.calculate_payout(10_001), None);
    }

    #[test]
    fn fixed_payment_requires_complete_work() {
        let terms = settlement(PaymentModel::Fixed, 100_000_000);

        let incomplete = terms.calculate_payout(9_999).unwrap();

        assert_eq!(incomplete, (0, 100_000_000));

        let complete = terms.calculate_payout(10_000).unwrap();

        assert_eq!(complete, (100_000_000, 0));
    }

    #[test]
    fn payout_math_handles_u64_max() {
        let terms = settlement(PaymentModel::Proportional, u64::MAX);

        let (payout, refund) = terms.calculate_payout(7_350).unwrap();

        assert_eq!(payout as u128 + refund as u128, u64::MAX as u128);
    }

    #[test]
    fn economic_policy_authorizes_profitable_compatible_work() {
        let agent = drone();
        let order = thermal_inspection();

        let policy = EconomicPolicy {
            allowed_work_types: WorkType::Inspection.bit() | WorkType::Mapping.bit(),

            min_reward: 50_000_000,
            min_energy_bps: 4_000,
            max_execution_seconds: 3_600,
        };

        let runtime = AgentRuntimeState { energy_bps: 8_000 };

        assert!(policy.authorizes(&agent, runtime, &order));
    }

    #[test]
    fn economic_policy_rejects_low_energy() {
        let agent = drone();
        let order = thermal_inspection();

        let policy = EconomicPolicy {
            allowed_work_types: WorkType::Inspection.bit(),

            min_reward: 1,
            min_energy_bps: 6_000,
            max_execution_seconds: 3_600,
        };

        let runtime = AgentRuntimeState { energy_bps: 5_999 };

        assert!(!policy.authorizes(&agent, runtime, &order));
    }

    #[test]
    fn economic_policy_rejects_low_reward() {
        let agent = drone();
        let order = thermal_inspection();

        let policy = EconomicPolicy {
            allowed_work_types: WorkType::Inspection.bit(),

            min_reward: 100_000_001,
            min_energy_bps: 1,
            max_execution_seconds: 3_600,
        };

        let runtime = AgentRuntimeState { energy_bps: 10_000 };

        assert!(!policy.authorizes(&agent, runtime, &order));
    }

    #[test]
    fn economic_policy_rejects_disallowed_work_type() {
        let agent = drone();
        let order = thermal_inspection();

        let policy = EconomicPolicy {
            allowed_work_types: WorkType::Mapping.bit(),

            min_reward: 1,
            min_energy_bps: 1,
            max_execution_seconds: 3_600,
        };

        let runtime = AgentRuntimeState { energy_bps: 10_000 };

        assert!(!policy.authorizes(&agent, runtime, &order));
    }
}
