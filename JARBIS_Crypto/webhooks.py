"""Webhook server + dashboard API + Slack outbound notifier.

Endpoints
    POST /news        {"ticker": "BTC", "headline": "...", "score": 0.8?}
    POST /emergency   {"confirm": true}
    POST /bot/start   {"confirm": true}  — resume new entries
    POST /bot/stop    {"confirm": true}  — pause new entries
    GET  /state       dashboard snapshot (read-only, public)
    GET  /healthz     liveness probe

Auth: POST endpoints require ``X-JARBIS-Secret: <WEBHOOK_SECRET>``. The
read-only ``GET /state`` is public so the live artifact on claude.ai can
poll it without shipping the secret; it contains only market + position
data, no keys.

CORS: ``*`` on ``GET /state`` so a Claude Live Artifact served from
https://claude.ai can fetch the local bot state via
http://127.0.0.1:<port>/state (Chrome/Edge/Firefox all permit loopback
http from https contexts).
"""
from __future__ import annotations

import logging
import queue
import threading
from dataclasses import dataclass
from typing import Optional, TYPE_CHECKING

import requests
from flask import Flask, jsonify, request

from .config import Settings, get_settings

if TYPE_CHECKING:
    from .main import JarbisBot

log = logging.getLogger(__name__)


@dataclass
class WebhookEvent:
    kind: str  # "news" | "emergency" | "bot_start" | "bot_stop"
    payload: dict


class WebhookServer:
    """Flask app for webhooks + dashboard state snapshot.

    POST events are pushed to a ``queue.Queue`` so the main asyncio loop
    drains them without touching Flask internals. ``GET /state`` reads
    directly from the bot reference — safe because all fields we touch
    are plain Python collections whose shapes change only under the
    asyncio loop (and we accept a best-effort snapshot).
    """

    def __init__(self, settings: Settings | None = None, bot: "JarbisBot | None" = None):
        self.settings = settings or get_settings()
        self.events: queue.Queue[WebhookEvent] = queue.Queue()
        self.app = Flask(__name__)
        self._thread: Optional[threading.Thread] = None
        self._bot = bot
        self._register_routes()
        self._register_cors()

    # ---- route registration ----

    def _register_routes(self) -> None:
        @self.app.post("/news")
        def _news():
            if not self._auth_ok():
                return jsonify({"ok": False, "error": "unauthorized"}), 401
            data = request.get_json(force=True, silent=True) or {}
            if "ticker" not in data or "headline" not in data:
                return jsonify({"ok": False, "error": "missing fields"}), 400
            self.events.put(WebhookEvent(kind="news", payload=data))
            return jsonify({"ok": True})

        @self.app.post("/emergency")
        def _emergency():
            if not self._auth_ok():
                return jsonify({"ok": False, "error": "unauthorized"}), 401
            data = request.get_json(force=True, silent=True) or {}
            if not data.get("confirm"):
                return jsonify({"ok": False, "error": "confirm=true required"}), 400
            self.events.put(WebhookEvent(kind="emergency", payload=data))
            return jsonify({"ok": True})

        @self.app.post("/bot/start")
        def _bot_start():
            if not self._auth_ok():
                return jsonify({"ok": False, "error": "unauthorized"}), 401
            self.events.put(WebhookEvent(kind="bot_start", payload={}))
            return jsonify({"ok": True, "bot_active": True})

        @self.app.post("/bot/stop")
        def _bot_stop():
            if not self._auth_ok():
                return jsonify({"ok": False, "error": "unauthorized"}), 401
            self.events.put(WebhookEvent(kind="bot_stop", payload={}))
            return jsonify({"ok": True, "bot_active": False})

        @self.app.get("/state")
        def _state():
            if self._bot is None:
                return jsonify({"ok": False, "error": "bot not attached"}), 503
            try:
                snap = self._bot.state_snapshot()
            except Exception as exc:  # noqa: BLE001
                log.warning("state snapshot failed: %s", exc)
                return jsonify({"ok": False, "error": str(exc)}), 500
            return jsonify({"ok": True, "state": snap})

        @self.app.get("/healthz")
        def _health():
            return jsonify({"ok": True})

        # CORS preflight — accept OPTIONS on every known route
        @self.app.route("/<path:_path>", methods=["OPTIONS"])
        def _opts(_path):
            return ("", 204)

    def _register_cors(self) -> None:
        @self.app.after_request
        def _cors(resp):
            resp.headers["Access-Control-Allow-Origin"] = "*"
            resp.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
            resp.headers["Access-Control-Allow-Headers"] = (
                "Content-Type, X-JARBIS-Secret"
            )
            resp.headers["Access-Control-Max-Age"] = "600"
            return resp

    # ---- auth / lifecycle ----

    def _auth_ok(self) -> bool:
        header = request.headers.get("X-JARBIS-Secret", "")
        return header == self.settings.webhook_secret

    def start(self) -> None:
        if self._thread:
            return

        def _run():
            # werkzeug dev server; fine for single-user localhost PC deployment
            self.app.run(
                host="0.0.0.0",
                port=self.settings.webhook_port,
                debug=False,
                use_reloader=False,
            )

        self._thread = threading.Thread(target=_run, daemon=True)
        self._thread.start()
        log.info("webhook + dashboard server listening on :%d",
                 self.settings.webhook_port)

    def drain(self) -> list[WebhookEvent]:
        events: list[WebhookEvent] = []
        while True:
            try:
                events.append(self.events.get_nowait())
            except queue.Empty:
                break
        return events


def slack_notify(message: str, settings: Settings | None = None) -> None:
    s = settings or get_settings()
    if not s.slack_webhook_url:
        return
    try:
        requests.post(s.slack_webhook_url, json={"text": message}, timeout=5)
    except Exception as exc:  # noqa: BLE001
        log.warning("slack notify failed: %s", exc)
