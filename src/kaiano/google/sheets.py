import random
import time
from typing import Any, Dict, Optional

from googleapiclient.errors import HttpError
from kaiano_common_utils import logger as log

from ._retry import RetryConfig, execute_with_retry

log = log.get_logger()


class SheetsFacade:
    """Small, stable wrapper around the Google Sheets API.

    External code should generally access this through `GoogleAPI.sheets`.
    """

    def __init__(self, service: Any, retry: RetryConfig | None = None):
        self._service = service
        self._retry = retry or RetryConfig()

    @property
    def service(self) -> Any:
        """Underlying googleapiclient Sheets service."""
        return self._service

    def get_metadata(
        self, spreadsheet_id: str, *, fields: str | None = None, max_retries: int = 6
    ) -> Dict[str, Any]:
        delay = 1.0
        last_err: HttpError | None = None

        for attempt in range(max_retries):
            try:

                def _do_get():
                    if fields:
                        return (
                            self._service.spreadsheets()
                            .get(spreadsheetId=spreadsheet_id, fields=fields)
                            .execute()
                        )
                    return (
                        self._service.spreadsheets()
                        .get(spreadsheetId=spreadsheet_id)
                        .execute()
                    )

                return _do_get()

            except HttpError as e:
                status = getattr(e.resp, "status", None)
                if status in (429, 500, 503) or (
                    status == 403 and "quota" in str(e).lower()
                ):
                    last_err = e
                    wait = delay * (0.7 + random.random() * 0.6)
                    log.warning(
                        f"⚠️ Retryable error {status} when fetching spreadsheet {spreadsheet_id}; retrying in {wait:.1f}s (attempt {attempt+1}/{max_retries})"
                    )
                    time.sleep(wait)
                    delay *= 2
                    continue
                raise

        # Exhausted retries; re-raise the last transient error if we have one
        if last_err is not None:
            raise last_err

        return execute_with_retry(
            lambda: self._service.spreadsheets()
            .get(spreadsheetId=spreadsheet_id)
            .execute(),
            context=f"fetching spreadsheet metadata ({spreadsheet_id})",
            retry=self._retry,
        )

    def batch_update(self, spreadsheet_id: str, requests: list[dict]) -> Dict[str, Any]:
        body = {"requests": requests}
        return execute_with_retry(
            lambda: self._service.spreadsheets()
            .batchUpdate(spreadsheetId=spreadsheet_id, body=body)
            .execute(),
            context=f"batchUpdate ({spreadsheet_id})",
            retry=self._retry,
        )

    def read_values(self, spreadsheet_id: str, a1_range: str) -> list[list[str]]:
        result = execute_with_retry(
            lambda: self._service.spreadsheets()
            .values()
            .get(spreadsheetId=spreadsheet_id, range=a1_range)
            .execute(),
            context=f"reading range '{a1_range}' ({spreadsheet_id})",
            retry=self._retry,
        )
        values = result.get("values", [])
        return [[str(c) if c is not None else "" for c in row] for row in values]

    def write_values(
        self,
        spreadsheet_id: str,
        a1_range: str,
        values: list[list[Any]],
        *,
        value_input_option: str = "RAW",
    ) -> Dict:
        body = {"values": values}
        return execute_with_retry(
            lambda: self._service.spreadsheets()
            .values()
            .update(
                spreadsheetId=spreadsheet_id,
                range=a1_range,
                valueInputOption=value_input_option,
                body=body,
            )
            .execute(),
            context=f"writing range '{a1_range}' ({spreadsheet_id})",
            retry=self._retry,
        )

    def append_values(
        self,
        spreadsheet_id: str,
        a1_range: str,
        values: list[list[Any]],
        *,
        value_input_option: str = "RAW",
    ) -> Dict:
        body = {"values": values}
        return execute_with_retry(
            lambda: self._service.spreadsheets()
            .values()
            .append(
                spreadsheetId=spreadsheet_id,
                range=a1_range,
                valueInputOption=value_input_option,
                insertDataOption="INSERT_ROWS",
                body=body,
            )
            .execute(),
            context=f"appending to range '{a1_range}' ({spreadsheet_id})",
            retry=self._retry,
        )

    def clear(self, spreadsheet_id: str, a1_range: str) -> Dict:
        return execute_with_retry(
            lambda: self._service.spreadsheets()
            .values()
            .clear(
                spreadsheetId=spreadsheet_id,
                range=a1_range,
                body={},
            )
            .execute(),
            context=f"clearing range '{a1_range}' ({spreadsheet_id})",
            retry=self._retry,
        )

    def ensure_sheet_exists(
        self, spreadsheet_id: str, sheet_name: str, headers: Optional[list[str]] = None
    ) -> None:
        meta = self.get_metadata(spreadsheet_id)
        titles = [s["properties"]["title"] for s in meta.get("sheets", [])]

        if sheet_name not in titles:
            self.batch_update(
                spreadsheet_id,
                [{"addSheet": {"properties": {"title": sheet_name}}}],
            )

        if headers:
            existing = self.read_values(spreadsheet_id, f"{sheet_name}!1:1")
            if not existing:
                self.write_values(
                    spreadsheet_id,
                    f"{sheet_name}!A1",
                    [headers],
                    value_input_option="RAW",
                )

    def get_sheet_id(self, spreadsheet_id: str, sheet_name: str) -> int:
        meta = self.get_metadata(spreadsheet_id)
        for sheet in meta.get("sheets", []):
            props = sheet.get("properties", {})
            if props.get("title") == sheet_name:
                return int(props["sheetId"])
        raise ValueError(
            f"Sheet '{sheet_name}' not found in spreadsheet {spreadsheet_id}"
        )

    def delete_sheet_by_name(self, spreadsheet_id: str, title: str) -> None:
        """Delete a sheet by title if it exists."""

        try:
            meta = self.get_metadata(spreadsheet_id)
            sheet_id: int | None = None
            for s in meta.get("sheets", []):
                props = s.get("properties", {})
                if props.get("title") == title:
                    sheet_id = int(props.get("sheetId"))
                    break

            if sheet_id is None:
                return

            self.batch_update(
                spreadsheet_id,
                [{"deleteSheet": {"sheetId": sheet_id}}],
            )
        except HttpError as e:
            # Ignore "not found" style errors
            log.debug(f"delete_sheet_by_name: unable to delete '{title}': {e}")

    def clear_all_except_one_sheet(self, spreadsheet_id: str, keep_title: str) -> None:
        """Delete all sheets except keep_title, and clear values on keep_title."""

        meta = self.get_metadata(spreadsheet_id)
        sheets_list = meta.get("sheets", [])

        # Ensure keep sheet exists
        keep_id: int | None = None
        for s in sheets_list:
            props = s.get("properties", {})
            if props.get("title") == keep_title:
                keep_id = int(props.get("sheetId"))
                break

        if keep_id is None:
            self.batch_update(
                spreadsheet_id,
                [{"addSheet": {"properties": {"title": keep_title}}}],
            )
            meta = self.get_metadata(spreadsheet_id)
            sheets_list = meta.get("sheets", [])

        # Delete all sheets except keep_title
        requests: list[dict] = []
        for s in sheets_list:
            props = s.get("properties", {})
            sid = props.get("sheetId")
            title = props.get("title")
            if sid is None or title == keep_title:
                continue
            requests.append({"deleteSheet": {"sheetId": int(sid)}})

        if requests:
            self.batch_update(spreadsheet_id, requests)

        # Clear values on the keep sheet
        self.clear(spreadsheet_id, f"{keep_title}!A:Z")

    def insert_rows(
        self,
        spreadsheet_id: str,
        sheet_title: str,
        rows: list[list[Any]],
        *,
        value_input_option: str = "RAW",
    ) -> None:
        """Ensure sheet exists, then write rows starting at A1."""

        self.ensure_sheet_exists(spreadsheet_id, sheet_title)
        self.write_values(
            spreadsheet_id,
            f"{sheet_title}!A1",
            rows,
            value_input_option=value_input_option,
        )

    def sort_sheet(
        self,
        spreadsheet_id: str,
        sheet_name: str,
        column_index: int,
        *,
        ascending: bool = True,
        start_row: int = 2,
        end_row: int | None = None,
    ) -> Dict:
        sheet_id = self.get_sheet_id(spreadsheet_id, sheet_name)

        sort_range: dict = {"sheetId": sheet_id, "startRowIndex": start_row - 1}
        if end_row is not None:
            sort_range["endRowIndex"] = end_row

        requests = [
            {
                "sortRange": {
                    "range": sort_range,
                    "sortSpecs": [
                        {
                            "dimensionIndex": column_index,
                            "sortOrder": "ASCENDING" if ascending else "DESCENDING",
                        }
                    ],
                }
            }
        ]
        return self.batch_update(spreadsheet_id, requests)

    @staticmethod
    def get_range_format(
        start_col: str, start_row: int, end_col: str, end_row: int | None = None
    ) -> str:
        """Build an A1 range like A5:D or A5:D10."""
        if end_row is None:
            return f"{start_col}{start_row}:{end_col}"
        return f"{start_col}{start_row}:{end_col}{end_row}"
