import os

from common.protocol import (
    MESSAGE_TYPE_AGENT_ACTION,
    MESSAGE_TYPE_AGENT_MSG,
    MESSAGE_TYPE_MATCHMAKING_JOIN,
    MESSAGE_TYPE_STATE_UPDATE,
    PROTOCOL_VERSION,
)


def _get_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _get_int(name: str, default: int) -> int:
    value = os.getenv(name)
    if value is None:
        return default
    return int(value)


def _get_float(name: str, default: float) -> float:
    value = os.getenv(name)
    if value is None:
        return default
    return float(value)


def _get_think(name: str, default: bool | str) -> bool | str:
    value = os.getenv(name)
    if value is None:
        return default

    normalized = value.strip().lower()
    if normalized in {"high", "medium", "low"}:
        return normalized
    return normalized in {"1", "true", "yes", "on"}


SERVER_PUBLIC_KEY = "08f33349d093cde382b99ac4eba3e60888e91042a7ba38a8cd79b7ec03438986"

OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "llama3.2")
OLLAMA_CONTEXT_LENGTH = _get_int("OLLAMA_CONTEXT_LENGTH", 8192)
OLLAMA_RESPONSE_TOKENS = _get_int("OLLAMA_RESPONSE_TOKENS", 512)
OLLAMA_TEMPERATURE = _get_float("OLLAMA_TEMPERATURE", 0.2)
OLLAMA_TOP_P = _get_float("OLLAMA_TOP_P", 0.9)
OLLAMA_TOP_K = _get_int("OLLAMA_TOP_K", 40)
OLLAMA_REPEAT_PENALTY = _get_float("OLLAMA_REPEAT_PENALTY", 1.1)
OLLAMA_SEED = os.getenv("OLLAMA_SEED")
OLLAMA_THINK = _get_think("OLLAMA_THINK", False)
OLLAMA_KEEP_ALIVE = os.getenv("OLLAMA_KEEP_ALIVE", "5m")
OLLAMA_TIMEOUT_SECONDS = _get_float("OLLAMA_TIMEOUT_SECONDS", 120.0)

MAX_ACTIONS_PER_TICK = _get_int("MAX_ACTIONS_PER_TICK", 8)
MAX_AGENT_MESSAGES_PER_TICK = _get_int("MAX_AGENT_MESSAGES_PER_TICK", 3)
MAX_AGENT_MESSAGE_CHARS = _get_int("MAX_AGENT_MESSAGE_CHARS", 600)
AGENT_MESSAGE_HISTORY_LIMIT = _get_int("AGENT_MESSAGE_HISTORY_LIMIT", 20)

BASE_PROMPT = """
You are an agent in an unknown world. It is represented as a grid with other agents and resources.
The conditions are harsh and cold and you must survive by managing your health, hunger, thirst, warmth, etc.
The simulation runs in iterations. Each iteration, you'll be given state information and valid actions.
You have to choose which actions to take to interact with the world.
You can talk to other agents to form alliances, trade resources, deceive, fight or just chat.
"""

USER_PROMPT = ""
