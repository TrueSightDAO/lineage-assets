#!/usr/bin/env python3
"""
Google Sheets QR Codes Batch Fetch

This script fetches QR codes in bulk from a Google Sheet using a service account.
Ensure you have a Google service account key file named 'gdrive_key.json' in the project root
(ignored by Git) containing your credentials in JSON format.

Install dependencies:
    pip install google-auth google-auth-oauthlib google-auth-httplib2 google-api-python-client

Usage:
    python gdrive.py [--credentials CREDENTIALS_FILE] [--sheet-url SHEET_URL] [--sheet-name SHEET_NAME]
"""
import argparse
import os
import re
import sys

from googleapiclient.discovery import build
import google.auth
from google.oauth2 import service_account
# Configuration variables
DEFAULT_CREDENTIALS_FILE = 'gdrive_key.json'
DEFAULT_SHEET_URL = 'https://docs.google.com/spreadsheets/d/1GE7PUq-UT6x2rBN-Q2ksogbWpgyuh2SaxJyG_uEK6PU/edit?gid=472328231'
DEFAULT_SHEET_NAME = 'Agroverse QR codes'
BASE_QR_CHECK_URL = 'https://edgar.truesight.me/agroverse/qr-code-check?qr_code='


class GDrive:
    """
    GDrive client to fetch QR codes from a Google Sheet and optionally update values.
    """

    # Use full Sheets scope to allow both read and write operations
    SCOPES = ['https://www.googleapis.com/auth/spreadsheets']

    def __init__(self, credentials_path: str = None):
        """
        Initialize GDrive client.

        :param credentials_path: Optional path to a service account JSON credentials file.
                                 If not provided, application default credentials will be used.
        """
        # Determine credentials file (defaults to DEFAULT_CREDENTIALS_FILE)
        credentials_file = credentials_path or DEFAULT_CREDENTIALS_FILE
        if credentials_file and os.path.exists(credentials_file):
            self.creds = service_account.Credentials.from_service_account_file(
                credentials_file, scopes=self.SCOPES
            )
        else:
            creds, _ = google.auth.default(scopes=self.SCOPES)
            self.creds = creds

    def list_qr_check_urls(self, sheet_url: str, sheet_name: str) -> list:
        """
        Fetches values from the first column (column A) starting at row 2 of the specified sheet,
        constructs check URLs for each QR code, prints them, and returns the list.

        :param sheet_url: URL of the Google Sheet.
        :param sheet_name: Name of the worksheet/tab within the spreadsheet.
        :return: List of constructed QR check URLs.
        """
        sheet_id = self._extract_sheet_id(sheet_url)
        service = build('sheets', 'v4', credentials=self.creds)
        # Range A2 to end of column A
        range_name = f"'{sheet_name}'!A2:A"
        sheet = service.spreadsheets()
        result = sheet.values().get(spreadsheetId=sheet_id, range=range_name).execute()
        values = result.get('values', [])

        base_url = BASE_QR_CHECK_URL
        urls = []
        for row in values:
            if row:
                qr_code = row[0].strip()
                if qr_code:
                    url = base_url + qr_code
                    urls.append(url)
                    print(url)
        return urls

    @staticmethod
    def _extract_sheet_id(sheet_url: str) -> str:
        """
        Extract the spreadsheet ID from its URL.

        :param sheet_url: Full URL of the Google Sheet.
        :return: Spreadsheet ID.
        :raises ValueError: if the URL is invalid or ID cannot be parsed.
        """
        match = re.search(r'/d/([a-zA-Z0-9-_]+)', sheet_url)
        if not match:
            raise ValueError(f"Could not parse spreadsheet ID from URL: {sheet_url}")
        return match.group(1)
        
def main():
    parser = argparse.ArgumentParser(
        description='Fetch QR codes from a Google Sheet and print check URLs'
    )
    parser.add_argument(
        '-c', '--credentials',
        default=DEFAULT_CREDENTIALS_FILE,
        help='Path to service account credentials JSON file (default: %(default)s)'
    )
    parser.add_argument(
        '-u', '--sheet-url',
        dest='sheet_url',
        default=DEFAULT_SHEET_URL,
        help='URL of the Google Sheet (default: %(default)s)'
    )
    parser.add_argument(
        '-n', '--sheet-name',
        dest='sheet_name',
        default=DEFAULT_SHEET_NAME,
        help='Worksheet/tab name in the spreadsheet (default: %(default)s)'
    )
    args = parser.parse_args()
    gd = GDrive(credentials_path=args.credentials)
    try:
        gd.list_qr_check_urls(args.sheet_url, args.sheet_name)
    except Exception as e:
        print(f'Error: {e}', file=sys.stderr)
        sys.exit(1)

if __name__ == '__main__':
    main()