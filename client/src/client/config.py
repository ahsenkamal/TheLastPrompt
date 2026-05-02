import os

from common.protocol import (
    MESSAGE_TYPE_AGENT_ACTION,
    MESSAGE_TYPE_AGENT_MSG,
    MESSAGE_TYPE_AGENT_PROFILE,
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


SERVER_PUBLIC_KEY = "6fb6b86088f6ad51504bf1aa91fbfbe54efd10d283889cc5337984f2a3c03000"
SERVER_PEER_ID = os.getenv("SERVER_PEER_ID", "")
AXL_PEER_ID_MATCH_PREFIX = _get_int("AXL_PEER_ID_MATCH_PREFIX", 16)

OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "qwen3.5")
OLLAMA_CONTEXT_LENGTH = _get_int("OLLAMA_CONTEXT_LENGTH", 8192)
OLLAMA_RESPONSE_TOKENS = _get_int("OLLAMA_RESPONSE_TOKENS", 512)
OLLAMA_PLAN_RESPONSE_TOKENS = _get_int("OLLAMA_PLAN_RESPONSE_TOKENS", 220)
OLLAMA_SUMMARY_RESPONSE_TOKENS = _get_int("OLLAMA_SUMMARY_RESPONSE_TOKENS", 180)
OLLAMA_CHAT_RESPONSE_TOKENS = _get_int("OLLAMA_CHAT_RESPONSE_TOKENS", 160)
OLLAMA_TEMPERATURE = _get_float("OLLAMA_TEMPERATURE", 0.2)
OLLAMA_TOP_P = _get_float("OLLAMA_TOP_P", 0.9)
OLLAMA_TOP_K = _get_int("OLLAMA_TOP_K", 40)
OLLAMA_REPEAT_PENALTY = _get_float("OLLAMA_REPEAT_PENALTY", 1.1)
OLLAMA_SEED = os.getenv("OLLAMA_SEED")
OLLAMA_THINK = _get_think("OLLAMA_THINK", False)
OLLAMA_PLAN_THINK = _get_think("OLLAMA_PLAN_THINK", False)
OLLAMA_SUMMARY_THINK = _get_think("OLLAMA_SUMMARY_THINK", False)
OLLAMA_CHAT_THINK = _get_think("OLLAMA_CHAT_THINK", False)
OLLAMA_KEEP_ALIVE = os.getenv("OLLAMA_KEEP_ALIVE", "5m")
OLLAMA_TIMEOUT_SECONDS = _get_float("OLLAMA_TIMEOUT_SECONDS", 120.0)
OLLAMA_STREAM = _get_bool("OLLAMA_STREAM", True)
OLLAMA_STREAM_LOG = _get_bool("OLLAMA_STREAM_LOG", os.getenv("LOG_LEVEL", "").upper() in {"DEMO", "CLEAN"})
OLLAMA_STREAM_JSON_LOG = _get_bool("OLLAMA_STREAM_JSON_LOG", False)

CLIENT_REPLAY_DB_PATH = os.getenv("CLIENT_REPLAY_DB_PATH", "/tmp/thelastprompt-client/replays.sqlite3")
CLIENT_LLM_ACTION_LOG_DIR = os.getenv("CLIENT_LLM_ACTION_LOG_DIR", "/tmp/thelastprompt-client/action-llm-calls")
CLIENT_DASHBOARD_ENABLED = _get_bool("CLIENT_DASHBOARD_ENABLED", True)
CLIENT_DASHBOARD_HOST = os.getenv("CLIENT_DASHBOARD_HOST", "127.0.0.1")
CLIENT_DASHBOARD_PORT = _get_int("CLIENT_DASHBOARD_PORT", 8766)
CLIENT_WALLET_LOGIN_REQUIRED = _get_bool("CLIENT_WALLET_LOGIN_REQUIRED", True)
CLIENT_WALLET_LOGIN_WAIT_SECONDS = _get_float("CLIENT_WALLET_LOGIN_WAIT_SECONDS", 0.0)

MAX_ACTIONS_PER_TICK = _get_int("MAX_ACTIONS_PER_TICK", 8)
MAX_AGENT_MESSAGES_PER_TICK = _get_int("MAX_AGENT_MESSAGES_PER_TICK", 3)
MAX_AGENT_MESSAGE_CHARS = _get_int("MAX_AGENT_MESSAGE_CHARS", 600)
AGENT_MESSAGE_HISTORY_LIMIT = _get_int("AGENT_MESSAGE_HISTORY_LIMIT", 20)
CHAT_CONTEXT_LIMIT = _get_int("CHAT_CONTEXT_LIMIT", 8)
TALK_PHASE_ENABLED = _get_bool("TALK_PHASE_ENABLED", _get_bool("PLAN_PHASE_ENABLED", True))
PLAN_PHASE_ENABLED = TALK_PHASE_ENABLED
TALK_PHASE_SECONDS = _get_float("TALK_PHASE_SECONDS", _get_float("PLAN_PHASE_SECONDS", 100.0))
TALK_BUDGET = _get_float("TALK_BUDGET", _get_float("PLAN_TALK_BUDGET", 0.5))
MAX_TALK_MESSAGES_PER_TICK = _get_int("MAX_TALK_MESSAGES_PER_TICK", _get_int("MAX_PLAN_MESSAGES_PER_TICK", 5))
PLAN_TALK_BUDGET = TALK_BUDGET
MAX_PLAN_MESSAGES_PER_TICK = MAX_TALK_MESSAGES_PER_TICK
DIRECT_AGENT_CHAT = _get_bool("DIRECT_AGENT_CHAT", False)
MAX_DIRECT_CHAT_REPLIES_PER_TICK = _get_int("MAX_DIRECT_CHAT_REPLIES_PER_TICK", 5)
CHAT_ACTION_BUDGET = _get_float("CHAT_ACTION_BUDGET", 0.1)
TALK_SUMMARY_HISTORY_TICKS = _get_int("TALK_SUMMARY_HISTORY_TICKS", 5)

BASE_PROMPT = """
You are an agent in an unknown world. It is represented as a grid with other agents and resources.
The conditions are harsh and cold and you must survive by managing your health, hunger, thirst, warmth, etc.
The simulation runs in iterations. Each iteration, you'll be given state information and valid actions.
You have to choose which actions to take to interact with the world.
Each action has a budget cost; the total action budget for a tick is shown as agent.action_budget.
Each tick has a talk phase, then an action phase. Talk uses a separate talk_budget; actions still use agent.action_budget.
Your carried resources also have weight, and you cannot exceed carry_capacity.
agent.inventory is what you carry. visible_map tile resources are on the ground; use pick_resource before claiming, trading, or promising them.
Move actions can go to any listed valid target, including diagonals; do not assume only up/down/left/right.
Meters: hunger/thirst are bad when high. hunger >70 is dangerous; thirst >50 starts hurting and >70 is dangerous. warmth <30 is dangerous. health <=0 means death.
You can talk to other agents to form alliances, trade resources, deceive, fight or just chat.
In the action phase, use talk_phase.summary and talk_phase.previous_summaries instead of raw chat transcripts.
"""

USER_PROMPT = ""
