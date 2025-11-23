import asyncio                      # Asynchronous I/O
import json                        # JSON handling
import websockets                  # WebSocket client
import traceback                   # Exception handling

from poly_data.data_processing import process_data, process_user_data
import poly_data.global_state as global_state


async def connect_market_websocket(chunk):
    """
    Connects to the Polymarket market WebSocket API, subscribes to market updates
    for a given chunk of assets, and processes incoming data.

    This function handles the entire lifecycle of the WebSocket connection,
    including sending the subscription message and processing messages in a loop.
    It is designed to be resilient, with automatic reconnection handled by the
    calling script.

    Args:
        chunk (list): A list of token IDs (as strings) to subscribe to for
                      market data updates.
    """
    uri = "wss://ws-subscriptions-clob.polymarket.com/ws/market"
    async with websockets.connect(uri, ping_interval=5, ping_timeout=None) as websocket:
        # Prepare and send subscription message
        message = {"assets_ids": chunk}
        await websocket.send(json.dumps(message))

        print("\n")
        print(f"Sent market subscription message: {message}")

        try:
            # Process incoming market data indefinitely
            while True:
                message = await websocket.recv()
                json_data = json.loads(message)
                # Process order book updates and trigger trading as needed
                process_data(json_data)
        except websockets.ConnectionClosed:
            print("Connection closed in market websocket")
            print(traceback.format_exc())
        except Exception as e:
            print(f"Exception in market websocket: {e}")
            print(traceback.format_exc())
        finally:
            # Brief delay before attempting to reconnect
            await asyncio.sleep(5)


async def connect_user_websocket():
    """
    Connects to the Polymarket user WebSocket API, authenticates, and processes
    user-specific data like order updates and trade confirmations.

    This function manages the user data WebSocket connection, handling
    authentication and message processing. Reconnection logic is managed by the
    calling script.
    """
    uri = "wss://ws-subscriptions-clob.polymarket.com/ws/user"

    async with websockets.connect(uri, ping_interval=5, ping_timeout=None) as websocket:
        # Prepare authentication message with API credentials
        message = {
            "type": "user",
            "auth": {
                "apiKey": global_state.client.client.creds.api_key, 
                "secret": global_state.client.client.creds.api_secret,  
                "passphrase": global_state.client.client.creds.api_passphrase
            }
        }

        # Send authentication message
        await websocket.send(json.dumps(message))

        print("\n")
        print(f"Sent user subscription message")

        try:
            # Process incoming user data indefinitely
            while True:
                message = await websocket.recv()
                json_data = json.loads(message)
                # Process trade and order updates
                process_user_data(json_data)
        except websockets.ConnectionClosed:
            print("Connection closed in user websocket")
            print(traceback.format_exc())
        except Exception as e:
            print(f"Exception in user websocket: {e}")
            print(traceback.format_exc())
        finally:
            # Brief delay before attempting to reconnect
            await asyncio.sleep(5)