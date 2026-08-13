"""Tests for the Discord webhook notifier used by the BTC automation scripts.

All HTTP access is mocked, so these run without a network connection.
"""

from unittest import mock

import pytest
import requests

from tradingagents import discord_notify


def _ok_response():
    resp = mock.Mock()
    resp.raise_for_status = mock.Mock()
    return resp


@pytest.mark.unit
class TestBiasTag:
    def test_buy_and_overweight_are_long(self):
        assert discord_notify.bias_tag("Buy") == "🟢 LONG"
        assert discord_notify.bias_tag("Overweight") == "🟢 LONG"

    def test_sell_and_underweight_are_short(self):
        assert discord_notify.bias_tag("Sell") == "🔴 SHORT"
        assert discord_notify.bias_tag("Underweight") == "🔴 SHORT"

    def test_hold_is_neutral(self):
        assert discord_notify.bias_tag("Hold") == "⚪ NEUTRAL"

    def test_unrecognized_rating_is_unknown(self):
        assert discord_notify.bias_tag("Whatever") == "❓ UNKNOWN"


@pytest.mark.unit
class TestNotifyDiscord:
    def test_no_webhook_configured_returns_false(self, monkeypatch):
        monkeypatch.delenv("DISCORD_WEBHOOK_URL", raising=False)
        assert discord_notify.notify_discord("hello") is False

    def test_posts_content_to_configured_webhook(self, monkeypatch):
        monkeypatch.setenv("DISCORD_WEBHOOK_URL", "https://discord.example/hook")
        with mock.patch.object(discord_notify.requests, "post", return_value=_ok_response()) as post:
            ok = discord_notify.notify_discord("hello world")
        assert ok is True
        args, kwargs = post.call_args
        assert args[0] == "https://discord.example/hook"
        assert kwargs["json"] == {"content": "hello world"}
        assert kwargs["timeout"] == 10

    def test_explicit_webhook_url_overrides_env(self, monkeypatch):
        monkeypatch.setenv("DISCORD_WEBHOOK_URL", "https://discord.example/env-hook")
        with mock.patch.object(discord_notify.requests, "post", return_value=_ok_response()) as post:
            discord_notify.notify_discord("hi", webhook_url="https://discord.example/explicit-hook")
        assert post.call_args[0][0] == "https://discord.example/explicit-hook"

    def test_request_exception_returns_false(self, monkeypatch):
        monkeypatch.setenv("DISCORD_WEBHOOK_URL", "https://discord.example/hook")
        with mock.patch.object(
            discord_notify.requests, "post", side_effect=requests.ConnectionError("down")
        ):
            assert discord_notify.notify_discord("hello") is False

    def test_http_error_status_returns_false(self, monkeypatch):
        monkeypatch.setenv("DISCORD_WEBHOOK_URL", "https://discord.example/hook")
        resp = mock.Mock()
        resp.raise_for_status.side_effect = requests.HTTPError("400 Bad Request")
        with mock.patch.object(discord_notify.requests, "post", return_value=resp):
            assert discord_notify.notify_discord("hello") is False

    def test_long_message_is_truncated(self, monkeypatch):
        monkeypatch.setenv("DISCORD_WEBHOOK_URL", "https://discord.example/hook")
        long_message = "x" * 2500
        with mock.patch.object(discord_notify.requests, "post", return_value=_ok_response()) as post:
            discord_notify.notify_discord(long_message)
        sent_content = post.call_args.kwargs["json"]["content"]
        assert len(sent_content) == 2000
        assert sent_content.endswith("…")


@pytest.mark.unit
class TestNotifyDiscordEmbed:
    def test_no_webhook_configured_returns_false(self, monkeypatch):
        monkeypatch.delenv("DISCORD_WEBHOOK_URL", raising=False)
        assert discord_notify.notify_discord_embed("title", "body") is False

    def test_posts_embed_with_bias_color(self, monkeypatch):
        monkeypatch.setenv("DISCORD_WEBHOOK_URL", "https://discord.example/hook")
        with mock.patch.object(discord_notify.requests, "post", return_value=_ok_response()) as post:
            discord_notify.notify_discord_embed("BTC-USD: Buy", "details", rating="Buy")
        embed = post.call_args.kwargs["json"]["embeds"][0]
        assert embed["title"] == "BTC-USD: Buy"
        assert embed["description"] == "details"
        assert embed["color"] == discord_notify._BIAS_COLOR["Buy"]

    def test_sell_and_buy_have_different_colors(self, monkeypatch):
        monkeypatch.setenv("DISCORD_WEBHOOK_URL", "https://discord.example/hook")
        with mock.patch.object(discord_notify.requests, "post", return_value=_ok_response()) as post:
            discord_notify.notify_discord_embed("t", "d", rating="Sell")
        sell_color = post.call_args.kwargs["json"]["embeds"][0]["color"]
        with mock.patch.object(discord_notify.requests, "post", return_value=_ok_response()) as post:
            discord_notify.notify_discord_embed("t", "d", rating="Buy")
        buy_color = post.call_args.kwargs["json"]["embeds"][0]["color"]
        assert sell_color != buy_color

    def test_missing_rating_falls_back_to_neutral_color(self, monkeypatch):
        monkeypatch.setenv("DISCORD_WEBHOOK_URL", "https://discord.example/hook")
        with mock.patch.object(discord_notify.requests, "post", return_value=_ok_response()) as post:
            discord_notify.notify_discord_embed("t", "d")
        embed = post.call_args.kwargs["json"]["embeds"][0]
        assert embed["color"] == discord_notify._UNKNOWN_COLOR

    def test_unrecognized_rating_falls_back_to_neutral_color(self, monkeypatch):
        monkeypatch.setenv("DISCORD_WEBHOOK_URL", "https://discord.example/hook")
        with mock.patch.object(discord_notify.requests, "post", return_value=_ok_response()) as post:
            discord_notify.notify_discord_embed("t", "d", rating="Whatever")
        embed = post.call_args.kwargs["json"]["embeds"][0]
        assert embed["color"] == discord_notify._UNKNOWN_COLOR

    def test_long_description_is_truncated(self, monkeypatch):
        monkeypatch.setenv("DISCORD_WEBHOOK_URL", "https://discord.example/hook")
        long_description = "y" * 2500
        with mock.patch.object(discord_notify.requests, "post", return_value=_ok_response()) as post:
            discord_notify.notify_discord_embed("t", long_description)
        embed = post.call_args.kwargs["json"]["embeds"][0]
        assert len(embed["description"]) == 2000
        assert embed["description"].endswith("…")
