"""Custom status bar with cursor coordinates and FOV display."""

from PyQt6.QtWidgets import QStatusBar, QLabel
from PyQt6.QtCore import pyqtSlot

from core.coordinates import format_ra, format_dec


class StatusBar(QStatusBar):
    """Status bar showing cursor RA/Dec, FOV, and status messages."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)

        self._cursor_label = QLabel("Cursor: --")
        self._cursor_label.setStyleSheet("font-family: 'Menlo', 'Courier New', monospace; font-size: 12px;")
        self.addWidget(self._cursor_label, 1)

        self._fov_label = QLabel("FOV: --")
        self._fov_label.setStyleSheet("font-family: 'Menlo', 'Courier New', monospace; font-size: 12px;")
        self.addWidget(self._fov_label, 0)

        self._status_label = QLabel("Ready")
        self._status_label.setStyleSheet("font-size: 12px;")
        self.addPermanentWidget(self._status_label, 0)

    @pyqtSlot(float, float)
    def update_cursor(self, ra_deg: float, dec_deg: float) -> None:
        """Update cursor position display."""
        ra_str = format_ra(ra_deg)
        dec_str = format_dec(dec_deg)
        self._cursor_label.setText(f"Cursor: {ra_str}  {dec_str}")

    def update_fov(self, ra_deg: float, dec_deg: float, fov_deg: float) -> None:
        """Update FOV display (called on view change)."""
        self._fov_label.setText(f"FOV: {fov_deg:.2f}°")

    def set_status(self, message: str) -> None:
        """Set status message."""
        self._status_label.setText(message)

    def set_rendering(self, active: bool) -> None:
        """Show or clear rendering indicator."""
        if active:
            self._status_label.setText("Rendering...")
            self._status_label.setStyleSheet("font-size: 12px; font-weight: bold; color: #ff8844;")
        else:
            self._status_label.setText("Ready")
            self._status_label.setStyleSheet("font-size: 12px; font-weight: bold; color: #44ff44;")
