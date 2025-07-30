from mutagen.flac import FLAC
from pprint import pformat
import traceback
from utils import index_files, setup_logger, processing_message
from datetime import datetime
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
                - master_dir (str): Directory containing FLAC files.
                - field_definitions (dict): Mapping of tag keys to metadata field names.
                - collection_html (str): Path to the RYM collection HTML file.
                - fields_to_modify (dict): Fields that should be updated.
                - dry_run (bool): If True, do not save changes.
                - auto_skip (bool): If True, skip unmatched albums without prompt.
        """
        # Setup logger
        self.logger = setup_logger("rymporter", Path(__file__).resolve().parents[1])

        # Load configuration
        self.master_dir = config["master_dir"]
        self.field_definitions = config["field_definitions"]
        self.collection_html_file = config["collection_html"]
        self.fields_to_modify = config["fields_to_modify"]
        self.dry_run = config.get("dry_run", True)
        self.auto_skip = config.get("auto_skip", False)

        # Set internal state
        self.files = index_files(directory=self.master_dir, extension="flac", logger=self.logger)
        if len(self.files) == 0:
            self.logger.critical(f"No flac files found in {self.master_dir}.")
            raise RuntimeError(f"No flac files found in {self.master_dir}.")
        self.rym_albums = []
        self._manual_matches = {}
        self._albums_to_skip = []
        self._insufficient_metadata = []
        self._files_processed = 0
        self._files_modified = 0

    def run(self):
        """
        Parse the RYM collection HTML and update FLAC files with matched metadata.
        Raises RuntimeError on fatal errors.
        """
        self.logger.info("Starting Rymparser...")
        parser = Rymparser()

        self.logger.info("Parsing collection HTML...")
        try:
            with open(self.collection_html_file, "r", encoding="utf-8") as f:
                collection_html = f.read()

            parser.feed(collection_html)
            self.rym_albums = parser.albums[1:]  # TODO: fix this hacky skip of first album

            if len(self.rym_albums) == 0:
                self.logger.critical("No albums found in the HTML content.")
                raise RuntimeError("No albums found in the HTML content.")
            
            else:
                self.logger.info(f"Parsed {len(self.rym_albums)} albums from the HTML content.")
                log_dir = Path(__file__).resolve().parents[1] / "logs" / datetime.now().strftime('%Y-%m-%d')
                log_dir.mkdir(exist_ok=True)
                with open(log_dir / "albums.txt", "w", encoding="utf-8") as f:
                    self.logger.info(f"Writing parsed albums to {log_dir}/albums.txt for debugging...")
                    f.write(pformat(self.rym_albums))

        except FileNotFoundError:
            self.logger.error(f"Collection HTML file '{self.collection_html_file}' not found.")
            raise
        except Exception as e:
            self.logger.error(f"Unexpected error parsing collection HTML: {e}")
            self.logger.error("Traceback:\n" + traceback.format_exc())
            raise

        self.logger.info("Starting RYM album matching process...")

        self._files_processed = 0
        self._files_modified = 0
        for file in self.files:
            self._files_processed += 1
            self.logger.info(processing_message(self._files_processed, len(self.files), file))
            self.match_album(file)

        self.logger.info(f"\n{'-'*100}\nRymporter summary\n{'-'*100}")
        self.logger.info(f"Total files processed: {self._files_processed}")
        self.logger.info(("[DRY RUN] " if self.dry_run else "") + f"Total files modified: {self._files_modified}")
        if len(self._albums_to_skip) > 0:
            self.logger.warning(
                f"Unmatched albums skipped: {len(self._albums_to_skip)}\n"
                f"{'\n'.join(f'  - \"{skipped_album[1]}\" by {skipped_album[0]}' for skipped_album in self._albums_to_skip)}"
            )
        if len(self._insufficient_metadata) > 0:
            self.logger.warning(
                f"Files with insufficient metadata skipped: {len(self._insufficient_metadata)}\n"
                f"{'\n'.join(f'  - {file}' for file in self._insufficient_metadata)}"
            )
        if len(self._albums_to_skip) == 0 and len(self._insufficient_metadata) == 0:
            self.logger.info("No issues encountered.")
        self.logger.info(f"\n{'-'*100}\nGoing back to main...\n{'-'*100}")

    def match_album(self, file: Path):
        """
        Attempt to match a FLAC file's metadata with RYM album data and update metadata if matched.

        Args:
            file (Path): Path to the FLAC file.
        """
        matched = False

        def _normalize_str(s):
            return s.strip().lower() if s else ""

        try:
            audio = FLAC(file)
            audio_artist = audio.get(self.field_definitions["artist_name"], [""])[0]
            audio_album_title = audio.get(self.field_definitions["album_title"], [""])[0]
            audio_album_id = audio.get(self.field_definitions["album_id"], [""])[0]

            if (audio_artist, audio_album_title) in self._albums_to_skip:
                self.logger.debug("Skipping previously skipped album.")
                return

            if not audio_album_id and not (audio_artist and audio_album_title):
                self.logger.warning("Skipping file due to insufficient metadata.")
                self._insufficient_metadata.append(file)
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
                    self._update_album(rym_album, audio)
                    break

                # Match by normalized artist and album title
                if (_normalize_str(rym_artist) == _normalize_str(audio_artist)
                        and _normalize_str(rym_album_title) == _normalize_str(audio_album_title)):
                    self.logger.debug(f"Matched via artist-title: {rym_album_str}")
                    matched = True
                    self._update_album(rym_album, audio)
                    break

                # Check manual matches
                for input_id, (input_artist, input_title) in self._manual_matches.items():
                    if (rym_album_id == input_id
                            and _normalize_str(input_artist) == _normalize_str(audio_artist)
                            and _normalize_str(input_title) == _normalize_str(audio_album_title)):
                        self.logger.debug(f"Matched via manual input: {rym_album_str}")
                        matched = True
                        self._update_album(rym_album, audio)
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
                                self._update_album(rym_album, audio)
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

    def _update_album(self, rym_album: dict, audio: FLAC):
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
            # Use lowercase field names consistently
            current_values = audio.get(field_name.lower(), [])
            if self._should_update_field(current_values, new_values):
                self.logger.debug(f"  {field_name.upper()} = {', '.join(map(str, new_values))}")
                audio[field_name.lower()] = new_values
                modified = True
                self._files_modified += 1
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
            dict: Mapping of metadata field names (lowercase) to list of values.
        """
        temp_values = {
            self.field_definitions[tag].lower(): []
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
                        temp_values[field_name.lower()].append(val)

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
