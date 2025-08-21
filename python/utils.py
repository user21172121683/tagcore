import sys
import logging
from datetime import datetime
from pathlib import Path
from threading import Event
import shutil
from datetime import timedelta


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
    level: int =logging.DEBUG,
    console_level: str = "INFO",
    file_level: str = "DEBUG"
) -> logging.Logger:
    # Helper to convert string level to logging constant
    def get_level(level_str: str) -> int:
        level_str = level_str.upper()
        levels = {
            'DEBUG': logging.DEBUG,
            'INFO': logging.INFO,
            'WARNING': logging.WARNING,
            'ERROR': logging.ERROR,
            'CRITICAL': logging.CRITICAL,
        }
        return levels.get(level_str, logging.INFO)  # Default INFO if invalid

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
    console_handler.setLevel(get_level(console_level))
    console_formatter = ColorFormatter("[%(levelname)s] %(message)s")
    console_handler.setFormatter(console_formatter)

    # File handler (the log file now has a timestamp in its name)
    file_handler = logging.FileHandler(log_file)
    file_handler.setLevel(get_level(file_level))
    file_formatter = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")
    file_handler.setFormatter(file_formatter)

    # Add handlers to logger
    logger.addHandler(console_handler)
    logger.addHandler(file_handler)
    logger.propagate = False

    logger.info(f"\n{'-'*100}\nStarting {name}...\n{'-'*100}")

    return logger


def processing_message(current: int, total: int, file: Path, elapsed: float | None = None) -> str:
    return f"[{current}/{total}{f' | {str(timedelta(seconds=elapsed))[:-3]}' if elapsed else ''}] Processing: {file}"


def summary_message(name: str, summary_items: list[tuple[list, str]], dry_run: bool, elapsed: float | None = None) -> str:
    # Initialise with banner
    message = banner_message(f"{name} summary")

    # Table to summarise
    if not any(items for items, _ in summary_items):
        message = message + "\nNothing done!"
    else:
        for items, message in summary_items:
            if items:
                message = message + "\n" + dry_run_message(dry_run, message.format(len(items)))
    
    # Total time elapsed
    if elapsed:
        message = message + f"\nTotal time elapsed: {str(timedelta(seconds=elapsed))[:-3]}"
    
    # Returning to main
    message = message + banner_message("Returning...")
    return message


def banner_message(message: str, symbol: str = "-", length: int = 100):
    return f"\n{symbol*length}\n{message}\n{symbol*length}"


def dry_run_message(dry_run: bool, message: str) -> str:
    return f"[DRY RUN] {message}" if dry_run else message


def check_stop(stop_flag: Event, logger: logging.Logger) -> bool:
    """
    Checks whether the stop_flag is set.
    If set, logs a message and returns True.
    """
    if stop_flag and hasattr(stop_flag, 'is_set') and stop_flag.is_set():
        logger.warning("Stop flag received. Exiting early.")
        return True
    return False
