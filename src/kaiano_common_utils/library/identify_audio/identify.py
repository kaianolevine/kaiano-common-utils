from __future__ import annotations

from typing import List

from kaiano_common_utils.api.music_tag.retagger_api import AcoustIdIdentifier
from kaiano_common_utils.api.music_tag.retagger_types import TagSnapshot, TrackId


class IdentifierFacade:
    """Thin facade over AcoustIdIdentifier."""

    def __init__(self, identifier: AcoustIdIdentifier):
        self._identifier = identifier

    def candidates(self, path: str, existing: TagSnapshot) -> List[TrackId]:
        return list(self._identifier.identify(path, existing))
