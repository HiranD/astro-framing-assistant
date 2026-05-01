"""Overlay drawing for the sky canvas (FOV rectangle, etc.)."""

import math
from typing import Optional

import numpy as np
from matplotlib.axes import Axes
from matplotlib.patches import Polygon, Ellipse
from matplotlib.lines import Line2D
from astropy.coordinates import SkyCoord
from astropy.wcs import WCS
import astropy.units as u

from core.camera import CameraProfile
from core.mosaic import MosaicPlan
from core.catalog import CatalogSearchEngine, CatalogObject
from core.image_loader import ImageData, downsample_for_display
from core import memlog
from core.memlog import log_snapshot


def _compute_fov_corners(
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
    cos_dec = max(math.cos(math.radians(dec_deg)), 0.01)

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
        rx = dx * cos_r - dy * sin_r
        ry = dx * sin_r + dy * cos_r
        corner_ra = ra_deg + rx / cos_dec
        corner_dec = dec_deg + ry
        sky_corners.append(SkyCoord(corner_ra, corner_dec, unit='deg'))

    return sky_corners


def _corners_to_pixels(corners: list[SkyCoord], canvas_wcs: WCS) -> list[list[float]]:
    """Convert sky corners to pixel coordinates."""
    px = []
    for corner in corners:
        x, y = canvas_wcs.world_to_pixel(corner)
        px.append([float(x), float(y)])
    return px


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
        corners = _compute_fov_corners(ra_deg, dec_deg, fov_w, fov_h, rotation_deg)
        px_corners = _corners_to_pixels(corners, canvas_wcs)

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
            except Exception:
                pass
        self._artists.clear()



class MosaicOverlay:
    """Draws a mosaic grid of panel rectangles on the sky canvas."""

    def __init__(self) -> None:
        self._artists: list = []

    def draw(
        self,
        ax: Axes,
        plan: MosaicPlan,
        camera: CameraProfile,
        canvas_wcs: WCS,
    ) -> None:
        """Draw all mosaic panels with labels and bounding box."""
        self.clear()

        fov_w = camera.fov_width_deg
        fov_h = camera.fov_height_deg

        for panel in plan.panels:
            corners = _compute_fov_corners(
                panel.ra_deg, panel.dec_deg,
                fov_w, fov_h, panel.rotation_deg,
            )
            px_corners = _corners_to_pixels(corners, canvas_wcs)

            # Panel border
            closed = px_corners + [px_corners[0]]
            xs = [c[0] for c in closed]
            ys = [c[1] for c in closed]
            border = Line2D(
                xs, ys,
                color='#4488ff', alpha=0.6, linewidth=1.0,
                transform=ax.transData,
            )
            ax.add_line(border)
            self._artists.append(border)

            # Semi-transparent fill
            poly = Polygon(
                px_corners, closed=True,
                facecolor='#4488ff', alpha=0.04, linewidth=0,
                transform=ax.transData,
            )
            ax.add_patch(poly)
            self._artists.append(poly)

            # Panel label at center
            cx = sum(c[0] for c in px_corners) / 4.0
            cy = sum(c[1] for c in px_corners) / 4.0
            label = ax.text(
                cx, cy, panel.label,
                color='white', fontsize=7, alpha=0.7,
                ha='center', va='center',
                transform=ax.transData,
            )
            self._artists.append(label)

        # Bounding box around entire mosaic
        all_corners = []
        for panel in plan.panels:
            corners = _compute_fov_corners(
                panel.ra_deg, panel.dec_deg,
                fov_w, fov_h, panel.rotation_deg,
            )
            all_corners.extend(_corners_to_pixels(corners, canvas_wcs))

        if all_corners:
            min_x = min(c[0] for c in all_corners)
            max_x = max(c[0] for c in all_corners)
            min_y = min(c[1] for c in all_corners)
            max_y = max(c[1] for c in all_corners)
            bbox = Line2D(
                [min_x, max_x, max_x, min_x, min_x],
                [min_y, min_y, max_y, max_y, min_y],
                color='white', alpha=0.4, linewidth=1.0,
                linestyle='--', transform=ax.transData,
            )
            ax.add_line(bbox)
            self._artists.append(bbox)

        # Center crosshair
        center = SkyCoord(plan.center_ra, plan.center_dec, unit='deg')
        cx, cy = canvas_wcs.world_to_pixel(center)
        cx, cy = float(cx), float(cy)
        cross_size = 10
        for coords in [([cx - cross_size, cx + cross_size], [cy, cy]),
                       ([cx, cx], [cy - cross_size, cy + cross_size])]:
            line = Line2D(
                coords[0], coords[1],
                color='#ff6644', alpha=0.8, linewidth=1.5,
                transform=ax.transData,
            )
            ax.add_line(line)
            self._artists.append(line)

        # Total FOV label
        total_label = ax.text(
            max_x + 5, max_y + 5,
            f"Mosaic: {plan.total_fov_w_deg:.2f}° × {plan.total_fov_h_deg:.2f}°",
            color='white', fontsize=8, alpha=0.7,
            transform=ax.transData,
        )
        self._artists.append(total_label)

    def clear(self) -> None:
        for artist in self._artists:
            try:
                artist.remove()
            except Exception:
                pass
        self._artists.clear()


class CatalogOverlay:
    """Draws catalog object labels and size ellipses on the sky canvas."""

    def __init__(self) -> None:
        self._artists: list = []
        self._enabled = True

    def set_enabled(self, enabled: bool) -> None:
        self._enabled = enabled

    def draw(
        self,
        ax: Axes,
        canvas_wcs: WCS,
        fov_deg: float,
        catalog_engine: CatalogSearchEngine,
        ra_deg: float,
        dec_deg: float,
    ) -> None:
        """Draw catalog labels and ellipses for objects in the current view."""
        self.clear()

        if not self._enabled or catalog_engine is None:
            return

        # Determine magnitude limit based on FOV
        if fov_deg > 10:
            mag_limit = 8.0
        elif fov_deg > 3:
            mag_limit = 12.0
        elif fov_deg > 1:
            mag_limit = 15.0
        else:
            mag_limit = None

        objects = catalog_engine.search_region(
            ra_deg, dec_deg, fov_deg * 0.7, mag_limit=mag_limit,
        )

        # Sort by magnitude (brightest first) for label priority
        objects.sort(key=lambda o: o.magnitude if o.magnitude is not None else 99)

        # Pixel scale for size ellipses
        pixel_scale = abs(canvas_wcs.wcs.cd[0][0])  # deg/pixel
        pix_per_arcmin = 1.0 / (pixel_scale * 60.0)

        # Track label positions to avoid overlap
        label_boxes = []
        max_labels = 60

        for obj in objects[:max_labels * 2]:
            try:
                coord = SkyCoord(obj.ra_deg, obj.dec_deg, unit='deg')
                px, py = canvas_wcs.world_to_pixel(coord)
                px, py = float(px), float(py)
            except Exception:
                continue

            # Size ellipse
            if obj.major_axis_arcmin and obj.major_axis_arcmin > 0:
                w = obj.major_axis_arcmin * pix_per_arcmin
                h = (obj.minor_axis_arcmin or obj.major_axis_arcmin) * pix_per_arcmin
                if w > 3:  # Only draw if visible
                    pa = obj.position_angle if obj.position_angle is not None else 0
                    ellipse = Ellipse(
                        xy=(px, py), width=w, height=h, angle=90 + pa,
                        fill=False, edgecolor='cyan', alpha=0.3,
                        linewidth=0.7, transform=ax.transData,
                    )
                    ax.add_patch(ellipse)
                    self._artists.append(ellipse)

            # Label (check overlap)
            if len(label_boxes) >= max_labels:
                continue

            lx, ly = px + 8, py + 8
            overlaps = False
            for bx, by in label_boxes:
                if abs(lx - bx) < 60 and abs(ly - by) < 12:
                    overlaps = True
                    break

            if not overlaps:
                display = obj.display_name or obj.name
                if obj.catalog == 'Messier':
                    display = f"M{obj.catalog_number.lstrip('0')}"

                label = ax.text(
                    lx, ly, display,
                    color='#aaddff', fontsize=6, alpha=0.7,
                    transform=ax.transData,
                )
                self._artists.append(label)
                label_boxes.append((lx, ly))

    def clear(self) -> None:
        for artist in self._artists:
            try:
                artist.remove()
            except Exception:
                pass
        self._artists.clear()


class UserImageOverlay:
    """Draws user image footprints and/or reprojected image data."""

    def __init__(self) -> None:
        self._artists: list = []

    def draw(
        self,
        ax: Axes,
        canvas_wcs: WCS,
        images: list[ImageData],
        canvas_shape: tuple[int, int],
    ) -> None:
        """Draw user image overlays."""
        self.clear()

        for img in images:
            if not img.visible or img.wcs is None:
                continue
            if img.show_full:
                self._draw_full(ax, canvas_wcs, img, canvas_shape)
            self._draw_footprint(ax, canvas_wcs, img)

    def _draw_footprint(self, ax: Axes, canvas_wcs: WCS, img: ImageData) -> None:
        """Draw polygon outline from WCS footprint."""
        try:
            sky_corners = img.wcs.calc_footprint()
        except Exception:
            return

        px_corners = []
        for ra, dec in sky_corners:
            try:
                coord = SkyCoord(ra, dec, unit='deg')
                x, y = canvas_wcs.world_to_pixel(coord)
                px_corners.append([float(x), float(y)])
            except Exception:
                return

        if len(px_corners) < 3:
            return

        # Filled polygon
        poly = Polygon(
            px_corners, closed=True,
            facecolor='#ff8844', edgecolor='#ff8844',
            alpha=0.06, linewidth=0,
            transform=ax.transData,
        )
        ax.add_patch(poly)
        self._artists.append(poly)

        # Border
        closed = px_corners + [px_corners[0]]
        border = Line2D(
            [c[0] for c in closed], [c[1] for c in closed],
            color='#ff8844', alpha=0.7, linewidth=1.5,
            linestyle='--', transform=ax.transData,
        )
        ax.add_line(border)
        self._artists.append(border)

        # Label at center
        cx = sum(c[0] for c in px_corners) / len(px_corners)
        cy = sum(c[1] for c in px_corners) / len(px_corners)
        label = ax.text(
            cx, cy, img.label,
            color='#ff8844', fontsize=8, alpha=0.8,
            ha='center', va='center',
            transform=ax.transData,
        )
        self._artists.append(label)

    def _draw_full(self, ax: Axes, canvas_wcs: WCS, img: ImageData,
                   canvas_shape: tuple[int, int]) -> None:
        """Reproject and display the user image."""
        from reproject import reproject_interp

        try:
            display_data, factor = downsample_for_display(img.data)
            log_snapshot(
                "user_img_full_enter",
                label=img.label,
                factor=factor,
                ds=f"{display_data.shape[0]}x{display_data.shape[1]}",
                canvas=f"{canvas_shape[0]}x{canvas_shape[1]}",
            )

            # Build downsampled WCS
            if factor > 1:
                ds_wcs = img.wcs.deepcopy()
                ds_wcs.wcs.crpix = ds_wcs.wcs.crpix / factor
                if hasattr(ds_wcs.wcs, 'cd') and ds_wcs.wcs.cd is not None:
                    ds_wcs.wcs.cd = ds_wcs.wcs.cd * factor
                elif hasattr(ds_wcs.wcs, 'cdelt'):
                    ds_wcs.wcs.cdelt = ds_wcs.wcs.cdelt * factor
            else:
                ds_wcs = img.wcs

            height, width = canvas_shape
            memlog.check_ceiling("user_img_rgb_alloc")
            rgb_out = np.zeros((height, width, 3), dtype=np.float32)

            for ch in range(min(3, display_data.shape[2])):
                try:
                    reprojected, _ = reproject_interp(
                        (display_data[:, :, ch].astype(np.float64), ds_wcs),
                        canvas_wcs, shape_out=(height, width),
                    )
                    mask = np.isfinite(reprojected)
                    rgb_out[:, :, ch] = np.where(mask, reprojected, 0.0)
                except Exception:
                    pass
                log_snapshot("user_img_channel", label=img.label, ch=ch)

            artist = ax.imshow(
                rgb_out, origin='lower', alpha=img.opacity,
                interpolation='bilinear',
            )
            self._artists.append(artist)
            log_snapshot("user_img_full_exit", label=img.label)
        except MemoryError:
            log_snapshot("user_img_full_aborted", label=img.label, reason="ceiling")

    def clear(self) -> None:
        for artist in self._artists:
            try:
                artist.remove()
            except Exception:
                pass
        self._artists.clear()
