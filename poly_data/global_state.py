import threading
import pandas as pd

# ============ Market Data ============

# List of all tokens being tracked
all_tokens = []

# Mapping between tokens in the same market (YES->NO, NO->YES)
REVERSE_TOKENS = {}  

# Order book data for all markets
all_data = {}

# Per-token real order books, keyed by token_id.
# Format: {token_id: {'bids': SortedDict, 'asks': SortedDict}}
# Unlike all_data (which holds only the primary/token1 book per market and
# derives the other side as 1 - price), this stores the *actual* book for every
# subscribed token. Required for true cross-token Dutch-book arbitrage detection
# and accurate quoting of the second outcome.
all_token_data = {}

# Maps a market's condition_id -> its primary token (token1). Used to keep the
# legacy all_data[market] book pointed at token1 even though both tokens are now
# subscribed on the market websocket.
MARKET_TOKEN1 = {}

# Market configuration data from Google Sheets
df = None

# ============ Client & Parameters ============

# Polymarket client instance
client = None

# Trading parameters from Google Sheets
params = {}

# Lock for thread-safe trading operations
lock = threading.Lock()

# ============ Trading State ============

# Tracks trades that have been matched but not yet mined
# Format: {"token_side": {trade_id1, trade_id2, ...}}
performing = {}

# Timestamps for when trades were added to performing
# Used to clear stale trades
performing_timestamps = {}

# Timestamps for when positions were last updated
last_trade_update = {}

# Current open orders for each token
# Format: {token_id: {'buy': {price, size}, 'sell': {price, size}}}
orders = {}

# Current positions for each token
# Format: {token_id: {'size': float, 'avgPrice': float}}
positions = {}

