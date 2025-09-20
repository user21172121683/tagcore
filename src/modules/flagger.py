import io
import subprocess
from pathlib import Path
from datetime import datetime

from mutagen.flac import FLAC
from PIL import Image

from core.base import BaseProcessor
from constants.flagger import CORRUPTED, OK
from utils.helpers import get_config


class Flagger(BaseProcessor):
    """Flags problematic FLAC files."""

    def __init__(self, **config):
        super().__init__(**config)
        self.tags_to_check = get_config(
            config, "tags_to_check", expected_type=list[str], optional=False
        )
        self.problems_field = get_config(
            config,
            "problems_field",
            expected_type=str,
            optional=True,
            default="PROBLEMS",
        )
        self.timestamp = get_config(
            config, "timestamp", expected_type=str, optional=True, default=None
        )
        self.streamstamp = get_config(
            config, "streamstamp", expected_type=str, optional=True, default=None
        )
        self.cover_target_size = tuple(
            get_config(
                config,
                "cover_target_size",
                expected_type=list[int, int],
                optional=True,
                default=None,
            )
        )
        self.cover_square = get_config(
            config, "cover_square", expected_type=bool, optional=True, default=False
        )
        self.cover_allowed_formats = {
            fmt.lower()
            for fmt in get_config(
                config,
                "cover_allowed_formats",
                expected_type=list[str],
                optional=True,
                default=None,
            )
        }
        self.skip_integrity_check = get_config(
            config,
            "skip_integrity_check",
            expected_type=bool,
            optional=True,
            default=False,
        )

        # Additional stats
        self.stats.modified = {}
        self.stats.modified_already = []

    def pre_process(self):
        self.logger.info("Flagging problematic files...")

    def process_file(self, file: Path):
        with self.lock:
            self.stats.processed.append(file)
        try:
            audio = FLAC(file)
            self.check_integrity(file, audio)
            self.check_tags(file, audio)
            self.check_cover(file, audio)
            self.document_problems(file, audio)
        except Exception:
            with self.lock:
                self.stats.failed.append(file)

    def document_problems(self, file: Path, audio: FLAC):
        problems = self.stats.modified.get(file, [])
        if self.streamstamp and CORRUPTED not in problems and not self.dry_run:
            if audio.get(self.streamstamp, []) != [OK]:
                audio[self.streamstamp] = OK
                audio.save()
        if problems:
            if sorted(problems) == sorted(audio.get(self.problems_field, [])):
                with self.lock:
                    self.stats.modified_already.append(file)
            else:
                if not self.dry_run:
                    audio[self.problems_field] = problems
                    if self.timestamp:
                        audio[self.timestamp] = datetime.now().strftime("%Y-%m-%d")
                    audio.save()
        else:
            if not self.dry_run:
                if audio.get(self.problems_field, []):
                    audio[self.problems_field] = []
                    audio.save()

    def check_integrity(self, file: Path, audio: FLAC):
        if self.skip_integrity_check:
            return

        if self.streamstamp and audio.get(self.streamstamp, []) == [OK]:
            return

        try:
            result = subprocess.run(
                ["flac", "-t", str(file)],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                check=False,
            )
            if result.returncode != 0:
                self.stats.modified.setdefault(file, []).append(CORRUPTED)
        except FileNotFoundError:
            self.logger.critical(
                "The 'flac' command is not found. Please install the FLAC utility."
            )

    def check_tags(self, file: Path, audio: FLAC):
        if not self.tags_to_check:
            return
        for tag in self.tags_to_check:
            if tag not in audio or not audio[tag]:
                self.stats.modified.setdefault(file, []).append(f"NO {tag.upper()}")
        return

    def check_cover(self, file: Path, audio: FLAC):
        pictures = audio.pictures
        if not pictures:
            with self.lock:
                self.stats.modified.setdefault(file, []).append("NO COVER")
            return
        if len(pictures) > 1:
            with self.lock:
                self.stats.modified.setdefault(file, []).append("MULTIPLE COVERS")

        pic = pictures[0]
        image_data = pic.data
        try:
            with Image.open(io.BytesIO(image_data)) as image:
                if (image.size[0] != self.cover_target_size[0]) or (
                    image.size[1] != self.cover_target_size[1]
                ):
                    if self.cover_square:
                        with self.lock:
                            self.stats.modified.setdefault(file, []).append(
                                "COVER NOT SQUARE"
                            )
                    if self.cover_target_size:
                        if (
                            image.size[0] < self.cover_target_size[0]
                            and image.size[1] < self.cover_target_size[1]
                        ):
                            with self.lock:
                                self.stats.modified.setdefault(file, []).append(
                                    "COVER TOO SMALL"
                                )
                        if (
                            image.size[0] > self.cover_target_size[0]
                            and image.size[1] > self.cover_target_size[1]
                        ):
                            with self.lock:
                                self.stats.modified.setdefault(file, []).append(
                                    "COVER TOO LARGE"
                                )
                if image.format.lower() not in self.cover_allowed_formats:
                    with self.lock:
                        self.stats.modified.setdefault(file, []).append(
                            "COVER WRONG FORMAT"
                        )
        except Exception:
            with self.lock:
                self.stats.modified.setdefault(file, []).append("COVER ACCESS ERROR")
        return
