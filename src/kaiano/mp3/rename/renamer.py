from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Mapping, Optional

from .io.rename_fs import RenameFacade


@dataclass(frozen=True)
class RenameResult:
    src_path: str
    dest_path: str
    dest_name: str
    renamed: bool


class Mp3Renamer:
    """Rename local MP3 files based on metadata (prefer the single-call rename() API).

    This module is fully self-contained (no dependency on identify/tag).

    Metadata contract:
    - accepts a mapping (dict-like) with optional keys: title, artist
    """

    def __init__(self, facade: Optional[RenameFacade] = None):
        self._rename = facade or RenameFacade()

    def rename(
        self,
        path: str,
        *,
        metadata: Optional[Mapping[str, Any]] = None,
        title: Optional[str] = None,
        artist: Optional[str] = None,
        template: str = "{title}_{artist}",
        fallback_to_original: bool = True,
    ) -> RenameResult:
        """Rename a file and return the result.

        Intent (confirmed): callers should be able to provide metadata/title/artist and
        receive a single, fully-populated result without a two-step propose/apply flow.

        Notes:
        - Explicit `title`/`artist` override values from `metadata`.
        - `template` controls the output name.
        - If the destination name cannot be constructed (missing fields),
          `fallback_to_original=True` keeps the original name.
        """

        if metadata is not None:
            title = title or metadata.get("title")  # type: ignore[arg-type]
            artist = artist or metadata.get("artist")  # type: ignore[arg-type]

        proposal = self._rename.propose(
            path,
            title=title,
            artist=artist,
            template=template,
            fallback_to_original=fallback_to_original,
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

    @staticmethod
    def sanitize_string(v: Any) -> str:
        """Return a filename-safe token.

        Intent (confirmed):
        - None -> "" (treated as not provided)
        - Collapse all internal whitespace to a single underscore
        - Remove all non-alphanumeric characters except underscores
        - Strip leading/trailing underscores

        This is intentionally more aggressive than tag sanitization:
        filenames must be stable and filesystem-safe.
        """
        if v is None:
            return ""

        s = str(v).strip()
        if not s:
            return ""

        # Collapse all whitespace to single underscores
        s = re.sub(r"\s+", "_", s)

        # Remove all non-alphanumeric / underscore characters
        s = re.sub(r"[^A-Za-z0-9_]", "", s)

        # Avoid leading/trailing separators
        return s.strip("_")

    # build_routine_filename relies on sanitize_string to ensure filesystem safety
    @staticmethod
    def build_routine_filename(
        leader, follower, division, routine, descriptor, season_year
    ) -> str:
        """Return base_without_version_or_ext. Base includes season year and optional fields."""

        prefix = "_".join(
            [
                (Mp3Renamer.sanitize_string(leader)),
                (Mp3Renamer.sanitize_string(follower)),
                (Mp3Renamer.sanitize_string(division)),
            ]
        )

        tail_parts: list[str] = [Mp3Renamer.sanitize_string(season_year)]
        if routine:
            tail_parts.append(Mp3Renamer.sanitize_string(routine))
        if descriptor:
            tail_parts.append(Mp3Renamer.sanitize_string(descriptor))

        return f"{prefix}_{'_'.join(tail_parts)}"
