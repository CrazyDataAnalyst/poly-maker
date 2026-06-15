"""
Nautilus Trader strategy wrapping the poly_strategy quoting engine.

Why Nautilus: it runs the *same* Strategy object in backtest and live, on real
Polymarket order-book data through its first-class Polymarket adapter. Because
``poly_strategy.Quoter`` is a pure decision function, this class is a thin
translation layer:

    Nautilus book / trade events  ->  MarketSnapshot  ->  Quoter.compute()
                                   ->  QuoteDecision   ->  post-only LIMIT orders

The same ``PolymakerNautilusStrategy`` is used by both ``backtest.py`` (historical
replay via PolymarketDataLoader + BacktestEngine) and ``live.py`` (TradingNode
with the live Polymarket data/exec clients) - guaranteeing zero backtest-vs-live
strategy skew.

NOTE: targets the nautilus_trader Polymarket adapter API as documented in
docs/integrations/polymarket.md. nautilus_trader is an optional dependency
(`uv pip install "nautilus_trader[polymarket]"`); import this module only in an
environment where it is installed. See NAUTILUS.md.
"""

from __future__ import annotations

from typing import Optional

from nautilus_trader.config import StrategyConfig
from nautilus_trader.model.book import OrderBook
from nautilus_trader.model.data import OrderBookDeltas, QuoteTick, TradeTick
from nautilus_trader.model.enums import AggressorSide, OrderSide, TimeInForce
from nautilus_trader.model.identifiers import InstrumentId
from nautilus_trader.trading.strategy import Strategy

from poly_strategy import MarketSnapshot, Quoter, StrategyConfig as EngineConfig


class PolymakerNautilusConfig(StrategyConfig, frozen=True):
    """Configuration for the Nautilus market-making strategy.

    ``instrument_id`` is the outcome token to quote. ``other_instrument_id`` is the
    opposite outcome of the same binary market; when supplied, its book feeds the
    Dutch-book arbitrage detector. Remaining fields mirror poly_strategy's
    StrategyConfig and are assembled into an EngineConfig in on_start.
    """

    instrument_id: InstrumentId
    other_instrument_id: Optional[InstrumentId] = None

    # Engine knobs (defaults match poly_strategy.StrategyConfig).
    gamma: float = 2.0
    kappa: float = 30.0
    horizon_hours: float = 24.0
    max_loss_usd: float = 200.0
    trade_size: float = 20.0
    max_size: float = 200.0
    min_half_spread: float = 0.01
    max_half_spread: float = 0.15
    inventory_skew_cap: float = 0.08
    kelly_fraction: float = 0.30
    reward_max_spread: float = 3.0
    reward_band_fraction: float = 0.8
    resolution_widen_hours: float = 6.0
    resolution_withdraw_hours: float = 1.0
    min_price: float = 0.05
    max_price: float = 0.95

    # Execution behaviour.
    requote_interval_ms: int = 1000   # min ms between requotes (rate-limit friendly)
    use_trade_ticks: bool = True      # feed real trade prints into VPIN


class PolymakerNautilusStrategy(Strategy):
    def __init__(self, config: PolymakerNautilusConfig) -> None:
        super().__init__(config)
        self.quoter: Optional[Quoter] = None
        self._engine_cfg: Optional[EngineConfig] = None
        self.instrument = None
        self._tick_size: float = 0.01
        self._token: str = str(config.instrument_id)
        self._last_requote_ns: int = 0

    # ------------------------------------------------------------------ lifecycle
    def on_start(self) -> None:
        self.instrument = self.cache.instrument(self.config.instrument_id)
        if self.instrument is None:
            self.log.error(f"Instrument {self.config.instrument_id} not found in cache")
            self.stop()
            return

        self._tick_size = float(self.instrument.price_increment)

        self._engine_cfg = EngineConfig(
            gamma=self.config.gamma,
            kappa=self.config.kappa,
            horizon_hours=self.config.horizon_hours,
            max_loss_usd=self.config.max_loss_usd,
            base_order_size=self.config.trade_size,
            max_order_size=self.config.max_size,
            min_half_spread=self.config.min_half_spread,
            max_half_spread=self.config.max_half_spread,
            inventory_skew_cap=self.config.inventory_skew_cap,
            kelly_fraction=self.config.kelly_fraction,
            reward_max_spread=self.config.reward_max_spread,
            reward_band_fraction=self.config.reward_band_fraction,
            resolution_widen_hours=self.config.resolution_widen_hours,
            resolution_withdraw_hours=self.config.resolution_withdraw_hours,
            min_price=self.config.min_price,
            max_price=self.config.max_price,
            tick_size=self._tick_size,
        )
        self.quoter = Quoter(self._engine_cfg)

        self.subscribe_order_book_deltas(self.config.instrument_id)
        if self.config.use_trade_ticks:
            self.subscribe_trade_ticks(self.config.instrument_id)
        if self.config.other_instrument_id is not None:
            self.subscribe_order_book_deltas(self.config.other_instrument_id)

        self.log.info(f"Polymaker strategy started on {self.config.instrument_id}")

    def on_stop(self) -> None:
        self.cancel_all_orders(self.config.instrument_id)

    # ------------------------------------------------------------------ data in
    def on_order_book_deltas(self, deltas: OrderBookDeltas) -> None:
        if deltas.instrument_id == self.config.instrument_id:
            self._maybe_requote()

    def on_order_book(self, order_book: OrderBook) -> None:
        if order_book.instrument_id == self.config.instrument_id:
            self._maybe_requote()

    def on_trade_tick(self, tick: TradeTick) -> None:
        # Feed real trade prints into the VPIN toxicity estimator with the true
        # aggressor side - sharper than the order-flow proxy used elsewhere.
        if self.quoter is None or tick.instrument_id != self.config.instrument_id:
            return
        vpin = self.quoter.state_for(self._token).vpin
        size = float(tick.size)
        if tick.aggressor_side == AggressorSide.BUYER:
            vpin.add_signed_volume(size, 0.0)
        elif tick.aggressor_side == AggressorSide.SELLER:
            vpin.add_signed_volume(0.0, size)
        else:
            vpin.add_trade(float(tick.price), size)

    # ------------------------------------------------------------------ quoting
    def _maybe_requote(self) -> None:
        now = self.clock.timestamp_ns()
        if now - self._last_requote_ns < self.config.requote_interval_ms * 1_000_000:
            return
        self._last_requote_ns = now
        self._requote()

    @staticmethod
    def _best(book: Optional[OrderBook]):
        """Return (best_bid, best_ask, bid_size, ask_size) as floats or Nones."""
        if book is None:
            return None, None, None, None

        def _f(v):
            return float(v) if v is not None else None

        return (
            _f(book.best_bid_price()),
            _f(book.best_ask_price()),
            _f(book.best_bid_size()),
            _f(book.best_ask_size()),
        )

    def _hours_to_resolution(self) -> Optional[float]:
        info = getattr(self.instrument, "info", None) or {}
        end = info.get("end_date_iso") or info.get("end_date")
        if not end:
            return None
        try:
            from datetime import datetime, timezone
            end_dt = datetime.fromisoformat(str(end).replace("Z", "+00:00"))
            now = datetime.now(timezone.utc)
            return max((end_dt - now).total_seconds() / 3600.0, 0.0)
        except Exception:
            return None

    def _requote(self) -> None:
        if self.quoter is None:
            return
        book = self.cache.order_book(self.config.instrument_id)
        best_bid, best_ask, bid_size, ask_size = self._best(book)
        if best_bid is None or best_ask is None:
            return

        other_ask = other_bid = None
        if self.config.other_instrument_id is not None:
            other_book = self.cache.order_book(self.config.other_instrument_id)
            ob, oa, _, _ = (None, None, None, None)
            if other_book is not None:
                ob = float(other_book.best_bid_price()) if other_book.best_bid_price() else None
                oa = float(other_book.best_ask_price()) if other_book.best_ask_price() else None
            other_bid, other_ask = ob, oa

        position = float(self.portfolio.net_position(self.config.instrument_id) or 0.0)

        snap = MarketSnapshot(
            token=self._token,
            best_bid=best_bid,
            best_ask=best_ask,
            bid_size=bid_size,
            ask_size=ask_size,
            position=position,
            avg_price=self._avg_px(),
            book_age_s=0.0,
            hours_to_resolution=self._hours_to_resolution(),
            sheet_annual_vol=0.0,
            seconds_per_update=1.0,
            other_best_ask=other_ask,
            other_best_bid=other_bid,
        )
        decision = self.quoter.compute(snap, self._engine_cfg)

        if decision.arb is not None:
            self.log.info(f"ARBITRAGE: {decision.arb.note}")

        if not decision.quote_bid and not decision.quote_ask:
            self.cancel_all_orders(self.config.instrument_id)
            return

        self._reconcile(
            OrderSide.BUY,
            decision.bid_price if decision.quote_bid else None,
            decision.bid_size if decision.quote_bid else 0.0,
        )
        self._reconcile(
            OrderSide.SELL,
            decision.ask_price if decision.quote_ask else None,
            decision.ask_size if decision.quote_ask else 0.0,
        )

    def _avg_px(self) -> float:
        pos = self.cache.position_for_instrument(self.config.instrument_id) \
            if hasattr(self.cache, "position_for_instrument") else None
        if pos is not None:
            try:
                return float(pos.avg_px_open)
            except Exception:
                return 0.0
        return 0.0

    def _reconcile(self, side: OrderSide, price: Optional[float], size: float) -> None:
        """Cancel/replace this side's working order to match the target quote.

        Requoting cancels and re-posts (back of the FIFO queue) only when price
        drifts more than a tick or size by more than 10%, to respect rate limits.
        """
        working = [
            o for o in self.cache.orders_open(instrument_id=self.config.instrument_id)
            if o.side == side
        ]

        want = price is not None and size > 0
        if not want:
            for o in working:
                self.cancel_order(o)
            return

        if working:
            cur = working[0]
            cur_px = float(cur.price)
            cur_sz = float(cur.quantity)
            changed = abs(cur_px - price) > (self._tick_size + 1e-9) or abs(cur_sz - size) > size * 0.10
            if not changed:
                return
            for o in working:
                self.cancel_order(o)

        order = self.order_factory.limit(
            instrument_id=self.config.instrument_id,
            order_side=side,
            quantity=self.instrument.make_qty(size),
            price=self.instrument.make_price(price),
            time_in_force=TimeInForce.GTC,
            post_only=True,  # maker-only: never pay taker fees (MVP requirement)
        )
        self.submit_order(order)
