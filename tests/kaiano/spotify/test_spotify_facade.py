import importlib
import sys
import types


def _install(name: str, module: types.ModuleType) -> None:
    sys.modules[name] = module


def _ensure_stubbed_config():
    cfg = sys.modules.get("kaiano.config")
    if cfg is None:
        cfg = types.ModuleType("kaiano.config")
        _install("kaiano.config", cfg)
    # minimal config surface used by spotify.py
    setattr(cfg, "SPOTIPY_CLIENT_ID", "cid")
    setattr(cfg, "SPOTIPY_CLIENT_SECRET", "secret")
    setattr(cfg, "SPOTIPY_REFRESH_TOKEN", "refresh")
    setattr(cfg, "SPOTIPY_REDIRECT_URI", "http://127.0.0.1:8888/callback")


def test_spotify_retry_helpers_and_client_from_refresh(monkeypatch):
    _ensure_stubbed_config()

    # requests stub
    requests = types.ModuleType("requests")
    exc_mod = types.SimpleNamespace(
        RequestException=Exception, ReadTimeout=TimeoutError
    )
    requests.exceptions = exc_mod
    _install("requests", requests)

    # spotipy stub
    spotipy = types.ModuleType("spotipy")
    spotipy_exceptions = types.ModuleType("spotipy.exceptions")
    spotipy_oauth2 = types.ModuleType("spotipy.oauth2")

    class SpotifyException(Exception):
        def __init__(self, http_status=None, headers=None):
            super().__init__("spotify")
            self.http_status = http_status
            self.headers = headers or {}

    class SpotifyOauthError(Exception):
        pass

    class CacheHandler:
        pass

    class SpotifyOAuth:
        def __init__(self, **_kwargs):
            self.calls = 0

        def refresh_access_token(self, refresh_token):
            self.calls += 1
            return {"access_token": f"token-{self.calls}"}

    class Spotify:
        def __init__(self, auth=None, auth_manager=None):
            self.auth = auth
            self.auth_manager = auth_manager
            self._search_calls = 0

        def search(self, q, type, limit):
            self._search_calls += 1
            return {
                "tracks": {
                    "items": [{"uri": "uri:1", "name": "T", "artists": [{"name": "A"}]}]
                }
            }

        def current_user(self):
            return {"id": "me"}

        def user_playlist_create(self, user, name, public, description):
            return {"id": "pl"}

        def playlist_items(self, playlist_id, offset=0, fields=None, **_kwargs):
            # pagination fixture: first page has one existing track, then ends
            if offset == 0:
                return {
                    "items": [{"track": {"uri": "uri:existing"}}],
                    "total": 1,
                    "next": None,
                }
            return {"items": [], "total": 0, "next": None}

        def playlist_add_items(self, playlist_id, items):
            return {"snapshot_id": "s"}

        def current_user_playlists(self, limit=50):
            return {"items": [{"name": "MyPlaylist", "id": "pl-1"}]}

        def playlist_remove_all_occurrences_of_items(self, playlist_id, items):
            self._removed = list(items)
            return {"snapshot_id": "r"}

    spotipy.Spotify = Spotify  # type: ignore[attr-defined]
    spotipy.exceptions = spotipy_exceptions  # type: ignore[attr-defined]
    spotipy.oauth2 = spotipy_oauth2  # type: ignore[attr-defined]
    _install("spotipy", spotipy)

    spotipy_exceptions.SpotifyException = SpotifyException  # type: ignore[attr-defined]
    spotipy_exceptions.SpotifyOauthError = SpotifyOauthError  # type: ignore[attr-defined]
    _install("spotipy.exceptions", spotipy_exceptions)

    spotipy_oauth2.CacheHandler = CacheHandler  # type: ignore[attr-defined]
    spotipy_oauth2.SpotifyOAuth = SpotifyOAuth  # type: ignore[attr-defined]
    _install("spotipy.oauth2", spotipy_oauth2)

    # Import module under test (reload to pick up stubs)
    mod = importlib.reload(importlib.import_module("kaiano.spotify.spotify"))

    # avoid real sleeps
    monkeypatch.setattr(mod.time, "sleep", lambda *_a, **_k: None)

    api = mod.SpotifyAPI.from_env()
    client = api.client
    assert isinstance(client, Spotify)
    assert client.auth.startswith("token-")

    # basic facade methods exercise call path
    assert api.search_track("A", "T") == "uri:1"
    assert api.create_playlist("Name", "Desc") == "pl"

    # add_tracks_to_specific_playlist: filters existing unless allowDuplicates=True
    api.add_tracks_to_specific_playlist(
        "pl", ["uri:existing", "uri:new"], allowDuplicates=False
    )

    # get_playlist_tracks: returns URIs
    assert api.get_playlist_tracks("pl") == ["uri:existing"]

    # find_playlist_by_name (match)
    assert api.find_playlist_by_name("MyPlaylist")["id"] == "pl-1"

    # retry helpers
    assert (
        mod._is_retryable_spotify_exception(SpotifyException(http_status=429)) is True
    )
    assert (
        mod._is_retryable_spotify_exception(SpotifyException(http_status=503)) is True
    )
    assert (
        mod._is_retryable_spotify_exception(SpotifyException(http_status=400)) is False
    )


def test_spotify_call_with_retry_respects_rate_limit(monkeypatch):
    _ensure_stubbed_config()

    # Ensure our third-party stubs exist (tests can run in any order).
    if "spotipy" not in sys.modules:
        # Minimal repeat of the stubs from the first test.
        requests = types.ModuleType("requests")
        exc_mod = types.SimpleNamespace(
            RequestException=Exception, ReadTimeout=TimeoutError
        )
        requests.exceptions = exc_mod
        _install("requests", requests)

        spotipy = types.ModuleType("spotipy")
        spotipy_exceptions = types.ModuleType("spotipy.exceptions")
        spotipy_oauth2 = types.ModuleType("spotipy.oauth2")

        class SpotifyException(Exception):
            def __init__(self, http_status=None, headers=None):
                super().__init__("spotify")
                self.http_status = http_status
                self.headers = headers or {}

        class SpotifyOauthError(Exception):
            pass

        class CacheHandler:
            pass

        class SpotifyOAuth:
            def __init__(self, **_kwargs):
                pass

            def refresh_access_token(self, _refresh_token):
                return {"access_token": "token"}

        class Spotify:
            def __init__(self, auth=None, auth_manager=None):
                self.auth = auth
                self.auth_manager = auth_manager

        spotipy.Spotify = Spotify  # type: ignore[attr-defined]
        spotipy.exceptions = spotipy_exceptions  # type: ignore[attr-defined]
        spotipy.oauth2 = spotipy_oauth2  # type: ignore[attr-defined]
        _install("spotipy", spotipy)

        spotipy_exceptions.SpotifyException = SpotifyException  # type: ignore[attr-defined]
        spotipy_exceptions.SpotifyOauthError = SpotifyOauthError  # type: ignore[attr-defined]
        _install("spotipy.exceptions", spotipy_exceptions)

        spotipy_oauth2.CacheHandler = CacheHandler  # type: ignore[attr-defined]
        spotipy_oauth2.SpotifyOAuth = SpotifyOAuth  # type: ignore[attr-defined]
        _install("spotipy.oauth2", spotipy_oauth2)

    mod = importlib.reload(importlib.import_module("kaiano.spotify.spotify"))

    sleeps = []
    monkeypatch.setattr(mod.time, "sleep", lambda s: sleeps.append(s))

    class E(mod.SpotifyException):
        pass

    calls = {"n": 0}

    def fn():
        calls["n"] += 1
        if calls["n"] == 1:
            raise E(http_status=429, headers={"Retry-After": "3"})
        return "ok"

    out = mod.SpotifyAPI()._call_with_retry(fn, context="testing")
    assert out == "ok"
    # slept for retry-after
    assert sleeps and sleeps[0] >= 1
