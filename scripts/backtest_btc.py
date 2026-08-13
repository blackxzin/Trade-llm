"""Historical backtest for the crypto trading pipeline.

Unlike a classic indicator-based backtest, every historical day tested here
re-runs the full multi-agent LLM pipeline (market/sentiment/news analysts ->
bull/bear debate -> risk debate -> trader -> portfolio manager) against real
data up to that date. A 10-day backtest makes roughly 10x the LLM calls of a
single live run — read the result as a small directional pilot, not a
statistically powered backtest.

Each date is decided once (one LLM pass), then scored against the realized
price return at every horizon in ``--horizons`` — so a multi-horizon run
costs the same LLM calls as a single-horizon run over the same ``--days``:
  - "hit" when a directional decision (not Hold) agrees in sign with the
    realized return at that horizon
  - the strategy-weighted return uses each rating's directional lean
    (Buy=+1, Overweight=+0.5, Hold=0, Underweight=-0.5, Sell=-1) as a
    position weight against that horizon's forward return
  - a round-trip trading fee (``--fee-bps``, default 10bps = 0.10% each way,
    typical spot taker) is deducted from every directional day, scaled by
    position size, since each scored day opens and closes a position; the
    unadjusted figure is also reported as "gross"
  - compared against a flat buy-and-hold baseline over the same days
    (the benchmark itself is not fee-adjusted — it is a passive reference,
    not a repeated trade)

Usage:
    GOOGLE_API_KEY=... python scripts/backtest_btc.py --days 10
    python scripts/backtest_btc.py --days 30 --horizons 1,3,7 --ticker ETH-USD
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timedelta
from pathlib import Path

import yfinance as yf

from tradingagents.agents.utils.rating import RATING_SCORE
from tradingagents.dataflows.symbol_utils import normalize_symbol
from tradingagents.default_config import DEFAULT_CONFIG
from tradingagents.discord_notify import bias_tag, notify_discord, notify_discord_embed
from tradingagents.env_check import require_llm_api_key, warn_if_no_discord_webhook
from tradingagents.graph.trading_graph import TradingAgentsGraph


def _parse_horizons(raw: str) -> list[int]:
    try:
        horizons = sorted({int(h) for h in raw.split(",")})
    except ValueError:
        horizons = []
    if not horizons or any(h < 1 for h in horizons):
        raise argparse.ArgumentTypeError("must be a comma-separated list of positive integers, e.g. 1,3,7")
    return horizons


def _test_dates(reference: datetime, count: int, max_horizon: int) -> list[datetime]:
    """``count`` consecutive calendar days ending ``max_horizon`` days before
    ``reference``, so every tested date has a *closed* (fully known) forward
    price at every tested horizon, no later than ``reference`` itself."""
    last = reference - timedelta(days=max_horizon)
    return sorted(last - timedelta(days=i) for i in range(count))


def _append_history(path: Path, record: dict) -> None:
    """Append ``record`` as one JSON line, so successive backtest runs can be
    compared over time without re-parsing console output."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record) + "\n")


def _close_prices(canonical: str, start: datetime, end: datetime) -> dict[str, float]:
    hist = yf.Ticker(canonical).history(
        start=start.strftime("%Y-%m-%d"),
        end=(end + timedelta(days=1)).strftime("%Y-%m-%d"),
    )
    if hist.empty:
        raise SystemExit(f"No price data for {canonical} between {start:%Y-%m-%d} and {end:%Y-%m-%d}")
    if hist.index.tz is not None:
        hist.index = hist.index.tz_localize(None)
    return {ts.strftime("%Y-%m-%d"): float(close) for ts, close in hist["Close"].items()}


def _score_horizon(rows: list[tuple[str, str, float]], fee_bps: float) -> dict:
    """Score one horizon's already-filtered ``(date, decision, forward_return)`` rows.

    ``strategy_return`` is net of a round-trip fee (``2 * fee_bps`` scaled by
    position size) charged on every directional day; ``strategy_return_gross``
    is the same figure before that deduction, for comparison.
    """
    directional = [(d, dec, ret) for d, dec, ret in rows if dec != "Hold"]
    hits = sum(1 for _, dec, ret in directional if (RATING_SCORE[dec] > 0) == (ret > 0))
    hit_rate = hits / len(directional) if directional else None

    fee_rate = 2 * fee_bps / 10_000  # round trip: one entry + one exit
    gross = sum(RATING_SCORE[dec] * ret for _, dec, ret in rows) / len(rows)
    fee_drag = sum(fee_rate * abs(RATING_SCORE[dec]) for _, dec, _ in rows) / len(rows)
    return {
        "days_scored": len(rows),
        "directional_days": len(directional),
        "hit_rate": hit_rate,
        "strategy_return": gross - fee_drag,
        "strategy_return_gross": gross,
        "buy_hold_return": sum(ret for _, _, ret in rows) / len(rows),
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--ticker", default="BTC-USD")
    parser.add_argument("--days", type=int, default=10, help="number of historical days to test")
    parser.add_argument(
        "--horizons", type=_parse_horizons, default=[3],
        help="comma-separated list of forward day-counts to score against, e.g. 1,3,7 (default: 3)",
    )
    parser.add_argument(
        "--fee-bps", type=float, default=10.0,
        help="one-way trading fee in basis points, charged round-trip on directional days "
        "(default: 10bps = 0.10%%, typical spot taker; 0 to disable)",
    )
    parser.add_argument("--provider", default=None, help="override TRADINGAGENTS_LLM_PROVIDER")
    parser.add_argument("--no-discord", action="store_true", help="skip the Discord notification")
    parser.add_argument(
        "--history-file", default=None,
        help="JSONL file to append this run's summary to (default: <results_dir>/backtest_history.jsonl)",
    )
    args = parser.parse_args()

    config = DEFAULT_CONFIG.copy()
    if args.provider:
        config["llm_provider"] = args.provider

    require_llm_api_key(config["llm_provider"])
    warn_if_no_discord_webhook(args.no_discord)

    canonical = normalize_symbol(args.ticker)
    horizons = args.horizons
    max_horizon = max(horizons)
    # Yesterday, not "now": guarantees every tested horizon's forward price
    # point for the most recent tested date is a closed daily bar.
    reference = datetime.now() - timedelta(days=1)
    dates = _test_dates(reference, args.days, max_horizon)

    prices = _close_prices(
        canonical, dates[0] - timedelta(days=2), dates[-1] + timedelta(days=max_horizon + 1)
    )

    ta = TradingAgentsGraph(
        debug=False, config=config,
        selected_analysts=("market", "social", "news"),
    )

    horizons_label = ",".join(f"{h}d" for h in horizons)
    print(f"Backtesting {args.ticker} ({canonical}): {args.days} days, forward horizons: {horizons_label}")
    print(f"Range: {dates[0]:%Y-%m-%d} to {dates[-1]:%Y-%m-%d}\n")

    errors: list[str] = []
    # One entry per successfully-decided date: decision plus each horizon's
    # forward return (None where the horizon's price point is missing).
    decision_rows: list[tuple[str, str, dict[int, float | None]]] = []
    for d in dates:
        date_str = d.strftime("%Y-%m-%d")
        c0 = prices.get(date_str)

        try:
            _, decision = ta.propagate(args.ticker, date_str, asset_type="crypto")
        except Exception as e:  # noqa: BLE001 — one bad day should not kill the run
            print(f"{date_str}: ERROR {e}")
            errors.append(f"{date_str}: {e}")
            continue

        rets: dict[int, float | None] = {}
        for h in horizons:
            c1 = prices.get((d + timedelta(days=h)).strftime("%Y-%m-%d"))
            rets[h] = (c1 - c0) / c0 if c0 is not None and c1 is not None else None
        decision_rows.append((date_str, decision, rets))

        ret_str = "  ".join(
            f"{h}d={rets[h]:+.2%}" if rets[h] is not None else f"{h}d=n/a" for h in horizons
        )
        print(f"{date_str}: decision={decision:<12} {bias_tag(decision):<12} {ret_str}")

    if not decision_rows:
        print("\nNo scored days — nothing to summarize.")
        if not args.no_discord:
            message = f"Backtest {args.ticker}: no scored days ({dates[0]:%Y-%m-%d} to {dates[-1]:%Y-%m-%d})."
            if errors:
                message += "\n\nErrors:\n" + "\n".join(errors)
            notify_discord(message)
        return 1

    summaries: dict[int, dict | None] = {}
    for h in horizons:
        rows_h = [(d, dec, rets[h]) for d, dec, rets in decision_rows if rets[h] is not None]
        summaries[h] = _score_horizon(rows_h, args.fee_bps) if rows_h else None

    print("\n" + "=" * 60)
    for h in horizons:
        s = summaries[h]
        if s is None:
            print(f"{h}d horizon: no price data to score")
            continue
        hit_str = f"{s['hit_rate']:.0%}" if s["hit_rate"] is not None else "n/a (every day was Hold)"
        print(
            f"{h}d horizon: days={s['days_scored']} (directional={s['directional_days']}) "
            f"hit-rate={hit_str} strategy(net)={s['strategy_return']:+.2%} "
            f"strategy(gross)={s['strategy_return_gross']:+.2%} buy&hold={s['buy_hold_return']:+.2%}"
        )
    print(f"\nFee: {args.fee_bps:g}bps one-way, round-trip, scaled by position size on directional days.")
    print(
        "Sample size is tiny — treat this as 'does the mechanism work', "
        "not a validated edge. Re-run with more --days for a steadier read."
    )

    history_path = Path(args.history_file) if args.history_file else Path(config["results_dir"]) / "backtest_history.jsonl"
    _append_history(history_path, {
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "ticker": args.ticker,
        "canonical": canonical,
        "days": args.days,
        "range_start": dates[0].strftime("%Y-%m-%d"),
        "range_end": dates[-1].strftime("%Y-%m-%d"),
        "fee_bps": args.fee_bps,
        "horizons": {str(h): summaries[h] for h in horizons},
    })
    print(f"Appended summary to {history_path}")

    if not args.no_discord:
        lines = []
        for h in horizons:
            s = summaries[h]
            if s is None:
                lines.append(f"{h}d: no price data")
                continue
            hit_str = f"{s['hit_rate']:.0%}" if s["hit_rate"] is not None else "n/a"
            lines.append(
                f"{h}d — hit-rate {hit_str} | strategy(net) {s['strategy_return']:+.2%} | "
                f"b&h {s['buy_hold_return']:+.2%}"
            )
        # No single rating for an aggregate run — borrow the bias color scale
        # by the sign of the first-listed horizon's strategy return.
        primary = summaries[horizons[0]]
        primary_return = primary["strategy_return"] if primary else 0.0
        pseudo_rating = "Buy" if primary_return > 0 else "Sell" if primary_return < 0 else "Hold"
        description = "\n".join(lines)
        if errors:
            description += f"\n\n⚠ {len(errors)} day(s) errored:\n" + "\n".join(errors)
        notify_discord_embed(
            title=f"Backtest {args.ticker} — {dates[0]:%Y-%m-%d} to {dates[-1]:%Y-%m-%d} ({horizons_label})",
            description=description,
            rating=pseudo_rating,
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
