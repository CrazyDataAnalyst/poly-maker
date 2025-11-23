from google.oauth2.service_account import Credentials
import gspread
import os
import pandas as pd
import requests
import re
from dotenv import load_dotenv

load_dotenv()


def get_spreadsheet(read_only=False):
    """
    Initializes and returns a gspread Spreadsheet object for authenticated access
    or a read-only wrapper for public access via CSV export.

    Args:
        read_only (bool, optional): If True, forces the use of the read-only
                                  wrapper, which is useful when credentials are
                                  not available. Defaults to False.

    Returns:
        gspread.Spreadsheet or ReadOnlySpreadsheet: An object to interact with
                                                      the Google Sheet.

    Raises:
        ValueError: If the SPREADSHEET_URL environment variable is not set.
        FileNotFoundError: If credentials are not found and read_only is False.
    """
    spreadsheet_url = os.getenv("SPREADSHEET_URL")
    if not spreadsheet_url:
        raise ValueError("SPREADSHEET_URL environment variable is not set")
    
    # Check for credentials
    creds_file = 'credentials.json' if os.path.exists('credentials.json') else '../credentials.json'
    
    if not os.path.exists(creds_file):
        if read_only:
            return ReadOnlySpreadsheet(spreadsheet_url)
        else:
            raise FileNotFoundError(f"Credentials file not found at {creds_file}. Use read_only=True for read-only access.")
    
    # Normal authenticated access
    scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
    credentials = Credentials.from_service_account_file(creds_file, scopes=scope)
    client = gspread.authorize(credentials)
    spreadsheet = client.open_by_url(spreadsheet_url)
    return spreadsheet


class ReadOnlySpreadsheet:
    """
    A read-only wrapper for Google Sheets that uses public CSV export URLs.
    This class is used when authenticated access is not available.
    """
    
    def __init__(self, spreadsheet_url):
        self.spreadsheet_url = spreadsheet_url
        self.sheet_id = self._extract_sheet_id(spreadsheet_url)
        
    def _extract_sheet_id(self, url):
        """
        Extracts the sheet ID from a Google Sheets URL.

        Args:
            url (str): The Google Sheets URL.

        Returns:
            str: The extracted sheet ID.
        """
        match = re.search(r'/spreadsheets/d/([a-zA-Z0-9-_]+)', url)
        if not match:
            raise ValueError("Invalid Google Sheets URL")
        return match.group(1)
    
    def worksheet(self, title):
        """
        Returns a read-only worksheet object.

        Args:
            title (str): The title of the worksheet.

        Returns:
            ReadOnlyWorksheet: A read-only worksheet object.
        """
        return ReadOnlyWorksheet(self.sheet_id, title)


class ReadOnlyWorksheet:
    """
    Represents a read-only worksheet that fetches data via CSV export.
    """
    
    def __init__(self, sheet_id, title):
        self.sheet_id = sheet_id
        self.title = title
        
    def get_all_records(self):
        """
        Fetches all records from the worksheet as a list of dictionaries.

        Returns:
            list: A list of dictionaries representing the rows of the sheet.
        """
        try:
            # URL encode the sheet title to handle spaces and special characters
            import urllib.parse
            encoded_title = urllib.parse.quote(self.title)
            
            # Map known sheet names to likely GID positions
            # Based on the sheet order: Full Markets, All Markets, Volatility Markets, Selected Markets, Hyperparameters
            sheet_gid_mapping = {
                'Full Markets': 0,
                'All Markets': 1, 
                'Volatility Markets': 2,
                'Selected Markets': 3,
                'Hyperparameters': 4
            }
            
            # Try multiple URL formats for accessing the sheet
            urls_to_try = [
                f"https://docs.google.com/spreadsheets/d/{self.sheet_id}/gviz/tq?tqx=out:csv&sheet={encoded_title}",
                f"https://docs.google.com/spreadsheets/d/{self.sheet_id}/gviz/tq?tqx=out:csv&sheet={self.title}",
            ]
            
            # Add GID-based URL if we know the likely position for this sheet
            if self.title in sheet_gid_mapping:
                gid = sheet_gid_mapping[self.title]
                urls_to_try.append(f"https://docs.google.com/spreadsheets/d/{self.sheet_id}/export?format=csv&gid={gid}")
            
            # Also try a few common GID positions as fallback
            for gid in [0, 1, 2, 3, 4]:
                urls_to_try.append(f"https://docs.google.com/spreadsheets/d/{self.sheet_id}/export?format=csv&gid={gid}")
            
            for csv_url in urls_to_try:
                try:
                    print(f"Trying to fetch sheet '{self.title}' from: {csv_url}")
                    response = requests.get(csv_url, timeout=30)
                    response.raise_for_status()
                    
                    # Read CSV data into DataFrame
                    from io import StringIO
                    df = pd.read_csv(StringIO(response.text))
                    
                    # Check if we got meaningful data (not empty or error response)
                    if not df.empty and len(df.columns) > 1:
                        # For Hyperparameters sheet, verify it has the expected columns
                        if self.title == 'Hyperparameters':
                            expected_cols = ['type', 'param', 'value']
                            if all(col in df.columns for col in expected_cols):
                                print(f"Successfully fetched {len(df)} hyperparameter records")
                                return df.to_dict('records')
                            else:
                                print(f"Sheet doesn't match Hyperparameters format. Columns: {list(df.columns)}")
                                continue
                        else:
                            print(f"Successfully fetched {len(df)} records from sheet '{self.title}'")
                            # Convert to list of dictionaries (same format as gspread)
                            return df.to_dict('records')
                    
                except Exception as url_error:
                    print(f"Failed with URL {csv_url}: {url_error}")
                    continue
            
            print(f"All URL attempts failed for sheet '{self.title}'")
            return []
            
        except Exception as e:
            print(f"Warning: Could not fetch data from sheet '{self.title}': {e}")
            return []
    
    def get_all_values(self):
        """
        Fetches all values from the worksheet as a list of lists.

        Returns:
            list: A list of lists representing the rows and columns of the sheet.
        """
        try:
            csv_url = f"https://docs.google.com/spreadsheets/d/{self.sheet_id}/gviz/tq?tqx=out:csv&sheet={self.title}"
            response = requests.get(csv_url, timeout=30)
            response.raise_for_status()
            
            # Read CSV and return as list of lists
            from io import StringIO
            df = pd.read_csv(StringIO(response.text))
            
            # Include headers and convert to list of lists
            headers = [df.columns.tolist()]
            data = df.values.tolist()
            return headers + data
            
        except Exception as e:
            print(f"Warning: Could not fetch data from sheet '{self.title}': {e}")
            return []


