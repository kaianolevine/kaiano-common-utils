from __future__ import annotations


def test_retry_execute_with_retry_zero_retries_hits_defensive_path():
    from kaiano.google._retry import RetryConfig, execute_with_retry

    # With max_retries=0, the loop never runs; we should get the final RuntimeError.
    try:
        execute_with_retry(lambda: 1, context="unit", retry=RetryConfig(max_retries=0))
    except RuntimeError as e:
        assert "Unknown error" in str(e) or "Unknown" in str(e)
    else:
        raise AssertionError("expected RuntimeError")


def test_errors_module_smoke():
    from kaiano.google.errors import GoogleAPIError, NotFoundError

    assert issubclass(NotFoundError, GoogleAPIError)


def test_sheets_facade_exercises_write_append_clear_insert_sort(monkeypatch):
    # Reuse FakeSheetsService from the other test module (pytest loads tests as top-level modules)
    import importlib

    from kaiano.google.sheets import SheetsFacade

    FakeSheetsService = importlib.import_module("test_sheets_facade").FakeSheetsService

    svc = FakeSheetsService()
    sheets = SheetsFacade(svc)

    sheets.write_values("ssid", "Sheet1!A1", [["a"]])
    sheets.append_values("ssid", "Sheet1!A1", [["b"]])
    sheets.clear("ssid", "Sheet1!A1")
    sheets.insert_rows("ssid", "Inserted", [["h"], ["1"]])
    sheets.sort_sheet("ssid", "Sheet1", 0, ascending=False, start_row=1, end_row=10)

    ops = [c[0] for c in svc.calls]
    assert "values.update" in ops
    assert "values.append" in ops
    assert "values.clear" in ops
    assert "batchUpdate" in ops


def test_drive_facade_exercises_remaining_helpers(monkeypatch, tmp_path):
    import importlib

    from kaiano.google.drive import DriveFacade
    from kaiano.google.types import DriveFile

    FakeDriveService = importlib.import_module("test_drive_facade").FakeDriveService

    svc = FakeDriveService()

    # Force Drive "find" query to return no existing spreadsheets so create path is taken.
    original_files = svc.files

    class _Exec:
        def __init__(self, fn):
            self._fn = fn

        def execute(self):
            return self._fn()

    def files_empty_list():
        f = original_files()

        def list(**kwargs):
            return _Exec(lambda: {"files": []})

        f.list = list  # type: ignore[attr-defined]
        return f

    svc.files = files_empty_list  # type: ignore[assignment]
    drive = DriveFacade(svc)

    # find_or_create_spreadsheet -> create path
    monkeypatch.setattr(
        drive, "create_spreadsheet_in_folder", lambda name, folder_id: "new_sheet"
    )
    assert (
        drive.find_or_create_spreadsheet(parent_folder_id="p", name="X") == "new_sheet"
    )

    # get_all_subfolders / get_files_in_folder just call list_files
    monkeypatch.setattr(
        drive, "list_files", lambda *a, **k: [DriveFile(id="f", name="n")]
    )
    assert drive.get_all_subfolders("p")[0].id == "f"
    assert drive.get_files_in_folder("p")[0].name == "n"

    # upload_csv_as_google_sheet + create_spreadsheet_in_folder cover media upload mimeType
    p = tmp_path / "x.csv"
    p.write_text("a,b")
    drive.upload_csv_as_google_sheet(str(p), parent_id="p", dest_name="Y")
    drive.create_spreadsheet_in_folder("S", "p")


def test_sheets_formatting_apply_formatting_to_sheet_and_helpers(monkeypatch):
    from kaiano.google import sheets_formatting as sf

    # Avoid sleeps
    monkeypatch.setattr(sf.time, "sleep", lambda _s: None)

    # Fake sheets service with minimal get + batchUpdate
    class _Exec:
        def __init__(self, fn):
            self._fn = fn

        def execute(self):
            return self._fn()

    class _Svc:
        def spreadsheets(self):
            class _Sheets:
                def get(self, spreadsheetId=None, includeGridData=None, fields=None):
                    # Return metadata with 2 sheets and gridProperties
                    return _Exec(
                        lambda: {
                            "sheets": [
                                {
                                    "properties": {
                                        "sheetId": 1,
                                        "title": "A",
                                        "gridProperties": {
                                            "columnCount": 3,
                                            "rowCount": 10,
                                        },
                                    },
                                    "data": [
                                        {
                                            "columnMetadata": [
                                                {"pixelSize": 100},
                                                {"pixelSize": 120},
                                                {"pixelSize": 330},
                                            ]
                                        }
                                    ],
                                },
                                {
                                    "properties": {
                                        "sheetId": 2,
                                        "title": "B",
                                        "gridProperties": {
                                            "columnCount": 2,
                                            "rowCount": 5,
                                        },
                                    },
                                    "data": [
                                        {
                                            "columnMetadata": [
                                                {"pixelSize": 50},
                                                {"pixelSize": None},
                                            ]
                                        }
                                    ],
                                },
                            ]
                        }
                    )

                def batchUpdate(self, spreadsheetId=None, body=None):
                    return _Exec(
                        lambda: {"replies": [], "requests": body.get("requests", [])}
                    )

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

    monkeypatch.setattr(sf, "_get_sheets_service", lambda *a, **k: _Svc())

    captured = {"batches": []}

    def capture_batch(_svc, _ssid, requests, **_kwargs):
        captured["batches"].append(list(requests))

    monkeypatch.setattr(sf, "_batch_update_with_retry", capture_batch)

    # Force a deterministic column pixel-size lookup
    monkeypatch.setattr(
        sf,
        "_get_column_pixel_sizes",
        lambda *_a, **_k: {1: [100, 120, 330], 2: [50, None]},
    )

    sf.apply_formatting_to_sheet("ssid")

    # We should have at least 2 batches: initial formatting + width buffer
    assert len(captured["batches"]) >= 2

    # Cover helpers
    assert sf._prepare_cell_for_user_entered(None, force_text=True) == ""
    assert sf._prepare_cell_for_user_entered(
        "=HYPERLINK('x','y')", force_text=True
    ).startswith("=")
    assert sf._prepare_cell_for_user_entered(123, force_text=True).startswith("'")
    assert sf._prepare_cell_for_user_entered(123, force_text=False) == 123

    # set_values uses USER_ENTERED vs RAW paths
    svc = _Svc()
    sf.set_values(svc, "ssid", "A", 1, 1, [["x", 1]], force_text=True)
    sf.set_values(svc, "ssid", "A", 1, 1, [["x", 1]], force_text=False)
