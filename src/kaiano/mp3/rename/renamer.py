from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Optional

from .io.rename_fs import RenameFacade, RenameProposal


@dataclass(frozen=True)
class RenameResult:
    src_path: str
    dest_path: str
    dest_name: str
    renamed: bool


class Mp3Renamer:
    """Rename local MP3 files based on metadata.

    This module is fully self-contained (no dependency on identify/tag).

    Metadata contract:
    - accepts a mapping (dict-like) with optional keys: title, artist
    """

    def __init__(self, facade: Optional[RenameFacade] = None):
        self._rename = facade or RenameFacade()

    def propose(
        self,
        path: str,
        *,
        metadata: Optional[Mapping[str, Any]] = None,
        title: Optional[str] = None,
        artist: Optional[str] = None,
        template: str = "{title}_{artist}",
        fallback_to_original: bool = True,
    ) -> RenameProposal:
        if metadata is not None:
            title = title or metadata.get("title")  # type: ignore[arg-type]
            artist = artist or metadata.get("artist")  # type: ignore[arg-type]

        return self._rename.propose(
            path,
            title=title,
            artist=artist,
            template=template,
            fallback_to_original=fallback_to_original,
        )

    def apply(
        self,
        path: str,
        *,
        metadata: Optional[Mapping[str, Any]] = None,
        title: Optional[str] = None,
        artist: Optional[str] = None,
        template: str = "{title}_{artist}",
    ) -> RenameResult:
        proposal = self.propose(
            path,
            metadata=metadata,
            title=title,
            artist=artist,
            template=template,
        )
        dest = self._rename.apply(
            path,
            metadata=metadata,
            title=title,
            artist=artist,
            template=template,
        )

        return RenameResult(
            src_path=proposal.src_path,
            dest_path=dest,
            dest_name=proposal.dest_name,
            renamed=dest != proposal.src_path,
        )
