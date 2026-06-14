"""
Strategy configuration.

All tunables for the quoting brain live in one immutable dataclass. Defaults are
chosen to be *conservative* (wide spreads, small size, low inventory limits) so
that an operator who flips the engine on without tuning loses slowly rather than
quickly. Parameters are sourced, in priority order, from:

  1. the per-market-type ``Hyperparameters`` sheet (``params`` dict), then
  2. the per-market row (tick size, reward ``max_spread``, ``min_size``), then
  3. the defaults below.

This keeps the engine fully backwards-compatible with the existing Google-Sheets
driven configuration: an operator adds a few new hyperparameter rows to tune the
brain, and everything else keeps working.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional


def _get(params: Dict[str, Any], key: str, default: float) -> float:
    """Fetch a numeric hyperparameter, tolerating blanks/strings from the sheet."""
    if params is None:
        return default
    val = params.get(key, "")
    if val == "" or val is None:
        return default
    try:
        return float(val)
    except (TypeError, ValueError):
        return default


@dataclass(frozen=True)
class StrategyConfig:
    # ----- Avellaneda-Stoikov / GLFT core -----
    # gamma/kappa defaults are tuned so the textbook AS spread lands in a few-cent
    # band for typical prediction-market volatility; see avellaneda.py.
    gamma: float = 2.0            # CARA risk aversion. Higher => more inventory-averse, wider/skewed.
    kappa: float = 30.0           # Order-arrival decay (sensitivity of fill prob to distance from fair).
    horizon_hours: float = 24.0   # Planning horizon (T-t) when market end time is unknown.

    # ----- Spread bounds (in probability / price units) -----
    min_half_spread: float = 0.01   # Never quote tighter than this half-spread (1 cent).
    max_half_spread: float = 0.15   # Cap so a vol spike can't push quotes to absurd prices.

    # ----- Inventory limits -----
    max_loss_usd: float = 200.0     # Max tolerable loss on a single binary outcome -> hard limit Q.
    target_inventory: float = 0.0   # Desired steady-state inventory (tokens). Usually flat.
    inventory_skew_cap: float = 0.08  # Cap on the reservation-price shift from inventory (price units).

    # ----- Position sizing -----
    base_order_size: float = 20.0   # Base quote size (tokens) before adjustments.
    kelly_fraction: float = 0.30    # Fractional-Kelly multiplier on edge-implied size.
    max_order_size: float = 200.0   # Hard cap on any single quote.

    # ----- Volatility estimation -----
    vol_ewma_lambda: float = 0.94   # EWMA persistence for realized log-odds volatility.
    vol_floor: float = 0.02         # Floor on per-horizon log-odds sigma (avoid zero spread).
    sheet_vol_weight: float = 0.5   # Blend weight on the slower sheet (annualized) vol vs realtime.

    # ----- Toxicity / VPIN -----
    vpin_bucket_size: float = 200.0   # Volume (tokens) per VPIN bucket.
    vpin_num_buckets: int = 20        # Buckets averaged for the VPIN estimate.
    vpin_widen_threshold: float = 0.35  # Above this, widen spreads proportionally.
    vpin_kill_threshold: float = 0.60   # Above this, pull quotes on the exposed side.
    vpin_widen_gain: float = 2.0        # How aggressively spread widens with excess VPIN.

    # ----- Liquidity-reward optimization -----
    reward_max_spread: float = 3.0    # Reward band half-width in *cents* (from market 'max_spread').
    reward_band_fraction: float = 0.8  # Quote within this fraction of the band to stay eligible+safe.
    enforce_two_sided: bool = True    # Two-sided quoting earns ~3x rewards; keep both sides eligible.

    # ----- Resolution / staged withdrawal -----
    resolution_widen_hours: float = 6.0   # Begin widening this many hours before resolution.
    resolution_withdraw_hours: float = 1.0  # Fully withdraw this many hours before resolution.

    # ----- Arbitrage -----
    arb_min_edge: float = 0.005   # Min Dutch-book edge (price units) net of costs to act.

    # ----- Price bounds & fees -----
    min_price: float = 0.05       # Don't quote below this (deep-tail adverse selection).
    max_price: float = 0.95       # Don't quote above this.
    tick_size: float = 0.01       # Market tick; overridden per-market.
    maker_fee: float = 0.0        # Maker fee fraction (most Polymarket markets are 0).

    @classmethod
    def from_params(
        cls,
        params: Optional[Dict[str, Any]] = None,
        row: Optional[Dict[str, Any]] = None,
    ) -> "StrategyConfig":
        """Build a config from sheet hyperparameters and a market row.

        Unknown / blank fields fall back to the conservative defaults above.
        """
        params = params or {}
        row = row or {}

        def row_get(key: str, default: float) -> float:
            val = row.get(key, "") if hasattr(row, "get") else default
            if val == "" or val is None:
                return default
            try:
                return float(val)
            except (TypeError, ValueError):
                return default

        d = cls()  # defaults

        # Order sizes live in the per-market sheet columns (trade_size / max_size);
        # allow a Hyperparameters override but fall back to the row, then defaults.
        base_size = _get(params, "base_order_size", row_get("trade_size", d.base_order_size))
        max_size = _get(params, "max_order_size", row_get("max_size", d.max_order_size))

        return cls(
            gamma=_get(params, "gamma", d.gamma),
            kappa=_get(params, "kappa", d.kappa),
            horizon_hours=_get(params, "horizon_hours", d.horizon_hours),
            min_half_spread=_get(params, "min_half_spread", d.min_half_spread),
            max_half_spread=_get(params, "max_half_spread", d.max_half_spread),
            max_loss_usd=_get(params, "max_loss_usd", d.max_loss_usd),
            target_inventory=_get(params, "target_inventory", d.target_inventory),
            inventory_skew_cap=_get(params, "inventory_skew_cap", d.inventory_skew_cap),
            base_order_size=base_size,
            kelly_fraction=_get(params, "kelly_fraction", d.kelly_fraction),
            max_order_size=max_size,
            vol_ewma_lambda=_get(params, "vol_ewma_lambda", d.vol_ewma_lambda),
            vol_floor=_get(params, "vol_floor", d.vol_floor),
            sheet_vol_weight=_get(params, "sheet_vol_weight", d.sheet_vol_weight),
            vpin_bucket_size=_get(params, "vpin_bucket_size", d.vpin_bucket_size),
            vpin_num_buckets=int(_get(params, "vpin_num_buckets", d.vpin_num_buckets)),
            vpin_widen_threshold=_get(params, "vpin_widen_threshold", d.vpin_widen_threshold),
            vpin_kill_threshold=_get(params, "vpin_kill_threshold", d.vpin_kill_threshold),
            vpin_widen_gain=_get(params, "vpin_widen_gain", d.vpin_widen_gain),
            reward_max_spread=row_get("max_spread", _get(params, "reward_max_spread", d.reward_max_spread)),
            reward_band_fraction=_get(params, "reward_band_fraction", d.reward_band_fraction),
            enforce_two_sided=bool(_get(params, "enforce_two_sided", 1.0 if d.enforce_two_sided else 0.0)),
            resolution_widen_hours=_get(params, "resolution_widen_hours", d.resolution_widen_hours),
            resolution_withdraw_hours=_get(params, "resolution_withdraw_hours", d.resolution_withdraw_hours),
            arb_min_edge=_get(params, "arb_min_edge", d.arb_min_edge),
            min_price=_get(params, "min_price", d.min_price),
            max_price=_get(params, "max_price", d.max_price),
            tick_size=row_get("tick_size", _get(params, "tick_size", d.tick_size)),
            maker_fee=_get(params, "maker_fee", d.maker_fee),
        )
