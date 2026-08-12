"""Crypto-native news vendor: CoinDesk + CoinTelegraph RSS.

The configured news_data vendors (Yahoo/Alpha Vantage) are equity-oriented
and thin on crypto-specific events — protocol upgrades, ETF flows, exchange
incidents, regulatory action — that move BTC/ETH more than most headlines
picked up by a general finance feed. These are public RSS feeds, parsed with
the standard library so no extra dependency is needed.

Both feeds are fixed, reputable HTTPS sources (not user-controlled URLs), so
``xml.etree.ElementTree`` — which does not resolve external entities — is
adequate here; the byte-size cap below is defense-in-depth against a
malformed/hostile response, not a substitute for that.
"""

from __future__ import annotations

import logging
from datetime import datetime
from email.utils import parsedate_to_datetime
from xml.etree import ElementTree

import requests

from .symbol_utils import crypto_base

logger = logging.getLogger(__name__)

_FEEDS = {
    "CoinDesk": "https://www.coindesk.com/arc/outboundfeeds/rss/",
    "CoinTelegraph": "https://cointelegraph.com/rss",
}

# Network timeout (seconds), consistent with the other vendors.
REQUEST_TIMEOUT = 30

# Refuse to parse an implausibly large feed response.
MAX_FEED_BYTES = 5_000_000

# Search terms per crypto base, for filtering the (asset-agnostic) feeds down
# to the one being analyzed. A base with no entry here gets an unfiltered feed
# rather than an empty result.
_SEARCH_TERMS: dict[str, tuple[str, ...]] = {
    "BTC": ("bitcoin", "btc"),
    "ETH": ("ethereum", "eth", "ether"),
    "SOL": ("solana", "sol"),
    "XRP": ("xrp", "ripple"),
    "ADA": ("cardano", "ada"),
    "DOGE": ("dogecoin", "doge"),
    "LTC": ("litecoin", "ltc"),
    "BCH": ("bitcoin cash", "bch"),
    "DOT": ("polkadot", "dot"),
    "AVAX": ("avalanche", "avax"),
    "LINK": ("chainlink", "link"),
}


def _parse_feed(xml_bytes: bytes, source: str) -> list[dict]:
    items = []
    root = ElementTree.fromstring(xml_bytes)
    for item in root.iter("item"):
        title = (item.findtext("title") or "").strip()
        description = (item.findtext("description") or "").strip()
        link = (item.findtext("link") or "").strip()
        pub_date_raw = item.findtext("pubDate")
        try:
            pub_date = parsedate_to_datetime(pub_date_raw) if pub_date_raw else None
        except (TypeError, ValueError):
            pub_date = None
        if pub_date is not None and pub_date.tzinfo is not None:
            pub_date = pub_date.replace(tzinfo=None)
        items.append(
            {
                "title": title,
                "description": description,
                "link": link,
                "pub_date": pub_date,
                "source": source,
            }
        )
    return items


def _fetch_feed_items(source: str, url: str) -> list[dict]:
    try:
        response = requests.get(
            url, timeout=REQUEST_TIMEOUT, headers={"User-Agent": "Mozilla/5.0"}
        )
        response.raise_for_status()
        if len(response.content) > MAX_FEED_BYTES:
            logger.warning("%s RSS feed exceeded size cap, skipping", source)
            return []
        return _parse_feed(response.content, source)
    except (requests.RequestException, ElementTree.ParseError) as e:
        logger.warning("Failed to fetch %s RSS feed: %s", source, e)
        return []


def fetch_crypto_news(
    ticker: str, start_date: str, end_date: str, limit: int = 15
) -> str:
    """Return crypto-native news for ``ticker``'s base asset in a date window.

    Args:
        ticker: Any form ``crypto_base`` resolves (e.g. ``BTC-USD``, ``BTCUSD``).
        start_date: Window start, ``YYYY-MM-DD``, inclusive.
        end_date: Window end, ``YYYY-MM-DD``, inclusive.
        limit: Max articles to return, newest first.

    Returns:
        A formatted block of dated headlines with source, description, and
        link, or a placeholder (invalid range, unreachable feeds, or no
        matching articles) so the caller can inject this directly into a
        prompt without its own exception handling.
    """
    try:
        start = datetime.strptime(start_date, "%Y-%m-%d")
        end = datetime.strptime(end_date, "%Y-%m-%d").replace(
            hour=23, minute=59, second=59
        )
    except ValueError:
        return "<Crypto news unavailable: invalid date range>"

    all_items = [
        item
        for source, url in _FEEDS.items()
        for item in _fetch_feed_items(source, url)
    ]
    if not all_items:
        return "<Crypto news unavailable: no feeds reachable>"

    base = crypto_base(ticker)
    terms = _SEARCH_TERMS.get(base, ()) if base else ()

    filtered = []
    for item in all_items:
        if item["pub_date"] is None or not (start <= item["pub_date"] <= end):
            continue
        haystack = f"{item['title']} {item['description']}".lower()
        if terms and not any(term in haystack for term in terms):
            continue
        filtered.append(item)

    if not filtered:
        return (
            f"<No {base or 'crypto'} news found from CoinDesk/CoinTelegraph "
            f"in {start_date} to {end_date}>"
        )

    filtered.sort(key=lambda i: i["pub_date"], reverse=True)
    lines = [
        f"[{item['pub_date'].strftime('%Y-%m-%d')}] ({item['source']}) {item['title']}\n"
        f"{item['description']}\n{item['link']}"
        for item in filtered[:limit]
    ]
    return "\n\n".join(lines)
