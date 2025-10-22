import time

import spotipy
from spotipy import Spotify
from spotipy.exceptions import SpotifyException
from spotipy.oauth2 import CacheHandler, SpotifyOAuth

from kaiano_common_utils import config
from kaiano_common_utils import logger as log

log = log.get_logger()

_spotify_client: Spotify | None = None


class NoopCacheHandler(CacheHandler):
    def get_cached_token(self):
        return None

    def save_token_to_cache(self, token_info):
        pass


def get_spotify_client() -> Spotify:
    """Return Spotify client, preferring refresh-token flow in CI."""
    global _spotify_client
    if _spotify_client is not None:
        return _spotify_client
    if config.SPOTIFY_REFRESH_TOKEN:
        log.debug("🔄 Using refresh-token authentication.")
        _spotify_client = get_spotify_client_from_refresh()
    else:
        log.debug("⚙️ Using OAuth (local interactive) authentication.")
        _spotify_client = spotipy.Spotify(
            auth_manager=SpotifyOAuth(
                client_id=config.SPOTIPY_CLIENT_ID,
                client_secret=config.SPOTIPY_CLIENT_SECRET,
                redirect_uri=config.SPOTIPY_REDIRECT_URI,
                scope="playlist-modify-public playlist-modify-private",
                cache_path=".cache-ci",
                open_browser=False,
            )
        )
    return _spotify_client


def get_spotify_client_from_refresh() -> Spotify:
    log.debug("🔐 Called with no parameters.")
    log.debug("🔐 Loading Spotify credentials from environment variables...")

    client_id = config.SPOTIPY_CLIENT_ID
    client_secret = config.SPOTIPY_CLIENT_SECRET
    redirect_uri = config.SPOTIPY_REDIRECT_URI
    refresh_token = config.SPOTIPY_REFRESH_TOKEN

    log.debug(
        f"Loaded env vars: "
        f"client_id={'set' if client_id else 'unset'}, "
        f"client_secret={'set' if client_secret else 'unset'}, "
        f"redirect_uri={'set' if redirect_uri else 'unset'}, "
        f"refresh_token={'set' if refresh_token else 'unset'}"
    )

    if not all([client_id, client_secret, redirect_uri, refresh_token]):
        log.critical("Missing one or more required Spotify credentials.")
        raise ValueError("Missing one or more required Spotify credentials.")

    log.info("✅ All Spotify environment variables found. Initializing client...")

    auth_manager = SpotifyOAuth(
        client_id=client_id,
        client_secret=client_secret,
        redirect_uri=redirect_uri,
        scope="playlist-modify-public playlist-modify-private",
        cache_handler=NoopCacheHandler(),
    )

    try:
        log.info("Refreshing Spotify access token...")
        token_info = auth_manager.refresh_access_token(refresh_token)
        log.info("Obtained new Spotify access token.")
        return Spotify(auth=token_info["access_token"])
    except Exception as e:
        log.error(f"Failed to refresh token: {e}")
        raise


def search_track(artist: str, title: str) -> str | None:
    log.debug(f"Called with artist='{artist}', title='{title}'")
    sp = get_spotify_client()
    query = f"artist:{artist} track:{title}"
    log.debug(f"Constructed query: {query}")

    max_retries = 3
    for attempt in range(max_retries):
        try:
            results = sp.search(q=query, type="track", limit=1)
            tracks = results.get("tracks", {}).get("items", [])
            log.debug(f"Number of tracks found: {len(tracks)}")
            if tracks:
                log.info(f"Found track: {artist} - {title} (URI: {tracks[0]['uri']})")
                return tracks[0]["uri"]
            else:
                # No tracks found, fallback to relaxed query with only title
                if attempt == 0:
                    log.debug(
                        "No track found with full query; retrying with relaxed query."
                    )
                    query = f"track:{title}"
                    continue
                else:
                    log.warning(
                        f"No track found for the given artist/title: {artist} - {title}"
                    )
                    return None
        except SpotifyException as e:
            if e.http_status == 429:
                retry_after = int(e.headers.get("Retry-After", 2))
                log.warning(
                    f"Rate limited by Spotify API. Sleeping for {retry_after} seconds."
                )
                time.sleep(retry_after)
                continue
            elif e.http_status == 403:
                log.warning(
                    "Forbidden error (403) from Spotify API. Check permissions."
                )
                return None
            elif e.http_status >= 500:
                log.error(f"Server error {e.http_status} from Spotify API: {e}")
                return None
            else:
                log.error(f"SpotifyException encountered: {e}")
                return None
    log.warning("Exhausted retries without success.")
    return None


def add_tracks_to_playlist(uris: list[str]) -> None:
    log.debug(f"Called with uris={uris}")
    if not config.SPOTIFY_PLAYLIST_ID:
        log.critical("Missing SPOTIFY_PLAYLIST_ID environment variable.")
        raise EnvironmentError("Missing SPOTIFY_PLAYLIST_ID environment variable.")
    if not uris:
        log.warning("No tracks to add.")
        print("No tracks to add.")
        return

    unique_uris = list(dict.fromkeys(uris))
    duplicates_removed = len(uris) - len(unique_uris)
    if duplicates_removed > 0:
        log.info(f"Removed {duplicates_removed} duplicate track(s).")

    log.info(
        f"Adding {len(unique_uris)} tracks to playlist ID {config.SPOTIFY_PLAYLIST_ID}"
    )
    sp = get_spotify_client()
    sp.playlist_add_items(config.SPOTIFY_PLAYLIST_ID, unique_uris)
    log.info(
        f"Added {len(unique_uris)} track(s) to playlist {config.SPOTIFY_PLAYLIST_ID}."
    )
    print(f"✅ Added {len(unique_uris)} track(s) to playlist.")


def trim_playlist_to_limit(limit: int = 200) -> None:
    log.debug(f"Called with limit={limit}")
    if not config.SPOTIFY_PLAYLIST_ID:
        log.critical("Missing SPOTIFY_PLAYLIST_ID environment variable.")
        raise EnvironmentError("Missing SPOTIFY_PLAYLIST_ID environment variable.")
    sp = get_spotify_client()
    current = sp.playlist_items(
        config.SPOTIFY_PLAYLIST_ID,
        fields="items.track.uri,total",
        additional_types=["track"],
    )
    total = current["total"]
    log.info(f"Playlist size: {total}, limit: {limit}")
    if total <= limit:
        log.info(f"Playlist is within limit ({total}/{limit}); no tracks removed.")
        return
    num_to_remove = total - limit
    uris_to_remove = [item["track"]["uri"] for item in current["items"][:num_to_remove]]
    log.info(
        f"Removing {num_to_remove} tracks from playlist ID {config.SPOTIFY_PLAYLIST_ID}."
    )
    sp.playlist_remove_all_occurrences_of_items(
        config.SPOTIFY_PLAYLIST_ID, uris_to_remove
    )
    log.info(f"Removed {len(uris_to_remove)} old tracks to stay under {limit}.")
    print(f"🗑️ Removed {len(uris_to_remove)} old tracks to stay under {limit}.")


def create_playlist(
    name: str,
    description: str = "Generated automatically by Deejay Marvel Automation Tools",
) -> str | None:
    """
    Create a new Spotify playlist with the given name.
    Returns the playlist ID on success, or None on failure.
    """
    sp = get_spotify_client()
    try:
        user_id = sp.current_user()["id"]
        playlist = sp.user_playlist_create(
            user=user_id, name=name, public=False, description=description
        )
        playlist_id = playlist["id"]
        log.info(f"✅ Created Spotify playlist '{name}' (ID: {playlist_id})")
        return playlist_id
    except Exception as e:
        log.error(f"❌ Failed to create playlist '{name}': {e}")
        return None


def add_tracks_to_specific_playlist(playlist_id: str, track_uris: list[str]) -> None:
    """
    Add tracks to a specific Spotify playlist.
    """
    if not playlist_id or not track_uris:
        log.debug("⚠️ No playlist_id or track URIs provided; skipping track addition.")
        return

    unique_uris = list(dict.fromkeys(track_uris))
    duplicates_removed = len(track_uris) - len(unique_uris)
    if duplicates_removed > 0:
        log.info(f"Removed {duplicates_removed} duplicate track(s).")
    log.debug(f"Adding {len(unique_uris)} tracks to playlist {playlist_id}")

    sp = get_spotify_client()
    try:
        sp.playlist_add_items(playlist_id, unique_uris)
        log.info(f"🎶 Added {len(unique_uris)} tracks to playlist {playlist_id}")
    except Exception as e:
        log.error(f"❌ Failed to add tracks to playlist {playlist_id}: {e}")


def find_playlist_by_name(name: str):
    """Return (playlist_id, playlist_data) if a playlist exists with the given name."""
    sp = get_spotify_client_from_refresh()
    results = sp.current_user_playlists(limit=50)
    for playlist in results["items"]:
        if playlist["name"] == name:
            return playlist["id"], playlist
    return None, None


def get_playlist_tracks(playlist_id: str) -> list[str]:
    """
    Retrieve all track URIs from a specific Spotify playlist.
    Returns a list of track URIs.
    """
    log.debug(f"[get_playlist_tracks] Fetching tracks for playlist_id={playlist_id}")
    if not playlist_id:
        log.warning(
            "[get_playlist_tracks] No playlist_id provided; returning empty list."
        )
        return []

    sp = get_spotify_client()
    tracks = []
    offset = 0

    try:
        while True:
            response = sp.playlist_items(
                playlist_id,
                fields="items.track.uri,total,next",
                additional_types=["track"],
                limit=100,
                offset=offset,
            )
            items = response.get("items", [])
            uris = [item["track"]["uri"] for item in items if item.get("track")]
            tracks.extend(uris)
            log.debug(
                f"[get_playlist_tracks] Retrieved {len(uris)} tracks (offset={offset})"
            )

            if not response.get("next"):
                break
            offset += 100

        log.info(f"[get_playlist_tracks] Total tracks retrieved: {len(tracks)}")
        return tracks

    except Exception as e:
        log.error(
            f"[get_playlist_tracks] ❌ Failed to retrieve playlist tracks for {playlist_id}: {e}"
        )
        return []
