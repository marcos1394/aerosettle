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
                    "enum": ["ACTIVE", "DEPLETED", "CLOSED"],
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
                "enum": ["ACTIVE", "DEPLETED", "CLOSED"],
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
            "version": "0.3.3",
            "description":
                "Localnet read-only API. Matching is advisory; "
                "claim_work_order remains authoritative on-chain. "
                "No authentication; bind to loopback only.",
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
