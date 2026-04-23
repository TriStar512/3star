from flask import Flask, request, jsonify
from typing import Optional, Callable, Dict, Any
from datetime import datetime
import logging
import asyncio
from threading import Thread

logger = logging.getLogger(__name__)


class WebhookServer:
    """Flask webhook server for manual alerts and integrations."""

    def __init__(
        self,
        port: int = 5000,
        secret: str = "your_secret_key",
        on_news_received: Optional[Callable] = None,
        on_alert_received: Optional[Callable] = None,
    ):
        self.port = port
        self.secret = secret
        self.on_news_received = on_news_received
        self.on_alert_received = on_alert_received
        self.app = Flask(__name__)
        self._register_routes()
        self.thread: Optional[Thread] = None

    def _register_routes(self) -> None:
        """Register Flask routes."""

        @self.app.route("/health", methods=["GET"])
        def health() -> tuple:
            return jsonify({"status": "ok", "timestamp": datetime.utcnow().isoformat()}), 200

        @self.app.route("/news", methods=["POST"])
        def receive_news() -> tuple:
            """
            Receive manual news injection.

            POST body: {
                "ticker": "BTC",
                "headline": "SEC approves Bitcoin ETF",
                "sentiment": 0.8  # optional, -1 to +1
            }
            """
            try:
                data = request.json
                secret = request.headers.get("X-Secret")

                if secret != self.secret:
                    return jsonify({"error": "Invalid secret"}), 401

                ticker = data.get("ticker")
                headline = data.get("headline")
                sentiment = data.get("sentiment")

                if not ticker or not headline:
                    return jsonify({"error": "Missing ticker or headline"}), 400

                logger.info(f"Received news webhook: {ticker} | {headline}")

                if self.on_news_received:
                    self.on_news_received(ticker, headline, sentiment)

                return jsonify({"status": "received"}), 200

            except Exception as e:
                logger.error(f"Error processing news webhook: {e}")
                return jsonify({"error": str(e)}), 500

        @self.app.route("/alert", methods=["POST"])
        def receive_alert() -> tuple:
            """
            Receive trading alert.

            POST body: {
                "action": "buy|sell|close",
                "ticker": "BTC",
                "quantity": 0.5,
                "price": 50000  # optional
            }
            """
            try:
                data = request.json
                secret = request.headers.get("X-Secret")

                if secret != self.secret:
                    return jsonify({"error": "Invalid secret"}), 401

                action = data.get("action")
                ticker = data.get("ticker")

                if not action or not ticker:
                    return jsonify({"error": "Missing action or ticker"}), 400

                logger.info(f"Received alert webhook: {action} {ticker}")

                if self.on_alert_received:
                    self.on_alert_received(data)

                return jsonify({"status": "received"}), 200

            except Exception as e:
                logger.error(f"Error processing alert webhook: {e}")
                return jsonify({"error": str(e)}), 500

    def start(self) -> None:
        """Start webhook server in background thread."""
        def run_server():
            logger.info(f"Starting webhook server on port {self.port}")
            self.app.run(host="0.0.0.0", port=self.port, debug=False)

        self.thread = Thread(target=run_server, daemon=True)
        self.thread.start()
        logger.info("Webhook server started in background")

    def stop(self) -> None:
        """Stop webhook server."""
        # In production, use proper shutdown
        logger.info("Webhook server stopped")

    @staticmethod
    def send_webhook(
        url: str,
        data: Dict[str, Any],
        secret: str = "",
        timeout: int = 5,
    ) -> bool:
        """
        Send webhook to external service (e.g., for Slack/Discord integration).
        """
        try:
            import requests

            headers = {}
            if secret:
                headers["X-Secret"] = secret

            response = requests.post(url, json=data, headers=headers, timeout=timeout)
            return response.status_code == 200

        except Exception as e:
            logger.error(f"Error sending webhook: {e}")
            return False
