from dataclasses import dataclass, field
from typing import Any, Optional
import time


@dataclass
class Stats:
    """
    Tracks statistics for processed, modified, and failed items, along with timing information.
    """

    # Stats
    processed: list[Any] = field(default_factory=list)
    modified: list[Any] = field(default_factory=list)
    failed: list[Any] = field(default_factory=list)

    # Time
    start_time: Optional[float] = None
    end_time: Optional[float] = None

    # Additional dynamically added stats
    _custom: dict[str, Any] = field(default_factory=dict, repr=False)

    def __getattr__(self, name: str) -> Any:
        if name in self._custom:
            return self._custom[name]
        raise AttributeError(f"'Stats' object has no attribute '{name}'")

    def __setattr__(self, name: str, value: Any):
        if name in self.__annotations__ or name.startswith("_"):
            super().__setattr__(name, value)
        else:
            self._custom[name] = value

    def start_timer(self):
        self.start_time = time.time()
        self.end_time = None

    def stop_timer(self):
        if self.start_time is not None:
            self.end_time = time.time()
        else:
            print("Cannot stop timer as it was never started.")

    def get_elapsed_time(self) -> Optional[float]:
        if self.start_time is None:
            return None
        return (self.end_time or time.time()) - self.start_time

    def reset(self):
        for key, value in vars(self).items():
            if isinstance(value, (list, dict, set)):
                value.clear()
            elif hasattr(value, "reset") and callable(value.reset):
                try:
                    value.reset()
                except Exception as e:
                    print(f"Failed to reset {key}: {e}")
            else:
                setattr(self, key, None)

    def to_dict(self) -> dict:
        result = {}
        for key, value in vars(self).items():
            if key == "custom":
                continue  # Handle separately
            try:
                result[key] = value
            except Exception as e:
                result[key] = f"Error: {e}"

        # Add dynamic elapsed time
        result["elapsed_time"] = self.get_elapsed_time()

        # Add custom stats
        result.update(self.custom)
        return result
