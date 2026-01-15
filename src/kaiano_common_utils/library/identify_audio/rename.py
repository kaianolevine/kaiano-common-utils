from __future__ import annotations

import os
import re

from kaiano_common_utils.api.music_tag.retagger_types import TrackMetadata


class RenameFacade:
    """Responsible for generating safe filenames and applying renames.

    The goal is to keep all renaming rules consistent across repos.
    """

    def safe_component(self, value: str | None) -> str:
        if not value:
            return ""
        s = str(value)
        # Replace filesystem-hostile characters and collapse whitespace.
        s = re.sub(r"[\\/:*?\"<>|]", "", s)
        s = s.replace("\n", " ").replace("\r", " ").strip()
        s = re.sub(r"\s+", " ", s)
        return s

    def build_name(self, updates: TrackMetadata, *, ext: str, template: str) -> str:
        title = self.safe_component(updates.title)
        artist = self.safe_component(updates.artist)
        album = self.safe_component(updates.album)
        year = self.safe_component(updates.year)

        # Available template keys: title, artist, album, year
        base = template.format(title=title, artist=artist, album=album, year=year)
        base = self.safe_component(base)
        if not base:
            base = "Unknown"
        return f"{base}{ext}"

    def apply(self, path: str, updates: TrackMetadata, *, template: str) -> str:
        folder = os.path.dirname(path)
        _base, ext = os.path.splitext(os.path.basename(path))
        new_name = self.build_name(updates, ext=ext, template=template)
        new_path = os.path.join(folder, new_name)
        if new_path == path:
            return path
        os.rename(path, new_path)
        return new_path
