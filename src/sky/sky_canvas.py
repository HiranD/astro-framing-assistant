"""Sky canvas — matplotlib Figure with WCSAxes for sky rendering."""

import logging

import numpy as np
import matplotlib
matplotlib.use('Agg')  # Non-interactive backend; PyQt provides the display
from matplotlib.figure import Figure
from matplotlib.lines import Line2D
from matplotlib.patches import Polygon
from astropy.wcs import WCS
from PyQt6.QtCore import QObject, pyqtSignal

from sky.wcs_utils import build_canvas_wcs
from sky.tile_renderer import TileRenderer
from sky.tile_cache import TileCache
from sky.render_worker import RenderWorker
from sky.overlays import FovOverlay, MosaicOverlay, CatalogOverlay, UserImageOverlay
from core.camera import CameraProfile
from core.mosaic import MosaicPlan, compute_mosaic
from core.catalog import CatalogSearchEngine
from core.memlog import log_snapshot

logger = logging.getLogger(__name__)


class SkyCanvas(QObject):
    """Manages a matplotlib Figure with WCS-aware axes for sky display."""

    rendering_started = pyqtSignal()
    rendering_finished = pyqtSignal()

    def __init__(self, tile_cache: TileCache) -> None:
        super().__init__()
        self._tile_cache = tile_cache
        self._renderer = TileRenderer(tile_cache)
        self._figure = Figure(facecolor='black')
        self._figure.subplots_adjust(left=0, right=1, top=1, bottom=0)
        self._ax = None
        self._wcs = None
        self._image_artist = None

        # Current view parameters
        self._ra_deg = 10.685   # M31
        self._dec_deg = 41.269
        self._fov_deg = 3.0
        self._rotation_deg = 0.0

        # Overlays
        self._fov_overlay = FovOverlay()
        self._mosaic_overlay = MosaicOverlay()
        self._catalog_overlay = CatalogOverlay()
        self._user_image_overlay = UserImageOverlay()
        self._user_images: list = []
        self._catalog_engine = None
        self._camera = None
        self._camera_rotation = 0.0
        self._show_fov = True
        self._h_panels = 1
        self._v_panels = 1
        self._overlap_pct = 10.0
        self._mosaic_plan = None

        # Threaded rendering state
        self._render_worker = None
        self._render_id = 0  # Incremented each request, used for stale detection
        self._pending_render = False  # Latches requests that arrive while a worker is in flight

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

    def start_pan(self) -> tuple[float, float] | None:
        """Prepare for live panning. Returns screen-to-data pixel scale factors."""
        if self._ax is None:
            return None
        self._pan_xlim = self._ax.get_xlim()
        self._pan_ylim = self._ax.get_ylim()
        bbox = self._ax.get_window_extent()
        if bbox.width < 1 or bbox.height < 1:
            return None
        # Clear non-FOV overlays (catalog labels, user images)
        self._catalog_overlay.clear()
        self._user_image_overlay.clear()
        # Store FOV artist original positions for counter-shifting
        self._pan_fov_origins = []
        for artist in self._fov_overlay._artists:
            if isinstance(artist, Polygon):
                self._pan_fov_origins.append(
                    ('poly', artist, artist.get_xy().copy()))
            elif isinstance(artist, Line2D):
                self._pan_fov_origins.append(
                    ('line', artist,
                     (list(artist.get_xdata()), list(artist.get_ydata()))))
            elif hasattr(artist, 'get_position'):
                self._pan_fov_origins.append(
                    ('text', artist, artist.get_position()))
        # Same for mosaic overlay
        self._pan_mosaic_origins = []
        for artist in self._mosaic_overlay._artists:
            if isinstance(artist, Polygon):
                self._pan_mosaic_origins.append(
                    ('poly', artist, artist.get_xy().copy()))
            elif isinstance(artist, Line2D):
                self._pan_mosaic_origins.append(
                    ('line', artist,
                     (list(artist.get_xdata()), list(artist.get_ydata()))))
            elif hasattr(artist, 'get_position'):
                self._pan_mosaic_origins.append(
                    ('text', artist, artist.get_position()))
        sx = (self._pan_xlim[1] - self._pan_xlim[0]) / bbox.width
        sy = (self._pan_ylim[1] - self._pan_ylim[0]) / bbox.height
        return (sx, sy)

    def pan_by_screen(self, dx: float, dy: float, sx: float, sy: float) -> None:
        """Shift displayed view by screen-pixel offset from pan start (no re-render)."""
        if self._ax is None or not hasattr(self, '_pan_xlim'):
            return
        dx_d = dx * sx
        dy_d = dy * sy
        self._ax.set_xlim(self._pan_xlim[0] - dx_d, self._pan_xlim[1] - dx_d)
        self._ax.set_ylim(self._pan_ylim[0] - dy_d, self._pan_ylim[1] - dy_d)
        # Counter-shift FOV/mosaic artists to keep them at screen center
        for origins in (self._pan_fov_origins, self._pan_mosaic_origins):
            for kind, artist, orig in origins:
                if kind == 'poly':
                    artist.set_xy(orig + np.array([-dx_d, -dy_d]))
                elif kind == 'line':
                    artist.set_xdata([x - dx_d for x in orig[0]])
                    artist.set_ydata([y - dy_d for y in orig[1]])
                elif kind == 'text':
                    artist.set_position((orig[0] - dx_d, orig[1] - dy_d))
        self._figure.canvas.draw_idle()

    def set_center(self, ra_deg: float, dec_deg: float) -> None:
        """Update view center and re-render."""
        self._ra_deg = ra_deg % 360.0
        self._dec_deg = max(-90.0, min(90.0, dec_deg))
        self._request_render()

    def set_fov(self, fov_deg: float) -> None:
        """Update FOV and re-render."""
        self._fov_deg = max(0.1, min(20.0, fov_deg))
        self._request_render()

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
        self._request_render()

    def _request_render(self) -> None:
        """Request a tile render on a background thread."""
        # Coalesce: if a worker is already in flight, latch a pending flag and
        # return. _on_render_complete will re-fire once the current render
        # finishes, picking up whatever ra/dec/fov/canvas size is current then.
        # Without this, rapid pan/resize bursts spawn concurrent workers that
        # each allocate ~100+ MB of float64 reproject buffers.
        if self._render_worker is not None and self._render_worker.isRunning():
            self._pending_render = True
            return

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

        canvas_shape = (height_px, width_px)

        # Increment render ID for stale detection
        self._render_id += 1
        current_id = self._render_id

        ti = TileCache._load_tile_cached.cache_info()
        log_snapshot(
            "render_start",
            id=current_id,
            ra=f"{self._ra_deg:.2f}",
            dec=f"{self._dec_deg:.2f}",
            fov=f"{self._fov_deg:.2f}",
            canvas=f"{width_px}x{height_px}",
            tiles=f"{ti.currsize}/{ti.maxsize}",
            thits=ti.hits,
            tmiss=ti.misses,
            n_user_imgs=len(self._user_images),
        )

        # Launch background render
        self._render_worker = RenderWorker(
            self._renderer, self._wcs, canvas_shape,
        )
        self._render_worker.finished.connect(
            lambda img, wcs: self._on_render_complete(img, wcs, current_id)
        )
        self.rendering_started.emit()
        self._render_worker.start()

    def shutdown(self) -> None:
        """Stop any running render worker. Call before closing the app."""
        if self._render_worker is not None and self._render_worker.isRunning():
            self._render_worker.wait(3000)  # wait up to 3 seconds
            if self._render_worker.isRunning():
                self._render_worker.terminate()
                self._render_worker.wait(1000)

    def _on_render_complete(self, image: np.ndarray, wcs: WCS,
                            render_id: int) -> None:
        """Handle completed render on main thread (all matplotlib here)."""
        # Discard stale results — a newer render was requested
        if render_id != self._render_id:
            return

        # Set up axes
        self._figure.clear()
        self._figure.subplots_adjust(left=0, right=1, top=1, bottom=0)
        self._ax = self._figure.add_subplot(111, projection=self._wcs)
        self._ax.set_facecolor('black')

        # Display the rendered image (low zorder so frame/overlays draw on top)
        self._image_artist = self._ax.imshow(
            image,
            origin='lower',
            interpolation='bilinear',
            zorder=0,
        )

        # Hide axes frame — sky fills edge to edge
        self._ax.coords.frame.set_linewidth(0)
        self._ax.coords.frame.set_color('none')

        # Configure coordinate grid
        overlay = self._ax.get_coords_overlay('icrs')
        overlay[0].set_axislabel('')
        overlay[1].set_axislabel('')
        overlay[0].set_ticks_visible(True)
        overlay[1].set_ticks_visible(True)
        overlay.grid(color='white', alpha=0.3, linestyle='--', linewidth=0.5)

        # Place tick labels inside the axes frame
        overlay[0].set_ticklabel(color='white', size=7, pad=-15)
        overlay[1].set_ticklabel(color='white', size=7, pad=-30)
        overlay[1].ticklabels.set_rotation(0)  # horizontal Dec labels
        overlay[0].set_ticklabel_position('t')
        overlay[1].set_ticklabel_position('r')

        # Draw overlays
        self._recompute_mosaic()
        self._draw_overlays()

        self._figure.canvas.draw_idle()

        ti = TileCache._load_tile_cached.cache_info()
        ax = self._ax
        log_snapshot(
            "render_done",
            id=render_id,
            tiles=f"{ti.currsize}/{ti.maxsize}",
            thits=ti.hits,
            tmiss=ti.misses,
            imgs=len(ax.images),
            patches=len(ax.patches),
            lines=len(ax.lines),
            texts=len(ax.texts),
        )
        self.rendering_finished.emit()

        # Drain any request that arrived while this render was in flight.
        if self._pending_render:
            self._pending_render = False
            self._request_render()

    def set_camera(self, camera: CameraProfile, rotation_deg: float = None) -> None:
        """Set the camera profile for FOV overlay."""
        self._camera = camera
        if rotation_deg is not None:
            self._camera_rotation = rotation_deg
        self._recompute_mosaic()
        self._redraw_overlays()

    def set_camera_rotation(self, rotation_deg: float) -> None:
        """Set camera rotation and redraw overlay."""
        self._camera_rotation = rotation_deg
        self._recompute_mosaic()
        self._redraw_overlays()

    def set_fov_visible(self, visible: bool) -> None:
        """Show or hide the camera FOV overlay."""
        self._show_fov = visible
        self._redraw_overlays()

    def set_mosaic(self, h_panels: int, v_panels: int, overlap_pct: float) -> None:
        """Set mosaic parameters and redraw overlay."""
        self._h_panels = max(1, h_panels)
        self._v_panels = max(1, v_panels)
        self._overlap_pct = overlap_pct
        self._recompute_mosaic()
        self._redraw_overlays()

    @property
    def mosaic_plan(self) -> MosaicPlan:
        return self._mosaic_plan

    def _recompute_mosaic(self) -> None:
        """Recompute the mosaic plan from current state."""
        if self._camera is None:
            self._mosaic_plan = None
            return
        self._mosaic_plan = compute_mosaic(
            self._ra_deg, self._dec_deg,
            self._camera.fov_width_deg, self._camera.fov_height_deg,
            self._h_panels, self._v_panels,
            self._overlap_pct, self._camera_rotation,
        )

    def set_catalog_engine(self, engine: CatalogSearchEngine) -> None:
        """Set the catalog engine for label overlay."""
        self._catalog_engine = engine

    def set_user_images(self, images: list) -> None:
        """Set the list of user images for overlay."""
        self._user_images = images
        self._redraw_overlays()

    def update_user_image(self, filepath: str, **kwargs) -> None:
        """Update properties of a single user image."""
        for img in self._user_images:
            if str(img.filepath) == filepath:
                for k, v in kwargs.items():
                    setattr(img, k, v)
                break
        self._redraw_overlays()

    def _draw_overlays(self) -> None:
        """Draw all overlays on the current axes."""
        if self._ax is None or self._wcs is None:
            return

        # User images (draw first so FOV/mosaic appear on top)
        if self._user_images:
            dpi = self._figure.get_dpi()
            fig_w, fig_h = self._figure.get_size_inches()
            canvas_shape = (int(fig_h * dpi), int(fig_w * dpi))
            self._user_image_overlay.draw(
                self._ax, self._wcs, self._user_images, canvas_shape,
            )

        # Catalog labels
        if self._catalog_engine is not None:
            self._catalog_overlay.draw(
                self._ax, self._wcs, self._fov_deg,
                self._catalog_engine, self._ra_deg, self._dec_deg,
            )

        if self._camera is None or not self._show_fov:
            return

        is_mosaic = self._h_panels > 1 or self._v_panels > 1

        if is_mosaic and self._mosaic_plan is not None:
            self._mosaic_overlay.draw(
                self._ax, self._mosaic_plan, self._camera, self._wcs,
            )
        else:
            self._fov_overlay.draw(
                self._ax, self._ra_deg, self._dec_deg,
                self._camera, self._camera_rotation, self._wcs,
            )

    def _redraw_overlays(self) -> None:
        """Redraw overlays without re-rendering tiles."""
        if self._ax is None or self._wcs is None:
            return
        self._fov_overlay.clear()
        self._mosaic_overlay.clear()
        self._catalog_overlay.clear()
        self._user_image_overlay.clear()
        self._draw_overlays()
        self._figure.canvas.draw_idle()
