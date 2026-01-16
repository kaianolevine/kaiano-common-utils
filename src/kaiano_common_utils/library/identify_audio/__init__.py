"""Unified audio identification + tagging + renaming interface."""

from .api import AudioToolbox, IdentifyAudio
from .policies import IdentificationPolicy

# Low-level interfaces (advanced / escape-hatch use only)
from .retagger_api import AcoustIdIdentifier, MusicBrainzRecordingProvider
from .retagger_music_tag import MusicTagIO
from .retagger_types import TagSnapshot, TrackId, TrackMetadata

__all__ = [
    "AudioToolbox",
    "IdentifyAudio",
    "IdentificationPolicy",
    "TagSnapshot",
    "TrackId",
    "TrackMetadata",
    "AcoustIdIdentifier",
    "MusicBrainzRecordingProvider",
    "MusicTagIO",
]
