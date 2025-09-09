from utils import *
from mutagen.flac import FLAC
import time
import threading


class Stamper:
    """
    Applies static metadata tags to FLAC files.
    """

    def __init__(self, **config):
        # Setup technical stuff
        self.logger = get_config(config, "logger", expected_type=logging.Logger, optional=True, default=None)
        self.max_workers = get_config(config, "max_workers", expected_type=int, optional=True, default=4)
        self.stop_flag = get_config(config, "stop_flag", expected_type=Event, optional=True, default=None)
        self.lock = threading.Lock()

        # Load configuration
        self.dry_run = get_config(config,"dry_run", expected_type=bool, optional=True, default=True)
        self.main_dir = Path(get_config(config, "main_dir", expected_type=str, optional=False, default=None))
        self.stamps = {k.upper(): v for k, v in get_config(config, "stamps", expected_type=dict[str, str], optional=True, default={})}

        # Initialise indices
        self.files = []
        self._files_processed = []
        self._files_stamped = []
        self._files_failed = []
    
    def run(self):
        # Start timer
        start = time.time()

        # Build index
        self.files = index_files(directory=self.main_dir, extension="flac", logger=self.logger)

        # Process FLAC files in parallel
        parallel_map(
            func=self.stamp_file,
            items_with_args=self.files,
            max_workers=self.max_workers,
            stop_flag=self.stop_flag,
            logger=self.logger,
            description="Stamping",
            unit="files"
        )
        
        # Final summary
        summary_items = [
            (self._files_processed, "Processed {} files."),
            (self._files_stamped, "Stamped {} files."),
            (self._files_failed, "Failed to process {} files.")
        ]

        self.logger.info(
            summary_message(
                name="Flagger",
                summary_items=summary_items,
                dry_run=self.dry_run,
                elapsed=time.time() - start
            )
        )

    def stamp_file(self, file: Path):
        if not self.stamps:
            return
        with self.lock:
            self._files_processed.append(file)
        try:
            audio = FLAC(file)
        except Exception as e:
            self.logger.error(f"Failed to load FLAC file {file}: {e}")
            with self.lock:
                self._files_failed.append(file)
            return

        # Map existing tags to upper-case keys for case-insensitive lookup
        existing_keys = {k.upper(): k for k in audio.keys()}
        changed = False

        for tag, value in self.stamps.items():
            tag_upper = tag.upper()
            real_key = existing_keys.get(tag_upper, tag_upper)

            # Normalize configured value to a list
            desired_values = value if isinstance(value, list) else [value]

            # Get current tag values (empty if not present)
            current_values = audio.get(real_key, [])

            # Sort both for comparison (order doesn"t matter)
            if sorted(current_values) != sorted(desired_values):
                try:
                    audio[real_key] = desired_values
                    changed = True
                except Exception as e:
                    self.logger.warning(f"{file}: Failed to update {real_key}: {e}")
                    with self.lock:
                        self._files_failed.append(file)

        if changed:
            with self.lock:
                self._files_stamped.append(file)
            if not self.dry_run:
                try:
                    audio.save()
                except Exception as e:
                    self.logger.error(f"{file}: Failed to save stamped metadata: {e}")
                    with self.lock:
                        self._files_failed.append(file)
