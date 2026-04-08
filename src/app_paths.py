"""Path resolution for both development and PyInstaller frozen mode."""

import sys
from pathlib import Path


def get_app_dir() -> Path:
    """Get the application root directory."""
    if getattr(sys, 'frozen', False):
        return Path(sys._MEIPASS)
    return Path(__file__).resolve().parent.parent


def get_data_dir() -> Path:
    """Get the data directory (contains astro_objects.db)."""
    return get_app_dir() / 'data'


def get_db_path() -> Path:
    """Get the path to the astronomical objects database."""
    return get_data_dir() / 'astro_objects.db'
