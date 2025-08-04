import sys
import logging
from datetime import datetime
from pathlib import Path
from threading import Event
import shutil


def index_files(
    directory: Path,
    extension: str,
    logger: logging.Logger
) -> list[Path]:
    log_dir = Path(__file__).resolve().parent / "logs" / datetime.now().strftime('%Y-%m-%d')
    log_dir.mkdir(parents=True, exist_ok=True)

    logger.info(f"Indexing {extension} files in {directory.resolve()}...")
    try:
        files = list(directory.rglob(f'*.{extension.lower()}'))
        if not files:
            logger.info(f"No {extension} files found.")
        else:
            logger.info(f"Found {len(files)} {extension} files.")
        return files
    except FileNotFoundError:
        logger.critical(f"Main directory '{directory.resolve()}' not found. Exiting.")
        return []


def setup_logger(
    name: str,
    base_dir: Path,
    level=logging.DEBUG
) -> logging.Logger:
    # Colorful console formatter
    class ColorFormatter(logging.Formatter):
        COLORS = {
            'DEBUG': '\033[96m',
            'INFO': '\033[92m',
            'WARNING': '\033[93m',
            'ERROR': '\033[91m',
            'CRITICAL': '\033[95m',
            'RESET': '\033[0m'
        }

        def format(self, record):
            color = self.COLORS.get(
                record.levelname, self.COLORS['RESET'])
            message = super().format(record)
            return f"{color}{message}{self.COLORS['RESET']}"

    # Setup log directory and file paths
    log_dir = base_dir / "logs" / datetime.now().strftime('%Y-%m-%d')
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / f"{name}.log"
    archive_dir = log_dir / "archive"
    archive_dir.mkdir(parents=True, exist_ok=True)

    # Check if a log file with the same name exists and move it to archive
    if log_file.exists():
        archive_file = archive_dir / f"{name}_{datetime.now().strftime('%H-%M-%S')}.log"
        shutil.move(str(log_file), str(archive_file))
        print(f"Moved existing log file to archive: {archive_file}")

    # Create and configure logger
    logger = logging.getLogger(name)
    logger.setLevel(level)
    logger.handlers.clear()

    # Console handler
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.DEBUG)
    console_formatter = ColorFormatter("[%(levelname)s] %(message)s")
    console_handler.setFormatter(console_formatter)

    # File handler (the log file now has a timestamp in its name)
    file_handler = logging.FileHandler(log_file)
    file_handler.setLevel(logging.DEBUG)
    file_formatter = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")
    file_handler.setFormatter(file_formatter)

    # Add handlers to logger
    logger.addHandler(console_handler)
    logger.addHandler(file_handler)
    logger.propagate = False

    logger.info(f"\n{'-'*100}\nStarting {name}...\n{'-'*100}")

    return logger


def processing_message(current: int, total: int, file: Path) -> str:
    return f"({str(current).zfill(len(str(total)))}/{total}) Processing: {file}"


def summary_message(name: str):
    return f"\n{'-'*100}\n{name} summary\n{'-'*100}"


def returning_message():
    return f"\n{'-'*100}\nReturning to main...\n{'-'*100}"


def check_stop(stop_flag: Event, logger: logging.Logger):
    """
    Checks whether the stop_flag is set.
    If set, logs a message and returns True.
    """
    if stop_flag and hasattr(stop_flag, 'is_set') and stop_flag.is_set():
        logger.warning("Stop flag received. Exiting early.")
        return True
    return False
