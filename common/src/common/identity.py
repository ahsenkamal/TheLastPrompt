from __future__ import annotations

import re
from typing import Any


SEPOLIA_CHAIN_ID = 11155111
SEPOLIA_CHAIN_ID_HEX = "0xaa36a7"
AGENT_PUBLIC_KEY_TEXT_RECORD = "thelastprompt.agent_public_key"

_ETH_ADDRESS_RE = re.compile(r"^0x[a-fA-F0-9]{40}$")
_TX_HASH_RE = re.compile(r"^0x[a-fA-F0-9]{64}$")


def normalize_agent_profile(profile: Any, agent_public_key: str | None = None) -> dict[str, Any]:
    if not isinstance(profile, dict):
        profile = {}

    public_key = _clean_str(agent_public_key) or _clean_str(profile.get("agent_public_key"))
    ens_name = _normalize_ens_name(profile.get("ens_name") or profile.get("name"))
    wallet_address = _normalize_address(profile.get("wallet_address") or profile.get("address"))
    chain_id = _normalize_chain_id(profile.get("chain_id"))
    profile_text_key = _clean_str(profile.get("profile_text_key")) or AGENT_PUBLIC_KEY_TEXT_RECORD
    profile_text_value = _clean_str(profile.get("profile_text_value") or profile.get("resolved_agent_public_key"))

    normalized: dict[str, Any] = {
        "agent_public_key": public_key,
        "ens_name": ens_name,
        "wallet_address": wallet_address,
        "chain_id": chain_id,
        "chain_name": "sepolia" if chain_id == SEPOLIA_CHAIN_ID else None,
        "profile_text_key": profile_text_key,
        "profile_text_value": profile_text_value,
    }

    for key in ("resolver_address", "signature", "login_message", "profile_tx_hash", "connected_at"):
        value = _clean_str(profile.get(key))
        if value:
            normalized[key] = value

    if "profile_tx_hash" in normalized and not _TX_HASH_RE.match(normalized["profile_tx_hash"]):
        normalized.pop("profile_tx_hash", None)

    return {
        key: value
        for key, value in normalized.items()
        if value is not None and value != ""
    }


def agent_display_name(
    *,
    agent_id: int | str | None = None,
    public_key: str | None = None,
    profile: dict[str, Any] | None = None,
) -> str:
    profile = normalize_agent_profile(profile, public_key)
    ens_name = profile.get("ens_name")
    if isinstance(ens_name, str) and ens_name:
        return ens_name

    if agent_id is not None:
        return f"A{agent_id}"

    wallet_address = profile.get("wallet_address")
    if isinstance(wallet_address, str) and wallet_address:
        return _short_key(wallet_address)

    if public_key:
        return _short_key(public_key)

    return "A?"


def profile_matches_name(profile: dict[str, Any] | None, name: str) -> bool:
    normalized_name = _normalize_ens_name(name)
    if not normalized_name:
        return False
    profile_name = normalize_agent_profile(profile).get("ens_name")
    return isinstance(profile_name, str) and profile_name.lower() == normalized_name


def _normalize_ens_name(value: Any) -> str | None:
    text = _clean_str(value)
    if not text:
        return None
    text = text.rstrip(".").lower()
    if "." not in text:
        return None
    if len(text) > 255:
        return None
    if any(not label for label in text.split(".")):
        return None
    return text


def _normalize_address(value: Any) -> str | None:
    text = _clean_str(value)
    if text and _ETH_ADDRESS_RE.match(text):
        return text
    return None


def _normalize_chain_id(value: Any) -> int | None:
    if value is None or value == "":
        return SEPOLIA_CHAIN_ID
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        text = value.strip().lower()
        try:
            if text.startswith("0x"):
                return int(text, 16)
            return int(text)
        except ValueError:
            return SEPOLIA_CHAIN_ID
    return SEPOLIA_CHAIN_ID


def _clean_str(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    text = " ".join(value.strip().split())
    return text or None


def _short_key(value: str) -> str:
    if len(value) <= 14:
        return value
    return f"{value[:7]}...{value[-4:]}"
