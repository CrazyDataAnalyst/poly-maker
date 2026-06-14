"""
Inventory management: hard limits and position sizing.

In equities you hedge inventory by trading the underlying. In prediction markets
there is no underlying - the "asset" is an unobservable probability. So inventory
risk is managed entirely through (a) a hard token limit ``Q`` derived from the
maximum tolerable loss on a single binary outcome, and (b) shrinking order size
as you approach that limit.

Worst-case loss on a binary outcome:
  * Long  q tokens at avg cost c: if it resolves NO you lose ``q * c``.
  * Short q tokens at avg cost c (you received 1-c... ): if it resolves YES you
    lose ``q * (1 - c)``.
The conservative single number is ``Q = max_loss / max(c, 1 - c)`` evaluated at
the current fair, which is why ``Q`` is *smaller* for lopsided markets (a 0.9
contract can lose 0.9 per token if wrong, so you may hold fewer).

Position sizing uses fractional Kelly on the *maker edge* (half-spread captured),
then clamps to the remaining capacity before ``Q``. This keeps size large when
edge is high and inventory is low, and forces it to zero exactly at the limit -
the practical realization of "spread your capital across many small positions and
never let one toxic fill blow up days of rewards."
"""

from __future__ import annotations

from poly_strategy.math_utils import clamp


def inventory_limit(max_loss_usd: float, fair: float) -> float:
    """Hard inventory cap ``Q`` in tokens from max tolerable single-outcome loss."""
    worst_case_price = max(fair, 1.0 - fair, 1e-6)
    return max(max_loss_usd / worst_case_price, 0.0)


def inventory_ratio(position: float, target: float, limit_q: float) -> float:
    """Signed inventory utilization in [-1, 1]; +1 means at the long limit."""
    if limit_q <= 0:
        return 0.0
    return clamp((position - target) / limit_q, -1.0, 1.0)


def kelly_size(
    edge: float,
    fair: float,
    base_size: float,
    kelly_fraction: float,
    max_order_size: float,
) -> float:
    """Fractional-Kelly order size scaled by the maker edge.

    ``edge`` is the half-spread we expect to capture (price units). Variance of a
    binary outcome is ``fair * (1 - fair)``. The Kelly-style fraction ``edge /
    variance`` is scaled by ``kelly_fraction`` and applied to ``base_size``, then
    capped. We keep ``base_size`` as the anchor (rather than full bankroll Kelly)
    because reward farming wants *many small* orders, not a few large ones.
    """
    variance = max(fair * (1.0 - fair), 1e-4)
    kelly_mult = clamp(kelly_fraction * (edge / variance), 0.0, 3.0)
    size = base_size * (0.5 + kelly_mult)  # floor at half base so we always quote something
    return clamp(size, 0.0, max_order_size)


def capacity_capped_size(
    desired_size: float,
    position: float,
    target: float,
    limit_q: float,
    side: str,
    min_size: float,
) -> float:
    """Clamp a desired order size to the remaining capacity toward ``Q``.

    For a buy, remaining capacity is ``Q - position`` (can't exceed long limit);
    for a sell it is capacity toward the short limit ``Q + position`` (positions
    are tracked as signed, long positive). Returns 0 if below the venue minimum.
    """
    if side == "buy":
        remaining = limit_q - (position - target)
    else:  # sell
        remaining = limit_q + (position - target)

    remaining = max(remaining, 0.0)
    size = min(desired_size, remaining)

    if size < min_size:
        return 0.0
    return size
