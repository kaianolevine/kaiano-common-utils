from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Mapping, Optional

try:
    import kaiano.helpers as helpers  # type: ignore
except Exception:  # pragma: no cover
    helpers = None


def _safe_filename_component_fallback(value: Optional[str]) -> str:
    if value is None:
        return ""
    # Keep it simple: strip, replace spaces, and drop path separators.
    s = str(value).strip().replace(" ", "_")
    s = s.replace(os.sep, "_")
    s = s.replace("/", "_").replace("\\", "_")
    bad = '<>:"|?*'
    for ch in bad:
        s = s.replace(ch, "")
    return s


def _safe_component(value: Optional[str]) -> str:
    if helpers is not None and hasattr(helpers, "safe_filename_component"):
        return helpers.safe_filename_component(value)  # type: ignore[attr-defined]
    return _safe_filename_component_fallback(value)


@dataclass
class RenameProposal:
    src_path: str
    dest_path: str
    dest_name: str


class RenameFacade:
    """Local-only filename proposal + rename application.

    This module does not depend on identify/tag types.
    """

    def propose(
        self,
        path: str,
        *,
        title: Optional[str] = None,
        artist: Optional[str] = None,
        template: str = "{title}_{artist}",
        fallback_to_original: bool = True,
    ) -> RenameProposal:
        base_dir = os.path.dirname(path)
        original_name = os.path.basename(path)
        _, ext = os.path.splitext(original_name)

        title_part = _safe_component(title)
        artist_part = _safe_component(artist)

        if title_part and artist_part:
            name = template.format(title=title_part, artist=artist_part) + ext
        elif fallback_to_original:
            name = original_name
        else:
            name = original_name

        dest_path = os.path.join(base_dir, name)
        return RenameProposal(src_path=path, dest_path=dest_path, dest_name=name)

    def apply(
        self,
        path: str,
        metadata: Mapping[str, Any] | None = None,
        *,
        title: Optional[str] = None,
        artist: Optional[str] = None,
        template: str = "{title}_{artist}",
    ) -> str:
        if metadata is not None:
            title = title or (metadata.get("title") if hasattr(metadata, "get") else None)  # type: ignore[arg-type]
            artist = artist or (metadata.get("artist") if hasattr(metadata, "get") else None)  # type: ignore[arg-type]

        proposal = self.propose(path, title=title, artist=artist, template=template)

        if proposal.dest_path != proposal.src_path:
            os.rename(proposal.src_path, proposal.dest_path)
            return proposal.dest_path

        return proposal.src_path
