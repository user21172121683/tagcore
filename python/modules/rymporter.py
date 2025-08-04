from mutagen.flac import FLAC
import traceback
from utils import index_files, setup_logger, processing_message, returning_message, summary_message
from pathlib import Path
from rymparser import Rymparser


class Rymporter:
    """
    Parses RYM collection HTML and updates FLAC files with matched metadata.
    """

    def __init__(self, **config):
        """
        Initialize Rymporter with configuration parameters.

        Args:
            config (dict): Configuration dictionary with keys:
                - main_dir (str): Directory containing FLAC files.
                - field_definitions (dict): Mapping of tag keys to metadata field names.
                - collection_html (str): Path to the RYM collection HTML file.
                - fields_to_modify (dict): Fields that should be updated.
                - dry_run (bool): If True, do not save changes.
                - auto_skip (bool): If True, skip unmatched albums without prompt.
        """
        # Setup logger
        self.logger = setup_logger("rymporter", Path(__file__).resolve().parents[1])

        # Load configuration
        self.main_dir = Path(config["main_dir"])
        self.field_definitions = config["field_definitions"]
        self.collection_html_file = config["collection_html"]
        self.fields_to_modify = config["fields_to_modify"]
        self.dry_run = config.get("dry_run", True)
        self.auto_skip = config.get("auto_skip", False)

        # Set internal state
        self.files = []
        self.rym_albums = []
        self._manual_matches = {}
        self._albums_to_skip = []
        self._insufficient_metadata = []
        self._files_processed = 0
        self._files_modified = []

    def run(self):
        """
        Parse the RYM collection HTML and update FLAC files with matched metadata.
        Raises RuntimeError on fatal errors.
        """

        self.rym_albums = self.parse_collection_html()
        self.files = index_files(directory=self.main_dir, extension="flac", logger=self.logger)
        self.logger.info("Starting RYM album matching process...")

        for file in self.files:
            self._files_processed += 1
            self.logger.info(processing_message(self._files_processed, len(self.files), file))
            self.match_album(file)

        self.logger.info(summary_message("Rymporter"))
        self.logger.info(f"Total files processed: {self._files_processed}")
        self.logger.info(("[DRY RUN] " if self.dry_run else "") + f"Total files modified: {len(self._files_modified)}")
        if self._albums_to_skip:
            self.logger.warning(f"Unmatched albums skipped: {len(self._albums_to_skip)}")

        if self._insufficient_metadata:
            self.logger.warning(f"Files with insufficient metadata skipped: {len(self._insufficient_metadata)}")

        if not self._albums_to_skip and not self._insufficient_metadata:
            self.logger.info("No issues encountered.")

        self.logger.info(returning_message())
    
    def parse_collection_html(self):
        parser = Rymparser()
        self.logger.info("Parsing collection HTML...")
        try:
            with open(self.collection_html_file, "r", encoding="utf-8") as f:
                collection_html = f.read()
            parser.feed(collection_html)
            # TODO: fix this hacky skip of first album
            if len(parser.albums[1:]) == 0:
                self.logger.info("No albums found in the HTML content.")
            else:
                self.logger.info(f"Parsed {len(self.rym_albums)} albums from the HTML content.")
            return parser.albums[1:]
        except FileNotFoundError:
            self.logger.error(f"Collection HTML file '{self.collection_html_file}' not found.")
        except Exception as e:
            self.logger.error(f"Unexpected error parsing collection HTML: {e}")
            self.logger.error("Traceback:\n" + traceback.format_exc())

    def match_album(self, file: Path):
        """
        Attempt to match a FLAC file's metadata with RYM album data and update metadata if matched.

        Args:
            file (Path): Path to the FLAC file.
        """
        matched = False
        try:
            audio = FLAC(file)
            audio_artist = audio.get(self.field_definitions["artist_name"], [""])[0]
            audio_album_title = audio.get(self.field_definitions["album_title"], [""])[0]
            audio_album_id = audio.get(self.field_definitions["album_id"], [""])[0]

            if not audio_album_id and not (audio_artist and audio_album_title):
                self.logger.warning("Skipping file due to insufficient metadata.")
                self._insufficient_metadata.append(file)
                return

            if (audio_artist, audio_album_title) in self._albums_to_skip:
                self.logger.debug("Skipping previously skipped album.")
                return

            for i, rym_album in enumerate(self.rym_albums):
                rym_album_id = rym_album["album"]["album_id"]
                rym_album_title = rym_album["album"]["album_title"]
                rym_artist = rym_album["artist"][0]["artist_name"]

                rym_album_str = (
                    f'{rym_album_id} "{rym_album_title.strip('"')}" by '
                    f'{", ".join(artist.get("artist_name", "") for artist in rym_album.get("artist", []))} '
                    f'({rym_album["date"]})'
                )

                # Match by ID
                if rym_album_id == audio_album_id:
                    self.logger.debug(f"Matched via ID: {rym_album_str}")
                    matched = True
                    self._update_album(rym_album, audio, file)
                    break

                # Match by normalized artist and album title
                if rym_artist == audio_artist and rym_album_title == audio_album_title:
                    self.logger.debug(f"Matched via artist-title: {rym_album_str}")
                    matched = True
                    self._update_album(rym_album, audio, file)
                    break

                # Check manual matches
                for input_id, (input_artist, input_title) in self._manual_matches.items():
                    if rym_album_id == input_id and input_artist == audio_artist and input_title == audio_album_title:
                        self.logger.debug(f"Matched via manual input: {rym_album_str}")
                        matched = True
                        self._update_album(rym_album, audio, file)
                        break

                # No match found after last album in list
                if i == len(self.rym_albums) - 1 and not matched:
                    if self.auto_skip:
                        self.logger.warning("No match found. Auto-skipping album.")
                        self._albums_to_skip.append((audio_artist, audio_album_title))
                        continue

                    self.logger.warning(f"No match found.\nMetadata in file:\n{"\n".join(f"  {line}" for line in audio.pprint().splitlines())}\nAsking user for input...")
                    input_id = input("Press Enter to skip or type Album ID: ").strip()

                    if input_id:
                        self.logger.info(f"User entered Album ID: {input_id}")
                        for rym_album in self.rym_albums:
                            if input_id == rym_album["album"]["album_id"]:
                                self.logger.info(f"User confirmed match: {input_id}")
                                matched = True
                                self._manual_matches[input_id] = (audio_artist, audio_album_title)
                                self._update_album(rym_album, audio, file)
                                break
                        if not matched:
                            self.logger.warning(f"No album found with ID: {input_id}. Skipping...")
                            self._albums_to_skip.append((audio_artist, audio_album_title))
                    else:
                        self.logger.info("User skipped album manually.")
                        self._albums_to_skip.append((audio_artist, audio_album_title))

        except Exception as e:
            self.logger.error(f"Error processing {file}: {type(e).__name__}: {e}")
            self.logger.error("Traceback:\n" + traceback.format_exc())

    def _update_album(self, rym_album: dict, audio: FLAC, file: Path):
        """
        Update the FLAC file metadata with data from a matched RYM album.

        Args:
            rym_album (dict): Matched album data from RYM.
            audio (FLAC): Mutagen FLAC object for the file.
        """
        self.logger.debug("Updating file with RYM data...")
        new_metadata = self._build_new_metadata_dict(rym_album)

        modified = False
        for field_name, new_values in new_metadata.items():
            # Use uppercase field names consistently
            current_values = audio.get(field_name.upper(), [])
            if self._should_update_field(current_values, new_values):
                self.logger.debug(f"  {field_name.upper()} = {', '.join(map(str, new_values))}")
                audio[field_name.upper()] = new_values
                modified = True
                self._files_modified.append(file)
            else:
                self.logger.debug(f"  {field_name.upper()} is unchanged. Skipping update.")

        if modified:
            if not self.dry_run:
                try:
                    audio.save()
                    self.logger.info("File successfully updated with RYM data.")
                except Exception as e:
                    self.logger.error(f"Error saving file: {e}")
            else:
                self.logger.info("[DRY RUN] Changes detected but not saved.")
        else:
            self.logger.debug("No changes detected. File remains unmodified.")

    def _build_new_metadata_dict(self, rym_album: dict) -> dict:
        """
        Build a dictionary of tag field names and their new values from RYM album data.

        Args:
            rym_album (dict): Album data from RYM.

        Returns:
            dict: Mapping of metadata field names (uppercase) to list of values.
        """
        temp_values = {
            self.field_definitions[tag].upper(): []
            for tag in self.fields_to_modify
            if self.fields_to_modify.get(tag) and self.field_definitions.get(tag)
        }

        for tag, value in rym_album.items():
            tag_value_pairs = []

            if isinstance(value, list):
                for item in value:
                    if isinstance(item, dict):
                        tag_value_pairs.extend(
                            (k, v) for k, v in item.items() if v not in (None, '')
                        )
                    elif isinstance(item, str):
                        tag_value_pairs.append((tag, item))
            elif isinstance(value, dict):
                tag_value_pairs.extend(
                    (k, v) for k, v in value.items() if v not in (None, '')
                )
            else:
                if value not in (None, ''):
                    tag_value_pairs.append((tag, value))

            for key, val in tag_value_pairs:
                if self.fields_to_modify.get(key):
                    field_name = self.field_definitions.get(key)
                    if field_name:
                        temp_values[field_name.upper()].append(val)

        return temp_values

    def _should_update_field(self, current_values: list, new_values: list) -> bool:
        """
        Determine if a metadata field should be updated by comparing current and new values.

        Args:
            current_values (list): Current metadata values.
            new_values (list): New metadata values.

        Returns:
            bool: True if values differ, False otherwise.
        """
        current_values_str = [str(v) for v in current_values]
        new_values_str = [str(v) for v in new_values]
        return current_values_str != new_values_str
