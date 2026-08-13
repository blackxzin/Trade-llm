"""Run one live crypto analysis and print the decision.

Thin, non-interactive wrapper around TradingAgentsGraph for unattended use
(cron, /schedule routines, quick manual checks) — the interactive CLI
prompts for ticker/analysts even when the LLM provider is set via env, so it
is not suitable for automation on its own.

Usage:
    python scripts/run_btc_analysis.py
    python scripts/run_btc_analysis.py --ticker ETH-USD --date 2026-08-12
"""

from __future__ import annotations

import argparse
from datetime import datetime

from tradingagents.default_config import DEFAULT_CONFIG
from tradingagents.discord_notify import bias_tag, notify_discord_embed
from tradingagents.graph.trading_graph import TradingAgentsGraph


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ticker", default="BTC-USD")
    parser.add_argument("--date", default=None, help="YYYY-MM-DD; defaults to today")
    parser.add_argument("--provider", default=None, help="override TRADINGAGENTS_LLM_PROVIDER")
    parser.add_argument("--save-reports", action="store_true", help="write the report tree to disk")
    parser.add_argument("--no-discord", action="store_true", help="skip the Discord notification")
    args = parser.parse_args()

    date = args.date or datetime.now().strftime("%Y-%m-%d")

    config = DEFAULT_CONFIG.copy()
    if args.provider:
        config["llm_provider"] = args.provider

    ta = TradingAgentsGraph(
        debug=False, config=config,
        selected_analysts=("market", "social", "news"),
    )
    state, decision = ta.propagate(args.ticker, date, asset_type="crypto")

    print(f"{args.ticker} on {date}: {decision}")
    print()
    print(state.get("final_trade_decision", ""))

    if args.save_reports:
        path = ta.save_reports(state, args.ticker)
        print(f"\nSaved report tree to {path}")

    if not args.no_discord:
        summary = state.get("final_trade_decision", "") or decision
        notify_discord_embed(
            title=f"{args.ticker} — {date}: {decision} ({bias_tag(decision)})",
            description=summary,
            rating=decision,
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
