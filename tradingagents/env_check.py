"""Startup env checks for the unattended BTC automation scripts.

Fails fast with a clear message before the (expensive, multi-LLM-call)
pipeline runs, instead of discovering a missing key deep inside a provider
SDK call.
"""

from __future__ import annotations

import os
import sys

from tradingagents.llm_clients.api_key_env import get_api_key_env


def require_llm_api_key(provider: str) -> None:
    """Exit with an actionable message if `provider`'s API key env var is unset."""
    env_var = get_api_key_env(provider)
    if env_var and not os.environ.get(env_var):
        sys.exit(f"Missing {env_var} for provider '{provider}'. Set it in .env or the environment.")


def warn_if_no_discord_webhook(no_discord: bool) -> None:
    """Print a heads-up (not a hard failure) when Discord notification is enabled but unconfigured."""
    if not no_discord and not os.environ.get("DISCORD_WEBHOOK_URL"):
        print("Note: DISCORD_WEBHOOK_URL is not set — the Discord notification will be skipped.", file=sys.stderr)
