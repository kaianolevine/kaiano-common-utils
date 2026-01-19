from __future__ import annotations

from typing import Any, Dict, Mapping, Optional

from .io.music_tag_io import MusicTagIO
from .models import TagSnapshot


class Mp3Tagger:
    """Read/write tags on local MP3 files via `music-tag`.

    This module is fully self-contained (no dependency on identify/name).

    Contract:
    - read() returns TagSnapshot (tags are strings)
    - write() accepts a metadata mapping (dict-like). Keys are flexible but common ones are:
      title, artist, album, album_artist, year, genre, comment, isrc, track_number,
      disc_number, bpm
    """

    def __init__(self, io: Optional[MusicTagIO] = None):
        self._io = io or MusicTagIO()

    def read(self, path: str) -> TagSnapshot:
        return self._io.read(path)

    def write(
        self,
        path: str,
        metadata: Mapping[str, Any],
        *,
        ensure_virtualdj_compat: bool = False,
    ) -> None:
        self._io.write(path, metadata, ensure_virtualdj_compat=ensure_virtualdj_compat)

    def dump(self, path: str) -> Dict[str, str]:
        return self._io.dump_tags(path)
