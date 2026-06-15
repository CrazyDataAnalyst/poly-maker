# Poly-Maker → v2: Transition — Completion Record

Tracks completion of the developer transition guide (legacy mid-price bot →
simple-but-sufficient quant maker). This is the in-repo status artifact; the
narrative guide is the source spec.

**Legend:**
`[x]` delivered & verified in this environment (code + offline tests/backtests).
`[x]ᵒ` engineering work complete and offline-verified, **final acceptance is
operator-gated** — it requires real historical data, live credentials, or live
network that cannot run in the build sandbox. The tooling to do it ships here.

---

## Phase status

| Phase | Scope | Status |
|---|---|---|
| 0 | Baseline & safety net (tests green, engine off-switch) | ✅ done |
| 1 | Validate engine offline (backtest) | ✅ tooling + multi-regime run; historical = operator |
| 2 | Forward-test on live data (paper) | ✅ tooling (`paper_trade.py`); run = operator |
| 3 | Live cutover, one param-type | ✅ path ready; run = operator |
| 4 | Income streams explicit & measured | ✅ done (passive guard, reward log, PnL attribution) |
| 5 | Harden adverse-selection defenses | ✅ done (each defense has a triggering test) |
| 7 | Fine-tuning workflow (`sweep.py`) | ✅ done |
| 8 | Prune the legacy path | ✅ done (one quoting path) |
| 9 | Management & ops | ✅ Google Sheets retained + hourly PnL summary |
| 10 | Deliberately NOT built | ✅ honored (no arb-exec, no UI, no DB, no HFT) |

---

## §12 Acceptance checklist

- [x] **Offline tests green** — `tests/test_strategy.py` (39) + `tests/test_backtest.py` (19) = **58 passing**.
- [x]ᵒ **Engine profitable + tolerable drawdown across regimes** — validated offline
  across calm→volatile synthetic regimes *including informed bursts* (profitable in
  calm/low-vol, drawdown-bounded; adverse bursts correctly produce losses, proving
  the harness captures adverse selection). **Confirm on your markets** with
  `run_backtest.py --mode csv` on real historical data (e.g. warproxxx/poly_data)
  or the Nautilus backtest (`poly_nautilus/`).
- [x]ᵒ **Paper-trade PnL tracks backtest** — `paper_trade.py` shares the exact sim
  core with the backtester; run it on live data for a few days to confirm (needs
  live network, not available in build env).
- [x]ᵒ **Live, one param-type, tiny size** — single quoting path is live behind the
  per-param-type switch; `[engine]` log shows `fair/res/sigma/vpin/inv_ratio/
  spread_x/bid/ask/reward/reasons`. Run with credentials + tiny `trade_size`.
- [x] **Every quote provably passive** — `poly_strategy.execution.is_passive_quote`
  guard in `_reconcile_engine_orders` rejects+logs any crossing quote; tested
  (`test_passive_quote_guard`, `test_quoter_quotes_are_passive`).
- [x] **Reward-band eligibility + two-sided status visible per market** —
  `QuoteDecision.bid_reward_score/ask_reward_score/reward_two_sided`, surfaced in
  the `[engine]` line; tested (`test_quoter_reports_reward_scores`).
- [x] **VPIN widen/kill, resolution withdrawal, stale-book kill demonstrably trigger** —
  `test_quoter_vpin_widens_before_kill`, `test_quoter_kills_on_toxicity`,
  `test_quoter_withdraws_near_resolution`, `test_quoter_withdraws_on_stale_book`,
  `test_quoter_stops_buying_at_inventory_limit`.
- [x] **Daily PnL split into rebates / rewards / spread** —
  `poly_stats/pnl_attribution.py`; fills recorded in `data_processing` against the
  engine's reservation price; hourly `[pnl]` summary in `main.py`; tested
  (4 attribution tests).
- [x] **`sweep.py` ranks configs; winner promoted with documented basis** —
  e.g. `reward_band_fraction=0.9` ranked top by Sharpe on the synthetic set
  (wider quotes → fewer toxic fills). Tune on one range, validate on a held-out range.
- [x] **Legacy quoting path deleted; one quoting path remains; tests green** —
  removed `send_buy_order`/`send_sell_order`, the legacy `perform_trade` branch,
  and `get_order_prices`/`get_buy_sell_amount`. `trading.py` is now merge +
  `run_engine_outcomes` only (net-negative diff).
- [x] **Market on/off and parameter changes take one edit, no redeploy** —
  Google Sheets management retained: `Selected Markets` (on/off), `Hyperparameters`
  (tuning, incl. `use_strategy_engine` off-switch), refreshed every ~30s by the
  background loop. Documented in `templates/SPREADSHEET_TEMPLATE.md`.

**Operator-gated items (`[x]ᵒ`)** — items 2–4 — are *code-complete and
offline-verified*; their final sign-off requires running on your real data / live
account, which is outside the build sandbox. Everything needed to run them ships
in this branch.

---

## What changed in the cutover (file-by-file)

| Path | Action taken |
|---|---|
| `trading.py` | **Simplified**: deleted legacy quoting (`send_buy_order`, `send_sell_order`, legacy `perform_trade` branch). One path: merge + `run_engine_outcomes`. Added passive-maker guard + reward logging + attribution hook. |
| `poly_data/trading_utils.py` | Deleted `get_order_prices`, `get_buy_sell_amount`; kept book helpers + `round_*`. |
| `poly_data/strategy_adapter.py` | Engine now default (`is_enabled` defaults on); added `note_decision` / `record_fill` / `pnl_summary` + `ATTRIBUTOR`. |
| `poly_data/data_processing.py` | Record maker fills into the PnL attributor. |
| `poly_strategy/quoter.py` | `QuoteDecision` now carries reward scores + two-sided flag. |
| `poly_strategy/execution.py` | **New**: pure `is_passive_quote` guard (testable offline). |
| `poly_stats/pnl_attribution.py` | **New**: spread / rebates / rewards attribution. |
| `main.py` | Hourly `[pnl]` attribution summary in the refresh loop. |
| `sweep.py` | **New**: parameter sweep over the backtester. |
| `tests/` | +9 tests (passive guard, reward visibility, VPIN widen, attribution). |
