# Admin Panel (Google Spreadsheet) Template

The bot is configured entirely from a Google Spreadsheet. This document describes
every worksheet and column, including the parameters added for the
`poly_strategy` quantitative engine. A ready-to-import `Hyperparameters` sheet is
provided in [`hyperparameters_template.csv`](./hyperparameters_template.csv).

## How configuration flows into the bot

`poly_data/utils.py::get_sheet_df` reads three worksheets and merges them:

- **Selected Markets** (operator-edited) — the markets you want to trade and your
  per-market sizing. Merged with **All Markets** on the `question` column.
- **All Markets** (auto-written by `update_markets.py`) — the market database
  (prices, reward band, tick size, volatility, `end_date_iso`, token ids, …).
- **Hyperparameters** (operator-edited) — strategy knobs grouped by `param_type`.

At runtime each market row's `param_type` selects which Hyperparameters group
applies, and `StrategyConfig.from_params(params, row)` builds the engine config
from the group plus the row.

---

## 1. Selected Markets  (you edit this)

| Column        | Required | Meaning |
|---------------|----------|---------|
| `question`    | yes | Market question; the merge key into All Markets. |
| `param_type`  | yes | Which Hyperparameters group to use (e.g. `default`). |
| `trade_size`  | yes | Base quote size in tokens. The engine uses this as `base_order_size`. |
| `max_size`    | yes | Max position per outcome (tokens). The engine uses this as `max_order_size`. |
| `multiplier`  | no  | Legacy size multiplier for sub-$0.10 outcomes (legacy path only). |

> Only these are operator-owned; everything else for a market comes from the
> auto-populated All Markets sheet via the merge.

## 2. All Markets  (auto-written by `update_markets.py`)

Key columns the bot consumes: `question`, `answer1`, `answer2`, `neg_risk`,
`best_bid`, `best_ask`, `min_size`, `max_spread` (reward-band half-width in
cents), `tick_size`, `end_date_iso` **(new — enables staged resolution
withdrawal)**, `3_hour` and other volatility horizons, `token1`, `token2`,
`condition_id`.

> **Action required:** re-run `python update_markets.py` after upgrading so the
> new `end_date_iso` column is written. Without it, the resolution-withdrawal
> safety layer stays dormant (the bot simply won't know when a market expires).

## 3. Volatility Markets / Full Markets

Auto-written candidate lists for choosing what to add to Selected Markets. Not
read by the trading loop.

---

## 4. Hyperparameters  (you edit this)

Three columns: **`type`**, **`param`**, **`value`**. Put the group name in `type`
on the first row of a group; leave `type` blank on following rows (the parser
carries the last non-empty `type` forward). Import
`hyperparameters_template.csv` to get the `default` group below.

### Strategy engine parameters

| param | default | What it controls / when to change |
|-------|---------|-----------------------------------|
| `use_strategy_engine` | `1` | **On by default** (the engine is the only quoting path in v2). Set `0` to disable quoting for this `param_type`. |
| `gamma` | `2.0` | AS risk aversion. Higher ⇒ wider spreads and stronger inventory skew. |
| `kappa` | `30.0` | Order-arrival decay. Higher ⇒ tighter base spread (min half-spread ≈ `1/kappa`). |
| `horizon_hours` | `24.0` | Planning horizon (T−t) when no end date is known; scales the inventory penalty. |
| `min_half_spread` | `0.01` | Floor on half-spread (price units). Never quote tighter. |
| `max_half_spread` | `0.15` | Cap on half-spread; protects against vol blow-ups. |
| `max_loss_usd` | `200.0` | Max tolerable loss on one outcome ⇒ sets the hard inventory limit `Q`. |
| `target_inventory` | `0.0` | Desired steady-state inventory (tokens). Usually flat. |
| `inventory_skew_cap` | `0.08` | Cap on the reservation-price shift from inventory (price units). |
| `kelly_fraction` | `0.30` | Fractional-Kelly multiplier on edge-implied order size. |
| `vol_ewma_lambda` | `0.94` | EWMA persistence for realized volatility. Higher ⇒ smoother/slower. |
| `vol_floor` | `0.02` | Floor on per-horizon volatility so spreads never collapse. |
| `sheet_vol_weight` | `0.5` | Weight on the slow sheet (annualized) vol vs. realtime vol. |
| `vpin_bucket_size` | `200.0` | Volume per VPIN toxicity bucket (tokens). |
| `vpin_num_buckets` | `20` | Number of buckets averaged for VPIN. |
| `vpin_widen_threshold` | `0.35` | VPIN above this widens spreads proportionally. |
| `vpin_kill_threshold` | `0.60` | VPIN above this pulls quotes (toxicity kill switch). |
| `vpin_widen_gain` | `2.0` | How aggressively spreads widen with excess VPIN. |
| `reward_band_fraction` | `0.8` | Fraction of the reward band to quote within (safety margin inside the cliff). |
| `enforce_two_sided` | `1` | Prefer two-sided quotes (~3× rewards) when not adding risk. |
| `resolution_widen_hours` | `6.0` | Begin widening this many hours before resolution (needs `end_date_iso`). |
| `resolution_withdraw_hours` | `1.0` | Fully withdraw this many hours before resolution (needs `end_date_iso`). |
| `arb_min_edge` | `0.005` | Min Dutch-book edge (price units), net of fees, to flag arbitrage. |
| `min_price` | `0.05` | Don't quote below this price (deep-tail adverse selection). |
| `max_price` | `0.95` | Don't quote above this price. |
| `maker_fee` | `0.0` | Maker fee fraction (most Polymarket markets are 0). |

Optional overrides (otherwise taken from the market row): `base_order_size`
(else `trade_size`), `max_order_size` (else `max_size`), `reward_max_spread`
(else the market's `max_spread`), `tick_size`.

> The legacy quoting parameters (`stop_loss_threshold`, `take_profit_threshold`,
> `spread_threshold`, `volatility_threshold`, `sleep_period`) were **removed in the
> v2 cutover** — the strategy engine is now the only quoting path, so those columns
> are no longer read and can be deleted from the sheet. `use_strategy_engine`
> defaults to on; set it to `0` to disable quoting a param-type.

---

## Recommended rollout

1. Re-run `python update_markets.py` to populate `end_date_iso` in All Markets.
2. Import `hyperparameters_template.csv` into the **Hyperparameters** sheet (or a
   new `param_type` group), keeping `use_strategy_engine = 0`.
3. Point a couple of low-risk markets at that `param_type` in Selected Markets.
4. Flip `use_strategy_engine = 1`, start with small `trade_size`/`max_loss_usd`,
   and watch the `[engine]` log lines before scaling capital.
