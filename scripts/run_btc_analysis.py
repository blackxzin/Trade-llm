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
import os
import time
from datetime import datetime
from pathlib import Path

from tradingagents.agents.utils.rating import majority_rating
from tradingagents.default_config import DEFAULT_CONFIG
from tradingagents.discord_notify import bias_tag, notify_discord, notify_discord_embed
from tradingagents.env_check import require_llm_api_key, warn_if_no_discord_webhook
from tradingagents.graph.trading_graph import TradingAgentsGraph
from tradingagents.llm_clients.api_key_env import get_api_key_env

_QUOTA_ERROR_MARKERS = ("resource_exhausted", "rate_limit", "429", "quota", "504", "gateway timeout")

# Transient provider-side hiccups (server overload) that usually clear up if
# retried on the same key after a short wait, unlike a hard quota cap.
_TRANSIENT_ERROR_MARKERS = ("503", "unavailable", "high demand", "internal server error")
_MAX_TRANSIENT_RETRIES = 3
_TRANSIENT_RETRY_BACKOFF_SECONDS = 15.0


def _is_quota_error(exc: Exception) -> bool:
    text = str(exc).lower()
    return any(marker in text for marker in _QUOTA_ERROR_MARKERS)


def _is_transient_error(exc: Exception) -> bool:
    text = str(exc).lower()
    return any(marker in text for marker in _TRANSIENT_ERROR_MARKERS)


def _available_api_keys(env_var: str) -> list[str]:
    """API keys set for one provider: ``env_var``, ``env_var_2``, ``env_var_3``, ... in order."""
    keys = []
    base = os.environ.get(env_var)
    if base:
        keys.append(base)
    i = 2
    while (extra := os.environ.get(f"{env_var}_{i}")):
        keys.append(extra)
        i += 1
    return keys


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

    try:
        return _run(args)
    except Exception as exc:
        if not args.no_discord:
            notify_discord(f"⚠️ BTC live analysis failed for {args.ticker}: {exc}")
        raise


def _run(args: argparse.Namespace) -> int:
    date = args.date or datetime.now().strftime("%Y-%m-%d")

    config = DEFAULT_CONFIG.copy()
    if args.provider:
        config["llm_provider"] = args.provider

    require_llm_api_key(config["llm_provider"])
    warn_if_no_discord_webhook(args.no_discord)

    api_key_env = get_api_key_env(config["llm_provider"])
    api_keys = _available_api_keys(api_key_env) if api_key_env else []

    def _build_graph() -> TradingAgentsGraph:
        return TradingAgentsGraph(
            debug=False, config=config,
            selected_analysts=("market", "social", "news"),
        )

    ta = _build_graph()

    states, decisions = [], []
    key_index = 0
    for i in range(args.votes):
        transient_attempt = 0
        while True:
            try:
                state, decision = ta.propagate(args.ticker, date, asset_type="crypto")
                break
            except Exception as exc:
                if _is_quota_error(exc) and key_index + 1 < len(api_keys):
                    key_index += 1
                    print(f"{api_key_env} exhausted, switching to key {key_index + 1}/{len(api_keys)}: {exc}")
                    os.environ[api_key_env] = api_keys[key_index]
                    ta = _build_graph()
                    transient_attempt = 0
                    continue
                if _is_transient_error(exc) and transient_attempt < _MAX_TRANSIENT_RETRIES:
                    transient_attempt += 1
                    wait = _TRANSIENT_RETRY_BACKOFF_SECONDS * transient_attempt
                    print(f"Transient error, retry {transient_attempt}/{_MAX_TRANSIENT_RETRIES} in {wait:.0f}s: {exc}")
                    time.sleep(wait)
                    continue
                raise
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
            posted = notify_discord_embed(title=title, description=summary, rating=decision)
            if posted:
                notify_state[args.ticker] = {
                    "decision": decision, "date": date,
                    "last_notified": datetime.now().isoformat(timespec="seconds"),
                }
                _save_notify_state(state_path, notify_state)
            else:
                print("Discord post failed — not recording as notified, will retry next run.")
        else:
            print(f"\nSkipped Discord notification: decision unchanged ({decision}); use --force-notify to override.")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
