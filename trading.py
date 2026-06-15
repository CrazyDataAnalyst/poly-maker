import gc                       # Garbage collection
import asyncio                  # Asynchronous I/O
import traceback                # Exception handling
import pandas as pd             # Data analysis library

import poly_data.global_state as global_state
import poly_data.CONSTANTS as CONSTANTS
import poly_data.strategy_adapter as sa

# Order-book utilities (the legacy quoting math get_order_prices / get_buy_sell_amount
# was removed in the v2 cutover - the strategy engine is now the only quoting path).
from poly_data.trading_utils import get_best_bid_ask_deets, get_token_best_bid_ask, round_down
from poly_data.data_utils import get_position, get_order, set_position
from poly_strategy.execution import is_passive_quote

# Dictionary to store locks for each market to prevent concurrent trading on the same market
market_locks = {}


async def perform_trade(market):
    """Entry point invoked on every book/trade update for a market.

    There is a single quoting path: position merging + the strategy engine
    (run_engine_outcomes). The legacy mid-price quoting logic has been removed.
    """
    if market not in market_locks:
        market_locks[market] = asyncio.Lock()

    async with market_locks[market]:
        try:
            row = global_state.df[global_state.df['condition_id'] == market].iloc[0]
            round_length = len(str(row['tick_size']).split(".")[1])
            params = global_state.params[row['param_type']]
            # Engine is the default and only quoting path; an operator can still
            # disable a param-type by setting use_strategy_engine = 0 in the sheet.
            if sa.is_enabled(params):
                await run_engine_outcomes(market, row, params, round_length)
        except Exception as ex:
            print(f"Error performing trade for {market}: {ex}")
            traceback.print_exc()

        gc.collect()
        await asyncio.sleep(2)


# ============================================================================
# Strategy-engine order management (the "Order Manager" module of the MVP spec)
# ============================================================================

def _quote_changed(existing_side, desired_price, desired_size, tick_size):
    """Decide whether a resting order must be cancelled/replaced.

    We only requote on a *meaningful* change to limit order churn against the
    3,000-requests / 10-minute rate limit:
      * the side should be on but isn't (or vice-versa), or
      * price drifted by more than one tick, or
      * size drifted by more than 10%.
    """
    have = existing_side['size'] > 0
    want = desired_price is not None and desired_size > 0

    if want != have:
        return True
    if not want:
        return False

    price_diff = abs(existing_side['price'] - desired_price)
    size_diff = abs(existing_side['size'] - desired_size)
    return price_diff > (tick_size + 1e-9) or size_diff > desired_size * 0.10


def _reconcile_engine_orders(client, token, neg_risk, decision, existing,
                             tick_size, min_price, max_price, best_bid, best_ask):
    """Cancel/replace this token's quotes to match the engine's decision.

    Both sides are managed atomically: if anything changed we cancel all orders
    for the asset (which also requeues us to the back of the FIFO queue - the
    defensive cancel/replace pattern the research corpus recommends) and re-place
    the desired bid and/or ask together, so the two sides never cancel each other.

    Every quote is checked against the passive-maker guard before sending; a quote
    that would cross is rejected and logged (it should never happen given the AS
    spread, but the guard makes maker-only a hard guarantee).
    """
    desired_bid_price = decision.bid_price if decision.quote_bid else None
    desired_ask_price = decision.ask_price if decision.quote_ask else None
    desired_bid_size = decision.bid_size if decision.quote_bid else 0.0
    desired_ask_size = decision.ask_size if decision.quote_ask else 0.0

    # Passive-maker guard: drop any side that would cross the opposite touch.
    if desired_bid_price is not None and not is_passive_quote('BUY', desired_bid_price, best_bid, best_ask, tick_size):
        print(f"[engine] {token}: REJECT non-passive BUY {desired_bid_price} vs ask {best_ask}")
        desired_bid_price, desired_bid_size = None, 0.0
    if desired_ask_price is not None and not is_passive_quote('SELL', desired_ask_price, best_bid, best_ask, tick_size):
        print(f"[engine] {token}: REJECT non-passive SELL {desired_ask_price} vs bid {best_bid}")
        desired_ask_price, desired_ask_size = None, 0.0

    bid_change = _quote_changed(existing['buy'], desired_bid_price, desired_bid_size, tick_size)
    ask_change = _quote_changed(existing['sell'], desired_ask_price, desired_ask_size, tick_size)

    if not bid_change and not ask_change:
        print(f"[engine] {token}: quotes unchanged, holding")
        return

    # Something changed -> clear the book for this asset, then re-place.
    client.cancel_all_asset(token)

    if desired_bid_price is not None and desired_bid_size > 0:
        if min_price <= desired_bid_price <= max_price:
            print(f"[engine] {token}: BUY {desired_bid_size:.1f} @ {desired_bid_price}")
            client.create_order(token, 'BUY', desired_bid_price, desired_bid_size, neg_risk)
        else:
            print(f"[engine] {token}: skip BUY, price {desired_bid_price} out of band")

    if desired_ask_price is not None and desired_ask_size > 0:
        if min_price <= desired_ask_price <= max_price:
            print(f"[engine] {token}: SELL {desired_ask_size:.1f} @ {desired_ask_price}")
            client.create_order(token, 'SELL', desired_ask_price, desired_ask_size, neg_risk)
        else:
            print(f"[engine] {token}: skip SELL, price {desired_ask_price} out of band")


async def run_engine_outcomes(market, row, params, round_length):
    """Strategy-engine trading path for one market (both outcomes).

    Reuses the position-merging and order-book plumbing, then delegates the
    pricing/sizing/risk decision to poly_strategy via the adapter. Assumes the
    caller already holds this market's lock.
    """
    client = global_state.client
    cfg = sa.build_config(params, row)
    neg_risk = row['neg_risk'] == 'TRUE'
    row_dict = row.to_dict() if hasattr(row, 'to_dict') else dict(row)

    print(f"\n\n[engine] {pd.Timestamp.utcnow().tz_localize(None)}: {row['question']}")

    deets_meta = [
        {'name': 'token1', 'token': row['token1'], 'answer': row['answer1']},
        {'name': 'token2', 'token': row['token2'], 'answer': row['answer2']},
    ]

    # ------- POSITION MERGING (recover collateral from offsetting positions) -------
    pos_1 = get_position(row['token1'])['size']
    pos_2 = get_position(row['token2'])['size']
    amount_to_merge = min(pos_1, pos_2)
    if float(amount_to_merge) > CONSTANTS.MIN_MERGE_SIZE:
        raw_1 = client.get_position(row['token1'])[0]
        raw_2 = client.get_position(row['token2'])[0]
        amount_to_merge = min(raw_1, raw_2)
        scaled_amt = amount_to_merge / 10 ** 6
        if scaled_amt > CONSTANTS.MIN_MERGE_SIZE:
            print(f"[engine] merging {scaled_amt} offsetting tokens to free collateral")
            client.merge_positions(amount_to_merge, market, neg_risk)
            set_position(row['token1'], 'SELL', scaled_amt, 0, 'merge')
            set_position(row['token2'], 'SELL', scaled_amt, 0, 'merge')

    # ------- QUOTE EACH OUTCOME -------
    for detail in deets_meta:
        token = int(detail['token'])

        existing = get_order(token)

        # Prefer this token's REAL book; fall back to the legacy derivation if its
        # book hasn't been received yet.
        deets = get_token_best_bid_ask(detail['token'], 20)
        if deets is None or deets['best_bid'] is None or deets['best_ask'] is None:
            deets = get_best_bid_ask_deets(market, detail['name'], 100, 0.1)
            if (deets['best_bid'] is None or deets['best_ask'] is None
                    or deets['best_bid_size'] is None or deets['best_ask_size'] is None):
                deets = get_best_bid_ask_deets(market, detail['name'], 20, 0.1)

        # Opposite outcome's real best prices for cross-token Dutch-book arb.
        other_token = global_state.REVERSE_TOKENS.get(str(detail['token']))
        other_deets = get_token_best_bid_ask(other_token, 20) if other_token else None
        other_best_ask = other_deets['best_ask'] if other_deets else None
        other_best_bid = other_deets['best_bid'] if other_deets else None

        pos = get_position(token)
        position = round_down(pos['size'], 2)
        avg_price = pos['avgPrice']

        sa.mark_book_update(detail['token'])
        snapshot = sa.build_snapshot(
            detail['token'], deets, position, avg_price, row_dict,
            other_best_ask=other_best_ask, other_best_bid=other_best_bid,
        )
        decision = sa.compute(detail['token'], snapshot, cfg)
        # Stash reservation/fair so fills can be attributed to spread vs rewards.
        sa.note_decision(detail['token'], decision)

        print(f"[engine] {detail['answer']}: fair={decision.fair_value:.4f} "
              f"res={decision.reservation_price:.4f} sigma={decision.sigma_price:.4f} "
              f"vpin={decision.vpin:.2f} inv_ratio={decision.inventory_ratio:.2f} "
              f"spread_x={decision.spread_multiplier:.2f} pos={position} "
              f"bid={decision.bid_price} ask={decision.ask_price} "
              f"reward[b={decision.bid_reward_score:.3f} a={decision.ask_reward_score:.3f} "
              f"2sided={decision.reward_two_sided}] reasons={decision.reasons}")

        # Risk-free Dutch book (logged only; execution intentionally not wired).
        if decision.arb is not None:
            print(f"[engine] ARBITRAGE detected: {decision.arb.note}")

        # Full withdrawal -> clear the book for this asset and move on.
        if not decision.quote_bid and not decision.quote_ask:
            if existing['buy']['size'] > 0 or existing['sell']['size'] > 0:
                print(f"[engine] {token}: withdrawing all quotes ({decision.reasons})")
                client.cancel_all_asset(token)
            continue

        _reconcile_engine_orders(
            client, token, neg_risk, decision, existing,
            cfg.tick_size, cfg.min_price, cfg.max_price,
            deets['best_bid'], deets['best_ask'],
        )
