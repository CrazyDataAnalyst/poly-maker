"""
Conservative maker fill model.

A resting limit order is a free option granted to the rest of the market; the
question a backtest must answer honestly is "would this quote *actually* have been
filled, and at what adverse cost?". This model is deliberately pessimistic:

  * **Crossing required.** Our bid only fills when a *sell* aggressor trades at a
    price <= our bid (it reached us). Our ask fills on a *buy* aggressor at a
    price >= our ask. A trade that merely touches the opposite side never fills us.

  * **Partial participation.** Because Polymarket matching is FIFO and we are
    rarely first in queue, we capture only ``participation`` (default 0.25) of the
    crossing trade's volume, capped by our own resting size. Setting this to 1.0
    gives an optimistic upper bound; lower it for a safety margin.

  * **No market impact.** Our quotes do not move the simulated book - a standard
    backtest limitation. It biases results *optimistically* (in reality, posting
    size can scare flow away), so treat reported edge as a ceiling.

Adverse selection is not modeled here; it emerges naturally in the ledger, which
marks inventory at the *subsequent* mid after each fill.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional, Tuple

from poly_backtest.events import Trade


@dataclass
class Fill:
    token: str
    side: str        # 'buy' (we bought) | 'sell' (we sold)
    price: float
    size: float
    ts: float


class MakerFillModel:
    def __init__(self, participation: float = 0.25, require_strict_cross: bool = False):
        # participation in (0, 1]; require_strict_cross uses < / > instead of <= / >=.
        self.participation = max(min(participation, 1.0), 1e-6)
        self.strict = require_strict_cross

    def _infer_side(self, trade: Trade, best_bid: Optional[float], best_ask: Optional[float]) -> Optional[str]:
        """Infer aggressor side from trade price vs. the prevailing book."""
        if trade.side in ("buy", "sell"):
            return trade.side
        if best_bid is None or best_ask is None:
            return None
        mid = (best_bid + best_ask) / 2.0
        return "buy" if trade.price >= mid else "sell"

    def fills_for_trade(
        self,
        trade: Trade,
        resting_bid: Optional[Tuple[float, float]],   # (price, size) or None
        resting_ask: Optional[Tuple[float, float]],
        best_bid: Optional[float] = None,
        best_ask: Optional[float] = None,
    ) -> List[Fill]:
        """Return the fills our resting quotes receive from one incoming trade."""
        side = self._infer_side(trade, best_bid, best_ask)
        if side is None:
            return []

        out: List[Fill] = []
        capturable = trade.size * self.participation

        if side == "sell" and resting_bid is not None:
            bid_px, bid_sz = resting_bid
            crosses = (trade.price < bid_px) if self.strict else (trade.price <= bid_px)
            if crosses and bid_sz > 0:
                fill_sz = min(bid_sz, capturable)
                if fill_sz > 0:
                    # We buy at our posted bid price (price improvement vs. trade px
                    # is not assumed; we conservatively fill at our own quote).
                    out.append(Fill(trade.token, "buy", bid_px, fill_sz, trade.ts))

        if side == "buy" and resting_ask is not None:
            ask_px, ask_sz = resting_ask
            crosses = (trade.price > ask_px) if self.strict else (trade.price >= ask_px)
            if crosses and ask_sz > 0:
                fill_sz = min(ask_sz, capturable)
                if fill_sz > 0:
                    out.append(Fill(trade.token, "sell", ask_px, fill_sz, trade.ts))

        return out
