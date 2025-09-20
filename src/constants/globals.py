from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
CONFIG_PATH = ROOT / "config.yaml"
DATA_DIR = ROOT / "data"
LOG_DIR = ROOT / "logs"
MODULES_DIR = ROOT / "src" / "modules"
BANNER = "┌┬┐┌─┐┌─┐┌─┐┌─┐┬─┐┌─┐\n │ ├─┤│ ┬│  │ │├┬┘├┤ \n ┴ ┴ ┴└─┘└─┘└─┘┴└─└─┘"
