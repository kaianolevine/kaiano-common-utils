from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Optional

import kaiano.helpers as helpers

from .identify import IdentifyAudio
from .policies import IdentificationPolicy, RenamePolicy, TagPolicy
from .rename import RenameFacade
from .retagger_types import TagSnapshot, TrackId, TrackMetadata


@dataclass
class PipelineResult:
    """Result from the optional convenience pipeline."""

    path_in: str
    path_out: str
    desired_filename: str
    identified: bool
    wrote_tags: bool
    renamed: bool
    reason: str
    confidence: Optional[float] = None
    chosen: Optional[TrackId] = None


def _passthrough_updates_from_snapshot(snapshot: TagSnapshot) -> TrackMetadata:
    """Build TrackMetadata from existing readable tags for a safe rewrite."""
    t = snapshot.tags

    title = helpers.safe_str(t.get("tracktitle")).strip()
    artist = helpers.safe_str(t.get("artist")).strip()
    album = helpers.safe_str(t.get("album")).strip()
    album_artist = helpers.safe_str(t.get("albumartist")).strip()
    genre = helpers.safe_str(t.get("genre")).strip()
    bpm = helpers.safe_str(t.get("bpm")).strip()
    comment = helpers.safe_str(t.get("comment")).strip()
    year = helpers.normalize_year_for_tag(t.get("year") or t.get("date"))

    track_number = helpers.safe_str(t.get("tracknumber")).strip()
    disc_number = helpers.safe_str(t.get("discnumber")).strip()

    return TrackMetadata(
        title=title if title else None,
        artist=artist if artist else None,
        album=album if album else None,
        album_artist=album_artist if album_artist else None,
        year=year if year else None,
        genre=genre if genre else None,
        bpm=bpm if bpm else None,
        comment=comment if comment else None,
        isrc=None,
        track_number=track_number if track_number else None,
        disc_number=disc_number if disc_number else None,
        raw=getattr(snapshot, "raw", None),
    )


class PipelineFacade:
    """Composable convenience layer (optional)."""

    def __init__(self, ia: IdentifyAudio, renamer: RenameFacade):
        self._ia = ia
        self._renamer = renamer

    def process_file(
        self,
        path: str,
        *,
        do_identify: bool = True,
        do_tag: bool = True,
        do_rename: bool = True,
        min_confidence: Optional[float] = None,
        tag: Optional[TagPolicy] = None,
        rename: Optional[RenamePolicy] = None,
    ) -> PipelineResult:
        tag = tag or TagPolicy.virtualdj_safe()
        rename = rename or RenamePolicy.template_policy("{title}_{artist}")
        threshold = (
            min_confidence
            if min_confidence is not None
            else self._ia.id_policy.min_confidence
        )

        snapshot: Optional[TagSnapshot] = None
        if do_tag or do_identify or do_rename or tag.on_identify_fail == "passthrough":
            snapshot = self._ia.tags.read(path)

        chosen: Optional[TrackId] = None
        confidence: Optional[float] = None

        if do_identify and snapshot is not None:
            try:
                candidates = self._ia.identify.candidates(path, snapshot)
            except Exception:
                candidates = []
            if candidates:
                chosen = max(candidates, key=lambda c: c.confidence)
                confidence = float(chosen.confidence)

        if (
            (not do_identify)
            or (chosen is None)
            or (confidence is not None and confidence < threshold)
        ):
            if not do_identify:
                reason = "identify_disabled"
            elif chosen is None:
                reason = "no_candidates"
            else:
                reason = "low_confidence"

            wrote = False
            updates: Optional[TrackMetadata] = None
            if (
                do_tag
                and snapshot is not None
                and tag.on_identify_fail == "passthrough"
            ):
                updates = _passthrough_updates_from_snapshot(snapshot)
                self._ia.tags.write(
                    path, updates, ensure_virtualdj_compat=tag.ensure_virtualdj_compat
                )
                wrote = True

            out_path = path
            renamed = False
            desired = os.path.basename(path)

            if do_rename and updates is not None and rename.enabled:
                if (not rename.require_title_and_artist) or (
                    updates.title and updates.artist
                ):
                    out_path = self._renamer.apply(
                        path, updates, template=rename.template
                    )
                    renamed = out_path != path
                    desired = os.path.basename(out_path)

            return PipelineResult(
                path_in=path,
                path_out=out_path,
                desired_filename=desired,
                identified=False,
                wrote_tags=wrote,
                renamed=renamed,
                reason=reason,
                confidence=confidence,
                chosen=chosen,
            )

        assert chosen is not None
        meta = self._ia.metadata.fetch(chosen)

        wrote = False
        if do_tag:
            self._ia.tags.write(
                path, meta, ensure_virtualdj_compat=tag.ensure_virtualdj_compat
            )
            wrote = True

        out_path = path
        renamed = False
        desired = os.path.basename(path)

        if do_rename and rename.enabled:
            if (not rename.require_title_and_artist) or (meta.title and meta.artist):
                out_path = self._renamer.apply(path, meta, template=rename.template)
                renamed = out_path != path
                desired = os.path.basename(out_path)

        return PipelineResult(
            path_in=path,
            path_out=out_path,
            desired_filename=desired,
            identified=True,
            wrote_tags=wrote,
            renamed=renamed,
            reason="ok",
            confidence=confidence,
            chosen=chosen,
        )


class AudioToolbox:
    """Single entry point providing independent identify/tag/rename + optional pipeline."""

    def __init__(self, ia: IdentifyAudio):
        self._ia = ia
        self.identify = ia.identify
        self.metadata = ia.metadata
        self.tags = ia.tags
        self.rename = RenameFacade()
        self.pipeline = PipelineFacade(ia, self.rename)

    @classmethod
    def from_env(
        cls,
        *,
        acoustid_api_key: str,
        id_policy: Optional[IdentificationPolicy] = None,
        app_name: str = "identify-audio",
        app_version: str = "0.1.0",
        contact: str = "",
        throttle_s: float = 1.0,
    ) -> "AudioToolbox":
        ia = IdentifyAudio.from_env(
            acoustid_api_key=acoustid_api_key,
            id_policy=id_policy,
            app_name=app_name,
            app_version=app_version,
            contact=contact,
            throttle_s=throttle_s,
        )
        return cls(ia)
