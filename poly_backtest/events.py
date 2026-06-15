"""
Normalized market events.

Every data source - synthetic, historical CSV, or live websocket - is converted
into this small set of events. The runner consumes a time-ordered stream of them.
Keeping the event vocabulary tiny is what lets one runner serve both backtest and
forward-test.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass
class BookUpdate:
    """Top-of-book snapshot for one outcome token at time ``ts`` (epoch seconds)."""
    ts: float
    token: str
    best_bid: Optional[float]
    best_ask: Optional[float]
    bid_size: Optional[float] = None
    ask_size: Optional[float] = None

    @property
    def mid(self) -> Optional[float]:
        if self.best_bid is None or self.best_ask is None:
            return None
        return (self.best_bid + self.best_ask) / 2.0


@dataclass
class Trade:
    """A market trade print on one token.

    ``side`` is the *aggressor* side: 'buy' = a taker lifted the ask (hits resting
    asks), 'sell' = a taker hit the bid (hits resting bids). If unknown, leave as
    None and the fill model / source will infer it from price relative to the book.
    """
    ts: float
    token: str
    price: float
    size: float
    side: Optional[str] = None  # 'buy' | 'sell' | None
