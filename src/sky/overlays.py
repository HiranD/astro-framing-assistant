"""Overlay drawing for the sky canvas (FOV rectangle, etc.)."""

import math
from typing import Optional

import numpy as np
from matplotlib.axes import Axes
from matplotlib.patches import Polygon
from matplotlib.lines import Line2D
from astropy.coordinates import SkyCoord
from astropy.wcs import WCS
import astropy.units as u

from core.camera import CameraProfile


class FovOverlay:
    """Draws a camera FOV rectangle on the sky canvas."""

    def __init__(self) -> None:
        self._artists: list = []

    def draw(
        self,
        ax: Axes,
        ra_deg: float,
        dec_deg: float,
        camera: CameraProfile,
        rotation_deg: float,
        canvas_wcs: WCS,
    ) -> None:
        """Draw the FOV rectangle overlay.

        Args:
            ax: The WCSAxes to draw on.
            ra_deg: Center RA in degrees.
            dec_deg: Center Dec in degrees.
            camera: Camera profile for FOV dimensions.
            rotation_deg: Rotation angle in degrees (N through E).
            canvas_wcs: The canvas WCS for coordinate conversion.
        """
        self.clear()

        fov_w = camera.fov_width_deg
        fov_h = camera.fov_height_deg
        corners = self._compute_corners(ra_deg, dec_deg, fov_w, fov_h, rotation_deg)

        # Convert sky corners to pixel coordinates
        px_corners = []
        for corner in corners:
            x, y = canvas_wcs.world_to_pixel(corner)
            px_corners.append([float(x), float(y)])

        if not px_corners:
            return

        # Draw filled polygon
        poly = Polygon(
            px_corners,
            closed=True,
            facecolor='#4488ff',
            edgecolor='#4488ff',
            alpha=0.08,
            linewidth=0,
            transform=ax.transData,
        )
        ax.add_patch(poly)
        self._artists.append(poly)

        # Draw border
        border_corners = px_corners + [px_corners[0]]  # close the polygon
        xs = [c[0] for c in border_corners]
        ys = [c[1] for c in border_corners]
        border = Line2D(
            xs, ys,
            color='#4488ff',
            alpha=0.7,
            linewidth=1.5,
            transform=ax.transData,
        )
        ax.add_line(border)
        self._artists.append(border)

        # Center crosshair
        cx, cy = canvas_wcs.world_to_pixel(SkyCoord(ra_deg, dec_deg, unit='deg'))
        cx, cy = float(cx), float(cy)
        cross_size = 8
        for dx, dy in [(-cross_size, 0), (cross_size, 0)], [(0, -cross_size), (0, cross_size)]:
            pass
        h_line = Line2D(
            [cx - cross_size, cx + cross_size], [cy, cy],
            color='#4488ff', alpha=0.7, linewidth=1, transform=ax.transData,
        )
        v_line = Line2D(
            [cx, cx], [cy - cross_size, cy + cross_size],
            color='#4488ff', alpha=0.7, linewidth=1, transform=ax.transData,
        )
        ax.add_line(h_line)
        ax.add_line(v_line)
        self._artists.extend([h_line, v_line])

        # FOV label
        label = ax.text(
            px_corners[2][0] + 5, px_corners[2][1] + 5,
            f"{fov_w:.2f}° × {fov_h:.2f}°",
            color='#4488ff', fontsize=8, alpha=0.8,
            transform=ax.transData,
        )
        self._artists.append(label)

    def clear(self) -> None:
        """Remove all FOV overlay artists."""
        for artist in self._artists:
            try:
                artist.remove()
            except ValueError:
                pass
        self._artists.clear()

    def _compute_corners(
        self,
        ra_deg: float,
        dec_deg: float,
        fov_w: float,
        fov_h: float,
        rotation_deg: float,
    ) -> list[SkyCoord]:
        """Compute 4 rotated FOV corners on the sky."""
        rot = math.radians(rotation_deg)
        half_w = fov_w / 2.0
        half_h = fov_h / 2.0
        cos_dec = math.cos(math.radians(dec_deg))

        # Corner offsets in tangent plane (degrees)
        raw_corners = [
            (-half_w, -half_h),
            (half_w, -half_h),
            (half_w, half_h),
            (-half_w, half_h),
        ]

        cos_r = math.cos(rot)
        sin_r = math.sin(rot)

        sky_corners = []
        for dx, dy in raw_corners:
            # Apply rotation
            rx = dx * cos_r - dy * sin_r
            ry = dx * sin_r + dy * cos_r
            # Project onto sphere (RA corrected for cos(dec))
            corner_ra = ra_deg + rx / cos_dec
            corner_dec = dec_deg + ry
            sky_corners.append(SkyCoord(corner_ra, corner_dec, unit='deg'))

        return sky_corners
