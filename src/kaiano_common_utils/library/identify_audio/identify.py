from __future__ import annotations

from typing import List, Optional

from .metadata import MetadataFacade
from .policies import IdentificationPolicy
from .retagger_api import AcoustIdIdentifier, MusicBrainzRecordingProvider
from .retagger_music_tag import MusicTagIO
from .retagger_types import TagSnapshot, TrackId
from .tags import TagFacade


class IdentifierFacade:
    """Thin facade over AcoustIdIdentifier."""

    def __init__(self, identifier: AcoustIdIdentifier):
        self._identifier = identifier

    def candidates(self, path: str, existing: TagSnapshot) -> List[TrackId]:
        return list(self._identifier.identify(path, existing))


class IdentifyAudio:
    """Local-only orchestrator exposing identify / metadata / tags facades.

    This module intentionally has *no* Drive dependency. Callers should pass local file
    paths. Drive middleware (if any) is responsible for downloading/uploading.
    """

    def __init__(
        self,
        identifier: AcoustIdIdentifier,
        provider: MusicBrainzRecordingProvider,
        tag_io: MusicTagIO,
    ):
        self.identify = IdentifierFacade(identifier)
        self.metadata = MetadataFacade(provider)
        self.tags = TagFacade(tag_io)

    @classmethod
    def from_env(
        cls,
        *,
        acoustid_api_key: str,
        id_policy: Optional[IdentificationPolicy] = None,
        app_name: str = "identify-audio",
        app_version: str = "0.1.0",
        contact: str = "",
        throttle_s: float = 1.0,
    ) -> "IdentifyAudio":
        """Construct IdentifyAudio using the same parameters used across repos.

        `id_policy` controls min_confidence/max_candidates for AcoustID.
        MusicBrainz throttling is handled by the underlying provider.
        """

        id_policy = id_policy or IdentificationPolicy()

        identifier = AcoustIdIdentifier(
            api_key=acoustid_api_key,
            min_confidence=id_policy.min_confidence,
            max_candidates=id_policy.max_candidates,
        )

        # MusicBrainz provider constructor parameters may evolve; keep this call explicit.
        provider = MusicBrainzRecordingProvider(
            app_name=app_name,
            app_version=app_version,
            contact=contact,
            throttle_s=throttle_s,
        )

        tag_io = MusicTagIO()
        return cls(identifier=identifier, provider=provider, tag_io=tag_io)
