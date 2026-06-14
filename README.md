# Poly-Maker

A market making bot for Polymarket prediction markets. This bot automates the process of providing liquidity to markets on Polymarket by maintaining orders on both sides of the book with configurable parameters. A summary of my experience running this bot is available [here](https://x.com/defiance_cr/status/1906774862254800934)

## Overview

Poly-Maker is a comprehensive solution for automated market making on Polymarket. It includes:

- Real-time order book monitoring via WebSockets
- Position management with risk controls
- Customizable trade parameters fetched from Google Sheets
- Automated position merging functionality
- Sophisticated spread and price management

## Structure

The repository consists of several interconnected modules:

- `poly_data`: Core data management and market making logic
- `poly_merger`: Utility for merging positions (based on open-source Polymarket code)
- `poly_stats`: Account statistics tracking
- `poly_utils`: Shared utility functions
- `data_updater`: Separate module for collecting market information

## Requirements

- Python 3.9.10 or higher
- Node.js (for poly_merger)
- Google Sheets API credentials
- Polymarket account and API credentials

## Installation

This project uses UV for fast, reliable package management.

### Install UV

```bash
# macOS/Linux
curl -LsSf https://astral.sh/uv/install.sh | sh

# Windows
powershell -c "irm https://astral.sh/uv/install.ps1 | iex"

# Or with pip
pip install uv
```

### Install Dependencies

```bash
# Install all dependencies
uv sync

# Install with development dependencies (black, pytest)
uv sync --extra dev
```

### Quick Start

```bash
# Run the market maker (recommended)
uv run python main.py

# Update market data
uv run python update_markets.py

# Update statistics
uv run python update_stats.py
```

### Setup Steps

#### 1. Clone the repository

```bash
git clone https://github.com/yourusername/poly-maker.git
cd poly-maker
```

#### 2. Install Python dependencies

```bash
uv sync
```

#### 3. Install Node.js dependencies for the merger

```bash
cd poly_merger
npm install
cd ..
```

#### 4. Set up environment variables

```bash
cp .env.example .env
```

#### 5. Configure your credentials in `.env`

Edit the `.env` file with your credentials:
- `PK`: Your private key for Polymarket
- `BROWSER_ADDRESS`: Your wallet address

**Important:** Make sure your wallet has done at least one trade through the UI so that the permissions are proper.

#### 6. Set up Google Sheets integration

- Create a Google Service Account and download credentials to the main directory
- Copy the [sample Google Sheet](https://docs.google.com/spreadsheets/d/1Kt6yGY7CZpB75cLJJAdWo7LSp9Oz7pjqfuVWwgtn7Ns/edit?gid=1884499063#gid=1884499063)
- Add your Google service account to the sheet with edit permissions
- Update `SPREADSHEET_URL` in your `.env` file

#### 7. Update market data

Run the market data updater to fetch all available markets:

```bash
uv run python update_markets.py
```

This should run continuously in the background (preferably on a different IP than your trading bot).

- Add markets you want to trade to the "Selected Markets" sheet
- Select markets from the "Volatility Markets" sheet
- Configure parameters in the "Hyperparameters" sheet (default parameters that worked well in November are included)

#### 8. Start the market making bot

```bash
uv run python main.py
```

## Configuration

The bot is configured via a Google Spreadsheet with several worksheets:

- **Selected Markets**: Markets you want to trade
- **All Markets**: Database of all markets on Polymarket
- **Hyperparameters**: Configuration parameters for the trading logic


## Strategy Engine (`poly_strategy`)

The `poly_strategy` package is a self-contained quantitative quoting brain that
replaces the legacy "quote one tick inside the mid" logic with the
Avellaneda-Stoikov / GLFT framework adapted for binary, bounded prediction
markets. It is dependency-light (stdlib `math` only) and fully unit-tested
offline (`python3 tests/test_strategy.py`).

### What it does

| Module | Responsibility | Lever |
|---|---|---|
| `fair_value.py` | Micro-price + log-odds belief smoothing | Fair value, not mid-price |
| `volatility.py` | EWMA realized vol in log-odds space (+ sheet prior) | Spread sizing |
| `avellaneda.py` | Reservation price + AS/GLFT optimal spread | Inventory-aware pricing |
| `inventory.py` | Hard limit `Q` from max loss, Kelly-capped sizing | Inventory safety |
| `toxicity.py` | VPIN (bulk-volume classification) | Adverse-selection defense |
| `arbitrage.py` | Dutch-book / NegRisk detection | Risk-free PnL |
| `rewards.py` | Polymarket quadratic reward-band placement | Liquidity rewards |
| `risk.py` | Kill switches + staged resolution withdrawal | Risk controls |
| `quoter.py` | Orchestrates the above into a `QuoteDecision` | Integration surface |

### Enabling it

The engine is **opt-in per param-type** and off by default, so it never silently
changes a live bot. Add a `use_strategy_engine` row (value `1`) to the
`Hyperparameters` sheet for the param-type you want it on. When set, `trading.py`
hands that market to `run_engine_outcomes`; otherwise the original logic runs
unchanged.

### Tunable hyperparameters (all optional, conservative defaults)

`gamma`, `kappa` (AS risk-aversion / arrival decay), `max_loss_usd` (sets the hard
inventory limit `Q`), `min_half_spread`, `max_half_spread`, `kelly_fraction`,
`vol_ewma_lambda`, `sheet_vol_weight`, `vpin_bucket_size`, `vpin_num_buckets`,
`vpin_widen_threshold`, `vpin_kill_threshold`, `reward_band_fraction`,
`resolution_widen_hours`, `resolution_withdraw_hours`, `arb_min_edge`,
`min_price`, `max_price`. Existing `trade_size`/`max_size`/`max_spread`/`tick_size`
are reused automatically. See `poly_strategy/config.py` for the full list and
defaults.

### Known limitations / next steps

- **Intra-market Dutch-book arb is dormant**: the data layer only subscribes to
  the YES book and derives NO synthetically, so the detector (fully implemented
  and tested) won't fire live until both outcome books are subscribed.
- **Staged resolution withdrawal needs an end date**: it activates only when the
  market row carries `end_date_iso`; add that column in `data_updater` to enable.
- **VPIN feed is an order-flow proxy** (top-of-book consumption), not true trade
  prints; subscribing to the market trade channel would sharpen it.

## Poly Merger

The `poly_merger` module is a particularly powerful utility that handles position merging on Polymarket. It's built on open-source Polymarket code and provides a smooth way to consolidate positions, reducing gas fees and improving capital efficiency.

## Important Notes

- This code interacts with real markets and can potentially lose real money
- Test thoroughly with small amounts before deploying with significant capital
- The `data_updater` is technically a separate repository but is included here for convenience

## License

MIT
