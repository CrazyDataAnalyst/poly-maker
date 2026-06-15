"""
poly_nautilus - Nautilus Trader integration for poly_strategy.

Provides a single Nautilus ``Strategy`` (wrapping poly_strategy.Quoter) that runs
identically in backtest (real Polymarket historical data) and live/forward
trading (Polymarket data + execution adapter).

Submodules import ``nautilus_trader`` (an optional dependency), so they are NOT
imported here at package load. Import what you need explicitly, e.g.::

    from poly_nautilus.strategy import PolymakerNautilusStrategy, PolymakerNautilusConfig

Install the dependency with::

    uv pip install "nautilus_trader[polymarket]"

See NAUTILUS.md for setup, credentials, and run instructions.
"""

__all__ = []
