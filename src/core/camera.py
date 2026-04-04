"""Camera profile and FOV computation."""

import json
import math
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Optional

from config import CONFIG_DIR

PROFILES_FILE = CONFIG_DIR / 'camera_profiles.json'


@dataclass
class CameraProfile:
    """Camera + telescope configuration for FOV computation."""
    name: str
    sensor_width_px: int
    sensor_height_px: int
    pixel_size_um: float
    focal_length_mm: float

    @property
    def fov_width_deg(self) -> float:
        """Horizontal FOV in degrees."""
        sensor_width_mm = self.sensor_width_px * self.pixel_size_um / 1000.0
        return math.degrees(2 * math.atan(sensor_width_mm / (2 * self.focal_length_mm)))

    @property
    def fov_height_deg(self) -> float:
        """Vertical FOV in degrees."""
        sensor_height_mm = self.sensor_height_px * self.pixel_size_um / 1000.0
        return math.degrees(2 * math.atan(sensor_height_mm / (2 * self.focal_length_mm)))

    @property
    def pixel_scale_arcsec(self) -> float:
        """Arcseconds per pixel."""
        return self.pixel_size_um / self.focal_length_mm * 206.265


DEFAULT_PROFILE = CameraProfile(
    name="ASI2600MC + Esprit 100",
    sensor_width_px=6248,
    sensor_height_px=4176,
    pixel_size_um=3.76,
    focal_length_mm=550.0,
)


def save_profiles(profiles: list[CameraProfile]) -> None:
    """Save camera profiles to disk."""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    data = [asdict(p) for p in profiles]
    with open(PROFILES_FILE, 'w') as f:
        json.dump(data, f, indent=2)


def load_profiles() -> list[CameraProfile]:
    """Load camera profiles from disk. Returns default if none saved."""
    if PROFILES_FILE.exists():
        try:
            with open(PROFILES_FILE, 'r') as f:
                data = json.load(f)
            return [CameraProfile(**d) for d in data]
        except (json.JSONDecodeError, OSError, TypeError):
            pass
    return [DEFAULT_PROFILE]
