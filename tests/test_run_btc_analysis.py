"""Tests for the API-key rotation helpers in the BTC live-analysis script."""

import importlib.util
import sys
from pathlib import Path

import pytest

_SCRIPT_PATH = Path(__file__).resolve().parent.parent / "scripts" / "run_btc_analysis.py"
_spec = importlib.util.spec_from_file_location("run_btc_analysis", _SCRIPT_PATH)
run_btc_analysis = importlib.util.module_from_spec(_spec)
sys.modules["run_btc_analysis"] = run_btc_analysis
_spec.loader.exec_module(run_btc_analysis)


@pytest.mark.unit
class TestIsQuotaError:
    @pytest.mark.parametrize(
        "message",
        [
            "429 RESOURCE_EXHAUSTED: quota exceeded",
            "openai.RateLimitError: rate_limit_exceeded",
            "You exceeded your current quota",
        ],
    )
    def test_recognizes_quota_errors(self, message):
        assert run_btc_analysis._is_quota_error(Exception(message))

    def test_ignores_unrelated_errors(self):
        assert not run_btc_analysis._is_quota_error(Exception("connection refused"))


@pytest.mark.unit
class TestAvailableApiKeys:
    def test_collects_numbered_fallback_keys_in_order(self, monkeypatch):
        monkeypatch.setenv("NVIDIA_API_KEY", "k1")
        monkeypatch.setenv("NVIDIA_API_KEY_2", "k2")
        monkeypatch.setenv("NVIDIA_API_KEY_3", "k3")
        assert run_btc_analysis._available_api_keys("NVIDIA_API_KEY") == ["k1", "k2", "k3"]

    def test_stops_at_first_gap(self, monkeypatch):
        monkeypatch.setenv("NVIDIA_API_KEY", "k1")
        monkeypatch.delenv("NVIDIA_API_KEY_2", raising=False)
        monkeypatch.setenv("NVIDIA_API_KEY_3", "k3")
        assert run_btc_analysis._available_api_keys("NVIDIA_API_KEY") == ["k1"]

    def test_empty_when_base_key_unset(self, monkeypatch):
        monkeypatch.delenv("NVIDIA_API_KEY", raising=False)
        monkeypatch.delenv("NVIDIA_API_KEY_2", raising=False)
        assert run_btc_analysis._available_api_keys("NVIDIA_API_KEY") == []
