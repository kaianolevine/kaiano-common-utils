import time
from typing import Any, Dict, List, Optional

from googleapiclient.errors import HttpError

from kaiano_common_utils import logger as log

from ._auth import AuthConfig, build_sheets_service, load_credentials
from ._retry import is_retryable_http_error

# -----------------------------------------------------------------------------
# Local service / metadata helpers
# -----------------------------------------------------------------------------


def _as_sheets_service(sheets_or_service: Any) -> Any:
    """Accept either SheetsFacade or raw Sheets API service and return the raw service."""
    return getattr(sheets_or_service, "service", sheets_or_service)


def _get_sheets_service(auth: AuthConfig | None = None, sheets_service=None):
    """Return an authorized googleapiclient Sheets service.

    We intentionally keep this module self-contained so it does not depend on
    legacy helpers living in `kaiano_common_utils.api.google.sheets`.
    """
    if sheets_service is not None:
        return sheets_service
    creds = load_credentials(auth)
    return build_sheets_service(creds)


def _get_sheet_id_by_name(sheets_service, spreadsheet_id: str, sheet_name: str) -> int:
    """Resolve a sheetId from a sheet title."""
    meta = _execute_with_http_retry(
        lambda: sheets_service.spreadsheets()
        .get(spreadsheetId=spreadsheet_id)
        .execute(),
        operation=f"fetching spreadsheet metadata for {spreadsheet_id}",
        max_attempts=5,
    )
    for sheet in meta.get("sheets", []):
        props = sheet.get("properties", {})
        if props.get("title") == sheet_name:
            return int(props["sheetId"])
    raise ValueError(f"Sheet '{sheet_name}' not found in spreadsheet {spreadsheet_id}")


def hex_to_rgb(hex_color: str) -> Dict[str, float]:
    hex_color = hex_color.lstrip("#")
    if len(hex_color) == 6 and all(c in "0123456789abcdefABCDEF" for c in hex_color):
        r, g, b = tuple(int(hex_color[i : i + 2], 16) for i in (0, 2, 4))
    elif len(hex_color) == 3 and all(c in "0123456789abcdefABCDEF" for c in hex_color):
        r, g, b = tuple(int(hex_color[i] * 2, 16) for i in range(3))
    else:
        r, g, b = (255, 255, 255)
    return {"red": r / 255, "green": g / 255, "blue": b / 255}


def _batch_update_with_retry(
    sheets_service,
    spreadsheet_id: str,
    requests: List[Dict[str, Any]],
    *,
    operation: str = "batchUpdate",
    max_attempts: int = 5,
) -> None:
    """Execute a Sheets batchUpdate with conservative exponential backoff.

    Formatting tends to be quota-heavy and can trigger 429 (rate limit) or 5xx.
    This wrapper retries only for transient statuses.
    """
    delay_s = 1.0
    last_err: Optional[Exception] = None

    for attempt in range(1, max_attempts + 1):
        try:
            sheets_service.spreadsheets().batchUpdate(
                spreadsheetId=spreadsheet_id, body={"requests": requests}
            ).execute()
            return
        except Exception as e:
            last_err = e

            retryable = isinstance(e, HttpError) and is_retryable_http_error(e)
            if not retryable or attempt >= max_attempts:
                raise

            status = getattr(getattr(e, "resp", None), "status", None)
            log.warning(
                f"⚠️ {operation} hit retryable error (HTTP {status}) on attempt {attempt}/{max_attempts}. "
                f"Backing off for {delay_s:.1f}s..."
            )

            time.sleep(delay_s)
            delay_s = min(delay_s * 2, 16.0)

    if last_err:
        raise last_err


# --- Helper for conservative retry on .execute() calls ---
def _execute_with_http_retry(fn, *, operation: str, max_attempts: int = 5) -> Any:
    """Execute a Google API call with conservative backoff for retryable HttpError."""

    delay_s = 1.0
    last_err: Optional[Exception] = None

    for attempt in range(1, max_attempts + 1):
        try:
            return fn()
        except Exception as e:
            last_err = e

            retryable = isinstance(e, HttpError) and is_retryable_http_error(e)
            if not retryable or attempt >= max_attempts:
                raise

            status = getattr(getattr(e, "resp", None), "status", None)
            log.warning(
                f"⚠️ {operation} hit retryable error (HTTP {status}) on attempt {attempt}/{max_attempts}. "
                f"Backing off for {delay_s:.1f}s..."
            )
            time.sleep(delay_s)
            delay_s = min(delay_s * 2, 16.0)

    if last_err:
        raise last_err

    raise RuntimeError(f"Unknown error in {operation}")


# --- Helper: get column pixel sizes for all sheets in a spreadsheet ---
def _get_column_pixel_sizes(
    sheets_service,
    spreadsheet_id: str,
) -> Dict[int, List[Optional[int]]]:
    """Return {sheetId: [pixelSize,...]} using a minimal includeGridData fetch.

    We keep fields tight to avoid large payloads.
    """
    meta = _execute_with_http_retry(
        lambda: sheets_service.spreadsheets()
        .get(
            spreadsheetId=spreadsheet_id,
            includeGridData=True,
            fields="sheets(properties(sheetId,title),data(columnMetadata(pixelSize)))",
        )
        .execute(),
        operation=f"fetching column pixel sizes for {spreadsheet_id}",
        max_attempts=5,
    )

    out: Dict[int, List[Optional[int]]] = {}
    for s in meta.get("sheets", []):
        props = s.get("properties", {})
        sid = props.get("sheetId")
        data = s.get("data", []) or []
        if not sid or not data:
            continue
        # data[0] is typically the main GridData
        col_meta = (data[0] or {}).get("columnMetadata", []) or []
        sizes: List[Optional[int]] = []
        for cm in col_meta:
            ps = cm.get("pixelSize")
            sizes.append(int(ps) if ps is not None else None)
        out[int(sid)] = sizes

    return out


class SheetsFormatting:
    """Static wrapper for this module’s formatting utilities.

    This is intentionally *stateless*: each method operates on the provided
    spreadsheet/service arguments. This keeps usage simple and avoids any hidden
    state (spreadsheet IDs, cached services, etc.).

    Module-level functions remain available for backwards compatibility.
    """

    @staticmethod
    def _service(sheets_service=None):
        return _get_sheets_service(sheets_service=sheets_service)

    # --- High level helpers ---

    @staticmethod
    def apply_to_spreadsheet(spreadsheet_id: str) -> None:
        apply_formatting_to_sheet(spreadsheet_id)

    @staticmethod
    def apply_to_gspread_sheet(sheet) -> None:
        apply_sheet_formatting(sheet)

    # --- Thin wrappers around existing module functions ---

    @staticmethod
    def set_values(
        spreadsheet_id: str,
        sheet_name: str,
        start_row: int,
        start_col: int,
        values,
        *,
        force_text: bool = True,
        sheets_service=None,
    ) -> None:
        set_values(
            SheetsFormatting._service(sheets_service),
            spreadsheet_id,
            sheet_name,
            start_row,
            start_col,
            values,
            force_text=force_text,
        )

    @staticmethod
    def set_bold_font(
        spreadsheet_id: str,
        sheet_id: int,
        start_row: int,
        end_row: int,
        start_col: int,
        end_col: int,
        *,
        sheets_service=None,
    ) -> None:
        set_bold_font(
            SheetsFormatting._service(sheets_service),
            spreadsheet_id,
            sheet_id,
            start_row,
            end_row,
            start_col,
            end_col,
        )

    @staticmethod
    def freeze_rows(
        spreadsheet_id: str,
        sheet_id: int,
        num_rows: int,
        *,
        sheets_service=None,
    ) -> None:
        freeze_rows(
            SheetsFormatting._service(sheets_service),
            spreadsheet_id,
            sheet_id,
            num_rows,
        )

    @staticmethod
    def set_horizontal_alignment(
        spreadsheet_id: str,
        sheet_id: int,
        start_row: int,
        end_row: int,
        start_col: int,
        end_col: int,
        *,
        alignment: str = "LEFT",
        sheets_service=None,
    ) -> None:
        set_horizontal_alignment(
            SheetsFormatting._service(sheets_service),
            spreadsheet_id,
            sheet_id,
            start_row,
            end_row,
            start_col,
            end_col,
            alignment=alignment,
        )

    @staticmethod
    def set_number_format(
        spreadsheet_id: str,
        sheet_id: int,
        start_row: int,
        end_row: int,
        start_col: int,
        end_col: int,
        format_str,
        *,
        sheets_service=None,
    ) -> None:
        set_number_format(
            SheetsFormatting._service(sheets_service),
            spreadsheet_id,
            sheet_id,
            start_row,
            end_row,
            start_col,
            end_col,
            format_str,
        )

    @staticmethod
    def auto_resize_columns(
        spreadsheet_id: str,
        sheet_id: int,
        *,
        start_col: int = 1,
        end_col: Optional[int] = None,
        sheets_service=None,
    ) -> None:
        auto_resize_columns(
            SheetsFormatting._service(sheets_service),
            spreadsheet_id,
            sheet_id,
            start_col,
            end_col,
        )

    @staticmethod
    def set_column_text_formatting(
        sheets_or_service, spreadsheet_id: str, sheet_name: str, column_indexes
    ) -> None:
        set_column_text_formatting(
            sheets_or_service,
            spreadsheet_id,
            sheet_name,
            column_indexes,
        )

    @staticmethod
    def reorder_sheets(
        sheets_or_service,
        spreadsheet_id: str,
        sheet_names_in_order: List[str],
        spreadsheet_metadata: Dict,
    ) -> None:
        reorder_sheets(
            sheets_or_service,
            spreadsheet_id,
            sheet_names_in_order,
            spreadsheet_metadata,
        )

    @staticmethod
    def format_summary_sheet(
        spreadsheet_id: str,
        sheet_name: str,
        header: List[str],
        rows: List[List[Any]],
        *,
        sheets_service=None,
    ) -> None:
        format_summary_sheet(
            SheetsFormatting._service(sheets_service),
            spreadsheet_id,
            sheet_name,
            header,
            rows,
        )

    @staticmethod
    def formatter(spreadsheet_id: str, *, sheets_service=None) -> "SheetFormatter":
        """Return the optional convenience SheetFormatter for a spreadsheet."""
        return SheetFormatter(SheetsFormatting._service(sheets_service), spreadsheet_id)


# --- Higher-level / opinionated formatting recipes namespace ---
class SheetsFormattingPresets:
    """Static wrappers for higher-level / opinionated formatting recipes.

    Use this when you want the module's "do-the-whole-thing" helpers rather than the
    low-level primitives in `SheetsFormatting`.

    These methods intentionally keep the existing module-level functions as the
    source of truth (no behavior changes), but provide a discoverable namespace.
    """

    @staticmethod
    def apply_formatting_to_sheet(spreadsheet_id: str) -> None:
        """Apply standard formatting to all sheets in a spreadsheet."""
        apply_formatting_to_sheet(spreadsheet_id)

    @staticmethod
    def apply_sheet_formatting(sheet) -> None:
        """Apply lightweight formatting to a single gspread Worksheet."""
        apply_sheet_formatting(sheet)

    @staticmethod
    def set_sheet_formatting(
        spreadsheet_id: str,
        sheet_id: int,
        header_row_count: int,
        total_rows: int,
        total_cols: int,
        backgrounds,
    ) -> None:
        """Apply the module's legacy per-sheet formatting recipe."""
        set_sheet_formatting(
            spreadsheet_id,
            sheet_id,
            header_row_count,
            total_rows,
            total_cols,
            backgrounds,
        )

    @staticmethod
    def set_column_formatting(
        sheets_or_service, spreadsheet_id: str, sheet_name: str, num_columns: int
    ) -> None:
        set_column_formatting(
            sheets_or_service,
            spreadsheet_id,
            sheet_name,
            num_columns,
        )

    @staticmethod
    def update_sheet_values(
        sheets_service,
        spreadsheet_id: str,
        sheet_name: str,
        values,
    ) -> None:
        """Update values starting at A1 using USER_ENTERED (legacy helper)."""
        update_sheet_values(sheets_service, spreadsheet_id, sheet_name, values)

    @staticmethod
    def format_summary_sheet(
        sheets_service,
        spreadsheet_id: str,
        sheet_name: str,
        header: List[str],
        rows: List[List[Any]],
    ) -> None:
        """Apply the summary-sheet formatting recipe."""
        format_summary_sheet(sheets_service, spreadsheet_id, sheet_name, header, rows)


def apply_sheet_formatting(sheet):
    """Apply lightweight formatting to a gspread Worksheet with minimal API calls.

    NOTE: We avoid gspread's `sheet.format()` and `sheet.freeze()` calls because
    they each translate into additional Sheets API requests per sheet.

    This function now uses a single Sheets API `batchUpdate` request per sheet
    (plus one metadata fetch when called via `apply_formatting_to_sheet`).
    """
    try:
        spreadsheet_id = sheet.spreadsheet.id
        sheet_id = sheet.id
        sheets_service = _get_sheets_service()

        # Use metadata-provided column count instead of reading values (saves quota).
        # gspread Worksheet exposes `col_count` which is backed by sheet properties.
        num_columns = int(getattr(sheet, "col_count", 26) or 26)
        if num_columns < 1:
            num_columns = 26

        requests: List[Dict[str, Any]] = []

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

        # Font size + left alignment across used columns.
        # IMPORTANT: Do NOT set/replace the entire textFormat object, because that can wipe
        # rich-text hyperlink info (textFormat.link / textFormatRuns). Only set fontSize.
        requests.append(
            {
                "repeatCell": {
                    "range": {
                        "sheetId": sheet_id,
                        "startRowIndex": 0,
                        "startColumnIndex": 0,
                        "endColumnIndex": num_columns,
                    },
                    "cell": {
                        "userEnteredFormat": {
                            "textFormat": {"fontSize": 10},
                            "horizontalAlignment": "LEFT",
                        }
                    },
                    "fields": "userEnteredFormat.textFormat.fontSize,userEnteredFormat.horizontalAlignment",
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
                        "startColumnIndex": 0,
                        "endColumnIndex": num_columns,
                    },
                    "cell": {"userEnteredFormat": {"textFormat": {"bold": True}}},
                    "fields": "userEnteredFormat.textFormat.bold",
                }
            }
        )

        # Auto-resize only the columns we expect to be used
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

        _batch_update_with_retry(
            sheets_service,
            spreadsheet_id,
            requests,
            operation=f"format sheetId={sheet_id}",
            max_attempts=5,
        )
    except Exception as e:
        log.warning(
            f"Auto formatting failed for sheet '{getattr(sheet, 'title', sheet)}': {e}"
        )


def apply_formatting_to_sheet(spreadsheet_id):
    """Apply formatting to all sheets in a spreadsheet with quota-friendly batching.

    We currently may have ~12 sheets, but this can grow over time. The safest approach
    is to:
    - Fetch spreadsheet metadata once
    - Build a single list of batchUpdate requests for ALL sheets
    - Send those requests in CHUNKS to avoid very large batchUpdate payloads

    This reduces the number of *HTTP requests* significantly (often to 1–2 calls),
    which helps with per-minute quotas and rate limiting.

    NOTE: We intentionally do NOT read any cell values here.
    """

    log.debug(f"Applying formatting to all sheets in spreadsheet ID: {spreadsheet_id}")

    sheets_service = _get_sheets_service()

    try:
        meta = _execute_with_http_retry(
            lambda: sheets_service.spreadsheets()
            .get(spreadsheetId=spreadsheet_id)
            .execute(),
            operation=f"fetching spreadsheet metadata for {spreadsheet_id}",
            max_attempts=5,
        )
        sheets = meta.get("sheets", [])
        log.debug(f"Found {len(sheets)} sheet(s) to format")

        # Build ONE request list for all sheets, then chunk it.
        all_requests: List[Dict[str, Any]] = []

        for s in sheets:
            props = s.get("properties", {})
            sheet_id = props.get("sheetId")
            title = props.get("title", "(untitled)")
            grid = props.get("gridProperties", {})
            num_columns = int(grid.get("columnCount", 26) or 26)
            if num_columns < 1:
                num_columns = 26

            log.debug(
                f"Queueing formatting for sheet: {title} (sheetId={sheet_id}, cols={num_columns})"
            )

            # Freeze header row
            all_requests.append(
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

            # Font size + left alignment across used columns.
            # IMPORTANT: Do NOT set/replace the entire textFormat object, because that can wipe
            # rich-text hyperlink info (textFormat.link / textFormatRuns). Only set fontSize.
            all_requests.append(
                {
                    "repeatCell": {
                        "range": {
                            "sheetId": sheet_id,
                            "startRowIndex": 0,
                            "startColumnIndex": 0,
                            "endColumnIndex": num_columns,
                        },
                        "cell": {
                            "userEnteredFormat": {
                                "textFormat": {"fontSize": 10},
                                "horizontalAlignment": "LEFT",
                            }
                        },
                        "fields": "userEnteredFormat.textFormat.fontSize,userEnteredFormat.horizontalAlignment",
                    }
                }
            )

            # Bold header row
            all_requests.append(
                {
                    "repeatCell": {
                        "range": {
                            "sheetId": sheet_id,
                            "startRowIndex": 0,
                            "endRowIndex": 1,
                            "startColumnIndex": 0,
                            "endColumnIndex": num_columns,
                        },
                        "cell": {"userEnteredFormat": {"textFormat": {"bold": True}}},
                        "fields": "userEnteredFormat.textFormat.bold",
                    }
                }
            )

            # Auto-resize columns
            all_requests.append(
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

        if not all_requests:
            log.info("No sheets found to format; nothing to do")
            return

        # Chunk the requests to keep payloads reasonable and avoid API limits.
        # Each sheet contributes 4 requests, so CHUNK_SIZE=400 formats ~100 sheets per call.
        CHUNK_SIZE = 400

        log.debug(
            f"Sending formatting batchUpdate requests in chunks of {CHUNK_SIZE}. Total requests: {len(all_requests)}"
        )

        for i in range(0, len(all_requests), CHUNK_SIZE):
            chunk = all_requests[i : i + CHUNK_SIZE]
            chunk_num = (i // CHUNK_SIZE) + 1
            total_chunks = ((len(all_requests) - 1) // CHUNK_SIZE) + 1

            _batch_update_with_retry(
                sheets_service,
                spreadsheet_id,
                chunk,
                operation=f"format all sheets (chunk {chunk_num}/{total_chunks})",
                max_attempts=5,
            )

            # Light throttle between chunks (helps when spreadsheets grow large)
            if chunk_num < total_chunks:
                time.sleep(0.5)

        # --- Column width buffer pass ---
        # Auto-resize sets widths, but can be a little tight. We re-fetch the computed
        # widths and then apply a small pixel buffer, capped at a max width.
        BUFFER_PX = 20
        MAX_PX = 350

        try:
            pixel_sizes_by_sheet = _get_column_pixel_sizes(
                sheets_service, spreadsheet_id
            )

            width_requests: List[Dict[str, Any]] = []

            for s in sheets:
                props = s.get("properties", {})
                sheet_id = int(props.get("sheetId"))
                grid = props.get("gridProperties", {})
                num_columns = int(grid.get("columnCount", 26) or 26)
                if num_columns < 1:
                    num_columns = 26

                sizes = pixel_sizes_by_sheet.get(sheet_id, [])
                if not sizes:
                    continue

                # Build per-column updates only where we have a size.
                for col_idx in range(0, min(num_columns, len(sizes))):
                    ps = sizes[col_idx]
                    if ps is None:
                        continue

                    new_ps = min(int(ps) + BUFFER_PX, MAX_PX)
                    # If already wide enough, no need to write.
                    if new_ps <= int(ps):
                        continue

                    width_requests.append(
                        {
                            "updateDimensionProperties": {
                                "range": {
                                    "sheetId": sheet_id,
                                    "dimension": "COLUMNS",
                                    "startIndex": col_idx,
                                    "endIndex": col_idx + 1,
                                },
                                "properties": {"pixelSize": new_ps},
                                "fields": "pixelSize",
                            }
                        }
                    )

            if width_requests:
                # Chunk dimension updates too.
                WIDTH_CHUNK_SIZE = 500
                log.debug(
                    f"Applying column width buffer (+{BUFFER_PX}px, cap {MAX_PX}px). Total width updates: {len(width_requests)}"
                )

                for i in range(0, len(width_requests), WIDTH_CHUNK_SIZE):
                    chunk = width_requests[i : i + WIDTH_CHUNK_SIZE]
                    chunk_num = (i // WIDTH_CHUNK_SIZE) + 1
                    total_chunks = ((len(width_requests) - 1) // WIDTH_CHUNK_SIZE) + 1

                    _batch_update_with_retry(
                        sheets_service,
                        spreadsheet_id,
                        chunk,
                        operation=f"column width buffer (chunk {chunk_num}/{total_chunks})",
                        max_attempts=5,
                    )

                    if chunk_num < total_chunks:
                        time.sleep(0.5)

        except Exception as e:
            log.warning(f"Column width buffer pass failed (continuing without it): {e}")

        log.info("✅ Formatting applied successfully to all sheets")
    except Exception as e:
        log.error(f"Error applying formatting to sheets: {e}")


# --- Helper function for preparing cell values for user entry ---
def _prepare_cell_for_user_entered(cell: Any, *, force_text: bool) -> Any:
    """Prepare a cell for Sheets values.update.

    When `force_text=True`, we prefix strings with an apostrophe to prevent Sheets
    auto-parsing (dates, numbers, etc.). HOWEVER, doing so will break formulas,
    including `=HYPERLINK(...)` cells.

    So we preserve formulas by detecting strings that start with '=' and leaving
    them untouched.
    """
    if cell is None:
        return "" if force_text else ""

    # Preserve formulas (including =HYPERLINK(...))
    if isinstance(cell, str) and cell.startswith("="):
        return cell

    if not force_text:
        return cell

    # Force literal text (USER_ENTERED) by prefixing with apostrophe.
    return f"'{str(cell)}"


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
        prepared = [
            [_prepare_cell_for_user_entered(cell, force_text=True) for cell in row]
            for row in values
        ]
        value_input = "USER_ENTERED"
    else:
        prepared = [
            [_prepare_cell_for_user_entered(cell, force_text=False) for cell in row]
            for row in values
        ]
        value_input = "RAW"
    body = {"values": prepared}
    _execute_with_http_retry(
        lambda: sheets_service.spreadsheets()
        .values()
        .update(
            spreadsheetId=spreadsheet_id,
            range=range_name,
            valueInputOption=value_input,
            body=body,
        )
        .execute(),
        operation=f"updating values {range_name} in {spreadsheet_id}",
        max_attempts=5,
    )


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
    _batch_update_with_retry(
        sheets_service,
        spreadsheet_id,
        requests,
        operation="set_bold_font",
        max_attempts=5,
    )


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
    _batch_update_with_retry(
        sheets_service,
        spreadsheet_id,
        requests,
        operation="freeze_rows",
        max_attempts=5,
    )


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
    _batch_update_with_retry(
        sheets_service,
        spreadsheet_id,
        requests,
        operation="set_horizontal_alignment",
        max_attempts=5,
    )


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
    _batch_update_with_retry(
        sheets_service,
        spreadsheet_id,
        requests,
        operation="set_number_format",
        max_attempts=5,
    )


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

        _batch_update_with_retry(
            service,
            spreadsheet_id,
            body["requests"],
            operation="auto_resize_columns",
            max_attempts=5,
        )
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
    sheets_service = _get_sheets_service()
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
                return {"userEnteredFormat": {"backgroundColor": hex_to_rgb(color)}}
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

    _batch_update_with_retry(
        sheets_service,
        spreadsheet_id,
        requests,
        operation=f"set_sheet_formatting sheetId={sheet_id}",
        max_attempts=5,
    )


def set_column_formatting(
    sheets_or_service, spreadsheet_id: str, sheet_name: str, num_columns: int
):
    sheets_service = _as_sheets_service(sheets_or_service)
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
            _batch_update_with_retry(
                sheets_service,
                spreadsheet_id,
                requests,
                operation=f"set_column_formatting sheet={sheet_name}",
                max_attempts=5,
            )
            log.info("✅ Column formatting set successfully")
    except HttpError as error:
        log.error(f"An error occurred while setting column formatting: {error}")
        raise


def set_column_text_formatting(
    sheets_or_service, spreadsheet_id: str, sheet_name: str, column_indexes
):
    sheets_service = _as_sheets_service(sheets_or_service)
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
        _batch_update_with_retry(
            sheets_service,
            spreadsheet_id,
            requests,
            operation=f"set_column_text_formatting sheet={sheet_name}",
            max_attempts=5,
        )


def reorder_sheets(
    sheets_or_service,
    spreadsheet_id: str,
    sheet_names_in_order: List[str],
    spreadsheet_metadata: Dict,
):
    sheets_service = _as_sheets_service(sheets_or_service)
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
            _batch_update_with_retry(
                sheets_service,
                spreadsheet_id,
                requests,
                operation="reorder_sheets",
                max_attempts=5,
            )
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
    sheet_id = _get_sheet_id_by_name(sheet_service, spreadsheet_id, sheet_name)
    log.debug(
        f"Formatting summary sheet '{sheet_name}' (sheetId={sheet_id}) in spreadsheet {spreadsheet_id}"
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
        _batch_update_with_retry(
            sheet_service,
            spreadsheet_id,
            requests,
            operation=f"format_summary_sheet sheetId={sheet_id}",
            max_attempts=5,
        )

        # --- Column width buffer pass (auto-resize + buffer) ---
        BUFFER_PX = 20
        MAX_PX = 350

        pixel_sizes_by_sheet = _get_column_pixel_sizes(sheet_service, spreadsheet_id)
        sizes = pixel_sizes_by_sheet.get(int(sheet_id), [])

        width_requests: List[Dict[str, Any]] = []
        if sizes:
            for col_idx in range(0, min(num_columns, len(sizes))):
                ps = sizes[col_idx]
                if ps is None:
                    continue
                new_ps = min(int(ps) + BUFFER_PX, MAX_PX)
                if new_ps <= int(ps):
                    continue
                width_requests.append(
                    {
                        "updateDimensionProperties": {
                            "range": {
                                "sheetId": sheet_id,
                                "dimension": "COLUMNS",
                                "startIndex": col_idx,
                                "endIndex": col_idx + 1,
                            },
                            "properties": {"pixelSize": new_ps},
                            "fields": "pixelSize",
                        }
                    }
                )

        if width_requests:
            _batch_update_with_retry(
                sheet_service,
                spreadsheet_id,
                width_requests,
                operation=f"format_summary_sheet column buffer sheetId={sheet_id}",
                max_attempts=5,
            )
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
        meta = _execute_with_http_retry(
            lambda: self.service.spreadsheets()
            .get(spreadsheetId=spreadsheet_id)
            .execute(),
            operation=f"fetching spreadsheet metadata for {spreadsheet_id}",
            max_attempts=5,
        )
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
