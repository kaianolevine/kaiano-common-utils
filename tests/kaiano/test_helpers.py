from kaiano import helpers as h

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
