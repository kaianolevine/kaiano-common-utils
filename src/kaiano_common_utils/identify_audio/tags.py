class TagFacade:
    def __init__(self, io):
        self._io = io

    def read(self, path):
        return self._io.read(path)

    def write(self, path, metadata, *, ensure_virtualdj_compat=False):
        return self._io.write(
            path,
            metadata,
            ensure_virtualdj_compat=ensure_virtualdj_compat,
        )

    def dump(self, path):
        if hasattr(self._io, "dump_tags"):
            return self._io.dump_tags(path)
        return self._io.dump(path)
