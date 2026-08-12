"""Historical backtest for the crypto trading pipeline.

Unlike a classic indicator-based backtest, every historical day tested here
re-runs the full multi-agent LLM pipeline (market/sentiment/news analysts ->
bull/bear debate -> risk debate -> trader -> portfolio manager) against real
data up to that date. A 10-day backtest makes roughly 10x the LLM calls of a
single live run — read the result as a small directional pilot, not a
statistically powered backtest.

For each tested date, the decision (Buy/Overweight/Hold/Underweight/Sell) is
scored against the realized price return ``--horizon`` days later:
  - "hit" when a directional decision (not Hold) agrees in sign with the
    realized return
  - the strategy-weighted return uses each rating's directional lean
    (Buy=+1, Overweight=+0.5, Hold=0, Underweight=-0.5, Sell=-1) as a
    position weight against that day's forward return
  - compared against a flat buy-and-hold baseline over the same days

Usage:
    GOOGLE_API_KEY=... python scripts/backtest_btc.py --days 10
    python scripts/backtest_btc.py --days 30 --horizon 5 --ticker ETH-USD
"""

from __future__ import annotations

import argparse
from datetime import datetime, timedelta

import yfinance as yf

from tradingagents.dataflows.symbol_utils import normalize_symbol
from tradingagents.default_config import DEFAULT_CONFIG
from tradingagents.discord_notify import notify_discord
from tradingagents.graph.trading_graph import TradingAgentsGraph

# Directional lean per rating: +1 fully long ... -1 fully short. Used both to
# score hit-rate direction and as a position weight for the strategy return.
_RATING_SCORE = {
    "Buy": 1.0, "Overweight": 0.5, "Hold": 0.0, "Underweight": -0.5, "Sell": -1.0,
}


def _test_dates(reference: datetime, count: int, horizon: int) -> list[datetime]:
    """``count`` consecutive calendar days ending ``horizon`` days before
    ``reference``, so every tested date has a *closed* (fully known) forward
    price ``horizon`` days later, no later than ``reference`` itself."""
    last = reference - timedelta(days=horizon)
    return sorted(last - timedelta(days=i) for i in range(count))


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


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--ticker", default="BTC-USD")
    parser.add_argument("--days", type=int, default=10, help="number of historical days to test")
    parser.add_argument("--horizon", type=int, default=3, help="days forward to measure return over")
    parser.add_argument("--provider", default=None, help="override TRADINGAGENTS_LLM_PROVIDER")
    parser.add_argument("--no-discord", action="store_true", help="skip the Discord notification")
    args = parser.parse_args()

    config = DEFAULT_CONFIG.copy()
    if args.provider:
        config["llm_provider"] = args.provider

    canonical = normalize_symbol(args.ticker)
    # Yesterday, not "now": guarantees the horizon-forward price point for the
    # most recent tested date is a closed daily bar, not a partial in-progress one.
    reference = datetime.now() - timedelta(days=1)
    dates = _test_dates(reference, args.days, args.horizon)

    prices = _close_prices(
        canonical, dates[0] - timedelta(days=2), dates[-1] + timedelta(days=args.horizon + 1)
    )

    ta = TradingAgentsGraph(
        debug=False, config=config,
        selected_analysts=("market", "social", "news"),
    )

    print(f"Backtesting {args.ticker} ({canonical}): {args.days} days, {args.horizon}-day forward horizon")
    print(f"Range: {dates[0]:%Y-%m-%d} to {dates[-1]:%Y-%m-%d}\n")

    rows: list[tuple[str, str, float]] = []
    for d in dates:
        date_str = d.strftime("%Y-%m-%d")
        fwd_str = (d + timedelta(days=args.horizon)).strftime("%Y-%m-%d")
        c0, c1 = prices.get(date_str), prices.get(fwd_str)

        try:
            _, decision = ta.propagate(args.ticker, date_str, asset_type="crypto")
        except Exception as e:  # noqa: BLE001 — one bad day should not kill the run
            print(f"{date_str}: ERROR {e}")
            continue

        if c0 is None or c1 is None:
            print(f"{date_str}: decision={decision:<12} (no price data to score)")
            continue

        ret = (c1 - c0) / c0
        rows.append((date_str, decision, ret))
        print(f"{date_str}: decision={decision:<12} {args.horizon}d fwd return={ret:+.2%}")

    if not rows:
        print("\nNo scored days — nothing to summarize.")
        if not args.no_discord:
            notify_discord(f"Backtest {args.ticker}: no scored days ({dates[0]:%Y-%m-%d} to {dates[-1]:%Y-%m-%d}).")
        return 1

    directional = [(d, dec, ret) for d, dec, ret in rows if dec != "Hold"]
    hits = sum(1 for _, dec, ret in directional if (_RATING_SCORE[dec] > 0) == (ret > 0))
    hit_rate = hits / len(directional) if directional else None

    strategy_return = sum(_RATING_SCORE[dec] * ret for _, dec, ret in rows) / len(rows)
    buy_hold_return = sum(ret for _, _, ret in rows) / len(rows)

    print("\n" + "=" * 60)
    print(f"Days scored: {len(rows)} (directional: {len(directional)}, hold: {len(rows) - len(directional)})")
    print(
        f"Directional hit-rate: {hit_rate:.0%}" if hit_rate is not None
        else "Directional hit-rate: n/a (every day was Hold)"
    )
    print(f"Avg strategy-weighted return per decision: {strategy_return:+.2%}")
    print(f"Avg raw {args.horizon}d buy-and-hold return over same days: {buy_hold_return:+.2%}")
    print(
        "\nSample size is tiny — treat this as 'does the mechanism work', "
        "not a validated edge. Re-run with more --days for a steadier read."
    )

    if not args.no_discord:
        hit_str = f"{hit_rate:.0%}" if hit_rate is not None else "n/a"
        notify_discord(
            f"**Backtest {args.ticker}** ({dates[0]:%Y-%m-%d} to {dates[-1]:%Y-%m-%d}, "
            f"{args.horizon}d horizon)\n"
            f"Days scored: {len(rows)} (directional: {len(directional)})\n"
            f"Hit-rate: {hit_str} | Strategy return: {strategy_return:+.2%} | "
            f"Buy-and-hold: {buy_hold_return:+.2%}"
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
