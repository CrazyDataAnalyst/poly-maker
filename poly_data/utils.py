import json
from poly_utils.google_utils import get_spreadsheet
import pandas as pd 
import os


def pretty_print(txt, dic):
    """
    Prints a dictionary in a formatted JSON string for better readability.

    Args:
        txt (str): A descriptive text to print before the dictionary.
        dic (dict): The dictionary to be pretty-printed.
    """
    print("\n", txt, json.dumps(dic, indent=4))


def get_sheet_df(read_only=None):
    """
    Fetches and processes data from the Google Sheet, combining selected markets
    with all market data and extracting hyperparameters.

    This function handles both read-only and authenticated access to the Google
    Sheet, automatically detecting the mode based on the presence of credentials.

    Args:
        read_only (bool, optional): If True, forces read-only mode. If None,
                                  the function auto-detects based on credentials.
                                  Defaults to None.

    Returns:
        tuple: A tuple containing:
               - result (pandas.DataFrame): A DataFrame of selected markets merged
                 with all market data.
               - hyperparams (dict): A dictionary of hyperparameters, structured
                 by type.
    """
    all = 'All Markets'
    sel = 'Selected Markets'

    # Auto-detect read-only mode if not specified
    if read_only is None:
        creds_file = 'credentials.json' if os.path.exists('credentials.json') else '../credentials.json'
        read_only = not os.path.exists(creds_file)
        if read_only:
            print("No credentials found, using read-only mode")

    try:
        spreadsheet = get_spreadsheet(read_only=read_only)
    except FileNotFoundError:
        print("No credentials found, falling back to read-only mode")
        spreadsheet = get_spreadsheet(read_only=True)

    wk = spreadsheet.worksheet(sel)
    df = pd.DataFrame(wk.get_all_records())
    df = df[df['question'] != ""].reset_index(drop=True)

    wk2 = spreadsheet.worksheet(all)
    df2 = pd.DataFrame(wk2.get_all_records())
    df2 = df2[df2['question'] != ""].reset_index(drop=True)

    result = df.merge(df2, on='question', how='inner')

    wk_p = spreadsheet.worksheet('Hyperparameters')
    records = wk_p.get_all_records()
    hyperparams, current_type = {}, None

    for r in records:
        # Update current_type only when we have a non-empty type value
        # Handle both string and NaN values from pandas
        type_value = r['type']
        if type_value and str(type_value).strip() and str(type_value) != 'nan':
            current_type = str(type_value).strip()
        
        # Skip rows where we don't have a current_type set
        if current_type:
            # Convert numeric values to appropriate types
            value = r['value']
            try:
                # Try to convert to float if it's numeric
                if isinstance(value, str) and value.replace('.', '').replace('-', '').isdigit():
                    value = float(value)
                elif isinstance(value, (int, float)):
                    value = float(value)
            except (ValueError, TypeError):
                pass  # Keep as string if conversion fails
            
            hyperparams.setdefault(current_type, {})[r['param']] = value

    return result, hyperparams
