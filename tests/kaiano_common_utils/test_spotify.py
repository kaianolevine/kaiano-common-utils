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
# Client Initialization
# -------------------------------------------------------------------


def test_get_spotify_client_uses_refresh(monkeypatch, mock_config):
    mock_spotify = MagicMock()
    monkeypatch.setattr(
        spotify, "get_spotify_client_from_refresh", lambda: mock_spotify
    )

    client = spotify.get_spotify_client()
    assert client == mock_spotify
    # second call uses cached client
    assert spotify.get_spotify_client() == client


def test_get_spotify_client_local_auth(monkeypatch):
    monkeypatch.setattr(spotify.config, "SPOTIFY_REFRESH_TOKEN", "")
    mock_spotify_instance = MagicMock()
    mock_oauth = MagicMock()
    monkeypatch.setattr(spotify, "SpotifyOAuth", lambda **kwargs: mock_oauth)
    monkeypatch.setattr(
        spotify.spotipy, "Spotify", lambda auth_manager=None: mock_spotify_instance
    )

    client = spotify.get_spotify_client()
    assert client == mock_spotify_instance
    assert spotify._spotify_client == mock_spotify_instance


def test_get_spotify_client_from_refresh_missing_credentials(monkeypatch):
    monkeypatch.setattr(spotify.config, "SPOTIFY_CLIENT_ID", None)
    with pytest.raises(ValueError):
        spotify.get_spotify_client_from_refresh()


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


# -------------------------------------------------------------------
# Playlist Add / Trim
# -------------------------------------------------------------------


def test_add_tracks_to_playlist_happy(monkeypatch, mock_config):
    mock_sp = MagicMock()
    monkeypatch.setattr(spotify, "get_spotify_client", lambda: mock_sp)
    spotify.add_tracks_to_playlist(["t1", "t1", "t2"])
    mock_sp.playlist_add_items.assert_called_once()
    args, kwargs = mock_sp.playlist_add_items.call_args
    assert args[1] == ["t1", "t2"]  # deduped


def test_add_tracks_to_playlist_missing_env(monkeypatch):
    monkeypatch.setattr(spotify.config, "SPOTIFY_PLAYLIST_ID", "")
    with pytest.raises(EnvironmentError):
        spotify.add_tracks_to_playlist(["a"])


def test_add_tracks_to_playlist_no_tracks(monkeypatch, mock_config, capsys):
    spotify.add_tracks_to_playlist([])
    captured = capsys.readouterr()
    assert "No tracks to add" in captured.out


def test_trim_playlist_within_limit(monkeypatch, mock_config):
    mock_sp = MagicMock()
    mock_sp.playlist_items.return_value = {"total": 10}
    monkeypatch.setattr(spotify, "get_spotify_client", lambda: mock_sp)
    spotify.trim_playlist_to_limit(limit=20)
    mock_sp.playlist_remove_all_occurrences_of_items.assert_not_called()


def test_trim_playlist_exceeds_limit(monkeypatch, mock_config):
    mock_sp = MagicMock()
    mock_sp.playlist_items.return_value = {
        "total": 250,
        "items": [{"track": {"uri": f"track_{i}"}} for i in range(250)],
    }
    monkeypatch.setattr(spotify, "get_spotify_client", lambda: mock_sp)
    spotify.trim_playlist_to_limit(limit=200)
    mock_sp.playlist_remove_all_occurrences_of_items.assert_called_once()
    args, _ = mock_sp.playlist_remove_all_occurrences_of_items.call_args
    assert len(args[1]) == 50  # 250 - 200 removed


def test_create_playlist_success(monkeypatch):
    mock_sp = MagicMock()
    mock_sp.current_user.return_value = {"id": "user123"}
    mock_sp.user_playlist_create.return_value = {"id": "plid"}
    monkeypatch.setattr(spotify, "get_spotify_client", lambda: mock_sp)
    pid = spotify.create_playlist("MyList")
    assert pid == "plid"


def test_create_playlist_failure(monkeypatch):
    mock_sp = MagicMock()
    mock_sp.current_user.side_effect = Exception("bad")
    monkeypatch.setattr(spotify, "get_spotify_client", lambda: mock_sp)
    assert spotify.create_playlist("Fail") is None


def test_add_tracks_to_specific_playlist(monkeypatch):
    mock_sp = MagicMock()
    monkeypatch.setattr(spotify, "get_spotify_client", lambda: mock_sp)
    spotify.add_tracks_to_specific_playlist("pid", ["u1", "u1", "u2"])
    mock_sp.playlist_add_items.assert_called_once()
    args, _ = mock_sp.playlist_add_items.call_args
    assert args[1] == ["u1", "u2"]  # deduped


def test_add_tracks_to_specific_playlist_no_id(monkeypatch):
    spotify.add_tracks_to_specific_playlist("", ["x"])
    spotify.add_tracks_to_specific_playlist("pid", [])
    # Should just skip without exception
