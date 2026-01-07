import random
import time
from typing import Any, Dict, List

from googleapiclient.errors import HttpError

from kaiano_common_utils import _google_credentials
from kaiano_common_utils import logger as log

log = log.get_logger()


# Helper functions for retryable Sheets API operations
def _is_retryable_http_error(error: HttpError) -> bool:
    status = getattr(getattr(error, "resp", None), "status", None)
    msg = str(error).lower()

    # Retry on transient / server-side failures
    if isinstance(status, int) and 500 <= status <= 599:
        return True

    # Too many requests
    if status == 429:
        return True

    # Some quota errors come back as 403 with a quota-related message
    if status == 403 and "quota" in msg:
        return True

    return False


def _sleep_with_backoff(
    *,
    attempt: int,
    delay: float,
    max_delay: float,
    context: str,
):
    # exponential backoff with jitter (0.7x–1.3x)
    wait = min(max_delay, delay) * (0.7 + random.random() * 0.6)
    log.warning(
        f"⚠️ Retryable Sheets API error while {context}; retrying in {wait:.1f}s (attempt {attempt})"
    )
    time.sleep(wait)
    return wait


# Helper for safe spreadsheet metadata retrieval with retries
def safe_get_spreadsheet_metadata(
    service, spreadsheet_id: str, max_retries: int = 3
) -> Dict:
    """
    Safely retrieves spreadsheet metadata with exponential backoff retries.
    """
    for attempt in range(max_retries):
        try:
            return service.spreadsheets().get(spreadsheetId=spreadsheet_id).execute()
        except HttpError as e:
            log.warning(
                f"Metadata fetch failed (attempt {attempt + 1}/{max_retries}): {e}"
            )
            if attempt == max_retries - 1:
                raise
            time.sleep(2**attempt)


def get_sheets_service():
    return _google_credentials.get_sheets_client()


def get_gspread_client():
    return _google_credentials.get_gspread_client()


def get_or_create_sheet(service, spreadsheet_id: str, sheet_name: str) -> None:
    log.debug(
        f"get_or_create_sheet called with spreadsheet_id={spreadsheet_id}, sheet_name={sheet_name}"
    )

    sheets_metadata = safe_get_spreadsheet_metadata(service, spreadsheet_id)

    sheet_titles = [s["properties"]["title"] for s in sheets_metadata.get("sheets", [])]
    log.debug(f"Existing sheet titles: {sheet_titles}")
    if sheet_name not in sheet_titles:
        log.debug(f"Creating new sheet tab: {sheet_name}")
        add_sheet_body = {
            "requests": [{"addSheet": {"properties": {"title": sheet_name}}}]
        }
        service.spreadsheets().batchUpdate(
            spreadsheetId=spreadsheet_id, body=add_sheet_body
        ).execute()
        log.debug(f"Sheet '{sheet_name}' created successfully.")
    else:
        log.debug(f"Sheet '{sheet_name}' already exists; no creation needed.")


def read_sheet(
    service,
    spreadsheet_id: str,
    range_name: str,
    max_retries: int = 8,
    base_delay: float = 1.0,
    max_delay: float = 60.0,
):
    log.debug(
        f"Reading sheet data from spreadsheet_id={spreadsheet_id}, range_name={range_name}"
    )

    delay = base_delay
    last_error: Exception | None = None

    for attempt in range(1, max_retries + 1):
        try:
            result = (
                service.spreadsheets()
                .values()
                .get(spreadsheetId=spreadsheet_id, range=range_name)
                .execute()
            )
            values = result.get("values", [])
            log.debug(f"Sheets API returned {len(values)} rows")
            return values

        except HttpError as error:
            last_error = error
            status = getattr(getattr(error, "resp", None), "status", None)

            if (not _is_retryable_http_error(error)) or attempt == max_retries:
                log.error(
                    f"An error occurred while reading sheet (attempt {attempt}/{max_retries}): {error}"
                )
                raise

            # exponential backoff with jitter (0.7x–1.3x)
            wait = min(max_delay, delay) * (0.7 + random.random() * 0.6)
            log.warning(
                f"⚠️ Retryable Sheets API error {status} while reading range '{range_name}' "
                f"({spreadsheet_id}); retrying in {wait:.1f}s (attempt {attempt}/{max_retries})"
            )
            time.sleep(wait)
            delay *= 2

        except Exception as error:
            last_error = error
            log.error(f"An error occurred while reading sheet: {error}")
            raise

    # Defensive: should be unreachable
    if last_error:
        raise last_error
    return []


def write_sheet(
    service,
    spreadsheet_id,
    range_name,
    values=None,
    max_retries: int = 8,
    base_delay: float = 1.0,
    max_delay: float = 60.0,
):
    log.debug(
        f"Writing data to sheet: spreadsheet_id={spreadsheet_id}, range_name={range_name}, number of rows={len(values) if values else 0}"
    )
    if values:
        preview = values[:3] if len(values) > 3 else values
        log.debug(f"Preview of values to write: {preview}")
    else:
        log.debug("No values provided to write.")

    log.debug(
        f"Calling Sheets API with spreadsheetId={spreadsheet_id}, range={range_name}"
    )
    body = {"values": values}

    delay = base_delay
    last_error: Exception | None = None

    for attempt in range(1, max_retries + 1):
        try:
            result = (
                service.spreadsheets()
                .values()
                .update(
                    spreadsheetId=spreadsheet_id,
                    range=range_name,
                    valueInputOption="RAW",
                    body=body,
                )
                .execute()
            )
            log.debug(
                f"write_sheet updated range {range_name} with {len(values) if values else 0} rows"
            )
            return result

        except HttpError as error:
            last_error = error
            if (not _is_retryable_http_error(error)) or attempt == max_retries:
                log.error(
                    f"An error occurred while writing to sheet (attempt {attempt}/{max_retries}): {error}"
                )
                raise

            _sleep_with_backoff(
                attempt=attempt,
                delay=delay,
                max_delay=max_delay,
                context=f"writing range '{range_name}' ({spreadsheet_id})",
            )
            delay *= 2

        except Exception as error:
            last_error = error
            log.error(f"An error occurred while writing to sheet: {error}")
            raise

    if last_error:
        raise last_error
    return None


def append_rows(
    service,
    spreadsheet_id: str,
    range_name: str,
    values: list,
    max_retries: int = 8,
    base_delay: float = 1.0,
    max_delay: float = 60.0,
) -> None:
    log.debug(
        f"Appending {len(values)} rows to spreadsheet_id={spreadsheet_id}, range_name={range_name}"
    )
    body = {"values": values}
    log.debug("Calling Sheets API to append rows...")

    delay = base_delay
    last_error: Exception | None = None

    for attempt in range(1, max_retries + 1):
        try:
            result = (
                service.spreadsheets()
                .values()
                .append(
                    spreadsheetId=spreadsheet_id,
                    range=range_name,
                    valueInputOption="RAW",
                    insertDataOption="INSERT_ROWS",
                    body=body,
                )
                .execute()
            )
            log.debug(f"Appended {len(values)} rows to {range_name}")
            return result

        except HttpError as error:
            last_error = error
            if (not _is_retryable_http_error(error)) or attempt == max_retries:
                log.error(
                    f"An error occurred while appending rows (attempt {attempt}/{max_retries}): {error}"
                )
                raise

            _sleep_with_backoff(
                attempt=attempt,
                delay=delay,
                max_delay=max_delay,
                context=f"appending to range '{range_name}' ({spreadsheet_id})",
            )
            delay *= 2

        except Exception as error:
            last_error = error
            log.error(f"An error occurred while appending rows: {error}")
            raise

    if last_error:
        raise last_error
    return None


# Ensure all required sheet tabs exist in a spreadsheet
def ensure_sheet_exists(
    service, spreadsheet_id: str, sheet_name: str, headers: list[str] = None
) -> None:
    log.debug(
        f"Ensuring sheet '{sheet_name}' exists in spreadsheet_id={spreadsheet_id}"
    )
    get_or_create_sheet(service, spreadsheet_id, sheet_name)
    if headers:
        existing = read_sheet(service, spreadsheet_id, f"{sheet_name}!1:1")
        if not existing:
            write_sheet(service, spreadsheet_id, f"{sheet_name}!A1", [headers])
            log.debug(f"Wrote headers to sheet '{sheet_name}': {headers}")
        else:
            log.debug(
                f"Headers already present in sheet '{sheet_name}'; no write needed."
            )


# Function to fetch spreadsheet metadata
def get_sheet_metadata(service, spreadsheet_id: str):
    log.debug(f"Retrieving spreadsheet metadata for ID={spreadsheet_id}")
    log.debug(f"Fetching spreadsheet metadata for ID={spreadsheet_id}")
    try:
        metadata = safe_get_spreadsheet_metadata(service, spreadsheet_id)
        log.debug(f"Metadata keys available: {list(metadata.keys())}")
        return metadata
    except HttpError as error:
        log.error(f"An error occurred while retrieving spreadsheet metadata: {error}")
        raise


def update_row(spreadsheet_id: str, range_: str, values: list[list[str]]):
    """
    Update a specific row in a Google Sheet.

    Args:
        spreadsheet_id (str): The ID of the spreadsheet.
        range_ (str): The A1-style range to update (e.g., "Processed!A2:C2").
        values (list[list[str]]): 2D list of values to set in the range.

    Example:
        update_row(
            "spreadsheet_id_here",
            "Processed!A2:C2",
            [["filename.m3u", "2025-10-09", "last_extvdj_line"]]
        )
    """
    service = get_sheets_service()
    log.debug(
        f"Updating row in spreadsheet_id={spreadsheet_id}, range={range_}, number of rows={len(values)}"
    )
    log.debug(f"Values to update: {values}")
    body = {"values": values}

    delay = 1.0
    max_retries = 8
    max_delay = 60.0
    last_error: Exception | None = None

    for attempt in range(1, max_retries + 1):
        try:
            result = (
                service.spreadsheets()
                .values()
                .update(
                    spreadsheetId=spreadsheet_id,
                    range=range_,
                    valueInputOption="USER_ENTERED",
                    body=body,
                )
                .execute()
            )
            log.debug(
                f"Row updated in range {range_} in spreadsheet_id={spreadsheet_id}"
            )
            return result

        except HttpError as error:
            last_error = error
            if (not _is_retryable_http_error(error)) or attempt == max_retries:
                log.error(
                    f"An error occurred while updating row (attempt {attempt}/{max_retries}): {error}"
                )
                raise

            _sleep_with_backoff(
                attempt=attempt,
                delay=delay,
                max_delay=max_delay,
                context=f"updating range '{range_}' ({spreadsheet_id})",
            )
            delay *= 2

        except Exception as error:
            last_error = error
            log.error(f"An error occurred while updating row: {error}")
            raise

    if last_error:
        raise last_error
    return None


def sort_sheet_by_column(
    service,
    spreadsheet_id: str,
    sheet_name: str,
    column_index: int,
    ascending: bool = True,
    start_row: int = 2,
    end_row: int = None,
):
    """
    Sort a sheet by a specific column.

    Args:
        spreadsheet_id (str): The ID of the spreadsheet.
        sheet_name (str): The name of the sheet tab.
        column_index (int): The 0-based column index to sort by.
        ascending (bool): Whether to sort ascending (True) or descending (False).
        start_row (int): Row index (1-based in UI, 0-based in API) to start sorting.
                         Default is 2 to skip header row.
        end_row (int): Optional end row index (exclusive). If None, will sort until the last row.
    """
    log.debug(
        f"Sorting sheet '{sheet_name}' on column {column_index} ({'ASC' if ascending else 'DESC'}) in spreadsheet_id={spreadsheet_id}"
    )
    log.debug(
        f"sort_sheet_by_column called with spreadsheet_id={spreadsheet_id}, "
        f"sheet_name={sheet_name}, column_index={column_index}, ascending={ascending}, "
        f"start_row={start_row}, end_row={end_row}"
    )
    try:
        # Get sheet ID from metadata
        metadata = safe_get_spreadsheet_metadata(service, spreadsheet_id)
        sheet_id = None
        for sheet in metadata.get("sheets", []):
            if sheet["properties"]["title"] == sheet_name:
                sheet_id = sheet["properties"]["sheetId"]
                break

        if sheet_id is None:
            log.warning(
                f"Sheet '{sheet_name}' not found in spreadsheet {spreadsheet_id}"
            )
            raise ValueError(
                f"Sheet '{sheet_name}' not found in spreadsheet {spreadsheet_id}"
            )

        sort_spec = {
            "dimensionIndex": column_index,
            "sortOrder": "ASCENDING" if ascending else "DESCENDING",
        }

        sort_range = {
            "sheetId": sheet_id,
            "startRowIndex": start_row - 1,  # Convert to 0-based
        }
        if end_row is not None:
            sort_range["endRowIndex"] = end_row

        request_body = {
            "requests": [{"sortRange": {"range": sort_range, "sortSpecs": [sort_spec]}}]
        }

        result = (
            service.spreadsheets()
            .batchUpdate(spreadsheetId=spreadsheet_id, body=request_body)
            .execute()
        )
        log.debug("Batch update executed")
        return result
    except HttpError as error:
        log.error(f"An error occurred while sorting sheet: {error}")
        raise


def get_sheet_id_by_name(sheet_service, spreadsheet_id: str, sheet_name: str) -> int:
    """
    Returns the numeric sheet ID of the given sheet name.
    """
    metadata = safe_get_spreadsheet_metadata(sheet_service, spreadsheet_id)
    for sheet in metadata.get("sheets", []):
        if sheet.get("properties", {}).get("title") == sheet_name:
            return sheet.get("properties", {}).get("sheetId")
    raise ValueError(f"Sheet '{sheet_name}' not found in spreadsheet.")


def rename_sheet(sheets_service, spreadsheet_id, sheet_id, new_title):
    """
    Renames a sheet within a spreadsheet.
    """
    body = {
        "requests": [
            {
                "updateSheetProperties": {
                    "properties": {"sheetId": sheet_id, "title": new_title},
                    "fields": "title",
                }
            }
        ]
    }
    sheets_service.spreadsheets().batchUpdate(
        spreadsheetId=spreadsheet_id, body=body
    ).execute()


def insert_rows(
    sheets_service, spreadsheet_id: str, sheet_name: str, values: List[List]
):
    """
    Inserts rows into the specified sheet (overwrites the range starting at A1).
    Uses USER_ENTERED so formulas like HYPERLINK() are written as formulas.
    """
    log.debug(
        f"Inserting {len(values)} rows into sheet '{sheet_name}' in spreadsheet {spreadsheet_id}"
    )
    try:
        range_ = f"{sheet_name}!A1"
        body = {"values": values}
        sheets_service.spreadsheets().values().update(
            spreadsheetId=spreadsheet_id,
            range=range_,
            valueInputOption="USER_ENTERED",
            body=body,
        ).execute()
        log.debug("Rows inserted successfully")
    except HttpError as error:
        log.error(f"An error occurred while inserting rows: {error}")
        raise


def get_spreadsheet_metadata(sheets_service, spreadsheet_id: str) -> Dict:
    """
    Retrieves the metadata of the spreadsheet, including sheets info.
    """
    log.debug(f"Retrieving spreadsheet metadata for ID {spreadsheet_id}")
    try:
        return safe_get_spreadsheet_metadata(sheets_service, spreadsheet_id)
    except HttpError as error:
        log.error(f"An error occurred while retrieving spreadsheet metadata: {error}")
        raise


def write_sheet_data(
    sheet_service,
    spreadsheet_id: str,
    sheet_name: str,
    header: List[str],
    rows: List[List[Any]],
) -> None:
    """
    Overwrites the specified sheet in the given spreadsheet with the provided header and rows.

    If the sheet does not exist, it will be created.
    If the sheet exists, its contents will be cleared before writing.

    Args:
        sheet_service: The Google Sheets API service instance.
        spreadsheet_id (str): The ID of the spreadsheet.
        sheet_name (str): The name of the sheet to write data to.
        header (List[str]): A list of column headers.
        rows (List[List[Any]]): A list of data rows (each a list of cell values).
    """
    log.debug(
        f"Overwriting sheet '{sheet_name}' in spreadsheet_id={spreadsheet_id} with {len(rows)} rows"
    )
    # Ensure the sheet exists or create it
    ensure_sheet_exists(sheet_service, spreadsheet_id, sheet_name)

    # Clear existing data
    clear_range = f"{sheet_name}!A:Z"
    try:
        sheet_service.spreadsheets().values().clear(
            spreadsheetId=spreadsheet_id, range=clear_range, body={}
        ).execute()
        log.debug(f"Cleared range {clear_range} before writing new data")
    except HttpError as error:
        log.error(f"An error occurred while clearing sheet: {error}")
        raise

    # Prepare values for update
    values = [header] + rows
    body = {"values": values}

    # Write new data
    try:
        sheet_service.spreadsheets().values().update(
            spreadsheetId=spreadsheet_id,
            range=f"{sheet_name}!A1",
            valueInputOption="RAW",
            body=body,
        ).execute()
        log.debug(f"Sheet '{sheet_name}' written successfully")
    except HttpError as error:
        log.error(f"An error occurred while writing sheet data: {error}")
        raise


def get_sheet_values(
    sheets_service,
    spreadsheet_id,
    sheet_name,
    max_retries: int = 8,
    base_delay: float = 1.0,
    max_delay: float = 60.0,
):
    """
    Get all values from the given sheet.

    Returns a list of rows (each row is a list of strings).

    Retries on transient API errors (429, 500, 503) and quota-related 403s using
    exponential backoff with jitter.
    """
    range_name = f"{sheet_name}"
    log.debug(
        f"Getting all values from sheet '{sheet_name}' in spreadsheet_id={spreadsheet_id}"
    )

    delay = base_delay
    last_error: Exception | None = None

    for attempt in range(1, max_retries + 1):
        try:
            result = (
                sheets_service.spreadsheets()
                .values()
                .get(
                    spreadsheetId=spreadsheet_id,
                    range=range_name,
                    majorDimension="ROWS",
                )
                .execute()
            )
            values = result.get("values", [])
            log.debug(f"Retrieved {len(values)} rows from sheet '{sheet_name}'")

            # Normalize all values to strings
            normalized: list[list[str]] = []
            for row in values:
                normalized.append(
                    [str(cell) if cell is not None else "" for cell in row]
                )
            return normalized

        except HttpError as error:
            last_error = error
            status = getattr(getattr(error, "resp", None), "status", None)

            if (not _is_retryable_http_error(error)) or attempt == max_retries:
                log.error(
                    f"An error occurred while getting sheet values (attempt {attempt}/{max_retries}): {error}"
                )
                raise

            # exponential backoff with jitter (0.7x–1.3x)
            wait = min(max_delay, delay) * (0.7 + random.random() * 0.6)
            log.warning(
                f"⚠️ Retryable Sheets API error {status} while reading '{sheet_name}' ({spreadsheet_id}); "
                f"retrying in {wait:.1f}s (attempt {attempt}/{max_retries})"
            )
            time.sleep(wait)
            delay *= 2

        except Exception as error:
            # Non-HTTP errors: do not retry endlessly
            last_error = error
            log.error(f"An error occurred while getting sheet values: {error}")
            raise

    # Should be unreachable, but keep a defensive raise
    if last_error:
        raise last_error
    return []


def clear_all_except_one_sheet(sheets_service, spreadsheet_id: str, sheet_to_keep: str):
    """
    Deletes all sheets in the spreadsheet except the one specified.
    If the sheet_to_keep does not exist, creates it.
    """
    log.debug(
        f"Clearing all sheets except '{sheet_to_keep}' in spreadsheet ID {spreadsheet_id}"
    )
    try:
        spreadsheet = safe_get_spreadsheet_metadata(sheets_service, spreadsheet_id)
        sheets = spreadsheet.get("sheets", [])
        sheet_titles = [sheet["properties"]["title"] for sheet in sheets]
        requests = []
        # Create the sheet_to_keep if it does not exist
        if sheet_to_keep not in sheet_titles:
            log.debug(f"Sheet '{sheet_to_keep}' not found, queuing create request")
            requests.append({"addSheet": {"properties": {"title": sheet_to_keep}}})
        # Delete all sheets except sheet_to_keep
        for sheet in sheets:
            title = sheet["properties"]["title"]
            sheet_id = sheet["properties"]["sheetId"]
            if title != sheet_to_keep:
                log.debug(f"Queuing deletion of sheet '{title}' (id {sheet_id})")
                requests.append({"deleteSheet": {"sheetId": sheet_id}})
        if requests:
            body = {"requests": requests}
            sheets_service.spreadsheets().batchUpdate(
                spreadsheetId=spreadsheet_id, body=body
            ).execute()
            log.debug("Sheets updated successfully (clear/create/delete performed)")
        else:
            log.debug("No sheet changes required")
    except HttpError as error:
        log.error(f"An error occurred while clearing sheets: {error}")
        raise


def clear_sheet(sheets_service, spreadsheet_id, sheet_name):
    log.debug(
        f"Clearing all cells in sheet '{sheet_name}' in spreadsheet_id={spreadsheet_id}"
    )
    try:
        # Get sheetId from sheet name
        metadata = safe_get_spreadsheet_metadata(sheets_service, spreadsheet_id)
        sheet_id = None
        for sheet in metadata["sheets"]:
            if sheet["properties"]["title"] == sheet_name:
                sheet_id = sheet["properties"]["sheetId"]
                break

        if sheet_id is None:
            log.warning(f"Sheet name '{sheet_name}' not found in spreadsheet.")
            raise ValueError(f"Sheet name '{sheet_name}' not found in spreadsheet.")

        body = {
            "requests": [
                {"updateCells": {"range": {"sheetId": sheet_id}, "fields": "*"}}
            ]
        }

        sheets_service.spreadsheets().batchUpdate(
            spreadsheetId=spreadsheet_id, body=body
        ).execute()
        log.debug(f"Sheet '{sheet_name}' cleared successfully.")
    except HttpError as error:
        log.error(f"An error occurred while clearing sheet: {error}")
        raise


def delete_sheet_by_name(sheets_service, spreadsheet_id: str, sheet_name: str):
    """
    Deletes a sheet by its name from the spreadsheet.
    """
    log.debug(
        f"Deleting sheet '{sheet_name}' if it exists in spreadsheet_id={spreadsheet_id}"
    )
    try:
        spreadsheet = safe_get_spreadsheet_metadata(sheets_service, spreadsheet_id)
        sheets = spreadsheet.get("sheets", [])
        if len(sheets) <= 1:
            log.warning(
                f"Not deleting sheet '{sheet_name}': spreadsheet only has one sheet."
            )
            return
        sheet_id = None
        for sheet in sheets:
            if sheet["properties"]["title"] == sheet_name:
                sheet_id = sheet["properties"]["sheetId"]
                break
        if sheet_id is not None:
            body = {"requests": [{"deleteSheet": {"sheetId": sheet_id}}]}
            sheets_service.spreadsheets().batchUpdate(
                spreadsheetId=spreadsheet_id, body=body
            ).execute()
            log.debug(f"Sheet '{sheet_name}' deleted successfully")
        else:
            log.warning(f"Sheet '{sheet_name}' not found; no deletion necessary")
    except HttpError as error:
        log.error(f"An error occurred while deleting sheet: {error}")
        raise


def delete_all_sheets_except(sheets_service, spreadsheet_id, sheet_to_keep):
    """
    Deletes all sheets except the one named sheet_to_keep.
    """
    spreadsheet = safe_get_spreadsheet_metadata(sheets_service, spreadsheet_id)
    sheets = spreadsheet.get("sheets", [])
    requests = []
    for sheet in sheets:
        title = sheet["properties"]["title"]
        sheet_id = sheet["properties"]["sheetId"]
        if title != sheet_to_keep:
            requests.append({"deleteSheet": {"sheetId": sheet_id}})
    if requests:
        body = {"requests": requests}
        sheets_service.spreadsheets().batchUpdate(
            spreadsheetId=spreadsheet_id, body=body
        ).execute()


def a1_range(
    col_start: str,
    row_start: int,
    col_end: str | None = None,
    row_end: int | None = None,
) -> str:
    """Build an A1 range like 'A5:C10' or 'A5:C'.

    If row_end is None, returns an open-ended range ending at the given column (e.g., 'A5:C').
    """
    if col_end is None:
        col_end = col_start
    if row_end is None:
        return f"{col_start}{row_start}:{col_end}"
    return f"{col_start}{row_start}:{col_end}{row_end}"


def sheets_clear_values(sheets_service, spreadsheet_id: str, a1: str) -> None:
    sheet = sheets_service.spreadsheets()
    sheet.values().clear(spreadsheetId=spreadsheet_id, range=a1).execute()


def sheets_update_values(
    sheets_service,
    spreadsheet_id: str,
    a1: str,
    values: list[list[str]],
    *,
    value_input_option: str = "RAW",
) -> None:
    sheet = sheets_service.spreadsheets()
    sheet.values().update(
        spreadsheetId=spreadsheet_id,
        range=a1,
        valueInputOption=value_input_option,
        body={"values": values},
    ).execute()


def sheets_get_values(sheets_service, spreadsheet_id: str, a1: str) -> list[list[str]]:
    sheet = sheets_service.spreadsheets()
    result = sheet.values().get(spreadsheetId=spreadsheet_id, range=a1).execute()
    return result.get("values", [])


def normalize_cell(value: str) -> str:
    return (value or "").strip()
