"""Crypto derivatives-market vendor: funding rate & open interest.

Funding rate and open interest are leverage/positioning signals with no
equity analogue: a persistently positive funding rate means leveraged longs
are paying shorts to stay open (a crowded-long lean with squeeze risk to the
downside; the reverse for a negative rate), and open interest rising
alongside price confirms fresh leveraged money entering rather than short
covering. Neither is visible from OHLCV or news alone.

Uses Binance's public USDT-margined futures API
(https://developers.binance.com/docs/derivatives/usds-margined-futures) — no
key, no auth, generous public rate limits. Binance is the deepest crypto
derivatives venue by open interest, so its perpetual swap is a reasonable
proxy for market-wide positioning even for a trader who does not use Binance.
"""

from __future__ import annotations

import contextlib
import logging
from datetime import datetime, timezone

import requests

from .symbol_utils import crypto_base

logger = logging.getLogger(__name__)

BINANCE_FAPI_BASE = "https://fapi.binance.com/fapi/v1"

# Network timeout (seconds), consistent with the other vendors.
REQUEST_TIMEOUT = 30


def _binance_symbol(ticker: str) -> str | None:
    """Map a canonical crypto symbol (e.g. ``BTC-USD``) to its Binance
    USDT-margined perpetual futures symbol (e.g. ``BTCUSDT``).

    Returns None for a ticker that isn't a recognized crypto base — the
    caller degrades to a placeholder rather than guessing a futures symbol
    for an equity.
    """
    base = crypto_base(ticker)
    return f"{base}USDT" if base else None


def fetch_funding_and_open_interest(ticker: str) -> str:
    """Return current funding rate and open interest for ``ticker``'s
    USDT-margined perpetual future.

    Args:
        ticker: Any form ``crypto_base`` resolves (e.g. ``BTC-USD``, ``BTCUSD``).

    Returns:
        A formatted block with mark price, funding rate, next funding time,
        and open interest — or an ``<unavailable>`` placeholder (non-crypto
        ticker, unlisted pair, or network failure) so the caller can inject
        this directly into a prompt without its own exception handling.
    """
    symbol = _binance_symbol(ticker)
    if symbol is None:
        return "<Funding rate / open interest unavailable: not a recognized crypto symbol>"

    try:
        premium_resp = requests.get(
            f"{BINANCE_FAPI_BASE}/premiumIndex", params={"symbol": symbol}, timeout=REQUEST_TIMEOUT
        )
        premium_resp.raise_for_status()
        premium = premium_resp.json()

        oi_resp = requests.get(
            f"{BINANCE_FAPI_BASE}/openInterest", params={"symbol": symbol}, timeout=REQUEST_TIMEOUT
        )
        oi_resp.raise_for_status()
        open_interest_data = oi_resp.json()
    except (requests.RequestException, ValueError) as e:
        logger.warning("Funding/open-interest fetch failed for %s: %s", symbol, e)
        return f"<Funding rate / open interest unavailable for {symbol}: fetch failed>"

    try:
        funding_rate_pct = float(premium["lastFundingRate"]) * 100
    except (KeyError, TypeError, ValueError):
        return f"<Funding rate / open interest unavailable for {symbol}: malformed response>"

    mark_price = premium.get("markPrice", "?")
    next_funding_ms = premium.get("nextFundingTime")
    next_funding = "unknown"
    if next_funding_ms:
        with contextlib.suppress(TypeError, ValueError, OverflowError):
            next_funding = datetime.fromtimestamp(
                int(next_funding_ms) / 1000, tz=timezone.utc
            ).strftime("%Y-%m-%d %H:%M UTC")

    open_interest = open_interest_data.get("openInterest", "?")
    lean = "crowded-long" if funding_rate_pct > 0 else "crowded-short" if funding_rate_pct < 0 else "balanced"

    return (
        f"Binance perpetual futures ({symbol}):\n"
        f"- Mark price: {mark_price}\n"
        f"- Funding rate: {funding_rate_pct:+.4f}% (positive = longs pay shorts = {lean} lean)\n"
        f"- Next funding: {next_funding}\n"
        f"- Open interest: {open_interest} {symbol.removesuffix('USDT')} contracts"
    )
