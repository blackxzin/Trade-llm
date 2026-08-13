"""Run one live crypto analysis and print the decision.

Thin, non-interactive wrapper around TradingAgentsGraph for unattended use
(cron, /schedule routines, quick manual checks) — the interactive CLI
prompts for ticker/analysts even when the LLM provider is set via env, so it
is not suitable for automation on its own.

Usage:
    python scripts/run_btc_analysis.py
    python scripts/run_btc_analysis.py --ticker ETH-USD --date 2026-08-12
    python scripts/run_btc_analysis.py --votes 3   # majority-vote ensemble

Discord notification is skipped when the decision is unchanged from the last
notified run for this ticker, unless --heartbeat-hours have passed since
then (default 24h) — running this every 4h via cron shouldn't spam the
channel with repeated "Hold" alerts. Pass --force-notify to always post.
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path

from tradingagents.agents.utils.rating import majority_rating
from tradingagents.default_config import DEFAULT_CONFIG
from tradingagents.discord_notify import bias_tag, notify_discord_embed
from tradingagents.env_check import require_llm_api_key, warn_if_no_discord_webhook
from tradingagents.graph.trading_graph import TradingAgentsGraph


def _load_notify_state(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def _save_notify_state(path: Path, state: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, indent=2), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--ticker", default="BTC-USD")
    parser.add_argument("--date", default=None, help="YYYY-MM-DD; defaults to today")
    parser.add_argument("--provider", default=None, help="override TRADINGAGENTS_LLM_PROVIDER")
    parser.add_argument("--save-reports", action="store_true", help="write the report tree to disk")
    parser.add_argument("--no-discord", action="store_true", help="skip the Discord notification")
    parser.add_argument(
        "--votes", type=int, default=1,
        help="run N independent passes over the same day and take the majority rating "
        "(reduces single-sample LLM noise; makes N times the LLM calls)",
    )
    parser.add_argument(
        "--heartbeat-hours", type=float, default=24.0,
        help="re-notify even on an unchanged decision after this many hours (default: 24; 0 disables the heartbeat)",
    )
    parser.add_argument("--force-notify", action="store_true", help="always post to Discord, bypassing dedup")
    parser.add_argument(
        "--state-file", default=None,
        help="JSON file tracking the last notified decision per ticker "
        "(default: <results_dir>/run_btc_analysis_state.json)",
    )
    args = parser.parse_args()
    if args.votes < 1:
        parser.error("--votes must be >= 1")

    date = args.date or datetime.now().strftime("%Y-%m-%d")

    config = DEFAULT_CONFIG.copy()
    if args.provider:
        config["llm_provider"] = args.provider

    require_llm_api_key(config["llm_provider"])
    warn_if_no_discord_webhook(args.no_discord)

    ta = TradingAgentsGraph(
        debug=False, config=config,
        selected_analysts=("market", "social", "news"),
    )

    states, decisions = [], []
    for i in range(args.votes):
        state, decision = ta.propagate(args.ticker, date, asset_type="crypto")
        states.append(state)
        decisions.append(decision)
        if args.votes > 1:
            print(f"Vote {i + 1}/{args.votes}: {decision}")

    decision = majority_rating(decisions)
    # Representative state: the first vote that actually landed on the
    # majority rating, so the printed/posted summary matches the verdict.
    state = states[decisions.index(decision)]
    consensus_count = decisions.count(decision)
    low_confidence = args.votes > 1 and consensus_count < args.votes

    if args.votes > 1:
        flag = " ⚠ LOW CONFIDENCE (not unanimous)" if low_confidence else ""
        print(f"\nConsensus ({consensus_count}/{args.votes}): {decision}{flag}")
    print(f"{args.ticker} on {date}: {decision}")
    print()
    print(state.get("final_trade_decision", ""))

    if args.save_reports:
        path = ta.save_reports(state, args.ticker)
        print(f"\nSaved report tree to {path}")

    if not args.no_discord:
        state_path = Path(args.state_file) if args.state_file else Path(config["results_dir"]) / "run_btc_analysis_state.json"
        notify_state = _load_notify_state(state_path)
        prev = notify_state.get(args.ticker)

        should_notify = True
        if not args.force_notify and prev is not None and prev.get("decision") == decision:
            hours_since = (datetime.now() - datetime.fromisoformat(prev["last_notified"])).total_seconds() / 3600
            if args.heartbeat_hours <= 0 or hours_since < args.heartbeat_hours:
                should_notify = False

        if should_notify:
            summary = state.get("final_trade_decision", "") or decision
            title = f"{args.ticker} — {date}: {decision} ({bias_tag(decision)})"
            if args.votes > 1:
                summary = f"Consensus: {consensus_count}/{args.votes} votes\n\n{summary}"
                if low_confidence:
                    title = f"⚠ LOW CONFIDENCE — {title}"
            notify_discord_embed(title=title, description=summary, rating=decision)
            notify_state[args.ticker] = {
                "decision": decision, "date": date,
                "last_notified": datetime.now().isoformat(timespec="seconds"),
            }
            _save_notify_state(state_path, notify_state)
        else:
            print(f"\nSkipped Discord notification: decision unchanged ({decision}); use --force-notify to override.")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
