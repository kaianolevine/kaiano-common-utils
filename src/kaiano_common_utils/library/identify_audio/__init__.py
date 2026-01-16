"""Unified local audio identification, tagging, and renaming.

Public API:
- AudioToolbox: single entry point (recommended)
- IdentifyAudio: low-level orchestration (advanced)

This module is local-filesystem only and has no Drive dependency.
"""

# ---- Advanced / low-level access (opt-in) ----
# ---- Primary public entry point (recommended) ----
from .api import AudioToolbox, IdentifyAudio
from .policies import IdentificationPolicy

# ---- Escape hatches (advanced users only) ----
from .retagger_api import AcoustIdIdentifier, MusicBrainzRecordingProvider
from .retagger_music_tag import MusicTagIO

# ---- Data models (stable, library-agnostic) ----
from .retagger_types import TagSnapshot, TrackId, TrackMetadata

__all__ = [
    # Primary
    "AudioToolbox",
    # Advanced orchestration
    "IdentifyAudio",
    "IdentificationPolicy",
    # Data models
    "TagSnapshot",
    "TrackId",
    "TrackMetadata",
    # Escape hatches
    "AcoustIdIdentifier",
    "MusicBrainzRecordingProvider",
    "MusicTagIO",
]
