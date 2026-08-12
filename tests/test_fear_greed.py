"""Crypto Fear & Greed Index vendor: formatting and graceful degradation.

All API access is mocked, so these run without a network connection.
"""

from unittest import mock

import pytest
import requests

from tradingagents.dataflows import fear_greed


def _response(payload):
    resp = mock.Mock()
    resp.raise_for_status = mock.Mock()
    resp.json.return_value = payload
    return resp


@pytest.mark.unit
class TestFetchFearGreedIndex:
    def test_formats_entries_newest_first(self):
        payload = {
            "data": [
                {"value": "72", "value_classification": "Greed", "timestamp": "1750000000"},
                {"value": "50", "value_classification": "Neutral", "timestamp": "1749913600"},
            ]
        }
        with mock.patch.object(fear_greed.requests, "get", return_value=_response(payload)):
            out = fear_greed.fetch_fear_greed_index()
        assert "72/100 (Greed)" in out
        assert "50/100 (Neutral)" in out

    def test_network_error_returns_placeholder(self):
        with mock.patch.object(
            fear_greed.requests, "get", side_effect=requests.ConnectionError("down")
        ):
            out = fear_greed.fetch_fear_greed_index()
        assert out.startswith("<Fear & Greed Index unavailable")

    def test_empty_payload_returns_placeholder(self):
        with mock.patch.object(fear_greed.requests, "get", return_value=_response({"data": []})):
            out = fear_greed.fetch_fear_greed_index()
        assert out.startswith("<Fear & Greed Index unavailable")

    def test_malformed_json_returns_placeholder(self):
        resp = mock.Mock()
        resp.raise_for_status = mock.Mock()
        resp.json.side_effect = ValueError("bad json")
        with mock.patch.object(fear_greed.requests, "get", return_value=resp):
            out = fear_greed.fetch_fear_greed_index()
        assert out.startswith("<Fear & Greed Index unavailable")

    def test_limit_forwarded_to_request(self):
        seen = {}

        def fake_get(url, params=None, timeout=None):
            seen["params"] = params
            return _response({"data": []})

        with mock.patch.object(fear_greed.requests, "get", side_effect=fake_get):
            fear_greed.fetch_fear_greed_index(limit=3)
        assert seen["params"]["limit"] == 3
