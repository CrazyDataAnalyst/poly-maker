"""
Execution-layer guards shared by the live path and tests.

Kept here (pure, dependency-free) so the maker-only invariant can be unit-tested
without importing the live trading stack.
"""

from __future__ import annotations

from typing import Optional


def is_passive_quote(
    side: str,
    price: Optional[float],
    best_bid: Optional[float],
    best_ask: Optional[float],
    tick_size: float,
) -> bool:
    """True if the quote rests passively (cannot cross the opposite touch).

    A BUY must sit at least one tick below the best ask; a SELL at least one tick
    above the best bid. This is the hard maker-only guarantee behind earning maker
    rebates and never paying taker fees.
    """
    if price is None:
        return False
    if side.upper() == "BUY":
        return best_ask is None or price <= best_ask - tick_size + 1e-9
    return best_bid is None or price >= best_bid + tick_size - 1e-9
