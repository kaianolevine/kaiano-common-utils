from __future__ import annotations

from typing import Dict

from kaiano_common_utils.api.music_tag.retagger_music_tag import MusicTagIO
from kaiano_common_utils.api.music_tag.retagger_types import TagSnapshot, TrackMetadata


class TagFacade:
    """Facade for reading/writing tags.

    Wraps MusicTagIO (music_tag + mutagen) and provides stable methods.
    """

    def __init__(self, io: MusicTagIO | None = None):
        self._io = io or MusicTagIO()

    def read(self, path: str) -> TagSnapshot:
        return self._io.read(path)

    def write(
        self,
        path: str,
        updates: TrackMetadata,
        *,
        ensure_virtualdj_compat: bool = False,
    ) -> None:
        self._io.write(path, updates, ensure_virtualdj_compat=ensure_virtualdj_compat)

    def dump(self, path: str) -> Dict[str, str]:
        return self._io.dump_tags(path)
