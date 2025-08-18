import musicbrainzngs


class ReBrainer:
    """
    Checks if files should be updated with fresh metadata from the MusicBrainz API.
    """
    def __init__(self, **config):
        # Set user agent
        musicbrainzngs.set_useragent("ReBrainer", "1.0")
