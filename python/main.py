import sys
import yaml
import importlib.util
from pathlib import Path
from pprint import pformat
import threading
import shutil


class App:
    def __init__(self):
        """
        Initialize the App:
        - Resolve base directory relative to this file.
        - Locate config.yaml.
        - Load YAML config safely with error handling.
        - Setup logger.
        - Discover scripts from modules folder.
        """
        self.base_dir = Path(__file__).resolve().parent
        self.modules_path = self.base_dir / "modules"
        sys.path.insert(0, str(self.modules_path))

        # Initialise config and scripts
        self.config_path = None
        self.config = {}
        self.scripts = {}

    def find_config(self) -> Path:
        """
        Find the config.yaml file in the base directory.
        Raises FileNotFoundError if not found.
        """
        config_path = self.base_dir / "config.yaml"
        if config_path.is_file():
            return config_path
        raise FileNotFoundError("config.yaml not found in the same directory as main.py.")

    def load_config(self) -> dict:
        """
        Load YAML configuration file with error handling.
        Returns an empty dict on failure.
        """
        try:
            with open(self.config_path, "r") as f:
                return yaml.safe_load(f) or {}
        except yaml.YAMLError as e:
            print(f"Failed to parse YAML config: {e}")
        except Exception as e:
            print(f"Failed to load config file: {e}")

        return {}

    def discover_scripts(self) -> dict:
        """
        Discover script classes in the modules directory.
        A script class is any class that implements a callable 'run' method.
        Returns a dictionary mapping module_name -> script metadata.
        """
        scripts = {}
        for file in self.modules_path.glob("*.py"):
            module_name = file.stem
            try:
                spec = importlib.util.spec_from_file_location(module_name, file)
                module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(module)

                for attr in dir(module):
                    obj = getattr(module, attr)
                    if isinstance(obj, type) and callable(getattr(obj, "run", None)):
                        scripts[obj.__name__] = {
                            "class": obj,
                            "module": module_name,
                            "class_name": obj.__name__,
                            "doc": (obj.__doc__ or "").strip().splitlines()[0] if obj.__doc__ else ""
                        }
                        break

            except Exception as e:
                print(f"Failed to load {module_name}: {e}")
        return scripts

    def run_script(self, name: str):
        if name not in self.scripts:
            print(f"Script '{name}' not found.")
            return

        if name not in self.config:
            print(f"No config found for '{name}' in {self.config_path}")
            return

        try:
            cls = self.scripts[name]["class"]

            script_args = self.config[name].copy()
            for key, value in self.config['General'].items():
                script_args[key] = value

            answer = input(f"{pformat(script_args, indent=2, width=80, sort_dicts=True)}\nRun {name} with the above config? (Y/n): ").strip().lower()
            if answer not in ("", "y", "yes"):
                print("Aborting script run.")
                return

            stop_flag = threading.Event()
            script_args['stop_flag'] = stop_flag
            instance = cls(**script_args)

            # Function to run the script
            def script_target():
                try:
                    instance.run()
                except Exception as e:
                    print(f"Error running script '{name}': {e}", exc_info=True)
                    print(f"An error occurred while running '{name}'. Check the logs for details.")

            # Function to listen for 'q'
            def input_listener():
                while not stop_flag.is_set():
                    user_input = input()
                    if user_input.strip().lower() == "q":
                        print("Stopping script...")
                        stop_flag.set()
                        break

            # Start both threads
            script_thread = threading.Thread(target=script_target)
            listener_thread = threading.Thread(target=input_listener)

            script_thread.start()
            listener_thread.start()

            print("Script is running. Type 'q' then press Enter to stop it.")

            # Wait for the script to finish
            script_thread.join()

            # Ensure listener thread stops too
            stop_flag.set()
            listener_thread.join()

            print("Script finished.")

        except Exception as e:
            print(f"Error launching script '{name}': {e}", exc_info=True)
            print(f"An error occurred while launching '{name}'. Check the logs for details.")

    def refresh(self):
        """
        Refresh the configuration and script discovery.
        Called each time the main menu is displayed.
        """
        print("Refreshing configuration and scripts...")
        self.config_path = self.find_config()
        self.config = self.load_config()
        self.scripts = self.discover_scripts()

    def clear_caches(self):
        """
        Clears Python's cache after quitting:
        - Removes all __pycache__ directories.
        - Clears sys.modules cache.
        """
        # Use the directory where the script is located
        base_path = Path(__file__).resolve().parent
        
        # Clear all __pycache__ directories using pathlib
        for pycache_dir in base_path.rglob("__pycache__"):
            try:
                shutil.rmtree(pycache_dir)
                print(f"Cleared cache at {pycache_dir}")
            except Exception as e:
                print(f"Error clearing cache at {pycache_dir}: {e}")

        # Clear sys.modules cache
        for module_name in list(sys.modules.keys()):
            if module_name not in ('__main__', 'builtins'):
                del sys.modules[module_name]

        print("Cleared Python caches.")


def main():
    app = App()

    try:
        while True:
            print(f"\n{'='*100}\nWelcome back!\n{'='*100}\n\nAvailable scripts:")
            app.refresh()
            indexed_names = sorted(app.scripts.items())
            for i, (name, info) in enumerate(indexed_names, start=1):
                description = info.get("doc", "")
                display_name = info['class_name']
                if description:
                    display_name += f": {description}"
                print(f"  [{i}] {display_name}")

            script_input = input("\nEnter script number or class name (or press Enter to quit): ").strip()

            if not script_input:
                break

            # Try interpreting the input as a number
            if script_input.isdigit():
                idx = int(script_input) - 1
                if 0 <= idx < len(indexed_names):
                    script_name = indexed_names[idx][0]
                else:
                    print("Invalid number.")
                    continue
            else:
                script_name = script_input
            app.refresh()
            app.run_script(script_name)
    finally:
        # Ensure caches are cleared before quitting
        app.clear_caches()
        print("Goodbye!")


if __name__ == "__main__":
    main()
