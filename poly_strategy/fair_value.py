"""
Fair-value estimation.

The single biggest flaw in the legacy bot is *mid-price bias*: it treats
``(best_bid + best_ask) / 2`` as truth and quotes one tick inside it. Two
problems with that:

  1. The mid is noisy and easily manipulated by a single small order at a wide
     price. A 1-lot at 0.20 against a real book at 0.50 drags the naive mid.
  2. The mid ignores book *imbalance*, which is the cheapest available predictor
     of the next price move. If the bid is 10x the size of the ask, the true
     clearing price is closer to the ask.

We fix both with a two-layer estimate:

  * **Micro-price** (Gatheral/Stoikov): a size-weighted mid that leans toward the
    thinner side, i.e. toward where price is likely to go next. This is the
    instantaneous signal.
  * **Log-odds belief smoothing**: an EWMA of the micro-price carried out in
    logit space, so transient spikes are damped but the estimate still lives in a
    space where moves are statistically well-behaved and can never escape (0, 1).

The estimator is deliberately *stateful per market* but cheap: one float of
state. It also accepts an optional external reference price (e.g. a more liquid
venue or an independent model) which, when supplied, anchors the belief - this is
the hook for the cross-venue / independent-pricing edge described in the research
corpus.

Will this increase PnL or reduce risk? Both: a better fair value reduces adverse
fills (you stop quoting a stale mid into a moving market) and tightens the spread
you can safely show (less uncertainty buffer needed).
"""

from __future__ import annotations

from typing import Optional

from poly_strategy.math_utils import (
    clamp_prob,
    ewma,
    inv_logit,
    logit,
    safe_div,
)


class FairValueEstimator:
    """Per-market fair-value estimator operating in log-odds space."""

    def __init__(self, ewma_lambda: float = 0.85, micro_weight: float = 0.6):
        # ``micro_weight`` blends the instantaneous micro-price against the
        # slower smoothed belief. Higher => more responsive, more noise.
        self.ewma_lambda = ewma_lambda
        self.micro_weight = micro_weight
        self._belief_logit: Optional[float] = None  # smoothed state, log-odds

    @staticmethod
    def micro_price(
        best_bid: Optional[float],
        best_ask: Optional[float],
        bid_size: Optional[float],
        ask_size: Optional[float],
    ) -> Optional[float]:
        """Size-weighted mid that leans toward the thinner side of the book.

        ``micro = bid * (ask_size / total) + ask * (bid_size / total)``

        When the ask is thin relative to the bid, ``bid_size`` is large, so the
        ask term dominates and the estimate is pulled up toward the ask - the
        direction price tends to move when buyers stack the bid.
        """
        if best_bid is None or best_ask is None:
            return None
        if bid_size is None or ask_size is None or (bid_size + ask_size) <= 0:
            return (best_bid + best_ask) / 2.0
        total = bid_size + ask_size
        return best_bid * (ask_size / total) + best_ask * (bid_size / total)

    def update(
        self,
        best_bid: Optional[float],
        best_ask: Optional[float],
        bid_size: Optional[float] = None,
        ask_size: Optional[float] = None,
        external_ref: Optional[float] = None,
    ) -> Optional[float]:
        """Incorporate the latest book snapshot and return the fair value in (0, 1).

        Returns ``None`` only when the book is one-sided/empty *and* no prior
        belief exists - the caller should then refrain from quoting.
        """
        micro = self.micro_price(best_bid, best_ask, bid_size, ask_size)

        # One-sided book: fall back to whatever side exists, else prior belief.
        if micro is None:
            if best_bid is not None:
                micro = best_bid
            elif best_ask is not None:
                micro = best_ask
            elif self._belief_logit is not None:
                return inv_logit(self._belief_logit)
            else:
                return None

        micro = clamp_prob(micro)
        micro_l = logit(micro)

        if self._belief_logit is None:
            self._belief_logit = micro_l
        else:
            # Smooth in log-odds space.
            self._belief_logit = ewma(self._belief_logit, micro_l, self.ewma_lambda)

        # Combine instantaneous micro and smoothed belief.
        fair_l = self.micro_weight * micro_l + (1.0 - self.micro_weight) * self._belief_logit

        # Anchor to an external reference if provided (blend in log-odds space).
        if external_ref is not None:
            ext_l = logit(clamp_prob(external_ref))
            fair_l = 0.5 * fair_l + 0.5 * ext_l

        return inv_logit(fair_l)

    @property
    def belief(self) -> Optional[float]:
        """Current smoothed belief as a probability, or ``None`` if unseeded."""
        if self._belief_logit is None:
            return None
        return inv_logit(self._belief_logit)

    @staticmethod
    def book_imbalance(bid_size: Optional[float], ask_size: Optional[float]) -> float:
        """Signed order-book imbalance in [-1, 1]; >0 means bid-heavy (upward pressure)."""
        if not bid_size and not ask_size:
            return 0.0
        b = bid_size or 0.0
        a = ask_size or 0.0
        return safe_div(b - a, b + a, 0.0)
