from PIL import Image
import io
import subprocess
from mutagen.flac import FLAC
from utils import index_files, setup_logger, processing_message, returning_message, check_stop
from pathlib import Path
from threading import Event
from datetime import datetime


class Flagger:
    """
    Flags problematic FLAC files.
    """
    
    def __init__(self, **config):
        # Setup logger
        self.logger = setup_logger("flagger", Path(__file__).resolve().parents[1])

        # Stop flag (for safe quitting)
        self.stop_flag: Event = config.get("stop_flag")

        # Load configuration
        self.main_dir = Path(config['main_dir'])
        self.tags_to_check = config['tags_to_check']
        self.problems_field = config.get('problems_field', 'PROBLEMS')
        self.timestamp = config.get('timestamp', True)
        self.cover_target_size = tuple(config.get('cover_target_size', [1000, 1000]))
        self.cover_allowed_formats = config.get('cover_allowed_formats', ['jpg', 'jpeg'])
        self.cover_auto_resize = config.get('cover_auto_resize', False)
        self.cover_auto_delete = config.get('cover_auto_delete', False)
        self.cover_auto_reformat = config.get('cover_auto_reformat', False)
        self.skip_integrity_check = config.get('skip_integrity_check', False)
        self.dry_run = config.get('dry_run', True)

        # Set internal state
        self.files = index_files(directory=self.main_dir, extension='flac', logger=self.logger)
        self._files_processed = 0
        self._files_flagged = 0
        self._files_flagged_already = 0
        self._files_failed = []
    
    def run(self):
        self._files_processed = 0
        self._files_flagged = 0
        for file in self.files:
            if check_stop(self.stop_flag, self.logger):
                break
            problems = []
            self._files_processed += 1
            self.logger.info(processing_message(self._files_processed, len(self.files), file))
            try:
                audio = FLAC(file)
            except Exception as e:
                self.logger.error(f"Failed to load FLAC file {file}: {e}")
                self._files_failed.append(file)
                continue
            problems.extend(self.check_integrity(file))
            problems.extend(self.check_tags(audio))
            problems.extend(self.check_cover(audio))

            if len(problems) > 0:
                self._files_flagged += 1
                if sorted(problems) == sorted(audio.get(self.problems_field, [])):
                    self._files_flagged_already += 1
                    self.logger.info(f"Problems already recorded in {self.problems_field}.")
                else:
                    if not self.dry_run:
                        audio[self.problems_field] = problems
                        if self.timestamp:
                            audio[f"{self.problems_field}_LASTCHECKED"] = datetime.now().strftime('%Y-%m-%d')
                        audio.save()
                        self.logger.info(f"Problems saved to {self.problems_field}.")
                    else:
                        self.logger.info("[DRY RUN] File is left unmodified.")
            else:
                if not self.dry_run:
                    audio[self.problems_field] = []
                    audio.save()
                self.logger.info(f"No problems found.")
        self.logger.info(f"\n{'-'*100}\nFlagger summary\n{'-'*100}")
        self.logger.info(f"Total files processed: {self._files_processed}")
        self.logger.info(("[DRY RUN] " if self.dry_run else "") + f"Total files flagged: {self._files_flagged}, of which already flagged: {self._files_flagged_already}")
        if len(self._files_failed) > 0:
            self.logger.error(f"Failed to process {len(self._files_failed)} files:")
            for failed_file in self._files_failed:
                self.logger.critical(f"  - {failed_file}")
        self.logger.info(returning_message())

    def check_integrity(self, file):
        problems = []
        if self.skip_integrity_check:
            self.logger.info("Skipping integrity check.")
            return problems
        self.logger.info("Checking integrity...")
        try:
            result = subprocess.run(
                ["flac", "-t", file],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True
            )
            if result.returncode == 0:
                self.logger.debug(f"  OK!")
            else:
                self.logger.warning(f"  FAILED: {result.stderr.strip()}")
                problems.append("CORRUPTED STREAM")
            return problems
        except FileNotFoundError:
            self.logger.critical("The 'flac' command is not found. Please install the FLAC utility.")

    def check_tags(self, audio):
        self.logger.info("Checking for empty or missing tags...")
        problems = []
        for tag in self.tags_to_check:
            if tag not in audio or not audio[tag]:
                self.logger.warning(f"  Field {tag.upper()} is missing or empty.")
                problems.append(f"NO {tag.upper()}")
        return problems

    def check_cover(self, audio):
        self.logger.info("Checking cover image...")
        problems = []
        pictures = audio.pictures
        if not pictures:
            self.logger.warning("  No cover image found.")
            problems.append("NO COVER")
            return problems
        if len(pictures) > 1:
            if self.cover_auto_delete:
                self.logger.info(f"  {len(pictures)} cover images found, deleting all but the first one.")
                audio.pictures = [pictures[0]]
                if not self.dry_run:
                    audio.save()
                else:
                    self.logger.info("[DRY RUN] Cover images are left unmodified.")
            else:
                self.logger.warning(f"  {len(pictures)} cover images found, analysing only the first one.")
                problems.append("MULTIPLE COVERS")

        pic = pictures[0]
        image_data = pic.data
        try:
            with Image.open(io.BytesIO(image_data)) as image:
                if (image.size[0] != self.cover_target_size[0]) and (image.size[1] != self.cover_target_size[1]):
                    if image.size[0] != image.size[1]:
                        self.logger.warning(f"  Cover image is not square: {image.size}.")
                        problems.append("COVER NOT SQUARE")
                    if image.size[0] < self.cover_target_size[0] and image.size[1] < self.cover_target_size[1]:
                        self.logger.warning(f"  Cover image is smaller than target size: {image.size} < {self.cover_target_size}.")
                        problems.append("COVER TOO SMALL")
                    if image.size[0] > self.cover_target_size[0] and image.size[1] > self.cover_target_size[1]:
                        if self.cover_auto_resize:
                            self.logger.info(f"Resizing cover image from {image.size} to {self.cover_target_size}.")
                            image = image.resize(self.cover_target_size, Image.ANTIALIAS)
                            output = io.BytesIO()
                            image.save(output, format=pic.mime[6:])
                            pic.data = output.getvalue()
                            if not self.dry_run:
                                audio.save()
                            else:
                                self.logger.info("  [DRY RUN] Cover image is left unmodified.")
                        else:
                            self.logger.warning(f"  Cover image is larger than target size: {image.size} > {self.cover_target_size}.")
                            problems.append("COVER TOO LARGE")
                else:
                    self.logger.debug(f"  Cover image size {image.size} matches target size {self.cover_target_size}.")
                if image.format.lower() not in self.cover_allowed_formats:
                    if self.cover_auto_reformat:
                        self.logger.info(f"Converting cover image format {image.format} to allowed format: {self.cover_allowed_formats[0]}.")
                        output = io.BytesIO()
                        image.save(output, format=self.cover_allowed_formats[0])
                        pic.data = output.getvalue()
                        if not self.dry_run:
                            audio.save()
                        else:
                            self.logger.info("  [DRY RUN] Cover image is left unmodified.")
                    else:
                        self.logger.warning(f"  Cover image format {image.format} is not allowed. Allowed formats: {self.cover_allowed_formats}.")
                        problems.append("COVER WRONG FORMAT")
                else:
                    self.logger.debug(f"  Cover image format {image.format} is allowed.")
        except Exception as e:
            self.logger.warning(f"Could not access cover: {e}")
            problems.append("COVER ACCESS ERROR")
        return problems
