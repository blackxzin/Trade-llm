"""Minimal Discord webhook notifier shared by the automation scripts.

Reads the webhook URL from ``DISCORD_WEBHOOK_URL`` (see ``.env.example``) so
no token lives in source. Failures are logged, never raised — a notification
outage must not take down a live run or a backtest.
"""

from __future__ import annotations

import logging
import os

import requests

logger = logging.getLogger(__name__)

_DISCORD_CONTENT_LIMIT = 2000


def notify_discord(message: str, webhook_url: str | None = None) -> bool:
    """Post ``message`` to the configured Discord webhook.

    Returns ``True`` on success, ``False`` if no webhook is configured or the
    request failed (details logged, not raised).
    """
    url = webhook_url or os.environ.get("DISCORD_WEBHOOK_URL")
    if not url:
        return False

    content = message if len(message) <= _DISCORD_CONTENT_LIMIT else message[: _DISCORD_CONTENT_LIMIT - 1] + "…"

    try:
        response = requests.post(url, json={"content": content}, timeout=10)
        response.raise_for_status()
    except requests.RequestException as e:
        logger.warning("Discord notification failed: %s", e)
        return False
    return True
