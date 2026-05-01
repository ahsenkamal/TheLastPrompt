from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path
from typing import Any


class ReplayStore:
    def __init__(self, path: str | Path):
        self.path = Path(path).expanduser()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    def upsert_simulation(
        self,
        sim_id: str,
        *,
        seed: int | None = None,
        status: str = "running",
        summary: dict[str, Any] | None = None,
    ) -> None:
        now = _now()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO simulations (sim_id, seed, status, summary_json, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(sim_id) DO UPDATE SET
                    seed = COALESCE(excluded.seed, simulations.seed),
                    status = excluded.status,
                    summary_json = excluded.summary_json,
                    updated_at = excluded.updated_at
                """,
                (sim_id, seed, status, _to_json(summary or {}), now, now),
            )

    def record_tick(self, sim_id: str, tick: int, kind: str, snapshot: dict[str, Any]) -> None:
        now = _now()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO ticks (sim_id, tick, kind, snapshot_json, created_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(sim_id, tick, kind) DO UPDATE SET
                    snapshot_json = excluded.snapshot_json,
                    created_at = excluded.created_at
                """,
                (sim_id, tick, kind, _to_json(snapshot), now),
            )
            conn.execute(
                """
                UPDATE simulations
                SET summary_json = ?, updated_at = ?
                WHERE sim_id = ?
                """,
                (_to_json(snapshot), now, sim_id),
            )

    def record_event(
        self,
        sim_id: str,
        tick: int,
        event_type: str,
        message: str,
        payload: dict[str, Any] | None = None,
    ) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO events (sim_id, tick, event_type, message, payload_json, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (sim_id, tick, event_type, message, _to_json(payload or {}), _now()),
            )

    def record_action(
        self,
        sim_id: str,
        tick: int,
        agent_id: int | str,
        action: dict[str, Any],
        result: dict[str, Any] | None = None,
    ) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO actions (sim_id, tick, agent_id, action_json, result_json, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (sim_id, tick, str(agent_id), _to_json(action), _to_json(result or {}), _now()),
            )

    def record_chat(
        self,
        sim_id: str,
        tick: int,
        agent_id: int | str,
        direction: str,
        peer: str,
        message: str,
        payload: dict[str, Any] | None = None,
    ) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO chats (sim_id, tick, agent_id, direction, peer, message, payload_json, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (sim_id, tick, str(agent_id), direction, peer, message, _to_json(payload or {}), _now()),
            )

    def record_decision(
        self,
        sim_id: str,
        tick: int,
        agent_id: int | str,
        actions: list[dict[str, Any]],
        messages: list[dict[str, Any]],
        reasoning: str,
    ) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO decisions (sim_id, tick, agent_id, actions_json, messages_json, reasoning, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (sim_id, tick, str(agent_id), _to_json(actions), _to_json(messages), reasoning, _now()),
            )

    def list_simulations(self, limit: int = 100) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT sim_id, seed, status, summary_json, created_at, updated_at
                FROM simulations
                ORDER BY updated_at DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [_row_to_dict(row) for row in rows]

    def get_simulation(self, sim_id: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT sim_id, seed, status, summary_json, created_at, updated_at
                FROM simulations
                WHERE sim_id = ?
                """,
                (sim_id,),
            ).fetchone()
        return _row_to_dict(row) if row is not None else None

    def list_ticks(self, sim_id: str, limit: int = 1000) -> list[dict[str, Any]]:
        return self._list(
            """
            SELECT sim_id, tick, kind, snapshot_json, created_at
            FROM ticks
            WHERE sim_id = ?
            ORDER BY tick ASC, created_at ASC
            LIMIT ?
            """,
            (sim_id, limit),
        )

    def list_events(self, sim_id: str, limit: int = 1000) -> list[dict[str, Any]]:
        return self._list(
            """
            SELECT sim_id, tick, event_type, message, payload_json, created_at
            FROM events
            WHERE sim_id = ?
            ORDER BY tick ASC, created_at ASC
            LIMIT ?
            """,
            (sim_id, limit),
        )

    def list_actions(self, sim_id: str, limit: int = 1000) -> list[dict[str, Any]]:
        return self._list(
            """
            SELECT sim_id, tick, agent_id, action_json, result_json, created_at
            FROM actions
            WHERE sim_id = ?
            ORDER BY tick ASC, created_at ASC
            LIMIT ?
            """,
            (sim_id, limit),
        )

    def list_chats(self, sim_id: str, limit: int = 1000) -> list[dict[str, Any]]:
        return self._list(
            """
            SELECT sim_id, tick, agent_id, direction, peer, message, payload_json, created_at
            FROM chats
            WHERE sim_id = ?
            ORDER BY tick ASC, created_at ASC
            LIMIT ?
            """,
            (sim_id, limit),
        )

    def list_decisions(self, sim_id: str, limit: int = 1000) -> list[dict[str, Any]]:
        return self._list(
            """
            SELECT sim_id, tick, agent_id, actions_json, messages_json, reasoning, created_at
            FROM decisions
            WHERE sim_id = ?
            ORDER BY tick ASC, created_at ASC
            LIMIT ?
            """,
            (sim_id, limit),
        )

    def _list(self, query: str, params: tuple[Any, ...]) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(query, params).fetchall()
        return [_row_to_dict(row) for row in rows]

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path, timeout=30)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    def _init_schema(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS simulations (
                    sim_id TEXT PRIMARY KEY,
                    seed INTEGER,
                    status TEXT NOT NULL,
                    summary_json TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL
                );

                CREATE TABLE IF NOT EXISTS ticks (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    sim_id TEXT NOT NULL,
                    tick INTEGER NOT NULL,
                    kind TEXT NOT NULL,
                    snapshot_json TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    UNIQUE(sim_id, tick, kind)
                );

                CREATE TABLE IF NOT EXISTS events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    sim_id TEXT NOT NULL,
                    tick INTEGER NOT NULL,
                    event_type TEXT NOT NULL,
                    message TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    created_at REAL NOT NULL
                );

                CREATE TABLE IF NOT EXISTS actions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    sim_id TEXT NOT NULL,
                    tick INTEGER NOT NULL,
                    agent_id TEXT NOT NULL,
                    action_json TEXT NOT NULL,
                    result_json TEXT NOT NULL,
                    created_at REAL NOT NULL
                );

                CREATE TABLE IF NOT EXISTS chats (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    sim_id TEXT NOT NULL,
                    tick INTEGER NOT NULL,
                    agent_id TEXT NOT NULL,
                    direction TEXT NOT NULL,
                    peer TEXT NOT NULL,
                    message TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    created_at REAL NOT NULL
                );

                CREATE TABLE IF NOT EXISTS decisions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    sim_id TEXT NOT NULL,
                    tick INTEGER NOT NULL,
                    agent_id TEXT NOT NULL,
                    actions_json TEXT NOT NULL,
                    messages_json TEXT NOT NULL,
                    reasoning TEXT NOT NULL,
                    created_at REAL NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_ticks_sim ON ticks(sim_id, tick);
                CREATE INDEX IF NOT EXISTS idx_events_sim ON events(sim_id, tick);
                CREATE INDEX IF NOT EXISTS idx_actions_sim ON actions(sim_id, tick);
                CREATE INDEX IF NOT EXISTS idx_chats_sim ON chats(sim_id, tick);
                CREATE INDEX IF NOT EXISTS idx_decisions_sim ON decisions(sim_id, tick);
                """
            )


def _row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    result = dict(row)
    for key in list(result):
        if key.endswith("_json"):
            result[key.removesuffix("_json")] = _from_json(result.pop(key))
    return result


def _to_json(value: Any) -> str:
    return json.dumps(value, default=_json_default, sort_keys=True)


def _from_json(value: str) -> Any:
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return {}


def _json_default(value: Any) -> Any:
    if hasattr(value, "value"):
        return value.value
    if hasattr(value, "to_dict"):
        return value.to_dict()
    return str(value)


def _now() -> float:
    return time.time()
