import json
from sortedcontainers import SortedDict
import poly_data.global_state as global_state
import poly_data.CONSTANTS as CONSTANTS

from trading import perform_trade
import time
import asyncio
from poly_data.data_utils import set_position, set_order, update_positions


def _feed_toxicity(token, buy_volume, sell_volume):
    """Forward inferred order-flow to the strategy engine's VPIN estimator.

    Imported lazily and wrapped so the legacy data path has no hard dependency on
    the strategy package and never breaks if it is absent.
    """
    try:
        from poly_data import strategy_adapter
        strategy_adapter.feed_flow(token, buy_volume, sell_volume)
    except Exception:
        pass

def _is_primary(asset, asset_id):
    """True if asset_id is the market's primary (token1) book, or unknown."""
    primary = global_state.MARKET_TOKEN1.get(asset)
    return primary is None or str(asset_id) == str(primary)


def process_book_data(asset, j):
    asset_id = j.get('asset_id')
    bids = j.get('bids', [])
    asks = j.get('asks', [])

    # Always store the real per-token book (used by the engine for both outcomes
    # and for cross-token arbitrage detection).
    token_book = {'bids': SortedDict(), 'asks': SortedDict()}
    token_book['bids'].update({float(e['price']): float(e['size']) for e in bids})
    token_book['asks'].update({float(e['price']): float(e['size']) for e in asks})
    global_state.all_token_data[str(asset_id)] = token_book

    # Keep the legacy market book pinned to the primary (token1) book only, so the
    # existing get_best_bid_ask_deets derivation (NO = 1 - YES) is unchanged.
    if _is_primary(asset, asset_id):
        global_state.all_data[asset] = {
            'asset_id': asset_id,
            'bids': SortedDict(),
            'asks': SortedDict(),
        }
        global_state.all_data[asset]['bids'].update({float(e['price']): float(e['size']) for e in bids})
        global_state.all_data[asset]['asks'].update({float(e['price']): float(e['size']) for e in asks})


def _apply_change(book_dict, side, price_level, new_size, feed_token):
    """Apply one price-level change to a book dict, optionally feeding VPIN.

    Toxicity (VPIN) feed: a shrinking resting size at the *best* price almost
    always means it was traded into (vs. a cancel deeper in the book). Bid
    consumption = sell flow; ask consumption = buy flow. This is the order-flow
    proxy the VPIN estimator consumes, since this repo's market websocket does not
    expose trade prints.
    """
    book = book_dict['bids'] if side == 'bids' else book_dict['asks']

    if feed_token is not None:
        try:
            old_size = book.get(price_level, 0.0)
            if new_size < old_size and len(book) > 0:
                best_price = book.keys()[-1] if side == 'bids' else book.keys()[0]
                if abs(price_level - best_price) < 1e-9:
                    consumed = old_size - new_size
                    if side == 'bids':
                        _feed_toxicity(feed_token, buy_volume=0.0, sell_volume=consumed)
                    else:
                        _feed_toxicity(feed_token, buy_volume=consumed, sell_volume=0.0)
        except Exception:
            pass

    if new_size == 0:
        if price_level in book:
            del book[price_level]
    else:
        book[price_level] = new_size


def process_price_change(asset, asset_id, side, price_level, new_size):
    # Update the real per-token book (feeds VPIN off this token's flow).
    token_book = global_state.all_token_data.get(str(asset_id))
    if token_book is not None:
        _apply_change(token_book, side, price_level, new_size, feed_token=str(asset_id))

    # Update the legacy market book only for the primary (token1) token.
    if asset in global_state.all_data:
        stored_asset_id = global_state.all_data[asset].get('asset_id')
        if stored_asset_id and str(asset_id) == str(stored_asset_id):
            _apply_change(global_state.all_data[asset], side, price_level, new_size, feed_token=None)

def process_data(json_data, trade=True):
    
    if not isinstance(json_data, list): #Add data format handling
        json_data = [json_data]
        
    for j in json_data:
        event_type = j.get('event_type')
        asset = j.get('market')
        asset_id = j.get('asset_id')

        # Both outcome tokens are subscribed, but a single perform_trade(market)
        # call already processes both outcomes. Trigger only on primary (token1)
        # events so quote-trigger frequency matches the legacy single-subscription
        # behaviour; token2 events still update the stored book for the next pass.
        primary = _is_primary(asset, asset_id)

        if event_type == 'book':
            process_book_data(asset, j)

            if trade and primary:
                asyncio.create_task(perform_trade(asset))

        elif event_type == 'price_change':
            price_changes = j.get('price_changes')
            if not isinstance(price_changes, list):
                continue
            for data in price_changes:
                side = 'bids' if data.get('side') == 'BUY' else 'asks'
                price_level = float(data.get('price'))
                new_size = float(data.get('size'))
                process_price_change(asset, asset_id, side, price_level, new_size)

                if trade and primary:
                    asyncio.create_task(perform_trade(asset))
        

        # pretty_print(f'Received book update for {asset}:', global_state.all_data[asset])

def add_to_performing(col, id):
    if col not in global_state.performing:
        global_state.performing[col] = set()
    
    if col not in global_state.performing_timestamps:
        global_state.performing_timestamps[col] = {}

    # Add the trade ID and track its timestamp
    global_state.performing[col].add(id)
    global_state.performing_timestamps[col][id] = time.time()

def remove_from_performing(col, id):
    if col in global_state.performing:
        global_state.performing[col].discard(id)

    if col in global_state.performing_timestamps:
        global_state.performing_timestamps[col].pop(id, None)

def process_user_data(rows):
    
    if not isinstance(rows, list):
        rows = [rows]

    for row in rows:
        market = row.get('market')

        side = row.get('side').lower()
        token = row.get('asset_id')
            
        if token in global_state.REVERSE_TOKENS:     
            col = token + "_" + side
            event_type = row.get('event_type')
            
            if event_type == 'trade':
                size = 0
                price = 0
                maker_outcome = ""
                taker_outcome = row.get('outcome')

                is_user_maker = False
                maker_orders = row.get('maker_orders')
                for maker_order in maker_orders:
                    maker_addr = maker_order.get('maker_address')
                    if maker_addr.lower() == global_state.client.browser_wallet.lower():
                        print("User is maker")
                        
                        size = float(maker_order.get('matched_amount'))
                        price = float(maker_order.get('price'))
                        
                        is_user_maker = True
                        maker_outcome = maker_order.get('outcome') #this is curious

                        if maker_outcome == taker_outcome:
                            side = 'buy' if side == 'sell' else 'sell' #need to reverse as we reverse token too
                        else:
                            token = global_state.REVERSE_TOKENS[token]
                
                if not is_user_maker:
                    size = float(row.get('size'))
                    price = float(row.get('price'))
                    print("User is taker")

                print("TRADE EVENT FOR: ", row.get('market'), "ID: ", row.get('id'), "STATUS: ", row.get('status'), " SIDE: ", row.get('side'), "  MAKER OUTCOME: ", maker_outcome, " TAKER OUTCOME: ", taker_outcome, " PROCESSED SIDE: ", side, " SIZE: ", size) 
                status = row.get('status')

                if status in ('CONFIRMED', 'FAILED'):
                    if status == 'FAILED':
                        print(f"Trade failed for {token}, decreasing")
                        asyncio.create_task(asyncio.sleep(2))
                        update_positions()
                    else:
                        remove_from_performing(col, row.get('id'))
                        print("Confirmed. Performing is ", len(global_state.performing[col]))
                        print("Last trade update is ", global_state.last_trade_update)
                        print("Performing is ", global_state.performing)
                        print("Performing timestamps is ", global_state.performing_timestamps)
                        
                        asyncio.create_task(perform_trade(market))

                elif status == 'MATCHED':
                    add_to_performing(col, row.get('id'))

                    print("Matched. Performing is ", len(global_state.performing[col]))
                    set_position(token, side, size, price)
                    # Attribute the fill to spread (vs reservation) + maker rebates.
                    try:
                        from poly_data import strategy_adapter
                        strategy_adapter.record_fill(token, side, size, price, is_maker=is_user_maker)
                    except Exception:
                        pass
                    print("Position after matching is ", global_state.positions[str(token)])
                    print("Last trade update is ", global_state.last_trade_update)
                    print("Performing is ", global_state.performing)
                    print("Performing timestamps is ", global_state.performing_timestamps)
                    asyncio.create_task(perform_trade(market))
                elif status == 'MINED':
                    remove_from_performing(col, row.get('id'))

            elif event_type == 'order':
                print("ORDER EVENT FOR: ", row.get('market'), " STATUS: ",  row.get('status'), " TYPE: ", row.get('type'), " SIDE: ", side, "  ORIGINAL SIZE: ", row.get('original_size'), " SIZE MATCHED: ", row.get('size_matched'))
               
                set_order(token, side, float(row.get('original_size')) - float(row.get('size_matched')), row.get('price'))
                asyncio.create_task(perform_trade(market))

    else:
        print(f"User date received for {market} but its not in")
