from unittest.mock import MagicMock, patch

import pytest

import kaiano_common_utils.spotify as spotify


@pytest.fixture(autouse=True)
def clear_spotify_client_cache():
    """Ensure _spotify_client is reset between tests."""
    spotify._spotify_client = None
    yield
    spotify._spotify_client = None


@pytest.fixture
def mock_config(monkeypatch):
    """Provide fake Spotify config values."""
    monkeypatch.setattr(spotify.config, "SPOTIPY_CLIENT_ID", "id")
    monkeypatch.setattr(spotify.config, "SPOTIPY_CLIENT_SECRET", "secret")
    monkeypatch.setattr(spotify.config, "SPOTIPY_REDIRECT_URI", "uri")
    monkeypatch.setattr(spotify.config, "SPOTIFY_REFRESH_TOKEN", "refresh")
    monkeypatch.setattr(spotify.config, "SPOTIFY_PLAYLIST_ID", "playlist123")
    return spotify.config


@pytest.fixture
def ensure_config(monkeypatch):
    """Set environment variables and config attributes for Spotify credentials."""
    creds = {
        "SPOTIPY_CLIENT_ID": "id",
        "SPOTIPY_CLIENT_SECRET": "secret",
        "SPOTIPY_REDIRECT_URI": "uri",
        "SPOTIFY_REFRESH_TOKEN": "refresh",
    }
    for key, val in creds.items():
        monkeypatch.setenv(key, val)
        monkeypatch.setattr(spotify.config, key, val)
    monkeypatch.setattr(spotify.config, "SPOTIFY_PLAYLIST_ID", "playlist123")
    return spotify.config


# ---------------------------------------------------------------------------
# get_spotify_client / get_spotify_client_from_refresh
# ---------------------------------------------------------------------------


@patch(
    "kaiano_common_utils.spotify.SpotifyOAuth.refresh_access_token",
    side_effect=Exception("fail"),
)
def test_get_spotify_client_from_refresh_failure(mock_refresh, mock_config):
    with pytest.raises(Exception):
        spotify.get_spotify_client_from_refresh()


def test_get_spotify_client_from_refresh_missing_env(monkeypatch):
    monkeypatch.setattr(spotify.config, "SPOTIPY_CLIENT_ID", None)
    with pytest.raises(ValueError):
        spotify.get_spotify_client_from_refresh()


# ---------------------------------------------------------------------------
# search_track
# ---------------------------------------------------------------------------


@patch("kaiano_common_utils.spotify.get_spotify_client")
def test_search_track_found(mock_client):
    sp = MagicMock()
    sp.search.return_value = {"tracks": {"items": [{"uri": "spotify:track:1"}]}}
    mock_client.return_value = sp
    result = spotify.search_track("artist", "title")
    assert result == "spotify:track:1"


@patch("kaiano_common_utils.spotify.get_spotify_client")
def test_search_track_no_results_relaxed_retry(mock_client):
    sp = MagicMock()
    sp.search.side_effect = [
        {"tracks": {"items": []}},
        {"tracks": {"items": []}},
    ]
    mock_client.return_value = sp
    result = spotify.search_track("a", "b")
    assert result is None
    assert sp.search.call_count == 2


@patch("kaiano_common_utils.spotify.get_spotify_client")
def test_search_track_403(mock_client):
    from spotipy.exceptions import SpotifyException

    sp = MagicMock()
    err = SpotifyException(
        http_status=403, code=403, msg="Forbidden", reason="forbidden", headers={}
    )
    sp.search.side_effect = err
    mock_client.return_value = sp
    result = spotify.search_track("a", "b")
    assert result is None


@patch("kaiano_common_utils.spotify.get_spotify_client")
def test_search_track_429_retries(mock_client):
    from spotipy.exceptions import SpotifyException

    sp = MagicMock()
    err = SpotifyException(
        http_status=429,
        code=429,
        msg="Rate limited",
        reason="ratelimit",
        headers={"Retry-After": "0"},
    )
    sp.search.side_effect = [err, {"tracks": {"items": [{"uri": "uri"}]}}]
    mock_client.return_value = sp
    result = spotify.search_track("a", "b")
    assert result == "uri"
    assert sp.search.call_count == 2


# ---------------------------------------------------------------------------
# add_tracks_to_playlist
# ---------------------------------------------------------------------------


@patch("kaiano_common_utils.spotify.get_spotify_client")
def test_add_tracks_to_playlist_adds_new(mock_client, mock_config):
    sp = MagicMock()
    sp.playlist_items.side_effect = [
        {"items": [{"track": {"uri": "olduri"}}], "next": None},
    ]
    mock_client.return_value = sp
    spotify.add_tracks_to_playlist(["uri1", "uri2", "olduri"])
    sp.playlist_add_items.assert_called_once()


@patch("kaiano_common_utils.spotify.get_spotify_client")
def test_add_tracks_to_playlist_no_new_tracks(mock_client, mock_config, capsys):
    sp = MagicMock()
    sp.playlist_items.return_value = {
        "items": [{"track": {"uri": "uri"}}],
        "next": None,
    }
    mock_client.return_value = sp
    spotify.add_tracks_to_playlist(["uri"])
    out = capsys.readouterr().out
    assert "No new tracks to add" in out


def test_add_tracks_to_playlist_missing_env(monkeypatch):
    monkeypatch.setattr(spotify.config, "SPOTIFY_PLAYLIST_ID", None)
    with pytest.raises(EnvironmentError):
        spotify.add_tracks_to_playlist(["uri"])


def test_add_tracks_to_playlist_empty_list(capsys, mock_config):
    spotify.add_tracks_to_playlist([])
    out = capsys.readouterr().out
    assert "No tracks to add" in out


# ---------------------------------------------------------------------------
# trim_playlist_to_limit
# ---------------------------------------------------------------------------


@patch("kaiano_common_utils.spotify.get_spotify_client")
def test_trim_playlist_within_limit(mock_client, mock_config):
    sp = MagicMock()
    sp.playlist_items.return_value = {"total": 10, "items": []}
    mock_client.return_value = sp
    spotify.trim_playlist_to_limit(limit=20)
    sp.playlist_remove_all_occurrences_of_items.assert_not_called()


@patch("kaiano_common_utils.spotify.get_spotify_client")
def test_trim_playlist_removes_tracks(mock_client, mock_config, capsys):
    sp = MagicMock()
    sp.playlist_items.return_value = {
        "total": 5,
        "items": [
            {"track": {"uri": "a"}},
            {"track": {"uri": "b"}},
            {"track": {"uri": "c"}},
            {"track": {"uri": "d"}},
            {"track": {"uri": "e"}},
        ],
    }
    mock_client.return_value = sp
    spotify.trim_playlist_to_limit(limit=3)
    sp.playlist_remove_all_occurrences_of_items.assert_called_once()
    assert "🗑️ Removed" in capsys.readouterr().out


def test_trim_playlist_missing_env(monkeypatch):
    monkeypatch.setattr(spotify.config, "SPOTIFY_PLAYLIST_ID", None)
    with pytest.raises(EnvironmentError):
        spotify.trim_playlist_to_limit()


# ---------------------------------------------------------------------------
# create_playlist
# ---------------------------------------------------------------------------


@patch("kaiano_common_utils.spotify.get_spotify_client")
def test_create_playlist_success(mock_client):
    sp = MagicMock()
    sp.current_user.return_value = {"id": "u"}
    sp.user_playlist_create.return_value = {"id": "playlist_id"}
    mock_client.return_value = sp
    result = spotify.create_playlist("My List")
    assert result == "playlist_id"


@patch("kaiano_common_utils.spotify.get_spotify_client")
def test_create_playlist_failure(mock_client):
    sp = MagicMock()
    sp.user_playlist_create.side_effect = Exception("boom")
    sp.current_user.return_value = {"id": "u"}
    mock_client.return_value = sp
    result = spotify.create_playlist("My List")
    assert result is None


# ---------------------------------------------------------------------------
# add_tracks_to_specific_playlist
# ---------------------------------------------------------------------------


@patch("kaiano_common_utils.spotify.get_spotify_client")
def test_add_tracks_to_specific_playlist_success(mock_client):
    sp = MagicMock()
    mock_client.return_value = sp
    spotify.add_tracks_to_specific_playlist("pid", ["a", "b", "a"])
    sp.playlist_add_items.assert_called_once()


@patch("kaiano_common_utils.spotify.get_spotify_client")
def test_add_tracks_to_specific_playlist_failure(mock_client):
    sp = MagicMock()
    sp.playlist_add_items.side_effect = Exception("fail")
    mock_client.return_value = sp
    spotify.add_tracks_to_specific_playlist("pid", ["a"])
    sp.playlist_add_items.assert_called_once()


def test_add_tracks_to_specific_playlist_no_data():
    spotify.add_tracks_to_specific_playlist("", [])


# ---------------------------------------------------------------------------
# find_playlist_by_name
# ---------------------------------------------------------------------------


@patch("kaiano_common_utils.spotify.get_spotify_client_from_refresh")
def test_find_playlist_by_name_found(mock_spotify):
    sp = MagicMock()
    sp.current_user_playlists.return_value = {
        "items": [{"name": "Target", "id": "id1"}],
        "total": 1,
    }
    mock_spotify.return_value = sp
    result = spotify.find_playlist_by_name("Target")
    assert result["id"] == "id1"


@patch("kaiano_common_utils.spotify.get_spotify_client_from_refresh")
def test_find_playlist_by_name_not_found(mock_spotify):
    sp = MagicMock()
    sp.current_user_playlists.return_value = {
        "items": [{"name": "Other", "id": "id"}],
        "total": 1,
    }
    mock_spotify.return_value = sp
    result = spotify.find_playlist_by_name("Missing")
    assert result is None


@patch(
    "kaiano_common_utils.spotify.get_spotify_client_from_refresh",
    side_effect=Exception("fail"),
)
def test_find_playlist_by_name_exception(mock_spotify):
    result = spotify.find_playlist_by_name("Any")
    assert result is None


# ---------------------------------------------------------------------------
# get_playlist_tracks
# ---------------------------------------------------------------------------


@patch("kaiano_common_utils.spotify.get_spotify_client")
def test_get_playlist_tracks_success(mock_client):
    sp = MagicMock()
    sp.playlist_items.side_effect = [
        {
            "items": [{"track": {"uri": "u1"}}, {"track": {"uri": "u2"}}],
            "total": 2,
            "next": None,
        },
    ]
    mock_client.return_value = sp
    result = spotify.get_playlist_tracks("playlist123")
    assert result == ["u1", "u2"]


@patch("kaiano_common_utils.spotify.get_spotify_client")
def test_get_playlist_tracks_missing_fields(mock_client):
    sp = MagicMock()
    sp.playlist_items.return_value = {"foo": "bar"}
    mock_client.return_value = sp
    result = spotify.get_playlist_tracks("pid")
    assert result == []


@patch("kaiano_common_utils.spotify.get_spotify_client")
def test_get_playlist_tracks_non_dict_response(mock_client):
    sp = MagicMock()
    sp.playlist_items.return_value = ["bad"]
    mock_client.return_value = sp
    result = spotify.get_playlist_tracks("pid")
    assert result == []


@patch("kaiano_common_utils.spotify.get_spotify_client", side_effect=Exception("fail"))
def test_get_playlist_tracks_client_init_fail(mock_client):
    result = spotify.get_playlist_tracks("pid")
    assert result == []


def test_get_playlist_tracks_no_id():
    assert spotify.get_playlist_tracks("") == []
