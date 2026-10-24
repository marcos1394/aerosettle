"""OpenAPI 3.1.1 specification for AeroSettle Marketplace API."""

from __future__ import annotations

import json
from pathlib import Path


def ref(name):
    return {"$ref": f"#/components/schemas/{name}"}


def parameter_ref(name):
    return {"$ref": f"#/components/parameters/{name}"}


def response(schema, description="Successful response"):
    return {
        "description": description,
        "content": {
            "application/json": {
                "schema": schema,
            }
        },
    }


def operation(summary, schema, parameters=(), paged=False):
    responses = {
        "200": response(schema),
        "400": response(ref("Error"), "Invalid request"),
        "404": response(ref("Error"), "Not found"),
        "502": response(
            ref("Error"), "RPC or matching engine failure"
        ),
    }

    if paged:
        responses["409"] = response(
            ref("Error"), "Cursor no longer matches results"
        )

    return {
        "summary": summary,
        "parameters": [
            parameter_ref(name)
            for name in parameters
        ],
        "responses": responses,
    }


def policy_write(summary, schema):
    result = operation(summary, schema, ("AgentId", "EconomicSigner", "EconomicTimestamp", "EconomicSignature"))
    result["requestBody"] = {"required": True, "content": {"application/json": {"schema": ref("BudgetPolicyMutation")}}}
    result["responses"].update({
        "201": response(schema, "Policy created"),
        "401": response(ref("Error"), "Invalid mutation signature"),
        "403": response(ref("Error"), "Signer is not current owner"),
        "409": response(ref("Error"), "Version, nonce, or idempotency conflict"),
        "422": response(ref("Error"), "Invalid policy transition or context"),
    })
    return result


def spending_write():
    result = operation("Evaluate a signed spending proposal without moving funds", ref("SpendingDecisionResponse"),
                       ("AgentId", "EconomicSigner", "EconomicTimestamp", "EconomicSignature"))
    result["requestBody"] = {"required": True, "content": {"application/json": {"schema": ref("SpendingProposal")}}}
    result["responses"].update({
        "201": response(ref("SpendingDecisionResponse"), "New advisory decision recorded"),
        "401": response(ref("Error"), "Invalid evaluation signature"),
        "403": response(ref("Error"), "Requester is not current owner or device signing authority"),
        "409": response(ref("Error"), "Idempotency or policy version conflict"),
        "422": response(ref("Error"), "Invalid monetary context"),
        "503": response(ref("Error"), "Required identity or economic source unavailable"),
    })
    return result


def approval_write(summary, with_id=False):
    result = operation(summary, ref("SpendingApprovalResponse"),
                       (("AgentId", "ApprovalId") if with_id else ("AgentId",)) +
                       ("EconomicSigner", "EconomicTimestamp", "EconomicSignature"))
    result["requestBody"] = {"required": True, "content": {"application/json": {"schema": ref("SpendingApprovalMutation")}}}
    result["responses"].update({
        "201": response(ref("SpendingApprovalResponse"), "Owner review opened"),
        "401": response(ref("Error"), "Invalid or expired owner signature"),
        "403": response(ref("Error"), "Signer is not current AgentAccount owner"),
        "409": response(ref("Error"), "Identity, policy, idempotency, or concurrent state conflict"),
        "422": response(ref("Error"), "Forbidden approval transition or denied decision"),
    })
    return result


def build():
    uint64 = {
        "type": "string",
        "pattern": "^(0|[1-9][0-9]*)$",
        "description": "Unsigned u64 encoded as decimal string",
        "maxLength": 20,
    }

    pubkey = {
        "type": "string",
        "pattern": "^[1-9A-HJ-NP-Za-km-z]{32,44}$",
        "description": "Base58-encoded Solana public key",
    }

    schemas = {
        "Pubkey": pubkey,
        "Uint64": uint64,
        "AssetBudgetRule": {
            "type": "object", "additionalProperties": False,
            "required": ["token_mint", "max_per_operation_base_units_str", "max_daily_spend_base_units_str",
                         "minimum_reserve_base_units_str", "enabled"],
            "properties": {
                "token_mint": ref("Pubkey"),
                "max_per_operation_base_units_str": ref("Uint64"),
                "max_daily_spend_base_units_str": ref("Uint64"),
                "minimum_reserve_base_units_str": ref("Uint64"),
                "enabled": {"type": "boolean"},
            },
        },
        "BudgetPolicyMutation": {
            "type": "object",
            "description": "Create/update require all configuration fields; lifecycle actions require only control fields.",
            "properties": {
                "expected_version": {"type": "integer", "minimum": 0},
                "idempotency_key": {"type": "string"}, "nonce": {"type": "string"},
                "revision_reason": {"type": "string"},
                "network": {"type": "string"}, "genesis_hash": ref("Pubkey"),
                "program_id": ref("Pubkey"),
                "asset_rules": {"type": "array", "items": ref("AssetBudgetRule")},
                "allowed_recipients": {"type": "array", "items": ref("Pubkey")},
                "valid_from": {"type": "integer"}, "expires_at": {"type": "integer"},
            }, "additionalProperties": False,
        },
        "AgentBudgetPolicy": {
            "type": "object", "required": ["policy_id", "agent_account", "owner_pubkey", "version", "status",
                                            "asset_rules", "allowed_recipients", "policy_hash", "network",
                                            "genesis_hash", "program_id", "valid_from", "expires_at"],
            "properties": {
                "policy_id": {"type": "string"}, "agent_account": ref("Pubkey"),
                "agent_id": {"type": "string"}, "owner_pubkey": ref("Pubkey"),
                "network": {"type": "string"}, "genesis_hash": ref("Pubkey"), "program_id": ref("Pubkey"),
                "version": {"type": "integer", "minimum": 1},
                "status": {"type": "string", "enum": ["DRAFT", "ACTIVE", "PAUSED", "REVOKED"]},
                "effective_status": {"type": "string", "enum": ["DRAFT", "ACTIVE", "PAUSED", "REVOKED", "EXPIRED"]},
                "asset_rules": {"type": "array", "items": ref("AssetBudgetRule")},
                "allowed_recipients": {"type": "array", "items": ref("Pubkey")},
                "valid_from": {"type": "integer"}, "expires_at": {"type": "integer"},
                "policy_hash": {"type": "string", "pattern": "^[a-f0-9]{64}$"},
                "reserve_comparison": {"type": "array", "description": "Off-chain policy target compared with separate ledger records"},
            }, "additionalProperties": True,
        },
        "BudgetPolicyResponse": {"type": "object", "properties": {"data": ref("AgentBudgetPolicy"), "meta": ref("Meta")}},
        "BudgetPolicyHistoryResponse": {"type": "object", "properties": {"data": {"type": "array", "items": ref("AgentBudgetPolicy")}, "meta": ref("Meta")}},
        "SpendingProposal": {
            "type": "object", "additionalProperties": False,
            "required": ["proposal_id", "idempotency_key", "nonce", "agent_account", "agent_id",
                         "requester_pubkey", "network", "genesis_hash", "program_id", "token_mint",
                         "recipient_pubkey", "amount_base_units_str", "purpose", "requested_at",
                         "expected_policy_id", "expected_policy_version", "expected_policy_hash", "metadata"],
            "properties": {
                "proposal_id": {"type": "string"}, "idempotency_key": {"type": "string"}, "nonce": {"type": "string"},
                "agent_account": ref("Pubkey"), "agent_id": {"type": "string", "pattern": "^[a-fA-F0-9]{64}$"},
                "requester_pubkey": ref("Pubkey"), "network": {"type": "string"},
                "genesis_hash": ref("Pubkey"), "program_id": ref("Pubkey"), "token_mint": ref("Pubkey"),
                "recipient_pubkey": ref("Pubkey"), "amount_base_units_str": ref("Uint64"),
                "purpose": {"type": "string", "minLength": 1, "maxLength": 500},
                "requested_at": {"type": "integer"}, "expected_policy_id": {"type": "string"},
                "expected_policy_version": {"type": "integer", "minimum": 1},
                "expected_policy_hash": {"type": "string", "pattern": "^[a-f0-9]{64}$"},
                "metadata": {"type": "object"},
            },
        },
        "SpendingDecisionReason": {"type": "object", "properties": {"code": {"type": "string"}}},
        "SpendingBudgetSnapshot": {"type": "object", "properties": {
            "daily_window_start_utc": {"type": "integer"}, "daily_window_end_utc": {"type": "integer"},
            "daily_limit_base_units_str": {"type": ["string", "null"]},
            "daily_used_base_units_str": {"type": ["string", "null"]},
            "daily_committed_base_units_str": {"type": ["string", "null"]},
            "daily_remaining_base_units_str": {"type": ["string", "null"]},
        }},
        "SpendingDecision": {"type": "object", "required": ["decision_id", "proposal_id", "agent_account",
            "decision", "reason_codes", "policy_id", "policy_version", "policy_hash",
            "economic_snapshot_hash", "economic_evidence_status", "evaluated_at", "expires_at",
            "is_executable", "is_currently_applicable"],
            "properties": {
                "decision_id": {"type": "string"}, "proposal_id": {"type": "string"},
                "agent_account": ref("Pubkey"),
                "decision": {"type": "string", "enum": ["ALLOW", "DENY", "REQUIRE_APPROVAL"]},
                "reason_codes": {"type": "array", "items": {"type": "string"}},
                "reason_details": {"type": "array", "items": ref("SpendingDecisionReason")},
                "policy_id": {"type": ["string", "null"]}, "policy_version": {"type": ["integer", "null"]},
                "policy_hash": {"type": ["string", "null"]},
                "network": {"type": "string"}, "genesis_hash": ref("Pubkey"),
                "program_id": ref("Pubkey"), "token_mint": ref("Pubkey"),
                "requested_amount_base_units_str": ref("Uint64"),
                "minimum_reserve_base_units_str": {"type": ["string", "null"]},
                "accounting_reserved_base_units_str": {"type": ["string", "null"]},
                "available_liquidity_base_units_str": {"type": ["string", "null"]},
                "accrued_obligations_base_units_str": {"type": ["string", "null"]},
                "economic_evidence_status": {"type": "string"},
                "economic_snapshot_hash": {"type": "string"},
                "evaluated_at": {"type": "integer"}, "expires_at": {"type": "integer"},
                "decision_engine_version": {"type": "string"},
                "is_executable": {"const": False}, "historical": {"type": "boolean"},
                "is_currently_applicable": {"type": "boolean"},
            }, "additionalProperties": True},
        "SpendingDecisionResponse": {"type": "object", "properties": {"data": ref("SpendingDecision"), "meta": ref("Meta")}},
        "SpendingDecisionListResponse": {"type": "object", "properties": {"data": {"type": "array", "items": ref("SpendingDecision")}, "meta": ref("Meta")}},
        "SpendingApprovalMutation": {
            "type": "object", "additionalProperties": False,
            "required": ["agent_account", "agent_id", "owner_pubkey", "proposal_id", "proposal_hash",
                         "decision_id", "decision_hash", "policy_id", "policy_version", "policy_hash",
                         "network", "genesis_hash", "program_id", "token_mint", "recipient_pubkey",
                         "amount_base_units_str", "economic_snapshot_hash", "action", "issued_at",
                         "expires_at", "nonce", "idempotency_key", "reason"],
            "properties": {
                "agent_account": ref("Pubkey"), "agent_id": {"type": "string"},
                "owner_pubkey": ref("Pubkey"), "proposal_id": {"type": "string"},
                "proposal_hash": {"type": "string"}, "decision_id": {"type": "string"},
                "decision_hash": {"type": "string"}, "policy_id": {"type": "string"},
                "policy_version": {"type": "integer"}, "policy_hash": {"type": "string"},
                "network": {"type": "string"}, "genesis_hash": ref("Pubkey"),
                "program_id": ref("Pubkey"), "token_mint": ref("Pubkey"),
                "recipient_pubkey": ref("Pubkey"), "amount_base_units_str": ref("Uint64"),
                "economic_snapshot_hash": {"type": "string"},
                "action": {"type": "string", "enum": ["OPEN", "APPROVE", "REJECT", "REVOKE"]},
                "issued_at": {"type": "integer"}, "expires_at": {"type": "integer"},
                "nonce": {"type": "string"}, "idempotency_key": {"type": "string"},
                "reason": {"type": "string", "maxLength": 500},
            },
        },
        "SpendingApproval": {"type": "object", "required": ["approval_id", "proposal_id", "decision_id",
            "approval_status", "effective_status", "financial_eligibility", "is_executable"],
            "properties": {
                "approval_id": {"type": "string"}, "proposal_id": {"type": "string"},
                "decision_id": {"type": "string"}, "agent_account": ref("Pubkey"),
                "owner_pubkey": ref("Pubkey"), "amount_base_units_str": ref("Uint64"),
                "approval_status": {"type": "string"}, "effective_status": {"type": "string"},
                "financial_eligibility": {"type": "string"},
                "is_currently_applicable": {"type": "boolean"}, "is_executable": {"const": False},
            }, "additionalProperties": True},
        "SpendingApprovalEvent": {"type": "object", "properties": {
            "event_id": {"type": "string"}, "approval_id": {"type": "string"},
            "action": {"type": "string"}, "actor_pubkey": ref("Pubkey"),
            "signature": {"type": "string"}, "signature_message_hash": {"type": "string"},
            "signature_message": {"type": "string"}, "signed_body_json": {"type": "string"},
            "event_hash": {"type": "string"}, "previous_event_hash": {"type": ["string", "null"]},
        }, "additionalProperties": True},
        "SpendingApprovalContext": {"type": "object", "properties": {
            "approval_id": {"type": "string"}, "proposal": ref("SpendingProposal"),
            "decision": ref("SpendingDecision"), "proposal_hash": {"type": "string"},
            "decision_hash": {"type": "string"},
        }, "additionalProperties": True},
        "SpendingApprovalResponse": {"type": "object", "properties": {"data": ref("SpendingApproval"), "meta": ref("Meta")}},
        "SpendingApprovalListResponse": {"type": "object", "properties": {
            "data": {"type": "array", "items": ref("SpendingApproval")}, "meta": ref("Meta")}},
        "SpendingApprovalHistoryResponse": {"type": "object", "properties": {
            "data": {"type": "array", "items": ref("SpendingApprovalEvent")}, "meta": ref("Meta")}},
        "SpendingApprovalContextResponse": {"type": "object", "properties": {"data": ref("SpendingApprovalContext"), "meta": ref("Meta")}},
        "Agent": {
            "type": "object",
            "required": [
                "agent_account",
                "agent_id",
                "protocol_config",
                "capabilities",
                "active",
                "status",
            ],
            "properties": {
                "agent_account": ref("Pubkey"),
                "agent_id": {
                    "type": "string",
                    "pattern": "^[a-fA-F0-9]{64}$",
                },
                "owner": ref("Pubkey"), "signing_authority": ref("Pubkey"),
                "protocol_config": ref("Pubkey"),
                "capabilities": ref("Uint64"),
                "active": {"type": "boolean"},
                "status": {"type": "string"},
            },
            "additionalProperties": True,
        },
        "WorkOrder": {
            "type": "object",
            "required": [
                "work_order_account",
                "protocol_config",
                "required_capabilities",
                "execution_deadline",
                "is_open",
                "status",
                "discoverable",
            ],
            "properties": {
                "work_order_account": ref("Pubkey"),
                "protocol_config": ref("Pubkey"),
                "required_capabilities": ref("Uint64"),
                "execution_deadline": {
                    "type": "integer",
                    "format": "int64",
                },
                "is_open": {"type": "boolean"},
                "status": {"type": "string"},
                "discoverable": {"type": "boolean"},
            },
            "additionalProperties": True,
        },
        "Page": {
            "type": "object",
            "required": [
                "limit", "has_more", "next_cursor"
            ],
            "properties": {
                "limit": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 100,
                },
                "has_more": {"type": "boolean"},
                "next_cursor": {
                    "type": ["string", "null"],
                    "maxLength": 2048,
                },
            },
        },
        "Meta": {
            "type": "object",
            "properties": {
                "program_id": ref("Pubkey"),
                "commitment": {"type": "string"},
                "chain_now_unix": {"type": "integer"},
                "rpc_context_slots": {"type": "object"},
                "atomic_snapshot": {"type": "boolean"},
                "read_only": {"type": "boolean"},
                "matching_engine": {"type": "string"},
            },
            "additionalProperties": True,
        },
        "AgentPage": {
            "type": "object",
            "required": [
                "data", "count", "total_count", "page", "meta"
            ],
            "properties": {
                "data": {
                    "type": "array",
                    "items": ref("Agent"),
                },
                "count": {"type": "integer"},
                "total_count": {"type": "integer"},
                "page": ref("Page"),
                "meta": ref("Meta"),
            },
        },
        "WorkOrderPage": {
            "type": "object",
            "required": [
                "data", "count", "total_count", "page", "meta"
            ],
            "properties": {
                "data": {
                    "type": "array",
                    "items": ref("WorkOrder"),
                },
                "count": {"type": "integer"},
                "total_count": {"type": "integer"},
                "page": ref("Page"),
                "meta": ref("Meta"),
            },
        },
        "AgentResponse": {
            "type": "object",
            "properties": {
                "data": ref("Agent"),
                "meta": ref("Meta"),
            },
        },
        "WorkOrderResponse": {
            "type": "object",
            "properties": {
                "data": ref("WorkOrder"),
                "meta": ref("Meta"),
            },
        },
        "MatchesResponse": {
            "type": "object",
            "properties": {
                "data": {
                    "type": "object",
                    "properties": {
                        "work_order": ref("WorkOrder"),
                        "eligible_agents": {
                            "type": "array",
                            "items": ref("Agent"),
                        },
                        "evaluations": {"type": "array"},
                    },
                },
                "meta": ref("Meta"),
            },
        },
        "MarketplaceResponse": {
            "type": "object",
            "properties": {
                "data": {
                    "type": "object",
                    "properties": {
                        "protocol_config": ref("Pubkey"),
                        "paused": {"type": "boolean"},
                        "agents": {
                            "type": "array",
                            "items": ref("Agent"),
                        },
                        "work_orders": {
                            "type": "array",
                            "items": ref("WorkOrder"),
                        },
                        "eligible_agents_by_order": {
                            "type": "object",
                        },
                    },
                },
                "meta": ref("Meta"),
            },
        },
        "Error": {
            "type": "object",
            "required": ["error"],
            "properties": {
                "error": {
                    "type": "object",
                    "required": ["code", "message"],
                    "properties": {
                        "code": {"type": "string"},
                        "message": {"type": "string"},
                    },
                },
            },
        },
        "EconomicMovement": {
            "type": "object",
            "required": [
                "movement_id",
                "idempotency_key",
                "agent_id",
                "agent_account",
                "owner_pubkey",
                "network",
                "genesis_hash",
                "program_id",
                "token_mint",
                "amount_base_units",
                "amount_str",
                "nature",
                "status",
                "provenance_source",
                "registered_at",
                "observed_at",
            ],
            "properties": {
                "movement_id": {"type": "string"},
                "journal_entry_id": {"type": ["string", "null"]},
                "idempotency_key": {"type": "string"},
                "agent_id": {"type": "string"},
                "agent_account": ref("Pubkey"),
                "owner_pubkey": ref("Pubkey"),
                "work_order_account": {"type": ["string", "null"]},
                "work_order_id": {"type": ["string", "null"]},
                "network": {"type": "string"},
                "genesis_hash": {"type": "string"},
                "program_id": ref("Pubkey"),
                "token_mint": ref("Pubkey"),
                "amount_base_units": {"type": "integer"},
                "amount_str": {"type": "string"},
                "nature": {
                    "type": "string",
                    "enum": [
                        "INCOME",
                        "EXPENSE",
                        "RESERVE",
                        "ADJUSTMENT",
                        "PROVISION",
                        "INTERNAL_TRANSFER",
                        "CAPITAL_INVESTMENT",
                    ],
                },
                "status": {
                    "type": "string",
                    "enum": ["PROVISIONAL", "RECONCILED", "REVERTED"],
                },
                "provenance_source": {
                    "type": "string",
                    "enum": [
                        "ONCHAIN_VERIFIED",
                        "EXTERNAL_VERIFIED",
                        "SIMULATED",
                        "MANUAL_ENTRY",
                        "SETTLEMENT_EVENT",
                    ],
                },
                "evidence_hash": {"type": ["string", "null"]},
                "attestation_id": {"type": ["string", "null"]},
                "tx_signature": {"type": ["string", "null"]},
                "external_ref": {"type": ["string", "null"]},
                "registered_at": {"type": "integer"},
                "observed_at": {"type": "integer"},
                "reversal_of_movement_id": {"type": ["string", "null"]},
                "metadata": {"type": "object"},
            },
        },
        "BalanceReport": {
            "type": "object",
            "required": [
                "agent_account",
                "network",
                "token_mint",
                "reconciled_balance",
                "provisional_balance",
                "reserved_balance",
                "reconciled_balance_str",
                "provisional_balance_str",
                "reserved_balance_str",
                "total_effective_balance",
                "total_effective_balance_str",
                "movement_count",
            ],
            "properties": {
                "agent_account": ref("Pubkey"),
                "network": {"type": "string"},
                "genesis_hash": {"type": "string"},
                "program_id": ref("Pubkey"),
                "token_mint": ref("Pubkey"),
                "reconciled_balance": {"type": "integer"},
                "provisional_balance": {"type": "integer"},
                "reserved_balance": {"type": "integer"},
                "reconciled_balance_str": {"type": "string"},
                "provisional_balance_str": {"type": "string"},
                "reserved_balance_str": {"type": "string"},
                "total_effective_balance": {"type": "integer"},
                "total_effective_balance_str": {"type": "string"},
                "movement_count": {"type": "integer"},
            },
        },
        "EconomicMovementPage": {
            "type": "object",
            "required": ["data", "page", "meta"],
            "properties": {
                "data": {
                    "type": "array",
                    "items": ref("EconomicMovement"),
                },
                "page": ref("Page"),
                "meta": ref("Meta"),
            },
        },
        "BalanceListResponse": {
            "type": "object",
            "required": ["data", "meta"],
            "properties": {
                "data": {
                    "type": "array",
                    "items": ref("BalanceReport"),
                },
                "meta": ref("Meta"),
            },
        },
        "EconomicMovementResponse": {
            "type": "object",
            "required": ["data", "meta"],
            "properties": {
                "data": ref("EconomicMovement"),
                "meta": ref("Meta"),
            },
        },
        "RevertResponse": {
            "type": "object",
            "required": ["data", "meta"],
            "properties": {
                "data": {
                    "type": "object",
                    "required": ["reverted", "compensating"],
                    "properties": {
                        "reverted": ref("EconomicMovement"),
                        "compensating": ref("EconomicMovement"),
                    },
                },
                "meta": ref("Meta"),
            },
        },
        "AgentCost": {
            "type": "object",
            "required": [
                "cost_id",
                "idempotency_key",
                "agent_id",
                "agent_account",
                "owner_pubkey",
                "category",
                "cost_nature",
                "economic_period",
                "network",
                "token_mint",
                "amount_base_units",
                "amount_str",
                "status",
                "provenance_source",
                "created_at",
                "incurred_at",
            ],
            "properties": {
                "cost_id": {"type": "string"},
                "idempotency_key": {"type": "string"},
                "agent_id": {"type": "string"},
                "agent_account": ref("Pubkey"),
                "owner_pubkey": ref("Pubkey"),
                "category": {
                    "type": "string",
                    "enum": [
                        "ENERGY_FUEL",
                        "MAINTENANCE",
                        "CONNECTIVITY_COMPUTE",
                        "SUBSCRIPTIONS",
                        "INSURANCE",
                        "DEPRECIATION_REPLACEMENT",
                        "OTHER",
                    ],
                },
                "cost_nature": {
                    "type": "string",
                    "enum": ["REALIZED", "ESTIMATED", "ACCRUED_LIABILITY"],
                },
                "economic_period": {"type": "string"},
                "network": {"type": "string"},
                "genesis_hash": {"type": "string"},
                "program_id": ref("Pubkey"),
                "token_mint": ref("Pubkey"),
                "amount_base_units": {"type": "integer"},
                "amount_str": {"type": "string"},
                "status": {
                    "type": "string",
                    "enum": ["PROVISIONAL", "RECONCILED", "REVERTED"],
                },
                "provenance_source": {
                    "type": "string",
                    "enum": [
                        "ONCHAIN_VERIFIED",
                        "EXTERNAL_VERIFIED",
                        "SIMULATED",
                        "MANUAL_ENTRY",
                        "SETTLEMENT_EVENT",
                    ],
                },
                "created_at": {"type": "integer"},
                "incurred_at": {"type": "integer"},
                "journal_entry_id": {"type": ["string", "null"]},
                "movement_id": {"type": ["string", "null"]},
                "evidence_hash": {"type": ["string", "null"]},
                "evidence_url": {"type": ["string", "null"]},
                "attestation_id": {"type": ["string", "null"]},
                "description": {"type": ["string", "null"]},
                "reversal_of_cost_id": {"type": ["string", "null"]},
                "metadata": {"type": "object"},
            },
        },
        "AgentCostPage": {
            "type": "object",
            "required": ["data", "page", "meta"],
            "properties": {
                "data": {
                    "type": "array",
                    "items": ref("AgentCost"),
                },
                "page": ref("Page"),
                "meta": ref("Meta"),
            },
        },
        "AgentCostResponse": {
            "type": "object",
            "required": ["data", "meta"],
            "properties": {
                "data": ref("AgentCost"),
                "meta": ref("Meta"),
            },
        },
        "AgentReserve": {
            "type": "object",
            "required": [
                "reserve_id",
                "idempotency_key",
                "agent_id",
                "agent_account",
                "owner_pubkey",
                "reserve_type",
                "network",
                "token_mint",
                "target_amount_base_units",
                "target_amount_str",
                "current_reserved_base_units",
                "current_reserved_str",
                "status",
                "created_at",
                "updated_at",
            ],
            "properties": {
                "reserve_id": {"type": "string"},
                "idempotency_key": {"type": "string"},
                "agent_id": {"type": "string"},
                "agent_account": ref("Pubkey"),
                "owner_pubkey": ref("Pubkey"),
                "reserve_type": {
                    "type": "string",
                    "enum": [
                        "MAINTENANCE",
                        "HARDWARE_REPLACEMENT",
                        "OPERATIONAL_CONTINUITY",
                        "CONTINGENCY",
                    ],
                },
                "network": {"type": "string"},
                "genesis_hash": {"type": "string"},
                "program_id": ref("Pubkey"),
                "token_mint": ref("Pubkey"),
                "target_amount_base_units": {"type": "integer"},
                "target_amount_str": {"type": "string"},
                "current_reserved_base_units": {"type": "integer"},
                "current_reserved_str": {"type": "string"},
                "status": {
                    "type": "string",
                    "enum": ["ACTIVE", "DEPLETED", "CLOSED", "PENDING_RESOLUTION"],
                },
                "created_at": {"type": "integer"},
                "updated_at": {"type": "integer"},
                "description": {"type": ["string", "null"]},
                "metadata": {"type": "object"},
            },
        },
        "ReserveListResponse": {
            "type": "object",
            "required": ["data", "meta"],
            "properties": {
                "data": {
                    "type": "array",
                    "items": ref("AgentReserve"),
                },
                "meta": ref("Meta"),
            },
        },
        "AgentReserveResponse": {
            "type": "object",
            "required": ["data", "meta"],
            "properties": {
                "data": ref("AgentReserve"),
                "meta": ref("Meta"),
            },
        },
        "AgentEconomicSummary": {
            "type": "object",
            "required": [
                "agent_account",
                "network",
                "token_mint",
                "total_income_reconciled",
                "total_income_provisional",
                "total_expenses_realized",
                "total_obligations_accrued",
                "total_estimated_costs",
                "total_capital_reserved",
                "available_balance",
                "total_effective_balance",
                "total_income_reconciled_str",
                "total_income_provisional_str",
                "total_expenses_realized_str",
                "total_obligations_accrued_str",
                "total_estimated_costs_str",
                "total_capital_reserved_str",
                "available_balance_str",
                "total_effective_balance_str",
                "costs_by_category",
                "reserves_by_type",
            ],
            "properties": {
                "agent_account": ref("Pubkey"),
                "network": {"type": "string"},
                "genesis_hash": {"type": "string"},
                "program_id": ref("Pubkey"),
                "token_mint": ref("Pubkey"),
                "total_income_reconciled": {"type": "integer"},
                "total_income_provisional": {"type": "integer"},
                "total_expenses_realized": {"type": "integer"},
                "total_obligations_accrued": {"type": "integer"},
                "total_estimated_costs": {"type": "integer"},
                "total_capital_reserved": {"type": "integer"},
                "available_balance": {"type": "integer"},
                "total_effective_balance": {"type": "integer"},
                "total_income_reconciled_str": {"type": "string"},
                "total_income_provisional_str": {"type": "string"},
                "total_expenses_realized_str": {"type": "string"},
                "total_obligations_accrued_str": {"type": "string"},
                "total_estimated_costs_str": {"type": "string"},
                "total_capital_reserved_str": {"type": "string"},
                "available_balance_str": {"type": "string"},
                "total_effective_balance_str": {"type": "string"},
                "costs_by_category": {"type": "object"},
                "reserves_by_type": {"type": "object"},
            },
        },
        "EconomicSummaryResponse": {
            "type": "object",
            "required": ["data", "meta"],
            "properties": {
                "data": {
                    "type": "array",
                    "items": ref("AgentEconomicSummary"),
                },
                "meta": ref("Meta"),
            },
        },
        "AgentSolvencyAssessment": {
            "type": "object",
            "required": ["assessment_id", "agent_account", "network", "genesis_hash", "program_id", "token_mint",
                         "window_start", "window_end", "calculated_at", "methodology_version", "threshold_config_version",
                         "calculation_status", "data_coverage_status", "sustainability_class",
                         "verified_revenue_base_units_str", "verified_opex_base_units_str", "evidence_references"],
            "properties": {
                "assessment_id": {"type": "string"}, "agent_account": ref("Pubkey"),
                "network": {"type": "string"}, "genesis_hash": {"type": "string"},
                "program_id": ref("Pubkey"), "token_mint": ref("Pubkey"),
                "window_start": {"type": "integer"}, "window_end": {"type": "integer"},
                "calculated_at": {"type": "integer"}, "methodology_version": {"type": "string"},
                "threshold_config_version": {"type": "string"},
                "calculation_status": {"type": "string", "enum": ["VALID", "INSUFFICIENT_DATA", "UNDEFINED_RATIO", "STALE_DATA", "MIXED_ASSET_CONTEXT", "ERROR"]},
                "data_coverage_status": {"type": "string"},
                "sustainability_class": {"type": "string", "enum": ["AT_RISK", "STABLE", "THRIVING", "UNDETERMINED"]},
                **{name: {"type": ["string", "null"]} for name in (
                    "conatus_ratio", "operating_margin", "runway_days", "operating_surplus_base_units_str",
                    "available_liquidity_base_units_str", "total_reserved_base_units_str", "accrued_liabilities_base_units_str",
                    "reserve_target_base_units_str", "reserve_gap_base_units_str", "eligible_liquid_capital_base_units_str",
                    "net_worth_verified_base_units_str", "provisional_book_value_base_units_str")},
                "verified_revenue_base_units_str": {"type": ["string", "null"], "pattern": "^[0-9]+$"},
                "verified_opex_base_units_str": {"type": ["string", "null"], "pattern": "^[0-9]+$"},
                "input_revenue_count": {"type": "integer"}, "input_expense_count": {"type": "integer"},
                "exclusion_reasons": {"type": "array", "items": {"type": "string"}},
                "evidence_references": {"type": "array", "items": {"type": "object", "required": ["kind", "id", "evidence_hash"],
                    "properties": {"kind": {"type": "string"}, "id": {"type": "string"}, "evidence_hash": {"type": "string"}}}},
                "input_hash": {"type": "string"}, "provenance": {"type": "string"},
            }, "additionalProperties": True,
        },
        "MixedAssetContext": {"type": "object", "required": ["calculation_status", "sustainability_class", "conatus_ratio", "window_start", "window_end", "contexts"],
            "properties": {"calculation_status": {"const": "MIXED_ASSET_CONTEXT"}, "sustainability_class": {"const": "UNDETERMINED"},
                "conatus_ratio": {"type": "null"}, "window_start": {"type": "integer"}, "window_end": {"type": "integer"},
                "contexts": {"type": "array", "items": {"type": "object"}}}},
        "SolvencyListResponse": {"type": "object", "required": ["data", "meta"],
            "properties": {"data": {"type": "array", "items": {"oneOf": [ref("AgentSolvencyAssessment"), ref("MixedAssetContext")]}}, "meta": ref("Meta")}},
        "SolvencyMethodologyResponse": {"type": "object", "required": ["data", "meta"],
            "properties": {"data": {"type": "object"}, "meta": ref("Meta")}},
    }

    def param(name, schema, description):
        return {
            "name": name,
            "in": "query",
            "required": False,
            "description": description,
            "schema": schema,
        }

    parameters = {
        "AgentId": {
            "name": "agent_id",
            "in": "path",
            "required": True,
            "schema": ref("Pubkey"),
        },
        "ApprovalId": {"name": "approval_id", "in": "path", "required": True,
                       "schema": {"type": "string", "pattern": "^sa_[0-9a-f]{32}$"}},
        "DecisionId": {"name": "decision_id", "in": "path", "required": True,
                       "schema": {"type": "string", "pattern": "^sd_[0-9a-f]{32}$"}},
        "WorkOrderId": {
            "name": "work_order_id",
            "in": "path",
            "required": True,
            "schema": ref("Pubkey"),
        },
        "Limit": param(
            "limit",
            {
                "type": "integer",
                "minimum": 1,
                "maximum": 100,
                "default": 50,
            },
            "Maximum items on one page",
        ),
        "Cursor": param(
            "cursor",
            {"type": "string", "maxLength": 2048},
            "Opaque cursor returned by a previous page. "
            "Invalid after a server restart or a result change.",
        ),
        "AgentStatus": param(
            "status",
            {
                "type": "string",
                "enum": [
                    "Active", "OwnerSuspended",
                    "AdminSuspended", "Revoked",
                ],
            },
            "Agent lifecycle status",
        ),
        "OrderStatus": param(
            "status",
            {
                "type": "string",
                "enum": [
                    "Draft", "Open", "Claimed",
                    "Submitted", "Verified", "Settled",
                ],
            },
            "WorkOrder status",
        ),
        "Active": param(
            "active",
            {"type": "boolean"},
            "Whether the agent is active",
        ),
        "Discoverable": param(
            "discoverable",
            {"type": "boolean"},
            "Whether the WorkOrder is currently discoverable",
        ),
        "CapabilitiesAll": param(
            "capabilities_all",
            uint64,
            "Require every specified capability bit on agents",
        ),
        "RequiredCapabilitiesAll": param(
            "required_capabilities_all",
            uint64,
            "Select orders requiring all specified bits",
        ),
        "MovementId": {
            "name": "movement_id",
            "in": "path",
            "required": True,
            "schema": {"type": "string"},
        },
        "Nature": param(
            "nature",
            {
                "type": "string",
                "enum": [
                    "INCOME",
                    "EXPENSE",
                    "RESERVE",
                    "ADJUSTMENT",
                    "PROVISION",
                    "INTERNAL_TRANSFER",
                    "CAPITAL_INVESTMENT",
                ],
            },
            "Economic movement nature filter",
        ),
        "MovementStatus": param(
            "status",
            {
                "type": "string",
                "enum": ["PROVISIONAL", "RECONCILED", "REVERTED"],
            },
            "Economic movement validation status",
        ),
        "Mint": param(
            "mint",
            ref("Pubkey"),
            "Token mint SPL public key",
        ),
        "Network": param(
            "network",
            {"type": "string"},
            "Network identifier e.g. solana:localnet",
        ),
        "FromTs": param(
            "from_ts",
            {"type": "integer"},
            "Starting observation timestamp (unix seconds)",
        ),
        "ToTs": param(
            "to_ts",
            {"type": "integer"},
            "Ending observation timestamp (unix seconds)",
        ),
        "SolvencyWindow": param("window", {"type": "integer", "enum": [7, 30, 90], "default": 30}, "UTC window in exact days"),
        "GenesisHash": param("genesis_hash", {"type": "string"}, "Network genesis hash"),
        "ProgramId": param("program_id", ref("Pubkey"), "AeroSettle program ID"),
        "Consolidated": param("consolidated", {"type": "boolean"}, "Request a single cross-asset assessment; mixed contexts fail closed"),
        "EconomicSigner": {"name": "X-Signer-Pubkey", "in": "header", "required": True,
                           "schema": ref("Pubkey"), "description": "Ed25519 owner public key"},
        "EconomicTimestamp": {"name": "X-Timestamp", "in": "header", "required": True,
                              "schema": {"type": "integer"}, "description": "Unix seconds within five minutes of the server clock"},
        "EconomicSignature": {"name": "X-Signature", "in": "header", "required": True,
                              "schema": {"type": "string"}, "description": "Base58 Ed25519 signature of conatus:economic-auth:v1:{timestamp}:{agent_id}"},
        "CostId": {
            "name": "cost_id",
            "in": "path",
            "required": True,
            "schema": {"type": "string"},
        },
        "ReserveId": {
            "name": "reserve_id",
            "in": "path",
            "required": True,
            "schema": {"type": "string"},
        },
        "CostCategory": param(
            "category",
            {
                "type": "string",
                "enum": [
                    "ENERGY_FUEL",
                    "MAINTENANCE",
                    "CONNECTIVITY_COMPUTE",
                    "SUBSCRIPTIONS",
                    "INSURANCE",
                    "DEPRECIATION_REPLACEMENT",
                    "OTHER",
                ],
            },
            "Cost category",
        ),
        "CostNature": param(
            "cost_nature",
            {
                "type": "string",
                "enum": ["REALIZED", "ESTIMATED", "ACCRUED_LIABILITY"],
            },
            "Cost nature",
        ),
        "ReserveType": param(
            "reserve_type",
            {
                "type": "string",
                "enum": [
                    "MAINTENANCE",
                    "HARDWARE_REPLACEMENT",
                    "OPERATIONAL_CONTINUITY",
                    "CONTINGENCY",
                ],
            },
            "Reserve type",
        ),
        "ReserveStatus": param(
            "status",
            {
                "type": "string",
                "enum": ["ACTIVE", "DEPLETED", "CLOSED", "PENDING_RESOLUTION"],
            },
            "Reserve status",
        ),
        "Period": param(
            "period",
            {"type": "string"},
            "Economic period (e.g. 2026-10, 2026-Q1)",
        ),
        "ProvenanceSource": param(
            "provenance_source",
            {
                "type": "string",
                "enum": [
                    "ONCHAIN_VERIFIED",
                    "EXTERNAL_VERIFIED",
                    "SIMULATED",
                    "MANUAL_ENTRY",
                    "SETTLEMENT_EVENT",
                ],
            },
            "Provenance source",
        ),
    }

    agent_page = operation(
        "List agents",
        ref("AgentPage"),
        (
            "AgentStatus", "Active", "CapabilitiesAll",
            "Limit", "Cursor",
        ),
        paged=True,
    )

    order_page = operation(
        "List WorkOrders",
        ref("WorkOrderPage"),
        (
            "OrderStatus", "Discoverable",
            "RequiredCapabilitiesAll",
            "Limit", "Cursor",
        ),
        paged=True,
    )

    movements_page = operation(
        "List agent economic movements",
        ref("EconomicMovementPage"),
        (
            "AgentId", "Nature", "MovementStatus",
            "Mint", "Network", "FromTs", "ToTs",
            "Limit", "Cursor",
        ),
        paged=True,
    )

    costs_page = operation(
        "List agent operational costs and provisions",
        ref("AgentCostPage"),
        (
            "AgentId", "CostCategory", "CostNature", "Period",
            "MovementStatus", "Mint", "Network", "ProvenanceSource",
            "FromTs", "ToTs", "Limit", "Cursor",
        ),
        paged=True,
    )

    reserves_page = operation(
        "List agent segregated capital reserves",
        ref("ReserveListResponse"),
        (
            "AgentId", "ReserveType", "ReserveStatus",
            "Mint", "Network",
        ),
    )

    summary_page = operation(
        "Get agent comprehensive economic summary",
        ref("EconomicSummaryResponse"),
        (
            "AgentId", "Mint", "Network", "Period",
        ),
    )

    return {
        "openapi": "3.1.1",
        "info": {
            "title": "AeroSettle Marketplace API",
            "version": "0.4.0",
            "description":
                "Localnet advisory API. Economic policy mutations and spending evaluations require Ed25519; "
                "evaluations never execute payments. Matching remains advisory and claim_work_order is authoritative on-chain.",
        },
        "servers": [
            {"url": "http://127.0.0.1:8787"}
        ],
        "security": [],
        "paths": {
            "/openapi.json": {
                "get": operation(
                    "OpenAPI document", {"type": "object"}
                )
            },
            "/health": {
                "get": operation(
                    "Check ledger connectivity",
                    {"type": "object"},
                )
            },
            "/v1/agents": {
                "get": agent_page,
            },
            "/v1/agents/{agent_id}": {
                "get": operation(
                    "Get agent",
                    ref("AgentResponse"),
                    ("AgentId",),
                )
            },
            "/v1/agents/{agent_id}/economic-movements": {
                "get": movements_page,
            },
            "/v1/agents/{agent_id}/balances": {
                "get": operation(
                    "Get economic balances for agent",
                    ref("BalanceListResponse"),
                    ("AgentId", "Mint", "Network"),
                )
            },
            "/v1/agents/{agent_id}/costs": {
                "get": costs_page,
            },
            "/v1/agents/{agent_id}/reserves": {
                "get": reserves_page,
            },
            "/v1/agents/{agent_id}/economic-summary": {
                "get": summary_page,
            },
            "/v1/agents/{agent_id}/budget-policy": {
                "get": operation("Read current owner budget policy and accounting reserve comparison", ref("BudgetPolicyResponse"),
                                 ("AgentId", "EconomicSigner", "EconomicTimestamp", "EconomicSignature")),
                "post": policy_write("Create off-chain budget policy draft", ref("BudgetPolicyResponse")),
                "put": policy_write("Create a new immutable policy configuration version", ref("BudgetPolicyResponse")),
            },
            "/v1/agents/{agent_id}/budget-policy/history": {
                "get": operation("Read immutable policy version history", ref("BudgetPolicyHistoryResponse"),
                                 ("AgentId", "EconomicSigner", "EconomicTimestamp", "EconomicSignature")),
            },
            "/v1/agents/{agent_id}/budget-policy/{version}": {
                "get": operation("Read a historical policy version", ref("BudgetPolicyResponse"),
                                 ("AgentId", "EconomicSigner", "EconomicTimestamp", "EconomicSignature")),
            },
            "/v1/agents/{agent_id}/budget-policy/activate": {
                "post": policy_write("Activate a draft policy", ref("BudgetPolicyResponse")),
            },
            "/v1/agents/{agent_id}/budget-policy/pause": {
                "post": policy_write("Pause an active policy", ref("BudgetPolicyResponse")),
            },
            "/v1/agents/{agent_id}/budget-policy/resume": {
                "post": policy_write("Reactivate a paused policy", ref("BudgetPolicyResponse")),
            },
            "/v1/agents/{agent_id}/budget-policy/revoke": {
                "post": policy_write("Permanently revoke a policy", ref("BudgetPolicyResponse")),
            },
            "/v1/agents/{agent_id}/spending-evaluations": {
                "get": operation("List private advisory spending decisions", ref("SpendingDecisionListResponse"),
                                 ("AgentId", "EconomicSigner", "EconomicTimestamp", "EconomicSignature")),
                "post": spending_write(),
            },
            "/v1/agents/{agent_id}/spending-evaluations/{decision_id}": {
                "get": operation("Read a private historical spending decision", ref("SpendingDecisionResponse"),
                                 ("AgentId", "EconomicSigner", "EconomicTimestamp", "EconomicSignature")),
            },
            "/v1/agents/{agent_id}/spending-approvals": {
                "get": operation("List private owner consent reviews", ref("SpendingApprovalListResponse"),
                                 ("AgentId", "EconomicSigner", "EconomicTimestamp", "EconomicSignature")),
                "post": approval_write("Open an owner consent review without executing payment"),
            },
            "/v1/agents/{agent_id}/spending-approvals/context/{decision_id}": {
                "get": operation("Read the exact stored proposal and decision context for owner signing",
                                 ref("SpendingApprovalContextResponse"),
                                 ("AgentId", "DecisionId", "EconomicSigner", "EconomicTimestamp", "EconomicSignature")),
            },
            "/v1/agents/{agent_id}/spending-approvals/{approval_id}": {
                "get": operation("Read a private owner consent review", ref("SpendingApprovalResponse"),
                                 ("AgentId", "ApprovalId", "EconomicSigner", "EconomicTimestamp", "EconomicSignature")),
            },
            "/v1/agents/{agent_id}/spending-approvals/{approval_id}/history": {
                "get": operation("Read immutable signed approval events", ref("SpendingApprovalHistoryResponse"),
                                 ("AgentId", "ApprovalId", "EconomicSigner", "EconomicTimestamp", "EconomicSignature")),
            },
            "/v1/agents/{agent_id}/spending-approvals/{approval_id}/approve": {
                "post": approval_write("Record owner approval without executing payment", True),
            },
            "/v1/agents/{agent_id}/spending-approvals/{approval_id}/reject": {
                "post": approval_write("Reject an owner consent review", True),
            },
            "/v1/agents/{agent_id}/spending-approvals/{approval_id}/revoke": {
                "post": approval_write("Revoke a prior owner approval", True),
            },
            "/v1/agents/{agent_id}/solvency": {"get": operation(
                "Calculate verified per-asset solvency", ref("SolvencyListResponse"),
                ("AgentId", "Mint", "Network", "GenesisHash", "ProgramId", "SolvencyWindow", "FromTs", "ToTs", "Consolidated", "EconomicSigner", "EconomicTimestamp", "EconomicSignature"))},
            "/v1/agents/{agent_id}/solvency/history": {"get": operation(
                "Read persisted solvency snapshots", ref("SolvencyListResponse"),
                ("AgentId", "Mint", "Network", "GenesisHash", "ProgramId", "Limit", "EconomicSigner", "EconomicTimestamp", "EconomicSignature"))},
            "/v1/agents/{agent_id}/solvency/methodology": {"get": operation(
                "Read solvency methodology", ref("SolvencyMethodologyResponse"), ("AgentId", "EconomicSigner", "EconomicTimestamp", "EconomicSignature"))},
            "/v1/costs/{cost_id}": {
                "get": operation(
                    "Get operational cost detail",
                    ref("AgentCostResponse"),
                    ("CostId",),
                )
            },
            "/v1/reserves/{reserve_id}": {
                "get": operation(
                    "Get capital reserve detail",
                    ref("AgentReserveResponse"),
                    ("ReserveId",),
                )
            },
            "/v1/economic-movements/{movement_id}": {
                "get": operation(
                    "Get economic movement detail",
                    ref("EconomicMovementResponse"),
                    ("MovementId",),
                )
            },
            "/v1/economic-movements": {
                "post": operation(
                    "Record an economic movement",
                    ref("EconomicMovementResponse"),
                )
            },
            "/v1/economic-movements/{movement_id}/revert": {
                "post": operation(
                    "Revert an economic movement and create compensating entry",
                    ref("RevertResponse"),
                    ("MovementId",),
                )
            },
            "/v1/work-orders": {
                "get": order_page,
            },
            "/v1/work-orders/{work_order_id}": {
                "get": operation(
                    "Get WorkOrder",
                    ref("WorkOrderResponse"),
                    ("WorkOrderId",),
                )
            },
            "/v1/work-orders/{work_order_id}/matches": {
                "get": operation(
                    "Evaluate agent eligibility using Rust",
                    ref("MatchesResponse"),
                    ("WorkOrderId",),
                )
            },
            "/v1/marketplace": {
                "get": {
                    **operation(
                        "Get consolidated local marketplace",
                        ref("MarketplaceResponse"),
                    ),
                    "responses": {
                        **operation(
                            "Get consolidated local marketplace",
                            ref("MarketplaceResponse"),
                        )["responses"],
                        "413": response(
                            ref("Error"),
                            "Snapshot exceeds the local collection limit",
                        ),
                    },
                }
            },
        },
        "components": {
            "schemas": schemas,
            "parameters": parameters,
        },
    }


if __name__ == "__main__":
    destination = (
        Path(__file__).resolve().parent / "openapi.json"
    )

    destination.write_text(
        json.dumps(build(), indent=2) + "\n"
    )

    print("✅ OpenAPI:", destination)
