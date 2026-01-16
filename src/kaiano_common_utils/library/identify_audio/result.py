from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from .retagger_types import TrackId, TrackMetadata


@dataclass(frozen=True)
class ProcessWarning:
    code: str
    message: str


@dataclass
class ProcessResult:
    """Result object returned by IdentifyAudio.process_file/process_bytes."""

    path_in: str
    path_out: Optional[str] = None

    identified: bool = False
    chosen: Optional[TrackId] = None
    metadata: Optional[TrackMetadata] = None

    wrote_tags: bool = False
    renamed: bool = False

    warnings: list[ProcessWarning] = field(default_factory=list)
    error: Optional[str] = None
