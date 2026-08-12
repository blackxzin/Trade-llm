"""Crypto-native news vendor (CoinDesk/CoinTelegraph RSS): parsing, date
window filtering, symbol-term filtering, and graceful degradation.

All network access is mocked, so these run without a network connection.
"""

from unittest import mock

import pytest
import requests

from tradingagents.dataflows import crypto_news


def _rss(*items):
    body = "".join(
        f"<item><title>{title}</title><description>{desc}</description>"
        f"<link>{link}</link><pubDate>{pub_date}</pubDate></item>"
        for title, desc, link, pub_date in items
    )
    xml = f'<?xml version="1.0"?><rss version="2.0"><channel>{body}</channel></rss>'
    return xml.encode("utf-8")


def _response(content):
    resp = mock.Mock()
    resp.raise_for_status = mock.Mock()
    resp.content = content
    return resp


@pytest.mark.unit
class TestFetchCryptoNews:
    def test_filters_by_symbol_terms_and_date_window(self):
        feed = _rss(
            ("Bitcoin ETF sees record inflows", "BTC desc", "https://x/1",
             "Mon, 15 Jun 2026 12:00:00 GMT"),
            ("Ethereum upgrade ships", "ETH desc", "https://x/2",
             "Mon, 15 Jun 2026 12:00:00 GMT"),
            ("Bitcoin miner news, out of window", "old", "https://x/3",
             "Mon, 01 Jan 2020 12:00:00 GMT"),
        )
        with mock.patch.object(
            crypto_news.requests, "get", return_value=_response(feed)
        ):
            out = crypto_news.fetch_crypto_news("BTC-USD", "2026-06-14", "2026-06-16")
        assert "Bitcoin ETF sees record inflows" in out
        assert "Ethereum upgrade ships" not in out
        assert "out of window" not in out

    def test_unfiltered_when_base_has_no_search_terms(self):
        feed = _rss(
            ("Some unrelated headline", "desc", "https://x/1",
             "Mon, 15 Jun 2026 12:00:00 GMT"),
        )
        with mock.patch.object(
            crypto_news.requests, "get", return_value=_response(feed)
        ):
            out = crypto_news.fetch_crypto_news("UNKNOWNCOIN-USD", "2026-06-14", "2026-06-16")
        assert "Some unrelated headline" in out

    def test_invalid_date_range_returns_placeholder_without_network_call(self):
        with mock.patch.object(crypto_news.requests, "get") as get:
            out = crypto_news.fetch_crypto_news("BTC-USD", "not-a-date", "2026-06-16")
        get.assert_not_called()
        assert out.startswith("<Crypto news unavailable")

    def test_unreachable_feeds_return_placeholder(self):
        with mock.patch.object(
            crypto_news.requests, "get", side_effect=requests.ConnectionError("down")
        ):
            out = crypto_news.fetch_crypto_news("BTC-USD", "2026-06-14", "2026-06-16")
        assert out.startswith("<Crypto news unavailable")

    def test_no_matching_articles_returns_placeholder(self):
        feed = _rss(
            ("Ethereum only headline", "desc", "https://x/1", "Mon, 15 Jun 2026 12:00:00 GMT"),
        )
        with mock.patch.object(
            crypto_news.requests, "get", return_value=_response(feed)
        ):
            out = crypto_news.fetch_crypto_news("BTC-USD", "2026-06-14", "2026-06-16")
        assert out.startswith("<No BTC news found")

    def test_oversized_feed_is_skipped(self):
        feed = _rss(
            ("Bitcoin headline", "desc", "https://x/1", "Mon, 15 Jun 2026 12:00:00 GMT"),
        )
        with (
            mock.patch.object(crypto_news, "MAX_FEED_BYTES", 1),
            mock.patch.object(crypto_news.requests, "get", return_value=_response(feed)),
        ):
            out = crypto_news.fetch_crypto_news("BTC-USD", "2026-06-14", "2026-06-16")
        assert out.startswith("<Crypto news unavailable")

    def test_respects_limit(self):
        items = [
            (f"Bitcoin headline {i}", "desc", f"https://x/{i}", "Mon, 15 Jun 2026 12:00:00 GMT")
            for i in range(5)
        ]
        feed = _rss(*items)
        with mock.patch.object(
            crypto_news.requests, "get", return_value=_response(feed)
        ):
            out = crypto_news.fetch_crypto_news("BTC-USD", "2026-06-14", "2026-06-16", limit=2)
        assert out.count("Bitcoin headline") == 2
