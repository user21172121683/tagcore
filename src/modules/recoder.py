import subprocess
from pathlib import Path

from mutagen.flac import FLAC

from core.base import BaseProcessor
from utils.helpers import get_config, UpperFLAC


class ReCoder(BaseProcessor):
    """Re-encodes FLAC files to another compression level."""

    def __init__(self, **config):
        super().__init__(**config)

        # Additional configuration
        self.level = get_config(config, "level", expected_type=int, optional=False)
        self.stamp = (
            get_config(
                config, "stamp", expected_type=str, optional=True, default=None
            ).upper()
            or None
        )

    def pre_process(self):
        self.logger.info("Re-encoding FLAC files...")

    def process_file(self, file: Path):
        try:
            with self.lock:
                self.stats.processed.append(file)
            audio = UpperFLAC(FLAC(file))
            if self._check_necessity(audio):
                if not self.dry_run:
                    self._encode(file, audio)
        except Exception as e:
            self.logger.error(f"Failed processing {file}: {e}")

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
        temp_wav = file.with_suffix(".wav")
        output_file = file.with_suffix(".flac.temp")
        backup_file = file.with_suffix(".flac.bak")

        try:
            # Backup the original file before modifying
            file.replace(backup_file)

            # Decode FLAC to WAV
            decode_cmd = [
                "flac",
                "-d",
                "-f",
                str(backup_file),
                "-o",
                str(temp_wav),
                "-s",
            ]
            subprocess.run(decode_cmd, check=True)

            # Re-encode WAV to FLAC
            encode_cmd = [
                "flac",
                f"-{self.level}",
                "-f",
                str(temp_wav),
                "-o",
                str(output_file),
                "-s",
            ]
            subprocess.run(encode_cmd, check=True)

            # Copy metadata from original audio
            reencoded_audio = UpperFLAC(FLAC(output_file))
            reencoded_audio.clear()
            for key in audio.keys():
                reencoded_audio[key] = audio[key]
            for picture in audio.pictures:
                reencoded_audio.add_picture(picture)

            # Optionally add stamp
            if self.stamp:
                reencoded_audio[self.stamp] = [str(self.level)]

            reencoded_audio.save()

            # Replace original with re-encoded version
            output_file.replace(file)

            with self.lock:
                self.stats.modified.append(file)

            # Cleanup backup after success
            if backup_file.exists():
                backup_file.unlink()

        except Exception as e:
            self.logger.exception(f"Encoding failed for {file.name}: {e}")
            self._rollback(file, backup_file)
            self.stats.failed.append(file)
        finally:
            if temp_wav.exists():
                try:
                    temp_wav.unlink()
                except Exception as e:
                    self.logger.warning(f"Failed to remove temporary WAV file: {e}")

    def _rollback(self, file: Path, backup_file: Path):
        """Restore original file from backup if rollback is needed."""
        if backup_file.exists():
            try:
                backup_file.replace(file)
            except Exception as e:
                self.logger.error(f"Failed to restore original file from backup: {e}")
