import os
import sys
import logging
from datetime import datetime
from pathlib import Path


def index_files(
    directory: Path,
    extension: str,
    logger: logging.Logger
) -> list:
    log_dir = Path(__file__).resolve().parent / "logs" / \
        datetime.now().strftime('%Y-%m-%d')
    log_dir.mkdir(exist_ok=True)
    logger.info(f"Indexing {extension} files in {directory}...")
    try:
        files = []
        for root, _, filenames in os.walk(directory):
            files.extend([os.path.join(root, file)
                         for file in filenames if file.lower().endswith(f".{extension}")])
        if len(files) == 0:
            logger.error(f"No {extension} files found. Exiting.")
        else:
            logger.info(f"Found {len(files)} {extension} files.")
            with open(log_dir / f"{extension}_files.txt", "w", encoding="utf-8") as f:
                logger.info(
                    f"Writing indexed {extension} files to {log_dir}/{extension}_files.txt for debugging...")
                for file in files:
                    f.write(file + "\n")
        return files
    except FileNotFoundError:
        logger.error(f"Master directory '{directory}' not found. Exiting.")


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

    # Setup log directory
    log_dir = base_dir / "logs" / datetime.now().strftime('%Y-%m-%d')
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / f"{name}.log"

    # Create and configure logger
    logger = logging.getLogger(name)
    logger.setLevel(level)
    logger.handlers.clear()

    # Console handler
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.DEBUG)
    console_formatter = ColorFormatter("[%(levelname)s] %(message)s")
    console_handler.setFormatter(console_formatter)

    # File handler
    file_handler = logging.FileHandler(log_file)
    file_handler.setLevel(logging.DEBUG)
    file_formatter = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(message)s")
    file_handler.setFormatter(file_formatter)

    logger.addHandler(console_handler)
    logger.addHandler(file_handler)
    logger.propagate = False

    logger.info(f"\n{'-'*100}\nStarting {name}...\n{'-'*100}")

    return logger


def processing_message(current, total, file):
    return f"({str(current).zfill(len(str(total)))}/{total}) Processing '{file}'..."

def returning_message():
    return f"\n{'-'*100}\nReturning to main...\n{'-'*100}"
