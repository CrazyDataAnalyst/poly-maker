"""
poly_backtest - simulation core for validating poly_strategy.

The strategy engine (poly_strategy.Quoter) is a pure function of market state, so
the *same* decision code can be driven by historical data (backtest) or a live
read-only feed (forward / paper test). Only the event source differs; the fill
model, PnL ledger, and metrics are shared here. That symmetry is what prevents
backtest-vs-live skew.

Public surface:
    BookUpdate, Trade            - normalized market events
    MakerFillModel               - conservative resting-order fill simulation
    Ledger                       - cash / inventory / PnL accounting
    BacktestRunner               - drives the Quoter over an event stream
    compute_metrics, Metrics     - Sharpe, drawdown, PnL, fill stats
"""

from poly_backtest.events import BookUpdate, Trade
from poly_backtest.fill_model import MakerFillModel
from poly_backtest.ledger import Ledger
from poly_backtest.metrics import Metrics, compute_metrics
from poly_backtest.runner import BacktestRunner, BacktestResult

__all__ = [
    "BookUpdate",
    "Trade",
    "MakerFillModel",
    "Ledger",
    "Metrics",
    "compute_metrics",
    "BacktestRunner",
    "BacktestResult",
]
