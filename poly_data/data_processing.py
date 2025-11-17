import json
from sortedcontainers import SortedDict
import poly_data.global_state as global_state
import poly_data.CONSTANTS as CONSTANTS

from trading import perform_trade
import time 
import asyncio
from poly_data.data_utils import set_position, set_order, update_positions

def process_book_data(asset, j):
    global_state.all_data[asset] = {
        'asset_id': j.get('asset_id'),  # token_id for the Yes token
        'bids': SortedDict(),
        'asks': SortedDict()
    }

    global_state.all_data[asset]['bids'].update({float(entry['price']): float(entry['size']) for entry in j.get('bids',[])})
    global_state.all_data[asset]['asks'].update({float(entry['price']): float(entry['size']) for entry in j.get('asks',[])})

def process_price_change(asset, asset_id, side, price_level, new_size):
    # Check if this asset_id matches what we stored (to avoid duplicate updates)
    if asset not in global_state.all_data:
        return  # Asset not initialized yet
    stored_asset_id = global_state.all_data[asset].get('asset_id')
    
    if stored_asset_id and asset_id != stored_asset_id:
        return  # Skip updates for the No token to prevent duplicated updates
        
    if side == 'bids':
        book = global_state.all_data[asset]['bids']
    else:
        book = global_state.all_data[asset]['asks']

    if new_size == 0:
        if price_level in book:
            del book[price_level]
    else:
        book[price_level] = new_size

def process_data(json_data, trade=True):
    
    if not isinstance(json_data, list): #Add data format handling
        json_data = [json_data]
        
    for j in json_data:
        event_type = j.get('event_type')
        asset = j.get('market')
        asset_id = j.get('asset_id')

        if event_type == 'book':
            process_book_data(asset, j)

            if trade:
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

                if trade:
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
