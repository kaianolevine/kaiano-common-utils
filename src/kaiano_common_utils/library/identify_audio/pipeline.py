import os


class Pipeline:
    def __init__(self, ia, renamer):
        self.ia = ia
        self.renamer = renamer

    def process_file(
        self,
        path,
        *,
        do_identify=True,
        do_tag=True,
        do_rename=True,
        min_confidence=0.9,
    ):
        snapshot = self.ia.tags.read(path)
        chosen = None

        if do_identify:
            candidates = self.ia.identify.candidates(path, snapshot)
            if candidates:
                chosen = max(candidates, key=lambda c: c.confidence)

        if not chosen or chosen.confidence < min_confidence:
            if do_tag:
                self.ia.tags.write(
                    path, snapshot.to_metadata(), ensure_virtualdj_compat=True
                )

            out = path
            name = os.path.basename(path)
            if do_rename:
                prop = self.renamer.propose(path)
                out = self.renamer.apply(prop)
                name = prop[2]

            return {
                "identified": False,
                "path_out": out,
                "desired_filename": name,
                "wrote_tags": do_tag,
                "reason": "no_or_low_confidence",
            }

        meta = self.ia.metadata.fetch(chosen)
        if do_tag:
            self.ia.tags.write(path, meta, ensure_virtualdj_compat=True)

        out = path
        name = os.path.basename(path)
        if do_rename:
            prop = self.renamer.propose(path, title=meta.title, artist=meta.artist)
            out = self.renamer.apply(prop)
            name = prop[2]

        return {
            "identified": True,
            "path_out": out,
            "desired_filename": name,
            "wrote_tags": do_tag,
            "reason": "ok",
        }
