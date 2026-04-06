"""Settings persistence for Astro Framing Assistant."""

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytz

CONFIG_DIR = Path.home() / '.astro-framing'
CONFIG_FILE = CONFIG_DIR / 'config.json'

# Approximate coordinates for common timezone regions
_TZ_COORDS = {
    'America/New_York': (40.71, -74.01),
    'America/Chicago': (41.88, -87.63),
    'America/Denver': (39.74, -104.99),
    'America/Los_Angeles': (34.05, -118.24),
    'America/Toronto': (43.65, -79.38),
    'America/Sao_Paulo': (-23.55, -46.63),
    'Europe/London': (51.51, -0.13),
    'Europe/Paris': (48.86, 2.35),
    'Europe/Berlin': (52.52, 13.41),
    'Europe/Madrid': (40.42, -3.70),
    'Europe/Rome': (41.90, 12.50),
    'Europe/Amsterdam': (52.37, 4.90),
    'Europe/Stockholm': (59.33, 18.07),
    'Europe/Helsinki': (60.17, 24.94),
    'Europe/Athens': (37.98, 23.73),
    'Europe/Moscow': (55.76, 37.62),
    'Asia/Colombo': (6.93, 79.86),
    'Asia/Kolkata': (28.61, 77.21),
    'Asia/Tokyo': (35.68, 139.69),
    'Asia/Shanghai': (31.23, 121.47),
    'Asia/Singapore': (1.35, 103.82),
    'Asia/Dubai': (25.20, 55.27),
    'Australia/Sydney': (-33.87, 151.21),
    'Australia/Melbourne': (-37.81, 144.96),
    'Pacific/Auckland': (-36.85, 174.76),
    'Africa/Johannesburg': (-26.20, 28.04),
    'Africa/Cairo': (30.04, 31.24),
}


def _detect_system_timezone() -> str:
    """Detect the system's IANA timezone name."""
    import subprocess, time as _time

    # macOS: read from systemsetup or /etc/localtime symlink
    try:
        link = Path('/etc/localtime').resolve()
        # /var/db/timezone/zoneinfo/Asia/Colombo → extract after zoneinfo/
        parts = link.parts
        if 'zoneinfo' in parts:
            idx = parts.index('zoneinfo')
            tz_name = '/'.join(parts[idx + 1:])
            if tz_name in pytz.all_timezones:
                return tz_name
    except Exception:
        pass

    # Fallback: try matching UTC offset to a known timezone
    try:
        import time as _time
        offset = -_time.timezone if _time.daylight == 0 else -_time.altzone
        offset_hours = offset / 3600
        # Find a timezone matching this offset
        now = datetime.now(timezone.utc)
        for tz_name in pytz.common_timezones:
            tz = pytz.timezone(tz_name)
            try:
                tz_offset = now.astimezone(tz).utcoffset().total_seconds() / 3600
                if abs(tz_offset - offset_hours) < 0.1:
                    return tz_name
            except Exception:
                continue
    except Exception:
        pass

    return 'UTC'


def _detect_coords_from_timezone(tz_name: str) -> tuple[float, float]:
    """Get approximate lat/lon from timezone name."""
    if tz_name in _TZ_COORDS:
        return _TZ_COORDS[tz_name]
    # Try matching by region prefix
    for known_tz, coords in _TZ_COORDS.items():
        if tz_name.split('/')[0] == known_tz.split('/')[0]:
            return coords
    return (0.0, 0.0)


def _build_defaults() -> dict[str, Any]:
    """Build defaults with auto-detected location."""
    tz = _detect_system_timezone()
    lat, lon = _detect_coords_from_timezone(tz)
    return {
        'cache_path': None,
        'observer_latitude': lat,
        'observer_longitude': lon,
        'observer_elevation': 0.0,
        'observer_timezone': tz,
    }


DEFAULTS = _build_defaults()


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
