import threading
import time
import traceback
from pathlib import Path
import logging

from mutagen.flac import FLAC

from modules._rymparser import Rymparser
from utils import (
    get_config,
    index_files,
    parallel_map,
    DATA_DIR,
    summary_message,
    dry_run_message,
)


class Rymporter:
    """Updates FLAC files with metadata from RYM collection."""

    def __init__(self, **config):
        # Setup technical stuff
        self.logger = get_config(
            config, "logger", expected_type=logging.Logger, optional=True, default=None
        )
        self.max_workers = get_config(
            config, "max_workers", expected_type=int, optional=True, default=4
        )
        self.stop_flag = get_config(
            config,
            "stop_flag",
            expected_type=threading.Event,
            optional=True,
            default=None,
        )
        self.lock = threading.Lock()

        # Load configuration
        self.dry_run = get_config(
            config, "dry_run", expected_type=bool, optional=True, default=True
        )
        self.main_dir = Path(
            get_config(config, "main_dir", expected_type=str, optional=False)
        )
        self.field_definitions = get_config(
            config, "field_definitions", expected_type=dict[str, str], optional=False
        )
        self.fields_to_modify = get_config(
            config, "fields_to_modify", expected_type=dict[str, bool], optional=False
        )
        self.collection = DATA_DIR / get_config(
            config, "collection", expected_type=str, optional=False
        )

        # Initialise indices
        self.files = []
        self.rym_albums = []
        self._files_processed = []
        self._manual_matches = {}
        self._albums_to_skip = []
        self._files_insufficient_metadata = []
        self._files_modified = []
        self._files_failed = {}

    def run(self):
        """
        Parse the RYM collection HTML and update FLAC files with matched metadata.
        """
        # Start timer
        start = time.time()

        # Build indices
        self.rym_albums = self.parse_collection_html()
        self.files = index_files(
            directory=self.main_dir, extension="flac", logger=self.logger
        )

        if self.rym_albums and self.files:
            # Try to find a match for each FLAC file
            self.logger.info("Matching files with RYM albums...")
            parallel_map(
                func=self.match_album,
                items_with_args=self.files,
                max_workers=self.max_workers,
                stop_flag=self.stop_flag,
                logger=self.logger,
                description=dry_run_message(self.dry_run, "Matching"),
                unit="files",
            )

        # Final summary
        summary_items = [
            (self._files_processed, "Processed {} FLAC files."),
            (self._files_modified, "Modified {} FLAC files."),
            (self._albums_to_skip, "Skipped {} unmatched albums."),
            (
                self._files_insufficient_metadata,
                "Skipped {} FLAC files with insufficient metadata.",
            ),
        ]
        self.logger.info(
            summary_message(
                name="Rymporter",
                summary_items=summary_items,
                dry_run=self.dry_run,
                elapsed=time.time() - start,
            )
        )

    def parse_collection_html(self):
        parser = Rymparser()
        self.logger.info(f"Parsing collection in {self.collection}...")
        try:
            with self.collection.open("r", encoding="utf-8") as f:
                collection_html = f.read()
            parser.feed(collection_html)

            # TODO: fix this hacky way to skip the first album
            albums = parser.albums[1:]

            if not albums:
                self.logger.info("No albums found in the collection.")
            else:
                self.logger.info(f"Parsed {len(albums)} albums from the collection.")

            return albums

        except FileNotFoundError:
            self.logger.error(f"Collection HTML file {self.collection} not found.")
        except Exception as e:
            self.logger.error(f"Unexpected error parsing collection HTML: {e}")
            self.logger.error("Traceback:\n" + traceback.format_exc())

    def match_album(self, file: Path):
        matched = False
        try:
            audio = FLAC(file)
            audio_artist = audio.get(self.field_definitions["artist_name"], [""])[0]
            audio_album_title = audio.get(self.field_definitions["album_title"], [""])[
                0
            ]
            audio_album_id = audio.get(self.field_definitions["album_id"], [""])[0]

            # Check if file has sufficient metadata for matching
            if not audio_album_id and not (audio_artist and audio_album_title):
                with self.lock:
                    self._files_insufficient_metadata.append(file)
                return

            # Check if album has been skipped beforehand
            if (audio_artist, audio_album_title) in self._albums_to_skip:
                return

            # Loop through all RYM albums
            for i, rym_album in enumerate(self.rym_albums):
                rym_album_id = rym_album["album"]["album_id"]
                rym_album_title = rym_album["album"]["album_title"]
                rym_artist = rym_album["artist"][0]["artist_name"]

                # Match by ID
                if rym_album_id == audio_album_id:
                    matched = True
                    self._update_album(rym_album, audio, file)
                    break

                # Match by normalised artist and album title
                if rym_artist == audio_artist and rym_album_title == audio_album_title:
                    matched = True
                    self._update_album(rym_album, audio, file)
                    break

                # No match found after last album in list
                if i == len(self.rym_albums) - 1 and not matched:
                    with self.lock:
                        self._albums_to_skip.append((audio_artist, audio_album_title))
                    continue

        except Exception as e:
            with self.lock:
                self._files_failed[file] = str(e)
            self.logger.error(f"Error processing {file}: {type(e).__name__}: {e}")

    def _update_album(self, rym_album: dict, audio: FLAC, file: Path):
        new_metadata = self._build_new_metadata_dict(rym_album)

        modified = False
        for field_name, new_values in new_metadata.items():
            # Use uppercase field names consistently
            current_values = audio.get(field_name.upper(), [])
            if self._should_update_field(current_values, new_values):
                audio[field_name.upper()] = new_values
                modified = True
                with self.lock:
                    self._files_modified.append(file)

        if modified:
            if not self.dry_run:
                try:
                    audio.save()
                except Exception as e:
                    with self.lock:
                        self._files_failed[file] = str(e)
                    self.logger.error(f"Error saving file: {e}")

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
                            (k, v) for k, v in item.items() if v not in (None, "")
                        )
                    elif isinstance(item, str):
                        tag_value_pairs.append((tag, item))
            elif isinstance(value, dict):
                tag_value_pairs.extend(
                    (k, v) for k, v in value.items() if v not in (None, "")
                )
            else:
                if value not in (None, ""):
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
