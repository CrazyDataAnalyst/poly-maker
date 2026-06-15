"""
Parameter sweep over the backtester (Phase 7 fine-tuning).

Runs BacktestRunner over a grid of StrategyConfig values on a FIXED event set and
prints a table sorted by Sharpe, so configs can be ranked reproducibly. No new
framework - it just calls the harness you already trust (poly_backtest).

Keep tuning honest: tune on one date range, validate on a held-out range, prefer
robust Sharpe over peak PnL, and change one family of parameters at a time.

Examples
--------
Synthetic:
    python sweep.py --mode synthetic --steps 8000 --grid gamma=1,2,4 kappa=15,30,60

Historical CSV (same column-map flags as run_backtest.py):
    python sweep.py --mode csv --book book.csv --trades trades.csv \
        --book-cols ts=t,token=asset,bid=best_bid,ask=best_ask \
        --grid gamma=1,2,4 reward_band_fraction=0.7,0.8,0.9
"""

from __future__ import annotations

import argparse
import itertools
from typing import Dict, List

from poly_backtest import BacktestRunner, MakerFillModel
from poly_backtest.data_sources import csv_events, merge_sources, synthetic_market
from poly_strategy import StrategyConfig


def _parse_grid(items: List[str]) -> Dict[str, list]:
    """Parse ['gamma=1,2,4', 'kappa=15,30'] into {'gamma':[1,2,4], 'kappa':[15,30]}."""
    grid: Dict[str, list] = {}
    for item in items or []:
        key, _, vals = item.partition("=")
        grid[key.strip()] = [float(v) for v in vals.split(",") if v != ""]
    return grid


def _materialize_events(args) -> list:
    """Build the fixed event list once so every config sees identical data."""
    if args.mode == "synthetic":
        return list(synthetic_market(n_steps=args.steps, seed=args.seed))
    streams = []
    if args.book:
        streams.append(csv_events(args.book, "book", _kv(args.book_cols), args.token))
    if args.trades:
        streams.append(csv_events(args.trades, "trades", _kv(args.trades_cols), args.token))
    if not streams:
        raise SystemExit("csv mode requires --book and/or --trades")
    return list(merge_sources(*streams))


def _kv(s):
    out = {}
    for pair in (s or "").split(","):
        if "=" in pair:
            k, v = pair.split("=", 1)
            out[k.strip()] = v.strip()
    return out


def main():
    p = argparse.ArgumentParser(description="Sweep poly_strategy parameters over the backtester")
    p.add_argument("--mode", choices=["synthetic", "csv"], default="synthetic")
    p.add_argument("--steps", type=int, default=8000)
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--book", default=None)
    p.add_argument("--book-cols", default=None)
    p.add_argument("--trades", default=None)
    p.add_argument("--trades-cols", default=None)
    p.add_argument("--token", default=None)
    p.add_argument("--participation", type=float, default=0.25)
    p.add_argument("--sample-interval", type=float, default=60.0)
    p.add_argument("--grid", nargs="+", required=True,
                   help="e.g. gamma=1,2,4 kappa=15,30,60 reward_band_fraction=0.7,0.8,0.9")
    args = p.parse_args()

    grid = _parse_grid(args.grid)
    keys = list(grid.keys())
    events = _materialize_events(args)
    print(f"Loaded {len(events)} events; sweeping {keys} "
          f"({len(list(itertools.product(*grid.values())))} combos)\n")

    rows = []
    for combo in itertools.product(*[grid[k] for k in keys]):
        overrides = dict(zip(keys, combo))
        cfg = StrategyConfig(**overrides)
        runner = BacktestRunner(
            config=cfg,
            fill_model=MakerFillModel(participation=args.participation),
            sample_interval_s=args.sample_interval,
        )
        res = runner.run(list(events))
        m = res.metrics
        rows.append((overrides, m.sharpe_annualized, m.total_pnl, m.max_drawdown, m.num_fills))

    rows.sort(key=lambda r: r[1], reverse=True)  # rank by annualized Sharpe

    header = "  ".join(f"{k:>10}" for k in keys) + "   |  Sharpe     PnL    MaxDD  fills"
    print(header)
    print("-" * len(header))
    for overrides, sharpe, pnl, dd, fills in rows:
        params = "  ".join(f"{overrides[k]:>10.3g}" for k in keys)
        print(f"{params}   | {sharpe:7.2f} {pnl:8.2f} {dd:8.2f} {fills:6d}")

    best = rows[0]
    print(f"\nBest by Sharpe: {best[0]}  Sharpe={best[1]:.2f}  PnL={best[2]:.2f}")


if __name__ == "__main__":
    main()
