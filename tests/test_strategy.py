"""
Validation suite for poly_strategy.

We cannot test against the live exchange offline, so we validate the *invariants*
the math must satisfy - the properties that, if violated, mean the engine is
mispricing risk. Each test states the property it protects.

Runnable two ways:
    python3 tests/test_strategy.py      # standalone, no pytest needed
    pytest tests/test_strategy.py       # standard
"""

from __future__ import annotations

import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from poly_strategy import MarketSnapshot, Quoter, StrategyConfig
from poly_strategy import avellaneda, inventory, rewards
from poly_strategy.arbitrage import detect_binary_arb, detect_multi_outcome_arb
from poly_strategy.fair_value import FairValueEstimator
from poly_strategy.math_utils import inv_logit, logit, norm_cdf, prob_to_logit_slope
from poly_strategy.toxicity import VPINEstimator
from poly_strategy.volatility import VolatilityEstimator


# ---------------------------------------------------------------- math_utils

def test_logit_roundtrip():
    for p in [0.01, 0.1, 0.37, 0.5, 0.63, 0.9, 0.99]:
        assert abs(inv_logit(logit(p)) - p) < 1e-9, p


def test_inv_logit_bounded_and_monotone():
    # Bounded in [0,1] even at extreme inputs; monotone increasing; strictly
    # inside (0,1) for moderate inputs (extreme inputs round to 0/1 in float64).
    assert 0.0 <= inv_logit(-1000) < inv_logit(1000) <= 1.0
    assert 0.0 < inv_logit(-20) < 0.5 < inv_logit(20) < 1.0


def test_sigmoid_slope_peaks_at_half():
    assert abs(prob_to_logit_slope(0.5) - 0.25) < 1e-9
    assert prob_to_logit_slope(0.5) > prob_to_logit_slope(0.1)
    assert prob_to_logit_slope(0.1) > prob_to_logit_slope(0.01)


def test_norm_cdf_known_values():
    assert abs(norm_cdf(0.0) - 0.5) < 1e-9
    assert abs(norm_cdf(1.96) - 0.975) < 1e-3


# ---------------------------------------------------------------- fair value

def test_microprice_leans_to_thin_side():
    fe = FairValueEstimator
    # Bid much larger than ask => price should be pulled toward the ask (up).
    mp = fe.micro_price(0.49, 0.51, bid_size=1000, ask_size=10)
    assert mp > 0.50, mp
    # Symmetric sizes => mid.
    mp2 = fe.micro_price(0.49, 0.51, bid_size=100, ask_size=100)
    assert abs(mp2 - 0.50) < 1e-9


def test_fair_value_stays_bounded():
    fe = FairValueEstimator()
    for _ in range(50):
        f = fe.update(0.97, 0.99, 100, 100)
    assert 0.0 < f < 1.0


def test_fair_value_one_sided_book_uses_prior():
    fe = FairValueEstimator()
    fe.update(0.40, 0.42, 100, 100)
    f = fe.update(None, None)  # empty book
    assert f is not None and 0.0 < f < 1.0


# ---------------------------------------------------------------- volatility

def test_volatility_increases_with_jumps():
    calm = VolatilityEstimator()
    for p in [0.50, 0.501, 0.499, 0.50, 0.501]:
        calm.update(p)
    wild = VolatilityEstimator()
    for p in [0.50, 0.60, 0.45, 0.65, 0.40]:
        wild.update(p)
    assert wild.sigma_logit_per_update() > calm.sigma_logit_per_update()


def test_sigma_horizon_floored_and_positive():
    ve = VolatilityEstimator(floor=0.02)
    ve.update(0.5)
    s = ve.sigma_horizon_price(0.5, horizon_hours=24, sheet_annual_vol=0.0)
    assert s >= 0.02


# ---------------------------------------------------------------- avellaneda

def test_reservation_price_skews_against_inventory():
    fair = 0.50
    # Long inventory => reservation below fair (want to sell).
    r_long = avellaneda.reservation_price(fair, 0.8, gamma=2.0, sigma_price=0.05, skew_cap=0.1)
    # Short inventory => reservation above fair (want to buy).
    r_short = avellaneda.reservation_price(fair, -0.8, gamma=2.0, sigma_price=0.05, skew_cap=0.1)
    assert r_long < fair < r_short


def test_reservation_shift_capped():
    fair = 0.50
    r = avellaneda.reservation_price(fair, 1.0, gamma=100.0, sigma_price=0.5, skew_cap=0.05)
    assert abs(fair - r) <= 0.05 + 1e-9


def test_half_spread_increases_with_vol():
    lo = avellaneda.as_half_spread(2.0, 0.02, 30.0)
    hi = avellaneda.as_half_spread(2.0, 0.10, 30.0)
    assert hi > lo


def test_compute_quotes_ordered_and_bounded():
    bid, ask, r = avellaneda.compute_quotes(
        fair=0.5, inventory_ratio=0.0, gamma=2.0, kappa=30.0, sigma_price=0.05,
        min_half_spread=0.01, max_half_spread=0.15, skew_cap=0.08,
        tick_size=0.01, min_price=0.05, max_price=0.95,
    )
    assert 0.05 <= bid < ask <= 0.95
    assert abs(r - 0.5) < 1e-9


def test_inventory_widen_exposed_side():
    # Long heavy: bid (buying more) should widen vs ask.
    bid_w = avellaneda.glft_inventory_widen(0.9, "bid")
    ask_w = avellaneda.glft_inventory_widen(0.9, "ask")
    assert bid_w > ask_w == 1.0


# ---------------------------------------------------------------- inventory

def test_inventory_limit_smaller_for_lopsided():
    q_mid = inventory.inventory_limit(200.0, 0.50)
    q_edge = inventory.inventory_limit(200.0, 0.90)
    assert q_edge < q_mid  # 0.9 contract can lose more per token => hold fewer


def test_capacity_capped_size_zero_at_limit():
    q = 100.0
    # Already long at the limit: no further buying.
    size = inventory.capacity_capped_size(50, position=100, target=0, limit_q=q, side="buy", min_size=1)
    assert size == 0.0
    # Room to sell.
    size2 = inventory.capacity_capped_size(50, position=100, target=0, limit_q=q, side="sell", min_size=1)
    assert size2 > 0.0


def test_kelly_size_grows_with_edge():
    small = inventory.kelly_size(0.01, 0.5, base_size=20, kelly_fraction=0.3, max_order_size=200)
    big = inventory.kelly_size(0.08, 0.5, base_size=20, kelly_fraction=0.3, max_order_size=200)
    assert big > small
    assert big <= 200


# ---------------------------------------------------------------- toxicity

def test_vpin_low_for_balanced_flow():
    v = VPINEstimator(bucket_size=100, num_buckets=10)
    # Perfectly balanced buy/sell volume => VPIN ~ 0.
    for _ in range(2000):
        v.add_signed_volume(1.0, 1.0)
    assert v.vpin() < 0.05


def test_vpin_high_for_one_sided_flow():
    v = VPINEstimator(bucket_size=100, num_buckets=10)
    for _ in range(2000):
        v.add_signed_volume(1.0, 0.0)  # all buys
    assert v.vpin() > 0.9


def test_vpin_bounded():
    v = VPINEstimator(bucket_size=50, num_buckets=5)
    for i in range(1000):
        v.add_trade(price=0.5 + 0.001 * math.sin(i), volume=3.0)
    assert 0.0 <= v.vpin() <= 1.0


# ---------------------------------------------------------------- arbitrage

def test_dutch_book_buy_pair():
    opp = detect_binary_arb(ask_yes=0.45, ask_no=0.50, bid_yes=0.44, bid_no=0.49, min_edge=0.005)
    assert opp is not None and opp.kind == "buy_pair"
    assert abs(opp.edge - 0.05) < 1e-9


def test_dutch_book_sell_pair():
    opp = detect_binary_arb(ask_yes=0.60, ask_no=0.55, bid_yes=0.58, bid_no=0.50, min_edge=0.005)
    assert opp is not None and opp.kind == "sell_pair"
    assert abs(opp.edge - 0.08) < 1e-9


def test_no_arb_when_consistent():
    opp = detect_binary_arb(ask_yes=0.51, ask_no=0.50, bid_yes=0.50, bid_no=0.49, min_edge=0.005)
    assert opp is None


def test_multi_outcome_arb():
    opp = detect_multi_outcome_arb([0.30, 0.30, 0.30], min_edge=0.005)
    assert opp is not None and abs(opp.edge - 0.10) < 1e-9
    assert detect_multi_outcome_arb([0.40, 0.35, 0.30]) is None


# ---------------------------------------------------------------- rewards

def test_reward_score_max_at_mid_zero_outside():
    v = 3.0  # cents
    assert rewards.reward_score(0.50, 0.50, v) > rewards.reward_score(0.51, 0.50, v) > 0
    assert rewards.reward_score(0.60, 0.50, v) == 0.0  # outside band


def test_clamp_to_band_pulls_inward_not_across_mid():
    # An ask way outside the band gets pulled to within band_fraction*v of mid.
    ask = rewards.clamp_to_band(0.70, midpoint=0.50, max_spread_cents=3.0, side="ask",
                                band_fraction=0.8, tick_size=0.01)
    assert 0.50 < ask <= 0.50 + 0.8 * 0.03 + 1e-9
    bid = rewards.clamp_to_band(0.20, midpoint=0.50, max_spread_cents=3.0, side="bid",
                                band_fraction=0.8, tick_size=0.01)
    assert 0.50 - 0.8 * 0.03 - 1e-9 <= bid < 0.50


# ---------------------------------------------------------------- quoter (integration)

def _warm_snapshot(position=0.0, **kw):
    base = dict(
        token="T", best_bid=0.49, best_ask=0.51, bid_size=500, ask_size=500,
        position=position, avg_price=0.50, book_age_s=1.0, hours_to_resolution=48.0,
        sheet_annual_vol=2.0, seconds_per_update=5.0,
        other_best_ask=0.52, other_best_bid=0.48,
    )
    base.update(kw)
    return MarketSnapshot(**base)


def test_quoter_basic_two_sided_when_flat_with_inventory_to_sell():
    q = Quoter(StrategyConfig())
    # Need position>0 to be allowed to sell in the single-token view.
    for _ in range(5):
        d = q.compute(_warm_snapshot(position=40.0))
    assert d.bid_price is not None and 0.05 <= d.bid_price < d.fair_value
    assert d.ask_price is not None and d.fair_value < d.ask_price <= 0.95
    assert d.bid_size > 0 and d.ask_size > 0


def test_quoter_withdraws_near_resolution():
    q = Quoter(StrategyConfig())
    d = q.compute(_warm_snapshot(position=40.0, hours_to_resolution=0.5))
    assert d.quote_bid is False and d.quote_ask is False
    assert any("resolution" in r for r in d.reasons)


def test_quoter_withdraws_on_stale_book():
    q = Quoter(StrategyConfig())
    d = q.compute(_warm_snapshot(position=40.0, book_age_s=60.0))
    assert d.quote_bid is False and d.quote_ask is False
    assert any("stale" in r for r in d.reasons)


def test_quoter_kills_on_toxicity():
    # Small VPIN buckets so the window warms quickly under test.
    q = Quoter(StrategyConfig(vpin_bucket_size=50.0, vpin_num_buckets=10))
    # Sustained one-directional drift = informed buying => BVC classifies as
    # heavily buy-side => high VPIN.
    for i in range(2000):
        q.on_trade("T", price=0.50 + 0.0002 * i, volume=5.0)
    d = q.compute(_warm_snapshot(position=40.0))
    assert d.vpin > 0.5, d.vpin
    assert d.quote_bid is False and d.quote_ask is False


def test_quoter_long_inventory_skews_reservation_down():
    q = Quoter(StrategyConfig())
    for _ in range(5):
        flat = q.compute(_warm_snapshot(position=1.0))
    q2 = Quoter(StrategyConfig())
    for _ in range(5):
        longd = q2.compute(_warm_snapshot(position=500.0))
    assert longd.reservation_price < flat.reservation_price


def test_quoter_stops_buying_at_inventory_limit():
    cfg = StrategyConfig(max_loss_usd=50.0)  # small Q
    q = Quoter(cfg)
    # Huge long position relative to Q => bid should be withdrawn.
    for _ in range(5):
        d = q.compute(_warm_snapshot(position=100000.0))
    assert d.quote_bid is False
    assert "long_limit" in d.reasons


def test_quoter_detects_arb_in_decision():
    q = Quoter(StrategyConfig())
    snap = _warm_snapshot(position=40.0, best_ask=0.45, other_best_ask=0.50)
    d = q.compute(snap)
    assert d.arb is not None and d.arb.kind == "buy_pair"


# ---------------------------------------------------------------- runner

def _run_all():
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    passed = 0
    failed = 0
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
    ok = _run_all()
    sys.exit(0 if ok else 1)
