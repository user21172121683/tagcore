from pathlib import Path

from mutagen.flac import FLAC

from core.base import BaseProcessor
from utils.helpers import get_config, UpperFLAC


class Stamper(BaseProcessor):
    """Applies static tags and re-maps fields in FLAC files."""

    def __init__(self, **config):
        super().__init__(**config)

        # Additional configuration
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

    def pre_process(self):
        self.logger.info("Stamping files...")

    def process_file(self, file: Path):
        if not self.stamps and not self.map:
            return
        with self.lock:
            self.stats.processed.append(file)
        try:
            audio = UpperFLAC(FLAC(file))
        except Exception as e:
            self.logger.error(f"Failed to load FLAC file {file}: {e}")
            with self.lock:
                self.stats.failed.append(file)
            return

        changed = False

        if self.map_tags(audio):
            changed = True

        if self.stamp_tags(audio):
            changed = True

        if changed:
            with self.lock:
                self.stats.modified.append(file)
            if not self.dry_run:
                try:
                    audio.save()
                except Exception as e:
                    self.logger.error(f"{file}: Failed to save stamped metadata: {e}")
                    with self.lock:
                        self.stats.failed.append(file)

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
