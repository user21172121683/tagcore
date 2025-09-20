from collections import defaultdict

from core.base import BaseProcessor
from utils.helpers import get_config, parallel_map
from utils.formatting import dry_run_message


class Lister(BaseProcessor):
    """Creates local playlists for folders of FLAC files."""

    def __init__(self, **config):
        super().__init__(**config)

        # Additional Configuration
        self.filename = get_config(
            config, "filename", expected_type=str, optional=True, default="album"
        )

        # Initialise indices
        self.folders = defaultdict(list)

        # Stats
        self.playlists_processed = []
        self.playlists_written = []

    def post_index(self):
        for file in self.files:
            folder = file.parent
            filename = file.name
            self.folders[folder].append(filename)
        self.logger.info(f"Found {len(self.folders)} folders.")

    def pre_process(self):
        self.logger.info("Populating playlists...")

    def process_file(self, file):
        pass

    def process_folder(self, folder):
        with self.lock:
            self.stats.processed.append(folder)

        playlist_filename = folder / f"{self.filename}.m3u8"

        # Generate new playlist content
        new_content = (
            "#EXTM3U\n"
            + "\n".join(track for track in sorted(self.folders[folder]))
            + "\n"
        )

        # Check if the playlist file already exists and compare contents
        if playlist_filename.exists():
            with playlist_filename.open("r", encoding="utf-8") as file:
                existing_content = file.read()
            if existing_content == new_content:
                return
        else:
            try:
                if not self.dry_run:
                    with playlist_filename.open("w", encoding="utf-8") as file:
                        file.write(new_content)
                with self.lock:
                    self.stats.modified.append(folder)
            except Exception as e:
                self.logger.exception(f"Writing playlist failed for {file.name}: {e}")
                self.stats.failed.append(folder)

    def process_all(self):
        parallel_map(
            func=self.process_folder,
            items_with_args=self.folders,
            max_workers=self.max_workers,
            stop_flag=self.stop_flag,
            logger=self.logger,
            description=dry_run_message(self.dry_run, "Processing"),
            unit="files",
        )
