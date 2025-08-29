from utils import *
from mutagen.flac import FLAC
import time

class Stamper:
    """
    Applies static metadata tags to FLAC files.
    """

    def __init__(self, **config):
        # Setup logger
        self.logger = config.get('logger')

        # Stop flag (for safe quitting)
        self.stop_flag = config.get("stop_flag")

        # Load configuration
        self.main_dir = Path(config.get('main_dir'))
        if not isinstance(self.main_dir, Path):
            raise TypeError("Expected 'main_dir' to be a path-like object.")

        self.dry_run = config.get('dry_run', True)
        if not isinstance(self.dry_run, bool):
            raise TypeError("'dry_run' must be a boolean.")

        stamps = config.get('stamps', {})
        if not isinstance(stamps, dict):
            raise TypeError("'stamps' must be a dictionary.")
        self.stamps = {k.upper(): v for k, v in stamps.items()}

        # Stats
        self.files = []
        self._files_processed = []
        self._files_stamped = []
    
    def run(self):
        # Start timer
        self.start_time = time.time()

        # Build index
        self.files = index_files(directory=self.main_dir, extension='flac', logger=self.logger)

        # Process each FLAC file
        for file in self.files:
            if check_stop(self.stop_flag, self.logger):
                break
            self._files_processed.append(file)
            self.logger.info(processing_message(len(self._files_processed), len(self.files), file))
            try:
                audio = FLAC(file)
            except Exception as e:
                self.logger.error(f"Failed to load FLAC file {file}: {e}")
                continue
            self.stamp_file(file, audio)
        
        # Final summary
        summary_items = [
            (self._files_processed, "Processed {} files."),
            (self._files_stamped, "Stamped {} files.")
        ]

        self.logger.info(
            summary_message(
                name="Flagger",
                summary_items=summary_items,
                dry_run=self.dry_run,
                elapsed=time.time() - self.start_time
            )
        )

    def stamp_file(self, file: Path, audio: FLAC):
        if not self.stamps or self.dry_run:
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

            # Sort both for comparison (order doesn't matter)
            if sorted(current_values) != sorted(desired_values):
                self.logger.info(dry_run_message(self.dry_run, f"Updating {real_key.upper()}: current = {current_values}, desired = {desired_values}"))
                if not self.dry_run:
                    try:
                        audio[real_key] = desired_values
                        changed = True
                    except Exception as e:
                        self.logger.warning(f"Failed to update {real_key}: {e}")
            else:
                self.logger.debug(f"{real_key.upper()} already matches desired values.")

        if changed:
            self._files_stamped.append(file)
            if not self.dry_run:
                try:
                    audio.save()
                except Exception as e:
                    self.logger.error(f"Failed to save stamped metadata for {file.name}: {e}")
