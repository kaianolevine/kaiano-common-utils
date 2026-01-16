from __future__ import annotations

from .identify import IdentifyAudio
from .pipeline import Pipeline
from .rename import RenameFacade


class AudioToolbox:
    """Single public entry point for local audio identification, tagging, and renaming."""

    def __init__(self, ia: IdentifyAudio):
        self.identify = ia.identify
        self.metadata = ia.metadata
        self.tags = ia.tags
        self.rename = RenameFacade()
        self.pipeline = Pipeline(ia, self.rename)

    @classmethod
    def from_env(cls, *, acoustid_api_key: str, **kwargs) -> "AudioToolbox":
        ia = IdentifyAudio.from_env(acoustid_api_key=acoustid_api_key, **kwargs)
        return cls(ia)
