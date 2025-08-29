from utils import *
import time
from mutagen.flac import FLAC
from pathlib import Path
import subprocess

class ReCoder:
    """
    Re-encodes FLAC files to another compression level.
    """

    def __init__(self, **config):
        # Setup logger
        self.logger = config.get('logger')

        # Stop flag (for safe quitting)
        self.stop_flag = config.get("stop_flag")

        # Load configuration
        self.main_dir = Path(config['main_dir'])

        self.dry_run = config.get('dry_run', True)

        self.level = config.get('level', None)
        if self.level is None:
            raise ValueError("Compression 'level' must be specified in config.")
        try:
            self.level = int(self.level)
        except (TypeError, ValueError):
            raise ValueError(f"Compression level must be an integer, got {self.level}")

        self.stamp = (config.get('stamp') or '').upper() or None

        # Initialise index
        self.files = []

        # Stats
        self._files_processed = []
        self._files_encoded = []

    def run(self):
        # Start timer
        self.start_time = time.time()

        # Build index
        self.files = index_files(self.main_dir, extension='flac', logger=self.logger)

        if not self.files:
            self.logger.info("No FLAC files found to process.")
            return

        # Process each file
        for file in self.files:
            if check_stop(self.stop_flag, self.logger):
                break
            try:
                self._files_processed.append(file)
                self.logger.info(
                    processing_message(
                        current=len(self._files_processed),
                        total=len(self.files),
                        file=file,
                        elapsed=time.time() - self.start_time
                    )
                )
                audio = FLAC(file)
                if self._check_necessity(audio):
                    self.logger.info(dry_run_message(self.dry_run, "Re-compressing FLAC file..."))
                    if not self.dry_run:
                        self._encode(file, audio)
                else:
                    self.logger.debug("No re-compression necessary!")
            except Exception as e:
                self.logger.error(f"Failed processing {file}: {e}")

        # Final summary
        summary_items = [
            (self._files_processed, "Processed {} FLAC files."),
            (self._files_encoded, "Re-compressed {} FLAC files.")
        ]

        self.logger.info(
            summary_message(
                name="ReCoder",
                summary_items=summary_items,
                dry_run=self.dry_run,
                elapsed=time.time() - self.start_time
            )
        )

    def _check_necessity(self, audio: FLAC) -> bool:
        if self.stamp:
            audio_stamp = None
            for key, value in audio.items():
                if key.upper() == self.stamp:
                    audio_stamp = value[0]
                    break
            if audio_stamp is None:
                # No stamp found, assume re-encoding is necessary
                return True
            try:
                return int(audio_stamp) != self.level
            except ValueError:
                # Stamp is not a valid integer, assume re-encoding needed
                return True
        else:
            return True

    def _encode(self, file: Path, audio: FLAC):
        temp_wav = file.with_suffix('.wav')
        output_file = file.with_suffix('.flac.temp')
        backup_file = file.with_suffix('.flac.bak')

        try:
            # Backup the original file before modifying
            file.replace(backup_file)

            # Decode FLAC to WAV
            self.logger.debug("Decoding to WAV...")
            decode_cmd = ['flac', '-d', '-f', str(backup_file), '-o', str(temp_wav), '-s']
            subprocess.run(decode_cmd, check=True)

            # Re-encode WAV to FLAC
            self.logger.debug(f"Re-encoding to compression level {self.level}...")
            encode_cmd = ['flac', f'-{self.level}', '-f', str(temp_wav), '-o', str(output_file), '-s']
            subprocess.run(encode_cmd, check=True)

            # Copy metadata from original audio
            reencoded_audio = FLAC(output_file)
            reencoded_audio.clear()
            for key in audio.keys():
                reencoded_audio[key] = audio[key]
            for picture in audio.pictures:
                reencoded_audio.add_picture(picture)

            # Optionally add stamp
            if self.stamp:
                reencoded_audio[self.stamp] = [str(self.level)]
                self.logger.debug(dry_run_message(self.dry_run, "Applied level stamp."))

            reencoded_audio.save()

            # Replace original with re-encoded version
            output_file.replace(file)
            self.logger.info("Re-encoded and replaced!")

            self._files_encoded.append(file)

            # Cleanup backup after success
            if backup_file.exists():
                backup_file.unlink()

        except subprocess.CalledProcessError as e:
            self.logger.error(f"Subprocess failed: {e}")
            self._rollback(file, backup_file)
        except Exception as e:
            self.logger.error(f"Encoding failed for {file.name}: {e}")
            self._rollback(file, backup_file)
        finally:
            if temp_wav.exists():
                try:
                    temp_wav.unlink()
                    self.logger.debug("Temporary WAV file removed.")
                except Exception as e:
                    self.logger.warning(f"Failed to remove temporary WAV file: {e}")

    def _rollback(self, file: Path, backup_file: Path):
        """Restore original file from backup if rollback is needed."""
        if backup_file.exists():
            try:
                backup_file.replace(file)
                self.logger.info(f"Rolled back to original file: {file.name}")
            except Exception as e:
                self.logger.error(f"Failed to restore original file from backup: {e}")
