//! EPIC 3.3.2 — off-chain bridge to the original Rust engine.
//! Read-only, stdio, no new dependencies.
use aerosettle::{
    discover_eligible_agents, evaluate_agent, AgentListing, MatchRejection, OrderListing,
};
use anchor_lang::prelude::Pubkey;
use std::{
    collections::HashSet,
    io::{self, Read},
    str::FromStr,
};

fn record<'a>(line: &'a str, name: &str, count: usize) -> Result<Vec<&'a str>, String> {
    let parts: Vec<_> = line.split('|').collect();

    if parts.len() != count || parts[0] != name {
        return Err(format!("invalid {name} record"));
    }

    Ok(parts)
}

fn parse_bool(s: &str) -> Result<bool, String> {
    match s {
        "0" => Ok(false),
        "1" => Ok(true),
        _ => Err("invalid boolean".into()),
    }
}

fn parse_pubkey(s: &str) -> Result<Pubkey, String> {
    Pubkey::from_str(s).map_err(|_| "invalid pubkey".into())
}

fn parse_id(s: &str) -> Result<[u8; 32], String> {
    if s.len() != 64 || !s.is_ascii() {
        return Err("invalid agent_id length".into());
    }

    let mut id = [0u8; 32];

    for (index, pair) in s.as_bytes().chunks_exact(2).enumerate() {
        let item = std::str::from_utf8(pair).map_err(|_| "invalid UTF-8")?;

        id[index] = u8::from_str_radix(item, 16).map_err(|_| "invalid agent_id hex")?;
    }

    Ok(id)
}

fn rejection_code(rejection: MatchRejection) -> String {
    match rejection {
        MatchRejection::ProtocolPaused => "PROTOCOL_PAUSED".into(),
        MatchRejection::WorkOrderNotOpen => "WORK_ORDER_NOT_OPEN".into(),
        MatchRejection::ExecutionDeadlineReached => "EXECUTION_DEADLINE_REACHED".into(),
        MatchRejection::DifferentProtocol => "DIFFERENT_PROTOCOL".into(),
        MatchRejection::AgentInactive => "AGENT_INACTIVE".into(),
        MatchRejection::MissingCapabilities { missing_mask } => {
            format!("MISSING_CAPABILITIES|{missing_mask}")
        }
    }
}

fn run() -> Result<(), String> {
    const MAX_INPUT: usize = 1_048_576;
    const MAX_AGENTS: usize = 500;

    let mut input = String::new();

    io::stdin()
        .take((MAX_INPUT + 1) as u64)
        .read_to_string(&mut input)
        .map_err(|e| e.to_string())?;

    if input.len() > MAX_INPUT {
        return Err("input exceeds maximum size".into());
    }

    let mut lines = input.lines();

    if lines.next() != Some("AEROSETTLE_MATCH_V1") {
        return Err("invalid protocol version".into());
    }

    let paused = record(lines.next().ok_or("missing paused")?, "paused", 2)?;

    let protocol_paused = parse_bool(paused[1])?;

    let time = record(lines.next().ok_or("missing timestamp")?, "now", 2)?;

    let now_unix: i64 = time[1].parse().map_err(|_| "invalid timestamp")?;

    let raw_order = record(lines.next().ok_or("missing order")?, "order", 5)?;

    let order = OrderListing {
        protocol_config: parse_pubkey(raw_order[1])?,
        is_open: parse_bool(raw_order[2])?,
        required_capabilities: raw_order[3]
            .parse()
            .map_err(|_| "invalid order capabilities")?,
        execution_deadline: raw_order[4]
            .parse()
            .map_err(|_| "invalid execution deadline")?,
    };

    let header = record(lines.next().ok_or("missing agents header")?, "agents", 2)?;

    let count: usize = header[1].parse().map_err(|_| "invalid agent count")?;

    if count > MAX_AGENTS {
        return Err("too many agents".into());
    }

    let mut agents = Vec::with_capacity(count);
    let mut seen_accounts = HashSet::new();
    let mut seen_ids = HashSet::new();

    for _ in 0..count {
        let raw = record(lines.next().ok_or("missing agent")?, "agent", 6)?;

        let listing = AgentListing {
            agent_account: parse_pubkey(raw[1])?,
            agent_id: parse_id(raw[2])?,
            protocol_config: parse_pubkey(raw[3])?,
            capabilities: raw[4].parse().map_err(|_| "invalid agent capabilities")?,
            active: parse_bool(raw[5])?,
        };

        if !seen_accounts.insert(listing.agent_account) || !seen_ids.insert(listing.agent_id) {
            return Err("duplicate agent identity".into());
        }

        agents.push(listing);
    }

    if lines.next() != Some("END") || lines.next().is_some() {
        return Err("invalid input terminator".into());
    }

    let mut output = vec!["AEROSETTLE_MATCH_RESULT_V1".to_string()];

    // Authoritative off-chain predicate from EPIC 3.1.
    for agent in &agents {
        let result = evaluate_agent(&order, agent, protocol_paused, now_unix);

        let decision = match result {
            Ok(()) => "ELIGIBLE".to_string(),
            Err(reason) => rejection_code(reason),
        };

        output.push(format!("evaluation|{}|{}", agent.agent_account, decision));
    }

    // Original Rust discovery ordering and deduplication.
    let shortlisted = discover_eligible_agents(&order, &agents, protocol_paused, now_unix);

    for agent in shortlisted {
        output.push(format!("shortlist|{}", agent.agent_account));
    }

    output.push("END".to_string());

    println!("{}", output.join("\n"));
    Ok(())
}

fn main() {
    if let Err(error) = run() {
        eprintln!("AEROSETTLE_MATCH_ERROR: {error}");
        std::process::exit(1);
    }
}
