"""
Performance metrics.

Computed from a sampled equity curve (equity marked on a fixed wall-clock
interval). Sharpe is reported two ways:

  * **per-sample** - mean / std of per-period PnL increments, unitless;
  * **annualized** - per-sample Sharpe * sqrt(periods_per_year), where
    periods_per_year = seconds_per_year / sample_interval_s.

Market-making PnL increments are autocorrelated and fat-tailed, so a high
annualized Sharpe from short sampling intervals overstates true risk-adjusted
return. Always report the sampling interval alongside the number, and prefer
longer intervals (e.g. 1-5 min) for the headline figure.
"""

from __future__ import annotations

import math
import statistics
from dataclasses import dataclass
from typing import List

_SECONDS_PER_YEAR = 365.0 * 24.0 * 3600.0


@dataclass
class Metrics:
    total_pnl: float
    sharpe_per_sample: float
    sharpe_annualized: float
    sortino_annualized: float
    max_drawdown: float          # absolute, in currency
    max_drawdown_pct: float      # fraction of running peak
    num_samples: int
    num_fills: int
    fill_imbalance: float        # (buys - sells) / (buys + sells)
    turnover: float              # total tokens traded
    final_equity: float
    sample_interval_s: float

    def summary(self) -> str:
        return (
            f"PnL={self.total_pnl:.2f}  "
            f"Sharpe(annual)={self.sharpe_annualized:.2f}  "
            f"Sharpe(/sample)={self.sharpe_per_sample:.3f}  "
            f"Sortino(annual)={self.sortino_annualized:.2f}  "
            f"MaxDD={self.max_drawdown:.2f} ({self.max_drawdown_pct*100:.1f}%)  "
            f"fills={self.num_fills}  turnover={self.turnover:.0f}  "
            f"samples={self.num_samples}@{self.sample_interval_s:.0f}s"
        )


def _increments(equity_curve: List[float]) -> List[float]:
    return [equity_curve[i] - equity_curve[i - 1] for i in range(1, len(equity_curve))]


def max_drawdown(equity_curve: List[float], capital_base: float = 0.0):
    """Return (absolute_dd, pct_dd) of the worst peak-to-trough decline.

    ``pct_dd`` is taken relative to max(running peak, capital_base) so it stays
    meaningful for a market maker whose equity starts near zero cash (without a
    capital base the percentage explodes when the peak crosses zero).
    """
    peak = equity_curve[0] if equity_curve else 0.0
    max_abs = 0.0
    max_pct = 0.0
    for eq in equity_curve:
        if eq > peak:
            peak = eq
        dd = peak - eq
        if dd > max_abs:
            max_abs = dd
        denom = max(abs(peak), capital_base, 1e-9)
        pct = dd / denom
        if pct > max_pct:
            max_pct = pct
    return max_abs, max_pct


def sharpe(increments: List[float], periods_per_year: float) -> float:
    if len(increments) < 2:
        return 0.0
    sd = statistics.stdev(increments)
    if sd <= 1e-12:
        return 0.0
    return (statistics.mean(increments) / sd) * math.sqrt(periods_per_year)


def sortino(increments: List[float], periods_per_year: float) -> float:
    if len(increments) < 2:
        return 0.0
    downside = [min(x, 0.0) for x in increments]
    dd = math.sqrt(statistics.mean(x * x for x in downside))
    if dd <= 1e-12:
        return 0.0
    return (statistics.mean(increments) / dd) * math.sqrt(periods_per_year)


def compute_metrics(
    equity_curve: List[float],
    sample_interval_s: float,
    num_fills: int,
    num_buys: int,
    num_sells: int,
    turnover: float,
    capital_base: float = 0.0,
) -> Metrics:
    incs = _increments(equity_curve)
    ppy = _SECONDS_PER_YEAR / max(sample_interval_s, 1e-6)
    abs_dd, pct_dd = max_drawdown(equity_curve, capital_base) if equity_curve else (0.0, 0.0)
    total = (equity_curve[-1] - equity_curve[0]) if len(equity_curve) >= 2 else 0.0
    total_fills = num_buys + num_sells
    imbalance = (num_buys - num_sells) / total_fills if total_fills > 0 else 0.0

    return Metrics(
        total_pnl=total,
        sharpe_per_sample=sharpe(incs, 1.0),
        sharpe_annualized=sharpe(incs, ppy),
        sortino_annualized=sortino(incs, ppy),
        max_drawdown=abs_dd,
        max_drawdown_pct=pct_dd,
        num_samples=len(equity_curve),
        num_fills=num_fills,
        fill_imbalance=imbalance,
        turnover=turnover,
        final_equity=equity_curve[-1] if equity_curve else 0.0,
        sample_interval_s=sample_interval_s,
    )
