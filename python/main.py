import sys
import yaml
import importlib.util
from pathlib import Path
from pprint import pformat
from utils import setup_logger


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

        # Setup logger
        self.logger = setup_logger("main", self.base_dir)

        # Find and load config
        self.config_path = self.find_config()
        self.config = self.load_config()

        # Discover scripts
        self.scripts = self.discover_scripts()

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
            self.logger.error(f"Failed to parse YAML config: {e}")
        except Exception as e:
            self.logger.error(f"Failed to load config file: {e}")

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
                        self.logger.debug(f"Discovered: {module_name} → {obj.__name__}")
                        break

            except Exception as e:
                self.logger.error(f"Failed to load {module_name}: {e}")
        return scripts

    def run_script(self, name: str):
        """
        Run the script identified by name if found.
        Uses the configuration parameters loaded for that script.
        """
        if name not in self.scripts:
            print(f"Script '{name}' not found.")
            return

        if name not in self.config:
            print(f"No config found for '{name}' in {self.config_path}")
            return

        try:
            print(f"\nRunning script: {name}")
            self.logger.debug(f"Config for {name}:\n{pformat(self.config[name], indent=2, width=80, sort_dicts=False)}")
            cls = self.scripts[name]["class"]
            instance = cls(**self.config[name])
            instance.run()
        except Exception as e:
            self.logger.error(f"Error running script '{name}': {e}", exc_info=True)
            print(f"An error occurred while running '{name}'. Check the logs for details.")


def main():
    app = App()

    while True:
        print(f"\n{'='*100}\nWelcome back!\n{'='*100}\n\nAvailable scripts:")
        indexed_names = sorted(app.scripts.items())
        for i, (name, info) in enumerate(indexed_names, start=1):
            description = info.get("doc", "")
            display_name = info['class_name']
            if description:
                display_name += f": {description}"
            print(f"  [{i}] {display_name}")
        print("  [all] Run all scripts")

        script_input = input("\nEnter script number or class name (or 'all' to run all, Enter to quit): ").strip()

        if not script_input:
            print("Goodbye!")
            break

        if script_input.lower() == "all":
            for name in app.scripts:
                app.run_script(name)
            continue

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

        app.run_script(script_name)


if __name__ == "__main__":
    main()
