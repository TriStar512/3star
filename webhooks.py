"""Webhook server for manual alerts and external integration."""

import logging
import json
from typing import Optional, Callable, Dict, Any
from flask import Flask, request, jsonify
from functools import wraps

logger = logging.getLogger(__name__)


class WebhookServer:
    """Flask-based webhook server for trading alerts."""

    def __init__(self, port: int = 5000, secret_key: str = ""):
        self.app = Flask(__name__)
        self.port = port
        self.secret_key = secret_key
        self.handlers: Dict[str, Callable] = {}
        self._setup_routes()

    def _setup_routes(self):
        """Setup Flask routes."""

        @self.app.route("/health", methods=["GET"])
        def health():
            """Health check endpoint."""
            return jsonify({"status": "ok", "service": "jarbis-crypto"})

        @self.app.route("/webhook/news", methods=["POST"])
        @self._require_secret
        def handle_news():
            """Handle news webhook."""
            data = request.get_json()
            if not data:
                return jsonify({"error": "No data provided"}), 400

            ticker = data.get("ticker")
            title = data.get("title")
            sentiment = data.get("sentiment")

            if not all([ticker, title]):
                return jsonify({"error": "Missing ticker or title"}), 400

            handler = self.handlers.get("news")
            if handler:
                try:
                    handler(ticker=ticker, title=title, sentiment=sentiment)
                    return jsonify({"status": "ok", "action": "news_injected"})
                except Exception as e:
                    logger.error(f"News handler error: {str(e)}")
                    return jsonify({"error": str(e)}), 500

            return jsonify({"error": "No news handler configured"}), 501

        @self.app.route("/webhook/alert", methods=["POST"])
        @self._require_secret
        def handle_alert():
            """Handle generic alert webhook."""
            data = request.get_json()
            if not data:
                return jsonify({"error": "No data provided"}), 400

            alert_type = data.get("type")  # "signal", "risk", "position", etc.
            message = data.get("message")

            if not alert_type:
                return jsonify({"error": "Missing alert type"}), 400

            handler = self.handlers.get("alert")
            if handler:
                try:
                    handler(alert_type=alert_type, message=message, data=data)
                    return jsonify({"status": "ok", "action": "alert_processed"})
                except Exception as e:
                    logger.error(f"Alert handler error: {str(e)}")
                    return jsonify({"error": str(e)}), 500

            return jsonify({"error": "No alert handler configured"}), 501

        @self.app.route("/webhook/emergency", methods=["POST"])
        @self._require_secret
        def handle_emergency():
            """Handle emergency close webhook."""
            handler = self.handlers.get("emergency")
            if handler:
                try:
                    handler()
                    return jsonify({"status": "ok", "action": "emergency_triggered"})
                except Exception as e:
                    logger.error(f"Emergency handler error: {str(e)}")
                    return jsonify({"error": str(e)}), 500

            return jsonify({"error": "No emergency handler configured"}), 501

        @self.app.route("/webhook/command", methods=["POST"])
        @self._require_secret
        def handle_command():
            """Handle command webhook."""
            data = request.get_json()
            if not data:
                return jsonify({"error": "No data provided"}), 400

            command = data.get("command")
            if not command:
                return jsonify({"error": "Missing command"}), 400

            handler = self.handlers.get("command")
            if handler:
                try:
                    result = handler(command=command, args=data.get("args", {}))
                    return jsonify({"status": "ok", "result": result})
                except Exception as e:
                    logger.error(f"Command handler error: {str(e)}")
                    return jsonify({"error": str(e)}), 500

            return jsonify({"error": "No command handler configured"}), 501

        @self.app.errorhandler(404)
        def not_found(e):
            return jsonify({"error": "Endpoint not found"}), 404

    def _require_secret(self, f):
        """Decorator to require secret key."""

        @wraps(f)
        def decorated_function(*args, **kwargs):
            if not self.secret_key:
                # No secret required if not configured
                return f(*args, **kwargs)

            secret = request.headers.get("X-Webhook-Secret")
            if not secret or secret != self.secret_key:
                logger.warning("Unauthorized webhook request")
                return jsonify({"error": "Unauthorized"}), 401

            return f(*args, **kwargs)

        return decorated_function

    def register_handler(self, event: str, handler: Callable):
        """
        Register handler for webhook event.

        Args:
            event: Event name ('news', 'alert', 'emergency', 'command')
            handler: Callable handler function
        """
        self.handlers[event] = handler
        logger.info(f"Registered handler for event: {event}")

    def run(self, host: str = "0.0.0.0", debug: bool = False):
        """Start webhook server."""
        logger.info(f"Starting webhook server on {host}:{self.port}")
        self.app.run(host=host, port=self.port, debug=debug, use_reloader=False)

    def run_in_thread(self, host: str = "0.0.0.0"):
        """Start webhook server in background thread."""
        import threading

        thread = threading.Thread(target=self.run, args=(host,), daemon=True)
        thread.start()
        logger.info(f"Webhook server started in thread on {host}:{self.port}")
        return thread


class WebhookClient:
    """Client for sending webhook requests."""

    def __init__(self, base_url: str, secret_key: str = ""):
        self.base_url = base_url.rstrip("/")
        self.secret_key = secret_key

    def _headers(self) -> Dict[str, str]:
        """Get headers for webhook request."""
        headers = {"Content-Type": "application/json"}
        if self.secret_key:
            headers["X-Webhook-Secret"] = self.secret_key
        return headers

    def send_news(self, ticker: str, title: str, sentiment: Optional[float] = None) -> bool:
        """Send news webhook."""
        import requests

        try:
            data = {
                "ticker": ticker,
                "title": title,
                "sentiment": sentiment,
            }
            response = requests.post(
                f"{self.base_url}/webhook/news",
                json=data,
                headers=self._headers(),
                timeout=5,
            )
            return response.status_code == 200
        except Exception as e:
            logger.error(f"Failed to send news webhook: {str(e)}")
            return False

    def send_alert(
        self,
        alert_type: str,
        message: str,
        data: Optional[Dict[str, Any]] = None,
    ) -> bool:
        """Send alert webhook."""
        import requests

        try:
            payload = {
                "type": alert_type,
                "message": message,
            }
            if data:
                payload.update(data)

            response = requests.post(
                f"{self.base_url}/webhook/alert",
                json=payload,
                headers=self._headers(),
                timeout=5,
            )
            return response.status_code == 200
        except Exception as e:
            logger.error(f"Failed to send alert webhook: {str(e)}")
            return False

    def send_emergency(self) -> bool:
        """Send emergency close webhook."""
        import requests

        try:
            response = requests.post(
                f"{self.base_url}/webhook/emergency",
                headers=self._headers(),
                timeout=5,
            )
            return response.status_code == 200
        except Exception as e:
            logger.error(f"Failed to send emergency webhook: {str(e)}")
            return False

    def send_command(self, command: str, args: Optional[Dict] = None) -> bool:
        """Send command webhook."""
        import requests

        try:
            data = {"command": command}
            if args:
                data["args"] = args

            response = requests.post(
                f"{self.base_url}/webhook/command",
                json=data,
                headers=self._headers(),
                timeout=5,
            )
            return response.status_code == 200
        except Exception as e:
            logger.error(f"Failed to send command webhook: {str(e)}")
            return False

    def health_check(self) -> bool:
        """Check if webhook server is alive."""
        import requests

        try:
            response = requests.get(f"{self.base_url}/health", timeout=5)
            return response.status_code == 200
        except Exception:
            return False
