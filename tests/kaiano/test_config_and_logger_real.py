import importlib.util
from pathlib import Path


def _load_module_from_path(module_name: str, path: Path):
    """Load a module from a file path under a custom name.

    We do this because the existing google/ conftest installs stubs into
    sys.modules for kaiano.config and kaiano.logger.
    Loading by file path still exercises the real source files for coverage.
    """

    spec = importlib.util.spec_from_file_location(module_name, str(path))
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # type: ignore[attr-defined]
    return mod


def test_config_env_overrides_are_applied(tmp_path, monkeypatch):
    # Arrange: make sure LOGGING_LEVEL is read and uppercased.
    monkeypatch.setenv("LOGGING_LEVEL", "info")

    config_path = Path(__file__).resolve().parents[2] / "src" / "kaiano" / "config.py"
    cfg = _load_module_from_path("kaiano_real_config", config_path)

    assert cfg.LOGGING_LEVEL == "INFO"
    # Sanity: important constants exist (spot-check)
    assert isinstance(cfg.TIMEZONE, str)
    assert "title" in cfg.ALLOWED_HEADERS


def test_logger_helpers(tmp_path, monkeypatch):
    monkeypatch.setenv("LOGGING_LEVEL", "warning")

    # Load config first so logger imports it with the overridden env.
    root = Path(__file__).resolve().parents[2]
    cfg = _load_module_from_path(
        "kaiano_real_config_for_logger", root / "src" / "kaiano" / "config.py"
    )
    assert cfg.LOGGING_LEVEL == "WARNING"

    # The test suite installs stub modules for kaiano.config/kaiano.logger.
    # Temporarily point kaiano.config at our real module so logger.py can import it.
    import sys

    prior = sys.modules.get("kaiano.config")
    sys.modules["kaiano.config"] = cfg

    try:
        logger_mod = _load_module_from_path(
            "kaiano_real_logger", root / "src" / "kaiano" / "logger.py"
        )
    finally:
        if prior is not None:
            sys.modules["kaiano.config"] = prior
        else:
            sys.modules.pop("kaiano.config", None)

    log = logger_mod.get_logger()
    assert log is logger_mod.logger

    # Shortcut aliases exist and are callable
    assert callable(logger_mod.info)
    assert callable(logger_mod.error)

    import datetime

    dt = datetime.datetime(2026, 1, 19, 15, 30)
    assert logger_mod.format_date(dt) == "2026-01-19 15:30"
