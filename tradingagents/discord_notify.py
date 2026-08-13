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

_BIAS_TAG = {
    "Buy": "🟢 LONG",
    "Overweight": "🟢 LONG",
    "Hold": "⚪ NEUTRAL",
    "Underweight": "🔴 SHORT",
    "Sell": "🔴 SHORT",
}

# Discord embed "color" is a decimal RGB int, not hex/CSS.
_BIAS_COLOR = {
    "Buy": 0x2ECC71,
    "Overweight": 0x2ECC71,
    "Hold": 0x95A5A6,
    "Underweight": 0xE74C3C,
    "Sell": 0xE74C3C,
}
_UNKNOWN_COLOR = 0x99AAB5


def bias_tag(rating: str) -> str:
    """Map a 5-tier portfolio rating (Buy/Overweight/Hold/Underweight/Sell) to a LONG/SHORT/NEUTRAL tag."""
    return _BIAS_TAG.get(rating, "❓ UNKNOWN")


def _post(payload: dict, webhook_url: str | None) -> bool:
    url = webhook_url or os.environ.get("DISCORD_WEBHOOK_URL")
    if not url:
        return False

    try:
        response = requests.post(url, json=payload, timeout=10)
        response.raise_for_status()
    except requests.RequestException as e:
        logger.warning("Discord notification failed: %s", e)
        return False
    return True


def notify_discord(message: str, webhook_url: str | None = None) -> bool:
    """Post plain ``message`` to the configured Discord webhook.

    Returns ``True`` on success, ``False`` if no webhook is configured or the
    request failed (details logged, not raised).
    """
    content = message if len(message) <= _DISCORD_CONTENT_LIMIT else message[: _DISCORD_CONTENT_LIMIT - 1] + "…"
    return _post({"content": content}, webhook_url)


def notify_discord_embed(
    title: str, description: str, rating: str | None = None, webhook_url: str | None = None
) -> bool:
    """Post ``description`` as a Discord embed under ``title``, side-colored by ``rating``'s bias.

    ``rating`` is one of Buy/Overweight/Hold/Underweight/Sell (green/gray/red);
    unset or unrecognized falls back to a neutral gray. Same failure semantics
    as :func:`notify_discord` — never raises, returns ``False`` on failure.
    """
    if len(description) > _DISCORD_CONTENT_LIMIT:
        description = description[: _DISCORD_CONTENT_LIMIT - 1] + "…"

    color = _BIAS_COLOR.get(rating, _UNKNOWN_COLOR) if rating else _UNKNOWN_COLOR
    embed = {"title": title, "description": description, "color": color}
    return _post({"embeds": [embed]}, webhook_url)
