"""Sky canvas — matplotlib Figure with WCSAxes for sky rendering."""

import logging

import numpy as np
import matplotlib
matplotlib.use('Agg')  # Non-interactive backend; PyQt provides the display
from matplotlib.figure import Figure
from astropy.wcs import WCS

from sky.wcs_utils import build_canvas_wcs
from sky.tile_renderer import TileRenderer
from sky.tile_cache import TileCache
from sky.overlays import FovOverlay
from core.camera import CameraProfile

logger = logging.getLogger(__name__)


class SkyCanvas:
    """Manages a matplotlib Figure with WCS-aware axes for sky display."""

    def __init__(self, tile_cache: TileCache) -> None:
        self._tile_cache = tile_cache
        self._renderer = TileRenderer(tile_cache)
        self._figure = Figure(facecolor='black', tight_layout=True)
        self._ax = None
        self._wcs = None
        self._image_artist = None

        # Current view parameters
        self._ra_deg = 186.27   # M84
        self._dec_deg = 12.89
        self._fov_deg = 3.0
        self._rotation_deg = 0.0

        # Overlays
        self._fov_overlay = FovOverlay()
        self._camera = None
        self._camera_rotation = 0.0

    @property
    def figure(self) -> Figure:
        return self._figure

    @property
    def wcs(self) -> WCS:
        return self._wcs

    @property
    def ra_deg(self) -> float:
        return self._ra_deg

    @property
    def dec_deg(self) -> float:
        return self._dec_deg

    @property
    def fov_deg(self) -> float:
        return self._fov_deg

    def set_center(self, ra_deg: float, dec_deg: float) -> None:
        """Update view center and re-render."""
        self._ra_deg = ra_deg % 360.0
        self._dec_deg = max(-90.0, min(90.0, dec_deg))
        self._render()

    def set_fov(self, fov_deg: float) -> None:
        """Update FOV and re-render."""
        self._fov_deg = max(0.1, min(20.0, fov_deg))
        self._render()

    def pixel_to_world(self, x: float, y: float):
        """Convert pixel coordinates to sky coordinates.

        Returns:
            (ra_deg, dec_deg) tuple, or None if WCS not available.
        """
        if self._wcs is None or self._ax is None:
            return None
        try:
            sky = self._wcs.pixel_to_world(x, y)
            return (sky.ra.deg, sky.dec.deg)
        except Exception:
            return None

    def set_view(
        self,
        ra_deg: float,
        dec_deg: float,
        fov_deg: float,
        rotation_deg: float = 0.0,
    ) -> None:
        """Set the view center, FOV, and rotation, then re-render."""
        self._ra_deg = ra_deg
        self._dec_deg = dec_deg
        self._fov_deg = fov_deg
        self._rotation_deg = rotation_deg
        self._render()

    def _render(self) -> None:
        """Render the sky view."""
        # Get canvas size in pixels from figure
        dpi = self._figure.get_dpi()
        fig_w, fig_h = self._figure.get_size_inches()
        width_px = int(fig_w * dpi)
        height_px = int(fig_h * dpi)

        if width_px < 10 or height_px < 10:
            return

        # Build WCS for current view
        self._wcs = build_canvas_wcs(
            self._ra_deg, self._dec_deg,
            self._fov_deg, self._rotation_deg,
            width_px, height_px,
        )

        # Render tiles
        canvas_shape = (height_px, width_px)
        image = self._renderer.render(self._wcs, canvas_shape)

        # Set up axes
        self._figure.clear()
        self._ax = self._figure.add_subplot(111, projection=self._wcs)
        self._ax.set_facecolor('black')

        # Display the rendered image
        self._image_artist = self._ax.imshow(
            image,
            origin='lower',
            interpolation='bilinear',
        )

        # Configure coordinate grid
        overlay = self._ax.get_coords_overlay('icrs')
        overlay[0].set_axislabel('RA (J2000)')
        overlay[1].set_axislabel('Dec (J2000)')
        overlay[0].set_ticks_visible(True)
        overlay[1].set_ticks_visible(True)
        overlay.grid(color='white', alpha=0.3, linestyle='--', linewidth=0.5)

        # Style the tick labels
        overlay[0].set_ticklabel(color='white', size=8)
        overlay[1].set_ticklabel(color='white', size=8)
        overlay[0].set_axislabel_position('b')
        overlay[1].set_axislabel_position('l')

        # Draw overlays
        self._draw_overlays()

        self._figure.canvas.draw_idle()

    def set_camera(self, camera: CameraProfile, rotation_deg: float = None) -> None:
        """Set the camera profile for FOV overlay."""
        self._camera = camera
        if rotation_deg is not None:
            self._camera_rotation = rotation_deg
        self._redraw_overlays()

    def set_camera_rotation(self, rotation_deg: float) -> None:
        """Set camera rotation and redraw overlay."""
        self._camera_rotation = rotation_deg
        self._redraw_overlays()

    def _draw_overlays(self) -> None:
        """Draw all overlays on the current axes."""
        if self._ax is None or self._wcs is None:
            return
        if self._camera is not None:
            self._fov_overlay.draw(
                self._ax, self._ra_deg, self._dec_deg,
                self._camera, self._camera_rotation, self._wcs,
            )

    def _redraw_overlays(self) -> None:
        """Redraw overlays without re-rendering tiles."""
        if self._ax is None or self._wcs is None:
            return
        self._fov_overlay.clear()
        self._draw_overlays()
        self._figure.canvas.draw_idle()
