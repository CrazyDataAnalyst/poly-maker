"""
Bridge between the live data/order plumbing and the poly_strategy engine.

This adapter is the *only* place the legacy stack touches the strategy brain. It:
  * owns a single process-wide ``Quoter`` (per-token estimator state lives inside),
  * decides whether the engine is enabled for a given market param-type,
  * builds a normalized ``MarketSnapshot`` from the existing order-book deets,
  * feeds market order-flow into the VPIN toxicity estimator.

Keeping this in one small module means the engine can be enabled/disabled per
param-type from the Google Sheet (``use_strategy_engine = 1``) with zero risk to
the legacy code path when it is off.
"""

from __future__ import annotations

import time
from typing import Any, Dict, Optional

import pandas as pd

from poly_strategy import MarketSnapshot, Quoter, StrategyConfig
from poly_stats.pnl_attribution import PnLAttribution

# Process-wide engine. Estimator state (fair value, vol, VPIN) is keyed by token
# inside the Quoter, so a single instance serves every market.
ENGINE = Quoter()

# Realized-PnL attribution (spread / rebates / rewards), process-wide.
ATTRIBUTOR = PnLAttribution()

# Last time we received a book update for each token (for staleness checks).
_last_book_ts: Dict[str, float] = {}

# Last reservation/fair the engine produced per token, for fill attribution.
_last_reservation: Dict[str, float] = {}


def is_enabled(params: Optional[Dict[str, Any]]) -> bool:
    """True if the strategy engine is on for this param-type (now the default).

    The engine is the only quoting path in v2; this remains as an explicit
    off-switch (set ``use_strategy_engine = 0`` to disable quoting a param-type).
    """
    if not params:
        return True
    val = params.get("use_strategy_engine", 1)
    if val == "" or val is None:
        return True
    try:
        return float(val) >= 1.0
    except (TypeError, ValueError):
        return str(val).strip().lower() in ("true", "yes", "on")


def note_decision(token: str, decision) -> None:
    """Stash the engine's reservation price so fills can be attributed to spread."""
    _last_reservation[str(token)] = float(decision.reservation_price)


def record_fill(token: str, side: str, size: float, price: float,
                is_maker: bool = True, rebate_rate: float = 0.0) -> None:
    """Record a confirmed fill into the PnL attributor (spread + rebates)."""
    reservation = _last_reservation.get(str(token), float(price))
    if rebate_rate and ATTRIBUTOR.rebate_rate != rebate_rate:
        ATTRIBUTOR.rebate_rate = rebate_rate
    try:
        ATTRIBUTOR.record_fill(side, float(size), float(price), reservation, is_maker)
    except Exception:
        pass


def pnl_summary() -> str:
    """Human-readable PnL attribution line (spread / rebates / rewards)."""
    return ATTRIBUTOR.summary_str()


def build_config(params: Optional[Dict[str, Any]], row: Any) -> StrategyConfig:
    """Construct a per-market StrategyConfig from sheet hyperparameters + row."""
    row_dict = row.to_dict() if hasattr(row, "to_dict") else dict(row or {})
    return StrategyConfig.from_params(params, row_dict)


def mark_book_update(token: str) -> None:
    """Record that a fresh book update arrived for ``token`` (staleness clock)."""
    _last_book_ts[str(token)] = time.time()


def book_age_s(token: str) -> Optional[float]:
    """Seconds since the last book update for ``token`` (None if never seen)."""
    ts = _last_book_ts.get(str(token))
    if ts is None:
        return None
    return time.time() - ts


def feed_flow(token: str, buy_volume: float, sell_volume: float) -> None:
    """Feed signed executed volume into the token's VPIN estimator.

    Driven by order-book consumption deltas (see data_processing): when resting
    size at the best bid disappears it was almost certainly *sold into* (sell
    flow); size vanishing at the best ask is buy flow. This is an order-flow proxy
    for true trade prints, which the market websocket in this repo does not expose.
    """
    if buy_volume <= 0 and sell_volume <= 0:
        return
    ENGINE.state_for(str(token)).vpin.add_signed_volume(buy_volume, sell_volume)


def _hours_to_resolution(row_dict: Dict[str, Any]) -> Optional[float]:
    """Hours until market resolution, if an end date is present in the row."""
    end = row_dict.get("end_date_iso") or row_dict.get("end_date")
    if not end:
        return None
    try:
        end_ts = pd.to_datetime(end, utc=True)
        now = pd.Timestamp.utcnow()
        delta_h = (end_ts - now).total_seconds() / 3600.0
        return max(delta_h, 0.0)
    except Exception:
        return None


def build_snapshot(
    token: str,
    deets: Dict[str, Any],
    position: float,
    avg_price: float,
    row_dict: Dict[str, Any],
    seconds_per_update: float = 5.0,
    other_best_ask: Optional[float] = None,
    other_best_bid: Optional[float] = None,
) -> MarketSnapshot:
    """Translate order-book deets + position into a MarketSnapshot.

    ``other_best_ask`` / ``other_best_bid`` are the *opposite* outcome token's real
    best prices, used for cross-token Dutch-book arbitrage detection. Pass None
    when the opposite book is unavailable so the detector cannot false-fire.
    """
    # Use the 3-hour annualized vol from the sheet as the slow volatility prior.
    sheet_vol = 0.0
    for col in ("3_hour", "6_hour", "1_hour", "24_hour"):
        v = row_dict.get(col, "")
        try:
            if v != "" and v is not None and float(v) > 0:
                sheet_vol = float(v)
                break
        except (TypeError, ValueError):
            continue

    return MarketSnapshot(
        token=str(token),
        best_bid=deets.get("best_bid"),
        best_ask=deets.get("best_ask"),
        bid_size=deets.get("best_bid_size"),
        ask_size=deets.get("best_ask_size"),
        position=float(position),
        avg_price=float(avg_price),
        book_age_s=book_age_s(token),
        hours_to_resolution=_hours_to_resolution(row_dict),
        sheet_annual_vol=sheet_vol,
        seconds_per_update=seconds_per_update,
        other_best_ask=other_best_ask,
        other_best_bid=other_best_bid,
    )


def compute(token: str, snapshot: MarketSnapshot, cfg: StrategyConfig):
    """Run the engine for one token. Returns a QuoteDecision."""
    return ENGINE.compute(snapshot, cfg)
