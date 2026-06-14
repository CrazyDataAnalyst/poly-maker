"""
Numerical helpers for prediction-market market making.

Prediction-market prices are *probabilities*: bounded in (0, 1) and, crucially,
non-linear near the edges. A 1-cent move from 0.50 to 0.51 is trivial; a 1-cent
move from 0.01 to 0.02 doubles the implied odds. Every quantitative operation in
this engine therefore happens in **log-odds (logit) space**, where the bounded
probability axis becomes an unbounded, roughly-symmetric real line on which the
Avellaneda-Stoikov Brownian-motion assumptions are far more defensible.

This module is intentionally dependency-free (stdlib ``math`` only) so it can be
imported and unit-tested without the trading stack or a virtualenv.
"""

from __future__ import annotations

import math
from typing import Iterable

# Smallest distance we ever allow a probability to sit from the {0, 1} barriers.
# Polymarket valid prices are 0.01..0.99, so 1e-4 is comfortably inside and keeps
# logit() finite without distorting realistic quotes.
PROB_EPS = 1e-4


def clamp(value: float, low: float, high: float) -> float:
    """Clamp ``value`` into the inclusive range [low, high]."""
    if value < low:
        return low
    if value > high:
        return high
    return value


def clamp_prob(p: float, eps: float = PROB_EPS) -> float:
    """Clamp a probability strictly inside (0, 1) by ``eps``."""
    return clamp(p, eps, 1.0 - eps)


def logit(p: float, eps: float = PROB_EPS) -> float:
    """Map a probability in (0, 1) to log-odds ``ln(p / (1 - p))`` on the real line."""
    p = clamp_prob(p, eps)
    return math.log(p / (1.0 - p))


def inv_logit(x: float) -> float:
    """Logistic sigmoid: map a real log-odds value back to a probability in (0, 1).

    Implemented in a numerically stable, branch-split form so very large |x| does
    not overflow ``exp``.
    """
    if x >= 0.0:
        z = math.exp(-x)
        return 1.0 / (1.0 + z)
    z = math.exp(x)
    return z / (1.0 + z)


def prob_to_logit_slope(p: float) -> float:
    """Derivative dp/dx of the sigmoid at probability ``p``: ``p * (1 - p)``.

    Used to convert a spread/volatility expressed in log-odds units into the
    equivalent move in probability (price) units, and vice-versa. Near 0.5 the
    slope is ~0.25 (price and log-odds move similarly); near the edges it
    collapses toward 0 (a large log-odds move is a tiny price move).
    """
    p = clamp_prob(p)
    return p * (1.0 - p)


def safe_div(numerator: float, denominator: float, default: float = 0.0) -> float:
    """Divide, returning ``default`` when the denominator is ~0."""
    if denominator is None or abs(denominator) < 1e-12:
        return default
    return numerator / denominator


def norm_cdf(x: float) -> float:
    """Standard-normal CDF via ``math.erf`` (no scipy dependency).

    Used by the Bulk Volume Classification step of the VPIN toxicity estimator.
    """
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def ewma(prev: float, sample: float, lam: float) -> float:
    """One step of an exponentially-weighted moving average.

    ``lam`` is the decay (persistence) weight on the previous estimate, so the
    new sample receives weight ``(1 - lam)``.
    """
    return lam * prev + (1.0 - lam) * sample


def mean(values: Iterable[float]) -> float:
    """Arithmetic mean with an empty-safe 0.0 fallback."""
    vals = list(values)
    if not vals:
        return 0.0
    return sum(vals) / len(vals)
