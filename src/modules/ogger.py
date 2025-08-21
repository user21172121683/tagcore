import subprocess
from utils import *
from pathlib import Path
from mutagen.flac import FLAC
from mutagen.oggvorbis import OggVorbis
import hashlib
import time


class Ogger:
    """
    Keeps a collection of OGG files synced against a main collection of FLAC files.
    """
    def __init__(self, **config):
        # Setup logger
        self.logger = setup_logger(
            name="ogger",
            base_dir=Path(__file__).resolve().parents[2],
            console_level=config.get('console_level'),
            file_level=config.get('file_level')
        )

        # Stop flag (for safe quitting)
        self.stop_flag = config.get("stop_flag")

        # Load configuration
        self.flac_dir = Path(config['main_dir'])
        self.ogg_dir = Path(config['ogg_dir'])
        self.dry_run = config.get('dry_run', True)
        self.quality = config.get('quality', 4)
        self.sample_rate = config.get('sample_rate', 44100)
        self.channels = config.get('channels', 2)
        self.track_id_field = config.get('track_id_field', None)
        self.filename_match = config.get('filename_match', True)
        self.cover_target_size = tuple(config.get('cover_target_size', [600, 600]))
        self.fields_to_copy = config.get('fields_to_copy', [])

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
        self.start_time = float

        # Map quality levels to bitrates
        self.BITRATE_QUALITY_MAP = {
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
            10: 499000
        }

    def run(self):
        # Start timer
        self.start_time = time.time()

        # Build indices and prepare for processing
        self.flac_files = index_files(self.flac_dir, extension='flac', logger=self.logger)
        self.ogg_files = index_files(self.ogg_dir, extension='ogg', logger=self.logger)
        self.ogg_metadata_index = self._build_metadata_index(self.ogg_files)

        # Initialise set for unmatched ogg files
        self._unmatched_ogg_files = set(self.ogg_files)

        # Process each FLAC file and match with OGG files
        for flac_file in self.flac_files:
            if check_stop(self.stop_flag, self.logger):
                break
            self._flac_files_processed.append(flac_file)
            self.logger.info(
                processing_message(
                    current=len(self._flac_files_processed),
                    total=len(self.flac_files),
                    file=flac_file,
                    elapsed=time.time() - self.start_time
                )
            )
            match = self._match_files(flac_file)
            # If no match found, convert FLAC to OGG
            if not match:
                self._convert_file(flac_file)
            # Sync metadata and rename OGG files if necessary
            else:
                if not self._verify_stream(match):
                    self._convert_file(flac_file)
                else:
                    self._sync_metadata(flac_file, match)
            self.logger.info(dry_run_message(self.dry_run, "OGG file is up to date!"))

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
                elapsed=time.time() - self.start_time
            )
        )

    def _build_metadata_index(self, files: list[Path]) -> dict:
        self.logger.info("Building metadata index with hashed fingerprints...")
        index = {}

        for i, file in enumerate(files):
            if check_stop(self.stop_flag, self.logger):
                break
            self.logger.debug(
                processing_message(
                    current=i,
                    total=len(files),
                    file=file,
                    elapsed=time.time() - self.start_time
                )
            )
            try:
                track_id = None
                # Detect file type and extract metadata
                if file.suffix.lower() == ".ogg":
                    tags = dict(OggVorbis(file).items())
                elif file.suffix.lower() == ".flac":
                    tags = dict(FLAC(file).items())
                else:
                    self.logger.warning(f"Unsupported file type: {file}")
                    continue

                # Get track_id field (assuming it's a valid metadata field)
                track_id = tags.get(self.track_id_field, None)
                # Create a hashable "fingerprint" from the metadata
                fingerprint = self._generate_fingerprint(tags)
                # Add both the fingerprint and track_id to the index
                index[file] = (fingerprint, track_id)
                
            except Exception as e:
                self.logger.error(f"Error processing file {file}: {e}")
                if not self.dry_run:
                    try:
                        file.unlink()
                    except Exception as delete_error:
                        self.logger.error(f"Failed to delete corrupt file {file}: {delete_error}")
                self.logger.info(dry_run_message(self.dry_run, f"Deleted corrupt audio file: {file}"))
                files.remove(file)

        return index

    def _generate_fingerprint(self, tags: dict) -> str:
        # Prepare a case-insensitive set of fields to copy
        allowed_fields = {field.upper() for field in self.fields_to_copy}

        # Filter tags to only include those explicitly set in fields_to_copy
        filtered_tags = {
            k: v for k, v in tags.items() if k.upper() in allowed_fields
        }

        # Create a sorted string from the filtered tags (sorted by original key casing)
        metadata_str = ''.join(f"{k}:{';'.join(v)}" for k, v in sorted(filtered_tags.items()))

        # Return a hash of the metadata string (MD5 hash)
        fingerprint = hashlib.md5(metadata_str.encode('utf-8')).hexdigest()
        self.logger.debug(f"Metadata fingerprint: {fingerprint}")
        return fingerprint

    def _match_files(self, flac_file: Path) -> Path | None:
        flac_audio = FLAC(flac_file)
        match = None

        # Generate the fingerprint of the FLAC file metadata
        flac_id = flac_audio.get(self.track_id_field, [None])[0]
        self.logger.debug(f"Track ID: {flac_id}")
        flac_fingerprint = self._generate_fingerprint(flac_audio)
        self.flac_metadata_index[flac_file] = (flac_fingerprint, flac_id)

        self.logger.debug("Trying to find a match...")
        # Match by track ID field if specified
        for ogg_file, (ogg_fingerprint, ogg_track_id) in self.ogg_metadata_index.items():
            if ogg_file in self._unmatched_ogg_files:
                if self.track_id_field and self.flac_metadata_index[flac_file][1] and ogg_track_id and self.flac_metadata_index[flac_file][1] == ogg_track_id:
                    self.logger.debug(f"Track ID match: {ogg_file}")
                    match = ogg_file
                    break
                if flac_fingerprint == ogg_fingerprint:
                    self.logger.debug(f"Fingerprint match: {ogg_file}")
                    match = ogg_file
                    break

        # Match by filename if filename_match is enabled
        if self.filename_match and not match:
            for ogg_file in self.ogg_files:
                if ogg_file in self._unmatched_ogg_files:
                    if flac_file.relative_to(self.flac_dir).with_suffix('') == ogg_file.relative_to(self.ogg_dir).with_suffix(""):
                        self.logger.info(f"Filename match: {ogg_file}")
                        match = ogg_file
                        break
        
        if not match:
            self.logger.info(f"No match found!")
        else:
            self._unmatched_ogg_files.remove(match)
            self._matched_ogg_files.add(match)

        return match

    def _sync_metadata(self, flac_file: Path, ogg_file: Path):
        # Check if OGG metadata matches FLAC
        if self.flac_metadata_index[flac_file][0] != self.ogg_metadata_index[ogg_file][0]:
            self.logger.info(dry_run_message(self.dry_run, "Updating OGG metadata..."))
            if not self.dry_run:
                flac_audio = FLAC(flac_file)
                ogg_audio = OggVorbis(ogg_file)
                for key in ogg_audio.keys():
                    ogg_audio[key] = []
                fields_to_copy = {field.upper() for field in self.fields_to_copy}
                for key, value in flac_audio.items():
                    if key.upper() in fields_to_copy:
                        ogg_audio[key] = value
                ogg_audio.save(ogg_file)
            self._ogg_files_modified.append(ogg_file)
        else:
            self.logger.debug("Metadata verified.")

        # If filename mismatch, rename OGG to match FLAC filename
        if flac_file.relative_to(self.flac_dir).with_suffix('') != ogg_file.relative_to(self.ogg_dir).with_suffix(""):
            self.logger.info(dry_run_message(self.dry_run, "Renaming OGG file..."))
            relative_path = flac_file.relative_to(self.flac_dir).with_suffix('.ogg')
            target_path = self.ogg_dir / relative_path
            if not self.dry_run:
                target_path.parent.mkdir(parents=True, exist_ok=True)
                ogg_file.rename(target_path)
            self._ogg_files_renamed.append(target_path)
        else:
            self.logger.debug("Path verified.")
    
    def _verify_stream(self, ogg_file: Path) -> bool:
        verified = True
        try:
            ogg_audio = OggVorbis(ogg_file)
            if ogg_audio.info.bitrate != self.BITRATE_QUALITY_MAP[self.quality]:
                self.logger.warning(f"Bitrate mismatch: expected {self.BITRATE_QUALITY_MAP[self.quality]}, got {ogg_audio.info.bitrate}")
                verified = False
            else:
                self.logger.debug(f"Bitrate verified.")
            if ogg_audio.info.sample_rate != self.sample_rate:
                self.logger.warning(f"Sample rate mismatch: expected {self.sample_rate}, got {ogg_audio.info.sample_rate}")
                verified = False
            else:
                self.logger.debug(f"Sample rate verified.")
            if ogg_audio.info.channels != self.channels:
                self.logger.warning(f"Channel count mismatch: expected {self.channels}, got {ogg_audio.info.channels}")
                verified = False
            else:
                self.logger.debug(f"Channel count verified.")
            return verified
        except Exception as e:
            self.logger.error(f"Error verifying bitrate: {e}")
            return False

    def _convert_file(self, flac_file: Path):
        self.logger.info(dry_run_message(self.dry_run, "Converting FLAC to OGG..."))
        ogg_file = self.ogg_dir / flac_file.relative_to(self.flac_dir).with_suffix('.ogg')
        if not self.dry_run:
            ogg_file.parent.mkdir(parents=True, exist_ok=True)
            command = [
                "ffmpeg", "-y", "-loglevel", "error",
                "-i", str(flac_file),
                "-map", "0:a",
                "-map_metadata", "-1",
                "-c:a", "libvorbis",
                "-q:a", str(self.quality),
                "-ar", str(self.sample_rate),
                "-ac", str(self.channels),
                str(ogg_file)
            ]
            try:
                subprocess.run(command, check=True)

                # Copy selected metadata
                flac_audio = FLAC(flac_file)
                ogg_audio = OggVorbis(ogg_file)

                # Clear any existing metadata
                for key in ogg_audio.keys():
                    ogg_audio[key] = []

                # Copy only allowed fields
                fields_to_copy = {field.upper() for field in self.fields_to_copy}
                for key, value in flac_audio.items():
                    if key.upper() in fields_to_copy:
                        ogg_audio[key] = value

                ogg_audio.save()

            except subprocess.CalledProcessError as e:
                self.logger.error(f"ffmpeg failed for {flac_file}: {e}")

        self._ogg_files_converted.append(ogg_file)

    def _clean(self):
        self.logger.info("Cleaning up unmatched OGG files and empty directories...")
        for ogg_file in self._unmatched_ogg_files:
            if check_stop(self.stop_flag, self.logger):
                break
            self.logger.info(dry_run_message(self.dry_run, f"Deleting unmatched OGG file: {ogg_file}"))
            if not self.dry_run:
                ogg_file.unlink()
            self._ogg_files_deleted.append(ogg_file)

        # Traverse the directory tree bottom-up
        for dir_path in sorted(self.ogg_dir.rglob('*'), key=lambda p: -len(p.parts)):
            if check_stop(self.stop_flag, self.logger):
                break
            if dir_path.is_dir() and not any(dir_path.iterdir()):
                self.logger.info(dry_run_message(self.dry_run, f"Deleting empty directory: {dir_path}"))
                if not self.dry_run:
                    self._directories_deleted.append(dir_path)
                    dir_path.rmdir()
