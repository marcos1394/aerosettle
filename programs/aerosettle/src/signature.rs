use anchor_lang::prelude::*;

use crate::{
    CanonicalCommitment, ExecutionReceipt, VerificationAttestation, AEROSETTLE_PROTOCOL_VERSION,
};

/// Domain used to produce the fixed-size digest that agents/verifiers sign.
pub const SIGNATURE_PAYLOAD_DOMAIN: &[u8] = b"AEROSETTLE:SIGNATURE_PAYLOAD:V1\0";

/// Identifies one specific AeroSettle deployment.
///
/// `network_id` should identify the underlying Solana cluster.
/// In production deployments it can be populated from the cluster
/// genesis hash and persisted in the AeroSettle configuration account.
///
/// `deployment_id` is intentionally independent from Program ID so a
/// deployment can invalidate signatures even if the upgradeable Program ID
/// remains unchanged.
#[derive(AnchorSerialize, AnchorDeserialize, Clone, Copy, Debug, PartialEq, Eq)]
pub struct DeploymentContext {
    pub network_id: [u8; 32],
    pub program_id: Pubkey,
    pub deployment_id: [u8; 32],
}

impl DeploymentContext {
    pub fn new(network_id: [u8; 32], program_id: Pubkey, deployment_id: [u8; 32]) -> Self {
        Self {
            network_id,
            program_id,
            deployment_id,
        }
    }
}

/// Semantic purpose of a detached signature.
///
/// These numeric values become part of protocol v1.
/// Existing codes must never be reordered or reused.
#[derive(AnchorSerialize, AnchorDeserialize, Clone, Copy, Debug, PartialEq, Eq)]
pub enum SignaturePurpose {
    AgentExecutionReceipt,
    VerifierAttestation,
    AgentWorkAcceptance,
    OwnerPolicyAuthorization,
}

impl SignaturePurpose {
    pub const fn code(self) -> u8 {
        match self {
            Self::AgentExecutionReceipt => 0,
            Self::VerifierAttestation => 1,
            Self::AgentWorkAcceptance => 2,
            Self::OwnerPolicyAuthorization => 3,
        }
    }
}

/// Canonical message envelope used for detached Ed25519 signatures.
///
/// Devices/verifiers DO NOT sign arbitrary JSON or serialized Rust objects.
/// They sign `signing_digest()`, which is always exactly 32 bytes.
///
/// The subject itself is already represented by its domain-separated
/// AeroSettle commitment.
#[derive(AnchorSerialize, AnchorDeserialize, Clone, Debug, PartialEq, Eq)]
pub struct SignaturePayload {
    pub protocol_version: u8,

    pub network_id: [u8; 32],
    pub program_id: Pubkey,
    pub deployment_id: [u8; 32],

    pub purpose: SignaturePurpose,

    /// Ed25519 public key expected to authorize this payload.
    pub signer: Pubkey,

    pub work_order_id: [u8; 32],

    /// Domain-separated commitment of the object being signed.
    pub subject_hash: [u8; 32],

    /// Unique nonce generated for this authorization/execution.
    ///
    /// Actual nonce consumption/replay prevention will be enforced by the
    /// persistent WorkOrder/Agent state in the on-chain layer.
    pub nonce: [u8; 32],

    pub issued_at: i64,
    pub expires_at: i64,
}

impl SignaturePayload {
    #[allow(clippy::too_many_arguments)]
    pub fn new(
        context: DeploymentContext,
        purpose: SignaturePurpose,
        signer: Pubkey,
        work_order_id: [u8; 32],
        subject_hash: [u8; 32],
        nonce: [u8; 32],
        issued_at: i64,
        expires_at: i64,
    ) -> Self {
        Self {
            protocol_version: AEROSETTLE_PROTOCOL_VERSION,
            network_id: context.network_id,
            program_id: context.program_id,
            deployment_id: context.deployment_id,
            purpose,
            signer,
            work_order_id,
            subject_hash,
            nonce,
            issued_at,
            expires_at,
        }
    }

    pub fn for_execution_receipt(
        context: DeploymentContext,
        signer: Pubkey,
        receipt: &ExecutionReceipt,
        nonce: [u8; 32],
        issued_at: i64,
        expires_at: i64,
    ) -> Self {
        Self::new(
            context,
            SignaturePurpose::AgentExecutionReceipt,
            signer,
            receipt.work_order_id,
            receipt.commitment_hash(),
            nonce,
            issued_at,
            expires_at,
        )
    }

    pub fn for_verification_attestation(
        context: DeploymentContext,
        attestation: &VerificationAttestation,
        nonce: [u8; 32],
        issued_at: i64,
        expires_at: i64,
    ) -> Self {
        Self::new(
            context,
            SignaturePurpose::VerifierAttestation,
            attestation.verifier,
            attestation.work_order_id,
            attestation.commitment_hash(),
            nonce,
            issued_at,
            expires_at,
        )
    }

    /// Fixed-size message to be signed by Ed25519.
    ///
    /// Ed25519 signs these 32 bytes, not the original Rust structure.
    pub fn signing_digest(&self) -> [u8; 32] {
        self.commitment_hash()
    }

    pub fn lifetime_seconds(&self) -> Option<u64> {
        let seconds = self.expires_at.checked_sub(self.issued_at)?;

        u64::try_from(seconds).ok()
    }

    pub fn is_structurally_valid(&self) -> bool {
        self.protocol_version == AEROSETTLE_PROTOCOL_VERSION
            && self.nonce != [0u8; 32]
            && self.issued_at <= self.expires_at
    }

    pub fn is_bound_to_context(&self, context: &DeploymentContext) -> bool {
        self.network_id == context.network_id
            && self.program_id == context.program_id
            && self.deployment_id == context.deployment_id
    }

    pub fn is_bound_to_execution_receipt(
        &self,
        context: &DeploymentContext,
        expected_signer: &Pubkey,
        receipt: &ExecutionReceipt,
    ) -> bool {
        self.is_structurally_valid()
            && self.is_bound_to_context(context)
            && self.purpose == SignaturePurpose::AgentExecutionReceipt
            && self.signer == *expected_signer
            && self.work_order_id == receipt.work_order_id
            && self.subject_hash == receipt.commitment_hash()
    }

    pub fn is_bound_to_verification_attestation(
        &self,
        context: &DeploymentContext,
        attestation: &VerificationAttestation,
    ) -> bool {
        self.is_structurally_valid()
            && self.is_bound_to_context(context)
            && self.purpose == SignaturePurpose::VerifierAttestation
            && self.signer == attestation.verifier
            && self.work_order_id == attestation.work_order_id
            && self.subject_hash == attestation.commitment_hash()
    }
}

impl CanonicalCommitment for SignaturePayload {
    const DOMAIN: &'static [u8] = SIGNATURE_PAYLOAD_DOMAIN;

    fn canonical_bytes(&self) -> Vec<u8> {
        // Protocol v1 SignaturePayload = exactly 242 bytes.
        let mut bytes = Vec::with_capacity(242);

        bytes.push(self.protocol_version);

        bytes.extend_from_slice(&self.network_id);

        bytes.extend_from_slice(self.program_id.as_ref());

        bytes.extend_from_slice(&self.deployment_id);

        bytes.push(self.purpose.code());

        bytes.extend_from_slice(self.signer.as_ref());

        bytes.extend_from_slice(&self.work_order_id);

        bytes.extend_from_slice(&self.subject_hash);

        bytes.extend_from_slice(&self.nonce);

        bytes.extend_from_slice(&self.issued_at.to_le_bytes());

        bytes.extend_from_slice(&self.expires_at.to_le_bytes());

        bytes
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    use crate::VerificationStatus;

    fn pubkey(value: u8) -> Pubkey {
        Pubkey::new_from_array([value; 32])
    }

    fn context() -> DeploymentContext {
        DeploymentContext::new([9u8; 32], pubkey(10), [11u8; 32])
    }

    fn receipt() -> ExecutionReceipt {
        ExecutionReceipt::new(
            [1u8; 32], [6u8; 32], 800, 950, [20u8; 32], [21u8; 32], [22u8; 32],
        )
    }

    fn attestation() -> VerificationAttestation {
        VerificationAttestation::new(
            [1u8; 32],
            [30u8; 32],
            [20u8; 32],
            pubkey(5),
            VerificationStatus::Accepted,
            7_350,
            1_100,
        )
    }

    fn execution_payload() -> SignaturePayload {
        SignaturePayload::for_execution_receipt(
            context(),
            pubkey(12),
            &receipt(),
            [13u8; 32],
            900,
            1_200,
        )
    }

    #[test]
    fn canonical_signature_payload_size_is_stable() {
        assert_eq!(execution_payload().canonical_bytes().len(), 242);
    }

    #[test]
    fn execution_signature_golden_vector_is_stable() {
        let expected = [
            0x0a, 0xd6, 0x8a, 0x95, 0xff, 0x65, 0xf8, 0xf7, 0xfc, 0x8c, 0xcb, 0x0d, 0xe7, 0x4e,
            0x90, 0x7d, 0x10, 0x8a, 0xe6, 0x52, 0xd9, 0x9e, 0xb9, 0x5a, 0x82, 0xe2, 0xd6, 0xd4,
            0x3d, 0x8b, 0x30, 0xc5,
        ];

        assert_eq!(execution_payload().signing_digest(), expected);
    }

    #[test]
    fn execution_payload_binds_to_receipt() {
        let receipt = receipt();
        let signer = pubkey(12);
        let payload = execution_payload();

        assert!(payload.is_bound_to_execution_receipt(&context(), &signer, &receipt,));
    }

    #[test]
    fn wrong_execution_signer_is_rejected() {
        let payload = execution_payload();

        assert!(!payload.is_bound_to_execution_receipt(&context(), &pubkey(99), &receipt(),));
    }

    #[test]
    fn changing_network_breaks_binding() {
        let payload = execution_payload();

        let wrong_context = DeploymentContext::new([99u8; 32], pubkey(10), [11u8; 32]);

        assert!(!payload.is_bound_to_context(&wrong_context));

        assert_ne!(
            payload.signing_digest(),
            SignaturePayload::for_execution_receipt(
                wrong_context,
                pubkey(12),
                &receipt(),
                [13u8; 32],
                900,
                1_200,
            )
            .signing_digest()
        );
    }

    #[test]
    fn changing_program_breaks_binding() {
        let payload = execution_payload();

        let wrong_context = DeploymentContext::new([9u8; 32], pubkey(99), [11u8; 32]);

        assert!(!payload.is_bound_to_context(&wrong_context));
    }

    #[test]
    fn changing_deployment_breaks_binding() {
        let payload = execution_payload();

        let wrong_context = DeploymentContext::new([9u8; 32], pubkey(10), [99u8; 32]);

        assert!(!payload.is_bound_to_context(&wrong_context));
    }

    #[test]
    fn changing_nonce_changes_digest() {
        let original = execution_payload();

        let changed = SignaturePayload::for_execution_receipt(
            context(),
            pubkey(12),
            &receipt(),
            [14u8; 32],
            900,
            1_200,
        );

        assert_ne!(original.signing_digest(), changed.signing_digest());
    }

    #[test]
    fn zero_nonce_is_invalid() {
        let payload = SignaturePayload::for_execution_receipt(
            context(),
            pubkey(12),
            &receipt(),
            [0u8; 32],
            900,
            1_200,
        );

        assert!(!payload.is_structurally_valid());
    }

    #[test]
    fn inverted_validity_window_is_invalid() {
        let payload = SignaturePayload::for_execution_receipt(
            context(),
            pubkey(12),
            &receipt(),
            [13u8; 32],
            1_201,
            1_200,
        );

        assert!(!payload.is_structurally_valid());

        assert_eq!(payload.lifetime_seconds(), None);
    }

    #[test]
    fn verifier_payload_binds_to_attestation() {
        let attestation = attestation();

        let payload = SignaturePayload::for_verification_attestation(
            context(),
            &attestation,
            [15u8; 32],
            1_100,
            1_250,
        );

        assert!(payload.is_bound_to_verification_attestation(&context(), &attestation,));
    }

    #[test]
    fn signature_purpose_prevents_cross_use() {
        let receipt = receipt();

        let payload = SignaturePayload::new(
            context(),
            SignaturePurpose::VerifierAttestation,
            pubkey(12),
            receipt.work_order_id,
            receipt.commitment_hash(),
            [13u8; 32],
            900,
            1_200,
        );

        assert!(!payload.is_bound_to_execution_receipt(&context(), &pubkey(12), &receipt,));
    }
}
