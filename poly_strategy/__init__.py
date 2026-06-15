"""
poly_strategy - the quantitative quoting brain for the Polymarket maker.

A self-contained, dependency-light (stdlib ``math`` only) strategy engine that
turns a normalized market/account snapshot into inventory-aware, toxicity-defended,
reward-optimized two-sided quotes built on the Avellaneda-Stoikov / GLFT
framework adapted for binary, bounded prediction markets.

Public surface:
    Quoter, MarketSnapshot, QuoteDecision  - the orchestrator and its I/O
    StrategyConfig                          - all tunables, from sheet params
"""

from poly_strategy.config import StrategyConfig
from poly_strategy.quoter import MarketSnapshot, QuoteDecision, Quoter

__all__ = ["StrategyConfig", "Quoter", "MarketSnapshot", "QuoteDecision"]
