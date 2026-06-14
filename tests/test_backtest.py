"""
Validation suite for poly_backtest.

Protects the accounting and simulation invariants: a backtest is only useful if
the ledger, fill model, and metrics are provably correct on known inputs.

Runnable standalone (python3 tests/test_backtest.py) or via pytest.
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from poly_backtest import BacktestRunner, Ledger, MakerFillModel
from poly_backtest.events import BookUpdate, Trade
from poly_backtest.metrics import compute_metrics, max_drawdown, sharpe
from poly_backtest.data_sources import synthetic_market
from poly_strategy import StrategyConfig


# ------------------------------------------------------------------- ledger

def test_ledger_roundtrip_pnl():
    led = Ledger()
    led.on_fill("T", "buy", 100, 0.50)
    assert led.position("T") == 100
    assert abs(led.cash - (-50.0)) < 1e-9
    led.on_fill("T", "sell", 100, 0.60)
    assert led.position("T") == 0
    # Bought 100@0.5 (-50), sold 100@0.6 (+60) => +10 cash.
    assert abs(led.cash - 10.0) < 1e-9


def test_ledger_avg_cost():
    led = Ledger()
    led.on_fill("T", "buy", 100, 0.40)
    led.on_fill("T", "buy", 100, 0.60)
    assert abs(led.avg_price("T") - 0.50) < 1e-9


def test_ledger_fees():
    led = Ledger(maker_fee=0.01)
    led.on_fill("T", "buy", 100, 0.50)  # notional 50, fee 0.5
    assert abs(led.fees_paid - 0.5) < 1e-9
    assert abs(led.cash - (-50.5)) < 1e-9


def test_ledger_settlement():
    led = Ledger()
    led.on_fill("YES", "buy", 100, 0.40)  # cash -40, pos 100
    led.settle({"YES": 1.0})              # resolves YES => +100
    assert led.position("YES") == 0
    assert abs(led.cash - 60.0) < 1e-9    # -40 + 100


def test_equity_marks_inventory():
    led = Ledger()
    led.on_fill("T", "buy", 100, 0.50)
    assert abs(led.equity({"T": 0.55}) - 5.0) < 1e-9   # -50 cash + 55 MTM
    assert abs(led.equity({"T": 0.45}) - (-5.0)) < 1e-9  # adverse move shows as loss


# ------------------------------------------------------------------- fill model

def test_fill_buy_on_crossing_sell():
    fm = MakerFillModel(participation=1.0)
    # Our bid 0.49; a sell aggressor at 0.49 reaches us -> we buy.
    tr = Trade(0, "T", 0.49, 100, "sell")
    fills = fm.fills_for_trade(tr, resting_bid=(0.49, 50), resting_ask=(0.51, 50))
    assert len(fills) == 1 and fills[0].side == "buy"
    assert fills[0].size == 50  # capped by our resting size


def test_fill_partial_participation():
    fm = MakerFillModel(participation=0.2)
    tr = Trade(0, "T", 0.49, 100, "sell")
    fills = fm.fills_for_trade(tr, resting_bid=(0.49, 50), resting_ask=None)
    assert abs(fills[0].size - 20.0) < 1e-9  # 100 * 0.2


def test_fill_no_cross_no_fill():
    fm = MakerFillModel(participation=1.0)
    # Sell aggressor at 0.50 does not reach our 0.49 bid.
    tr = Trade(0, "T", 0.50, 100, "sell")
    fills = fm.fills_for_trade(tr, resting_bid=(0.49, 50), resting_ask=(0.51, 50))
    assert fills == []


def test_fill_side_inference():
    fm = MakerFillModel(participation=1.0)
    # No side given; price >= mid => buy aggressor -> hits our ask.
    tr = Trade(0, "T", 0.51, 100, None)
    fills = fm.fills_for_trade(tr, resting_bid=(0.49, 50), resting_ask=(0.51, 50),
                               best_bid=0.49, best_ask=0.51)
    assert len(fills) == 1 and fills[0].side == "sell"


# ------------------------------------------------------------------- metrics

def test_max_drawdown_known():
    abs_dd, pct = max_drawdown([10, 8, 12, 6])
    assert abs(abs_dd - 6.0) < 1e-9       # peak 12 -> trough 6
    assert abs(pct - 0.5) < 1e-9


def test_sharpe_zero_mean_is_zero():
    assert abs(sharpe([1, -1, 1, -1], 1.0)) < 1e-9


def test_sharpe_positive_drift():
    s = sharpe([2, 1, 2, 1], 1.0)
    assert s > 0


def test_compute_metrics_shapes():
    m = compute_metrics([0, 1, 2, 3], sample_interval_s=60, num_fills=4,
                        num_buys=3, num_sells=1, turnover=80)
    assert abs(m.total_pnl - 3.0) < 1e-9
    assert m.num_samples == 4
    assert abs(m.fill_imbalance - 0.5) < 1e-9  # (3-1)/4


# ------------------------------------------------------------------- end-to-end

def test_synthetic_backtest_runs_and_is_finite():
    import math
    events = list(synthetic_market(n_steps=2000, seed=7))
    runner = BacktestRunner(
        config=StrategyConfig(gamma=2.0, base_order_size=20, max_order_size=200),
        fill_model=MakerFillModel(participation=0.3),
        sample_interval_s=30.0,
    )
    res = runner.run(events)
    assert len(res.equity_curve) > 2
    assert math.isfinite(res.metrics.total_pnl)
    assert math.isfinite(res.metrics.sharpe_annualized)
    # Engine should have transacted on the synthetic flow.
    assert res.metrics.num_fills > 0


def test_synthetic_backtest_deterministic():
    def run():
        events = list(synthetic_market(n_steps=1500, seed=99))
        r = BacktestRunner(config=StrategyConfig(), fill_model=MakerFillModel(0.3),
                           sample_interval_s=30.0)
        return r.run(events).metrics.total_pnl
    assert abs(run() - run()) < 1e-9


# ------------------------------------------------------------------- runner

def _run_all():
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    passed = failed = 0
    for fn in fns:
        try:
            fn()
            passed += 1
            print(f"  PASS  {fn.__name__}")
        except AssertionError as e:
            failed += 1
            print(f"  FAIL  {fn.__name__}: {e}")
        except Exception as e:  # noqa
            failed += 1
            print(f"  ERROR {fn.__name__}: {type(e).__name__}: {e}")
    print(f"\n{passed} passed, {failed} failed, {len(fns)} total")
    return failed == 0


if __name__ == "__main__":
    sys.exit(0 if _run_all() else 1)
