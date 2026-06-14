"""
The Quoter: the strategy engine's single integration surface.

It owns one stateful estimator set *per market token* (fair value, volatility,
VPIN) and turns a normalized snapshot of market + account state into a concrete
``QuoteDecision``: what bid/ask to rest, at what size, or whether to withdraw -
plus any detected arbitrage and a human-readable rationale for observability.

Pipeline (each layer answers "more PnL or less risk?"):

  fair value  ->  volatility  ->  reservation price + AS/GLFT spread
              ->  inventory limit & sizing  ->  toxicity/resolution risk gating
              ->  reward-band placement  ->  final clamps

The caller (trading.py) supplies a ``MarketSnapshot`` built from the existing
order-book / position plumbing, and receives a ``QuoteDecision`` it executes with
the existing order-sending functions. No exchange calls happen in here, which is
what makes the whole engine unit-testable offline.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional

from poly_strategy import avellaneda, inventory, rewards, risk
from poly_strategy.arbitrage import ArbOpportunity, detect_binary_arb
from poly_strategy.config import StrategyConfig
from poly_strategy.fair_value import FairValueEstimator
from poly_strategy.toxicity import VPINEstimator
from poly_strategy.volatility import VolatilityEstimator


@dataclass
class MarketSnapshot:
    """Normalized inputs the quoter needs for one outcome token."""
    token: str
    best_bid: Optional[float]
    best_ask: Optional[float]
    bid_size: Optional[float] = None
    ask_size: Optional[float] = None
    position: float = 0.0          # signed inventory in tokens (long positive)
    avg_price: float = 0.0
    book_age_s: Optional[float] = None
    hours_to_resolution: Optional[float] = None
    sheet_annual_vol: float = 0.0  # e.g. row['3_hour']
    external_ref: Optional[float] = None
    seconds_per_update: float = 5.0
    # Opposite-outcome best prices for Dutch-book detection (optional).
    other_best_ask: Optional[float] = None
    other_best_bid: Optional[float] = None


@dataclass
class QuoteDecision:
    quote_bid: bool
    quote_ask: bool
    bid_price: Optional[float]
    ask_price: Optional[float]
    bid_size: float
    ask_size: float
    fair_value: float
    reservation_price: float
    sigma_price: float
    vpin: float
    inventory_ratio: float
    spread_multiplier: float
    arb: Optional[ArbOpportunity] = None
    reasons: List[str] = field(default_factory=list)


class _MarketState:
    """Bundle of per-token estimators."""

    def __init__(self, cfg: StrategyConfig):
        self.fair = FairValueEstimator()
        self.vol = VolatilityEstimator(ewma_lambda=cfg.vol_ewma_lambda, floor=cfg.vol_floor)
        self.vpin = VPINEstimator(bucket_size=cfg.vpin_bucket_size, num_buckets=cfg.vpin_num_buckets)
        self.sigma_baseline: Optional[float] = None


class Quoter:
    """Stateful per-token quoting engine. One instance can serve many tokens."""

    def __init__(self, config: Optional[StrategyConfig] = None):
        self.config = config or StrategyConfig()
        self._states: Dict[str, _MarketState] = {}

    def set_config(self, config: StrategyConfig) -> None:
        self.config = config

    def state_for(self, token: str) -> _MarketState:
        st = self._states.get(token)
        if st is None:
            st = _MarketState(self.config)
            self._states[token] = st
        return st

    def on_trade(self, token: str, price: float, volume: float) -> None:
        """Feed a market trade print into the token's VPIN estimator."""
        self.state_for(token).vpin.add_trade(price, volume)

    def compute(self, snap: MarketSnapshot, cfg: Optional[StrategyConfig] = None) -> QuoteDecision:
        """Produce a QuoteDecision for one outcome token."""
        cfg = cfg or self.config
        st = self.state_for(snap.token)

        # --- Arbitrage first: risk-free money beats everything. ---
        arb = detect_binary_arb(
            ask_yes=snap.best_ask,
            ask_no=snap.other_best_ask,
            bid_yes=snap.best_bid,
            bid_no=snap.other_best_bid,
            min_edge=cfg.arb_min_edge,
            fee=cfg.maker_fee,
        )

        # --- 1. Fair value. ---
        fair = st.fair.update(
            snap.best_bid, snap.best_ask, snap.bid_size, snap.ask_size, snap.external_ref
        )
        if fair is None:
            return QuoteDecision(
                quote_bid=False, quote_ask=False, bid_price=None, ask_price=None,
                bid_size=0.0, ask_size=0.0, fair_value=0.0, reservation_price=0.0,
                sigma_price=0.0, vpin=st.vpin.vpin(), inventory_ratio=0.0,
                spread_multiplier=1.0, arb=arb, reasons=["no_fair_value"],
            )

        # --- 2. Volatility. ---
        st.vol.update(fair)
        sigma = st.vol.sigma_horizon_price(
            fair=fair,
            horizon_hours=cfg.horizon_hours,
            seconds_per_update=snap.seconds_per_update,
            sheet_annual_vol=snap.sheet_annual_vol,
            sheet_weight=cfg.sheet_vol_weight,
        )
        if st.sigma_baseline is None:
            st.sigma_baseline = sigma
        else:
            st.sigma_baseline = 0.99 * st.sigma_baseline + 0.01 * sigma

        # --- 3. Inventory limit & ratio. ---
        limit_q = inventory.inventory_limit(cfg.max_loss_usd, fair)
        inv_ratio = inventory.inventory_ratio(snap.position, cfg.target_inventory, limit_q)

        # --- 4. Risk gating (toxicity, resolution, stale book, vol spike, limit). ---
        vpin_val = st.vpin.vpin()
        directive = risk.evaluate_risk(
            book_age_s=snap.book_age_s,
            hours_to_resolution=snap.hours_to_resolution,
            vpin=vpin_val,
            inventory_ratio=inv_ratio,
            sigma_price=sigma,
            sigma_baseline=st.sigma_baseline,
            max_book_age_s=8.0,
            resolution_widen_hours=cfg.resolution_widen_hours,
            resolution_withdraw_hours=cfg.resolution_withdraw_hours,
            vpin_widen_threshold=cfg.vpin_widen_threshold,
            vpin_kill_threshold=cfg.vpin_kill_threshold,
            vpin_widen_gain=cfg.vpin_widen_gain,
        )

        # --- 5. Reservation price + AS/GLFT quotes. ---
        bid_price, ask_price, r = avellaneda.compute_quotes(
            fair=fair,
            inventory_ratio=inv_ratio,
            gamma=cfg.gamma,
            kappa=cfg.kappa,
            sigma_price=sigma,
            min_half_spread=cfg.min_half_spread,
            max_half_spread=cfg.max_half_spread,
            skew_cap=cfg.inventory_skew_cap,
            spread_multiplier=directive.spread_multiplier,
            tick_size=cfg.tick_size,
            min_price=cfg.min_price,
            max_price=cfg.max_price,
        )

        # --- 6. Reward-band placement (only tighten, never break safe spread). ---
        midpoint = fair
        if cfg.reward_max_spread > 0:
            bid_price = rewards.clamp_to_band(
                bid_price, midpoint, cfg.reward_max_spread, "bid",
                band_fraction=cfg.reward_band_fraction, tick_size=cfg.tick_size,
            )
            ask_price = rewards.clamp_to_band(
                ask_price, midpoint, cfg.reward_max_spread, "ask",
                band_fraction=cfg.reward_band_fraction, tick_size=cfg.tick_size,
            )

        # --- 7. Sizing: Kelly on captured edge, capped by capacity to Q. ---
        edge = max(ask_price - r, r - bid_price, cfg.min_half_spread)
        raw_size = inventory.kelly_size(
            edge=edge, fair=fair, base_size=cfg.base_order_size,
            kelly_fraction=cfg.kelly_fraction, max_order_size=cfg.max_order_size,
        )
        min_size = max(cfg.base_order_size * 0.0, 1.0)
        bid_size = inventory.capacity_capped_size(
            raw_size, snap.position, cfg.target_inventory, limit_q, "buy", min_size
        )
        ask_size = inventory.capacity_capped_size(
            min(raw_size, abs(snap.position)) if snap.position > 0 else 0.0,
            snap.position, cfg.target_inventory, limit_q, "sell", min_size,
        )

        quote_bid = directive.quote_bid and bid_size > 0
        # Only sell what we actually hold (no naked shorts in this single-token view;
        # the opposite token is handled as its own snapshot).
        quote_ask = directive.quote_ask and ask_size > 0 and snap.position > 0

        # Two-sided eligibility for max rewards: if config requires it and one side
        # is down for non-risk reasons (no inventory to sell), that's acceptable -
        # we never *add* risk just to be two-sided.

        return QuoteDecision(
            quote_bid=quote_bid,
            quote_ask=quote_ask,
            bid_price=bid_price if quote_bid else None,
            ask_price=ask_price if quote_ask else None,
            bid_size=bid_size if quote_bid else 0.0,
            ask_size=ask_size if quote_ask else 0.0,
            fair_value=fair,
            reservation_price=r,
            sigma_price=sigma,
            vpin=vpin_val,
            inventory_ratio=inv_ratio,
            spread_multiplier=directive.spread_multiplier,
            arb=arb,
            reasons=directive.reasons,
        )
