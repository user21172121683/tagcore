from mutagen.flac import FLAC
import traceback
from utils import *
from pathlib import Path
from rymparser import Rymparser
import time


class Rymporter:
    """
    Parses RYM collection HTML and updates FLAC files with matched metadata.
    """

    def __init__(self, **config):
        # Setup logger
        self.logger = config.get('logger')

        # Stop flag
        self.stop_flag = config.get("stop_flag")

        # Load configuration
        self.main_dir = Path(config["main_dir"])
        self.field_definitions = config["field_definitions"]
        self.collection_html_file = Path(__file__).resolve().parents[2] / "data" / config.get("collection_html")
        self.fields_to_modify = config["fields_to_modify"]
        self.dry_run = config.get("dry_run", True)
        self.auto_skip = config.get("auto_skip", False)

        # Initialise indices
        self.files = []
        self.rym_albums = []

        # Stats
        self._files_processed = []
        self._manual_matches = {}
        self._albums_to_skip = []
        self._files_insufficient_metadata = []
        self._files_modified = []
        self.start_time = float

    def run(self):
        """
        Parse the RYM collection HTML and update FLAC files with matched metadata.
        Raises RuntimeError on fatal errors.
        """
        # Start timer
        self.start_time = time.time()

        # Build indices
        self.rym_albums = self.parse_collection_html()
        self.files = index_files(directory=self.main_dir, extension="flac", logger=self.logger)

        # Try to find a match for each FLAC file
        for file in self.files:
            if check_stop(self.stop_flag, self.logger):
                break
            self._files_processed.append(file)
            self.logger.info(
                processing_message(
                    current=len(self._files_processed),
                    total=len(self.files),
                    file=file,
                    elapsed=time.time() - self.start_time
                )
            )
            self.match_album(file)

        # Final summary
        summary_items = [
            (self._files_processed, "Processed {} FLAC files."),
            (self._files_modified, "Modified {} FLAC files."),
            (self._albums_to_skip, "Skipped {} unmatched albums."),
            (self._files_insufficient_metadata, "Skipped {} FLAC files with insufficient metadata.")
        ]

        self.logger.info(
            summary_message(
                name="Rymporter",
                summary_items=summary_items,
                dry_run=self.dry_run,
                elapsed=time.time() - self.start_time
            )
        )

    def parse_collection_html(self):
        parser = Rymparser()
        self.logger.info(f"Parsing collection HTML in {self.collection_html_file}...")
        try:
            with self.collection_html_file.open("r", encoding="utf-8") as f:
                collection_html = f.read()
            parser.feed(collection_html)

            # TODO: fix this hacky way to skip the first album
            albums = parser.albums[1:]

            if not albums:
                self.logger.info("No albums found in the HTML content.")
            else:
                self.logger.info(f"Parsed {len(albums)} albums from the HTML content.")

            return albums

        except FileNotFoundError:
            self.logger.error(f"Collection HTML file '{self.collection_html_file}' not found.")
        except Exception as e:
            self.logger.error(f"Unexpected error parsing collection HTML: {e}")
            self.logger.error("Traceback:\n" + traceback.format_exc())

    def match_album(self, file: Path):
        matched = False
        try:
            audio = FLAC(file)
            audio_artist = audio.get(self.field_definitions["artist_name"], [""])[0]
            audio_album_title = audio.get(self.field_definitions["album_title"], [""])[0]
            audio_album_id = audio.get(self.field_definitions["album_id"], [""])[0]

            # Check if file has sufficient metadata for matching
            if not audio_album_id and not (audio_artist and audio_album_title):
                self.logger.warning("Skipping file due to insufficient metadata.")
                self._files_insufficient_metadata.append(file)
                return

            # Check if album has been skipped beforehand
            if (audio_artist, audio_album_title) in self._albums_to_skip:
                self.logger.debug("Skipping previously skipped album.")
                return

            # Loop through all RYM albums
            for i, rym_album in enumerate(self.rym_albums):
                rym_album_id = rym_album["album"]["album_id"]
                rym_album_title = rym_album["album"]["album_title"]
                rym_artist = rym_album["artist"][0]["artist_name"]

                # String for match message
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

                # Match by normalised artist and album title
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
        self.logger.debug("Checking if tags need to be updated...")
        new_metadata = self._build_new_metadata_dict(rym_album)

        modified = False
        for field_name, new_values in new_metadata.items():
            # Use uppercase field names consistently
            current_values = audio.get(field_name.upper(), [])
            if self._should_update_field(current_values, new_values):
                self.logger.debug(f"{field_name.upper()} = {', '.join(map(str, new_values))}")
                audio[field_name.upper()] = new_values
                modified = True
                self._files_modified.append(file)
            else:
                self.logger.debug(f"{field_name.upper()} is unchanged. Skipping update.")

        if modified:
            if not self.dry_run:
                try:
                    audio.save()
                    self.logger.info(dry_run_message("File successfully updated with RYM data."))
                except Exception as e:
                    self.logger.error(f"Error saving file: {e}")
        else:
            self.logger.info("No changes detected.")

    def _build_new_metadata_dict(self, rym_album: dict) -> dict:
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
        current_values_str = [str(v) for v in current_values]
        new_values_str = [str(v) for v in new_values]
        return current_values_str != new_values_str
