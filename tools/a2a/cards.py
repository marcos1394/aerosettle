"""A2A 1.0 Agent Card validation and Conatus owner/publisher binding.

AgentCard is the generated protobuf model in the official a2a-sdk. No card
contents are interpreted as instructions or as financial authorization.
"""
from __future__ import annotations

import base64
import hashlib
import ipaddress
import json
import re
import time
from urllib.parse import urlsplit

from a2a.types import AgentCard
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey
from google.protobuf.json_format import MessageToDict, ParseDict, ParseError
import rfc8785

from tools.discovery.agent_discovery import DiscoveryError, b58decode, b58encode

SPEC_RELEASE = "1.0.1"
WIRE_VERSION = "1.0"
EXTENSION_URI = "https://github.com/marcos1394/aerosettle/a2a/extensions/conatus-identity/v1"
DISCOVERY_BINDING = "https://github.com/marcos1394/aerosettle/a2a/bindings/read-only-card/v1"
CAPABILITIES = (
    "aerial_mobility", "ground_mobility", "rgb_vision", "thermal_vision",
    "multispectral_vision", "gps", "rtk_gps", "environmental_sensing",
    "object_detection", "edge_inference", "physical_manipulation", "transport",
    "energy_supply", "cold_chain_monitoring", "mapping", "telemetry",
)
SAFE_ID = re.compile(r"^[a-zA-Z0-9_.:-]{1,100}$")
UNSAFE_TEXT = re.compile(r"(?i)(ignore (all |the )?(previous|system) instructions|"
    r"system prompt|seed phrase|private key|transfer funds|send funds|execute command)")
MAX_CARD_BYTES = 65536
BINDING_FIELDS = ("cardId", "cardVersion", "agentAccount", "agentId", "ownerPubkey",
                  "signingAuthority", "publisherId", "publisherKey", "endpointDomain",
                  "issuedAt", "expiresAt", "capabilityMask", "network", "genesisHash",
                  "programId", "organizationId", "discoveryOnly")


class CardError(ValueError):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def unb64(value: str) -> bytes:
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_-]+", value):
        raise CardError("INVALID_SIGNATURE")
    try:
        return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))
    except (ValueError, base64.binascii.Error) as exc:
        raise CardError("INVALID_SIGNATURE") from exc


def public_bytes(private: Ed25519PrivateKey) -> bytes:
    return private.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw)


def key_id(raw_public: bytes) -> str:
    return "ed25519-" + hashlib.sha256(raw_public).hexdigest()[:24]


def canonical(value: object) -> bytes:
    try:
        return rfc8785.dumps(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise CardError("INVALID_SCHEMA") from exc


def _depth(value: object, level: int = 0) -> None:
    if level > 16:
        raise CardError("INVALID_SCHEMA")
    if isinstance(value, dict):
        if len(value) > 80:
            raise CardError("INVALID_SCHEMA")
        for key, child in value.items():
            if not isinstance(key, str) or len(key) > 128:
                raise CardError("INVALID_SCHEMA")
            _depth(child, level + 1)
    elif isinstance(value, list):
        if len(value) > 100:
            raise CardError("INVALID_SCHEMA")
        for child in value:
            _depth(child, level + 1)
    elif isinstance(value, str) and len(value) > 4096:
        raise CardError("INVALID_SCHEMA")


def _https_url(value: str) -> str:
    try:
        parsed = urlsplit(value)
        port = parsed.port
    except (ValueError, TypeError) as exc:
        raise CardError("INVALID_ENDPOINT") from exc
    if (parsed.scheme != "https" or not parsed.hostname or parsed.username or
            parsed.password or parsed.fragment or parsed.query or port not in (None, 443)):
        raise CardError("INVALID_ENDPOINT")
    host = parsed.hostname.rstrip(".").lower()
    if (not re.fullmatch(r"[a-z0-9.-]{1,253}", host) or ".." in host or
            host == "localhost" or host.endswith((".localhost", ".local", ".internal"))):
        raise CardError("INVALID_ENDPOINT")
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        address = None
    if address is not None and not address.is_global:
        raise CardError("INVALID_ENDPOINT")
    return host


def validate_card(value: dict) -> dict:
    """Strictly parse the official generated AgentCard model and required fields."""
    if not isinstance(value, dict):
        raise CardError("INVALID_SCHEMA")
    _depth(value)
    if len(canonical(value)) > MAX_CARD_BYTES:
        raise CardError("CARD_TOO_LARGE")
    try:
        model = ParseDict(value, AgentCard(), ignore_unknown_fields=False)
        normalized = MessageToDict(model, preserving_proto_field_name=False)
    except (ParseError, ValueError, TypeError) as exc:
        raise CardError("INVALID_SCHEMA") from exc
    required = ("name", "description", "supportedInterfaces", "version",
                "capabilities", "defaultInputModes", "defaultOutputModes", "skills")
    if any(field not in normalized for field in required):
        raise CardError("INVALID_SCHEMA")
    if (not normalized["name"].strip() or not normalized["description"].strip() or
            not normalized["supportedInterfaces"] or not normalized["skills"] or
            not normalized["defaultInputModes"] or not normalized["defaultOutputModes"]):
        raise CardError("INVALID_SCHEMA")
    if UNSAFE_TEXT.search(normalized["description"]):
        raise CardError("UNSAFE_DESCRIPTION")
    if any(UNSAFE_TEXT.search(skill.get("description", "")) for skill in normalized["skills"]):
        raise CardError("UNSAFE_DESCRIPTION")
    ids = [item.get("id", "") for item in normalized["skills"]]
    if len(ids) != len(set(ids)) or any(not SAFE_ID.fullmatch(item) for item in ids):
        raise CardError("INVALID_SKILLS")
    for item in normalized["skills"]:
        if not item.get("name") or not item.get("description") or not item.get("tags"):
            raise CardError("INVALID_SCHEMA")
    for item in normalized["supportedInterfaces"]:
        _https_url(item.get("url", ""))
        if not item.get("protocolBinding") or not item.get("protocolVersion"):
            raise CardError("INVALID_SCHEMA")
    return normalized


def identity_params(card: dict) -> dict:
    extensions = card.get("capabilities", {}).get("extensions", [])
    found = [item.get("params") for item in extensions if item.get("uri") == EXTENSION_URI]
    if len(found) != 1 or not isinstance(found[0], dict):
        raise CardError("INVALID_IDENTITY")
    return found[0]


def _binding_payload(params: dict, skill_ids: list[str], endpoint: str) -> bytes:
    if set(params) not in (set(BINDING_FIELDS), set(BINDING_FIELDS) | {"ownerSignature"}):
        raise CardError("INVALID_IDENTITY")
    return b"CONATUS-A2A-OWNER-BINDING-v1\n" + canonical({
        **{field: params[field] for field in BINDING_FIELDS},
        "skillIds": sorted(skill_ids), "interfaceUrl": endpoint,
    })


def sign_card(card: dict, private: Ed25519PrivateKey) -> dict:
    unsigned = {key: value for key, value in card.items() if key != "signatures"}
    normalized = validate_card(unsigned)
    header = {"alg": "EdDSA", "typ": "JOSE", "kid": key_id(public_bytes(private))}
    protected = b64(canonical(header))
    payload = b64(canonical(normalized))
    signature = b64(private.sign((protected + "." + payload).encode("ascii")))
    return {**normalized, "signatures": [{"protected": protected, "signature": signature}]}


def verify_jws(card: dict, trusted_public_key: bytes) -> None:
    signatures = card.get("signatures")
    if not isinstance(signatures, list) or len(signatures) != 1:
        raise CardError("INVALID_SIGNATURE")
    sig = signatures[0]
    if not isinstance(sig, dict) or set(sig) != {"protected", "signature"}:
        raise CardError("INVALID_SIGNATURE")
    header_bytes = unb64(sig["protected"])
    try:
        header = json.loads(header_bytes)
    except (UnicodeDecodeError, ValueError) as exc:
        raise CardError("INVALID_SIGNATURE") from exc
    if (header != {"alg": "EdDSA", "typ": "JOSE", "kid": key_id(trusted_public_key)} or
            header_bytes != canonical(header)):
        raise CardError("INVALID_SIGNATURE")
    unsigned = {key: value for key, value in card.items() if key != "signatures"}
    payload = b64(canonical(validate_card(unsigned)))
    try:
        Ed25519PublicKey.from_public_bytes(trusted_public_key).verify(
            unb64(sig["signature"]), (sig["protected"] + "." + payload).encode("ascii"))
    except (InvalidSignature, ValueError) as exc:
        raise CardError("INVALID_SIGNATURE") from exc


def generate_card(agent: dict, *, owner_private: Ed25519PrivateKey,
                  publisher_private: Ed25519PrivateKey, endpoint: str,
                  name: str, description: str, card_version: int = 1,
                  now: int | None = None, organization_id: str = "") -> dict:
    """Build a discovery-only card from a fresh AgentAccount projection."""
    timestamp = int(time.time()) if now is None else now
    if agent.get("status") != "Active" or agent.get("active") is not True:
        raise CardError("INVALID_IDENTITY")
    owner = agent.get("owner")
    if owner != b58encode(public_bytes(owner_private)):
        raise CardError("INVALID_IDENTITY")
    mask = agent.get("capabilities")
    if type(mask) is not int or mask <= 0 or mask >= 1 << 64:
        raise CardError("INVALID_CAPABILITIES")
    if type(card_version) is not int or card_version < 1:
        raise CardError("INVALID_VERSION")
    host = _https_url(endpoint)
    if urlsplit(endpoint).path != "/.well-known/agent-card.json":
        raise CardError("INVALID_ENDPOINT")
    skills = [{"id": "conatus." + label, "name": label.replace("_", " ").title(),
               "description": "Registered Conatus capability for discovery only.",
               "tags": [label, "conatus"]}
              for bit, label in enumerate(CAPABILITIES) if mask & (1 << bit)]
    if not skills:
        raise CardError("INVALID_CAPABILITIES")
    params = {"cardId": hashlib.sha256((agent["agent_account"] + host).encode()).hexdigest(),
              "cardVersion": str(card_version), "agentAccount": agent["agent_account"],
              "agentId": agent["agent_id"], "ownerPubkey": owner,
              "signingAuthority": agent.get("signing_authority") or "",
              "publisherId": key_id(public_bytes(publisher_private)),
              "publisherKey": b64(public_bytes(publisher_private)),
              "endpointDomain": host, "issuedAt": timestamp,
              "expiresAt": timestamp + 86400, "capabilityMask": str(mask),
              "network": agent["network"], "genesisHash": agent["genesis_hash"],
              "programId": agent["program_id"], "organizationId": organization_id,
              "discoveryOnly": True}
    interface_url = f"https://{host}/a2a/cards/{params['cardId']}"
    params["ownerSignature"] = b64(owner_private.sign(_binding_payload(
        params, [skill["id"] for skill in skills], interface_url)))
    card = {"name": name, "description": description,
            "supportedInterfaces": [{"url": interface_url, "protocolBinding": DISCOVERY_BINDING,
                                     "protocolVersion": WIRE_VERSION}],
            "version": f"{card_version}.0.0",
            "capabilities": {"streaming": False, "pushNotifications": False,
                             "extensions": [{"uri": EXTENSION_URI, "required": False,
                                             "params": params}]},
            "defaultInputModes": ["application/json"],
            "defaultOutputModes": ["application/json"],
            "skills": skills}
    return sign_card(card, publisher_private)


def verify_conatus_card(card: dict, fresh_agent: dict, *, now: int | None = None,
                        organization_check=None) -> dict:
    normalized = validate_card(card)
    params = identity_params(normalized)
    timestamp = int(time.time()) if now is None else now
    if type(params.get("expiresAt")) not in (int, float) or \
            type(params.get("issuedAt")) not in (int, float) or \
            not params["issuedAt"] <= timestamp < params["expiresAt"] or \
            params["expiresAt"] - params["issuedAt"] > 86400:
        raise CardError("EXPIRED_CARD")
    if (fresh_agent.get("status") != "Active" or fresh_agent.get("active") is not True or
            any(params.get(field) != fresh_agent.get(agent_field) for field, agent_field in
                (("agentAccount", "agent_account"), ("agentId", "agent_id"),
                 ("ownerPubkey", "owner"), ("network", "network"),
                 ("genesisHash", "genesis_hash"), ("programId", "program_id"))) or
            params.get("signingAuthority") != (fresh_agent.get("signing_authority") or "")):
        raise CardError("INVALID_IDENTITY")
    mask = fresh_agent.get("capabilities")
    if type(mask) is not int or params.get("capabilityMask") != str(mask):
        raise CardError("INVALID_CAPABILITIES")
    expected = {"conatus." + label for bit, label in enumerate(CAPABILITIES)
                if mask & (1 << bit)}
    actual = {item["id"] for item in normalized["skills"]}
    if not actual or not actual <= expected:
        raise CardError("INVALID_CAPABILITIES")
    for item in normalized["skills"]:
        label = item["id"].removeprefix("conatus.")
        if (item["name"] != label.replace("_", " ").title() or
                item["description"] != "Registered Conatus capability for discovery only." or
                item["tags"] != [label, "conatus"]):
            raise CardError("INVALID_CAPABILITIES")
    advertised = normalized["capabilities"]
    if (advertised.get("streaming") is not False or
            advertised.get("pushNotifications") is not False or
            advertised.get("extendedAgentCard") is True or
            len(advertised.get("extensions", [])) != 1 or
            normalized.get("securitySchemes") or normalized.get("securityRequirements") or
            normalized.get("provider") or normalized.get("documentationUrl") or
            normalized.get("iconUrl") or
            normalized["defaultInputModes"] != ["application/json"] or
            normalized["defaultOutputModes"] != ["application/json"]):
        raise CardError("INVALID_CAPABILITIES")
    interface = normalized["supportedInterfaces"][0]
    host = _https_url(interface["url"])
    expected_card_id = hashlib.sha256((params.get("agentAccount", "") + host).encode()).hexdigest()
    if (host != params.get("endpointDomain") or params.get("discoveryOnly") is not True or
            params.get("publisherId") != key_id(unb64(params.get("publisherKey", ""))) or
            params.get("cardId") != expected_card_id or
            not str(params.get("cardVersion", "")).isdigit() or
            normalized["version"] != str(params["cardVersion"]) + ".0.0" or
            len(normalized["supportedInterfaces"]) != 1 or
            interface["protocolBinding"] != DISCOVERY_BINDING or
            interface["url"] != f"https://{host}/a2a/cards/{params['cardId']}" or
            interface["protocolVersion"] != WIRE_VERSION):
        raise CardError("INVALID_IDENTITY")
    organization = params.get("organizationId")
    if organization and (organization_check is None or
                         not organization_check(organization, fresh_agent)):
        raise CardError("INVALID_IDENTITY")
    try:
        owner_public = Ed25519PublicKey.from_public_bytes(b58decode(params["ownerPubkey"], 32))
        owner_public.verify(unb64(params["ownerSignature"]), _binding_payload(
            params, [item["id"] for item in normalized["skills"]], interface["url"]))
    except (InvalidSignature, ValueError, KeyError, DiscoveryError, TypeError) as exc:
        raise CardError("INVALID_IDENTITY") from exc
    verify_jws(normalized, unb64(params["publisherKey"]))
    return {"status": "VERIFIED_DISCOVERY_ONLY", "card_id": params["cardId"],
            "card_version": int(params["cardVersion"]), "agent_account": params["agentAccount"],
            "agent_id": params["agentId"], "owner_pubkey": params["ownerPubkey"],
            "publisher_id": params["publisherId"], "endpoint_domain": host,
            "expires_at": params["expiresAt"], "skill_ids": sorted(actual),
            "is_executable": False, "is_financial_authority": False}


def negotiate(card: dict, *, versions: tuple[str, ...] = (WIRE_VERSION,),
              transports: tuple[str, ...] = (DISCOVERY_BINDING,),
              modalities: tuple[str, ...] = ("application/json",),
              trusted: bool = False, now: int | None = None,
              expires_at: int | None = None) -> dict:
    normalized = validate_card(card)
    if expires_at is None:
        try:
            expires_at = identity_params(normalized)["expiresAt"]
        except (CardError, KeyError):
            return {"status": "UNTRUSTED_CARD", "interface": None,
                    "skills": [], "is_executable": False}
    timestamp = int(time.time()) if now is None else now
    if expires_at <= timestamp:
        status = "EXPIRED_CARD"
    elif not trusted:
        status = "UNTRUSTED_CARD"
    else:
        interfaces = normalized["supportedInterfaces"]
        matching_version = [item for item in interfaces if item["protocolVersion"] in versions]
        matching_transport = [item for item in matching_version
                              if item["protocolBinding"] in transports]
        if not matching_version:
            status = "UNSUPPORTED_VERSION"
        elif not matching_transport:
            status = "UNSUPPORTED_TRANSPORT"
        elif not set(normalized["defaultInputModes"]) & set(modalities):
            status = "UNSUPPORTED_MODALITY"
        else:
            status = "SUPPORTED"
            return {"status": status, "interface": matching_transport[0],
                    "skills": [item["id"] for item in normalized["skills"]],
                    "is_executable": False}
    return {"status": status, "interface": None, "skills": [], "is_executable": False}
