from __future__ import annotations

import kaiano_common_utils.logger as log

from .identify import IdentifierFacade
from .merge import MergeFacade
from .metadata import MetadataFacade
from .policies import IdentificationPolicy, RenamePolicy, TagPolicy
from .rename import RenameFacade
from .result import ProcessResult, ProcessWarning
from .retagger_api import AcoustIdIdentifier, MusicBrainzRecordingProvider
from .tags import TagFacade

log = log.get_logger()


class IdentifyAudio:
    """Single entry point for identify + fetch metadata + tag + rename.

    This is intentionally small and stable. Internals (AcoustID, MusicBrainz,
    music_tag/mutagen) are hidden behind facades.
    """

    def __init__(
        self,
        *,
        identify: IdentifierFacade,
        metadata: MetadataFacade,
        tags: TagFacade,
        merge: MergeFacade,
        rename: RenameFacade,
        id_policy: IdentificationPolicy | None = None,
    ):
        self.identify = identify
        self.metadata = metadata
        self.tags = tags
        self.merge = merge
        self.rename = rename
        self.id_policy = id_policy or IdentificationPolicy()

    @classmethod
    def default(
        cls,
        *,
        acoustid_api_key: str,
        id_policy: IdentificationPolicy | None = None,
        app_name: str = "identify-audio",
        app_version: str = "0.1.0",
        contact: str = "https://example.com",
        throttle_s: float = 1.0,
    ) -> "IdentifyAudio":
        id_policy = id_policy or IdentificationPolicy()
        identifier = AcoustIdIdentifier(
            api_key=acoustid_api_key,
            min_confidence=id_policy.min_confidence,
            max_candidates=id_policy.max_candidates,
        )
        provider = MusicBrainzRecordingProvider(
            app_name=app_name,
            app_version=app_version,
            contact=contact,
            throttle_s=throttle_s,
        )
        return cls(
            identify=IdentifierFacade(identifier),
            metadata=MetadataFacade(provider),
            tags=TagFacade(),
            merge=MergeFacade(),
            rename=RenameFacade(),
            id_policy=id_policy,
        )

    @classmethod
    def from_env(
        cls,
        *,
        acoustid_api_key: str,
        id_policy: IdentificationPolicy | None = None,
        app_name: str = "identify-audio",
        app_version: str = "0.1.0",
        contact: str = "https://example.com",
        throttle_s: float = 1.0,
    ) -> "IdentifyAudio":
        # keeping parity with GoogleAPI.from_env pattern
        return cls.default(
            acoustid_api_key=acoustid_api_key,
            id_policy=id_policy,
            app_name=app_name,
            app_version=app_version,
            contact=contact,
            throttle_s=throttle_s,
        )

    def process_file(
        self,
        path: str,
        *,
        tag: TagPolicy | None = None,
        rename: RenamePolicy | None = None,
    ) -> ProcessResult:
        """Process a single local file in-place.

        Steps:
        1) Read current tags
        2) Identify via AcoustID
        3) Fetch metadata via MusicBrainz (best candidate)
        4) Merge to build tag updates
        5) Write tags (optionally VDJ-compatible)
        6) Rename file (optional)
        """

        tag = tag or TagPolicy.virtualdj_safe()
        rename = rename or RenamePolicy.template_policy("{title}_{artist}")

        res = ProcessResult(path_in=path)
        try:
            snapshot = self.tags.read(path)

            candidates = self.identify.candidates(path, snapshot)
            if not candidates:
                res.warnings.append(
                    ProcessWarning(
                        code="no_candidates", message="AcoustID returned no candidates"
                    )
                )
                if tag.on_identify_fail == "passthrough":
                    updates = self.merge.passthrough(snapshot)
                    self.tags.write(
                        path,
                        updates,
                        ensure_virtualdj_compat=tag.ensure_virtualdj_compat,
                    )
                    res.wrote_tags = True
                    res.identified = False
                    # Rename based on passthrough only if enabled and fields present
                    if rename.enabled and (
                        not rename.require_title_and_artist
                        or (updates.title and updates.artist)
                    ):
                        res.path_out = self.rename.apply(
                            path, updates, template=rename.template
                        )
                        res.renamed = res.path_out != path
                    return res
                return res

            chosen = max(candidates, key=lambda c: c.confidence)
            res.chosen = chosen

            # Enforce min confidence here too (extra safety if caller overrides identifier)
            if chosen.confidence < (self.id_policy.min_confidence or 0.0):
                res.warnings.append(
                    ProcessWarning(
                        code="low_confidence",
                        message=f"Best candidate {chosen.confidence:.3f} below threshold {self.id_policy.min_confidence:.2f}",
                    )
                )
                if tag.on_identify_fail == "passthrough":
                    updates = self.merge.passthrough(snapshot)
                    self.tags.write(
                        path,
                        updates,
                        ensure_virtualdj_compat=tag.ensure_virtualdj_compat,
                    )
                    res.wrote_tags = True
                    res.identified = False
                    if rename.enabled and (
                        not rename.require_title_and_artist
                        or (updates.title and updates.artist)
                    ):
                        res.path_out = self.rename.apply(
                            path, updates, template=rename.template
                        )
                        res.renamed = res.path_out != path
                    return res
                return res

            meta = self.metadata.fetch(chosen)
            res.metadata = meta
            res.identified = True

            updates = self.merge.build_updates(snapshot, meta)
            self.tags.write(
                path, updates, ensure_virtualdj_compat=tag.ensure_virtualdj_compat
            )
            res.wrote_tags = True

            if rename.enabled and (
                not rename.require_title_and_artist
                or (updates.title and updates.artist)
            ):
                res.path_out = self.rename.apply(
                    path, updates, template=rename.template
                )
                res.renamed = res.path_out != path

            return res

        except Exception as e:
            res.error = str(e)
            log.error(f"[IdentifyAudio] Failed processing {path}: {e!r}")
            return res
