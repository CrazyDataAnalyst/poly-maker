import poly_data.global_state as global_state
from poly_data.utils import get_sheet_df
import time
import poly_data.global_state as global_state


def update_positions(avgOnly=False):
    """
    Updates the global positions state by fetching the latest data from the client.

    This function can perform a full update (size and average price) or an
    average price-only update. It includes logic to avoid updating positions
    if there are pending trades.

    Args:
        avgOnly (bool, optional): If True, only the average price of positions
                                  is updated. Defaults to False.
    """
    pos_df = global_state.client.get_all_positions()

    for idx, row in pos_df.iterrows():
        asset = str(row['asset'])

        if asset in  global_state.positions:
            position = global_state.positions[asset].copy()
        else:
            position = {'size': 0, 'avgPrice': 0}

        position['avgPrice'] = row['avgPrice']

        if not avgOnly:
            position['size'] = row['size']
        else:
            
            for col in [f"{asset}_sell", f"{asset}_buy"]:
                #need to review this
                if col not in global_state.performing or not isinstance(global_state.performing[col], set) or len(global_state.performing[col]) == 0:
                    try:
                        old_size = position['size']
                    except:
                        old_size = 0

                    if asset in  global_state.last_trade_update:
                        if time.time() - global_state.last_trade_update[asset] < 5:
                            print(f"Skipping update for {asset} because last trade update was less than 5 seconds ago")
                            continue

                    if old_size != row['size']:
                        print(f"No trades are pending. Updating position from {old_size} to {row['size']} and avgPrice to {row['avgPrice']} using API")
    
                    position['size'] = row['size']
                else:
                    print(f"ALERT: Skipping update for {asset} because there are trades pending for {col} looking like {global_state.performing[col]}")
    
        global_state.positions[asset] = position


def get_position(token):
    """
    Retrieves the current position for a given token.

    Args:
        token (str or int): The token identifier.

    Returns:
        dict: A dictionary containing the size and average price of the position,
              or a default dictionary with 0 values if no position exists.
    """
    token = str(token)
    if token in global_state.positions:
        return global_state.positions[token]
    else:
        return {'size': 0, 'avgPrice': 0}


def set_position(token, side, size, price, source='websocket'):
    """
    Sets or updates the position for a given token based on a trade.

    Args:
        token (str or int): The token identifier.
        side (str): The side of the trade ('buy' or 'sell').
        size (float): The size of the trade.
        price (float): The price of the trade.
        source (str, optional): The source of the position update. Defaults to
                               'websocket'.
    """
    token = str(token)
    size = float(size)
    price = float(price)

    global_state.last_trade_update[token] = time.time()
    
    if side.lower() == 'sell':
        size *= -1

    if token in global_state.positions:
        
        prev_price = global_state.positions[token]['avgPrice']
        prev_size = global_state.positions[token]['size']


        if size > 0:
            if prev_size == 0:
                # Starting a new position
                avgPrice_new = price
            else:
                # Buying more; update average price
                avgPrice_new = (prev_price * prev_size + price * size) / (prev_size + size)
        elif size < 0:
            # Selling; average price remains the same
            avgPrice_new = prev_price
        else:
            # No change in position
            avgPrice_new = prev_price


        global_state.positions[token]['size'] += size
        global_state.positions[token]['avgPrice'] = avgPrice_new
    else:
        global_state.positions[token] = {'size': size, 'avgPrice': price}

    print(f"Updated position from {source}, set to ", global_state.positions[token])


def update_orders():
    """
    Updates the global orders state by fetching all open orders from the client.

    This function also includes logic to cancel orders if multiple open orders
    are found for the same token.
    """
    all_orders = global_state.client.get_all_orders()

    orders = {}

    if len(all_orders) > 0:
            for token in all_orders['asset_id'].unique():
                
                if token not in orders:
                    orders[str(token)] = {'buy': {'price': 0, 'size': 0}, 'sell': {'price': 0, 'size': 0}}

                curr_orders = all_orders[all_orders['asset_id'] == str(token)]
                
                if len(curr_orders) > 0:
                    sel_orders = {}
                    sel_orders['buy'] = curr_orders[curr_orders['side'] == 'BUY']
                    sel_orders['sell'] = curr_orders[curr_orders['side'] == 'SELL']

                    for type in ['buy', 'sell']:
                        curr = sel_orders[type]

                        if len(curr) > 1:
                            print("Multiple orders found, cancelling")
                            global_state.client.cancel_all_asset(token)
                            orders[str(token)] = {'buy': {'price': 0, 'size': 0}, 'sell': {'price': 0, 'size': 0}}
                        elif len(curr) == 1:
                            orders[str(token)][type]['price'] = float(curr.iloc[0]['price'])
                            orders[str(token)][type]['size'] = float(curr.iloc[0]['original_size'] - curr.iloc[0]['size_matched'])

    global_state.orders = orders


def get_order(token):
    """
    Retrieves the current open orders for a given token.

    Args:
        token (str or int): The token identifier.

    Returns:
        dict: A dictionary containing the buy and sell orders for the token,
              or a default dictionary with empty orders if no orders exist.
    """
    token = str(token)
    if token in global_state.orders:

        if 'buy' not in global_state.orders[token]:
            global_state.orders[token]['buy'] = {'price': 0, 'size': 0}

        if 'sell' not in global_state.orders[token]:
            global_state.orders[token]['sell'] = {'price': 0, 'size': 0}

        return global_state.orders[token]
    else:
        return {'buy': {'price': 0, 'size': 0}, 'sell': {'price': 0, 'size': 0}}
    

def set_order(token, side, size, price):
    """
    Sets or updates the record of an open order.

    Args:
        token (str or int): The token identifier.
        side (str): The side of the order ('buy' or 'sell').
        size (float): The size of the order.
        price (float): The price of the order.
    """
    curr = {}
    curr = {side: {'price': 0, 'size': 0}}

    curr[side]['size'] = float(size)
    curr[side]['price'] = float(price)

    global_state.orders[str(token)] = curr
    print("Updated order, set to ", curr)


def update_markets():
    """
    Updates the market data and parameters from the Google Sheet.

    This function fetches the latest market data and hyperparameters and updates
    the global state. It also populates the token mappings and performing sets.
    """
    received_df, received_params = get_sheet_df()

    if len(received_df) > 0:
        global_state.df, global_state.params = received_df.copy(), received_params
    

    for _, row in global_state.df.iterrows():
        for col in ['token1', 'token2']:
            row[col] = str(row[col])

        if row['token1'] not in global_state.all_tokens:
            global_state.all_tokens.append(row['token1'])

        if row['token1'] not in global_state.REVERSE_TOKENS:
            global_state.REVERSE_TOKENS[row['token1']] = row['token2']

        if row['token2'] not in global_state.REVERSE_TOKENS:
            global_state.REVERSE_TOKENS[row['token2']] = row['token1']

        for col2 in [f"{row['token1']}_buy", f"{row['token1']}_sell", f"{row['token2']}_buy", f"{row['token2']}_sell"]:
            if col2 not in global_state.performing:
                global_state.performing[col2] = set()