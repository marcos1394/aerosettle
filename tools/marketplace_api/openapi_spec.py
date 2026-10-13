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
