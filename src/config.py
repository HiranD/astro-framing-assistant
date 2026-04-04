"""Settings persistence for Astro Framing Assistant."""

import json
from pathlib import Path
from typing import Any, Optional

CONFIG_DIR = Path.home() / '.astro-framing'
CONFIG_FILE = CONFIG_DIR / 'config.json'

DEFAULTS = {
    'cache_path': None,
    'window_width': 1400,
    'window_height': 900,
}


def load_config() -> dict[str, Any]:
    """Load config from disk, merging with defaults."""
    config = dict(DEFAULTS)
    if CONFIG_FILE.exists():
        try:
            with open(CONFIG_FILE, 'r') as f:
                saved = json.load(f)
            config.update(saved)
        except (json.JSONDecodeError, OSError):
            pass
    return config


def save_config(config: dict[str, Any]) -> None:
    """Save config to disk."""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    with open(CONFIG_FILE, 'w') as f:
        json.dump(config, f, indent=2)
