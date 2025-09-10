import sys
import logging
from datetime import datetime
from pathlib import Path
from threading import Event
import shutil
from datetime import timedelta
from tqdm import tqdm
from typing import *
from concurrent.futures import ThreadPoolExecutor, Executor, as_completed


# Constants
DATA_DIR = Path(__file__).resolve().parents[1] / "data"
LOG_DIR = Path(__file__).resolve().parents[1] / "logs"


# Utility functions
def index_files(
    directory: Path,
    extension: str,
    logger: logging.Logger
) -> list[Path]:
    logger.info(f"Indexing {extension.upper()} files in {directory.resolve()}...")
    try:
        files = list(directory.rglob(f"*.{extension.lower()}"))
        if not files:
            logger.info(f"No {extension.upper()} files found.")
        else:
            logger.info(f"Found {len(files)} {extension.upper()} files.")
        return files
    except FileNotFoundError:
        logger.critical(f"Main directory {directory.resolve()} not found. Exiting.")
        return []


def setup_logger(
    name: str,
    level: int = logging.DEBUG,
    console_level: str = "INFO",
    file_level: str = "DEBUG"
) -> logging.Logger:
    # Helper to convert string level to logging constant
    def get_level(level_str: str) -> int:
        level_str = level_str.upper()
        levels = {
            "DEBUG": logging.DEBUG,
            "INFO": logging.INFO,
            "WARNING": logging.WARNING,
            "ERROR": logging.ERROR,
            "CRITICAL": logging.CRITICAL,
        }
        return levels.get(level_str, logging.INFO)  # Default INFO if invalid

    # Colorful console formatter
    class ColorFormatter(logging.Formatter):
        COLORS = {
            "DEBUG": "\033[96m",
            "INFO": "\033[92m",
            "WARNING": "\033[93m",
            "ERROR": "\033[91m",
            "CRITICAL": "\033[95m",
            "RESET": "\033[0m"
        }

        def format(self, record):
            color = self.COLORS.get(
                record.levelname, self.COLORS["RESET"])
            message = super().format(record)
            return f"{color}{message}{self.COLORS['RESET']}"

    logger = logging.getLogger(name)
    logger.setLevel(level)

    # Close and remove existing handlers properly
    for handler in logger.handlers[:]:
        handler.close()
        logger.removeHandler(handler)

    # Setup log directory and file paths
    log_dir = LOG_DIR / datetime.now().strftime("%Y-%m-%d")
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / f"{name}.log"
    archive_dir = log_dir / "archive"
    archive_dir.mkdir(parents=True, exist_ok=True)

    # Archive old file
    if log_file.exists():
        archive_file = archive_dir / f"{name}_{datetime.now().strftime('%H-%M-%S')}.log"
        try:
            shutil.move(str(log_file), str(archive_file))
            print(f"Moved existing log file to archive: {archive_file}")
        except PermissionError as e:
            print(f"Warning: Couldn't archive log file due to permission error: {e}")

    # Console handler
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(get_level(console_level))
    console_formatter = ColorFormatter("[%(levelname)s] %(message)s")
    console_handler.setFormatter(console_formatter)

    # File handler
    file_handler = logging.FileHandler(log_file)
    file_handler.setLevel(get_level(file_level))
    file_formatter = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")
    file_handler.setFormatter(file_formatter)

    # Add handlers
    logger.addHandler(console_handler)
    logger.addHandler(file_handler)

    logger.propagate = False

    logger.info(f"\n{'-'*100}\nStarting {name}...\n{'-'*100}")

    return logger


def parallel_map(
    func: Callable,
    items_with_args: List[Any],
    *,
    executor_type: Type[Executor] = ThreadPoolExecutor,
    max_workers: int = 4,
    logger: Optional[Any] = None,
    stop_flag: Optional[Any] = None,
    description: Optional[str] = "Processing",
    unit: str = "items"
) -> List[Any]:
    """Applies `func` to each item in `items_with_args` in parallel.

    Each item should be either:
        - A tuple of positional arguments, or
        - A tuple of (positional_args, keyword_args)
    Logs activity using logger or print.
    Returns results in the original order.
    """

    def get_item_name(args) -> str:
        """Get the display name of the task from its arguments."""
        if isinstance(args, tuple):
            return str(args[0]) if args else "Unknown"
        return str(args)

    results = [None] * len(items_with_args)
    futures = {}
    submitted_futures = []

    with executor_type(max_workers=max_workers) as executor:
        for index, args in enumerate(items_with_args):
            if stop_flag and check_stop(stop_flag, logger):
                break

            # Unpack arguments (positional and optional keyword arguments)
            if isinstance(args, tuple):
                if len(args) == 2 and isinstance(args[1], dict):
                    pos_args, kw_args = args
                else:
                    pos_args, kw_args = args, {}
            else:
                pos_args, kw_args = (args,), {}

            future = executor.submit(func, *pos_args, **kw_args)
            futures[future] = index
            submitted_futures.append(future)

        try:
            for future in tqdm(
                as_completed(submitted_futures),
                total=len(submitted_futures),
                desc=description,
                unit=unit,
                mininterval=0.2,
                smoothing=0.1
            ):
                if stop_flag and check_stop(stop_flag, logger):
                    # Cancel any remaining futures that haven"t started
                    for f in submitted_futures:
                        if not f.done():
                            f.cancel()
                    break

                index = futures[future]
                try:
                    results[index] = future.result()
                except Exception as e:
                    file = get_item_name(items_with_args[index])
                    err_msg = (
                        f"Error {description} on item {index} ({file}): {e}"
                        if description else f"Error on item {index} ({file}): {e}"
                    )
                    if logger:
                        logger.exception(err_msg)
                    else:
                        print(err_msg)
        finally:
            executor.shutdown(wait=False)

    return results


def get_config(
    config: Dict[str, Any],
    key: str,
    *,
    expected_type: Type,
    default: Any = None,
    optional: bool = False
) -> Any:
    value = config.get(key, default)

    if value is None:
        if optional:
            return None
        raise ValueError(f'Missing required config key: "{key}"')

    # Handle generic types like dict[str, str], list[int], etc.
    origin = get_origin(expected_type)
    args = get_args(expected_type)

    if origin:
        if not isinstance(value, origin):
            raise TypeError(f'"{key}" must be of type {origin.__name__}, got {type(value).__name__}.')

        # Special handling for dicts
        if origin is dict and len(args) == 2:
            key_type, val_type = args
            for k, v in value.items():
                if not isinstance(k, key_type):
                    raise TypeError(f'Key in "{key}" must be {key_type.__name__}, got {type(k).__name__}')
                if not isinstance(v, val_type):
                    raise TypeError(f'Value in "{key}" must be {val_type.__name__}, got {type(v).__name__}')
        
        # Special handling for lists
        elif origin is list and len(args) == 1:
            item_type = args[0]
            for item in value:
                if not isinstance(item, item_type):
                    raise TypeError(f'Item in "{key}" must be {item_type.__name__}, got {type(item).__name__}')
    else:
        # Non-generic type (e.g. str, int)
        if not isinstance(value, expected_type):
            raise TypeError(f'"{key}" must be of type {expected_type.__name__}. Got {type(value).__name__}.')

    return value


class UpperFLAC:
    def __init__(self, flac):
        self._flac = flac

    def __getitem__(self, key):
        return self._flac[key.upper()]

    def __setitem__(self, key, value):
        self._flac[key.upper()] = value

    def get(self, key, default=None):
        return self._flac.get(key.upper(), default)

    def keys(self):
        return [k.upper() for k in self._flac.keys()]

    def __contains__(self, key):
        return key.upper() in self._flac

    def save(self):
        self._flac.save()

    def __getattr__(self, attr):
        return getattr(self._flac, attr)


def summary_message(name: str, summary_items: list[tuple[list, str]], dry_run: bool, elapsed: float | None = None) -> str:
    # Initialise with banner
    message = banner_message(f"{dry_run_message(dry_run, name)} summary")

    # Table to summarise
    if not any(items for items, _ in summary_items):
        message += "\nNothing done!"
    else:
        for items, msg_template in summary_items:
            if items:
                message += "\n" + msg_template.format(len(items))
    
    # Total time elapsed
    if elapsed:
        message += f"\nTotal time elapsed: {str(timedelta(seconds=elapsed))[:-3]}"
    
    # Returning to main
    message += banner_message("Returning...")
    return message


def dry_run_message(dry_run: bool, message: str) -> str:
    return f"[DRY RUN] {message}" if dry_run else message


def banner_message(message: str, symbol: str = "-", length: int = 100):
    return f"\n{symbol*length}\n{message}\n{symbol*length}"


def check_stop(stop_flag: Event, logger=None) -> bool:
    if stop_flag and stop_flag.is_set():
        message = "Stop flag received. Exiting early."
        if logger:
            logger.warning(message)
        else:
            print(message)
        return True
    return False
