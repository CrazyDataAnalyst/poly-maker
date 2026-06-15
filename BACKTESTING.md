# Backtesting & Forward-Testing `poly_strategy`

The strategy engine (`poly_strategy.Quoter`) is a pure function of market state, so
the **same decision code** is driven by historical data (backtest) and by a live
read-only feed (forward / paper test). Both share one simulation core in
`poly_backtest/` — fill model, PnL ledger, metrics — so results are directly
comparable and there is no backtest-vs-live skew.

```
data source ──▶ events (BookUpdate / Trade) ──▶ BacktestRunner ──▶ Quoter.compute
                                                      │
                                       MakerFillModel ▼  Ledger ──▶ Metrics (PnL, Sharpe…)
```

## 1. Quick start (synthetic, no data needed)

```bash
python run_backtest.py --mode synthetic --steps 8000 --gamma 2 --participation 0.25
```

Output:

```
PnL=6.81  Sharpe(annual)=15.59  Sharpe(/sample)=0.022  Sortino(annual)=24.48
MaxDD=21.05 (10.5%)  fills=36  turnover=357  samples=268@60s
```

The synthetic source includes random *informed bursts* (jump + one-sided flow), so
it exercises the VPIN toxicity defense and adverse selection, not just calm flow.

## 2. Backtest on historical data (e.g. warproxxx/poly_data)

The CSV adapter takes a **column map**, so it adapts to any schema without code
changes. Supply a book stream and/or a trades stream:

```bash
python run_backtest.py --mode csv \
  --book   book.csv   --book-cols   ts=t,token=asset,bid=best_bid,ask=best_ask,bid_size=bsz,ask_size=asz \
  --trades trades.csv --trades-cols ts=t,token=asset,price=p,size=q,side=taker_side \
  --sample-interval 60 \
  --end-ts 1718400000 \          # market resolution epoch -> enables staged withdrawal
  --outcome YES=1                # terminal settlement of remaining inventory
```

Notes:
- **Provide the book.** Trades alone work but the book is then approximated and
  fills/marks are less realistic. A top-of-book quotes stream is strongly preferred.
- **Timestamps** may be epoch seconds, epoch millis, or ISO-8601 — auto-detected.
- **`--end-ts`** turns on the resolution-withdrawal risk layer; **`--outcome`**
  settles leftover inventory at 0/1 (the only correct terminal valuation).
- Multiple files/tokens merge by timestamp automatically.

> To wire the warproxxx dataset: fetch with that repo, point `--book`/`--trades` at
> the exported CSVs, and set the `*-cols` maps to its actual column names.

## 3. Forward-test on LIVE data (paper trading, no orders)

```bash
python paper_trade.py --tokens <token1>,<token2> --report-interval 30
# or, with a reachable Selected Markets sheet:
python paper_trade.py --from-sheet
```

This connects to Polymarket's **public** market websocket (no credentials), runs
the live Quoter, simulates fills with the same model, and prints rolling equity.
**It never places an order.** Run it for a day or two before committing capital;
compare its Sharpe/PnL to the backtest on the same markets.

## 4. Interpreting the metrics

- **Sharpe (annual)** = per-sample Sharpe × √(periods/year), `periods/year =
  31,536,000 / sample_interval_s`. MM PnL increments are autocorrelated and
  fat-tailed, so a high annualized Sharpe from short intervals **overstates**
  true risk-adjusted return. Use a 60–300s sampling interval for the headline and
  always quote the interval. Compare the *per-sample* Sharpe across runs for a
  fairer relative read.
- **MaxDD %** is relative to `max(running peak, max_loss_usd)` so it stays sane for
  a maker starting at zero cash.
- **fill_imbalance** = (buys − sells)/(buys + sells): persistent imbalance means
  inventory is drifting — check the skew/limit settings.
- **Sortino** penalizes only downside volatility; for a maker it is usually the
  more honest ratio.

## 5. Fill-model realism (read before trusting a number)

`MakerFillModel` is deliberately **pessimistic**, but it is still a model:

- **Crossing required** — a quote fills only when an aggressor trades *through* it.
- **Partial participation** (`--participation`, default 0.25) approximates FIFO
  queue position; you capture a fraction of crossing volume. Set 1.0 for an
  optimistic upper bound, lower it for a safety margin. **Sweep this** and treat
  the low-participation result as your realistic case.
- **Adverse selection is captured**, not assumed away: every fill is marked at the
  *subsequent* mid, so getting picked off shows up as a loss on the next sample.
- **No market impact / no latency** — your quotes don't move the book and cancels
  are instantaneous. Both bias results **optimistically**, so realized edge is a
  ceiling, not a forecast.

## 6. Methodology for trustworthy results

1. **Out-of-sample**: tune parameters on one date range, report on another.
2. **Walk-forward**: re-tune on a rolling window; report only the held-out periods.
3. **Cross-market**: run many markets; a strategy that only works on one is noise.
4. **Participation sweep**: report PnL/Sharpe across participation ∈ {0.1, 0.25, 0.5}.
5. **Include settlement**: always pass `--outcome` for resolved markets so terminal
   inventory risk is in the PnL, not hidden.
6. **Forward-test before capital**: paper-trade live and confirm the backtest edge
   survives real flow and real latency.

## 7. Tests

```bash
python3 tests/test_backtest.py     # 15 accounting/fill/metrics invariants
python3 tests/test_strategy.py     # 35 engine invariants
```
