import os

from common.protocol import PROTOCOL_VERSION


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


# SIM
AGENTS_IN_SIM = _get_int("AGENTS_IN_SIM", 2)
SIM_MAX_TICKS = _get_int("SIM_MAX_TICKS", 10)
TICK_TIMEOUT_SECONDS = _get_float("TICK_TIMEOUT_SECONDS", 180.0)

# MAP
MAP_SIZE = 5
NOISE_PASSES = 3
NORMAL_VISIBILITY_RADIUS = 2
SNEAK_VISIBILITY_RADIUS = 1

# STORAGE + DASHBOARD
REPLAY_DB_PATH = os.getenv("REPLAY_DB_PATH", "/tmp/thelastprompt-server/replays.sqlite3")
SERVER_DASHBOARD_ENABLED = _get_bool("SERVER_DASHBOARD_ENABLED", True)
SERVER_DASHBOARD_HOST = os.getenv("SERVER_DASHBOARD_HOST", "0.0.0.0")
SERVER_DASHBOARD_PORT = _get_int("SERVER_DASHBOARD_PORT", 8765)
