# Poly-Maker

A market making bot for Polymarket prediction markets. This bot automates the process of providing liquidity to markets on Polymarket by maintaining orders on both sides of the book with configurable parameters. A summary of my experience running this bot is available [here](https://x.com/defiance_cr/status/1906774862254800934)

## Overview

Poly-Maker is a comprehensive solution for automated market making on Polymarket. It includes:

- Real-time order book monitoring via WebSockets
- Position management with risk controls
- Customizable trade parameters fetched from Google Sheets
- Automated position merging functionality
- Sophisticated spread and price management

## How it Works

The bot operates through a main loop that connects to Polymarket's WebSocket APIs for real-time market and user data. A background thread periodically fetches market configurations, positions, and open orders. The core trading logic, found in `trading.py`, analyzes market conditions for each selected market, calculates optimal bid and ask prices, and manages orders. It also includes risk management features like stop-loss and take-profit, and automatically merges opposing positions to free up capital.

## Structure

The repository consists of several interconnected modules:

- `poly_data`: Core data management and market making logic.
- `poly_merger`: Utility for merging positions (based on open-source Polymarket code).
- `poly_stats`: Account statistics tracking.
- `poly_utils`: Shared utility functions.
- `data_updater`: Separate module for collecting market information.
- `main.py`: The main entry point for the application.
- `trading.py`: Contains the core trading logic.
- `update_markets.py`: A script to update the market data in the Google Sheet.
- `update_stats.py`: A script to update the account statistics in the Google Sheet.

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

- **Selected Markets**: A list of markets you want the bot to trade.
- **All Markets**: A comprehensive database of all markets on Polymarket, which is updated by `update_markets.py`.
- **Volatility Markets**: A filtered list of markets from "All Markets" that meet certain volatility criteria.
- **Hyperparameters**: Configuration parameters for the trading logic, such as stop-loss thresholds, take-profit percentages, and trade sizes.
- **Summary**: A summary of your current positions, orders, and earnings, which is updated by `update_stats.py`.


## Poly Merger

The `poly_merger` module is a particularly powerful utility that handles position merging on Polymarket. It's built on open-source Polymarket code and provides a smooth way to consolidate positions, reducing gas fees and improving capital efficiency.

## Risk Management

The bot includes the following risk management features:

- **Stop-Loss**: Automatically sells a position if the PnL drops below a configurable threshold and the market spread is tight enough for an efficient exit.
- **Take-Profit**: Places sell orders at a price calculated to lock in a desired profit percentage.
- **Volatility Threshold**: Pauses trading on a market if its volatility exceeds a predefined limit.
- **Position Sizing**: Limits the size of positions to a configurable maximum.

## Important Notes

- This code interacts with real markets and can potentially lose real money.
- Test thoroughly with small amounts before deploying with significant capital.
- The `data_updater` is technically a separate repository but is included here for convenience.

## License

MIT
