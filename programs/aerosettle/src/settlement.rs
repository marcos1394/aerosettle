use crate::{PaymentModel, VerificationStatus};

/// Exact distribution of a previously funded escrow.
///
/// Amounts are expressed in the mint's smallest units.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct EscrowAllocation {
    pub operator_amount: u64,
    pub creator_refund: u64,
}

impl EscrowAllocation {
    /// Returns None when the payout exceeds available escrow.
    #[must_use]
    pub fn new(total_amount: u64, operator_amount: u64) -> Option<Self> {
        let creator_refund = total_amount.checked_sub(operator_amount)?;

        Some(Self {
            operator_amount,
            creator_refund,
        })
    }

    /// Ensure there is no value creation or loss
    /// in the planned distribution.
    #[must_use]
    pub fn conserves_value(&self, total_amount: u64) -> bool {
        self.operator_amount.checked_add(self.creator_refund) == Some(total_amount)
    }
}

/// Allocates escrow using a payout independently calculated
/// by the protocol's verified settlement terms.
///
/// `verified_operator_payout` must come from the protocol's
/// economic policy, never directly from an untrusted client.
///
/// Rejected work always refunds all escrow to the creator.
#[must_use]
pub fn allocation_for_verification(
    status: &VerificationStatus,
    total_amount: u64,
    verified_operator_payout: u64,
) -> Option<EscrowAllocation> {
    if status == &VerificationStatus::Rejected {
        EscrowAllocation::new(total_amount, 0)
    } else if status == &VerificationStatus::Accepted {
        EscrowAllocation::new(total_amount, verified_operator_payout)
    } else {
        None
    }
}

/// Apply the existing Fixed/Proportional settlement semantics.
#[must_use]
pub fn verified_operator_payout(
    model: &PaymentModel,
    status: &VerificationStatus,
    total_amount: u64,
    completion_bps: u16,
) -> Option<u64> {
    if completion_bps > 10_000 {
        return None;
    }

    if status == &VerificationStatus::Rejected {
        return if completion_bps == 0 { Some(0) } else { None };
    }

    if status != &VerificationStatus::Accepted {
        return None;
    }

    if model == &PaymentModel::Fixed {
        return Some(if completion_bps == 10_000 {
            total_amount
        } else {
            0
        });
    }

    if model == &PaymentModel::Proportional {
        let numerator = u128::from(total_amount).checked_mul(u128::from(completion_bps))?;

        let payout = numerator / 10_000u128;

        return u64::try_from(payout).ok();
    }

    None
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn accepted_partial_completion_conserves_value() {
        let result =
            allocation_for_verification(&VerificationStatus::Accepted, 100_000_000, 73_500_000)
                .unwrap();

        assert_eq!(result.operator_amount, 73_500_000);
        assert_eq!(result.creator_refund, 26_500_000);
        assert!(result.conserves_value(100_000_000));
    }

    #[test]
    fn rejected_work_refunds_everything() {
        let result =
            allocation_for_verification(&VerificationStatus::Rejected, 100_000_000, 73_500_000)
                .unwrap();

        assert_eq!(result.operator_amount, 0);
        assert_eq!(result.creator_refund, 100_000_000);
        assert!(result.conserves_value(100_000_000));
    }

    #[test]
    fn accepted_full_payout_has_no_refund() {
        let result =
            allocation_for_verification(&VerificationStatus::Accepted, 100_000_000, 100_000_000)
                .unwrap();

        assert_eq!(result.operator_amount, 100_000_000);
        assert_eq!(result.creator_refund, 0);
        assert!(result.conserves_value(100_000_000));
    }

    #[test]
    fn payout_cannot_exceed_funded_escrow() {
        assert!(allocation_for_verification(&VerificationStatus::Accepted, 100, 101,).is_none());
    }

    #[test]
    fn zero_payout_refunds_entire_balance() {
        let result = EscrowAllocation::new(100, 0).unwrap();

        assert_eq!(result.operator_amount, 0);
        assert_eq!(result.creator_refund, 100);
        assert!(result.conserves_value(100));
    }

    #[test]
    fn full_u64_amount_is_supported() {
        let result = EscrowAllocation::new(u64::MAX, u64::MAX - 1).unwrap();

        assert_eq!(result.creator_refund, 1);
        assert!(result.conserves_value(u64::MAX));
    }

    #[test]
    fn over_allocation_is_rejected() {
        assert!(EscrowAllocation::new(0, 1).is_none());
    }
}
