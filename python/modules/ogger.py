import subprocess
from utils import index_files, setup_logger, processing_message, returning_message, check_stop
from pathlib import Path
from mutagen.flac import FLAC
from mutagen.oggvorbis import OggVorbis


class Ogger:
    def __init__(self, **config):
        # Setup logger
        self.logger = setup_logger("ogger", Path(__file__).resolve().parents[1])

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

        # Initialise indices
        self.flac_files = {}
        self.flac_metadata_index = {}
        self.ogg_files = {}
        self.ogg_metadata_index = {}

        # Stats
        self._matched_ogg_paths = set()
        self._flac_files_processed = 0
        self._ogg_files_converted = 0
        self._ogg_files_renamed = 0
        self._ogg_files_deleted = 0

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
        }

    def run(self):
        # Build indices and prepare for processing
        self.flac_files = index_files(self.flac_dir, extension='flac', logger=self.logger)
        self.flac_metadata_index = self._build_metadata_index(self.flac_files)
        self.ogg_files = index_files(self.ogg_dir, extension='ogg', logger=self.logger)
        self.ogg_metadata_index = self._build_metadata_index(self.ogg_files)

        # Process each FLAC file and match with OGG files
        self._flac_files_processed = 0
        for flac_file, flac_metadata in self.flac_metadata_index.items():
            if check_stop(self.stop_flag, self.logger):
                break
            self._flac_files_processed += 1
            self.logger.info(processing_message(self._flac_files_processed, len(self.flac_files), flac_file))
            match = self._match_files(flac_file, flac_metadata)
            # If no match found, convert FLAC to OGG
            if not match:
                ogg_output = self.ogg_dir / flac_file.relative_to(self.flac_dir).with_suffix('.ogg')
                ogg_output.parent.mkdir(parents=True, exist_ok=True)
                if not self.dry_run:
                    self._convert_file(str(flac_file), str(ogg_output))
                self._ogg_files_converted += 1
            # Sync metadata and rename OGG files if necessary
            else:
                if not self._verify_stream(match):
                    ogg_output = self.ogg_dir / flac_file.relative_to(self.flac_dir).with_suffix('.ogg')
                    ogg_output.parent.mkdir(parents=True, exist_ok=True)
                    if not self.dry_run:
                        self._convert_file(str(flac_file), str(ogg_output))
                    self._ogg_files_converted += 1
                else:
                    self._sync_metadata(flac_file, match)
            self.logger.info(f"File is up to date!")

        # Clean up unmatched OGG files and empty directories
        if not check_stop(self.stop_flag, self.logger):
            self._clean()

        # Final summary
        self.logger.info(f"\n{'-'*100}\nOgger summary\n{'-'*100}")
        self.logger.info(f"Processed {self._flac_files_processed} FLAC files.")
        if self._ogg_files_converted > 0:
            self.logger.info(f"Converted {self._ogg_files_converted} FLAC files to OGG.")
        if self._ogg_files_renamed > 0:
            self.logger.info(f"Renamed {self._ogg_files_renamed} OGG files to match FLAC structure.")
        if self._ogg_files_deleted > 0:
            self.logger.info(f"Deleted {self._ogg_files_deleted} unmatched OGG files.")
        self.logger.info(returning_message())

    def _build_metadata_index(self, files):
        self.logger.info("Building metadata index...")
        index = {}
        for file in files:
            if check_stop(self.stop_flag, self.logger):
                break
            try:
                if file.suffix.lower() == ".ogg":
                    tags = dict(OggVorbis(file).items())
                elif file.suffix.lower() == ".flac":
                    tags = dict(FLAC(file).items())
                else:
                    self.logger.warning(f"Unsupported file type: {file}")
                    continue
                fingerprint = tuple(sorted({k.upper(): tuple(sorted(v)) for k, v in tags.items()}.items()))
                index[file] = fingerprint
            except Exception as e:
                self.logger.error(f"Corrupt audio file detected: {file} - {e}")
                if not self.dry_run:
                    try:
                        file.unlink()
                        self.logger.warning(f"Deleted corrupt audio file: {file}")
                    except Exception as delete_error:
                        self.logger.error(f"Failed to delete corrupt file {file}: {delete_error}")
                else:
                    self.logger.warning(f"[DRY RUN] Would delete corrupt audio file: {file}")
                files.remove(file)
        return index

    def _match_files(self, flac_file, flac_metadata):
        flac_audio = FLAC(flac_file)
        matched = False
        for ogg_file, ogg_metadata in self.ogg_metadata_index.items():
            # Skip if already matched
            if ogg_file in self._matched_ogg_paths:
                continue
            ogg_audio = OggVorbis(ogg_file)

            # Match by track ID field if specified
            if self.track_id_field and flac_audio.get(self.track_id_field) and flac_audio.get(self.track_id_field) == ogg_audio.get(self.track_id_field):
                self.logger.info(f"Matched by {self.track_id_field}: {ogg_file}")
                matched = True

            # Match by exact metadata
            elif flac_metadata == ogg_metadata:
                self.logger.info(f"Exact metadata match: {ogg_file}")
                matched = True

            # Match by path if filename_match is enabled in config
            elif self.filename_match and flac_file.with_suffix("") == ogg_file.with_suffix(""):
                self.logger.info(f"Filename match: {ogg_file}")
                matched = True

            if matched:
                break

        if matched:
            self._matched_ogg_paths.add(ogg_file)
            return ogg_file
        else:
            self.logger.warning("No match found!")
            return None

    def _sync_metadata(self, flac_file, ogg_file):
        flac_audio = FLAC(flac_file)
        ogg_audio = OggVorbis(ogg_file)

        # Check if OGG metadata matches FLAC
        if sorted(flac_audio.items()) != sorted(ogg_audio.items()):
            self.logger.info(f"Updating OGG metadata from FLAC...")
            for key in ogg_audio.keys():
                ogg_audio[key] = []
            for key, value in flac_audio.items():
                ogg_audio[key] = value
            if not self.dry_run:
                ogg_audio.save(ogg_file)
                self.logger.info(f"Updated OGG metadata.")
            else:
                self.logger.info(f"[DRY RUN] File remains unmodified.")
        else:
            self.logger.debug(f"Metadata verified.")

        # If filename mismatch, rename OGG to match FLAC filename
        if flac_file.relative_to(self.flac_dir).with_suffix('') != ogg_file.relative_to(self.ogg_dir).with_suffix(""):
            relative_path = flac_file.relative_to(self.flac_dir).with_suffix('.ogg')
            target_path = self.ogg_dir / relative_path
            if not self.dry_run:
                target_path.parent.mkdir(parents=True, exist_ok=True)
                ogg_file.rename(target_path)
                self.logger.info(f"Renamed OGG file.")
            else:
                self.logger.info(f"[DRY RUN] Would rename OGG file.")
            self._ogg_files_renamed += 1
        else:
            self.logger.debug(f"Path verified.")
    
    def _verify_stream(self, ogg_file):
        verified = True
        try:
            ogg_audio = OggVorbis(ogg_file)
            if ogg_audio.info.bitrate != self.BITRATE_QUALITY_MAP[self.quality]:
                self.logger.warning(f"Bitrate mismatch for {ogg_file}: expected {self.BITRATE_QUALITY_MAP[self.quality]}, got {ogg_audio.info.bitrate}")
                verified = False
            else:
                self.logger.debug(f"Bitrate verified.")
            if ogg_audio.info.sample_rate != self.sample_rate:
                self.logger.warning(f"Sample rate mismatch for {ogg_file}: expected {self.sample_rate}, got {ogg_audio.info.sample_rate}")
                verified = False
            else:
                self.logger.debug(f"Sample rate verified.")
            if ogg_audio.info.channels != self.channels:
                self.logger.warning(f"Channel count mismatch for {ogg_file}: expected {self.channels}, got {ogg_audio.info.channels}")
                verified = False
            else:
                self.logger.debug(f"Channel count verified.")
            return verified
        except Exception as e:
            self.logger.error(f"Error verifying bitrate for {ogg_file}: {e}")
            return False

    def _convert_file(self, flac_file, ogg_file):
        command = [
            "ffmpeg", "-y", "-loglevel", "error",
            "-i", flac_file,
            "-map", "0:a",
            "-map_metadata", "0",
            "-c:a", "libvorbis",
            "-q:a", str(self.quality),
            "-ar", str(self.sample_rate),
            "-ac", str(self.channels),
            ogg_file
        ]
        try:
            self.logger.info("Converting FLAC to OGG...")
            subprocess.run(command, check=True)
            self._vorbis_fix_hack(ogg_file)

        except subprocess.CalledProcessError as e:
            self.logger.error(f"ffmpeg failed for {flac_file}: {e}")

    def _vorbis_fix_hack(self, ogg_file):
        self.logger.debug(f"Fixing OGG metadata...")
        # TODO: find a better solution to this hack
        audio = OggVorbis(ogg_file)
        if 'ENCODER' in audio:
            audio['ENCODER'] = []
        if 'DESCRIPTION' in audio:
            audio['COMMENT'] = audio['DESCRIPTION']
            audio['DESCRIPTION'] = []
        for tag in list(audio.keys()):
            values = audio.get(tag)
            if values and len(values) == 1 and ';' in values[0]:
                audio[tag.upper()] = [v.strip() for v in values[0].split(';')]
        audio.save()

    def _clean(self):
        self.logger.info("Cleaning up unmatched OGG files and empty directories...")
        self._ogg_files_deleted = 0
        unmatched_ogg_files = set(self.ogg_files) - self._matched_ogg_paths
        for ogg_file in unmatched_ogg_files:
            if self.dry_run:
                self.logger.info(f"[DRY RUN] Would delete unmatched OGG file: {ogg_file}")
            else:
                self.logger.info(f"Deleting unmatched OGG file: {ogg_file}")
                ogg_file.unlink()
            self._ogg_files_deleted += 1

        # Traverse the directory tree bottom-up
        for dir_path in sorted(self.ogg_dir.rglob('*'), key=lambda p: -len(p.parts)):
            if dir_path.is_dir() and not any(dir_path.iterdir()):
                self.logger.info(f"Deleting empty directory: {dir_path}")
                dir_path.rmdir()
