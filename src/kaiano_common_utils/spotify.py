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
    if config.SPOTIPY_REFRESH_TOKEN:
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
                found_artist = (
                    tracks[0]["artists"][0]["name"]
                    if tracks[0].get("artists")
                    else "Unknown Artist"
                )
                found_title = tracks[0].get("name", "Unknown Title")
                log.critical(
                    f"Original track: {artist} - {title} (URI: {tracks[0]['uri']})"
                )
                log.critical(
                    f"Found track: {found_artist} - {found_title} (URI: {tracks[0]['uri']})"
                )
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
            user=user_id, name=name, public=True, description=description
        )
        playlist_id = playlist["id"]
        log.info(f"✅ Created Spotify playlist '{name}' (ID: {playlist_id})")
        return playlist_id
    except Exception as e:
        log.error(f"❌ Failed to create playlist '{name}': {e}")
        return None


def add_tracks_to_playlist(uris: list[str], allowDuplicates: bool = False) -> None:
    add_tracks_to_specific_playlist(
        config.SPOTIFY_PLAYLIST_ID, uris, allowDuplicates=allowDuplicates
    )


def add_tracks_to_specific_playlist(
    playlist_id: str, uris: list[str], allowDuplicates: bool = False
) -> None:
    log.debug(f"Called with uris={uris} and allowDuplicates={allowDuplicates}")
    if not playlist_id:
        log.critical("Missing playlist_id parameter.")
        raise ValueError("Missing playlist_id parameter.")
    if not uris:
        log.warning("No tracks to add.")
        return

    # Remove duplicates in the provided list, preserving order
    unique_uris = list(dict.fromkeys(uris))
    duplicates_removed = len(uris) - len(unique_uris)
    if duplicates_removed > 0:
        log.info(f"Removed {duplicates_removed} duplicate track(s) from input list.")

    sp = get_spotify_client()

    if allowDuplicates:
        # Add all unique URIs without checking existing playlist content
        uris_to_add = unique_uris
        log.info(
            f"Adding {len(uris_to_add)} tracks to playlist ID {playlist_id} allowing duplicates."
        )
    else:
        # Fetch all current track URIs from the playlist, paginated
        existing_uris = set()
        offset = 0
        while True:
            resp = sp.playlist_items(
                playlist_id,
                fields="items.track.uri,total,next",
                additional_types=["track"],
                limit=100,
                offset=offset,
            )
            items = resp.get("items", [])
            for item in items:
                track = item.get("track")
                if track and "uri" in track:
                    existing_uris.add(track["uri"])
            if not resp.get("next"):
                break
            offset += 100

        # Filter out URIs that are already in the playlist
        uris_to_add = [uri for uri in unique_uris if uri not in existing_uris]
        skipped = len(unique_uris) - len(uris_to_add)
        if skipped > 0:
            log.info(f"Skipped {skipped} track(s) already present in the playlist.")

        log.info(
            f"Adding {len(uris_to_add)} tracks to playlist ID {playlist_id} without allowing duplicates."
        )

    if not uris_to_add:
        log.info(
            "No new tracks to add after filtering existing tracks."
            if not allowDuplicates
            else "No tracks to add."
        )
        return

    sp.playlist_add_items(playlist_id, uris_to_add)
    log.info(f"Added {len(uris_to_add)} track(s) to playlist {playlist_id}.")


def find_playlist_by_name(name: str):
    """Return a dict with playlist ID and metadata if a playlist exists with the given name."""
    log.debug(f"Searching for playlist: {name}")

    try:
        sp = get_spotify_client_from_refresh()
        log.debug("Spotify client initialized.")
        results = sp.current_user_playlists(limit=50)

        total = results.get("total", "unknown")
        log.debug(
            f"Retrieved {len(results.get('items', []))} playlists (total={total})"
        )

        # Log each playlist name to confirm what Spotify returned
        for playlist in results.get("items", []):
            log.debug(
                f"Found playlist: {playlist.get('name')} (ID={playlist.get('id')})"
            )

            if playlist.get("name") == name:
                log.info(
                    f"✅ Match found: {playlist.get('name')} (ID={playlist.get('id')})"
                )
                return {"id": playlist["id"], "data": playlist}

        log.warning(f"⚠️ No playlist found with name '{name}'")
        return None

    except Exception as e:
        log.error(
            f"❌ Exception while searching for playlist '{name}': {e}", exc_info=True
        )
        return None


def get_playlist_tracks(playlist_id: str) -> list[str]:
    """
    Retrieve all track URIs from a specific Spotify playlist.
    Returns a list of track URIs.
    """
    log.debug(f"Fetching tracks for playlist_id={playlist_id}")
    if not playlist_id:
        log.warning("No playlist_id provided; returning empty list.")
        return []

    try:
        sp = get_spotify_client()
        log.debug(f"Spotify client initialized for playlist_id={playlist_id}")
    except Exception as e:
        log.error(
            f"Failed to initialize Spotify client for playlist_id={playlist_id}: {e}",
            exc_info=True,
        )
        return []

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
            if not isinstance(response, dict):
                log.error(
                    f"Unexpected response type for playlist_id={playlist_id}: {type(response)}"
                )
                break

            items = response.get("items")
            total = response.get("total")
            next_page = response.get("next")

            if items is None or total is None:
                log.error(
                    f"Missing 'items' or 'total' in response for playlist_id={playlist_id}"
                )
                break

            log.debug(
                f"Retrieved batch of {len(items)} items at offset {offset} for playlist_id={playlist_id}, total expected: {total}"
            )

            uris = []
            for item in items:
                track = item.get("track")
                if track and "uri" in track:
                    uris.append(track["uri"])
                else:
                    log.debug(
                        f"Skipping item without valid track or URI at offset {offset} for playlist_id={playlist_id}"
                    )

            tracks.extend(uris)
            log.debug(
                f"Added {len(uris)} track URIs from current batch for playlist_id={playlist_id}"
            )

            if not next_page:
                log.debug(f"No more pages to fetch for playlist_id={playlist_id}")
                break

            offset += 100

        log.info(f"Total tracks retrieved: {len(tracks)} for playlist_id={playlist_id}")
        return tracks

    except Exception as e:
        log.error(
            f"❌ Failed to retrieve playlist tracks for {playlist_id}: {e}",
            exc_info=True,
        )
        return []
