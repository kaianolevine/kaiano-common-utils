from __future__ import annotations


def test_hex_to_rgb_variants():
    from kaiano.google.sheets_formatting import hex_to_rgb

    assert hex_to_rgb("#ffffff") == {"red": 1.0, "green": 1.0, "blue": 1.0}
    assert hex_to_rgb("000000") == {"red": 0.0, "green": 0.0, "blue": 0.0}
    assert hex_to_rgb("#abc") == {
        "red": 0xAA / 255,
        "green": 0xBB / 255,
        "blue": 0xCC / 255,
    }
    # Invalid -> white
    assert hex_to_rgb("not-a-color") == {"red": 1.0, "green": 1.0, "blue": 1.0}


def test_as_sheets_service_accepts_facade_or_raw(monkeypatch):
    from kaiano.google.sheets_formatting import _as_sheets_service

    raw = object()
    assert _as_sheets_service(raw) is raw

    class Facade:
        def __init__(self, service):
            self.service = service

    assert _as_sheets_service(Facade(raw)) is raw


def test_execute_with_http_retry_retries_then_succeeds(monkeypatch, as_http_error):
    from kaiano.google.sheets_formatting import _execute_with_http_retry

    monkeypatch.setattr("kaiano.google.sheets_formatting.time.sleep", lambda _s: None)

    state = {"n": 0}

    def fn():
        state["n"] += 1
        if state["n"] < 3:
            raise as_http_error(status=503)
        return "ok"

    assert _execute_with_http_retry(fn, operation="unit", max_attempts=5) == "ok"
    assert state["n"] == 3


def test_execute_with_http_retry_non_retryable_raises(monkeypatch, as_http_error):
    from kaiano.google.sheets_formatting import _execute_with_http_retry

    monkeypatch.setattr("kaiano.google.sheets_formatting.time.sleep", lambda _s: None)

    def fn():
        raise as_http_error(status=404)

    try:
        _execute_with_http_retry(fn, operation="unit", max_attempts=3)
    except Exception as e:
        assert "HttpError" in str(e)
    else:
        raise AssertionError("expected error")


def test_batch_update_with_retry_retries(monkeypatch, as_http_error):
    from kaiano.google.sheets_formatting import _batch_update_with_retry

    monkeypatch.setattr("kaiano.google.sheets_formatting.time.sleep", lambda _s: None)

    class _Svc:
        def __init__(self):
            self.n = 0

        def spreadsheets(self):
            svc = self

            class _Sheets:
                def batchUpdate(self, spreadsheetId, body):
                    def run():
                        svc.n += 1
                        if svc.n < 3:
                            raise as_http_error(status=503)
                        return {"ok": True}

                    class _Exec:
                        def execute(self_inner):
                            return run()

                    return _Exec()

            return _Sheets()

    svc = _Svc()
    _batch_update_with_retry(svc, "ssid", [{"noop": True}], max_attempts=5)
    assert svc.n == 3


def test_apply_sheet_formatting_builds_single_batch_update(monkeypatch):
    """Smoke-test that apply_sheet_formatting composes requests and calls batchUpdate."""

    from kaiano.google import sheets_formatting as sf

    captured = {"requests": None}

    def fake_get_service(*_a, **_k):
        return object()

    monkeypatch.setattr(sf, "_get_sheets_service", fake_get_service)

    def capture_batch(_svc, _ssid, requests, **_kwargs):
        captured["requests"] = requests

    monkeypatch.setattr(sf, "_batch_update_with_retry", capture_batch)

    class _Spreadsheet:
        id = "ssid"

    class _Sheet:
        spreadsheet = _Spreadsheet()
        id = 123
        col_count = 5

    sf.apply_sheet_formatting(_Sheet())
    # apply_sheet_formatting should have prepared a small set of requests
    assert isinstance(captured["requests"], list)
    assert any(
        "freeze" in str(r).lower() or "frozenrowcount" in str(r).lower()
        for r in captured["requests"]
    )
