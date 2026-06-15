# Nautilus Trader Integration (real-data backtest + live/forward)

[Nautilus Trader](https://github.com/nautechsystems/nautilus_trader) is a
production-grade trading platform whose key property for us is that it runs the
**same `Strategy` object in backtest and live**, on **real Polymarket order-book
data** through its first-class Polymarket adapter. `poly_nautilus/` wraps our
`poly_strategy.Quoter` in one Nautilus `Strategy` so it powers both.

```
                         ┌────────────────────────────────────────┐
 real Polymarket data ──▶│  PolymakerNautilusStrategy (Nautilus)   │──▶ post-only LIMIT orders
 (book / trades)         │   book/trade events → MarketSnapshot     │
                         │   → poly_strategy.Quoter.compute()       │
                         │   → QuoteDecision → reconcile orders     │
                         └────────────────────────────────────────┘
   backtest.py: BacktestEngine + PolymarketDataLoader (historical)
   live.py:     TradingNode + Polymarket data/exec clients (live or paper)
```

Because the decision + execution code is shared, backtest and live results are
directly comparable — the whole point of using Nautilus over a bespoke harness.

## Why this complements (not replaces) `poly_backtest`

- `poly_backtest/` — zero-dependency, instant, great for unit-level validation and
  parameter sweeps on synthetic or CSV data.
- `poly_nautilus/` — heavyweight but venue-accurate: real fills, the actual
  Polymarket fee model (incl. maker rebates), live execution, and identical
  backtest/live code. Use it for the **final** validation before risking capital.

## Install — in a SEPARATE venv (required)

Nautilus **cannot** be installed into the main bot's environment. Its Polymarket
adapter pins a `py-clob-client` range that conflicts with this bot's
`py-clob-client==0.28.0` (used by the live `PolymarketClient`), and it requires
Python **>=3.12** while the bot supports >=3.9.10. Trying `uv sync --extra ...`
fails with an unsatisfiable resolution for exactly these reasons.

Use a dedicated venv instead:

```bash
# from the repo root
uv venv --python 3.12 .venv-nautilus
uv pip install --python .venv-nautilus -r requirements-nautilus.txt
```

Then run the integration with that interpreter (not `uv run`, which uses the main
venv):

```bash
# macOS / Linux
.venv-nautilus/bin/python -m poly_nautilus.backtest --market-slug <slug> ...
# Windows
.venv-nautilus\Scripts\python -m poly_nautilus.backtest --market-slug <slug> ...
```

`poly_nautilus` only imports `poly_strategy` (pure stdlib) and pandas (a Nautilus
dependency), so running from the repo root is enough — the main bot does not need
to be installed into this venv. The rest of the bot (and `poly_backtest`) runs in
the main venv, completely independent of Nautilus.

## Credentials (live only — backtest needs none)

Set these environment variables (per the adapter docs):

```bash
export POLYMARKET_PK=...          # private key for signing
export POLYMARKET_FUNDER=...      # USDC funding wallet (public address)
export POLYMARKET_API_KEY=...     # CLOB API key (L2 auth)
export POLYMARKET_API_SECRET=...
export POLYMARKET_PASSPHRASE=...
```

One-time setup uses the adapter's bundled scripts:
`set_allowances.py` (token approvals) and `create_api_key.py` (CLOB key).

## 1. Backtest on real historical data

```bash
python -m poly_nautilus.backtest \
    --market-slug gta-vi-released-before-june-2026 \
    --start 2026-01-01 --end 2026-02-01 \
    --gamma 2 --kappa 30 --trade-size 20 --max-loss-usd 200
```

- Data is loaded with `PolymarketDataLoader.from_market_slug(..., sanitize_info=True)`
  (the flag redacts the resolved winner so there is no look-ahead bias).
- Nautilus applies `PolymarketFeeModel(maker_rebates_enabled=True)` and produces
  account / fills / positions reports plus portfolio statistics (Sharpe, returns).

## 2. Forward-test on live data (paper — no real orders)

```bash
python -m poly_nautilus.live --token <token_id> --condition <condition_id> \
    --other-token <no_token_id> --paper
```

`--paper` subscribes to live Polymarket data but routes execution to a simulated
(sandbox) path, so it places **no real orders**. This is the truest forward test:
live flow, live latency, simulated fills.

## 3. Live trading (real orders)

```bash
python -m poly_nautilus.live --token <token_id> --condition <condition_id>
```

Omitting `--paper` registers the live Polymarket execution client and places
**real** post-only limit orders. Start with tiny `--trade-size` / `--max-loss-usd`.

## How the strategy maps poly_strategy → Nautilus

| poly_strategy concept | Nautilus mechanism |
|---|---|
| `MarketSnapshot` | built from `self.cache.order_book(instrument_id)` best levels + `self.portfolio.net_position` |
| VPIN toxicity feed | `on_trade_tick` with the real `AggressorSide` (sharper than the websocket proxy) |
| `QuoteDecision` bid/ask | `order_factory.limit(..., time_in_force=GTC, post_only=True)` |
| requote / FIFO requeue | `_reconcile` cancels+replaces only on >1 tick / >10% size drift |
| withdraw (toxicity / resolution) | `cancel_all_orders(instrument_id)` |
| Dutch-book arb | opposite token's book via `other_instrument_id` (logged) |
| inventory limit `Q`, skew, AS/GLFT spread | unchanged — computed inside `Quoter` |

## Version caveats (please verify against your installed version)

This integration is written to the API documented in the adapter's
`docs/integrations/polymarket.md` and the Strategy concept docs. nautilus_trader
evolves quickly; if you hit an `AttributeError`/`ImportError`, check these spots
against your installed version:

- `PolymarketDataLoader` data methods: `load_deltas` / `load_quotes` /
  `load_trades` (the backtest script probes all three and reports what loaded).
  Market-making needs **book or quote** data; trades-only will not quote.
- Whether a binary market exposes one instrument or two (`loader.instruments`).
- `--paper` sandbox execution wiring — Nautilus's `SandboxExecutionClient` config
  varies by version; register it for `POLYMARKET` in `live.py` if the default
  data-only paper path isn't sufficient.
- Account/venue setup constants (`USDC`, `BookType.L2_MBP`, `OmsType`,
  `AccountType.CASH`).

These scripts were authored without a runnable Nautilus install in the build
environment; treat first-run as a smoke test and adjust the few version-specific
calls above if needed. The strategy logic itself (`strategy.py`) is independent of
those and is exercised by the existing `poly_strategy` tests.
