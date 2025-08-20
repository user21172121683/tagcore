import subprocess
from utils import index_files, setup_logger, processing_message, returning_message, check_stop
from pathlib import Path
from mutagen.flac import FLAC
from mutagen.oggvorbis import OggVorbis
import hashlib


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
            self.logger.info(processing_message(len(self._flac_files_processed), len(self.flac_files), flac_file))
            match = self._match_files(flac_file)
            # If no match found, convert FLAC to OGG
            if not match:
                ogg_output = self.ogg_dir / flac_file.relative_to(self.flac_dir).with_suffix('.ogg')
                ogg_output.parent.mkdir(parents=True, exist_ok=True)
                if not self.dry_run:
                    self._convert_file(str(flac_file), str(ogg_output))
                self._ogg_files_converted.append(ogg_output)
            # Sync metadata and rename OGG files if necessary
            else:
                if not self._verify_stream(match):
                    ogg_output = self.ogg_dir / flac_file.relative_to(self.flac_dir).with_suffix('.ogg')
                    ogg_output.parent.mkdir(parents=True, exist_ok=True)
                    if not self.dry_run:
                        self._convert_file(str(flac_file), str(ogg_output))
                    self._ogg_files_converted.append(ogg_output)
                else:
                    self._sync_metadata(flac_file, match)
            self.logger.info(f"File is up to date!")

        # Clean up unmatched OGG files and empty directories
        if not check_stop(self.stop_flag, self.logger):
            self._clean()

        # Final summary
        self.logger.info(f"\n{'-'*100}\nOgger summary\n{'-'*100}")
        self.logger.info(f"Processed {len(self._flac_files_processed)} FLAC files.")
        if len(self._ogg_files_converted) > 0:
            self.logger.info(f"Converted {len(self._ogg_files_converted)} FLAC files to OGG.")
        if len(self._ogg_files_modified) > 0:
            self.logger.info(f"Modified metadata for {len(self._ogg_files_modified)} OGG files.")
        if len(self._ogg_files_renamed) > 0:
            self.logger.info(f"Renamed {len(self._ogg_files_renamed)} OGG files to match FLAC structure.")
        if len(self._ogg_files_deleted) > 0:
            self.logger.info(f"Deleted {len(self._ogg_files_deleted)} unmatched OGG files.")
        self.logger.info(returning_message())

    def _build_metadata_index(self, files: list[Path]) -> dict:
        self.logger.info("Building metadata index with hashed fingerprints...")
        index = {}

        for file in files:
            if check_stop(self.stop_flag, self.logger):
                break
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
                        self.logger.warning(f"Deleted corrupt audio file: {file}")
                    except Exception as delete_error:
                        self.logger.error(f"Failed to delete corrupt file {file}: {delete_error}")
                else:
                    self.logger.warning(f"[DRY RUN] Would delete corrupt audio file: {file}")
                files.remove(file)
        
        return index
    
    def _generate_fingerprint(self, tags: dict) -> str:
        # Create a sorted string of tags
        metadata_str = ''.join(f"{k}:{';'.join(v)}" for k, v in sorted(tags.items()))
        # Return a hash of the metadata string (MD5 hash)
        return hashlib.md5(metadata_str.encode('utf-8')).hexdigest()

    def _match_files(self, flac_file: Path) -> Path | None:
        flac_audio = FLAC(flac_file)
        match = None

        # Generate the fingerprint of the FLAC file metadata
        self.logger.debug(f"Generating fingerprint...")
        flac_fingerprint = self._generate_fingerprint(flac_audio)
        self.flac_metadata_index[flac_file] = (flac_fingerprint, flac_audio.get(self.track_id_field, None))

        self.logger.debug("Trying to find a match...")
        # Match by track ID field if specified
        self.logger.debug("Matching by metadata...")
        for ogg_file, (ogg_fingerprint, ogg_track_id) in self.ogg_metadata_index.items():
            if ogg_file in self._unmatched_ogg_files:
                if self.track_id_field and self.flac_metadata_index[flac_file][1] and ogg_track_id and self.flac_metadata_index[flac_file][1] == ogg_track_id:
                    self.logger.info(f"Track ID match: {ogg_file}")
                    match = ogg_file
                    break
                if flac_fingerprint == ogg_fingerprint:
                    self.logger.info(f"Fingerprint match: {ogg_file}")
                    match = ogg_file
                    break

        # Match by filename if filename_match is enabled
        if self.filename_match and not match:
            self.logger.debug(f"Matching by filename...")
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
            flac_audio = FLAC(flac_file)
            ogg_audio = OggVorbis(ogg_file)
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
            self._ogg_files_modified.append(ogg_file)
        else:
            self.logger.debug(f"Metadata verified.")

        # If filename mismatch, rename OGG to match FLAC filename
        if flac_file.relative_to(self.flac_dir).with_suffix('') != ogg_file.relative_to(self.ogg_dir).with_suffix(""):
            self.logger.info(f"Renaming OGG file to match FLAC structure...")
            relative_path = flac_file.relative_to(self.flac_dir).with_suffix('.ogg')
            target_path = self.ogg_dir / relative_path
            if not self.dry_run:
                target_path.parent.mkdir(parents=True, exist_ok=True)
                ogg_file.rename(target_path)
                self.logger.info(f"Renamed OGG file.")
            else:
                self.logger.info(f"[DRY RUN] Would rename OGG file.")
            self._ogg_files_renamed.append(target_path)
        else:
            self.logger.debug(f"Path verified.")
    
    def _verify_stream(self, ogg_file: Path) -> bool:
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

    def _convert_file(self, flac_file: Path, ogg_file: Path):
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

    def _vorbis_fix_hack(self, ogg_file: Path):
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
        for ogg_file in self._unmatched_ogg_files:
            if self.dry_run:
                self.logger.info(f"[DRY RUN] Would delete unmatched OGG file: {ogg_file}")
            else:
                self.logger.info(f"Deleting unmatched OGG file: {ogg_file}")
                ogg_file.unlink()
            self._ogg_files_deleted.append(ogg_file)

        # Traverse the directory tree bottom-up
        for dir_path in sorted(self.ogg_dir.rglob('*'), key=lambda p: -len(p.parts)):
            if dir_path.is_dir() and not any(dir_path.iterdir()):
                self.logger.info(f"Deleting empty directory: {dir_path}")
                dir_path.rmdir()
