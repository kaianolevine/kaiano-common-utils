from __future__ import annotations

from typing import Optional

from kaiano_common_utils.api.music_tag.retagger_api import MusicBrainzRecordingProvider
from kaiano_common_utils.api.music_tag.retagger_types import TrackId, TrackMetadata


class MetadataFacade:
    """Thin facade over MusicBrainzRecordingProvider."""

    def __init__(self, provider: MusicBrainzRecordingProvider):
        self._provider = provider

    def fetch(self, track_id: TrackId) -> TrackMetadata:
        return self._provider.fetch(track_id)

    def fetch_best(self, candidates: list[TrackId]) -> Optional[TrackMetadata]:
        if not candidates:
            return None
        chosen = max(candidates, key=lambda c: c.confidence)
        return self.fetch(chosen)
