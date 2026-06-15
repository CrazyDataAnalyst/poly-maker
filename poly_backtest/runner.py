"""
BacktestRunner - drives poly_strategy.Quoter over a stream of market events.

This is the bridge that guarantees backtest/live parity: it builds the exact same
``MarketSnapshot`` the production adapter builds and calls the exact same
``Quoter.compute``. Backtest and forward-test differ only in where the event
stream comes from.

Flow per event:
  * BookUpdate -> update local book, recompute the quote, refresh resting orders,
    and (on the sampling clock) record a mark-to-market equity point.
  * Trade -> run the fill model against our resting quotes, book any fills in the
    ledger, and deplete the filled resting size until the next requote.

At the end it optionally applies binary settlement and computes metrics.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Optional

from poly_backtest.events import BookUpdate, Trade
from poly_backtest.fill_model import MakerFillModel
from poly_backtest.ledger import Ledger
from poly_backtest.metrics import Metrics, compute_metrics
from poly_strategy import MarketSnapshot, Quoter, StrategyConfig


@dataclass
class BacktestResult:
    metrics: Metrics
    equity_curve: List[float]
    ledger: Ledger
    num_fills: int


class BacktestRunner:
    def __init__(
        self,
        config: Optional[StrategyConfig] = None,
        fill_model: Optional[MakerFillModel] = None,
        sample_interval_s: float = 60.0,
        seconds_per_update: float = 2.0,
        end_ts: Optional[float] = None,
        maker_fee: float = 0.0,
        quoter: Optional[Quoter] = None,
    ):
        self.config = config or StrategyConfig()
        self.quoter = quoter or Quoter(self.config)
        self.fill_model = fill_model or MakerFillModel()
        self.sample_interval_s = sample_interval_s
        self.seconds_per_update = seconds_per_update
        self.end_ts = end_ts

        self.ledger = Ledger(maker_fee=maker_fee)
        # token -> (best_bid, best_ask, bid_size, ask_size)
        self._books: Dict[str, tuple] = {}
        # token -> {'bid': [price, size] | None, 'ask': [price, size] | None}
        self._resting: Dict[str, dict] = {}
        self._mids: Dict[str, float] = {}

        self.equity_curve: List[float] = []
        self._last_sample_ts: Optional[float] = None
        self.num_fills = 0

    # ------------------------------------------------------------------ helpers
    def _hours_to_resolution(self, ts: float) -> Optional[float]:
        if self.end_ts is None:
            return None
        return max((self.end_ts - ts) / 3600.0, 0.0)

    def _maybe_sample(self, ts: float) -> None:
        if self._last_sample_ts is None:
            self._last_sample_ts = ts
            self.equity_curve.append(self.ledger.equity(self._mids))
            return
        # Emit one sample per elapsed interval (carrying flat equity through gaps).
        while ts - self._last_sample_ts >= self.sample_interval_s:
            self._last_sample_ts += self.sample_interval_s
            self.equity_curve.append(self.ledger.equity(self._mids))

    def _other_token_prices(self, token: str):
        """Best ask/bid of the *other* token currently booked (for arb detection)."""
        for other, book in self._books.items():
            if other != token:
                return book[1], book[0]  # (best_ask, best_bid)
        return None, None

    # ------------------------------------------------------------------ events
    def _on_book(self, ev: BookUpdate) -> None:
        self._books[ev.token] = (ev.best_bid, ev.best_ask, ev.bid_size, ev.ask_size)
        if ev.mid is not None:
            self._mids[ev.token] = ev.mid

        other_ask, other_bid = self._other_token_prices(ev.token)
        snap = MarketSnapshot(
            token=ev.token,
            best_bid=ev.best_bid,
            best_ask=ev.best_ask,
            bid_size=ev.bid_size,
            ask_size=ev.ask_size,
            position=self.ledger.position(ev.token),
            avg_price=self.ledger.avg_price(ev.token),
            book_age_s=0.0,
            hours_to_resolution=self._hours_to_resolution(ev.ts),
            sheet_annual_vol=0.0,
            seconds_per_update=self.seconds_per_update,
            other_best_ask=other_ask,
            other_best_bid=other_bid,
        )
        decision = self.quoter.compute(snap, self.config)

        self._resting[ev.token] = {
            "bid": [decision.bid_price, decision.bid_size] if decision.quote_bid else None,
            "ask": [decision.ask_price, decision.ask_size] if decision.quote_ask else None,
        }

        self._maybe_sample(ev.ts)

    def _on_trade(self, ev: Trade) -> None:
        rest = self._resting.get(ev.token)
        book = self._books.get(ev.token)
        if not rest or not book:
            return
        best_bid, best_ask = book[0], book[1]
        resting_bid = tuple(rest["bid"]) if rest["bid"] else None
        resting_ask = tuple(rest["ask"]) if rest["ask"] else None

        fills = self.fill_model.fills_for_trade(
            ev, resting_bid, resting_ask, best_bid, best_ask
        )
        for f in fills:
            self.ledger.on_fill(f.token, f.side, f.size, f.price)
            self.num_fills += 1
            # Deplete the filled resting size so one trade can't refill it forever.
            key = "bid" if f.side == "buy" else "ask"
            if rest.get(key):
                rest[key][1] -= f.size
                if rest[key][1] <= 1e-9:
                    rest[key] = None

    # ------------------------------------------------------------------ run
    def run(self, events: Iterable, outcomes: Optional[Dict[str, float]] = None) -> BacktestResult:
        """Replay ``events`` (time-ordered) and return the result.

        ``outcomes`` (token -> 0/1) applies terminal settlement at the end.
        """
        for ev in events:
            if isinstance(ev, BookUpdate):
                self._on_book(ev)
            elif isinstance(ev, Trade):
                self._on_trade(ev)

        if outcomes:
            self.ledger.settle(outcomes)
        # Final mark.
        self.equity_curve.append(self.ledger.equity(self._mids))

        turnover = self.ledger.buy_volume + self.ledger.sell_volume
        metrics = compute_metrics(
            self.equity_curve,
            self.sample_interval_s,
            self.num_fills,
            self.ledger.num_buys,
            self.ledger.num_sells,
            turnover,
            capital_base=max(self.config.max_loss_usd, 0.0),
        )
        return BacktestResult(metrics, self.equity_curve, self.ledger, self.num_fills)
