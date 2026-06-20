from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

log = logging.getLogger(__name__)


@dataclass
class NotificationConfig:
    enabled: bool = False
    webhook_url: str = ""
    timeout_seconds: float = 3.0
    dedupe_window_seconds: int = 300


class HomeAssistantNotifier:
    def __init__(self, config: NotificationConfig) -> None:
        self.config = config
        self._last_sent: dict[str, float] = {}

    def send(
        self,
        *,
        title: str,
        message: str,
        severity: str = "info",
        event_type: str = "BOT_EVENT",
        tag: str = "tqqq_bot_status",
        group: str = "trading_bot",
        extra: dict[str, Any] | None = None,
    ) -> None:
        if not self.config.enabled:
            return

        if not self.config.webhook_url:
            log.warning("Notifications enabled but webhook_url is missing")
            return

        now = time.time()
        dedupe_key = f"{event_type}:{tag}:{message}"
        last_sent = self._last_sent.get(dedupe_key)

        if last_sent and now - last_sent < self.config.dedupe_window_seconds:
            return

        payload: dict[str, Any] = {
            "title": title,
            "message": message,
            "severity": severity,
            "event_type": event_type,
            "channel": "Trading Bot",
            "importance": "high" if severity in {"error", "critical"} else "default",
            "tag": tag,
            "group": group,
        }

        if extra:
            payload["extra"] = extra

        try:
            body = json.dumps(payload).encode("utf-8")
            request = Request(
                self.config.webhook_url,
                data=body,
                headers={"Content-Type": "application/json"},
                method="POST",
            )

            with urlopen(request, timeout=self.config.timeout_seconds) as response:
                if response.status >= 400:
                    log.warning("Home Assistant webhook returned HTTP %s", response.status)
                    return

            self._last_sent[dedupe_key] = now

        except (HTTPError, URLError, TimeoutError, OSError):
            log.exception("Failed to send Home Assistant notification")