from __future__ import annotations

import json
import logging
import threading
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from common.replay_store import ReplayStore


logger = logging.getLogger(__name__)


class ClientRuntime:
    def __init__(self, public_key: str, db_path: str):
        self.public_key = public_key
        self.store = ReplayStore(db_path)
        self.lock = threading.Lock()
        self.current_state: dict[str, Any] | None = None
        self.incoming_messages: list[dict[str, Any]] = []
        self.latest_decision: dict[str, Any] | None = None
        self.chat_log: list[dict[str, Any]] = []

    def record_state(self, sim_state: dict[str, Any], incoming_messages: list[dict[str, Any]]) -> None:
        sim_id = str(sim_state.get("sim_id") or "unmatched")
        tick = int(sim_state.get("tick") or 0)
        agent_id = _agent_id(sim_state)
        snapshot = {
            "sim_state": sim_state,
            "incoming_agent_messages": list(incoming_messages),
            "decision": self.latest_decision,
        }
        self.store.upsert_simulation(sim_id, status="client_live", summary=snapshot)
        self.store.record_tick(sim_id, tick, "client_state", snapshot)
        with self.lock:
            self.current_state = sim_state
            self.incoming_messages = list(incoming_messages)
        for message in incoming_messages:
            self.record_chat(sim_state, "incoming", str(message.get("from", "?")), str(message.get("message", "")), message)
        if agent_id is not None:
            self.store.record_event(
                sim_id,
                tick,
                "agent_state",
                f"Agent A{agent_id} observed tick {tick}",
                {"agent_id": agent_id},
            )

    def record_decision(
        self,
        sim_state: dict[str, Any],
        llm_response: dict[str, Any],
        accepted: dict[str, Any],
    ) -> None:
        sim_id = str(sim_state.get("sim_id") or "unmatched")
        tick = int(sim_state.get("tick") or 0)
        agent_id = _agent_id(sim_state) or "self"
        decision = {
            "tick": tick,
            "actions": accepted.get("actions", []),
            "messages": accepted.get("messages", []),
            "raw_actions": llm_response.get("actions", []),
            "raw_messages": llm_response.get("messages", []),
            "reasoning": llm_response.get("reasoning", ""),
            "talk_summary": accepted.get("talk_summary", ""),
            "phase_budgets": accepted.get("phase_budgets", {}),
        }
        self.store.record_decision(
            sim_id,
            tick,
            agent_id,
            decision["actions"],
            decision["messages"],
            str(decision["reasoning"]),
        )
        self.store.record_event(sim_id, tick, "decision", f"Agent A{agent_id} chose {len(decision['actions'])} action(s)", decision)
        for message in decision["messages"]:
            recipient = str(message.get("recipient_label") or message.get("recipient", "?"))
            content = str(message.get("content", ""))
            if content:
                self.record_chat(sim_state, "outgoing", recipient, content, {"mode": "turn_message"})
        with self.lock:
            self.latest_decision = decision

    def record_chat(
        self,
        sim_state: dict[str, Any] | None,
        direction: str,
        peer: str,
        message: str,
        payload: dict[str, Any] | None = None,
    ) -> None:
        sim_id = str((sim_state or {}).get("sim_id") or "unmatched")
        tick = int((sim_state or {}).get("tick") or 0)
        agent_id = _agent_id(sim_state or {}) or "self"
        chat = {
            "tick": tick,
            "agent_id": agent_id,
            "direction": direction,
            "peer": peer,
            "message": message,
            "payload": payload or {},
        }
        self.store.record_chat(sim_id, tick, agent_id, direction, peer, message, payload or {})
        with self.lock:
            self.chat_log.append(chat)
            if len(self.chat_log) > 200:
                del self.chat_log[:-200]

    def live_payload(self) -> dict[str, Any]:
        with self.lock:
            return {
                "public_key": self.public_key,
                "state": self.current_state,
                "incoming_messages": list(self.incoming_messages),
                "latest_decision": self.latest_decision,
                "chat_log": list(self.chat_log[-80:]),
            }


def start_dashboard(public_key: str, *, host: str, port: int, db_path: str) -> ClientRuntime:
    runtime = ClientRuntime(public_key, db_path)
    web_root = Path(__file__).with_name("web")
    handler = partial(_DashboardHandler, runtime=runtime, directory=str(web_root))
    httpd = ThreadingHTTPServer((host, port), handler)
    thread = threading.Thread(target=httpd.serve_forever, name="client-dashboard", daemon=True)
    thread.start()
    logger.info("client dashboard listening on http://%s:%s", host, port)
    return runtime


class _DashboardHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args: Any, runtime: ClientRuntime, **kwargs: Any):
        self.runtime = runtime
        super().__init__(*args, **kwargs)

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/api/live":
            self._send_json(self.runtime.live_payload())
            return
        if parsed.path == "/api/history/simulations":
            self._send_json({"simulations": self.runtime.store.list_simulations(200)})
            return
        if parsed.path == "/api/history/ticks":
            sim_id = _query_value(parsed.query, "sim_id")
            if not sim_id:
                self._send_json({"error": "missing sim_id"}, status=400)
                return
            self._send_json({"ticks": self.runtime.store.list_ticks(sim_id, 2000)})
            return
        if parsed.path == "/api/history/chats":
            sim_id = _query_value(parsed.query, "sim_id")
            if not sim_id:
                self._send_json({"error": "missing sim_id"}, status=400)
                return
            self._send_json({"chats": self.runtime.store.list_chats(sim_id, 2000)})
            return
        if parsed.path == "/api/history/decisions":
            sim_id = _query_value(parsed.query, "sim_id")
            if not sim_id:
                self._send_json({"error": "missing sim_id"}, status=400)
                return
            self._send_json({"decisions": self.runtime.store.list_decisions(sim_id, 2000)})
            return

        if parsed.path == "/":
            self.path = "/index.html"
        super().do_GET()

    def log_message(self, format: str, *args: Any) -> None:
        logger.debug("dashboard %s", format % args)

    def _send_json(self, payload: dict[str, Any], status: int = 200) -> None:
        body = json.dumps(payload, default=_json_default).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)


def _agent_id(sim_state: dict[str, Any]) -> int | str | None:
    agent = sim_state.get("agent")
    if isinstance(agent, dict):
        return agent.get("id")
    return None


def _query_value(query: str, key: str) -> str | None:
    values = parse_qs(query).get(key)
    if not values:
        return None
    value = values[0].strip()
    return value or None


def _json_default(value: Any) -> Any:
    if hasattr(value, "value"):
        return value.value
    return str(value)
