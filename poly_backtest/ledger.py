"""
Cash / inventory / PnL accounting.

Tracks signed token inventory and cash per the standard maker bookkeeping:

    buy  s @ p:  cash -= s*p (+ fee),  position += s
    sell s @ p:  cash += s*p (- fee),  position -= s

Equity (mark-to-market) at mids m_t is ``cash + sum_t position_t * m_t``. The
*change* in equity between two marks is the period PnL the metrics consume, so
adverse selection is captured automatically: a fill followed by an unfavourable
mid move reduces equity on the very next sample.

At resolution, ``settle`` marks each token at its binary outcome (0 or 1), which
is the only correct terminal valuation for a prediction market.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List


@dataclass
class Ledger:
    cash: float = 0.0
    maker_fee: float = 0.0  # fee fraction of notional
    positions: Dict[str, float] = field(default_factory=dict)   # token -> signed tokens
    cost_basis: Dict[str, float] = field(default_factory=dict)  # token -> avg cost (long side)
    num_buys: int = 0
    num_sells: int = 0
    buy_volume: float = 0.0
    sell_volume: float = 0.0
    fees_paid: float = 0.0

    def position(self, token: str) -> float:
        return self.positions.get(str(token), 0.0)

    def avg_price(self, token: str) -> float:
        return self.cost_basis.get(str(token), 0.0)

    def on_fill(self, token: str, side: str, size: float, price: float) -> None:
        token = str(token)
        notional = size * price
        fee = notional * self.maker_fee
        self.fees_paid += fee
        prev = self.positions.get(token, 0.0)

        if side == "buy":
            self.cash -= notional + fee
            new_pos = prev + size
            # Update average cost only while accumulating a long position.
            if prev >= 0:
                prev_cost = self.cost_basis.get(token, 0.0)
                self.cost_basis[token] = (
                    (prev_cost * prev + price * size) / new_pos if new_pos > 0 else 0.0
                )
            self.positions[token] = new_pos
            self.num_buys += 1
            self.buy_volume += size
        else:  # sell
            self.cash += notional - fee
            self.positions[token] = prev - size
            self.num_sells += 1
            self.sell_volume += size

    def equity(self, mids: Dict[str, float]) -> float:
        """Mark-to-market total equity given current mids per token."""
        eq = self.cash
        for token, pos in self.positions.items():
            if pos == 0:
                continue
            m = mids.get(token)
            if m is not None:
                eq += pos * m
        return eq

    def settle(self, outcomes: Dict[str, float]) -> None:
        """Apply terminal binary settlement: each token worth its outcome in {0,1}."""
        for token, pos in list(self.positions.items()):
            payoff = outcomes.get(token)
            if payoff is None:
                continue
            self.cash += pos * payoff
            self.positions[token] = 0.0
