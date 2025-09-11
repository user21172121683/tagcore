import threading
import time
import logging
from pathlib import Path

from mutagen.flac import FLAC

from utils import (
    get_config,
    index_files,
    parallel_map,
    summary_message,
    dry_run_message,
    UpperFLAC,
)


class Stamper:
    """Applies static tags and re-maps fields in FLAC files."""

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
            get_config(
                config, "main_dir", expected_type=str, optional=False, default=None
            )
        )
        self.stamps = {
            k.upper(): v
            for k, v in get_config(
                config,
                "stamps",
                expected_type=dict[str, str],
                optional=True,
                default={},
            ).items()
        }
        self.map = {
            k.upper(): v.upper()
            for k, v in get_config(
                config, "map", expected_type=dict[str, str], optional=True, default={}
            ).items()
        }
        self.clear_source = get_config(
            config, "clear_source", expected_type=bool, optional=True, default=False
        )

        # Initialise indices
        self.files = []
        self._files_processed = []
        self._files_modified = []
        self._files_failed = []

    def run(self):
        # Start timer
        start = time.time()

        # Build index
        self.files = index_files(
            directory=self.main_dir, extension="flac", logger=self.logger
        )

        # Process FLAC files in parallel
        parallel_map(
            func=self.process_file,
            items_with_args=self.files,
            max_workers=self.max_workers,
            stop_flag=self.stop_flag,
            logger=self.logger,
            description=dry_run_message(self.dry_run, "Stamping"),
            unit="files",
        )

        # Final summary
        summary_items = [
            (self._files_processed, "Processed {} files."),
            (self._files_modified, "Modified {} files."),
            (self._files_failed, "Failed to process {} files."),
        ]

        self.logger.info(
            summary_message(
                name="Flagger",
                summary_items=summary_items,
                dry_run=self.dry_run,
                elapsed=time.time() - start,
            )
        )

    def process_file(self, file: Path):
        if not self.stamps and not self.map:
            return
        with self.lock:
            self._files_processed.append(file)
        try:
            audio = UpperFLAC(FLAC(file))
        except Exception as e:
            self.logger.error(f"Failed to load FLAC file {file}: {e}")
            with self.lock:
                self._files_failed.append(file)
            return

        changed = False

        if self.map_tags(audio):
            changed = True

        if self.stamp_tags(audio):
            changed = True

        if changed:
            with self.lock:
                self._files_modified.append(file)
            if not self.dry_run:
                try:
                    audio.save()
                except Exception as e:
                    self.logger.error(f"{file}: Failed to save stamped metadata: {e}")
                    with self.lock:
                        self._files_failed.append(file)

    def map_tags(self, audio):
        changed = False
        for dest_key, source_key in self.map.items():
            source_values = audio.get(source_key, [])

            if source_values:
                if audio.get(dest_key, []) != source_values:
                    audio[dest_key] = source_values
                    changed = True
                if self.clear_source and source_key in audio:
                    audio[source_key] = []
                    changed = True
        return changed

    def stamp_tags(self, audio):
        changed = False
        for field, value in self.stamps.items():
            desired_values = value if isinstance(value, list) else [value]
            current_values = audio.get(field, [])
            if sorted(current_values) != sorted(desired_values):
                try:
                    audio[field] = desired_values
                    changed = True
                except Exception as e:
                    self.logger.warning(f"Failed to update {field}: {e}")
        return changed
