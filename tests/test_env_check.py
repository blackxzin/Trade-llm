"""Tests for the startup env checks used by the BTC automation scripts."""

import pytest

from tradingagents import env_check


@pytest.mark.unit
class TestRequireLlmApiKey:
    def test_exits_when_required_key_missing(self, monkeypatch):
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        with pytest.raises(SystemExit, match="OPENAI_API_KEY"):
            env_check.require_llm_api_key("openai")

    def test_passes_when_required_key_present(self, monkeypatch):
        monkeypatch.setenv("GOOGLE_API_KEY", "x")
        env_check.require_llm_api_key("google")  # no raise

    def test_passes_for_provider_with_no_key_env(self, monkeypatch):
        env_check.require_llm_api_key("ollama")  # no raise

    def test_passes_for_unknown_provider(self, monkeypatch):
        env_check.require_llm_api_key("totally-unknown-provider")  # no raise


@pytest.mark.unit
class TestWarnIfNoDiscordWebhook:
    def test_warns_when_enabled_and_unset(self, monkeypatch, capsys):
        monkeypatch.delenv("DISCORD_WEBHOOK_URL", raising=False)
        env_check.warn_if_no_discord_webhook(no_discord=False)
        assert "DISCORD_WEBHOOK_URL is not set" in capsys.readouterr().err

    def test_silent_when_discord_disabled(self, monkeypatch, capsys):
        monkeypatch.delenv("DISCORD_WEBHOOK_URL", raising=False)
        env_check.warn_if_no_discord_webhook(no_discord=True)
        assert capsys.readouterr().err == ""

    def test_silent_when_webhook_configured(self, monkeypatch, capsys):
        monkeypatch.setenv("DISCORD_WEBHOOK_URL", "https://discord.example/hook")
        env_check.warn_if_no_discord_webhook(no_discord=False)
        assert capsys.readouterr().err == ""
