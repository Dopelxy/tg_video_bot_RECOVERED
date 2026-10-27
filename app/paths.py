"""Stable paths; importing this module never creates files."""
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parents[1]
DATA_DIR = PROJECT_DIR / "data"
TEMP_ROOT = PROJECT_DIR / "temp_downloads"
