import hashlib
import subprocess
import threading
import time
from pathlib import Path
import logging

from mutagen.flac import FLAC
from mutagen.oggvorbis import OggVorbis

from utils import (
    get_config,
    index_files,
    parallel_map,
    check_stop,
    summary_message,
    dry_run_message,
)


class Ogger:
    """Keeps a collection of OGG files synced against a main collection of FLAC files."""

    _BITRATE_QUALITY_MAP = {
        0: 64000,
        1: 80000,
        2: 96000,
        3: 112000,
        4: 128000,
        5: 160000,
        6: 192000,
        7: 224000,
        8: 256000,
        9: 320000,
        10: 499000,
    }

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
        self.flac_dir = Path(
            get_config(config, "main_dir", expected_type=str, optional=False)
        )
        self.ogg_dir = Path(
            get_config(config, "ogg_dir", expected_type=str, optional=False)
        )
        self.quality = get_config(
            config, "quality", expected_type=int, optional=True, default=2
        )
        self.sample_rate = get_config(
            config, "sample_rate", expected_type=int, optional=True, default=44100
        )
        self.channels = get_config(
            config, "channels", expected_type=int, optional=True, default=2
        )
        self.track_id_field = (
            get_config(
                config, "track_id_field", expected_type=str, optional=True, default=None
            )
        ).upper() or None
        self.filename_match = get_config(
            config, "filename_match", expected_type=bool, optional=True, default=True
        )
        self.cover_target_size = tuple(
            get_config(
                config,
                "cover_target_size",
                expected_type=list[int, int],
                optional=True,
                default=[600, 600],
            )
        )
        self.fields_to_preserve = {
            field.upper()
            for field in get_config(
                config,
                "fields_to_preserve",
                expected_type=list[str],
                optional=True,
                default=[],
            )
        }

        # Initialise indices
        self.flac_files = []
        self.flac_metadata_index = {}
        self.ogg_files = []
        self.ogg_metadata_index = {}

        # Stats
        self._unmatched_ogg_files = set()
        self._matched_ogg_files = set()
        self._flac_files_processed = []
        self._ogg_files_converted = []
        self._ogg_files_renamed = []
        self._ogg_files_deleted = []
        self._ogg_files_modified = []
        self._directories_deleted = []

    def run(self):
        # Start timer
        start = time.time()

        # Build indices and prepare for processing
        self.flac_files = index_files(
            self.flac_dir, extension="flac", logger=self.logger
        )
        self.ogg_files = index_files(self.ogg_dir, extension="ogg", logger=self.logger)

        parallel_map(
            func=self._build_ogg_metadata_index,
            items_with_args=self.ogg_files,
            max_workers=self.max_workers,
            stop_flag=self.stop_flag,
            logger=self.logger,
            description="Fingerprinting",
            unit="files",
        )

        # Initialise set for unmatched ogg files
        self._unmatched_ogg_files = set(self.ogg_files)

        parallel_map(
            func=self._process_file,
            items_with_args=self.flac_files,
            max_workers=self.max_workers,
            stop_flag=self.stop_flag,
            logger=self.logger,
            description=dry_run_message(self.dry_run, "Syncing"),
            unit="files",
        )

        # Clean up unmatched OGG files and empty directories
        if not check_stop(self.stop_flag, self.logger):
            self._clean()

        # Final summary
        summary_items = [
            (self._flac_files_processed, "Processed {} FLAC files."),
            (self._ogg_files_converted, "Converted {} FLAC files to OGG."),
            (self._ogg_files_modified, "Modified metadata for {} OGG files."),
            (self._ogg_files_renamed, "Renamed {} OGG files."),
            (self._ogg_files_deleted, "Deleted {} unmatched OGG files."),
            (self._directories_deleted, "Deleted {} empty directories."),
        ]

        self.logger.info(
            summary_message(
                name="Ogger",
                summary_items=summary_items,
                dry_run=self.dry_run,
                elapsed=time.time() - start,
            )
        )

    def _process_file(self, file: Path):
        with self.lock:
            self._flac_files_processed.append(file)
        match = self._match_files(file)
        if not match:
            self._convert_file(file)
        else:
            if not self._verify_stream(match):
                self._convert_file(file)
            else:
                self._sync_metadata(file, match)

    def _build_ogg_metadata_index(self, file: Path) -> dict:
        try:
            track_id = None
            tags = dict(OggVorbis(file).items())

            # Get track_id field (assuming it's a valid metadata field)
            track_id = None
            for key, value in tags.items():
                if key.upper() == self.track_id_field:
                    track_id = value[0]
                    break
            # Create a hashable "fingerprint" from the metadata
            fingerprint = self._generate_fingerprint(tags)
            # Add both the fingerprint and track_id to the index
            with self.lock:
                self.ogg_metadata_index[file] = (fingerprint, track_id)

        except Exception:
            if not self.dry_run:
                try:
                    file.unlink()
                except Exception as delete_error:
                    self.logger.error(
                        f"Failed to delete corrupt file {file}: {delete_error}"
                    )
            with self.lock:
                self.ogg_files.remove(file)

    def _generate_fingerprint(self, tags: dict) -> str:
        # Filter tags to only include those explicitly set in fields_to_preserve
        filtered_tags = {
            k: v for k, v in tags.items() if k.upper() in self.fields_to_preserve
        }

        # Sort keys case-insensitively (but keep original casing)
        metadata_str = "".join(
            f"{k}:{';'.join(v)}"
            for k, v in sorted(filtered_tags.items(), key=lambda item: item[0].upper())
        )

        # Return a hash of the metadata string (MD5 hash)
        return hashlib.md5(metadata_str.encode("utf-8")).hexdigest()

    def _match_files(self, flac_file: Path) -> Path | None:
        flac_audio = FLAC(flac_file)
        flac_id = None
        for key, value in flac_audio.items():
            if key.upper() == self.track_id_field:
                flac_id = value[0]
                break
        flac_fingerprint = self._generate_fingerprint(flac_audio)
        self.flac_metadata_index[flac_file] = (flac_fingerprint, flac_id)

        # Try matching by track ID and/or fingerprint
        for ogg_file, (ogg_fingerprint, ogg_id) in self.ogg_metadata_index.items():
            if ogg_file not in self._unmatched_ogg_files:
                continue

            if self.track_id_field and flac_id and ogg_id and flac_id == ogg_id:
                return self._confirm_match(ogg_file)

            if flac_fingerprint == ogg_fingerprint:
                return self._confirm_match(ogg_file)

        # Fallback: try matching by filename if enabled
        if self.filename_match:
            flac_rel = flac_file.relative_to(self.flac_dir).with_suffix("")
            for ogg_file in list(self._unmatched_ogg_files):
                ogg_rel = ogg_file.relative_to(self.ogg_dir).with_suffix("")
                if flac_rel == ogg_rel:
                    return self._confirm_match(ogg_file)

        return None

    def _confirm_match(self, ogg_file: Path) -> Path:
        with self.lock:
            self._unmatched_ogg_files.remove(ogg_file)
        with self.lock:
            self._matched_ogg_files.add(ogg_file)
        return ogg_file

    def _sync_metadata(self, flac_file: Path, ogg_file: Path):
        # Load FLAC and OGG metadata
        flac_audio = FLAC(flac_file)
        ogg_audio = OggVorbis(ogg_file)

        # Check if relevant metadata differs
        flac_metadata_fingerprint = self.flac_metadata_index[flac_file][0]
        ogg_metadata_fingerprint = self.ogg_metadata_index[ogg_file][0]

        if flac_metadata_fingerprint != ogg_metadata_fingerprint:
            # Clear all fields before copying new metadata
            for field in list(ogg_audio.keys()):
                ogg_audio[field] = []

            # Copy relevant fields from FLAC to OGG
            for field, value in flac_audio.items():
                if field.upper() in self.fields_to_preserve:
                    ogg_audio[field] = value

            if not self.dry_run:
                ogg_audio.save()

            with self.lock:
                self._ogg_files_modified.append(ogg_file)

        # Check if filenames (relative paths) mismatch
        expected_ogg_relative_path = flac_file.relative_to(self.flac_dir).with_suffix(
            ".ogg"
        )
        actual_ogg_relative_path = ogg_file.relative_to(self.ogg_dir)

        if expected_ogg_relative_path != actual_ogg_relative_path:

            target_path = self.ogg_dir / expected_ogg_relative_path

            if not self.dry_run:
                target_path.parent.mkdir(parents=True, exist_ok=True)
                ogg_file.rename(target_path)

            with self.lock:
                self._ogg_files_renamed.append(target_path)

    def _verify_stream(self, ogg_file: Path) -> bool:
        verified = True
        try:
            ogg_audio = OggVorbis(ogg_file)
            if ogg_audio.info.bitrate != self._BITRATE_QUALITY_MAP[self.quality]:
                verified = False
            if ogg_audio.info.sample_rate != self.sample_rate:
                verified = False
            if ogg_audio.info.channels != self.channels:
                verified = False
            return verified
        except Exception as e:
            self.logger.error(f"Error verifying bitrate: {e}")
            return False

    def _convert_file(self, flac_file: Path):
        ogg_file = self.ogg_dir / flac_file.relative_to(self.flac_dir).with_suffix(
            ".ogg"
        )
        if not self.dry_run:
            ogg_file.parent.mkdir(parents=True, exist_ok=True)
            command = [
                "ffmpeg",
                "-y",
                "-loglevel",
                "error",
                "-i",
                str(flac_file),
                "-map",
                "0:a",
                "-map_metadata",
                "-1",
                "-c:a",
                "libvorbis",
                "-q:a",
                str(self.quality),
                "-ar",
                str(self.sample_rate),
                "-ac",
                str(self.channels),
                str(ogg_file),
            ]
            try:
                subprocess.run(command, check=True)

                try:
                    flac_audio = FLAC(flac_file)
                    ogg_audio = OggVorbis(ogg_file)

                    # Clear any existing metadata
                    for key in ogg_audio.keys():
                        ogg_audio[key] = []

                    # Copy only allowed fields
                    for key, value in flac_audio.items():
                        if key.upper() in self.fields_to_preserve:
                            ogg_audio[key] = value

                    ogg_audio.save()

                except Exception as meta_error:
                    self.logger.error(
                        f"Failed to write metadata for {ogg_file}: {meta_error}"
                    )

            except subprocess.CalledProcessError as e:
                self.logger.error(f"ffmpeg failed for {flac_file}: {e}")

        self._ogg_files_converted.append(ogg_file)

    def _clean(self):
        self.logger.info("Cleaning up unmatched OGG files and empty directories...")
        for ogg_file in self._unmatched_ogg_files:
            if check_stop(self.stop_flag, self.logger):
                break
            if not self.dry_run:
                ogg_file.unlink()
            self._ogg_files_deleted.append(ogg_file)

        # Traverse the directory tree bottom-up
        for dir_path in sorted(self.ogg_dir.rglob("*"), key=lambda p: -len(p.parts)):
            if check_stop(self.stop_flag, self.logger):
                break
            if dir_path.is_dir() and not any(dir_path.iterdir()):
                if not self.dry_run:
                    self._directories_deleted.append(dir_path)
                    dir_path.rmdir()
