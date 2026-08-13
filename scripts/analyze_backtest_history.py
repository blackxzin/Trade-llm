"""Summarize trend across successive backtest_btc.py runs.

Reads the JSONL history file backtest_btc.py appends to on every run
(default: <results_dir>/backtest_history.jsonl, see --history-file there)
and reports, per forward horizon, whether hit-rate and strategy-weighted
return are improving, declining, or flat across runs.

Usage:
    python scripts/analyze_backtest_history.py
    python scripts/analyze_backtest_history.py --ticker BTC-USD --last 10
"""

from __future__ import annotations

import argparse
import json
import statistics
from pathlib import Path

from tradingagents.default_config import DEFAULT_CONFIG

# Minimum runs per half needed to call a trend rather than "not enough data".
_MIN_RUNS_PER_HALF = 2
# Strategy-return delta (older-half avg -> newer-half avg) below this is "flat".
_FLAT_THRESHOLD = 0.005


def _load_runs(path: Path, ticker: str | None) -> list[dict]:
    if not path.exists():
        return []
    runs = []
    for i, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        line = line.strip()
        if not line:
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError as e:
            print(f"Skipping malformed line {i}: {e}")
            continue
        if ticker and record.get("ticker") != ticker:
            continue
        runs.append(record)
    return runs


def _trend_label(older_avg: float, newer_avg: float) -> str:
    delta = newer_avg - older_avg
    if abs(delta) < _FLAT_THRESHOLD:
        return "flat"
    return "improving" if delta > 0 else "declining"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--ticker", default=None, help="only include runs for this ticker")
    parser.add_argument("--last", type=int, default=None, help="only consider the N most recent runs")
    parser.add_argument(
        "--history-file", default=None,
        help="JSONL file to read (default: <results_dir>/backtest_history.jsonl)",
    )
    args = parser.parse_args()

    history_path = (
        Path(args.history_file) if args.history_file
        else Path(DEFAULT_CONFIG["results_dir"]) / "backtest_history.jsonl"
    )
    runs = _load_runs(history_path, args.ticker)
    if not runs:
        print(f"No backtest history found at {history_path}" + (f" for ticker {args.ticker}" if args.ticker else "."))
        return 1

    runs.sort(key=lambda r: r.get("timestamp", ""))
    if args.last:
        runs = runs[-args.last:]

    print(f"{len(runs)} run(s) from {history_path}\n")

    # Union of horizons seen across all loaded runs, in ascending order.
    horizons = sorted({int(h) for r in runs for h in r.get("horizons", {})})
    if not horizons:
        print("Runs have no per-horizon data to summarize.")
        return 1

    for h in horizons:
        key = str(h)
        series = [
            (r["timestamp"], r["horizons"][key])
            for r in runs
            if key in r.get("horizons", {}) and r["horizons"][key] is not None
        ]
        print("=" * 60)
        print(f"{h}d horizon — {len(series)} scored run(s)")
        for ts, s in series:
            hit_str = f"{s['hit_rate']:.0%}" if s["hit_rate"] is not None else "n/a"
            print(f"  {ts}  hit-rate={hit_str:>5}  strategy={s['strategy_return']:+.2%}  buy&hold={s['buy_hold_return']:+.2%}")

        if len(series) < _MIN_RUNS_PER_HALF * 2:
            print(f"  Not enough runs for a trend (need >= {_MIN_RUNS_PER_HALF * 2}, have {len(series)}).\n")
            continue

        mid = len(series) // 2
        older, newer = series[:mid], series[mid:]
        older_hit = [s["hit_rate"] for _, s in older if s["hit_rate"] is not None]
        newer_hit = [s["hit_rate"] for _, s in newer if s["hit_rate"] is not None]
        older_ret_avg = statistics.mean(s["strategy_return"] for _, s in older)
        newer_ret_avg = statistics.mean(s["strategy_return"] for _, s in newer)

        label = _trend_label(older_ret_avg, newer_ret_avg)
        print(f"  Strategy return: {older_ret_avg:+.2%} (older half) -> {newer_ret_avg:+.2%} (newer half) — {label}")
        if older_hit and newer_hit:
            print(f"  Hit-rate:        {statistics.mean(older_hit):.0%} (older half) -> {statistics.mean(newer_hit):.0%} (newer half)")
        print()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
