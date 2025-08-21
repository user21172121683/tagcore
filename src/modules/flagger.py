from PIL import Image
import io
import subprocess
from mutagen.flac import FLAC
from utils import *
from pathlib import Path
from datetime import datetime
import time


class Flagger:
    """
    Flags problematic FLAC files.
    """
    
    def __init__(self, **config):
        # Setup logger
        self.logger = setup_logger(
            name="flagger",
            base_dir=Path(__file__).resolve().parents[2],
            console_level=config.get('console_level'),
            file_level=config.get('file_level')
        )

        # Stop flag (for safe quitting)
        self.stop_flag = config.get("stop_flag")

        # Load configuration
        self.main_dir = Path(config.get('main_dir'))
        self.tags_to_check = config.get('tags_to_check', [])
        self.problems_field = config.get('problems_field', 'PROBLEMS')
        self.timestamp = config.get('timestamp', True)
        self.cover_target_size = tuple(config.get('cover_target_size', [1000, 1000]))
        self.cover_allowed_formats = {fmt.lower() for fmt in config.get('cover_allowed_formats', ['jpg', 'jpeg'])}
        self.skip_integrity_check = config.get('skip_integrity_check', False)
        self.dry_run = config.get('dry_run', True)

        # Stats
        self.files = []
        self._files_processed = []
        self._files_flagged = {}
        self._files_flagged_already = []
        self._files_failed = []
    
    def run(self):
        # Start timer
        self.start_time = time.time()

        # Build indices
        self.files = index_files(directory=self.main_dir, extension='flac', logger=self.logger)

        # Process each FLAC file
        for file in self.files:
            if check_stop(self.stop_flag, self.logger):
                break
            self._files_processed.append(file)
            self.logger.info(processing_message(len(self._files_processed), len(self.files), file))
            audio = FLAC(file)
            self.check_problems(file, audio)
            self.document_problems(file, audio)

        # Final summary
        summary_items = [
            (self._files_processed, "Processed {} files."),
            (self._files_flagged, "Flagged {} files."),
            (self._files_flagged_already, "  of which {} were already flagged."),
            (self._files_failed, "Failed to process {} Files.")
        ]

        self.logger.info(
            summary_message(
                name="Flagger",
                summary_items=summary_items,
                dry_run=self.dry_run,
                elapsed=time.time() - self.start_time
            )
        )

    def check_problems(self, file: Path, audio: FLAC):
        self.check_integrity(file)
        self.check_tags(file, audio)
        self.check_cover(file, audio)
    
    def document_problems(self, file: Path, audio: FLAC):
        problems = self._files_flagged.get(file, [])
        if problems:
            if sorted(problems) == sorted(audio.get(self.problems_field, [])):
                self._files_flagged_already.append(file)
                self.logger.info(f"Problems already recorded in {self.problems_field}.")
            else:
                if not self.dry_run:
                    audio[self.problems_field] = problems
                    if self.timestamp:
                        audio[f"{self.problems_field}_LASTCHECKED"] = datetime.now().strftime('%Y-%m-%d')
                    audio.save()
                    self.logger.info(dry_run_message(f"Problems saved to {self.problems_field}."))
        else:
            if not self.dry_run:
                if audio.get(self.problems_field, []):
                    audio[self.problems_field] = []
                    audio.save()
            self.logger.info(f"No problems found.")

    def check_integrity(self, file: Path):
        if self.skip_integrity_check:
            self.logger.debug("Skipping integrity check.")
            return
        self.logger.debug("Checking integrity...")
        try:
            result = subprocess.run(
                ["flac", "-t", str(file)],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True
            )
            if result.returncode == 0:
                self.logger.debug(f"OK!")
            else:
                self.logger.warning(f"FAILED: {result.stderr.strip()}")
                self._files_flagged.setdefault(file, []).append("CORRUPTED STREAM")
            return
        except FileNotFoundError:
            self.logger.critical("The 'flac' command is not found. Please install the FLAC utility.")

    def check_tags(self, file: Path, audio: FLAC):
        self.logger.debug("Checking for empty or missing tags...")
        if not self.tags_to_check:
            return
        for tag in self.tags_to_check:
            if tag not in audio or not audio[tag]:
                self.logger.warning(f"Field {tag.upper()} is missing or empty.")
                self._files_flagged.setdefault(file, []).append(f"NO {tag.upper()}")
        return

    def check_cover(self, file: Path, audio: FLAC):
        self.logger.debug("Checking cover image...")
        pictures = audio.pictures
        if not pictures:
            self.logger.warning("No cover image found.")
            self._files_flagged.setdefault(file, []).append("NO COVER")
            return
        if len(pictures) > 1:
            self.logger.warning(f"{len(pictures)} cover images found, analysing only the first one.")
            self._files_flagged.setdefault(file, []).append("MULTIPLE COVERS")

        pic = pictures[0]
        image_data = pic.data
        try:
            with Image.open(io.BytesIO(image_data)) as image:
                if (image.size[0] != self.cover_target_size[0]) or (image.size[1] != self.cover_target_size[1]):
                    if image.size[0] != image.size[1]:
                        self.logger.warning(f"Cover image is not square: {image.size}.")
                        self._files_flagged.setdefault(file, []).append("COVER NOT SQUARE")
                    if image.size[0] < self.cover_target_size[0] and image.size[1] < self.cover_target_size[1]:
                        self.logger.warning(f"Cover image is smaller than target size: {image.size} < {self.cover_target_size}.")
                        self._files_flagged.setdefault(file, []).append("COVER TOO SMALL")
                    if image.size[0] > self.cover_target_size[0] and image.size[1] > self.cover_target_size[1]:
                        self.logger.warning(f"Cover image is larger than target size: {image.size} > {self.cover_target_size}.")
                        self._files_flagged.setdefault(file, []).append("COVER TOO LARGE")
                else:
                    self.logger.debug(f"Cover image size matches target size: {image.size} = {self.cover_target_size}.")
                if image.format.lower() not in self.cover_allowed_formats:
                    self.logger.warning(f"Cover image format {image.format} is not allowed.")
                    self._files_flagged.setdefault(file, []).append("COVER WRONG FORMAT")
                else:
                    self.logger.debug(f"Cover image format {image.format} is allowed.")
        except Exception as e:
            self.logger.warning(f"Could not access cover: {e}")
            self._files_flagged.setdefault(file, []).append("COVER ACCESS ERROR")
        return
