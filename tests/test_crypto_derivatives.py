"""Crypto derivatives vendor (Binance funding rate / open interest): symbol
mapping, formatting, and graceful degradation.

All API access is mocked, so these run without a network connection.
"""

from unittest import mock

import pytest
import requests

from tradingagents.dataflows import crypto_derivatives


def _response(payload):
    resp = mock.Mock()
    resp.raise_for_status = mock.Mock()
    resp.json.return_value = payload
    return resp


@pytest.mark.unit
class TestBinanceSymbol:
    @pytest.mark.parametrize(
        ("ticker", "expected"),
        [
            ("BTC-USD", "BTCUSDT"),
            ("btc-usd", "BTCUSDT"),
            ("BTCUSD", "BTCUSDT"),
            ("ETH-USD", "ETHUSDT"),
            ("AAPL", None),
            ("XYZ-USD", None),
        ],
    )
    def test_maps_canonical_symbol_to_binance_pair(self, ticker, expected):
        assert crypto_derivatives._binance_symbol(ticker) == expected


@pytest.mark.unit
class TestFetchFundingAndOpenInterest:
    def test_non_crypto_ticker_returns_placeholder_without_network_call(self):
        with mock.patch.object(crypto_derivatives.requests, "get") as get:
            out = crypto_derivatives.fetch_funding_and_open_interest("AAPL")
        get.assert_not_called()
        assert out.startswith("<Funding rate / open interest unavailable")

    def test_formats_positive_funding_as_crowded_long(self):
        premium = {
            "lastFundingRate": "0.0001",
            "markPrice": "65000.5",
            "nextFundingTime": "1750003600000",
        }
        open_interest = {"openInterest": "45000.123"}
        with mock.patch.object(
            crypto_derivatives.requests, "get",
            side_effect=[_response(premium), _response(open_interest)],
        ):
            out = crypto_derivatives.fetch_funding_and_open_interest("BTC-USD")
        assert "BTCUSDT" in out
        assert "crowded-long" in out
        assert "45000.123" in out

    def test_formats_negative_funding_as_crowded_short(self):
        premium = {"lastFundingRate": "-0.0005", "markPrice": "3000", "nextFundingTime": None}
        open_interest = {"openInterest": "1000"}
        with mock.patch.object(
            crypto_derivatives.requests, "get",
            side_effect=[_response(premium), _response(open_interest)],
        ):
            out = crypto_derivatives.fetch_funding_and_open_interest("ETH-USD")
        assert "crowded-short" in out

    def test_network_error_returns_placeholder(self):
        with mock.patch.object(
            crypto_derivatives.requests, "get", side_effect=requests.ConnectionError("down")
        ):
            out = crypto_derivatives.fetch_funding_and_open_interest("BTC-USD")
        assert out.startswith("<Funding rate / open interest unavailable")

    def test_malformed_response_returns_placeholder(self):
        with mock.patch.object(
            crypto_derivatives.requests, "get",
            side_effect=[_response({}), _response({"openInterest": "1"})],
        ):
            out = crypto_derivatives.fetch_funding_and_open_interest("BTC-USD")
        assert out.startswith("<Funding rate / open interest unavailable")
