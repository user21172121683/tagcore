from pathlib import Path
import threading
import time
from collections import defaultdict
import logging
from utils import (
    get_config,
    index_files,
    dry_run_message,
    summary_message
)


class Lister:
    """
    Creates local playlists for folders of FLAC files.
    """

    def __init__(self, **config):
        # Setup technical stuff
        self.logger = get_config(
            config, "logger", expected_type=logging.Logger, optional=True, default=None)

        # Load configuration
        self.dry_run = get_config(
            config, "dry_run", expected_type=bool, optional=True, default=True)
        self.main_dir = Path(get_config(
            config, "main_dir", expected_type=str, optional=False))
        self.filename = get_config(
            config, "filename", expected_type=str, optional=True, default="album")

        # Initialise indices
        self.files = []
        self.folders = defaultdict(list)

        # Stats
        self.playlists_processed = []
        self.playlists_written = []

    def run(self):
        # Start timer
        start = time.time()

        # Build indices
        self.files = index_files(
            directory=self.main_dir, extension='flac', logger=self.logger)
        for file in self.files:
            folder = file.parent
            filename = file.name
            self.folders[folder].append(filename)
        self.logger.info(f"Found {len(self.folders)} folders.")

        # Build playlist files
        for folder, tracks in self.folders.items():
            self.process_folder(folder, tracks)

        # Final summary
        summary_items = [
            (self.playlists_processed, "Processed {} playlists."),
            (self.playlists_written, "Wrote or updated {} playlists.")
        ]

        self.logger.info(
            summary_message(
                name="Flagger",
                summary_items=summary_items,
                dry_run=self.dry_run,
                elapsed=time.time() - start
            )
        )

    def process_folder(self, folder, tracks):
        self.playlists_processed.append(folder)

        playlist_filename = folder / f"{self.filename}.m3u8"

        # Generate new playlist content
        new_content = "#EXTM3U\n" + "\n".join(track for track in sorted(tracks)) + "\n"

        # Check if the playlist file already exists and compare contents
        if playlist_filename.exists():
            with playlist_filename.open("r", encoding="utf-8") as f:
                existing_content = f.read()
            if existing_content == new_content:
                return
        if not self.dry_run:
            with playlist_filename.open("w", encoding="utf-8") as f:
                f.write(new_content)
        self.playlists_written.append(folder)
