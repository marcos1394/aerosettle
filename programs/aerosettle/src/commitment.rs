use anchor_lang::prelude::*;
use sha2::{Digest, Sha256};

use crate::{
    EvidenceManifest, ExecutionReceipt, PaymentModel, VerificationAttestation, VerificationStatus,
    WorkOrder, WorkType,
};

/// Domain separation prevents the same serialized payload from being
/// interpreted as two different AeroSettle protocol objects.
pub const WORK_ORDER_DOMAIN: &[u8] = b"AEROSETTLE:WORK_ORDER:V1\0";

pub const EVIDENCE_MANIFEST_DOMAIN: &[u8] = b"AEROSETTLE:EVIDENCE_MANIFEST:V1\0";

pub const EXECUTION_RECEIPT_DOMAIN: &[u8] = b"AEROSETTLE:EXECUTION_RECEIPT:V1\0";

pub const VERIFICATION_ATTESTATION_DOMAIN: &[u8] = b"AEROSETTLE:VERIFICATION_ATTESTATION:V1\0";

/// Objects that have a stable canonical representation and cryptographic
/// commitment in the AeroSettle protocol.
pub trait CanonicalCommitment {
    const DOMAIN: &'static [u8];

    fn canonical_bytes(&self) -> Vec<u8>;

    fn commitment_hash(&self) -> [u8; 32] {
        hash_with_domain(Self::DOMAIN, &self.canonical_bytes())
    }
}

/// Hashes:
///
/// SHA256(domain || canonical_payload)
///
/// The domains include protocol object type and schema version.
pub fn hash_with_domain(domain: &[u8], payload: &[u8]) -> [u8; 32] {
    let mut hasher = Sha256::new();

    hasher.update(domain);
    hasher.update(payload);

    let digest = hasher.finalize();

    let mut output = [0u8; 32];
    output.copy_from_slice(&digest);

    output
}

/// Minimal deterministic binary writer.
///
/// Protocol v1 encoding rules:
///
/// - integers: little-endian
/// - Pubkey: raw 32 bytes
/// - hashes/IDs: raw 32 bytes
/// - enums: explicit stable u8 codes
/// - no JSON
/// - no strings
/// - no platform-dependent encoding
struct CanonicalWriter {
    bytes: Vec<u8>,
}

impl CanonicalWriter {
    fn with_capacity(capacity: usize) -> Self {
        Self {
            bytes: Vec::with_capacity(capacity),
        }
    }

    fn put_u8(&mut self, value: u8) {
        self.bytes.push(value);
    }

    fn put_u16(&mut self, value: u16) {
        self.bytes.extend_from_slice(&value.to_le_bytes());
    }

    fn put_u64(&mut self, value: u64) {
        self.bytes.extend_from_slice(&value.to_le_bytes());
    }

    fn put_i64(&mut self, value: i64) {
        self.bytes.extend_from_slice(&value.to_le_bytes());
    }

    fn put_bytes32(&mut self, value: &[u8; 32]) {
        self.bytes.extend_from_slice(value);
    }

    fn put_pubkey(&mut self, value: &Pubkey) {
        self.bytes.extend_from_slice(value.as_ref());
    }

    fn finish(self) -> Vec<u8> {
        self.bytes
    }
}

/// Explicit stable codes.
///
/// These mappings are part of the protocol specification.
/// Never change the code of an existing value in protocol v1.
const fn work_type_code(value: WorkType) -> u8 {
    match value {
        WorkType::Inspection => 0,
        WorkType::Monitoring => 1,
        WorkType::Mapping => 2,
        WorkType::Delivery => 3,
        WorkType::Transport => 4,
        WorkType::Measurement => 5,
        WorkType::Actuation => 6,
        WorkType::Manufacturing => 7,
        WorkType::Compute => 8,
        WorkType::EnergyService => 9,
    }
}

const fn payment_model_code(value: PaymentModel) -> u8 {
    match value {
        PaymentModel::Fixed => 0,
        PaymentModel::Proportional => 1,
    }
}

const fn verification_status_code(value: VerificationStatus) -> u8 {
    match value {
        VerificationStatus::Accepted => 0,
        VerificationStatus::Rejected => 1,
    }
}

impl CanonicalCommitment for WorkOrder {
    const DOMAIN: &'static [u8] = WORK_ORDER_DOMAIN;

    fn canonical_bytes(&self) -> Vec<u8> {
        // Protocol v1 WorkOrder canonical payload = 203 bytes.
        let mut writer = CanonicalWriter::with_capacity(203);

        writer.put_u8(self.protocol_version);
        writer.put_bytes32(&self.work_order_id);
        writer.put_pubkey(&self.creator);

        writer.put_u8(work_type_code(self.work_type));

        writer.put_u64(self.required_capabilities);

        writer.put_u64(self.evidence_requirements);

        writer.put_bytes32(&self.manifest_hash);

        writer.put_pubkey(&self.settlement.token_mint);

        writer.put_u64(self.settlement.total_amount);

        writer.put_u8(payment_model_code(self.settlement.payment_model));

        writer.put_pubkey(&self.settlement.verifier);

        writer.put_i64(self.execution_deadline);

        writer.put_i64(self.verification_deadline);

        writer.finish()
    }
}

impl CanonicalCommitment for EvidenceManifest {
    const DOMAIN: &'static [u8] = EVIDENCE_MANIFEST_DOMAIN;

    fn canonical_bytes(&self) -> Vec<u8> {
        // Protocol v1 EvidenceManifest payload = 297 bytes.
        let mut writer = CanonicalWriter::with_capacity(297);

        writer.put_u8(self.protocol_version);
        writer.put_bytes32(&self.work_order_id);
        writer.put_bytes32(&self.agent_id);

        writer.put_u64(self.provided_evidence);

        writer.put_bytes32(&self.telemetry_hash);

        writer.put_bytes32(&self.gps_trace_hash);

        writer.put_bytes32(&self.image_manifest_hash);

        writer.put_bytes32(&self.video_manifest_hash);

        writer.put_bytes32(&self.sensor_readings_hash);

        writer.put_bytes32(&self.ai_inference_hash);

        writer.put_bytes32(&self.artifact_root);

        writer.finish()
    }
}

impl CanonicalCommitment for ExecutionReceipt {
    const DOMAIN: &'static [u8] = EXECUTION_RECEIPT_DOMAIN;

    fn canonical_bytes(&self) -> Vec<u8> {
        // Protocol v1 ExecutionReceipt payload = 177 bytes.
        let mut writer = CanonicalWriter::with_capacity(177);

        writer.put_u8(self.protocol_version);
        writer.put_bytes32(&self.work_order_id);
        writer.put_bytes32(&self.agent_id);

        writer.put_i64(self.started_at);
        writer.put_i64(self.ended_at);

        writer.put_bytes32(&self.evidence_manifest_hash);

        writer.put_bytes32(&self.software_hash);

        writer.put_bytes32(&self.model_manifest_hash);

        writer.finish()
    }
}

impl CanonicalCommitment for VerificationAttestation {
    const DOMAIN: &'static [u8] = VERIFICATION_ATTESTATION_DOMAIN;

    fn canonical_bytes(&self) -> Vec<u8> {
        // Protocol v1 VerificationAttestation payload = 140 bytes.
        let mut writer = CanonicalWriter::with_capacity(140);

        writer.put_u8(self.protocol_version);
        writer.put_bytes32(&self.work_order_id);

        writer.put_bytes32(&self.receipt_hash);

        writer.put_bytes32(&self.evidence_manifest_hash);

        writer.put_pubkey(&self.verifier);

        writer.put_u8(verification_status_code(self.status));

        writer.put_u16(self.completion_bps);

        writer.put_i64(self.verified_at);

        writer.finish()
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    use crate::{Capability, EvidenceRequirement, PaymentModel, SettlementTerms};

    fn pubkey(value: u8) -> Pubkey {
        Pubkey::new_from_array([value; 32])
    }

    fn work_order_fixture() -> WorkOrder {
        WorkOrder::new(
            [1u8; 32],
            pubkey(2),
            WorkType::Inspection,
            Capability::AerialMobility.bit()
                | Capability::ThermalVision.bit()
                | Capability::Gps.bit(),
            EvidenceRequirement::Telemetry.bit()
                | EvidenceRequirement::GpsTrace.bit()
                | EvidenceRequirement::ImageManifest.bit()
                | EvidenceRequirement::DeviceSignature.bit(),
            [3u8; 32],
            SettlementTerms {
                token_mint: pubkey(4),
                total_amount: 100_000_000,
                payment_model: PaymentModel::Proportional,
                verifier: pubkey(5),
            },
            1_000,
            1_300,
        )
    }

    fn evidence_fixture() -> EvidenceManifest {
        EvidenceManifest::new(
            [1u8; 32],
            [6u8; 32],
            EvidenceRequirement::Telemetry.bit()
                | EvidenceRequirement::GpsTrace.bit()
                | EvidenceRequirement::ImageManifest.bit()
                | EvidenceRequirement::DeviceSignature.bit(),
            [10u8; 32],
            [11u8; 32],
            [12u8; 32],
            [0u8; 32],
            [0u8; 32],
            [0u8; 32],
            [13u8; 32],
        )
    }

    fn receipt_fixture() -> ExecutionReceipt {
        ExecutionReceipt::new(
            [1u8; 32], [6u8; 32], 800, 950, [20u8; 32], [21u8; 32], [22u8; 32],
        )
    }

    fn attestation_fixture() -> VerificationAttestation {
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

    #[test]
    fn canonical_payload_sizes_are_stable() {
        assert_eq!(work_order_fixture().canonical_bytes().len(), 203);

        assert_eq!(evidence_fixture().canonical_bytes().len(), 297);

        assert_eq!(receipt_fixture().canonical_bytes().len(), 177);

        assert_eq!(attestation_fixture().canonical_bytes().len(), 140);
    }

    #[test]
    fn work_order_golden_vector_is_stable() {
        let expected = [
            0xeb, 0xb7, 0x84, 0xef, 0x2a, 0x6d, 0x20, 0x73, 0x87, 0xea, 0x0c, 0xf3, 0x92, 0x4d,
            0x5b, 0x5b, 0x47, 0x41, 0x97, 0xa8, 0xbb, 0xcc, 0x1f, 0x6d, 0x54, 0xa2, 0xc3, 0x2f,
            0x0b, 0x2a, 0x8f, 0x9a,
        ];

        assert_eq!(work_order_fixture().commitment_hash(), expected);
    }

    #[test]
    fn evidence_manifest_golden_vector_is_stable() {
        let expected = [
            0x4f, 0xf2, 0xf4, 0x42, 0xc1, 0x57, 0x6b, 0x26, 0x52, 0xf5, 0xf3, 0x11, 0x56, 0xc2,
            0x95, 0xb6, 0x6c, 0x03, 0xe6, 0x1a, 0x1b, 0x5f, 0x52, 0x93, 0xe6, 0xc2, 0x5a, 0xcf,
            0xf6, 0xfd, 0x30, 0x3a,
        ];

        assert_eq!(evidence_fixture().commitment_hash(), expected);
    }

    #[test]
    fn execution_receipt_golden_vector_is_stable() {
        let expected = [
            0x57, 0x72, 0x54, 0xde, 0xdb, 0x2b, 0x9d, 0x88, 0xd5, 0x10, 0x6b, 0x88, 0x57, 0x1e,
            0x78, 0x13, 0x73, 0xc0, 0xdd, 0xc7, 0x9a, 0xe0, 0x8b, 0x25, 0x54, 0x18, 0x5e, 0x72,
            0x83, 0x75, 0x8c, 0x78,
        ];

        assert_eq!(receipt_fixture().commitment_hash(), expected);
    }

    #[test]
    fn verification_attestation_golden_vector_is_stable() {
        let expected = [
            0x4b, 0xba, 0x29, 0xa7, 0x76, 0xd2, 0x85, 0x6f, 0xb7, 0xf9, 0x08, 0xc1, 0x69, 0xba,
            0xeb, 0x8f, 0x57, 0x95, 0x68, 0xa0, 0x66, 0x4b, 0x05, 0xa4, 0x84, 0xd9, 0xb7, 0xbb,
            0x4c, 0xb5, 0x06, 0xa2,
        ];

        assert_eq!(attestation_fixture().commitment_hash(), expected);
    }

    #[test]
    fn same_payload_different_domain_produces_different_hash() {
        let payload = b"same-payload";

        let work_hash = hash_with_domain(WORK_ORDER_DOMAIN, payload);

        let evidence_hash = hash_with_domain(EVIDENCE_MANIFEST_DOMAIN, payload);

        assert_ne!(work_hash, evidence_hash);
    }

    #[test]
    fn changing_work_order_amount_changes_commitment() {
        let original = work_order_fixture();

        let mut changed = original.clone();
        changed.settlement.total_amount += 1;

        assert_ne!(original.commitment_hash(), changed.commitment_hash());
    }

    #[test]
    fn changing_completion_changes_attestation_commitment() {
        let original = attestation_fixture();

        let mut changed = original.clone();
        changed.completion_bps = 7_351;

        assert_ne!(original.commitment_hash(), changed.commitment_hash());
    }

    #[test]
    fn commitment_is_deterministic() {
        let order = work_order_fixture();

        assert_eq!(order.commitment_hash(), order.commitment_hash());
    }
}
