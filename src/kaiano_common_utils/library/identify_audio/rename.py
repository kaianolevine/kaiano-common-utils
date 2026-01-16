import os


class RenameFacade:
    def apply(self, path: str, update, *, template: str = "{title}_{artist}") -> str:
        """Rename a local file based on metadata.

        This is a convenience wrapper around propose+os.rename.
        - `update` is expected to have `.title` and `.artist` attributes.
        - Returns the final path (may be unchanged if we cannot build a safe name).
        """

        proposal = self.propose(
            path,
            title=getattr(update, "title", None),
            artist=getattr(update, "artist", None),
            template=template,
        )

        # Support either tuple-based proposals or RenameProposal dataclass.
        try:
            src = proposal.src_path
            dst = proposal.dest_path
        except Exception:
            src, dst, _ = proposal

        if src != dst:
            os.rename(src, dst)
            return dst

        return src
