from typing import Any, Dict, Optional

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

    def get_metadata(self, spreadsheet_id: str) -> Dict:
        return execute_with_retry(
            lambda: self._service.spreadsheets()
            .get(spreadsheetId=spreadsheet_id)
            .execute(),
            context=f"fetching spreadsheet metadata ({spreadsheet_id})",
            retry=self._retry,
        )

    def batch_update(self, spreadsheet_id: str, requests: list[dict]) -> Dict:
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

    def get_range_format(
        start_col: str, start_row: int, end_col: str, end_row: int | None = None
    ) -> str:
        """Build an A1 range like A5:D or A5:D10."""
        if end_row is None:
            return f"{start_col}{start_row}:{end_col}"
        return f"{start_col}{start_row}:{end_col}{end_row}"
