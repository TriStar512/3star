"""Webhook server for manual alerts + Slack outbound notifier.

POST /news  {"ticker": "BTC", "headline": "...", "score": 0.8?}
POST /emergency {"confirm": true}
Headers: X-JARBIS-Secret: <WEBHOOK_SECRET>
"""
from __future__ import annotations

import logging
import queue
import threading
from dataclasses import dataclass
from typing import Optional

import requests
from flask import Flask, jsonify, request

from .config import Settings, get_settings

log = logging.getLogger(__name__)


@dataclass
class WebhookEvent:
    kind: str  # "news" or "emergency"
    payload: dict


class WebhookServer:
    """Flask app exposing POST /news and /emergency.

    Received events are pushed to a ``queue.Queue`` so the main asyncio
    loop can drain them without blocking on Flask's sync internals.
    """

    def __init__(self, settings: Settings | None = None):
        self.settings = settings or get_settings()
        self.events: queue.Queue[WebhookEvent] = queue.Queue()
        self.app = Flask(__name__)
        self._thread: Optional[threading.Thread] = None
        self._register_routes()

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

        @self.app.get("/healthz")
        def _health():
            return jsonify({"ok": True})

    def _auth_ok(self) -> bool:
        header = request.headers.get("X-JARBIS-Secret", "")
        return header == self.settings.webhook_secret

    def start(self) -> None:
        if self._thread:
            return

        def _run():
            # use werkzeug dev server, not gunicorn; good enough for localhost
            self.app.run(
                host="0.0.0.0",
                port=self.settings.webhook_port,
                debug=False,
                use_reloader=False,
            )

        self._thread = threading.Thread(target=_run, daemon=True)
        self._thread.start()
        log.info("webhook server listening on :%d", self.settings.webhook_port)

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
