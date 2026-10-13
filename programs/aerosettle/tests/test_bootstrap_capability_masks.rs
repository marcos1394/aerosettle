use aerosettle::Capability;

#[test]
fn bootstrap_capability_masks_are_valid() {
    let aerial = Capability::AerialMobility.bit();
    let gps = Capability::Gps.bit();
    let telemetry = Capability::Telemetry.bit();

    assert!(aerial.is_power_of_two());
    assert!(gps.is_power_of_two());
    assert!(telemetry.is_power_of_two());

    assert_ne!(aerial, gps);
    assert_ne!(aerial, telemetry);
    assert_ne!(gps, telemetry);

    println!(
        "AEROSETTLE_CAPABILITIES aerial={} gps={} telemetry={}",
        aerial, gps, telemetry
    );
}
