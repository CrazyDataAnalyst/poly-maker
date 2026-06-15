"""
Backtest poly_strategy and report PnL / Sharpe.

Examples
--------
Synthetic (no data needed, good for sanity-checking the engine + harness):

    python run_backtest.py --mode synthetic --steps 8000 --gamma 2 --participation 0.25

Historical CSV (e.g. data from https://github.com/warproxxx/poly_data). Map your
file's columns to the canonical names; book and/or trades may be supplied:

    python run_backtest.py --mode csv \
        --trades trades.csv --trades-cols ts=t,token=asset,price=p,size=q,side=taker_side \
        --book book.csv     --book-cols ts=t,token=asset,bid=best_bid,ask=best_ask \
        --sample-interval 60 --end-ts 1718400000 --outcome YES=1

If only trades are available, the harness still runs but the book is approximated
from trade prices; supplying a book stream is strongly recommended for realism.
"""

from __future__ import annotations

import argparse
import csv as _csv
from typing import Dict, List, Optional

from poly_backtest import BacktestRunner, MakerFillModel
from poly_backtest.data_sources import csv_events, merge_sources, synthetic_market
from poly_strategy import StrategyConfig


def _kv(s: Optional[str]) -> Dict[str, str]:
    """Parse 'a=b,c=d' into a dict."""
    out: Dict[str, str] = {}
    if not s:
        return out
    for pair in s.split(","):
        if "=" in pair:
            k, v = pair.split("=", 1)
            out[k.strip()] = v.strip()
    return out


def _outcomes(s: Optional[str]) -> Dict[str, float]:
    out: Dict[str, float] = {}
    for k, v in _kv(s).items():
        out[k] = float(v)
    return out


def build_config(args) -> StrategyConfig:
    return StrategyConfig(
        gamma=args.gamma,
        kappa=args.kappa,
        max_loss_usd=args.max_loss_usd,
        base_order_size=args.trade_size,
        max_order_size=args.max_size,
        tick_size=args.tick_size,
    )


def main():
    p = argparse.ArgumentParser(description="Backtest poly_strategy")
    p.add_argument("--mode", choices=["synthetic", "csv"], default="synthetic")
    # synthetic
    p.add_argument("--steps", type=int, default=8000)
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--vol", type=float, default=0.01, help="per-step logit vol")
    p.add_argument("--spread", type=float, default=0.02)
    # csv
    p.add_argument("--trades", type=str, default=None)
    p.add_argument("--trades-cols", type=str, default=None)
    p.add_argument("--book", type=str, default=None)
    p.add_argument("--book-cols", type=str, default=None)
    p.add_argument("--token", type=str, default=None, help="override token id for single-file CSVs")
    p.add_argument("--end-ts", type=float, default=None, help="resolution epoch seconds (enables withdrawal)")
    p.add_argument("--outcome", type=str, default=None, help="terminal settlement, e.g. YES=1,NO=0")
    # strategy / sim
    p.add_argument("--gamma", type=float, default=2.0)
    p.add_argument("--kappa", type=float, default=30.0)
    p.add_argument("--max-loss-usd", type=float, default=200.0)
    p.add_argument("--trade-size", type=float, default=20.0)
    p.add_argument("--max-size", type=float, default=200.0)
    p.add_argument("--tick-size", type=float, default=0.01)
    p.add_argument("--participation", type=float, default=0.25)
    p.add_argument("--sample-interval", type=float, default=60.0)
    p.add_argument("--maker-fee", type=float, default=0.0)
    p.add_argument("--equity-out", type=str, default=None, help="write equity curve CSV")
    args = p.parse_args()

    if args.mode == "synthetic":
        events: List = list(
            synthetic_market(
                token=args.token or "YES",
                n_steps=args.steps,
                vol_logit=args.vol,
                spread=args.spread,
                seed=args.seed,
            )
        )
    else:
        streams = []
        if args.book:
            streams.append(csv_events(args.book, "book", _kv(args.book_cols), args.token))
        if args.trades:
            streams.append(csv_events(args.trades, "trades", _kv(args.trades_cols), args.token))
        if not streams:
            p.error("csv mode requires --book and/or --trades")
        events = merge_sources(*streams)

    runner = BacktestRunner(
        config=build_config(args),
        fill_model=MakerFillModel(participation=args.participation),
        sample_interval_s=args.sample_interval,
        end_ts=args.end_ts,
        maker_fee=args.maker_fee,
    )
    result = runner.run(events, outcomes=_outcomes(args.outcome) or None)

    print("\n=== Backtest result ===")
    print(result.metrics.summary())
    print(f"buys={result.ledger.num_buys} sells={result.ledger.num_sells} "
          f"fees={result.ledger.fees_paid:.2f} final_equity={result.metrics.final_equity:.2f}")

    if args.equity_out:
        with open(args.equity_out, "w", newline="") as fh:
            w = _csv.writer(fh)
            w.writerow(["sample", "equity"])
            for i, eq in enumerate(result.equity_curve):
                w.writerow([i, eq])
        print(f"equity curve -> {args.equity_out}")


if __name__ == "__main__":
    main()
