from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Optional

import kaiano.helpers as helpers


@dataclass
class RenameProposal:
    src_path: str
    dest_path: str
    dest_name: str


class RenameFacade:
    """Local-only filename proposal + rename application."""

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

        title_part = helpers.safe_filename_component(title)
        artist_part = helpers.safe_filename_component(artist)

        if title_part and artist_part:
            name = template.format(title=title_part, artist=artist_part) + ext
        elif fallback_to_original:
            name = original_name
        else:
            name = original_name

        dest_path = os.path.join(base_dir, name)
        return RenameProposal(src_path=path, dest_path=dest_path, dest_name=name)

    def apply(self, path: str, update, *, template: str = "{title}_{artist}") -> str:
        """Rename a local file based on metadata.

        This is the calling convention used by the identify_audio pipeline.
        `update` is expected to have `.title` and `.artist` attributes.
        """

        proposal = self.propose(
            path,
            title=getattr(update, "title", None),
            artist=getattr(update, "artist", None),
            template=template,
        )

        if proposal.dest_path != proposal.src_path:
            os.rename(proposal.src_path, proposal.dest_path)
            return proposal.dest_path

        return proposal.src_path
