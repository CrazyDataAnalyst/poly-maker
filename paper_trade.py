"""
Forward-test (paper trade) poly_strategy on LIVE data - read-only, no orders.

Connects to Polymarket's public market websocket (no API credentials needed),
runs the *same* Quoter the live bot uses, and simulates fills with the *same*
backtest fill model, accumulating PnL in the *same* ledger. Because the decision
and simulation code are shared with run_backtest.py, forward-test results are
directly comparable to backtest results - the only difference is the data source.

It NEVER places real orders. Use it to validate the engine on live flow before
risking capital.

Usage:
    python paper_trade.py --tokens <token_id_1>,<token_id_2> --report-interval 60
    # or, if a configured Selected Markets sheet is reachable (read-only):
    python paper_trade.py --from-sheet

Trades are inferred from top-of-book consumption (same proxy the VPIN feed uses),
since the public market channel does not emit trade prints.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import time
import traceback
from typing import Dict, List, Optional

import websockets

from poly_backtest import BacktestRunner, MakerFillModel
from poly_backtest.events import BookUpdate, Trade
from poly_strategy import StrategyConfig

WS_URI = "wss://ws-subscriptions-clob.polymarket.com/ws/market"


def _tokens_from_sheet() -> List[str]:
    """Best-effort read of Selected Markets token ids (read-only mode)."""
    from poly_data.utils import get_sheet_df
    df, _ = get_sheet_df(read_only=True)
    tokens: List[str] = []
    for _, row in df.iterrows():
        for col in ("token1", "token2"):
            if col in row and str(row[col]):
                tokens.append(str(row[col]))
    return tokens


class PaperTrader:
    """Drives the BacktestRunner from live websocket book updates."""

    def __init__(self, tokens: List[str], config: StrategyConfig, participation: float,
                 sample_interval: float, report_interval: float):
        self.tokens = tokens
        self.runner = BacktestRunner(
            config=config,
            fill_model=MakerFillModel(participation=participation),
            sample_interval_s=sample_interval,
        )
        self.report_interval = report_interval
        self._last_report = time.time()
        # Track previous best sizes per token to infer consumed (traded) volume.
        self._prev_best: Dict[str, dict] = {}

    def _infer_trades(self, token: str, best_bid, best_ask, bid_size, ask_size, ts):
        """Emit synthetic Trade events from top-of-book size reductions."""
        prev = self._prev_best.get(token)
        trades = []
        if prev is not None:
            if best_bid is not None and prev.get("bid") == best_bid and bid_size is not None:
                consumed = prev.get("bid_size", 0.0) - bid_size
                if consumed > 0:
                    trades.append(Trade(ts, token, best_bid, consumed, "sell"))
            if best_ask is not None and prev.get("ask") == best_ask and ask_size is not None:
                consumed = prev.get("ask_size", 0.0) - ask_size
                if consumed > 0:
                    trades.append(Trade(ts, token, best_ask, consumed, "buy"))
        self._prev_best[token] = {"bid": best_bid, "ask": best_ask,
                                  "bid_size": bid_size, "ask_size": ask_size}
        return trades

    def _handle(self, msg):
        if not isinstance(msg, list):
            msg = [msg]
        ts = time.time()
        for j in msg:
            if j.get("event_type") not in ("book", "price_change"):
                continue
            token = str(j.get("asset_id"))
            if token not in self.tokens:
                continue
            bids = j.get("bids") or []
            asks = j.get("asks") or []
            # For price_change events we only get deltas; rebuild best from book msgs.
            best_bid = max((float(b["price"]) for b in bids), default=None) if bids else None
            best_ask = min((float(a["price"]) for a in asks), default=None) if asks else None
            bid_size = next((float(b["size"]) for b in bids if float(b["price"]) == best_bid), None) if best_bid else None
            ask_size = next((float(a["size"]) for a in asks if float(a["price"]) == best_ask), None) if best_ask else None
            if best_bid is None or best_ask is None:
                continue
            for tr in self._infer_trades(token, best_bid, best_ask, bid_size, ask_size, ts):
                self.runner._on_trade(tr)
            self.runner._on_book(BookUpdate(ts, token, best_bid, best_ask, bid_size, ask_size))

        if time.time() - self._last_report >= self.report_interval:
            self._report()
            self._last_report = time.time()

    def _report(self):
        eq = self.runner.ledger.equity(self.runner._mids)
        led = self.runner.ledger
        print(f"[paper] {time.strftime('%H:%M:%S')} equity={eq:.2f} "
              f"fills={self.runner.num_fills} buys={led.num_buys} sells={led.num_sells} "
              f"positions={ {k: round(v, 1) for k, v in led.positions.items() if v} }")

    async def run(self):
        while True:
            try:
                async with websockets.connect(WS_URI, ping_interval=5, ping_timeout=None) as ws:
                    await ws.send(json.dumps({"assets_ids": self.tokens}))
                    print(f"[paper] subscribed to {len(self.tokens)} tokens (read-only, NO orders)")
                    while True:
                        self._handle(json.loads(await ws.recv()))
            except Exception as e:
                print(f"[paper] websocket error: {e}")
                traceback.print_exc()
                await asyncio.sleep(5)


def main():
    p = argparse.ArgumentParser(description="Forward-test poly_strategy on live data (no orders)")
    p.add_argument("--tokens", type=str, default=None, help="comma-separated token ids")
    p.add_argument("--from-sheet", action="store_true", help="load tokens from Selected Markets")
    p.add_argument("--gamma", type=float, default=2.0)
    p.add_argument("--kappa", type=float, default=30.0)
    p.add_argument("--trade-size", type=float, default=20.0)
    p.add_argument("--max-size", type=float, default=200.0)
    p.add_argument("--participation", type=float, default=0.25)
    p.add_argument("--sample-interval", type=float, default=60.0)
    p.add_argument("--report-interval", type=float, default=30.0)
    args = p.parse_args()

    if args.from_sheet:
        tokens = _tokens_from_sheet()
    elif args.tokens:
        tokens = [t.strip() for t in args.tokens.split(",") if t.strip()]
    else:
        p.error("provide --tokens or --from-sheet")

    if not tokens:
        p.error("no tokens to subscribe to")

    cfg = StrategyConfig(gamma=args.gamma, kappa=args.kappa,
                         base_order_size=args.trade_size, max_order_size=args.max_size)
    trader = PaperTrader(tokens, cfg, args.participation, args.sample_interval, args.report_interval)
    asyncio.run(trader.run())


if __name__ == "__main__":
    main()
