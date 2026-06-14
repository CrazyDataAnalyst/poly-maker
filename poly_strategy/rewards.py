"""
Liquidity-reward optimization.

Polymarket distributes ~$12M/year in maker rewards. The payout uses a quadratic
scoring function that pays you for resting *close to the midpoint* and *on both
sides*. Two-sided quoting earns roughly 3x one-sided. For a reward-aware maker,
much of the realized PnL is this rebate, not spread capture - so quote placement
must respect the reward band, not just the AS spread.

The per-order score (mirroring data_updater/find_markets.add_formula_params, which
is the platform formula this repo already uses):

    s = |price - midpoint|                      # distance from mid
    S = ((v - s) / v)^2   for s <= v, else 0    # quadratic, v = max_spread (band half-width)

So score is maximized at the mid and decays to zero at the edge of the band ``v``.
Orders outside the band earn nothing.

This module provides:
  * ``reward_score`` - the quadratic score for ranking/are-we-eligible checks.
  * ``clamp_to_band`` - pull a quote inward to the reward-eligible band (scaled by
    ``band_fraction`` so we sit safely inside, not on the cliff edge).
  * ``two_sided_ok`` - the "10-cent rule" style check that both sides are present.

Critically, reward optimization is applied *after* risk (AS spread, toxicity,
inventory). We never tighten into the band if doing so violates the minimum safe
spread - rewards are worthless if a toxic fill costs more than days of rebates.
"""

from __future__ import annotations

from typing import Optional, Tuple

from poly_strategy.math_utils import clamp


def reward_score(price: float, midpoint: float, max_spread_cents: float, size: float = 1.0) -> float:
    """Polymarket quadratic reward score for a single resting order.

    ``max_spread_cents`` is the band half-width in *cents* (the sheet 'max_spread'
    column, e.g. 3.0). Returns 0 outside the band.
    """
    v = max(max_spread_cents / 100.0, 1e-6)
    s = abs(price - midpoint)
    if s > v:
        return 0.0
    shape = ((v - s) / v) ** 2
    return shape * max(size, 0.0)


def in_band(price: float, midpoint: float, max_spread_cents: float) -> bool:
    """True if the price is inside the reward-eligible band around the midpoint."""
    v = max_spread_cents / 100.0
    return abs(price - midpoint) <= v + 1e-12


def clamp_to_band(
    price: float,
    midpoint: float,
    max_spread_cents: float,
    side: str,
    band_fraction: float = 0.8,
    tick_size: float = 0.01,
) -> float:
    """Pull a quote inward so it earns rewards, without crossing the midpoint.

    We only ever move a quote *toward* the mid (tighter), never away, and never
    past ``band_fraction * v`` from the mid (a safety margin inside the cliff).
    If the AS quote is already inside the band, it is returned unchanged - we do
    not widen a safe quote just to chase the exact band edge.
    """
    v = max(max_spread_cents / 100.0, 1e-6) * clamp(band_fraction, 0.1, 1.0)

    if side == "bid":
        # Bid sits below mid; furthest-in eligible price is midpoint - v.
        lowest_eligible = midpoint - v
        if price < lowest_eligible:
            price = lowest_eligible  # pull up into the band
        price = min(price, midpoint - tick_size)  # never cross the mid
    else:  # ask
        highest_eligible = midpoint + v
        if price > highest_eligible:
            price = highest_eligible  # pull down into the band
        price = max(price, midpoint + tick_size)

    return price


def two_sided_ok(bid_price: Optional[float], ask_price: Optional[float]) -> bool:
    """Both sides present => eligible for the ~3x two-sided reward multiplier."""
    return bid_price is not None and ask_price is not None


def expected_reward(
    bid_price: Optional[float],
    ask_price: Optional[float],
    midpoint: float,
    max_spread_cents: float,
    bid_size: float,
    ask_size: float,
) -> Tuple[float, float]:
    """Return (bid_reward_score, ask_reward_score) for the proposed two-sided quote."""
    b = reward_score(bid_price, midpoint, max_spread_cents, bid_size) if bid_price is not None else 0.0
    a = reward_score(ask_price, midpoint, max_spread_cents, ask_size) if ask_price is not None else 0.0
    return b, a
