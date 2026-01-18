from __future__ import annotations


def test_sheets_formatting_low_level_and_recipes(monkeypatch):
    from kaiano.google import sheets_formatting as sf

    monkeypatch.setattr(sf.time, "sleep", lambda _s: None)

    captured = {"requests": []}

    class _Exec:
        def __init__(self, fn):
            self._fn = fn

        def execute(self):
            return self._fn()

    class _Svc:
        def spreadsheets(self):
            class _Sheets:
                def get(self, spreadsheetId=None, fields=None, includeGridData=None):
                    # Minimal metadata with one sheet
                    return _Exec(
                        lambda: {
                            "sheets": [
                                {
                                    "properties": {
                                        "title": "A",
                                        "sheetId": 1,
                                        "gridProperties": {
                                            "rowCount": 10,
                                            "columnCount": 3,
                                        },
                                    }
                                },
                                {
                                    "properties": {
                                        "title": "B",
                                        "sheetId": 2,
                                        "gridProperties": {
                                            "rowCount": 5,
                                            "columnCount": 2,
                                        },
                                    }
                                },
                            ]
                        }
                    )

                def batchUpdate(self, spreadsheetId=None, body=None):
                    # capture and return a plausible response
                    captured["requests"].append(body.get("requests", []))
                    return _Exec(lambda: {"replies": []})

                def values(self):
                    class _Values:
                        def update(
                            self,
                            spreadsheetId=None,
                            range=None,
                            valueInputOption=None,
                            body=None,
                        ):
                            return _Exec(lambda: {"updated": True})

                    return _Values()

            return _Sheets()

    svc = _Svc()

    # Patch helpers that would otherwise fetch metadata
    monkeypatch.setattr(sf, "_get_sheet_id_by_name", lambda *_a, **_k: 99)
    monkeypatch.setattr(sf, "_execute_with_http_retry", lambda fn, **_k: fn())

    # Basic formatting primitives
    sf.set_bold_font(svc, "ssid", 1, 1, 3, 1, 2)
    sf.freeze_rows(svc, "ssid", 1, 1)
    sf.set_horizontal_alignment(svc, "ssid", 1, 1, 3, 1, 2, alignment="CENTER")
    sf.set_number_format(svc, "ssid", 1, 1, 3, 1, 2, {"type": "TEXT", "pattern": "@"})
    sf.auto_resize_columns(svc, "ssid", 1, 1, 3)

    # Values update helper
    sf.update_sheet_values(svc, "ssid", "A", [["H"], ["1"]])

    # Column/text formatting + reorder + summary-sheet recipe
    meta = {
        "sheets": [
            {"properties": {"title": "A", "sheetId": 1}},
            {"properties": {"title": "B", "sheetId": 2}},
        ]
    }
    sf.set_column_text_formatting(svc, "ssid", "A", [0, 2])
    sf.reorder_sheets(svc, "ssid", ["B", "A"], meta)
    sf.format_summary_sheet(svc, "ssid", "A", ["H1", "H2"], [["a", "b"], ["c", "d"]])

    # Higher-level legacy per-sheet formatting (exercise request construction)
    monkeypatch.setattr(sf, "_get_sheets_service", lambda *_a, **_k: svc)
    sf.set_sheet_formatting(
        "ssid",
        1,
        header_row_count=1,
        total_rows=5,
        total_cols=3,
        backgrounds=[["#ffffff", "#ffffff", "#ffffff"] for _ in range(5)],
    )

    # Column-formatting recipe
    sf.set_column_formatting(svc, "ssid", "A", num_columns=3)

    # Ensure we produced a non-trivial number of batchUpdate request lists
    assert len(captured["requests"]) >= 8


def test_sheet_formatter_convenience(monkeypatch):
    from kaiano.google.sheets_formatting import SheetFormatter

    class _Svc:
        def __init__(self):
            self.requests = []

        def spreadsheets(self):
            svc = self

            class _Sheets:
                def get(self, spreadsheetId=None, fields=None, includeGridData=None):
                    class _Exec:
                        def execute(self_inner):
                            return {
                                "sheets": [{"properties": {"title": "A", "sheetId": 1}}]
                            }

                    return _Exec()

                def batchUpdate(self, spreadsheetId=None, body=None):
                    svc.requests.extend(body.get("requests", []))

                    class _Exec:
                        def execute(self_inner):
                            return {"ok": True}

                    return _Exec()

            return _Sheets()

    svc = _Svc()
    f = SheetFormatter(svc, "ssid")

    # Minimal smoke test: exercise the convenience methods
    f.freeze_headers("A", rows=1)
    f.bold_header("A")
    f.text_columns("A", [0, 1])
    f.number_format("A", 1, 2, 1, 2, "@")
    f.auto_resize("A", start_col=1, end_col=3)

    assert svc.requests
