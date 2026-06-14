"""
Avellaneda-Stoikov / Guéant-Lehalle-Fernandez-Tapia quoting core.

This is the "single most important number in market making" from the research
corpus: the **reservation price** - the inventory-adjusted fair value the maker
is actually indifferent to trading at - and the **optimal spread** around it.

Reservation price (AS 2008):

    r = s - q * gamma * sigma^2 * (T - t)

  * Long inventory (q > 0) pushes r *below* fair: you quote a tighter ask / wider
    bid to bleed the position down.
  * Short inventory does the opposite.

Two design adaptations for prediction markets:

  1. **Normalized inventory.** Raw ``q`` in tokens makes the skew un-comparable
     across markets and dollar sizes. We use ``f = (q - target) / Q`` in [-1, 1],
     where ``Q`` is the hard inventory limit. The shift at the limit is then
     ``gamma * sigma^2``, which is dimensionally clean and behaves identically
     whether the market trades in 20-lots or 2000-lots. ``(T - t)`` is folded into
     ``sigma`` upstream (volatility.sigma_horizon_price already scales to horizon).

  2. **Bounded-price safety.** The reservation price and both quotes are clamped
     into (0, 1) and into the operator's [min_price, max_price] band, so the model
     can never emit an "impossible" price - the GLFT bounded-inventory guarantee
     plus a hard floor.

Optimal spread (AS 2008):

    total_spread = gamma * sigma^2 + (2 / gamma) * ln(1 + gamma / kappa)
    half_spread  = total_spread / 2

The first term is inventory-risk compensation (grows with volatility); the second
is the pure liquidity-provision profit that survives even at gamma -> 0
(-> 2/kappa). The result is clamped to [min_half_spread, max_half_spread].

GLFT bounded inventory: as |f| -> 1 the *exposed* side's effective spread is
widened (and, at the limit, the side is withdrawn by the caller), which reproduces
the GLFT property that quotes vanish at the inventory boundary.
"""

from __future__ import annotations

import math
from typing import Tuple

from poly_strategy.math_utils import clamp, clamp_prob


def as_half_spread(gamma: float, sigma_price: float, kappa: float) -> float:
    """Avellaneda-Stoikov optimal half-spread in price units (pre-clamp)."""
    gamma = max(gamma, 1e-6)
    kappa = max(kappa, 1e-6)
    inventory_term = gamma * sigma_price * sigma_price
    info_term = (2.0 / gamma) * math.log1p(gamma / kappa)
    return 0.5 * (inventory_term + info_term)


def reservation_price(
    fair: float,
    inventory_ratio: float,
    gamma: float,
    sigma_price: float,
    skew_cap: float,
) -> float:
    """Inventory-adjusted reservation price in (0, 1).

    ``inventory_ratio`` = (q - target) / Q, clamped to [-1, 1] by the caller.
    The shift is capped at ``skew_cap`` (price units) so a vol blow-up cannot
    fling the reservation price across the book.
    """
    f = clamp(inventory_ratio, -1.0, 1.0)
    shift = gamma * sigma_price * sigma_price * f
    shift = clamp(shift, -skew_cap, skew_cap)
    return clamp_prob(fair - shift)


def glft_inventory_widen(inventory_ratio: float, side: str) -> float:
    """Multiplier (>= 1) that widens the *exposed* side as inventory nears its limit.

    If you are long (ratio > 0), buying more is the exposed action, so the *bid*
    widens as ratio -> 1. Symmetrically the ask widens as ratio -> -1. The barrier
    ``1 / (1 - |ratio|)`` -> infinity at the boundary, reproducing the GLFT
    "quotes disappear at the limit" behaviour; the caller additionally hard-stops
    the side at the limit.
    """
    f = clamp(inventory_ratio, -0.999, 0.999)
    if side == "bid":
        exposure = max(f, 0.0)       # long inventory makes further buying risky
    else:  # ask
        exposure = max(-f, 0.0)      # short inventory makes further selling risky
    if exposure <= 0.0:
        return 1.0
    return 1.0 + (exposure / (1.0 - exposure))


def compute_quotes(
    fair: float,
    inventory_ratio: float,
    gamma: float,
    kappa: float,
    sigma_price: float,
    *,
    min_half_spread: float,
    max_half_spread: float,
    skew_cap: float,
    spread_multiplier: float = 1.0,
    tick_size: float = 0.01,
    min_price: float = 0.05,
    max_price: float = 0.95,
) -> Tuple[float, float, float]:
    """Compute (bid_price, ask_price, reservation_price).

    ``spread_multiplier`` carries exogenous widening (toxicity, near-resolution).
    Quotes are rounded to the tick *outward* (bid down, ask up) so we never quote
    tighter than intended, and clamped to the price band.
    """
    r = reservation_price(fair, inventory_ratio, gamma, sigma_price, skew_cap)

    base_half = as_half_spread(gamma, sigma_price, kappa) * max(spread_multiplier, 1.0)
    base_half = clamp(base_half, min_half_spread, max_half_spread)

    bid_half = base_half * glft_inventory_widen(inventory_ratio, "bid")
    ask_half = base_half * glft_inventory_widen(inventory_ratio, "ask")

    # Re-cap after inventory widening so the barrier can't exceed the hard ceiling.
    bid_half = min(bid_half, max_half_spread)
    ask_half = min(ask_half, max_half_spread)

    bid = r - bid_half
    ask = r + ask_half

    # Round outward to the tick.
    if tick_size > 0:
        bid = math.floor(bid / tick_size) * tick_size
        ask = math.ceil(ask / tick_size) * tick_size

    bid = clamp(bid, min_price, max_price)
    ask = clamp(ask, min_price, max_price)

    # Degenerate guard: ensure ask strictly above bid by at least one tick.
    if ask <= bid:
        ask = clamp(bid + (tick_size or 0.01), min_price, max_price)

    return bid, ask, r
