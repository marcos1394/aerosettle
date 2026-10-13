/// Prefix for the token vault that economically backs one WorkOrder.
///
/// PDA:
///
/// [
///     b"escrow",
///     work_order
/// ]
pub const ESCROW_VAULT_SEED: &[u8] = b"escrow";
