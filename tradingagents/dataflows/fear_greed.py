"""Crypto Fear & Greed Index vendor.

Surfaces alternative.me's daily Fear & Greed Index — a crypto-specific
market-sentiment gauge (0 = extreme fear, 100 = extreme greed) with no
equity analogue in this pipeline. Complements StockTwits/Reddit chatter with
a slower-moving, aggregate positioning signal.

Uses alternative.me's public API (https://alternative.me/crypto/fear-and-greed-index/)
— no key, no auth.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

import requests

logger = logging.getLogger(__name__)

FNG_URL = "https://api.alternative.me/fng/"

# Network timeout (seconds), consistent with the other vendors.
REQUEST_TIMEOUT = 30

# Default number of daily readings to return (today plus recent trend).
DEFAULT_LIMIT = 7


def fetch_fear_greed_index(limit: int | None = None) -> str:
    """Return the most recent Fear & Greed Index readings, newest first.

    Args:
        limit: How many daily readings to fetch; ``None`` uses DEFAULT_LIMIT.

    Returns:
        A formatted block of date / value / classification lines, or an
        ``<unavailable>`` placeholder on any network or parse failure so the
        caller can inject this directly into a prompt without its own
        exception handling.
    """
    if limit is None:
        limit = DEFAULT_LIMIT

    try:
        response = requests.get(
            FNG_URL, params={"limit": limit, "format": "json"}, timeout=REQUEST_TIMEOUT
        )
        response.raise_for_status()
        payload = response.json()
    except (requests.RequestException, ValueError) as e:
        logger.warning("Fear & Greed Index fetch failed: %s", e)
        return "<Fear & Greed Index unavailable: fetch failed>"

    entries = payload.get("data") or []
    if not entries:
        return "<Fear & Greed Index unavailable: no data returned>"

    lines = []
    for entry in entries:
        value = entry.get("value")
        classification = entry.get("value_classification", "Unknown")
        timestamp = entry.get("timestamp")
        try:
            date_str = datetime.fromtimestamp(int(timestamp), tz=timezone.utc).strftime("%Y-%m-%d")
        except (TypeError, ValueError):
            date_str = "?"
        lines.append(f"{date_str}: {value}/100 ({classification})")

    return "\n".join(lines)
