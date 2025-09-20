from getpass import getpass
import logging

import musicbrainzngs

from core.base import BaseProcessor


class ReBrainer(BaseProcessor):
    """
    Checks if files should be updated with fresh metadata from the MusicBrainz API.
    """

    placeholder = True

    def __init__(self, **config):
        super().__init__(**config)

        # Setup and redirect musicbrainzngs logger
        musicbrainz_logger = logging.getLogger("musicbrainzngs")
        musicbrainz_logger.setLevel(logging.DEBUG)
        musicbrainz_logger.handlers.clear()
        for handler in self.logger.handlers:
            musicbrainz_logger.addHandler(handler)
        musicbrainz_logger.propagate = False

        # Load configuration
        self.field_map = config.get("field_map", {})
        self.include = config.get("include", [])
        self.username = config.get("username", None)
        self.password = config.get("password", None)

        # Initialise index
        self.results = {}

    def post_index(self):
        # Set user agent and authenticate
        musicbrainzngs.set_useragent("ReBrainer", "1.0")
        if not self.username:
            self.username = input("Enter MusicBrainz username: ")
        if not self.password:
            self.password = getpass("Enter MusicBrainz password: ")
        musicbrainzngs.auth(self.username, self.password)
