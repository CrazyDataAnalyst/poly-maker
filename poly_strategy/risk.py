"""
Risk controls: kill switches and staged withdrawal.

The research corpus is unanimous on the failure modes that actually kill makers:
adverse selection during news jumps, quoting into resolution, stale order books,
and inventory blow-ups. This module centralizes the *defensive* decisions, returning
a structured directive the quoter obeys. It never sends orders itself.

Decisions, in order of severity:

  1. **Stale book** - if the local book hasn't updated within ``max_book_age_s``,
     we cannot trust our fair value; withdraw entirely. ("Order book desync" is a
     named killer; quoting from a stale book is an immediate loss.)

  2. **Resolution proximity** - the Glosten-Milgrom adverse-selection cost
     dominates near expiry, where informed fraction mu -> 1. We widen spreads
     starting ``widen_hours`` out and fully withdraw inside ``withdraw_hours``.

  3. **Toxicity (VPIN)** - above the soft threshold, widen proportionally; above
     the hard threshold, pull the exposed side (the side informed flow is hitting).

  4. **Inventory limit** - at/above the hard limit ``Q`` on a side, stop adding to
     it (the GLFT boundary).

  5. **Volatility spike** - if realized vol jumps far above its own recent level,
     widen; this is the continuous-time analogue of the jump-diffusion kernel.

The output ``RiskDirective`` tells the quoter: should I quote each side, by how
much to widen, and why (for observability).
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import List, Optional

from poly_strategy.math_utils import clamp


@dataclass
class RiskDirective:
    quote_bid: bool = True
    quote_ask: bool = True
    spread_multiplier: float = 1.0
    reasons: List[str] = field(default_factory=list)

    @property
    def withdraw_all(self) -> bool:
        return not self.quote_bid and not self.quote_ask


def evaluate_risk(
    *,
    book_age_s: Optional[float],
    hours_to_resolution: Optional[float],
    vpin: float,
    inventory_ratio: float,
    sigma_price: float,
    sigma_baseline: Optional[float] = None,
    # config-derived thresholds
    max_book_age_s: float = 8.0,
    resolution_widen_hours: float = 6.0,
    resolution_withdraw_hours: float = 1.0,
    vpin_widen_threshold: float = 0.35,
    vpin_kill_threshold: float = 0.60,
    vpin_widen_gain: float = 2.0,
    inventory_limit_ratio: float = 0.999,
    vol_spike_mult: float = 3.0,
    max_spread_multiplier: float = 6.0,
) -> RiskDirective:
    """Combine all defensive signals into a single quoting directive."""
    d = RiskDirective()

    # 1. Stale book -> withdraw everything.
    if book_age_s is not None and book_age_s > max_book_age_s:
        d.quote_bid = d.quote_ask = False
        d.reasons.append(f"stale_book({book_age_s:.1f}s)")
        return d

    # 2. Resolution proximity.
    if hours_to_resolution is not None:
        if hours_to_resolution <= resolution_withdraw_hours:
            d.quote_bid = d.quote_ask = False
            d.reasons.append(f"near_resolution({hours_to_resolution:.2f}h)")
            return d
        if hours_to_resolution <= resolution_widen_hours:
            # Linearly widen from 1x at widen_hours to 3x at withdraw_hours.
            span = max(resolution_widen_hours - resolution_withdraw_hours, 1e-6)
            frac = (resolution_widen_hours - hours_to_resolution) / span
            d.spread_multiplier *= 1.0 + 2.0 * clamp(frac, 0.0, 1.0)
            d.reasons.append(f"resolution_widen(x{d.spread_multiplier:.2f})")

    # 3. Toxicity.
    if vpin >= vpin_kill_threshold:
        # Pull the side that informed flow is hitting. Net buying (informed think
        # value is higher) lifts asks -> our ask is the exposed side. We can't see
        # the sign here cheaply, so pull both sides on extreme toxicity.
        d.quote_bid = d.quote_ask = False
        d.reasons.append(f"vpin_kill({vpin:.2f})")
        return d
    if vpin >= vpin_widen_threshold:
        excess = (vpin - vpin_widen_threshold) / max(1.0 - vpin_widen_threshold, 1e-6)
        d.spread_multiplier *= 1.0 + vpin_widen_gain * clamp(excess, 0.0, 1.0)
        d.reasons.append(f"vpin_widen({vpin:.2f})")

    # 4. Inventory limit -> stop adding to the exposed side.
    if inventory_ratio >= inventory_limit_ratio:
        d.quote_bid = False
        d.reasons.append("long_limit")
    elif inventory_ratio <= -inventory_limit_ratio:
        d.quote_ask = False
        d.reasons.append("short_limit")

    # 5. Volatility spike vs baseline.
    if sigma_baseline is not None and sigma_baseline > 0 and sigma_price > vol_spike_mult * sigma_baseline:
        d.spread_multiplier *= 1.5
        d.reasons.append("vol_spike")

    d.spread_multiplier = clamp(d.spread_multiplier, 1.0, max_spread_multiplier)
    return d


def now_s() -> float:
    """Monotonic-ish wall clock for book-age computations (seconds)."""
    return time.time()
