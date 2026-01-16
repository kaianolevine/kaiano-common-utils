import os


class RenameFacade:
    def propose(self, path, *, title=None, artist=None, template="{title}_{artist}"):
        base = os.path.dirname(path)
        name = os.path.basename(path)
        root, ext = os.path.splitext(name)

        if title and artist:
            new_name = template.format(title=title, artist=artist) + ext
        else:
            new_name = name

        return path, os.path.join(base, new_name), new_name

    def apply(self, proposal):
        src, dst, _ = proposal
        if src != dst:
            os.rename(src, dst)
        return dst
