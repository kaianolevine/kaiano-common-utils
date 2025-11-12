from typing import Any, Dict, List, Optional

from googleapiclient.errors import HttpError

from kaiano_common_utils import google_sheets, helpers
from kaiano_common_utils import logger as log


def apply_sheet_formatting(sheet):
    # Set font size and alignment for entire sheet
    sheet.format("A:Z", {"textFormat": {"fontSize": 10}, "horizontalAlignment": "LEFT"})

    # Freeze header row
    sheet.freeze(rows=1)

    # Bold the header row
    sheet.format("1:1", {"textFormat": {"bold": True}})

    # --- Auto-resize all columns, then add a buffer to their width using Google Sheets API ---
    try:
        # Get spreadsheet and sheet info
        spreadsheet_id = sheet.spreadsheet.id
        sheet_id = sheet.id
        sheets_service = google_sheets.get_sheets_service()

        # Determine number of columns (by checking first row's length)
        values = sheet.get_all_values()
        if values and len(values) > 0:
            num_columns = len(values[0])
        else:
            num_columns = 26  # fallback default to 26 columns (A-Z)

        # 1. Auto-resize all columns
        auto_resize_req = {
            "autoResizeDimensions": {
                "dimensions": {
                    "sheetId": sheet_id,
                    "dimension": "COLUMNS",
                    "startIndex": 0,
                    "endIndex": num_columns,
                }
            }
        }
        # Send both requests (auto-resize, then buffer)
        sheets_service.spreadsheets().batchUpdate(
            spreadsheetId=spreadsheet_id,
            body={"requests": [auto_resize_req]},
        ).execute()
    except Exception as e:
        log.warning(f"Auto-resize and buffer for columns failed: {e}")


def apply_formatting_to_sheet(spreadsheet_id):
    log.debug(f"Applying formatting to all sheets in spreadsheet ID: {spreadsheet_id}")
    try:
        gc = google_sheets.get_gspread_client()
        sh = gc.open_by_key(spreadsheet_id)
        worksheets = sh.worksheets()
        log.debug(f"Found {len(worksheets)} sheet(s) to format")

        for sheet in worksheets:
            log.debug(f"Formatting sheet: {sheet.title}")
            values = sheet.get_all_values()
            if not values or len(values) == 0 or len(values[0]) == 0:
                log.warning(f"Sheet '{sheet.title}' is empty, skipping formatting")
                continue

            apply_sheet_formatting(sheet)

        log.info("✅ Formatting applied successfully to all sheets")
    except Exception as e:
        log.error(f"Error applying formatting to sheets: {e}")


def set_values(
    sheets_service,
    spreadsheet_id,
    sheet_name,
    start_row,
    start_col,
    values,
    force_text: bool = True,
):
    """
    Sets values in a sheet starting at (start_row, start_col).
    """
    end_row = start_row + len(values) - 1
    end_col = start_col + len(values[0]) - 1 if values else start_col
    range_name = f"{sheet_name}!R{start_row}C{start_col}:R{end_row}C{end_col}"
    if force_text:
        # Prefix with apostrophe to ensure USER_ENTERED treats as literal text
        prepared = [[f"'{str(cell)}" for cell in row] for row in values]
        value_input = "USER_ENTERED"
    else:
        prepared = values
        value_input = "RAW"
    body = {"values": prepared}
    sheets_service.spreadsheets().values().update(
        spreadsheetId=spreadsheet_id,
        range=range_name,
        valueInputOption=value_input,
        body=body,
    ).execute()


def set_bold_font(
    sheets_service, spreadsheet_id, sheet_id, start_row, end_row, start_col, end_col
):
    """
    Sets font weight to bold for the specified range.
    """
    requests = [
        {
            "repeatCell": {
                "range": {
                    "sheetId": sheet_id,
                    "startRowIndex": start_row - 1,
                    "endRowIndex": end_row,
                    "startColumnIndex": start_col - 1,
                    "endColumnIndex": end_col,
                },
                "cell": {"userEnteredFormat": {"textFormat": {"bold": True}}},
                "fields": "userEnteredFormat.textFormat.bold",
            }
        }
    ]
    body = {"requests": requests}
    sheets_service.spreadsheets().batchUpdate(
        spreadsheetId=spreadsheet_id, body=body
    ).execute()


def freeze_rows(sheets_service, spreadsheet_id, sheet_id, num_rows):
    """
    Freezes the specified number of rows at the top of the sheet.
    """
    requests = [
        {
            "updateSheetProperties": {
                "properties": {
                    "sheetId": sheet_id,
                    "gridProperties": {"frozenRowCount": num_rows},
                },
                "fields": "gridProperties.frozenRowCount",
            }
        }
    ]
    body = {"requests": requests}
    sheets_service.spreadsheets().batchUpdate(
        spreadsheetId=spreadsheet_id, body=body
    ).execute()


def set_horizontal_alignment(
    sheets_service,
    spreadsheet_id,
    sheet_id,
    start_row,
    end_row,
    start_col,
    end_col,
    alignment="LEFT",
):
    """
    Sets horizontal alignment for a range.
    """
    requests = [
        {
            "repeatCell": {
                "range": {
                    "sheetId": sheet_id,
                    "startRowIndex": start_row - 1,
                    "endRowIndex": end_row,
                    "startColumnIndex": start_col - 1,
                    "endColumnIndex": end_col,
                },
                "cell": {"userEnteredFormat": {"horizontalAlignment": alignment}},
                "fields": "userEnteredFormat.horizontalAlignment",
            }
        }
    ]
    body = {"requests": requests}
    sheets_service.spreadsheets().batchUpdate(
        spreadsheetId=spreadsheet_id, body=body
    ).execute()


def set_number_format(
    sheets_service,
    spreadsheet_id,
    sheet_id,
    start_row,
    end_row,
    start_col,
    end_col,
    format_str,
):
    """
    Sets number format for a range.
    """
    # Determine number format based on format_str
    number_format = {}
    if isinstance(format_str, str) and format_str:
        upper = format_str.strip().upper()
        if upper in {"TEXT", "@"}:
            number_format = {"type": "TEXT"}
        elif upper in {"DATE", "TIME", "DATETIME"}:
            number_format = {"type": upper}
        else:
            # Treat as numeric pattern (e.g., "0", "0.00", "#,##0", "0000")
            number_format = {"type": "NUMBER", "pattern": format_str}
    else:
        number_format = {"type": "NUMBER"}
    requests = [
        {
            "repeatCell": {
                "range": {
                    "sheetId": sheet_id,
                    "startRowIndex": start_row - 1,
                    "endRowIndex": end_row,
                    "startColumnIndex": start_col - 1,
                    "endColumnIndex": end_col,
                },
                "cell": {"userEnteredFormat": {"numberFormat": number_format}},
                "fields": "userEnteredFormat.numberFormat",
            }
        }
    ]
    body = {"requests": requests}
    sheets_service.spreadsheets().batchUpdate(
        spreadsheetId=spreadsheet_id, body=body
    ).execute()


def auto_resize_columns(
    service, spreadsheet_id, sheet_id, start_col: int = 1, end_col: Optional[int] = None
):
    """Automatically resize columns in a given sheet range.

    Args:
        service: Google Sheets API service instance.
        spreadsheet_id: ID of the spreadsheet.
        sheet_id: Sheet ID within the spreadsheet.
        start_col: 1-based first column to resize (default 1).
        end_col: 1-based last column to resize (inclusive). If None, will resize just start_col.

    This function is defensive: it validates and normalizes the start/end column values,
    converts them to the zero-based, end-exclusive indices expected by the Sheets API,
    and swaps the bounds if they were passed in the wrong order. If the API call fails
    with an HttpError, it will log the error and re-raise.
    """
    try:
        # Normalize inputs to integers and ensure at least 1
        start_col = int(start_col) if start_col is not None else 1
        if start_col < 1:
            log.warning(f"start_col < 1 ({start_col}) — clamping to 1")
            start_col = 1

        if end_col is None:
            end_col = start_col
        else:
            end_col = int(end_col)
            if end_col < 1:
                log.warning(f"end_col < 1 ({end_col}) — clamping to 1")
                end_col = 1

        # If bounds are reversed, swap them (caller may have passed in reversed args)
        if end_col < start_col:
            log.warning(
                f"auto_resize_columns received end_col < start_col ({end_col} < {start_col}); swapping bounds"
            )
            start_col, end_col = end_col, start_col

        # Convert to zero-based, end-exclusive indices for Sheets API
        start_index = start_col - 1
        end_index = end_col  # endIndex in the API is exclusive and zero-based

        body = {
            "requests": [
                {
                    "autoResizeDimensions": {
                        "dimensions": {
                            "sheetId": sheet_id,
                            "dimension": "COLUMNS",
                            "startIndex": start_index,
                            "endIndex": end_index,
                        }
                    }
                }
            ]
        }

        service.spreadsheets().batchUpdate(
            spreadsheetId=spreadsheet_id, body=body
        ).execute()
    except HttpError as e:
        log.error(
            f"Auto-resize columns failed for sheet {sheet_id} cols {start_col}-{end_col}: {e}"
        )
        raise


def update_sheet_values(sheets_service, spreadsheet_id, sheet_name, values):
    """
    Update values in the sheet starting from A1.
    """
    sheets_service.spreadsheets().values().update(
        spreadsheetId=spreadsheet_id,
        range=sheet_name,
        valueInputOption="USER_ENTERED",
        body={"values": values},
    ).execute()


def set_sheet_formatting(
    spreadsheet_id, sheet_id, header_row_count, total_rows, total_cols, backgrounds
):
    """
    Apply formatting to a Google Sheet:
    - Freeze header rows
    - Set font bold for header row
    - Set horizontal alignment left for all data
    - Set number format to plain text for data rows
    - Set background colors for data rows
    - Auto resize columns
    """
    sheets_service = google_sheets.get_sheets_service()
    requests = []

    # Freeze header rows
    requests.append(
        {
            "updateSheetProperties": {
                "properties": {
                    "sheetId": sheet_id,
                    "gridProperties": {"frozenRowCount": header_row_count},
                },
                "fields": "gridProperties.frozenRowCount",
            }
        }
    )

    # Bold font for header row
    requests.append(
        {
            "repeatCell": {
                "range": {
                    "sheetId": sheet_id,
                    "startRowIndex": 0,
                    "endRowIndex": header_row_count,
                    "startColumnIndex": 0,
                    "endColumnIndex": total_cols,
                },
                "cell": {"userEnteredFormat": {"textFormat": {"bold": True}}},
                "fields": "userEnteredFormat.textFormat.bold",
            }
        }
    )

    # Horizontal alignment left for all data
    requests.append(
        {
            "repeatCell": {
                "range": {
                    "sheetId": sheet_id,
                    "startRowIndex": 0,
                    "endRowIndex": total_rows,
                    "startColumnIndex": 0,
                    "endColumnIndex": total_cols,
                },
                "cell": {"userEnteredFormat": {"horizontalAlignment": "LEFT"}},
                "fields": "userEnteredFormat.horizontalAlignment",
            }
        }
    )

    # Number format plain text for data rows (excluding header)
    if total_rows > header_row_count:
        requests.append(
            {
                "repeatCell": {
                    "range": {
                        "sheetId": sheet_id,
                        "startRowIndex": header_row_count,
                        "endRowIndex": total_rows,
                        "startColumnIndex": 0,
                        "endColumnIndex": total_cols,
                    },
                    "cell": {"userEnteredFormat": {"numberFormat": {"type": "TEXT"}}},
                    "fields": "userEnteredFormat.numberFormat",
                }
            }
        )

    # Set background colors for data rows (excluding header)
    if len(backgrounds) > 1:

        def _bg(color: str):
            try:
                return {
                    "userEnteredFormat": {"backgroundColor": helpers.hex_to_rgb(color)}
                }
            except Exception:
                return {"userEnteredFormat": {}}

        bg_requests = []
        for row_idx, bg_colors in enumerate(backgrounds[1:], start=header_row_count):
            row_request = {
                "updateCells": {
                    "rows": [{"values": [_bg(color) for color in bg_colors]}],
                    "fields": "userEnteredFormat.backgroundColor",
                    "start": {
                        "sheetId": sheet_id,
                        "rowIndex": row_idx,
                        "columnIndex": 0,
                    },
                }
            }
            bg_requests.append(row_request)
        requests.extend(bg_requests)

    # Auto resize columns (single request for all columns)
    requests.append(
        {
            "autoResizeDimensions": {
                "dimensions": {
                    "sheetId": sheet_id,
                    "dimension": "COLUMNS",
                    "startIndex": 0,
                    "endIndex": total_cols,
                }
            }
        }
    )
    # Can't set max width directly via API; auto-resize only.

    body = {"requests": requests}
    sheets_service.spreadsheets().batchUpdate(
        spreadsheetId=spreadsheet_id, body=body
    ).execute()


def set_column_formatting(
    sheets_service, spreadsheet_id: str, sheet_name: str, num_columns: int
):
    """
    Sets formatting for specified columns (first column date, others text).
    """
    log.info(
        f"🎨 Setting column formatting for {num_columns} columns in sheet '{sheet_name}'"
    )
    try:
        spreadsheet = (
            sheets_service.spreadsheets().get(spreadsheetId=spreadsheet_id).execute()
        )
        sheet_id = None
        row_count = 1000000
        for sheet in spreadsheet.get("sheets", []):
            if sheet["properties"]["title"] == sheet_name:
                sheet_id = sheet["properties"]["sheetId"]
                row_count = sheet["properties"]["gridProperties"].get(
                    "rowCount", 1000000
                )
                break
        if sheet_id is None:
            log.warning(f"Sheet '{sheet_name}' not found for formatting")
            return

        requests = []
        # Format first column as DATE
        if num_columns >= 1:
            requests.append(
                {
                    "repeatCell": {
                        "range": {
                            "sheetId": sheet_id,
                            "startRowIndex": 0,
                            "endRowIndex": row_count,
                            "startColumnIndex": 0,
                            "endColumnIndex": 1,
                        },
                        "cell": {
                            "userEnteredFormat": {
                                "numberFormat": {
                                    "type": "DATE",
                                    "pattern": "yyyy-mm-dd",
                                }
                            }
                        },
                        "fields": "userEnteredFormat.numberFormat",
                    }
                }
            )
        # Format other columns as TEXT
        if num_columns > 1:
            requests.append(
                {
                    "repeatCell": {
                        "range": {
                            "sheetId": sheet_id,
                            "startRowIndex": 0,
                            "endRowIndex": row_count,
                            "startColumnIndex": 1,
                            "endColumnIndex": num_columns,
                        },
                        "cell": {
                            "userEnteredFormat": {"numberFormat": {"type": "TEXT"}}
                        },
                        "fields": "userEnteredFormat.numberFormat",
                    }
                }
            )

        if requests:
            body = {"requests": requests}
            sheets_service.spreadsheets().batchUpdate(
                spreadsheetId=spreadsheet_id, body=body
            ).execute()
            log.info("✅ Column formatting set successfully")
    except HttpError as error:
        log.error(f"An error occurred while setting column formatting: {error}")
        raise


def set_column_text_formatting(
    sheets_service, spreadsheet_id: str, sheet_name: str, column_indexes
):
    """
    Force plain text formatting for the given zero-based column indexes on a sheet.

    This prevents Google Sheets from auto-parsing numeric-looking values (e.g., 2025)
    into dates (e.g., 1905-07-17).

    Args:
        sheets_service: Authorized Google Sheets API service.
        spreadsheet_id: ID of the spreadsheet.
        sheet_name: Title of the target sheet.
        column_indexes: Iterable of zero-based column indexes to format.
    """
    # Resolve the sheetId from the sheet name
    meta = sheets_service.spreadsheets().get(spreadsheetId=spreadsheet_id).execute()
    sheet = next(
        (
            s
            for s in meta.get("sheets", [])
            if s.get("properties", {}).get("title") == sheet_name
        ),
        None,
    )
    if not sheet:
        raise ValueError(
            f"Sheet named '{sheet_name}' not found in spreadsheet {spreadsheet_id}"
        )

    sheet_id = sheet["properties"]["sheetId"]

    # Apply TEXT number format (pattern "@") to the entire column, skipping the header row
    requests = []
    for col in column_indexes:
        requests.append(
            {
                "repeatCell": {
                    "range": {
                        "sheetId": sheet_id,
                        "startRowIndex": 1,  # leave header row unmodified
                        "startColumnIndex": int(col),
                        "endColumnIndex": int(col) + 1,
                    },
                    "cell": {
                        "userEnteredFormat": {
                            "numberFormat": {
                                "type": "TEXT",
                                "pattern": "@",
                            }
                        }
                    },
                    "fields": "userEnteredFormat.numberFormat",
                }
            }
        )

    if requests:
        sheets_service.spreadsheets().batchUpdate(
            spreadsheetId=spreadsheet_id, body={"requests": requests}
        ).execute()


def reorder_sheets(
    sheets_service,
    spreadsheet_id: str,
    sheet_names_in_order: List[str],
    spreadsheet_metadata: Dict,
):
    """
    Reorders sheets in the spreadsheet to match the order of sheet_names_in_order.
    Sheets not in the list will be placed after those specified.
    """
    log.info(
        f"🔀 Reordering sheets in spreadsheet ID {spreadsheet_id} to order: {sheet_names_in_order}"
    )
    try:
        sheets = spreadsheet_metadata.get("sheets", [])
        title_to_id = {
            sheet["properties"]["title"]: sheet["properties"]["sheetId"]
            for sheet in sheets
        }
        requests = []
        index = 0
        for name in sheet_names_in_order:
            sheet_id = title_to_id.get(name)
            if sheet_id is not None:
                requests.append(
                    {
                        "updateSheetProperties": {
                            "properties": {"sheetId": sheet_id, "index": index},
                            "fields": "index",
                        }
                    }
                )
                index += 1
        remaining_sheets = [
            sheet
            for sheet in sheets
            if sheet["properties"]["title"] not in sheet_names_in_order
        ]
        for sheet in remaining_sheets:
            requests.append(
                {
                    "updateSheetProperties": {
                        "properties": {
                            "sheetId": sheet["properties"]["sheetId"],
                            "index": index,
                        },
                        "fields": "index",
                    }
                }
            )
            index += 1
        if requests:
            body = {"requests": requests}
            sheets_service.spreadsheets().batchUpdate(
                spreadsheetId=spreadsheet_id, body=body
            ).execute()
            log.info("✅ Sheets reordered successfully")
    except HttpError as error:
        log.error(f"An error occurred while reordering sheets: {error}")
        raise


def format_summary_sheet(
    sheet_service,
    spreadsheet_id: str,
    sheet_name: str,
    header: List[str],
    rows: List[List[Any]],
) -> None:
    """
    Applies formatting to a summary sheet, such as:
    - Bold header row
    - Frozen header
    - Auto-sized columns (limited width)
    - Plain text formatting
    - Gridlines and optional visual enhancements

    Args:
        sheet_service: The Google Sheets API service instance.
        spreadsheet_id (str): The ID of the spreadsheet.
        sheet_name (str): The sheet name to format.
        header (List[str]): The list of column headers (used for column count).
        rows (List[List[Any]]): The data rows (used for row count).
    """
    sheet_id = google_sheets.get_sheet_id_by_name(
        sheet_service, spreadsheet_id, sheet_name
    )
    requests = []

    num_columns = len(header)
    num_rows = len(rows) + 1  # +1 for header

    # Freeze header row
    requests.append(
        {
            "updateSheetProperties": {
                "properties": {
                    "sheetId": sheet_id,
                    "gridProperties": {"frozenRowCount": 1},
                },
                "fields": "gridProperties.frozenRowCount",
            }
        }
    )

    # Bold the header row
    requests.append(
        {
            "repeatCell": {
                "range": {
                    "sheetId": sheet_id,
                    "startRowIndex": 0,
                    "endRowIndex": 1,
                },
                "cell": {"userEnteredFormat": {"textFormat": {"bold": True}}},
                "fields": "userEnteredFormat.textFormat.bold",
            }
        }
    )

    # Auto resize columns (limited width)
    requests.append(
        {
            "autoResizeDimensions": {
                "dimensions": {
                    "sheetId": sheet_id,
                    "dimension": "COLUMNS",
                    "startIndex": 0,
                    "endIndex": num_columns,
                }
            }
        }
    )
    # Add buffer to column widths (e.g., 1.2x the auto-sized width, or a fixed pixel size as an approximation)
    requests.append(
        {
            "updateDimensionProperties": {
                "range": {
                    "sheetId": sheet_id,
                    "dimension": "COLUMNS",
                    "startIndex": 0,
                    "endIndex": num_columns,
                },
                "properties": {"pixelSize": 120},  # Approximate width buffer
                "fields": "pixelSize",
            }
        }
    )

    # Format all cells as plain text
    requests.append(
        {
            "repeatCell": {
                "range": {
                    "sheetId": sheet_id,
                    "startRowIndex": 0,
                    "endRowIndex": num_rows,
                    "startColumnIndex": 0,
                    "endColumnIndex": num_columns,
                },
                "cell": {"userEnteredFormat": {"numberFormat": {"type": "TEXT"}}},
                "fields": "userEnteredFormat.numberFormat",
            }
        }
    )

    # Send all formatting requests in batch
    try:
        sheet_service.spreadsheets().batchUpdate(
            spreadsheetId=spreadsheet_id, body={"requests": requests}
        ).execute()
    except HttpError as e:
        log.error(f"Error formatting summary sheet '{sheet_name}': {e}")
        raise


# Optional convenience wrapper class for high-level formatting
class SheetFormatter:
    """Convenience wrapper that caches IDs and exposes high-level formatting helpers.
    Existing functions remain available; this class is optional and non-breaking.
    """

    def __init__(self, sheets_service, spreadsheet_id: str):
        self.service = sheets_service
        self.spreadsheet_id = spreadsheet_id
        meta = self.service.spreadsheets().get(spreadsheetId=spreadsheet_id).execute()
        self._title_to_id = {
            s["properties"]["title"]: s["properties"]["sheetId"]
            for s in meta.get("sheets", [])
        }

    def sheet_id(self, name: str) -> int:
        sid = self._title_to_id.get(name)
        if sid is None:
            raise ValueError(f"Sheet '{name}' not found")
        return sid

    def text_columns(self, sheet_name: str, cols: List[int]):
        set_column_text_formatting(self.service, self.spreadsheet_id, sheet_name, cols)

    def number_format(
        self,
        sheet_name: str,
        start_row: int,
        end_row: int,
        start_col: int,
        end_col: int,
        pattern: str,
    ):
        set_number_format(
            self.service,
            self.spreadsheet_id,
            self.sheet_id(sheet_name),
            start_row,
            end_row,
            start_col,
            end_col,
            pattern,
        )

    def freeze_headers(self, sheet_name: str, rows: int = 1):
        freeze_rows(self.service, self.spreadsheet_id, self.sheet_id(sheet_name), rows)

    def bold_header(self, sheet_name: str):
        set_bold_font(
            self.service, self.spreadsheet_id, self.sheet_id(sheet_name), 1, 1, 1, 26
        )

    def auto_resize(
        self, sheet_name: str, start_col: int = 1, end_col: Optional[int] = None
    ):
        auto_resize_columns(
            self.service,
            self.spreadsheet_id,
            self.sheet_id(sheet_name),
            start_col,
            end_col,
        )
