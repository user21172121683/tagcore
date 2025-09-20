from abc import ABC, abstractmethod
import threading
from pathlib import Path
import logging

from core.dataclasses import Stats
from utils.formatting import summary_message, dry_run_message
from utils.helpers import parallel_map, get_config, index_files


class BaseProcessor(ABC):
    """
    Abstract base class for file-based processors.

    Provides a common structure for tools that:
    - Load configuration via keyword arguments
    - Index files
    - Process files in parallel
    - Log activity and provide summary statistics
    """

    def __init__(self, **config):
        # Technical stuff
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
        self.dry_run = get_config(
            config, "dry_run", expected_type=bool, optional=True, default=True
        )
        self.lock = threading.Lock()

        # Main directory
        self.main_dir = Path(
            get_config(config, "main_dir", expected_type=str, optional=False)
        )

        # Stats
        self.stats = Stats()

        # Index
        self.files = []

    def run(self):
        """Subclasses are expected to conform to this workflow."""
        # Start timer
        self.stats.start_timer()

        # Indexing
        self.pre_index()
        self.index()
        self.post_index()

        # Processing
        self.pre_process()
        self.process_all()
        self.post_process()

        # Summary
        self.pre_summary()
        self.summary()
        self.post_summary()

    def index(self):
        """Populate list of items to process."""
        self.files = index_files(
            directory=self.main_dir, extension="flac", logger=self.logger
        )

    @abstractmethod
    def process_file(self, file):
        """Process individual item."""
        raise NotImplementedError

    def process_all(self):
        """Process all items in parallel."""
        parallel_map(
            func=self.process_file,
            items_with_args=self.files,
            max_workers=self.max_workers,
            stop_flag=self.stop_flag,
            logger=self.logger,
            description=dry_run_message(self.dry_run, "Processing"),
            unit="files",
        )

    def summary(self):
        """Summarise activities recorded in self.stats."""
        self.stats.stop_timer()
        self.logger.info(
            summary_message(
                name=self.__class__.__name__,
                summary_items=self.stats.to_dict(),
                dry_run=self.dry_run,
            )
        )

    def pre_index(self):
        pass

    def post_index(self):
        pass

    def pre_process(self):
        pass

    def post_process(self):
        pass

    def pre_summary(self):
        pass

    def post_summary(self):
        pass
