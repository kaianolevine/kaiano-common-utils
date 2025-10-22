import time
from unittest.mock import MagicMock

import pytest

import kaiano_common_utils.spotify as spotify


@pytest.fixture(autouse=True)
def reset_client_cache():
    """Ensure _spotify_client cache is cleared before each test."""
    spotify._spotify_client = None
    yield
    spotify._spotify_client = None


@pytest.fixture
def mock_config(monkeypatch):
    """Provide fake config values for all required env vars."""
    monkeypatch.setattr(spotify.config, "SPOTIFY_CLIENT_ID", "fake_id")
    monkeypatch.setattr(spotify.config, "SPOTIFY_CLIENT_SECRET", "fake_secret")
    monkeypatch.setattr(spotify.config, "SPOTIFY_REDIRECT_URI", "http://localhost")
    monkeypatch.setattr(spotify.config, "SPOTIFY_REFRESH_TOKEN", "fake_refresh")
    monkeypatch.setattr(spotify.config, "SPOTIFY_PLAYLIST_ID", "playlist_123")
    return spotify.config


# -------------------------------------------------------------------
# Search
# -------------------------------------------------------------------


def test_search_track_found(monkeypatch, mock_config):
    mock_sp = MagicMock()
    mock_sp.search.return_value = {"tracks": {"items": [{"uri": "spotify:track:1"}]}}
    monkeypatch.setattr(spotify, "get_spotify_client_from_refresh", lambda: mock_sp)

    uri = spotify.search_track("Artist", "Song")
    assert uri == "spotify:track:1"
    mock_sp.search.assert_called_with(
        q="artist:Artist track:Song", type="track", limit=1
    )


def test_search_track_retry_with_relaxed(monkeypatch, mock_config):
    mock_sp = MagicMock()
    # first call returns no tracks, second returns one
    mock_sp.search.side_effect = [
        {"tracks": {"items": []}},
        {"tracks": {"items": [{"uri": "spotify:track:2"}]}},
    ]
    monkeypatch.setattr(spotify, "get_spotify_client_from_refresh", lambda: mock_sp)

    uri = spotify.search_track("A", "B")
    assert uri == "spotify:track:2"
    assert mock_sp.search.call_count >= 2


def test_search_track_rate_limit(monkeypatch, mock_config):
    mock_sp = MagicMock()
    exc = spotify.SpotifyException(429, -1, "rate", headers={"Retry-After": "1"})
    mock_sp.search.side_effect = [
        exc,
        {"tracks": {"items": [{"uri": "spotify:track:9"}]}},
    ]
    monkeypatch.setattr(spotify, "get_spotify_client_from_refresh", lambda: mock_sp)

    start = time.time()
    uri = spotify.search_track("A", "B")
    elapsed = time.time() - start
    assert uri == "spotify:track:9"
    assert elapsed >= 1  # waited for rate limit


def test_search_track_forbidden(monkeypatch, mock_config):
    mock_sp = MagicMock()
    exc = spotify.SpotifyException(403, -1, "forbidden")
    mock_sp.search.side_effect = [exc]
    monkeypatch.setattr(spotify, "get_spotify_client_from_refresh", lambda: mock_sp)
    assert spotify.search_track("A", "B") is None


def test_search_track_other_exception(monkeypatch, mock_config):
    mock_sp = MagicMock()
    exc = spotify.SpotifyException(500, -1, "error")
    mock_sp.search.side_effect = [exc]
    monkeypatch.setattr(spotify, "get_spotify_client_from_refresh", lambda: mock_sp)
    assert spotify.search_track("A", "B") is None


def test_search_track_no_results(monkeypatch, mock_config):
    mock_sp = MagicMock()
    mock_sp.search.return_value = {"tracks": {"items": []}}
    monkeypatch.setattr(spotify, "get_spotify_client_from_refresh", lambda: mock_sp)
    assert spotify.search_track("A", "B") is None
