use anchor_lang::prelude::*;

use crate::{
    PaymentModel, PhysicalAgent, SettlementTerms, VerificationStatus, WorkOrder, WorkType,
};

pub const WORK_ORDER_SEED: &[u8] = b"work_order";

#[derive(AnchorSerialize, AnchorDeserialize, Clone, Copy, Debug, PartialEq, Eq)]
pub enum WorkOrderStatus {
    /// Created but not yet economically backed by escrow.
    Draft,

    /// Escrow funded. Eligible agents may claim.
    Open,

    /// One agent has claimed the work.
    Claimed,

    /// Agent submitted execution/evidence commitments.
    Submitted,

    /// Authorized verifier issued an attestation.
    Verified,

    /// Settlement completed.
    Settled,

    /// Creator cancelled before execution.
    Cancelled,

    /// Deadline elapsed without successful execution.
    Expired,
}

/// Arguments used to create the persistent WorkOrder.
///
/// Creator is deliberately not included because it comes from the
/// transaction signer.
#[derive(AnchorSerialize, AnchorDeserialize, Clone, Debug, PartialEq, Eq)]
pub struct CreateWorkOrderArgs {
    pub work_order_id: [u8; 32],
    pub work_type: WorkType,
    pub required_capabilities: u64,
    pub evidence_requirements: u64,
    pub manifest_hash: [u8; 32],
    pub settlement: SettlementTerms,
    pub execution_deadline: i64,
    pub verification_deadline: i64,
}

impl CreateWorkOrderArgs {
    pub fn as_protocol_work_order(&self, creator: Pubkey) -> WorkOrder {
        WorkOrder::new(
            self.work_order_id,
            creator,
            self.work_type,
            self.required_capabilities,
            self.evidence_requirements,
            self.manifest_hash,
            self.settlement.clone(),
            self.execution_deadline,
            self.verification_deadline,
        )
    }
}

/// Persistent economic task in one AeroSettle deployment.
///
/// PDA:
///
/// [
///     b"work_order",
///     protocol_config,
///     creator,
///     work_order_id
/// ]
#[account]
pub struct WorkOrderAccount {
    pub protocol_version: u8,

    pub protocol_config: Pubkey,

    pub work_order_id: [u8; 32],

    pub creator: Pubkey,

    pub work_type: WorkType,

    pub required_capabilities: u64,

    pub evidence_requirements: u64,

    pub manifest_hash: [u8; 32],

    pub token_mint: Pubkey,

    pub total_amount: u64,

    pub payment_model: PaymentModel,

    pub verifier: Pubkey,

    /// Token account holding the economically committed funds.
    /// Default Pubkey while the WorkOrder is still Draft.
    pub escrow_vault: Pubkey,

    /// SPL Token or Token-2022 program controlling the escrow mint.
    /// Default Pubkey while the WorkOrder is still Draft.
    pub token_program: Pubkey,

    pub execution_deadline: i64,

    pub verification_deadline: i64,

    pub status: WorkOrderStatus,

    /// AgentAccount PDA. Default Pubkey means unclaimed.
    pub claimed_agent: Pubkey,
    /// Economic beneficiary frozen when the agent claims.
    pub settlement_beneficiary: Pubkey,

    /// Populated when execution is submitted.
    pub execution_receipt_hash: [u8; 32],

    pub evidence_manifest_hash: [u8; 32],

    /// Device signing key that authorized the submitted execution.
    ///
    /// Persisting this matters because the AgentAccount signing key may
    /// be rotated later.
    pub execution_signer: Pubkey,

    /// Agent signature sequence consumed by this execution.
    pub execution_sequence: u64,

    /// EvidenceRequirement bitmask supplied by the execution.
    pub provided_evidence: u64,

    pub execution_started_at: i64,
    pub execution_ended_at: i64,

    /// Populated after verifier acceptance/rejection.
    pub verification_attestation_hash: [u8; 32],

    /// None until an authorized verifier records a decision.
    pub verification_status: Option<VerificationStatus>,

    pub completion_bps: u16,

    pub created_at: i64,

    /// Timestamp when full escrow funding was confirmed.
    pub funded_at: i64,

    pub claimed_at: i64,

    pub submitted_at: i64,

    pub verified_at: i64,

    pub settled_at: i64,

    pub bump: u8,
}

impl WorkOrderAccount {
    /// Fixed serialized body size excluding Anchor discriminator.
    pub const DATA_LEN: usize = 1   // protocol_version
        + 32 // protocol_config
        + 32 // work_order_id
        + 32 // creator
        + 1  // WorkType
        + 8  // required_capabilities
        + 8  // evidence_requirements
        + 32 // manifest_hash
        + 32 // token_mint
        + 8  // total_amount
        + 1  // PaymentModel
        + 32 // verifier
        + 32 // escrow_vault
        + 32 // token_program
        + 8  // execution_deadline
        + 8  // verification_deadline
        + 1  // WorkOrderStatus
        + 32 // claimed_agent
        + 32 // settlement_beneficiary
        + 32 // execution_receipt_hash
        + 32 // evidence_manifest_hash
        + 32 // execution_signer
        + 8  // execution_sequence
        + 8  // provided_evidence
        + 8  // execution_started_at
        + 8  // execution_ended_at
        + 32 // verification_attestation_hash
        + 2  // verification_status: Option<VerificationStatus>
        + 2  // completion_bps
        + 8  // created_at
        + 8  // funded_at
        + 8  // claimed_at
        + 8  // submitted_at
        + 8  // verified_at
        + 8  // settled_at
        + 1; // bump

    pub const SPACE: usize = 8 + Self::DATA_LEN;

    pub const fn is_claimable(&self) -> bool {
        matches!(self.status, WorkOrderStatus::Open)
    }

    pub const fn has_required_evidence(&self, provided_evidence: u64) -> bool {
        provided_evidence & self.evidence_requirements == self.evidence_requirements
    }

    pub const fn is_terminal(&self) -> bool {
        matches!(
            self.status,
            WorkOrderStatus::Settled | WorkOrderStatus::Cancelled | WorkOrderStatus::Expired
        )
    }

    pub fn as_protocol_work_order(&self) -> WorkOrder {
        WorkOrder::new(
            self.work_order_id,
            self.creator,
            self.work_type,
            self.required_capabilities,
            self.evidence_requirements,
            self.manifest_hash,
            SettlementTerms {
                token_mint: self.token_mint,
                total_amount: self.total_amount,
                payment_model: self.payment_model,
                verifier: self.verifier,
            },
            self.execution_deadline,
            self.verification_deadline,
        )
    }

    pub fn is_compatible_with(&self, agent: &PhysicalAgent) -> bool {
        self.as_protocol_work_order().is_compatible_with(agent)
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
    fn work_order_account_size_is_stable() {
        assert_eq!(WorkOrderAccount::DATA_LEN, 577);

        assert_eq!(WorkOrderAccount::SPACE, 585);
    }

    #[test]
    fn draft_is_not_claimable() {
        assert!(!matches!(WorkOrderStatus::Draft, WorkOrderStatus::Open));
    }

    #[test]
    fn account_projection_preserves_protocol_fields() {
        let account = WorkOrderAccount {
            protocol_version: AEROSETTLE_PROTOCOL_VERSION,
            protocol_config: pubkey(1),
            work_order_id: [2u8; 32],
            creator: pubkey(3),
            work_type: WorkType::Inspection,
            required_capabilities: Capability::AerialMobility.bit() | Capability::Gps.bit(),
            evidence_requirements: 7,
            manifest_hash: [4u8; 32],
            token_mint: pubkey(5),
            total_amount: 100_000,
            payment_model: PaymentModel::Proportional,
            verifier: pubkey(6),
            escrow_vault: Pubkey::default(),
            token_program: Pubkey::default(),
            execution_deadline: 1_000,
            verification_deadline: 1_300,
            status: WorkOrderStatus::Draft,
            claimed_agent: Pubkey::default(),
            settlement_beneficiary: Pubkey::default(),
            execution_receipt_hash: [0u8; 32],
            evidence_manifest_hash: [0u8; 32],
            execution_signer: Pubkey::default(),
            execution_sequence: 0,
            provided_evidence: 0,
            execution_started_at: 0,
            execution_ended_at: 0,
            verification_attestation_hash: [0u8; 32],
            verification_status: None,
            completion_bps: 0,
            created_at: 500,
            funded_at: 0,
            claimed_at: 0,
            submitted_at: 0,
            verified_at: 0,
            settled_at: 0,
            bump: 200,
        };

        let projected = account.as_protocol_work_order();

        assert_eq!(projected.work_order_id, account.work_order_id);

        assert_eq!(projected.creator, account.creator);

        assert_eq!(
            projected.required_capabilities,
            account.required_capabilities
        );

        assert_eq!(projected.settlement.total_amount, account.total_amount);
    }

    #[test]
    fn required_evidence_bitmask_is_enforced() {
        let required = 0b1011u64;

        let account = WorkOrderAccount {
            protocol_version: AEROSETTLE_PROTOCOL_VERSION,
            protocol_config: pubkey(1),
            work_order_id: [2u8; 32],
            creator: pubkey(3),
            work_type: WorkType::Inspection,
            required_capabilities: Capability::Gps.bit(),
            evidence_requirements: required,
            manifest_hash: [4u8; 32],
            token_mint: pubkey(5),
            total_amount: 100,
            payment_model: PaymentModel::Proportional,
            verifier: pubkey(6),
            escrow_vault: pubkey(7),
            token_program: pubkey(8),
            execution_deadline: 1_000,
            verification_deadline: 1_300,
            status: WorkOrderStatus::Claimed,
            claimed_agent: pubkey(9),
            settlement_beneficiary: Pubkey::default(),
            execution_receipt_hash: [0u8; 32],
            evidence_manifest_hash: [0u8; 32],
            execution_signer: Pubkey::default(),
            execution_sequence: 0,
            provided_evidence: 0,
            execution_started_at: 0,
            execution_ended_at: 0,
            verification_attestation_hash: [0u8; 32],
            verification_status: None,
            completion_bps: 0,
            created_at: 100,
            funded_at: 110,
            claimed_at: 120,
            submitted_at: 0,
            verified_at: 0,
            settled_at: 0,
            bump: 200,
        };

        assert!(account.has_required_evidence(0b1011));

        assert!(account.has_required_evidence(0b1111));

        assert!(!account.has_required_evidence(0b0011));
    }
}
