# AudioToolbox single-entry API (local filesystem only)

import os
from dataclasses import dataclass
from typing import Optional

import kaiano_common_utils.helpers as helpers
from kaiano_common_utils.library.identify_audio.api import IdentifyAudio
from kaiano_common_utils.library.identify_audio.retagger_types import (
    TrackMetadata as TagUpdate,
)


@dataclass
class RenameProposal:
    src_path: str
    dest_path: str
    dest_name: str


class RenameFacade:
    def propose(
        self,
        path: str,
        *,
        update: Optional[TagUpdate] = None,
        title: Optional[str] = None,
        artist: Optional[str] = None,
        template: str = "{title}_{artist}",
    ) -> RenameProposal:
        base_dir = os.path.dirname(path)
        original = os.path.basename(path)
        _, ext = os.path.splitext(original)

        if update:
            title = title or update.title
            artist = artist or update.artist

        t = helpers.safe_filename_component(title)
        a = helpers.safe_filename_component(artist)

        if t and a:
            name = template.format(title=t, artist=a) + ext
        else:
            name = original

        return RenameProposal(path, os.path.join(base_dir, name), name)

    def apply(self, proposal: RenameProposal) -> str:
        if proposal.src_path != proposal.dest_path:
            os.rename(proposal.src_path, proposal.dest_path)
        return proposal.dest_path


@dataclass
class PipelineResult:
    path_in: str
    path_out: str
    desired_filename: str
    identified: bool
    confidence: Optional[float]
    wrote_tags: bool
    renamed: bool
    reason: str


class Pipeline:
    def __init__(self, ia: IdentifyAudio, renamer: RenameFacade):
        self.ia = ia
        self.renamer = renamer

    def process_file(
        self,
        path: str,
        *,
        do_identify: bool = True,
        do_tag: bool = True,
        do_rename: bool = True,
        min_confidence: float = 0.9,
    ) -> PipelineResult:

        snapshot = self.ia.tags.read(path)

        chosen = None
        if do_identify:
            try:
                cands = self.ia.identify.candidates(path, snapshot)
                if cands:
                    chosen = max(cands, key=lambda c: c.confidence)
            except Exception:
                pass

        if not chosen or chosen.confidence < min_confidence:
            if do_tag:
                self.ia.tags.write(
                    path, snapshot.to_metadata(), ensure_virtualdj_compat=True
                )
            out_path = path
            name = os.path.basename(path)
            if do_rename:
                p = self.renamer.propose(path, update=snapshot.to_metadata())
                out_path = self.renamer.apply(p)
                name = p.dest_name
            return PipelineResult(
                path,
                out_path,
                name,
                False,
                None,
                do_tag,
                do_rename,
                "no_or_low_confidence",
            )

        meta = self.ia.metadata.fetch(chosen)
        if do_tag:
            self.ia.tags.write(path, meta, ensure_virtualdj_compat=True)

        out_path = path
        name = os.path.basename(path)
        if do_rename:
            p = self.renamer.propose(path, update=meta)
            out_path = self.renamer.apply(p)
            name = p.dest_name

        return PipelineResult(
            path,
            out_path,
            name,
            True,
            float(chosen.confidence),
            do_tag,
            do_rename,
            "ok",
        )


class AudioToolbox:
    def __init__(self, ia: IdentifyAudio):
        self.identify = ia.identify
        self.metadata = ia.metadata
        self.tags = ia.tags
        self.rename = RenameFacade()
        self.pipeline = Pipeline(ia, self.rename)

    @classmethod
    def from_env(cls, *, acoustid_api_key: str) -> "AudioToolbox":
        ia = IdentifyAudio.from_env(acoustid_api_key=acoustid_api_key)
        return cls(ia)
