"""
Backtest poly_strategy on REAL Polymarket data via Nautilus Trader.

Loads historical Polymarket data with ``PolymarketDataLoader``, feeds it through a
``BacktestEngine`` configured with the Polymarket venue + fee model, and runs the
shared ``PolymakerNautilusStrategy``. Nautilus computes venue-accurate fills, fees
(incl. maker rebates), PnL, returns and Sharpe.

Run (after `uv pip install "nautilus_trader[polymarket]"`):

    python -m poly_nautilus.backtest --market-slug gta-vi-released-before-june-2026 \
        --start 2026-01-01 --end 2026-02-01 --gamma 2 --trade-size 20

API targets docs/integrations/polymarket.md. Some loader method names
(load_quotes / load_deltas) vary by version; this script probes what is available
and reports what it loaded. See NAUTILUS.md for caveats.
"""

from __future__ import annotations

import argparse
import asyncio
from typing import List

import pandas as pd

from nautilus_trader.adapters.polymarket import (  # type: ignore
    POLYMARKET_VENUE,
    PolymarketDataLoader,
)
from nautilus_trader.adapters.polymarket.fee_model import PolymarketFeeModel  # type: ignore
from nautilus_trader.backtest.engine import BacktestEngine, BacktestEngineConfig
from nautilus_trader.model.currencies import USDC
from nautilus_trader.model.enums import AccountType, BookType, OmsType
from nautilus_trader.model.objects import Money

from poly_nautilus.strategy import PolymakerNautilusConfig, PolymakerNautilusStrategy


async def _load_data(loader, start, end) -> List:
    """Probe the loader for whatever market data it can provide, newest API first."""
    data: List = []
    for method, kwargs in (
        ("load_deltas", {"start": start, "end": end}),
        ("load_quotes", {"start": start, "end": end}),
        ("load_trades", {"start": start, "end": end}),
    ):
        fn = getattr(loader, method, None)
        if fn is None:
            continue
        try:
            loaded = await fn(**kwargs)
            if loaded:
                data.extend(loaded)
                print(f"  loaded {len(loaded)} records via {method}")
        except Exception as e:  # noqa
            print(f"  {method} unavailable/failed: {e}")
    return data


async def run(args) -> None:
    print(f"Loading Polymarket market '{args.market_slug}' ...")
    loader = await PolymarketDataLoader.from_market_slug(
        args.market_slug, sanitize_info=True  # redact winner/closed -> no look-ahead
    )

    start = pd.Timestamp(args.start, tz="UTC") if args.start else None
    end = pd.Timestamp(args.end, tz="UTC") if args.end else None
    data = await _load_data(loader, start, end)
    if not data:
        raise SystemExit("No data loaded - provide a market with available history.")

    # A binary market exposes two outcome tokens; quote the primary, pass the
    # other (if the loader exposes it) for arbitrage detection.
    instruments = getattr(loader, "instruments", None) or [loader.instrument]
    primary = instruments[0]
    other_id = instruments[1].id if len(instruments) > 1 else None

    engine = BacktestEngine(config=BacktestEngineConfig(trader_id="POLYMAKER-BT-001"))
    engine.add_venue(
        venue=POLYMARKET_VENUE,
        oms_type=OmsType.NETTING,
        account_type=AccountType.CASH,
        base_currency=USDC,
        starting_balances=[Money(args.balance, USDC)],
        book_type=BookType.L2_MBP,
        fee_model=PolymarketFeeModel(maker_rebates_enabled=True),
    )
    for inst in instruments:
        engine.add_instrument(inst)
    engine.add_data(data)

    strategy = PolymakerNautilusStrategy(
        config=PolymakerNautilusConfig(
            instrument_id=primary.id,
            other_instrument_id=other_id,
            gamma=args.gamma,
            kappa=args.kappa,
            trade_size=args.trade_size,
            max_size=args.max_size,
            max_loss_usd=args.max_loss_usd,
        )
    )
    engine.add_strategy(strategy)

    engine.run()

    # Reports (Nautilus computes Sharpe/returns in the portfolio analyzer).
    print("\n=== Account ===")
    print(engine.trader.generate_account_report(POLYMARKET_VENUE))
    print("\n=== Fills ===")
    print(engine.trader.generate_order_fills_report())
    print("\n=== Positions ===")
    print(engine.trader.generate_positions_report())
    try:
        result = engine.get_result()
        print("\n=== Stats ===")
        print(result)
    except Exception:
        pass
    engine.dispose()


def main():
    p = argparse.ArgumentParser(description="Backtest poly_strategy on real Polymarket data")
    p.add_argument("--market-slug", required=True)
    p.add_argument("--start", default=None, help="UTC date e.g. 2026-01-01")
    p.add_argument("--end", default=None)
    p.add_argument("--balance", type=float, default=1000.0)
    p.add_argument("--gamma", type=float, default=2.0)
    p.add_argument("--kappa", type=float, default=30.0)
    p.add_argument("--trade-size", type=float, default=20.0)
    p.add_argument("--max-size", type=float, default=200.0)
    p.add_argument("--max-loss-usd", type=float, default=200.0)
    args = p.parse_args()
    asyncio.run(run(args))


if __name__ == "__main__":
    main()
