"""Sky widget — PyQt6 wrapper around the matplotlib sky canvas with mouse interaction."""

from PyQt6.QtWidgets import QWidget, QVBoxLayout
from PyQt6.QtCore import pyqtSignal, Qt
from PyQt6.QtGui import QCursor
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
        self._drag_start_x = 0.0
        self._drag_start_y = 0.0
        self._drag_start_ra = 0.0
        self._drag_start_dec = 0.0

        # Connect matplotlib mouse events
        self._mpl_canvas.mpl_connect('scroll_event', self._on_scroll)
        self._mpl_canvas.mpl_connect('button_press_event', self._on_press)
        self._mpl_canvas.mpl_connect('button_release_event', self._on_release)
        self._mpl_canvas.mpl_connect('motion_notify_event', self._on_motion)

    def show_initial_view(self) -> None:
        """Render the initial view centered on M84."""
        self._sky_canvas.set_view(ra_deg=186.27, dec_deg=12.89, fov_deg=3.0)
        self._sky_canvas.set_camera(DEFAULT_PROFILE, 0.0)
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

    @property
    def sky_canvas(self) -> SkyCanvas:
        return self._sky_canvas

    def _emit_view_changed(self) -> None:
        sc = self._sky_canvas
        self.view_changed.emit(sc.ra_deg, sc.dec_deg, sc.fov_deg)

    def _on_scroll(self, event) -> None:
        """Handle mouse wheel zoom."""
        if event.step > 0:
            factor = 1.0 / 1.3  # zoom in
        else:
            factor = 1.3  # zoom out

        new_fov = self._sky_canvas.fov_deg * factor
        new_fov = max(0.1, min(20.0, new_fov))
        self._sky_canvas.set_fov(new_fov)
        self._emit_view_changed()

    def _on_press(self, event) -> None:
        """Handle mouse press — start pan."""
        if event.button != 1 or event.inaxes is None:
            return
        self._dragging = True
        self._drag_start_x = event.xdata
        self._drag_start_y = event.ydata
        self._drag_start_ra = self._sky_canvas.ra_deg
        self._drag_start_dec = self._sky_canvas.dec_deg

    def _on_release(self, event) -> None:
        """Handle mouse release — end pan, re-render."""
        if not self._dragging:
            return
        self._dragging = False
        if event.button != 1:
            return
        # Final render is already done during drag via set_center

    def _on_motion(self, event) -> None:
        """Handle mouse move — pan or cursor tracking."""
        if event.inaxes is None:
            return

        if self._dragging and self._drag_start_x is not None:
            # Compute pixel offset and convert to sky offset
            dx = event.xdata - self._drag_start_x
            dy = event.ydata - self._drag_start_y

            wcs = self._sky_canvas.wcs
            if wcs is not None:
                # Pixel scale from CD matrix (deg/pixel)
                pixel_scale = abs(wcs.wcs.cd[0][0])
                dra = -dx * pixel_scale  # RA increases left
                ddec = -dy * pixel_scale

                new_ra = (self._drag_start_ra + dra) % 360.0
                new_dec = max(-90.0, min(90.0, self._drag_start_dec + ddec))

                self._sky_canvas.set_center(new_ra, new_dec)
                self._emit_view_changed()

                # Reset drag start for incremental panning
                self._drag_start_x = event.xdata
                self._drag_start_y = event.ydata
                self._drag_start_ra = self._sky_canvas.ra_deg
                self._drag_start_dec = self._sky_canvas.dec_deg
        else:
            # Cursor tracking — emit RA/Dec under mouse
            result = self._sky_canvas.pixel_to_world(event.xdata, event.ydata)
            if result:
                self.cursor_moved.emit(result[0], result[1])
