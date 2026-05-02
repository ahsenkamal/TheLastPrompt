from __future__ import annotations

import json
import logging
import threading
import time
from uuid import uuid4
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from common.identity import SEPOLIA_CHAIN_ID, normalize_agent_profile, agent_display_name
from common.logging_config import demo_log
from common.replay_store import ReplayStore


logger = logging.getLogger(__name__)


class ClientRuntime:
    def __init__(self, public_key: str, db_path: str):
        self.public_key = public_key
        self.store = ReplayStore(db_path)
        self.lock = threading.Lock()
        self.profile_condition = threading.Condition(self.lock)
        self.profile: dict[str, Any] = normalize_agent_profile({"agent_public_key": public_key}, public_key)
        self.profile_updates: list[dict[str, Any]] = []
        self.profile_nonce = uuid4().hex
        self.current_state: dict[str, Any] | None = None
        self.incoming_messages: list[dict[str, Any]] = []
        self.latest_decision: dict[str, Any] | None = None
        self.chat_log: list[dict[str, Any]] = []

    def profile_challenge(self) -> dict[str, Any]:
        with self.lock:
            message = "\n".join(
                [
                    "The Last Prompt agent login",
                    f"Agent public key: {self.public_key}",
                    f"Network: Sepolia ({SEPOLIA_CHAIN_ID})",
                    f"Nonce: {self.profile_nonce}",
                ]
            )
            return {
                "message": message,
                "nonce": self.profile_nonce,
                "agent_public_key": self.public_key,
                "chain_id": SEPOLIA_CHAIN_ID,
            }

    def update_profile(self, profile: dict[str, Any]) -> dict[str, Any]:
        normalized = normalize_agent_profile(profile, self.public_key)
        with self.profile_condition:
            self.profile = normalized
            self.profile_updates.append(dict(self.profile))
            self.profile_nonce = uuid4().hex
            self.profile_condition.notify_all()
            logger.info(
                "client profile updated wallet=%s ens_name=%s",
                normalized.get("wallet_address"),
                normalized.get("ens_name"),
            )
            return dict(self.profile)

    def get_profile(self) -> dict[str, Any]:
        with self.lock:
            return dict(self.profile)

    def wait_for_profile(self, timeout: float | None, *, require_ens: bool = False) -> dict[str, Any]:
        deadline = None if timeout is None or timeout <= 0 else time.monotonic() + timeout
        with self.profile_condition:
            while not _profile_ready(self.profile, require_ens=require_ens):
                if deadline is None:
                    self.profile_condition.wait(timeout=1.0)
                    continue
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    break
                self.profile_condition.wait(timeout=remaining)
            return dict(self.profile)

    def pop_profile_updates(self) -> list[dict[str, Any]]:
        with self.lock:
            updates = list(self.profile_updates)
            self.profile_updates.clear()
            return updates

    def record_state(self, sim_state: dict[str, Any], incoming_messages: list[dict[str, Any]]) -> None:
        sim_id = str(sim_state.get("sim_id") or "unmatched")
        tick = int(sim_state.get("tick") or 0)
        agent_id = _agent_id(sim_state)
        agent_name = _agent_name(sim_state, agent_id)
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
                f"Agent {agent_name} observed tick {tick}",
                {"agent_id": agent_id, "agent_name": agent_name},
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
        agent_name = _agent_name(sim_state, agent_id)
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
        self.store.record_event(sim_id, tick, "decision", f"Agent {agent_name} chose {len(decision['actions'])} action(s)", decision)
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
                "profile": dict(self.profile),
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
    url = dashboard_url(host, port)
    logger.info("client dashboard listening on %s", url)
    demo_log(logger, "Client dashboard: %s", url)
    return runtime


def dashboard_url(host: str, port: int) -> str:
    browser_host = host.strip() or "127.0.0.1"
    if browser_host in {"0.0.0.0", "::"}:
        browser_host = "127.0.0.1"
    if ":" in browser_host and not browser_host.startswith("["):
        browser_host = f"[{browser_host}]"
    return f"http://{browser_host}:{port}"


class _DashboardHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args: Any, runtime: ClientRuntime, **kwargs: Any):
        self.runtime = runtime
        super().__init__(*args, **kwargs)

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/api/live":
            self._send_json(self.runtime.live_payload())
            return
        if parsed.path == "/api/profile/challenge":
            self._send_json(self.runtime.profile_challenge())
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

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/api/profile":
            payload = self._read_json()
            if not isinstance(payload, dict):
                self._send_json({"error": "invalid JSON"}, status=400)
                return
            profile = self.runtime.update_profile(payload)
            self._send_json({"profile": profile})
            return

        self._send_json({"error": "not found"}, status=404)

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

    def _read_json(self, *, max_bytes: int = 32768) -> dict[str, Any] | None:
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            return None
        if length <= 0 or length > max_bytes:
            return None
        try:
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return None
        return payload if isinstance(payload, dict) else None


def _agent_id(sim_state: dict[str, Any]) -> int | str | None:
    agent = sim_state.get("agent")
    if isinstance(agent, dict):
        return agent.get("id")
    return None


def _profile_ready(profile: dict[str, Any], *, require_ens: bool) -> bool:
    if require_ens:
        return bool(profile.get("wallet_address") and profile.get("ens_name"))
    return bool(profile.get("wallet_address") or profile.get("ens_name"))


def _agent_name(sim_state: dict[str, Any], agent_id: int | str | None = None) -> str:
    agent = sim_state.get("agent")
    if isinstance(agent, dict):
        return agent_display_name(
            agent_id=agent.get("id", agent_id),
            public_key=agent.get("public_key"),
            profile=agent.get("profile") if isinstance(agent.get("profile"), dict) else agent,
        )
    return agent_display_name(agent_id=agent_id)


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
