import os
from dataclasses import dataclass

from .identify import IdentifyAudio
from .policies import RenamePolicy, TagPolicy


@dataclass
class PipelineResult:
    path_in: str
    path_out: str
    desired_filename: str
    identified: bool
    wrote_tags: bool
    renamed: bool
    reason: str
    confidence: float | None = None


class PipelineFacade:
    """Optional convenience wrapper that still allows independent steps."""

    def __init__(self, ia: "IdentifyAudio"):
        self._ia = ia

    def process_file(
        self,
        path: str,
        *,
        do_identify: bool = True,
        do_tag: bool = True,
        do_rename: bool = True,
        min_confidence: float | None = None,
    ) -> PipelineResult:
        # Map independent toggles onto IdentifyAudio.process_file
        tag = TagPolicy.virtualdj_safe()
        if not do_tag:
            # Don't write tags in any branch
            tag = TagPolicy(
                ensure_virtualdj_compat=tag.ensure_virtualdj_compat,
                on_identify_fail="skip",
            )

        rename = RenamePolicy.template_policy("{title}_{artist}")
        if not do_rename:
            rename = RenamePolicy(enabled=False)

        # If identify is disabled, optionally do passthrough tagging + optional rename
        if not do_identify:
            reason = "identify_disabled"
            wrote = False
            path_out = path
            renamed = False

            if do_tag:
                snapshot = self._ia.tags.read(path)
                updates = self._ia.merge.passthrough(snapshot)
                self._ia.tags.write(
                    path, updates, ensure_virtualdj_compat=tag.ensure_virtualdj_compat
                )
                wrote = True

                if rename.enabled and (
                    not rename.require_title_and_artist
                    or (updates.title and updates.artist)
                ):
                    path_out = self._ia.rename.apply(
                        path, updates, template=rename.template
                    )
                    renamed = path_out != path

            return PipelineResult(
                path_in=path,
                path_out=path_out,
                desired_filename=os.path.basename(path_out),
                identified=False,
                wrote_tags=wrote,
                renamed=renamed,
                reason=reason,
                confidence=None,
            )

        # Identify enabled -> use existing IdentifyAudio logic
        res = self._ia.process_file(path, tag=tag, rename=rename)

        # Determine reason + confidence from ProcessResult
        confidence = float(res.chosen.confidence) if res.chosen else None

        if res.error:
            reason = "error"
        elif res.identified:
            reason = "ok"
        else:
            # Use first warning code if present
            reason = res.warnings[0].code if res.warnings else "not_identified"

        # Optional extra gate: if caller passes min_confidence, treat below as low_confidence
        if (
            min_confidence is not None
            and confidence is not None
            and confidence < min_confidence
        ):
            reason = "low_confidence"

        path_out = res.path_out or res.path_in
        return PipelineResult(
            path_in=res.path_in,
            path_out=path_out,
            desired_filename=os.path.basename(path_out),
            identified=bool(res.identified) and reason == "ok",
            wrote_tags=bool(res.wrote_tags),
            renamed=bool(res.renamed),
            reason=reason,
            confidence=confidence,
        )


class AudioToolbox:
    """Single entry point providing independent identify/tag/rename + optional pipeline."""

    def __init__(self, ia: IdentifyAudio):
        self._ia = ia
        self.identify = ia.identify
        self.metadata = ia.metadata
        self.tags = ia.tags
        self.rename = ia.rename
        self.pipeline = PipelineFacade(ia)

    @classmethod
    def from_env(cls, *, acoustid_api_key: str, **kwargs) -> "AudioToolbox":
        ia = IdentifyAudio.from_env(acoustid_api_key=acoustid_api_key, **kwargs)
        return cls(ia)
