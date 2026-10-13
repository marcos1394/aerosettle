use aerosettle::EvidenceRequirement;

#[test]
fn bootstrap_evidence_mask_is_valid() {
    let telemetry = EvidenceRequirement::Telemetry.bit();
    let gps = EvidenceRequirement::GpsTrace.bit();
    let images = EvidenceRequirement::ImageManifest.bit();
    let signature = EvidenceRequirement::DeviceSignature.bit();

    let mask = telemetry | gps | images | signature;

    assert_ne!(mask, 0);
    assert_eq!(mask.count_ones(), 4);

    println!("AEROSETTLE_EVIDENCE_MASK={mask}");
}
