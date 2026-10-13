//! EPIC 3.1 — deterministic, off-chain marketplace eligibility.
//!
//! This module does not mutate accounts or claim work. The Solana program's
//! `claim_work_order` instruction is the final authority for authorization.

use anchor_lang::prelude::Pubkey;

use crate::{AgentAccount, WorkOrderAccount, WorkOrderStatus};

/// Minimal, queryable projection of a WorkOrder for discovery.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct OrderListing {
    pub protocol_config: Pubkey,
    pub is_open: bool,
    pub required_capabilities: u64,
    pub execution_deadline: i64,
}

impl From<&WorkOrderAccount> for OrderListing {
    fn from(order: &WorkOrderAccount) -> Self {
        Self {
            protocol_config: order.protocol_config,
            is_open: order.status == WorkOrderStatus::Open,
            required_capabilities: order.required_capabilities,
            execution_deadline: order.execution_deadline,
        }
    }
}

/// Account pubkey is supplied by a trusted RPC decoder/indexer; it is not
/// assumed to be stored inside AgentAccount itself.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct AgentListing {
    pub agent_account: Pubkey,
    pub agent_id: [u8; 32],
    pub protocol_config: Pubkey,
    pub capabilities: u64,
    pub active: bool,
}

impl AgentListing {
    #[must_use]
    pub fn from_chain(agent_account: Pubkey, agent: &AgentAccount) -> Self {
        Self {
            agent_account,
            agent_id: agent.agent_id,
            protocol_config: agent.protocol_config,
            capabilities: agent.capabilities,
            active: agent.is_active(),
        }
    }
}

/// An eligibility rejection is an explanation, NOT an on-chain error code.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum MatchRejection {
    ProtocolPaused,
    WorkOrderNotOpen,
    ExecutionDeadlineReached,
    DifferentProtocol,
    AgentInactive,
    MissingCapabilities { missing_mask: u64 },
}

/// Pure deterministic predicate. A matching result is advisory: do not treat
/// it as authorization to skip the checks in `claim_work_order`.
pub fn evaluate_agent(
    order: &OrderListing,
    agent: &AgentListing,
    protocol_paused: bool,
    now_unix: i64,
) -> Result<(), MatchRejection> {
    if protocol_paused {
        return Err(MatchRejection::ProtocolPaused);
    }

    if !order.is_open {
        return Err(MatchRejection::WorkOrderNotOpen);
    }

    // Conservative boundary: do not recommend new work at its deadline.
    if now_unix >= order.execution_deadline {
        return Err(MatchRejection::ExecutionDeadlineReached);
    }

    if agent.protocol_config != order.protocol_config {
        return Err(MatchRejection::DifferentProtocol);
    }

    if !agent.active {
        return Err(MatchRejection::AgentInactive);
    }

    let missing_mask = order.required_capabilities & !agent.capabilities;
    if missing_mask != 0 {
        return Err(MatchRejection::MissingCapabilities { missing_mask });
    }

    Ok(())
}

/// Return the eligible listings in deterministic ID/address order.
///
/// Sorting here is stable *discovery ordering*, not a quality or pricing rank.
/// The indexer must validate program ownership, Anchor account decoding and
/// PDA derivation before constructing these listings.
#[must_use]
pub fn discover_eligible_agents(
    order: &OrderListing,
    agents: &[AgentListing],
    protocol_paused: bool,
    now_unix: i64,
) -> Vec<AgentListing> {
    let mut eligible: Vec<AgentListing> = agents
        .iter()
        .copied()
        .filter(|agent| evaluate_agent(order, agent, protocol_paused, now_unix).is_ok())
        .collect();

    eligible.sort_unstable_by_key(|agent| (agent.agent_id, agent.agent_account.to_bytes()));
    eligible.dedup_by(|a, b| a.agent_id == b.agent_id);
    eligible
}

#[cfg(test)]
mod tests {
    use super::*;

    fn config() -> Pubkey {
        Pubkey::new_from_array([1u8; 32])
    }

    fn order() -> OrderListing {
        OrderListing {
            protocol_config: config(),
            is_open: true,
            required_capabilities: 0b0011,
            execution_deadline: 1_000,
        }
    }

    fn agent(id: u8, mask: u64) -> AgentListing {
        AgentListing {
            agent_account: Pubkey::new_from_array([id; 32]),
            agent_id: [id; 32],
            protocol_config: config(),
            capabilities: mask,
            active: true,
        }
    }

    #[test]
    fn exact_capability_set_is_eligible() {
        assert_eq!(
            evaluate_agent(&order(), &agent(1, 0b0011), false, 100),
            Ok(())
        );
    }

    #[test]
    fn extra_capabilities_are_allowed() {
        assert_eq!(
            evaluate_agent(&order(), &agent(1, 0b1111), false, 100),
            Ok(())
        );
    }

    #[test]
    fn missing_capabilities_are_precisely_reported() {
        assert_eq!(
            evaluate_agent(&order(), &agent(1, 0b0001), false, 100),
            Err(MatchRejection::MissingCapabilities {
                missing_mask: 0b0010
            }),
        );
    }

    #[test]
    fn inactive_agent_is_rejected() {
        let mut candidate = agent(1, 0b0011);
        candidate.active = false;
        assert_eq!(
            evaluate_agent(&order(), &candidate, false, 100),
            Err(MatchRejection::AgentInactive),
        );
    }

    #[test]
    fn cross_protocol_agent_is_rejected() {
        let mut candidate = agent(1, 0b0011);
        candidate.protocol_config = Pubkey::new_from_array([7u8; 32]);
        assert_eq!(
            evaluate_agent(&order(), &candidate, false, 100),
            Err(MatchRejection::DifferentProtocol),
        );
    }

    #[test]
    fn draft_order_is_not_discoverable() {
        let mut listing = order();
        listing.is_open = false;
        assert_eq!(
            evaluate_agent(&listing, &agent(1, 0b0011), false, 100),
            Err(MatchRejection::WorkOrderNotOpen),
        );
    }

    #[test]
    fn claimed_order_is_not_discoverable() {
        let mut listing = order();
        listing.is_open = false;
        assert_eq!(
            evaluate_agent(&listing, &agent(1, 0b0011), false, 100),
            Err(MatchRejection::WorkOrderNotOpen),
        );
    }

    #[test]
    fn paused_protocol_is_not_discoverable() {
        assert_eq!(
            evaluate_agent(&order(), &agent(1, 0b0011), true, 100),
            Err(MatchRejection::ProtocolPaused),
        );
    }

    #[test]
    fn deadline_is_exclusive() {
        assert_eq!(
            evaluate_agent(&order(), &agent(1, 0b0011), false, 999),
            Ok(())
        );
        assert_eq!(
            evaluate_agent(&order(), &agent(1, 0b0011), false, 1_000),
            Err(MatchRejection::ExecutionDeadlineReached),
        );
    }

    #[test]
    fn expired_work_is_rejected() {
        assert_eq!(
            evaluate_agent(&order(), &agent(1, 0b0011), false, 1_001),
            Err(MatchRejection::ExecutionDeadlineReached),
        );
    }

    #[test]
    fn shortlist_filters_sorts_and_deduplicates() {
        let mut inactive = agent(4, 0b0011);
        inactive.active = false;
        let candidates = [
            agent(9, 0b0011),
            agent(2, 0b0011),
            agent(2, 0b0011),
            agent(3, 0b0001),
            inactive,
        ];
        let result = discover_eligible_agents(&order(), &candidates, false, 500);
        assert_eq!(result.len(), 2);
        assert_eq!(result[0].agent_id, [2; 32]);
        assert_eq!(result[1].agent_id, [9; 32]);
    }

    #[test]
    fn no_matching_agents_returns_empty_shortlist() {
        let candidates = [agent(1, 0b0001), agent(2, 0b0100)];
        assert!(discover_eligible_agents(&order(), &candidates, false, 500).is_empty());
    }

    #[test]
    fn paused_protocol_returns_empty_shortlist() {
        let candidates = [agent(1, 0b0011)];
        assert!(discover_eligible_agents(&order(), &candidates, true, 500).is_empty());
    }
}
