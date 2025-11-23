from dotenv import load_dotenv          # Environment variable management
import os                           # Operating system interface

# Polymarket API client libraries
from py_clob_client.client import ClobClient
from py_clob_client.clob_types import OrderArgs, BalanceAllowanceParams, AssetType, PartialCreateOrderOptions
from py_clob_client.constants import POLYGON

# Web3 libraries for blockchain interaction
from web3 import Web3
from web3.middleware import ExtraDataToPOAMiddleware
from eth_account import Account

import requests                     # HTTP requests
import pandas as pd                 # Data analysis
import json                         # JSON processing
import subprocess                   # For calling external processes

from py_clob_client.clob_types import OpenOrderParams

# Smart contract ABIs
from poly_data.abis import NegRiskAdapterABI, ConditionalTokenABI, erc20_abi

# Load environment variables
load_dotenv()


class PolymarketClient:
    """
    Client for interacting with Polymarket's API and smart contracts.
    
    This class provides methods for:
    - Creating and managing orders
    - Querying order book data
    - Checking balances and positions
    - Merging positions
    
    The client connects to both the Polymarket API and the Polygon blockchain.
    """
    
    def __init__(self, pk='default') -> None:
        """
        Initializes the Polymarket client, setting up connections to the Polymarket API
        and the Polygon blockchain. It configures the necessary credentials, contract
        instances, and Web3 provider.

        Args:
            pk (str, optional): A private key identifier. Defaults to 'default',
                                which prompts the client to load the key from environment
                                variables.
        """
        host="https://clob.polymarket.com"

        # Get credentials from environment variables
        key=os.getenv("PK")
        browser_address = os.getenv("BROWSER_ADDRESS")

        # Don't print sensitive wallet information
        print("Initializing Polymarket client...")
        chain_id=POLYGON
        self.browser_wallet=Web3.to_checksum_address(browser_address)

        # Initialize the Polymarket API client
        self.client = ClobClient(
            host=host,
            key=key,
            chain_id=chain_id,
            funder=self.browser_wallet,
            signature_type=2
        )

        # Set up API credentials
        self.creds = self.client.create_or_derive_api_creds()
        self.client.set_api_creds(creds=self.creds)
        
        # Initialize Web3 connection to Polygon
        web3 = Web3(Web3.HTTPProvider("https://polygon-rpc.com"))
        web3.middleware_onion.inject(ExtraDataToPOAMiddleware, layer=0)
        
        # Set up USDC contract for balance checks
        self.usdc_contract = web3.eth.contract(
            address="0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174", 
            abi=erc20_abi
        )

        # Store key contract addresses
        self.addresses = {
            'neg_risk_adapter': '0xd91E80cF2E7be2e162c6513ceD06f1dD0dA35296',
            'collateral': '0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174',
            'conditional_tokens': '0x4D97DCd97eC945f40cF65F87097ACe5EA0476045'
        }

        # Initialize contract interfaces
        self.neg_risk_adapter = web3.eth.contract(
            address=self.addresses['neg_risk_adapter'], 
            abi=NegRiskAdapterABI
        )

        self.conditional_tokens = web3.eth.contract(
            address=self.addresses['conditional_tokens'], 
            abi=ConditionalTokenABI
        )

        self.web3 = web3

    
    def create_order(self, marketId, action, price, size, neg_risk=False):
        """
        Creates and submits a new order to the Polymarket order book.

        This method constructs an order with the specified parameters, signs it, and
        posts it to the Polymarket API. It handles both standard and negative risk
        markets.

        Args:
            marketId (str): The ID of the market token to be traded.
            action (str): The order action, either "BUY" or "SELL".
            price (float): The price for the order, typically in the 0-1 range for
                           prediction markets.
            size (float): The size of the order in USDC.
            neg_risk (bool, optional): Specifies if the market is a negative risk
                                       market. Defaults to False.

        Returns:
            dict: A dictionary containing the API response with order details upon
                  successful creation, or an empty dictionary if an error occurs.
        """
        # Create order parameters
        order_args = OrderArgs(
            token_id=str(marketId),
            price=price,
            size=size,
            side=action
        )

        signed_order = None

        # Handle regular vs negative risk markets differently
        if neg_risk == False:
            signed_order = self.client.create_order(order_args)
        else:
            signed_order = self.client.create_order(order_args, options=PartialCreateOrderOptions(neg_risk=True))
            
        try:
            # Submit the signed order to the API
            resp = self.client.post_order(signed_order)
            return resp
        except Exception as ex:
            print(ex)
            return {}

    def get_order_book(self, market):
        """
        Retrieves the current order book for a specific market.

        Args:
            market (str): The ID of the market to query.

        Returns:
            tuple: A tuple containing two pandas DataFrames: (bids_df, asks_df).
                   - bids_df: DataFrame of bid orders.
                   - asks_df: DataFrame of ask orders.
        """
        orderBook = self.client.get_order_book(market)
        return pd.DataFrame(orderBook.bids).astype(float), pd.DataFrame(orderBook.asks).astype(float)


    def get_usdc_balance(self):
        """
        Retrieves the USDC balance of the connected wallet.

        Returns:
            float: The USDC balance, adjusted for decimals.
        """
        return self.usdc_contract.functions.balanceOf(self.browser_wallet).call() / 10**6
     
    def get_pos_balance(self):
        """
        Retrieves the total value of all positions for the connected wallet from the
        Polymarket data API.

        Returns:
            float: The total value of all positions in USDC.
        """
        res = requests.get(f'https://data-api.polymarket.com/value?user={self.browser_wallet}')
        return float(res.json()['value'])

    def get_total_balance(self):
        """
        Calculates the total account value by combining the USDC balance and the
        total position value.

        Returns:
            float: The total account value in USDC.
        """
        return self.get_usdc_balance() + self.get_pos_balance()

    def get_all_positions(self):
        """
        Retrieves all positions for the connected wallet across all markets from the
        Polymarket data API.

        Returns:
            pandas.DataFrame: A DataFrame containing detailed information about each
                              position, such as market, size, and average price.
        """
        res = requests.get(f'https://data-api.polymarket.com/positions?user={self.browser_wallet}')
        return pd.DataFrame(res.json())
    
    def get_raw_position(self, tokenId):
        """
        Retrieves the raw token balance for a specific market outcome token directly
        from the smart contract.

        Args:
            tokenId (int): The token ID to query.

        Returns:
            int: The raw token amount, not adjusted for decimals.
        """
        return int(self.conditional_tokens.functions.balanceOf(self.browser_wallet, int(tokenId)).call())

    def get_position(self, tokenId):
        """
        Retrieves both the raw and formatted position size for a specific token.

        This method filters out very small "dust" amounts by treating any position
        less than 1 share as 0.

        Args:
            tokenId (int): The token ID to query.

        Returns:
            tuple: A tuple containing:
                   - raw_position (int): The raw token amount.
                   - shares (float): The position size in decimal shares (e.g., 10.5).
        """
        raw_position = self.get_raw_position(tokenId)
        shares = float(raw_position / 1e6)

        # Ignore very small positions (dust)
        if shares < 1:
            shares = 0

        return raw_position, shares
    
    def get_all_orders(self):
        """
        Retrieves all open orders for the connected wallet.

        Returns:
            pandas.DataFrame: A DataFrame containing details of all open orders.
        """
        orders_df = pd.DataFrame(self.client.get_orders())

        # Convert numeric columns to float
        for col in ['original_size', 'size_matched', 'price']:
            if col in orders_df.columns:
                orders_df[col] = orders_df[col].astype(float)

        return orders_df
    
    def get_market_orders(self, market):
        """
        Retrieves all open orders for a specific market.

        Args:
            market (str): The ID of the market to query.

        Returns:
            pandas.DataFrame: A DataFrame containing details of open orders for the
                              specified market.
        """
        orders_df = pd.DataFrame(self.client.get_orders(OpenOrderParams(
            market=market,
        )))

        # Convert numeric columns to float
        for col in ['original_size', 'size_matched', 'price']:
            if col in orders_df.columns:
                orders_df[col] = orders_df[col].astype(float)

        return orders_df
    

    def cancel_all_asset(self, asset_id):
        """
        Cancels all open orders for a specific asset token.

        Args:
            asset_id (str): The asset token ID.
        """
        self.client.cancel_market_orders(asset_id=str(asset_id))


    
    def cancel_all_market(self, marketId):
        """
        Cancels all open orders in a specific market.

        Args:
            marketId (str): The market ID.
        """
        self.client.cancel_market_orders(market=marketId)

    
    def merge_positions(self, amount_to_merge, condition_id, is_neg_risk_market):
        """
        Merge positions in a market to recover collateral.
        
        This function calls the external poly_merger Node.js script to execute
        the merge operation on-chain. When you hold both YES and NO positions
        in the same market, merging them recovers your USDC.
        
        Args:
            amount_to_merge (int): Raw token amount to merge (before decimal conversion)
            condition_id (str): Market condition ID
            is_neg_risk_market (bool): Whether this is a negative risk market
            
        Returns:
            str: Transaction hash or output from the merge script
            
        Raises:
            Exception: If the merge operation fails
        """
        amount_to_merge_str = str(amount_to_merge)

        # Prepare the command to run the JavaScript script
        node_command = f'node poly_merger/merge.js {amount_to_merge_str} {condition_id} {"true" if is_neg_risk_market else "false"}'
        print(node_command)

        # Run the command and capture the output
        result = subprocess.run(node_command, shell=True, capture_output=True, text=True)
        
        # Check if there was an error
        if result.returncode != 0:
            print("Error:", result.stderr)
            raise Exception(f"Error in merging positions: {result.stderr}")
        
        print("Done merging")

        # Return the transaction hash or output
        return result.stdout