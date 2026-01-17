class MetadataFacade:
    def __init__(self, provider):
        self._provider = provider

    def fetch(self, track_id):
        return self._provider.fetch(track_id)
