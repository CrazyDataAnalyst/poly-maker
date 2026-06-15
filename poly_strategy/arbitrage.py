"""
Dutch-book (arbitrage) detection.

The defining invariant of a Polymarket binary market is enforced at the smart
contract level: ``P(YES) + P(NO) = 1``, backed by exactly $1 of USDC collateral
via the mint/merge mechanism. Any time the *tradeable* prices violate this, there
is risk-free money:

  * **Buy-side Dutch book.** If you can BUY YES at ``ask_yes`` and BUY NO at
    ``ask_no`` with ``ask_yes + ask_no < 1``, you hold one of each token, which is
    guaranteed to be worth exactly $1 at resolution. Profit =
    ``1 - (ask_yes + ask_no)`` per pair, locked, regardless of outcome.

  * **Sell-side / merge book.** If you can SELL YES at ``bid_yes`` and SELL NO at
    ``bid_no`` with ``bid_yes + bid_no > 1`` (and you can source/mint the pair),
    you collect more than $1 for a pair that costs $1 to mint. Profit =
    ``(bid_yes + bid_no) - 1``.

This module only *detects*; execution (taking both legs atomically, or
mint/merge) is the order manager's job. Detection is gated by ``min_edge`` net of
fees so we don't chase sub-tick noise that evaporates in 2.7 seconds.

Multi-outcome (NegRisk) markets generalize the same idea: if the sum of all
mutually-exclusive YES asks < 1, buy them all.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional


@dataclass(frozen=True)
class ArbOpportunity:
    kind: str          # "buy_pair" or "sell_pair"
    edge: float        # price-units profit per pair, net of fees
    legs: tuple        # ((side, price), ...) describing the trade
    note: str = ""


def detect_binary_arb(
    ask_yes: Optional[float],
    ask_no: Optional[float],
    bid_yes: Optional[float],
    bid_no: Optional[float],
    min_edge: float = 0.005,
    fee: float = 0.0,
) -> Optional[ArbOpportunity]:
    """Detect a risk-free Dutch book in a single binary market.

    Returns the better of the buy-pair / sell-pair opportunities, or ``None``.
    """
    best: Optional[ArbOpportunity] = None

    # Buy-side: cost to own a guaranteed $1 pair.
    if ask_yes is not None and ask_no is not None:
        cost = ask_yes + ask_no + 2.0 * fee
        edge = 1.0 - cost
        if edge >= min_edge:
            best = ArbOpportunity(
                kind="buy_pair",
                edge=edge,
                legs=(("BUY_YES", ask_yes), ("BUY_NO", ask_no)),
                note=f"buy YES@{ask_yes:.4f}+NO@{ask_no:.4f} -> lock {edge:.4f}",
            )

    # Sell-side: collect more than $1 for a pair worth $1.
    if bid_yes is not None and bid_no is not None:
        proceeds = bid_yes + bid_no - 2.0 * fee
        edge = proceeds - 1.0
        if edge >= min_edge and (best is None or edge > best.edge):
            best = ArbOpportunity(
                kind="sell_pair",
                edge=edge,
                legs=(("SELL_YES", bid_yes), ("SELL_NO", bid_no)),
                note=f"sell YES@{bid_yes:.4f}+NO@{bid_no:.4f} -> lock {edge:.4f}",
            )

    return best


def detect_multi_outcome_arb(
    yes_asks: List[Optional[float]],
    min_edge: float = 0.005,
    fee: float = 0.0,
) -> Optional[ArbOpportunity]:
    """Detect a Dutch book across mutually-exclusive outcomes (NegRisk markets).

    If you can buy YES on every outcome for a combined cost < $1, exactly one
    resolves YES (worth $1) so the basket is risk-free.
    """
    prices = [p for p in yes_asks if p is not None]
    if len(prices) < 2:
        return None
    cost = sum(prices) + fee * len(prices)
    edge = 1.0 - cost
    if edge >= min_edge:
        return ArbOpportunity(
            kind="buy_basket",
            edge=edge,
            legs=tuple(("BUY", p) for p in prices),
            note=f"buy all {len(prices)} outcomes for {cost:.4f} -> lock {edge:.4f}",
        )
    return None
