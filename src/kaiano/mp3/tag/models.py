from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict


@dataclass(frozen=True)
class TagSnapshot:
    tags: Dict[str, str] = field(default_factory=dict)
    has_artwork: bool = False
