"""
Realized-PnL attribution: split earnings into spread / rebates / rewards.

This is the dashboard that tells you which income stream is actually paying, so
you can manage the business (Phase 4 of the v2 transition). Three streams:

  * **Spread capture** - for each maker fill, the edge of the fill price against
    the engine's reservation price *at the time of the fill*. Buying below the
    reservation or selling above it is positive edge; getting picked off (filled
    on the wrong side of a move) shows up as negative edge.
  * **Maker rebates** - maker notional volume x rebate rate. Polymarket
    redistributes taker fees to makers; the rate is venue/market specific.
  * **Liquidity rewards** - accrued separately (from the rewards API / sheet) and
    added via ``add_rewards``. Kept distinct because it is paid for *resting*, not
    for trading.

Pure and dependency-free so it is unit-testable offline.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict


@dataclass
class PnLAttribution:
    rebate_rate: float = 0.0      # fraction of maker notional rebated
    spread_pnl: float = 0.0       # signed edge captured vs reservation price
    rebates: float = 0.0          # maker_volume_notional * rebate_rate
    rewards: float = 0.0          # externally accrued liquidity rewards
    maker_volume: float = 0.0     # notional traded as maker
    num_fills: int = 0

    def record_fill(self, side: str, size: float, price: float,
                    reservation: float, is_maker: bool = True) -> None:
        """Attribute one fill. ``side`` is 'buy'/'sell' (case-insensitive)."""
        if size <= 0 or price <= 0:
            return
        s = side.lower()
        # Edge vs reservation: bought cheap (buy) or sold rich (sell) => positive.
        if s == "buy":
            edge = reservation - price
        else:
            edge = price - reservation
        self.spread_pnl += edge * size
        self.num_fills += 1
        if is_maker:
            notional = size * price
            self.maker_volume += notional
            self.rebates += notional * self.rebate_rate

    def add_rewards(self, amount: float) -> None:
        self.rewards += amount

    @property
    def total(self) -> float:
        return self.spread_pnl + self.rebates + self.rewards

    def summary(self) -> Dict[str, float]:
        return {
            "spread_pnl": self.spread_pnl,
            "rebates": self.rebates,
            "rewards": self.rewards,
            "total": self.total,
            "maker_volume": self.maker_volume,
            "num_fills": float(self.num_fills),
        }

    def summary_str(self) -> str:
        s = self.summary()
        return (
            f"PnL attribution: total={s['total']:.2f}  "
            f"spread={s['spread_pnl']:.2f}  rebates={s['rebates']:.2f}  "
            f"rewards={s['rewards']:.2f}  maker_vol={s['maker_volume']:.0f}  "
            f"fills={int(s['num_fills'])}"
        )
