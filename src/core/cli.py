import sys
import shutil
import threading
import importlib.util
import ast
from pprint import pformat

import yaml

from constants.globals import ROOT, MODULES_DIR, CONFIG_PATH, BANNER
from utils.helpers import setup_logger


class App:
    """Application class that dynamically loads and runs discovered modules."""

    def __init__(self):
        # Banner
        print(BANNER)

        # Ensure dynamically loaded scripts can be imported
        sys.path.insert(0, str(MODULES_DIR))

        # Initialise config and scripts
        self.config = {}
        self.scripts = {}

    def load_config(self) -> dict:
        """
        Load YAML configuration file with error handling.
        Raises FileNotFoundError if the config file does not exist.
        Returns an empty dict on YAML parsing failure.
        """
        if not CONFIG_PATH.is_file():
            raise FileNotFoundError(
                "config.yaml not found in the parent directory of main.py."
            )
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as file:
                return yaml.safe_load(file) or {}
        except yaml.YAMLError as e:
            print(f"Failed to parse YAML config: {e}")
        except Exception as e:
            print(f"Failed to load config file: {e}")
        return {}

    def parse_overrides(self, override_list):
        """
        Converts ['Section.key.sub=value'] into nested dict overrides with type conversion.
        """
        overrides = {}
        for item in override_list:
            if "=" not in item:
                print(f"Invalid override format (missing '='): {item}")
                continue

            key_path, value_str = item.split("=", 1)
            keys = key_path.split(".")

            try:
                value = ast.literal_eval(value_str)
            except (ValueError, SyntaxError):
                value = value_str

            current = overrides
            for key in keys[:-1]:
                current = current.setdefault(key, {})
            current[keys[-1]] = value

        return overrides

    def deep_update_config(self, updates):
        """
        Recursively updates self.config with nested dictionary 'updates'.
        """
        stack = [(self.config, updates)]

        while stack:
            base, updates = stack.pop()
            for k, v in updates.items():
                if isinstance(v, dict) and isinstance(base.get(k), dict):
                    stack.append((base[k], v))
                else:
                    base[k] = v

    def discover_scripts(self) -> dict:
        scripts = {}

        for file in MODULES_DIR.glob("*.py"):
            module_name = file.stem
            try:
                spec = importlib.util.spec_from_file_location(module_name, file)
                module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(module)

                for attr in dir(module):
                    obj = getattr(module, attr)

                    if not isinstance(obj, type):
                        continue

                    if callable(getattr(obj, "run", None)):
                        # Only include classes defined in this module
                        if obj.__module__ != module_name:
                            continue

                        # Skip classes explicitly marked as placeholders
                        if getattr(obj, "placeholder", False):
                            continue

                        scripts[obj.__name__] = {
                            "class": obj,
                            "module": module_name,
                            "class_name": obj.__name__,
                            "doc": (
                                (obj.__doc__ or "").strip().splitlines()[0]
                                if obj.__doc__
                                else ""
                            ),
                        }

            except Exception as e:
                print(f"Failed to load {module_name}: {e}")

        return scripts

    def run_script(self, name: str, confirm: bool = True):
        if name not in self.scripts:
            print(f"Script '{name}' not found.")
            return

        cls = self.scripts[name]["class"]

        # Build script args first
        script_args = self.config.get("General", {}).copy()
        script_args.update(self.config.get(name, {}))

        # Setup logger early — available for all branches (including exceptions)
        logger = setup_logger(
            name=self.scripts[name]["module"],
            console_level=script_args.get("console_level", "INFO"),
            file_level=script_args.get("file_level", "DEBUG"),
        )

        # Add logger and stop_flag to script_args
        stop_flag = threading.Event()
        script_args["stop_flag"] = stop_flag
        script_args["logger"] = logger

        try:
            # Confirm step
            if confirm:
                answer = (
                    input(
                        f"{pformat(script_args, indent=2, width=80, sort_dicts=True)}\nRun {name} with the above config? (Y/n): "
                    )
                    .strip()
                    .lower()
                )
                if answer not in ("", "y", "yes"):
                    print("Aborting script run.")
                    return
            else:
                print(
                    f"\nRunning {name} with config:\n{pformat(script_args, indent=2, width=80, sort_dicts=True)}"
                )

            instance = cls(**script_args)

            # Define the thread that runs the script
            def script_target():
                try:
                    print("Script is running. Type 'q' then press Enter to stop it.")
                    instance.run()
                except Exception:
                    logger.exception(f"An error occurred while running script '{name}'")
                    print(
                        f"An error occurred while running '{name}'. Check the logs for details."
                    )

            # Thread that listens for 'q'
            def input_listener():
                while not stop_flag.is_set():
                    user_input = input()
                    if user_input.strip().lower() == "q":
                        print("Stopping script...")
                        stop_flag.set()
                        break

            # Run threads
            script_thread = threading.Thread(target=script_target)
            listener_thread = threading.Thread(target=input_listener)

            script_thread.start()
            listener_thread.start()

            script_thread.join()
            stop_flag.set()
            print("Press Enter to return to main menu.")
            listener_thread.join()

        except Exception:
            logger.exception(f"An error occurred while launching script '{name}'")
            print(
                f"An error occurred while launching '{name}'. Check the logs for details."
            )

    def refresh(self):
        """
        Refresh the configuration and scripts.
        """
        self.config = self.load_config()
        self.scripts = self.discover_scripts()

    def clear_caches(self):
        """
        Clear Python's cache after quitting.
        """
        # Clear all __pycache__ directories
        for pycache_dir in ROOT.rglob("__pycache__"):
            try:
                shutil.rmtree(pycache_dir)
            except Exception as e:
                print(f"Error clearing cache at {pycache_dir}: {e}")

        # Clear sys.modules cache
        for module_name in list(sys.modules.keys()):
            if module_name not in ("__main__", "builtins"):
                del sys.modules[module_name]
