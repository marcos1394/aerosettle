//! Canonical VerificationAttestation hash for Localnet.
use aerosettle::{CanonicalCommitment, VerificationAttestation, VerificationStatus};
use anchor_lang::prelude::Pubkey;
use std::{env, str::FromStr};

fn hex32(name: &str) -> [u8; 32] {
    let value = env::var(name).expect("missing input");
    assert_eq!(value.len(), 64, "{name} must have 64 hex characters");

    let mut output = [0u8; 32];

    for (index, chunk) in value.as_bytes().chunks_exact(2).enumerate() {
        let pair = std::str::from_utf8(chunk).expect("invalid UTF-8");
        output[index] = u8::from_str_radix(pair, 16).expect("invalid hex byte");
    }

    output
}

fn main() {
    let order_id = hex32("AEROSETTLE_ATTEST_WORK_ORDER_ID");
    let receipt = hex32("AEROSETTLE_ATTEST_RECEIPT_HASH");
    let manifest = hex32("AEROSETTLE_ATTEST_MANIFEST_HASH");

    let verifier =
        Pubkey::from_str(&env::var("AEROSETTLE_ATTEST_VERIFIER").expect("missing verifier"))
            .expect("invalid verifier");

    let verified_at: i64 = env::var("AEROSETTLE_ATTEST_VERIFIED_AT")
        .expect("missing timestamp")
        .parse()
        .expect("invalid i64");

    let attestation = VerificationAttestation::new(
        order_id,
        receipt,
        manifest,
        verifier,
        VerificationStatus::Accepted,
        10_000,
        verified_at,
    );

    let digest = attestation.commitment_hash();

    let hex: String = digest.iter().map(|b| format!("{b:02x}")).collect();

    println!("AEROSETTLE_ATTESTATION_HASH={hex}");
}
