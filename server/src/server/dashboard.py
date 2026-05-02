from __future__ import annotations

import json
import logging
import threading
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from common.logging_config import demo_log
from common.replay_store import ReplayStore

from .state import State


logger = logging.getLogger(__name__)


def start_dashboard(state: State, *, host: str, port: int, db_path: str) -> ThreadingHTTPServer:
    web_root = Path(__file__).with_name("web")
    store = ReplayStore(db_path)
    handler = partial(_DashboardHandler, state=state, store=store, directory=str(web_root))
    httpd = ThreadingHTTPServer((host, port), handler)
    thread = threading.Thread(target=httpd.serve_forever, name="server-dashboard", daemon=True)
    thread.start()
    url = _dashboard_url(host, port)
    logger.info("server dashboard listening on %s", url)
    demo_log(logger, "Server dashboard: %s", url)
    return httpd


class _DashboardHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args: Any, state: State, store: ReplayStore, **kwargs: Any):
        self.state = state
        self.store = store
        super().__init__(*args, **kwargs)

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/api/live":
            self._send_json(_live_payload(self.state))
            return
        if parsed.path == "/api/history/simulations":
            self._send_json({"simulations": self.store.list_simulations(200)})
            return
        if parsed.path == "/api/history/simulation":
            sim_id = _query_value(parsed.query, "sim_id")
            if not sim_id:
                self._send_json({"error": "missing sim_id"}, status=400)
                return
            self._send_json({"simulation": self.store.get_simulation(sim_id)})
            return
        if parsed.path == "/api/history/ticks":
            sim_id = _query_value(parsed.query, "sim_id")
            if not sim_id:
                self._send_json({"error": "missing sim_id"}, status=400)
                return
            self._send_json({"ticks": self.store.list_ticks(sim_id, 2000)})
            return
        if parsed.path == "/api/history/events":
            sim_id = _query_value(parsed.query, "sim_id")
            if not sim_id:
                self._send_json({"error": "missing sim_id"}, status=400)
                return
            self._send_json({"events": self.store.list_events(sim_id, 2000)})
            return
        if parsed.path == "/api/history/actions":
            sim_id = _query_value(parsed.query, "sim_id")
            if not sim_id:
                self._send_json({"error": "missing sim_id"}, status=400)
                return
            self._send_json({"actions": self.store.list_actions(sim_id, 2000)})
            return
        if parsed.path == "/api/history/chats":
            sim_id = _query_value(parsed.query, "sim_id")
            if not sim_id:
                self._send_json({"error": "missing sim_id"}, status=400)
                return
            self._send_json({"chats": self.store.list_chats(sim_id, 2000)})
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


def _live_payload(state: State) -> dict[str, Any]:
    simulations = []
    for sim_instance in list(state.sim_instances):
        snapshot = getattr(sim_instance, "snapshot", None)
        if callable(snapshot):
            simulations.append(snapshot())
    return {
        "queue": list(state.matchmaking_queue),
        "agent_profiles": dict(state.agent_profiles),
        "simulations": simulations,
        "sim_size": state.sim_size,
        "server_public_key": state.self_public_key,
    }


def _query_value(query: str, key: str) -> str | None:
    values = parse_qs(query).get(key)
    if not values:
        return None
    value = values[0].strip()
    return value or None


def _dashboard_url(host: str, port: int) -> str:
    browser_host = host.strip() or "127.0.0.1"
    if browser_host in {"0.0.0.0", "::"}:
        browser_host = "127.0.0.1"
    if ":" in browser_host and not browser_host.startswith("["):
        browser_host = f"[{browser_host}]"
    return f"http://{browser_host}:{port}"


def _json_default(value: Any) -> Any:
    if hasattr(value, "value"):
        return value.value
    return str(value)
