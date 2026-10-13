#!/usr/bin/env python3
"""No-network, stdlib tests for EPIC 3.2 discovery and Borsh/RPC integrity."""
import base64
import copy
import hashlib
import json
import struct
import unittest

from agent_discovery import (
    Idl, DiscoveryError, Reader, b58decode, b58encode, discover,
    find_program_address, is_ed25519_curve_point, CLOCK_SYSVAR,
)

PROGRAM = "CeA1P1NSuPLUH31KsT4j3pZeBsknQZ3NSC6GUAqcsCLy"


def discriminator(name):
    return list(hashlib.sha256(("account:" + name).encode()).digest()[:8])


def schema():
    return {
        "address": PROGRAM,
        "accounts": [{"name": n, "discriminator": discriminator(n)} for n in
                     ("ProtocolConfig", "AgentAccount", "WorkOrderAccount")],
        "types": [
            {"name": "ProtocolConfig", "type": {"kind": "struct", "fields": [
                {"name": "paused", "type": "bool"},
                {"name": "program_id", "type": "pubkey"},
            ]}},
            {"name": "AgentAccount", "type": {"kind": "struct", "fields": [
                {"name": "protocol_config", "type": "pubkey"},
                {"name": "agent_id", "type": {"array": ["u8", 32]}},
                {"name": "capabilities", "type": "u64"},
                {"name": "status", "type": {"defined": {"name": "AgentStatus"}}},
            ]}},
            {"name": "WorkOrderAccount", "type": {"kind": "struct", "fields": [
                {"name": "protocol_config", "type": "pubkey"},
                {"name": "creator", "type": "pubkey"},
                {"name": "work_order_id", "type": {"array": ["u8", 32]}},
                {"name": "required_capabilities", "type": "u64"},
                {"name": "execution_deadline", "type": "i64"},
                {"name": "status", "type": {"defined": {"name": "WorkOrderStatus"}}},
            ]}},
            {"name": "AgentStatus", "type": {"kind": "enum", "variants": [
                {"name": n} for n in ("Active", "OwnerSuspended", "AdminSuspended", "Revoked")
            ]}},
            {"name": "WorkOrderStatus", "type": {"kind": "enum", "variants": [
                {"name": n} for n in ("Draft", "Open", "Claimed", "Submitted", "Verified", "Settled", "Cancelled", "Expired")
            ]}},
        ],
    }


def pack_account(kind, **kwargs):
    if kind == "ProtocolConfig":
        data = bytes([1 if kwargs["paused"] else 0]) + b58decode(kwargs["program_id"], 32)
    elif kind == "AgentAccount":
        data = (b58decode(kwargs["protocol_config"], 32) + kwargs["agent_id"] +
                struct.pack("<Q", kwargs["capabilities"]) + bytes([kwargs["status"]]))
    elif kind == "WorkOrderAccount":
        data = (b58decode(kwargs["protocol_config"], 32) + b58decode(kwargs["creator"], 32) +
                kwargs["work_order_id"] + struct.pack("<QqB", kwargs["required_capabilities"],
                                                     kwargs["execution_deadline"], kwargs["status"]))
    else:
        raise ValueError(kind)
    return bytes(discriminator(kind)) + data + b"\x00" * 8


def rpc_account(raw, owner=PROGRAM):
    return {"owner": owner, "executable": False,
            "data": [base64.b64encode(raw).decode(), "base64"]}


class FakeRPC:
    def __init__(self):
        self.config = find_program_address([b"protocol_config"], PROGRAM)
        self.creator = b58encode(bytes([3]) * 32)
        self.agent_one_id = bytes([10]) * 32
        self.agent_two_id = bytes([11]) * 32
        self.agent_three_id = bytes([12]) * 32
        self.order_id = bytes([20]) * 32
        self.draft_id = bytes([21]) * 32
        self.a1 = find_program_address([b"agent", b58decode(self.config, 32), self.agent_one_id], PROGRAM)
        self.a2 = find_program_address([b"agent", b58decode(self.config, 32), self.agent_two_id], PROGRAM)
        self.a3 = find_program_address([b"agent", b58decode(self.config, 32), self.agent_three_id], PROGRAM)
        self.o1 = find_program_address([b"work_order", b58decode(self.config, 32),
                                        b58decode(self.creator, 32), self.order_id], PROGRAM)
        self.o2 = find_program_address([b"work_order", b58decode(self.config, 32),
                                        b58decode(self.creator, 32), self.draft_id], PROGRAM)
        self.accounts = {
            self.config: rpc_account(pack_account("ProtocolConfig", paused=False, program_id=PROGRAM)),
            self.a1: rpc_account(pack_account("AgentAccount", protocol_config=self.config,
                                               agent_id=self.agent_one_id, capabilities=0b111, status=0)),
            self.a2: rpc_account(pack_account("AgentAccount", protocol_config=self.config,
                                               agent_id=self.agent_two_id, capabilities=0b001, status=0)),
            self.a3: rpc_account(pack_account("AgentAccount", protocol_config=self.config,
                                               agent_id=self.agent_three_id, capabilities=0b111, status=1)),
            self.o1: rpc_account(pack_account("WorkOrderAccount", protocol_config=self.config,
                                               creator=self.creator, work_order_id=self.order_id,
                                               required_capabilities=0b011, execution_deadline=1500, status=1)),
            self.o2: rpc_account(pack_account("WorkOrderAccount", protocol_config=self.config,
                                               creator=self.creator, work_order_id=self.draft_id,
                                               required_capabilities=0b001, execution_deadline=1500, status=0)),
            CLOCK_SYSVAR: rpc_account(struct.pack("<QqQQq", 1234, 0, 0, 0, 1000),
                                      "Sysvar1111111111111111111111111111111111111"),
        }
        self.calls = []

    def call(self, method, params):
        self.calls.append((method, params))
        if method == "getAccountInfo":
            return {"context": {"slot": 1234}, "value": self.accounts.get(params[0])}
        if method == "getProgramAccounts":
            options = params[1]
            assert options["withContext"] and options["encoding"] == "base64"
            assert options["minContextSlot"] >= 1234
            raw_discriminator = b58decode(options["filters"][0]["memcmp"]["bytes"])
            entries = [{"pubkey": key, "account": account} for key, account in self.accounts.items()
                       if key != CLOCK_SYSVAR and key != self.config
                       and base64.b64decode(account["data"][0])[:8] == raw_discriminator]
            return {"context": {"slot": 1234}, "value": entries}
        raise ValueError(method)


class DiscoveryTests(unittest.TestCase):
    def test_base58_round_trip_zeroes_and_pubkeys(self):
        for raw in (bytes(32), bytes([1])*32, bytes(range(32)), b"\0\0abc", b"\xff"):
            self.assertEqual(b58decode(b58encode(raw)), raw)
        self.assertEqual(b58encode(bytes(32)), "11111111111111111111111111111111")

    def test_invalid_base58_rejected(self):
        with self.assertRaises(DiscoveryError):
            b58decode("O0Il")
        with self.assertRaises(DiscoveryError):
            b58decode("123", expected_len=32)

    def test_ed25519_point_encoding(self):
        self.assertTrue(is_ed25519_curve_point(bytes([1]) + bytes(31)))
        self.assertFalse(is_ed25519_curve_point(bytes([255])*32))

    def test_pd_as_are_deterministic_and_off_curve(self):
        value = find_program_address([b"protocol_config"], PROGRAM)
        self.assertEqual(value, find_program_address([b"protocol_config"], PROGRAM))
        self.assertFalse(is_ed25519_curve_point(b58decode(value, 32)))

    def test_idl_schema_enforced(self):
        data = schema()
        data["accounts"] = data["accounts"][:2]
        with self.assertRaises(DiscoveryError):
            Idl(data)

    def test_idl_contract_field_missing_rejected(self):
        data = schema()
        data["types"][1]["type"]["fields"] = [
            f for f in data["types"][1]["type"]["fields"] if f["name"] != "agent_id"
        ]
        with self.assertRaisesRegex(DiscoveryError, "missing fields"):
            Idl(data).validate_marketplace_contract()

    def test_borsh_decoder_flags_invalid_bool(self):
        reader = Reader(bytes([2]), {})
        with self.assertRaises(DiscoveryError):
            reader.decode("bool")

    def test_borsh_decoder_rejects_truncated_data(self):
        reader = Reader(bytes([10]), {})
        with self.assertRaises(DiscoveryError):
            reader.decode("u64")

    def test_idl_decodes_borsh_with_trailing_padding(self):
        idl = Idl(schema())
        f = FakeRPC()
        payload = base64.b64decode(f.accounts[f.a1]["data"][0])
        decoded = idl.decode_account("AgentAccount", payload)
        self.assertEqual(decoded["capabilities"], 7)
        self.assertEqual(decoded["status"], "Active")
        self.assertEqual(decoded["agent_id"], f.agent_one_id.hex())

    def test_idl_rejects_nonzero_trailing_bytes(self):
        idl = Idl(schema())
        data = pack_account("ProtocolConfig", paused=False, program_id=PROGRAM) + b"\x01"
        with self.assertRaises(DiscoveryError):
            idl.decode_account("ProtocolConfig", data)

    def test_discovery_validates_and_matches(self):
        f = FakeRPC()
        result = discover(f, Idl(schema()))
        self.assertEqual(len(result["agents"]), 3)
        self.assertEqual(len(result["work_orders"]), 2)
        self.assertEqual(result["eligible_agents_by_order"][f.o1], [f.a1])
        self.assertEqual(result["now_unix"], 1000)
        self.assertEqual(result["rpc_context_slots"]["clock"], 1234)
        self.assertEqual([x[0] for x in f.calls],
                         ["getAccountInfo", "getProgramAccounts", "getProgramAccounts", "getAccountInfo"])

    def test_paused_returns_no_candidates(self):
        f = FakeRPC()
        f.accounts[f.config] = rpc_account(pack_account("ProtocolConfig", paused=True, program_id=PROGRAM))
        result = discover(f, Idl(schema()))
        self.assertEqual(result["eligible_agents_by_order"][f.o1], [])

    def test_expired_work_order_not_eligible(self):
        f = FakeRPC()
        f.accounts[f.o1] = rpc_account(pack_account("WorkOrderAccount", protocol_config=f.config,
                                                  creator=f.creator, work_order_id=f.order_id,
                                                  required_capabilities=0b011, execution_deadline=1000, status=1))
        result = discover(f, Idl(schema()))
        self.assertEqual(result["eligible_agents_by_order"][f.o1], [])

    def test_bad_agent_pda_rejected(self):
        f = FakeRPC()
        f.accounts[b58encode(bytes([98])*32)] = f.accounts.pop(f.a1)
        with self.assertRaisesRegex(DiscoveryError, "Invalid AgentAccount PDA"):
            discover(f, Idl(schema()))

    def test_wrong_program_owner_rejected(self):
        f = FakeRPC()
        f.accounts[f.a1]["owner"] = f.creator
        with self.assertRaisesRegex(DiscoveryError, "Unexpected Solana program owner"):
            discover(f, Idl(schema()))

    def test_wrong_protocol_config_rejected(self):
        f = FakeRPC()
        f.accounts[f.a1] = rpc_account(pack_account("AgentAccount", protocol_config=f.creator,
                                               agent_id=f.agent_one_id, capabilities=7, status=0))
        with self.assertRaisesRegex(DiscoveryError, "Cross-protocol"):
            discover(f, Idl(schema()))

    def test_missing_config_does_not_fabricate_results(self):
        f = FakeRPC()
        del f.accounts[f.config]
        with self.assertRaisesRegex(DiscoveryError, "ProtocolConfig absent"):
            discover(f, Idl(schema()))

    def test_invalid_discriminator_rejected(self):
        idl = Idl(schema())
        with self.assertRaises(DiscoveryError):
            idl.decode_account("AgentAccount", bytes(200))

    def test_closed_order_retained_but_not_matched(self):
        f = FakeRPC()
        result = discover(f, Idl(schema()))
        draft = next(x for x in result["work_orders"] if x["work_order_account"] == f.o2)
        self.assertFalse(draft["is_open"])
        self.assertNotIn(f.o2, result["eligible_agents_by_order"])


    def test_idl_accepts_mixed_account_naming(self):
        data = schema()
        aliases = {
            "ProtocolConfig": "protocol_config",
            "AgentAccount": "agentAccount",
            "WorkOrderAccount": "work_order_account",
        }
        for entry in data["accounts"]:
            entry["name"] = aliases[entry["name"]]
        for entry in data["types"]:
            if entry["name"] in aliases:
                entry["name"] = aliases[entry["name"]]
        idl = Idl(data)
        idl.validate_marketplace_contract()
        result = discover(FakeRPC(), idl)
        self.assertEqual(len(result["agents"]), 3)
        self.assertEqual(len(result["work_orders"]), 2)

    def test_idl_rejects_missing_account_discriminator(self):
        data = schema()
        data["accounts"][0].pop("discriminator")
        with self.assertRaisesRegex(DiscoveryError, "discriminator for ProtocolConfig"):
            Idl(data)



    def test_idl_accepts_anchor_qualified_names(self):
        data = schema()

        names = {
            "ProtocolConfig":
                "aerosettle::identity::ProtocolConfig",
            "AgentAccount":
                "aerosettle::identity::AgentAccount",
            "WorkOrderAccount":
                "aerosettle::work_order_account::WorkOrderAccount",
            "AgentStatus":
                "aerosettle::identity::AgentStatus",
            "WorkOrderStatus":
                "aerosettle::work_order_account::WorkOrderStatus",
        }

        for account in data["accounts"]:
            account["name"] = names[account["name"]]

        for typedef in data["types"]:
            typedef["name"] = names.get(
                typedef["name"],
                typedef["name"],
            )

        data["types"][1]["type"]["fields"][-1]["type"] = {
            "defined": {"name": names["AgentStatus"]}
        }

        data["types"][2]["type"]["fields"][-1]["type"] = {
            "defined": {"name": names["WorkOrderStatus"]}
        }

        idl = Idl(data)
        idl.validate_marketplace_contract()

        result = discover(FakeRPC(), idl)

        self.assertEqual(len(result["agents"]), 3)
        self.assertEqual(len(result["work_orders"]), 2)

    def test_idl_rejects_ambiguous_qualified_names(self):
        data = schema()

        data["accounts"][0]["name"] = (
            "aerosettle::identity::ProtocolConfig"
        )

        data["accounts"].append({
            "name": "other::ProtocolConfig",
            "discriminator": discriminator("ProtocolConfig"),
        })

        with self.assertRaisesRegex(
            DiscoveryError,
            "Missing/ambiguous account schema",
        ):
            Idl(data)


if __name__ == "__main__":
    unittest.main(verbosity=2)
