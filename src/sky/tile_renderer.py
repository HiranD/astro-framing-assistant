"""Tile renderer — projects cached sky tiles onto the canvas WCS."""

import logging

import numpy as np
from astropy.wcs import WCS
from reproject import reproject_interp

from sky.tile_cache import TileCache

logger = logging.getLogger(__name__)


class TileRenderer:
    """Renders sky tiles from the cache onto a WCS canvas."""

    def __init__(self, tile_cache: TileCache) -> None:
        self._cache = tile_cache

    def render(self, target_wcs: WCS, canvas_shape: tuple[int, int]) -> np.ndarray:
        """Render sky tiles onto the canvas.

        Args:
            target_wcs: The canvas WCS defining the view projection.
            canvas_shape: Output shape as (height, width).

        Returns:
            RGB numpy array with shape (height, width, 3), dtype uint8.
        """
        height, width = canvas_shape

        # Get canvas center and FOV from WCS
        ra_center, dec_center = target_wcs.wcs.crval
        # Estimate FOV from pixel scale and canvas size
        pixel_scale = abs(target_wcs.wcs.cd[0][0])  # deg/pixel (approximate)
        fov_deg = pixel_scale * max(width, height)

        # Find overlapping tiles
        tiles = self._cache.find_tiles(ra_center, dec_center, fov_deg)
        logger.info("Rendering %d tiles for view at RA=%.1f Dec=%.1f FOV=%.1f",
                     len(tiles), ra_center, dec_center, fov_deg)

        if not tiles:
            logger.warning("No tiles found for this view")
            return np.zeros((height, width, 3), dtype=np.uint8)

        # Composite tiles onto canvas
        canvas = np.zeros((height, width, 3), dtype=np.float64)
        coverage = np.zeros((height, width), dtype=np.float64)

        for tile_info in tiles:
            try:
                tile_data = self._cache.load_tile(tile_info)
                tile_wcs = self._cache.build_tile_wcs(tile_info)

                # Reproject each color channel
                for ch in range(3):
                    reprojected, footprint = reproject_interp(
                        (tile_data[:, :, ch].astype(np.float64), tile_wcs),
                        target_wcs,
                        shape_out=(height, width),
                    )
                    # Replace NaN with 0
                    mask = np.isfinite(reprojected)
                    reprojected = np.where(mask, reprojected, 0.0)
                    canvas[:, :, ch] += reprojected
                    if ch == 0:
                        coverage += mask.astype(np.float64)

            except Exception:
                logger.exception("Failed to render tile at RA=%.1f Dec=%.1f",
                                 tile_info.ra_deg, tile_info.dec_deg)

        # Average overlapping regions
        coverage_3d = np.maximum(coverage, 1.0)[:, :, np.newaxis]
        canvas = canvas / coverage_3d
        canvas = np.clip(canvas, 0, 255).astype(np.uint8)

        return canvas
