from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class DriveFile:
    id: str
    name: str
    mime_type: Optional[str] = None
    modified_time: Optional[str] = None
