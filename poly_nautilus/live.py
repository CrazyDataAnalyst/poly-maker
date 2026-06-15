"""
Live / forward-test poly_strategy on Polymarket via a Nautilus TradingNode.

Runs the *same* PolymakerNautilusStrategy used in backtest.py against the live
Polymarket data + execution clients. Two modes:

  * ``--paper``  : live market data, but execution routed to Nautilus's sandbox
                   (simulated fills) - true forward testing, NO real orders.
  * (default)    : live execution - places REAL orders. Requires funded wallet,
                   set allowances, and a created CLOB API key.

Credentials come from environment variables (see NAUTILUS.md):
    POLYMARKET_PK, POLYMARKET_FUNDER,
    POLYMARKET_API_KEY, POLYMARKET_API_SECRET, POLYMARKET_PASSPHRASE

Run:
    python -m poly_nautilus.live --token <token_id> --condition <condition_id> --paper

API targets docs/integrations/polymarket.md. Verify against your installed
nautilus_trader version; see NAUTILUS.md.
"""

from __future__ import annotations

import argparse

from nautilus_trader.adapters.polymarket import (  # type: ignore
    POLYMARKET,
    PolymarketDataClientConfig,
    PolymarketExecClientConfig,
    PolymarketInstrumentProviderConfig,
    PolymarketLiveDataClientFactory,
    PolymarketLiveExecClientFactory,
    get_polymarket_instrument_id,
)
from nautilus_trader.config import (
    ImportableStrategyConfig,
    LiveExecEngineConfig,
    LoggingConfig,
    TradingNodeConfig,
)
from nautilus_trader.live.node import TradingNode

from poly_nautilus.strategy import PolymakerNautilusConfig, PolymakerNautilusStrategy


def build_node(args) -> TradingNode:
    instrument_id = get_polymarket_instrument_id(
        condition_id=args.condition, token_id=args.token
    )
    instrument_provider = PolymarketInstrumentProviderConfig(load_all=False)

    data_config = PolymarketDataClientConfig(instrument_provider=instrument_provider)
    exec_config = PolymarketExecClientConfig(instrument_provider=instrument_provider)

    node_config = TradingNodeConfig(
        trader_id="POLYMAKER-LIVE-001",
        logging=LoggingConfig(log_level="INFO"),
        exec_engine=LiveExecEngineConfig(reconciliation=True),
        data_clients={POLYMARKET: data_config},
        # In --paper mode you would register a SandboxExecutionClient for this
        # venue instead of the live exec client; see NAUTILUS.md for the sandbox
        # wiring. Default below is LIVE execution (real orders).
        exec_clients={} if args.paper else {POLYMARKET: exec_config},
        strategies=[
            ImportableStrategyConfig(
                strategy_path="poly_nautilus.strategy:PolymakerNautilusStrategy",
                config_path="poly_nautilus.strategy:PolymakerNautilusConfig",
                config={
                    "instrument_id": instrument_id,
                    "other_instrument_id": (
                        get_polymarket_instrument_id(args.condition, args.other_token)
                        if args.other_token else None
                    ),
                    "gamma": args.gamma,
                    "kappa": args.kappa,
                    "trade_size": args.trade_size,
                    "max_size": args.max_size,
                    "max_loss_usd": args.max_loss_usd,
                },
            )
        ],
    )

    node = TradingNode(config=node_config)
    node.add_data_client_factory(POLYMARKET, PolymarketLiveDataClientFactory)
    if not args.paper:
        node.add_exec_client_factory(POLYMARKET, PolymarketLiveExecClientFactory)
    node.build()
    return node


def main():
    p = argparse.ArgumentParser(description="Live/forward-test poly_strategy on Polymarket")
    p.add_argument("--token", required=True, help="outcome token id")
    p.add_argument("--condition", required=True, help="market condition id")
    p.add_argument("--other-token", default=None, help="opposite outcome token id (for arb)")
    p.add_argument("--paper", action="store_true", help="forward test: no real orders")
    p.add_argument("--gamma", type=float, default=2.0)
    p.add_argument("--kappa", type=float, default=30.0)
    p.add_argument("--trade-size", type=float, default=20.0)
    p.add_argument("--max-size", type=float, default=200.0)
    p.add_argument("--max-loss-usd", type=float, default=200.0)
    args = p.parse_args()

    if args.paper:
        print("PAPER mode: live data, simulated execution - NO real orders.")
    else:
        print("LIVE mode: REAL orders will be placed. Ensure allowances + API key are set.")

    node = build_node(args)
    try:
        node.run()
    finally:
        node.dispose()


if __name__ == "__main__":
    main()
