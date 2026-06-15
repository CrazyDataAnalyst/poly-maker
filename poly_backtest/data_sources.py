"""
Event sources for the backtester.

Two built-ins:

  * ``synthetic_market`` - a self-contained generator (logit random walk + book +
    Poisson trade flow, optionally with informed/toxic bursts). Lets you run a
    real backtest with zero external data and is used by the tests.

  * ``csv_events`` - a generic CSV adapter with a configurable column map, so it
    adapts to the schema of an external historical dataset such as
    https://github.com/warproxxx/poly_data without code changes.

Sources yield time-ordered ``BookUpdate`` / ``Trade`` events. ``merge_sources``
interleaves several token/file streams by timestamp.
"""

from __future__ import annotations

import csv
import heapq
import math
import random
from typing import Dict, Iterable, Iterator, List, Optional

from poly_backtest.events import BookUpdate, Trade
from poly_strategy.math_utils import clamp_prob, inv_logit, logit


# --------------------------------------------------------------------- synthetic

def synthetic_market(
    token: str = "YES",
    n_steps: int = 5000,
    start_prob: float = 0.5,
    vol_logit: float = 0.01,
    spread: float = 0.02,
    book_size: float = 500.0,
    trades_per_step: float = 0.8,
    dt_s: float = 2.0,
    toxic_burst_prob: float = 0.02,
    seed: Optional[int] = 42,
) -> Iterator:
    """Yield a synthetic stream of BookUpdate/Trade events for one token.

    A latent fair value follows a logit-space random walk. Each step emits a book
    around it and a Poisson number of trades. With probability ``toxic_burst_prob``
    a step becomes an *informed burst*: fair value jumps and trades are one-sided
    in the jump direction - exactly the adverse-selection scenario the engine's
    VPIN defense is meant to survive.
    """
    rng = random.Random(seed)
    x = logit(clamp_prob(start_prob))
    ts = 0.0

    for _ in range(n_steps):
        toxic = rng.random() < toxic_burst_prob
        if toxic:
            jump = rng.choice([-1.0, 1.0]) * vol_logit * rng.uniform(8.0, 20.0)
            x += jump
        else:
            x += rng.gauss(0.0, vol_logit)

        fair = inv_logit(x)
        half = spread / 2.0
        best_bid = clamp_prob(fair - half)
        best_ask = clamp_prob(fair + half)
        bid_sz = book_size * rng.uniform(0.5, 1.5)
        ask_sz = book_size * rng.uniform(0.5, 1.5)

        yield BookUpdate(ts, token, round(best_bid, 3), round(best_ask, 3), bid_sz, ask_sz)

        n_trades = _poisson(rng, trades_per_step)
        for _ in range(n_trades):
            if toxic:
                side = "buy" if jump > 0 else "sell"
            else:
                side = rng.choice(["buy", "sell"])
            # Aggressors cross the relevant side; size is modest vs. book.
            price = best_ask if side == "buy" else best_bid
            size = book_size * rng.uniform(0.05, 0.4)
            yield Trade(ts + dt_s * 0.5, token, round(price, 3), size, side)

        ts += dt_s


def _poisson(rng: random.Random, lam: float) -> int:
    """Knuth's Poisson sampler (small lambda)."""
    if lam <= 0:
        return 0
    l = math.exp(-lam)
    k = 0
    p = 1.0
    while True:
        k += 1
        p *= rng.random()
        if p <= l:
            return k - 1


# --------------------------------------------------------------------------- CSV

# Default column names; override via ``column_map`` to match your dataset.
DEFAULT_TRADE_COLS = {"ts": "timestamp", "token": "token_id", "price": "price",
                      "size": "size", "side": "side"}
DEFAULT_BOOK_COLS = {"ts": "timestamp", "token": "token_id", "bid": "best_bid",
                     "ask": "best_ask", "bid_size": "bid_size", "ask_size": "ask_size"}


def _parse_ts(raw: str) -> float:
    """Parse a timestamp that may be epoch seconds, epoch millis, or ISO-8601."""
    s = str(raw).strip()
    try:
        v = float(s)
        return v / 1000.0 if v > 1e12 else v  # millis -> seconds
    except ValueError:
        pass
    # Fall back to ISO via the stdlib (avoid a pandas dependency here).
    from datetime import datetime
    return datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp()


def csv_events(
    path: str,
    kind: str,                         # 'trades' | 'book'
    column_map: Optional[Dict[str, str]] = None,
    token_override: Optional[str] = None,
) -> Iterator:
    """Yield events from a CSV file. ``kind`` selects the parser/column defaults.

    Map your dataset's columns via ``column_map``; e.g. for a trades file whose
    columns are ``t, asset, p, q, taker_side``::

        csv_events("trades.csv", "trades",
                   {"ts": "t", "token": "asset", "price": "p",
                    "size": "q", "side": "taker_side"})
    """
    if kind == "trades":
        cols = {**DEFAULT_TRADE_COLS, **(column_map or {})}
    elif kind == "book":
        cols = {**DEFAULT_BOOK_COLS, **(column_map or {})}
    else:
        raise ValueError("kind must be 'trades' or 'book'")

    with open(path, newline="") as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            ts = _parse_ts(row[cols["ts"]])
            token = token_override or str(row[cols["token"]])
            if kind == "trades":
                side = row.get(cols["side"], "") or None
                if side:
                    side = side.strip().lower()
                    side = "buy" if side in ("buy", "b", "bid", "taker_buy") else \
                           ("sell" if side in ("sell", "s", "ask", "taker_sell") else None)
                yield Trade(ts, token, float(row[cols["price"]]), float(row[cols["size"]]), side)
            else:
                def _f(key):
                    v = row.get(cols.get(key, ""), "")
                    return float(v) if v not in ("", None) else None
                yield BookUpdate(ts, token, _f("bid"), _f("ask"), _f("bid_size"), _f("ask_size"))


def merge_sources(*sources: Iterable) -> Iterator:
    """Merge several time-ordered event streams into one, ordered by ``ts``."""
    return heapq.merge(*sources, key=lambda e: e.ts)
