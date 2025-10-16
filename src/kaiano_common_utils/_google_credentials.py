import json
import os

import gspread
from google.oauth2 import service_account
from googleapiclient.discovery import build

from kaiano_common_utils import logger as log

log = log.get_logger()


def _load_credentials():
    """Load credentials either from GitHub secret (GOOGLE_CREDENTIALS_JSON) or local credentials.json.
    If GOOGLE_CREDENTIALS_JSON is set but contains invalid JSON or is not a dict, logs a warning and falls back to credentials.json.
    """
    creds_json = os.getenv("GOOGLE_CREDENTIALS_JSON")
    SCOPES = [
        "https://www.googleapis.com/auth/drive",
        "https://www.googleapis.com/auth/spreadsheets",
    ]
    if creds_json:
        try:
            creds_dict = json.loads(creds_json)
            if not isinstance(creds_dict, dict):
                log.warning(
                    "GOOGLE_CREDENTIALS_JSON did not decode to a dictionary. Falling back to credentials.json."
                )
                raise ValueError("Decoded JSON is not a dict")
            return service_account.Credentials.from_service_account_info(
                creds_dict,
                scopes=SCOPES,
            )
        except (json.JSONDecodeError, ValueError, TypeError) as e:
            log.warning(
                f"Invalid GOOGLE_CREDENTIALS_JSON environment variable: {e}. Falling back to credentials.json."
            )
    # Fallback to credentials.json for local development or if env var is missing/invalid
    return service_account.Credentials.from_service_account_file(
        "credentials.json",
        scopes=SCOPES,
    )


def get_drive_client():
    creds = _load_credentials()
    return build("drive", "v3", credentials=creds)


def get_sheets_client():
    """Return raw Sheets API client (Google API Resource)"""
    creds = _load_credentials()
    return build("sheets", "v4", credentials=creds)


def get_gspread_client():
    """Return gspread client for convenient worksheet editing"""
    creds = _load_credentials()
    return gspread.authorize(creds)
