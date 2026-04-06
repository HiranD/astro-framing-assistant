"""N.I.N.A. FramingAssistantCache reader.

Reads the flat directory of JPEG sky tiles produced by N.I.N.A.'s offline
framing assistant cache. Each tile covers 5x5 degrees of sky.

Filename format:
    {RA_HH}_{RA_MM}_{RA_SS}_{±DEC_DD}_ {DEC_MM}_ {DEC_SS}__{zoom}[_{size}px].jpg
"""

import os
import re
import math
import logging
import functools
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import numpy as np
from PIL import Image
from astropy.wcs import WCS

logger = logging.getLogger(__name__)

# Each tile covers this many degrees of sky
TILE_FOV_DEG = 5.0
# Full-resolution tile size in pixels
TILE_FULL_PX = 2000

# Regex to parse N.I.N.A. tile filenames (handles spaces in Dec parts)
# Examples:
#   00_00_00_-04_ 30_ 00__5.jpg        (full res, 2000px)
#   12_14_07_13_ 30_ 00__5_500px.jpg   (500px variant)
FILENAME_RE = re.compile(
    r'^(\d{2})_(\d{2})_(\d{2})_'       # RA: HH_MM_SS_
    r'(-?\d{1,2})_\s*(\d{2})_\s*(\d{2})_'  # Dec: ±DD_ MM_ SS_
    r'_(\d+)'                           # _zoom
    r'(?:_(\d+)px)?'                    # optional _SIZEpx
    r'\.jpg$'
)


@dataclass
class TileInfo:
    """Metadata for a single sky tile."""
    ra_deg: float
    dec_deg: float
    zoom: int
    size_px: int  # 2000 for full, 500/150/75 for thumbnails
    filepath: Path


class TileCache:
    """Index and loader for N.I.N.A. FramingAssistantCache tiles."""

    def __init__(self, cache_path: str) -> None:
        self.cache_path = Path(cache_path)
        # Index: (ra_deg, dec_deg) -> {size_px: TileInfo}
        self._index: dict[tuple[float, float], dict[int, TileInfo]] = {}
        self._valid = False
        self._build_index()

    @property
    def valid(self) -> bool:
        """Whether the cache path exists and contains tiles."""
        return self._valid

    def _build_index(self) -> None:
        """Scan directory and parse all tile filenames into the index."""
        if not self.cache_path.is_dir():
            logger.warning("Cache path does not exist: %s", self.cache_path)
            return

        count = 0
        for entry in os.scandir(self.cache_path):
            if not entry.name.endswith('.jpg'):
                continue
            info = self._parse_filename(entry.name, Path(entry.path))
            if info is None:
                continue
            key = (info.ra_deg, info.dec_deg)
            if key not in self._index:
                self._index[key] = {}
            self._index[key][info.size_px] = info
            count += 1

        self._valid = len(self._index) > 0
        logger.info("Indexed %d tile files at %d sky positions", count, len(self._index))

    def _parse_filename(self, name: str, filepath: Path) -> Optional[TileInfo]:
        """Parse a tile filename into a TileInfo."""
        m = FILENAME_RE.match(name)
        if not m:
            return None

        ra_h, ra_m, ra_s = int(m.group(1)), int(m.group(2)), int(m.group(3))
        dec_d, dec_m, dec_s = int(m.group(4)), int(m.group(5)), int(m.group(6))
        zoom = int(m.group(7))
        size_px = int(m.group(8)) if m.group(8) else TILE_FULL_PX

        # Convert RA to degrees (hours * 15)
        ra_deg = (ra_h + ra_m / 60.0 + ra_s / 3600.0) * 15.0

        # Convert Dec to degrees
        dec_sign = -1 if dec_d < 0 else 1
        dec_deg = dec_sign * (abs(dec_d) + dec_m / 60.0 + dec_s / 3600.0)

        return TileInfo(
            ra_deg=ra_deg,
            dec_deg=dec_deg,
            zoom=zoom,
            size_px=size_px,
            filepath=filepath,
        )

    @property
    def tile_count(self) -> int:
        """Number of unique sky positions in the cache."""
        return len(self._index)

    def find_tiles(
        self,
        ra_center: float,
        dec_center: float,
        fov_deg: float,
        size_px: int = TILE_FULL_PX,
    ) -> list[TileInfo]:
        """Find tiles whose footprint overlaps the given view.

        Args:
            ra_center: View center RA in degrees.
            dec_center: View center Dec in degrees.
            fov_deg: View field of view in degrees.
            size_px: Desired tile size (2000, 500, 150, or 75).

        Returns:
            List of TileInfo for overlapping tiles.
        """
        # Search radius: half the view FOV + half the tile FOV
        search_radius = fov_deg / 2.0 + TILE_FOV_DEG / 2.0

        results = []
        for (tile_ra, tile_dec), size_dict in self._index.items():
            # Check Dec distance first (cheap)
            dec_dist = abs(tile_dec - dec_center)
            if dec_dist > search_radius:
                continue

            # Check RA distance (account for cos(dec) and wraparound)
            ra_diff = abs(tile_ra - ra_center)
            if ra_diff > 180.0:
                ra_diff = 360.0 - ra_diff
            # Scale RA by cos(dec) for angular distance
            cos_dec = math.cos(math.radians((tile_dec + dec_center) / 2.0))
            ra_dist = ra_diff * cos_dec
            if ra_dist > search_radius:
                continue

            # Pick the requested size, fall back to full res
            tile = size_dict.get(size_px) or size_dict.get(TILE_FULL_PX)
            if tile:
                results.append(tile)

        return results

    def load_tile(self, tile: TileInfo) -> np.ndarray:
        """Load a tile JPEG as a numpy array (LRU cached)."""
        return TileCache._load_tile_cached(str(tile.filepath))

    @staticmethod
    @functools.lru_cache(maxsize=48)
    def _load_tile_cached(filepath: str) -> np.ndarray:
        """Cached tile loader — avoids re-reading JPEGs from disk."""
        img = Image.open(filepath)
        if img.mode != 'RGB':
            img = img.convert('RGB')
        return np.flipud(np.array(img))

    def build_tile_wcs(self, tile: TileInfo) -> WCS:
        """Build a WCS for a tile (LRU cached)."""
        return TileCache._build_tile_wcs_cached(
            tile.ra_deg, tile.dec_deg, tile.size_px
        )

    @staticmethod
    @functools.lru_cache(maxsize=256)
    def _build_tile_wcs_cached(ra_deg: float, dec_deg: float, size_px: int) -> WCS:
        """Cached WCS builder for tiles."""
        w = WCS(naxis=2)
        w.wcs.crpix = [size_px / 2.0 + 0.5, size_px / 2.0 + 0.5]
        w.wcs.crval = [ra_deg, dec_deg]
        w.wcs.ctype = ['RA---STG', 'DEC--STG']
        pixel_scale = TILE_FOV_DEG / size_px
        w.wcs.cd = [
            [-pixel_scale, 0.0],
            [0.0, pixel_scale],
        ]
        return w
