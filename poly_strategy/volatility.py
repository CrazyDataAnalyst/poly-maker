"""
Volatility estimation.

Avellaneda-Stoikov spreads scale with sigma^2: you must charge more when the
world is moving faster. We need a sigma that is (a) responsive to regime change
and (b) measured in the same space we quote in - log-odds.

Two sources are fused:

  * **Realtime EWMA** of squared log-odds increments of the fair value. This is
    the fast, market-specific signal. RiskMetrics-style EWMA (lambda~0.94) reacts
    to a volatility regime change within a handful of updates.
  * **Sheet annualized vol** (the existing ``1_hour``..``30_day`` columns) as a
    slow, robust prior. Early in a market's life the EWMA has too few samples;
    the sheet value keeps the spread sane until realtime data accumulates.

The output ``sigma_horizon`` is the standard deviation of the fair value, in
*price (probability) units*, over the planning horizon (T-t). That is exactly the
quantity the reservation-price and GLFT spread formulas consume.

Why per-horizon and in price units? Because the inventory penalty
``q * gamma * sigma^2 * (T-t)`` and the GLFT spread are most intuitive when sigma
already encodes "how far can fair value drift before I can unwind". Converting
the dimensionless log-odds vol to price units via the sigmoid slope keeps the
penalty correctly *smaller near the 0/1 edges*, where a big belief move is only a
small price move.
"""

from __future__ import annotations

import math
from typing import Optional

from poly_strategy.math_utils import clamp_prob, logit, prob_to_logit_slope


# Minutes per year used by the sheet's annualization (60 * 24 * 252), matching
# data_updater/find_markets.calculate_annualized_volatility so the two agree.
_MINUTES_PER_YEAR = 60.0 * 24.0 * 252.0


class VolatilityEstimator:
    """Per-market realized-volatility estimator in log-odds space."""

    def __init__(self, ewma_lambda: float = 0.94, floor: float = 0.02):
        self.ewma_lambda = ewma_lambda
        self.floor = floor
        self._last_logit: Optional[float] = None
        self._var_logit: Optional[float] = None  # EWMA variance of per-update increments
        self._n: int = 0

    def update(self, fair: float) -> None:
        """Feed a new fair-value observation (probability) to the estimator."""
        x = logit(clamp_prob(fair))
        if self._last_logit is None:
            self._last_logit = x
            return
        delta = x - self._last_logit
        self._last_logit = x
        sample_var = delta * delta
        if self._var_logit is None:
            self._var_logit = sample_var
        else:
            self._var_logit = self.ewma_lambda * self._var_logit + (1.0 - self.ewma_lambda) * sample_var
        self._n += 1

    def sigma_logit_per_update(self) -> float:
        """Per-update log-odds volatility (sqrt of EWMA increment variance)."""
        if self._var_logit is None:
            return 0.0
        return math.sqrt(max(self._var_logit, 0.0))

    @staticmethod
    def annualized_to_logit_per_update(annual_vol: float, seconds_per_update: float) -> float:
        """Convert a sheet annualized vol into a per-update log-odds sigma.

        The sheet computes std of 1-minute log *price* returns, annualized by
        sqrt(minutes/year). We de-annualize to per-update std. (Price log-returns
        and log-odds increments coincide to first order near p=0.5 and are a fine
        prior elsewhere given this is only a fallback weight.)
        """
        if annual_vol <= 0 or seconds_per_update <= 0:
            return 0.0
        per_minute = annual_vol / math.sqrt(_MINUTES_PER_YEAR)
        updates_per_minute = 60.0 / seconds_per_update
        # Variance scales linearly with time; convert per-minute -> per-update.
        if updates_per_minute <= 0:
            return per_minute
        return per_minute / math.sqrt(updates_per_minute)

    def sigma_horizon_price(
        self,
        fair: float,
        horizon_hours: float,
        seconds_per_update: float = 5.0,
        sheet_annual_vol: float = 0.0,
        sheet_weight: float = 0.5,
    ) -> float:
        """Std of fair value over the planning horizon, in price (probability) units.

        Steps:
          1. Blend realtime and sheet per-update log-odds sigma.
          2. Scale to the horizon: var grows linearly in time => sigma ~ sqrt(N).
          3. Convert log-odds -> price via the sigmoid slope p(1-p).
          4. Floor it so spread never collapses to zero.
        """
        realtime = self.sigma_logit_per_update()
        prior = self.annualized_to_logit_per_update(sheet_annual_vol, seconds_per_update)

        if realtime > 0 and prior > 0:
            sigma_update = (1.0 - sheet_weight) * realtime + sheet_weight * prior
        elif realtime > 0:
            sigma_update = realtime
        else:
            sigma_update = prior

        if sigma_update <= 0:
            sigma_update = self.floor

        horizon_seconds = max(horizon_hours, 0.0) * 3600.0
        n_updates = horizon_seconds / max(seconds_per_update, 1e-6)
        sigma_logit_horizon = sigma_update * math.sqrt(max(n_updates, 1.0))

        # Convert to price units at the current fair value.
        slope = prob_to_logit_slope(fair)
        sigma_price = sigma_logit_horizon * slope

        return max(sigma_price, self.floor)
