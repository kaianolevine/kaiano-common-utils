from unittest.mock import Mock

from kaiano_common_utils import helpers as h

# =====================================================
# Basic utilities
# =====================================================


def test_extract_date_and_title_with_date():
    date, title = h.extract_date_and_title("2025-10-13 My Song")
    assert date == "2025-10-13"
    assert "My Song" in title


def test_extract_date_and_title_without_date():
    date, title = h.extract_date_and_title("My Song.mp3")
    assert date == ""
    assert title == "My Song.mp3"


def test_extract_year_from_filename_logs(monkeypatch):
    calls = {}
    monkeypatch.setattr(h.log, "debug", lambda m: calls.setdefault("debug", True))
    result = h.extract_year_from_filename("2024-05-22_file.csv")
    assert result == "2024"
    assert calls["debug"]


# =====================================================
# normalize_csv
# =====================================================


def test_normalize_csv_reads_and_writes(tmp_path, monkeypatch):
    p = tmp_path / "f.csv"
    p.write_text("A  B\n\nC   D\n")
    monkeypatch.setattr(h.log, "debug", lambda m: None)
    monkeypatch.setattr(h.log, "info", lambda m: None)
    h.normalize_csv(str(p))
    data = p.read_text()
    assert "A B" in data and "C D" in data


# =====================================================
# normalize_prefixes_in_source
# =====================================================


def test_normalize_prefixes_in_source_handles_prefixes(monkeypatch):
    drive = Mock()
    drive.files.return_value.list.return_value.execute.side_effect = [
        {"files": [{"id": "1", "name": "FAILED_test.csv"}]},  # first list call
        {"files": []},  # exists_resp
    ]
    drive.files.return_value.update.return_value.execute.return_value = {}

    monkeypatch.setattr(h.config, "CSV_SOURCE_FOLDER_ID", "source")
    monkeypatch.setattr(h.log, "info", lambda m: None)
    monkeypatch.setattr(h.log, "debug", lambda m: None)
    monkeypatch.setattr(h.log, "warning", lambda m: None)
    monkeypatch.setattr(h.log, "error", lambda m: None)

    h.normalize_prefixes_in_source(drive)
    drive.files.return_value.update.assert_called()


def test_normalize_prefixes_in_source_handles_existing_target(monkeypatch):
    drive = Mock()
    drive.files.return_value.list.return_value.execute.side_effect = [
        {"files": [{"id": "1", "name": "Copy of test.csv"}]},
        {"files": [{"id": "2", "name": "test.csv"}]},  # exists
    ]
    monkeypatch.setattr(h.config, "CSV_SOURCE_FOLDER_ID", "source")
    monkeypatch.setattr(h.log, "info", lambda m: None)
    monkeypatch.setattr(h.log, "debug", lambda m: None)
    h.normalize_prefixes_in_source(drive)
    drive.files.return_value.update.assert_not_called()


def test_normalize_prefixes_in_source_handles_error(monkeypatch):
    drive = Mock()
    drive.files.return_value.list.side_effect = Exception("boom")
    monkeypatch.setattr(h.config, "CSV_SOURCE_FOLDER_ID", "source")
    monkeypatch.setattr(h.log, "error", lambda m: None)
    h.normalize_prefixes_in_source(drive)  # should log error but not raise
