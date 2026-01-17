from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class IdentificationPolicy:
    """Controls how identification is attempted."""

    min_confidence: float = 0.90
    max_candidates: int = 5


@dataclass(frozen=True)
class TagPolicy:
    """Controls tag-writing behavior."""

    ensure_virtualdj_compat: bool = True

    # When no candidates are found or confidence is too low:
    # - "passthrough": rewrite existing readable tags to improve VDJ compatibility
    # - "skip": do nothing
    on_identify_fail: str = "passthrough"  # "passthrough" | "skip"

    @classmethod
    def virtualdj_safe(cls) -> "TagPolicy":
        return cls(ensure_virtualdj_compat=True, on_identify_fail="passthrough")


@dataclass(frozen=True)
class RenamePolicy:
    """Controls file renaming."""

    enabled: bool = True
    template: str = "{title}_{artist}"

    # If required fields are missing, keep the original filename.
    require_title_and_artist: bool = True

    @classmethod
    def none(cls) -> "RenamePolicy":
        return cls(enabled=False)

    @classmethod
    def template_policy(
        cls, template: str, *, require_title_and_artist: bool = True
    ) -> "RenamePolicy":
        return cls(
            enabled=True,
            template=template,
            require_title_and_artist=require_title_and_artist,
        )
