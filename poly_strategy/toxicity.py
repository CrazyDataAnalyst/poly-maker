"""
VPIN - Volume-Synchronized Probability of Informed Trading.

Adverse selection is the market maker's existential risk: someone hitting your
quote knows more than you. Easley, López de Prado & O'Hara (2012) showed that the
*imbalance* between buy and sell volume, measured in volume-time rather than
clock-time, is a real-time estimate of the fraction of toxic (informed) flow -
and that it spiked hours before the 2010 flash crash.

Implementation (volume-clock + Bulk Volume Classification):

  * Trades are accumulated into fixed-size **volume buckets** of ``bucket_size``
    tokens. Volume-time, not clock-time, is what matters: information arrives with
    trades, not with seconds.
  * Each increment of volume is split into "buy" and "sell" fractions using BVC:
    the fraction is ``Phi(dP / sigma_dP)`` where ``dP`` is the price change and
    ``sigma_dP`` its rolling std. A big up-move => mostly informed buying. This
    avoids needing the aggressor flag (which the market-data feed may not give).
  * ``VPIN = mean over the last N buckets of |V_buy - V_sell| / bucket_size``,
    a number in [0, 1].

The maker consumes VPIN two ways: widen spreads proportionally above a soft
threshold, and pull quotes on the exposed side above a hard threshold (the
kill-switch). Both directly reduce expected loss to informed flow.

If a true buy/sell aggressor split is available it can be fed directly via
``add_signed_volume``; otherwise feed prints with ``add_trade`` and let BVC infer.
"""

from __future__ import annotations

import math
from collections import deque
from typing import Deque, Optional

from poly_strategy.math_utils import norm_cdf


class VPINEstimator:
    """Per-market VPIN estimator using volume buckets and bulk classification."""

    def __init__(self, bucket_size: float = 200.0, num_buckets: int = 20):
        self.bucket_size = max(bucket_size, 1.0)
        self.num_buckets = max(num_buckets, 1)
        self._buckets: Deque[float] = deque(maxlen=self.num_buckets)  # |buy-sell| per bucket
        self._cur_buy = 0.0
        self._cur_sell = 0.0
        self._cur_vol = 0.0
        # Rolling price-change volatility for BVC.
        self._last_price: Optional[float] = None
        self._dp_var: Optional[float] = None
        self._dp_lambda = 0.95

    def _update_dp_sigma(self, price: float) -> float:
        """Update and return the rolling std of price changes (for BVC scaling)."""
        if self._last_price is None:
            self._last_price = price
            return 0.0
        dp = price - self._last_price
        self._last_price = price
        sample = dp * dp
        if self._dp_var is None:
            self._dp_var = sample
        else:
            self._dp_var = self._dp_lambda * self._dp_var + (1.0 - self._dp_lambda) * sample
        return math.sqrt(max(self._dp_var, 1e-12))

    def add_trade(self, price: float, volume: float) -> None:
        """Add an (unsigned) trade print; the buy/sell split is inferred via BVC.

        BVC: the buy fraction of this print is ``Phi(dP / sigma_dP)`` where ``dP``
        is the price change since the previous print and ``sigma_dP`` its rolling
        std. A large up-move => fraction near 1 (informed buying); flat => 0.5.
        """
        if volume <= 0:
            return
        prev = self._last_price
        sigma_dp = self._update_dp_sigma(price)  # also advances _last_price
        if prev is None or sigma_dp <= 1e-9:
            buy_frac = 0.5
        else:
            buy_frac = norm_cdf((price - prev) / sigma_dp)
        self.add_signed_volume(buy_frac * volume, (1.0 - buy_frac) * volume)

    def add_signed_volume(self, buy_volume: float, sell_volume: float) -> None:
        """Add volume already split into buy/sell components (volume-clock fill)."""
        remaining_buy = buy_volume
        remaining_sell = sell_volume
        while remaining_buy + remaining_sell > 0:
            space = self.bucket_size - self._cur_vol
            chunk = min(space, remaining_buy + remaining_sell)
            if chunk <= 0:
                break
            total = remaining_buy + remaining_sell
            take_buy = chunk * (remaining_buy / total) if total > 0 else 0.0
            take_sell = chunk - take_buy
            self._cur_buy += take_buy
            self._cur_sell += take_sell
            self._cur_vol += chunk
            remaining_buy -= take_buy
            remaining_sell -= take_sell
            if self._cur_vol >= self.bucket_size - 1e-9:
                self._buckets.append(abs(self._cur_buy - self._cur_sell))
                self._cur_buy = self._cur_sell = self._cur_vol = 0.0

    def vpin(self) -> float:
        """Current VPIN in [0, 1]; 0 until at least one bucket has filled."""
        if not self._buckets:
            return 0.0
        return sum(self._buckets) / (len(self._buckets) * self.bucket_size)

    def is_warm(self) -> bool:
        """True once enough buckets exist for the estimate to be meaningful."""
        return len(self._buckets) >= max(2, self.num_buckets // 4)
