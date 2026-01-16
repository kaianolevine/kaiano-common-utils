"""Unified audio identification + tagging + renaming (local filesystem only).

Recommended entry point:
- AudioToolbox

Advanced:
- IdentifyAudio (lower-level orchestrator)
"""

from .api import AudioToolbox
from .identify import IdentifyAudio
from .policies import IdentificationPolicy, RenamePolicy, TagPolicy

# Low-level interfaces (advanced / escape-hatch use only)
from .retagger_api import AcoustIdIdentifier, MusicBrainzRecordingProvider
from .retagger_music_tag import MusicTagIO
from .retagger_types import TagSnapshot, TrackId, TrackMetadata

__all__ = [
    "AudioToolbox",
    "IdentifyAudio",
    "IdentificationPolicy",
    "TagPolicy",
    "RenamePolicy",
    "TagSnapshot",
    "TrackId",
    "TrackMetadata",
    "AcoustIdIdentifier",
    "MusicBrainzRecordingProvider",
    "MusicTagIO",
]
