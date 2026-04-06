"""Sky widget — PyQt6 wrapper around the matplotlib sky canvas with mouse interaction."""

from PyQt6.QtWidgets import QWidget, QVBoxLayout
from PyQt6.QtCore import pyqtSignal, Qt, QTimer
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg

from sky.sky_canvas import SkyCanvas
from sky.tile_cache import TileCache
from core.camera import CameraProfile, DEFAULT_PROFILE


class SkyWidget(QWidget):
    """Widget that displays the sky canvas with pan/zoom mouse handling."""

    cursor_moved = pyqtSignal(float, float)   # ra_deg, dec_deg
    view_changed = pyqtSignal(float, float, float)  # ra_deg, dec_deg, fov_deg

    def __init__(self, tile_cache: TileCache, parent=None) -> None:
        super().__init__(parent)

        self._sky_canvas = SkyCanvas(tile_cache)
        self._mpl_canvas = FigureCanvasQTAgg(self._sky_canvas.figure)
        self._mpl_canvas.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._mpl_canvas)

        # Pan state
        self._dragging = False
        self._drag_screen_x = 0.0
        self._drag_screen_y = 0.0
        self._drag_start_ra = 0.0
        self._drag_start_dec = 0.0
        self._pan_scales = None  # (sx, sy) screen→data pixel ratios
        self._pending_ra = None
        self._pending_dec = None

        # Re-render on resize (debounced)
        self._resize_timer = QTimer()
        self._resize_timer.setSingleShot(True)
        self._resize_timer.setInterval(300)
        self._resize_timer.timeout.connect(self._on_resize_done)

        # Connect matplotlib mouse events
        self._mpl_canvas.mpl_connect('button_press_event', self._on_press)
        self._mpl_canvas.mpl_connect('button_release_event', self._on_release)
        self._mpl_canvas.mpl_connect('motion_notify_event', self._on_motion)

    def show_initial_view(self, ra_deg: float = 10.685, dec_deg: float = 41.269,
                          fov_deg: float = 3.0, camera: CameraProfile = None,
                          rotation: float = 0.0) -> None:
        """Render the initial view."""
        self._sky_canvas.set_view(ra_deg=ra_deg, dec_deg=dec_deg, fov_deg=fov_deg)
        self._sky_canvas.set_camera(camera or DEFAULT_PROFILE, rotation)
        self._emit_view_changed()

    def set_center(self, ra_deg: float, dec_deg: float) -> None:
        """Navigate to a new center position."""
        self._sky_canvas.set_center(ra_deg, dec_deg)
        self._emit_view_changed()

    def set_fov(self, fov_deg: float) -> None:
        """Set the field of view."""
        self._sky_canvas.set_fov(fov_deg)
        self._emit_view_changed()

    def set_camera(self, camera: CameraProfile) -> None:
        """Update the camera profile for FOV overlay."""
        self._sky_canvas.set_camera(camera)

    def set_camera_rotation(self, rotation_deg: float) -> None:
        """Update the camera rotation for FOV overlay."""
        self._sky_canvas.set_camera_rotation(rotation_deg)

    def set_fov_visible(self, visible: bool) -> None:
        """Show or hide the camera FOV overlay."""
        self._sky_canvas.set_fov_visible(visible)

    def set_mosaic(self, h_panels: int, v_panels: int, overlap_pct: float) -> None:
        """Update mosaic parameters."""
        self._sky_canvas.set_mosaic(h_panels, v_panels, overlap_pct)

    @property
    def sky_canvas(self) -> SkyCanvas:
        return self._sky_canvas

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._resize_timer.start()

    def _on_resize_done(self) -> None:
        """Re-render after resize settles."""
        self._sky_canvas._request_render()

    def _emit_view_changed(self) -> None:
        sc = self._sky_canvas
        self.view_changed.emit(sc.ra_deg, sc.dec_deg, sc.fov_deg)

    def _on_press(self, event) -> None:
        """Handle mouse press — start pan."""
        if event.button != 1 or event.inaxes is None:
            return
        self._dragging = True
        self._drag_screen_x = event.x
        self._drag_screen_y = event.y
        self._drag_start_ra = self._sky_canvas.ra_deg
        self._drag_start_dec = self._sky_canvas.dec_deg
        self._pan_scales = self._sky_canvas.start_pan()

    def _on_release(self, event) -> None:
        """Handle mouse release — full re-render at final position."""
        if not self._dragging:
            return
        self._dragging = False
        if event.button != 1:
            return
        if self._pending_ra is not None:
            self._sky_canvas.set_center(self._pending_ra, self._pending_dec)
            self._emit_view_changed()
            self._pending_ra = None
            self._pending_dec = None

    def _on_motion(self, event) -> None:
        """Handle mouse move — pan or cursor tracking."""
        if self._dragging and self._pan_scales is not None:
            # Total screen-pixel offset from drag start
            dx = event.x - self._drag_screen_x
            dy = event.y - self._drag_screen_y
            sx, sy = self._pan_scales

            # Instant visual shift (FOV counter-shifted to stay centered)
            self._sky_canvas.pan_by_screen(dx, dy, sx, sy)

            # Compute new center from shifted view limits
            wcs = self._sky_canvas.wcs
            if wcs is not None:
                dx_data = dx * sx
                dy_data = dy * sy
                xlim = self._sky_canvas._ax.get_xlim()
                ylim = self._sky_canvas._ax.get_ylim()
                cx = (xlim[0] + xlim[1]) / 2
                cy = (ylim[0] + ylim[1]) / 2
                result = wcs.pixel_to_world(cx, cy)
                self._pending_ra = result.ra.deg
                self._pending_dec = result.dec.deg
        elif event.inaxes is not None:
            # Cursor tracking — emit RA/Dec under mouse
            result = self._sky_canvas.pixel_to_world(event.xdata, event.ydata)
            if result:
                self.cursor_moved.emit(result[0], result[1])
