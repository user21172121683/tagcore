import musicbrainzngs
from utils import *
from pathlib import Path
from mutagen.flac import FLAC
from getpass import getpass
import logging


class ReBrainer:
    """
    Checks if files should be updated with fresh metadata from the MusicBrainz API.
    """
    def __init__(self, **config):
        # Setup logger
        self.logger = setup_logger(
            name="rebrainer",
            base_dir=Path(__file__).resolve().parents[2],
            console_level=config.get('console_level'),
            file_level=config.get('file_level')
        )

        # Setup and redirect musicbrainzngs logger
        musicbrainz_logger = logging.getLogger("musicbrainzngs")
        musicbrainz_logger.setLevel(logging.DEBUG)
        musicbrainz_logger.handlers.clear()
        for handler in self.logger.handlers:
            musicbrainz_logger.addHandler(handler)
        musicbrainz_logger.propagate = False

        # Stop flag (for safe quitting)
        self.stop_flag = config.get("stop_flag")

        # Load configuration
        self.main_dir = Path(config['main_dir'])
        self.dry_run = config.get('dry_run', True)
        self.field_map = config.get("field_map", {})
        self.include = config.get("include", [])
        self.username = config.get("username", None)
        self.password = config.get("password", None)

        # Initialise indices
        self._results = {}
        self._files_processed = []
        self._files_modified = []

    def run(self):
        self._login()
        self.files = index_files(self.main_dir, "flac", self.logger)
        for file in self.files:
            self._files_processed.append(file)
            self.logger.info(processing_message(len(self._files_processed), len(self.files), file))
            audio = FLAC(file)
            audio_id = audio.get("MUSICBRAINZ_ALBUMID", None)[0]
            if audio_id:
                self.logger.debug(f"Looking up track with ID: {audio_id}")
                if audio_id in self._results:
                    self.logger.debug("Found match in existing results!")
                    result = self._results[audio_id]
                else:
                    self.logger.debug("Requesting release from MusicBrainz...")
                    result = musicbrainzngs.get_release_by_id(id=audio_id, includes=self.include)
                if result:
                    pass
                else:
                    self.logger.info("No match found!")
            else:
                self.logger.info("No track id in file.")
    
    def _login(self):
        # Set user agent and authenticate
        musicbrainzngs.set_useragent("ReBrainer", "1.0")
        if not self.username:
            self.username = input("Enter MusicBrainz username: ")
        if not self.password:
            self.password = getpass("Enter MusicBrainz password: ")
        musicbrainzngs.auth(self.username, self.password)
