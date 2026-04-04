"""Control panel — left sidebar with target, coordinates, camera, and FOV controls."""

import logging

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QDoubleSpinBox, QSpinBox, QGroupBox, QFormLayout,
)
from PyQt6.QtCore import pyqtSignal, Qt, QThread, pyqtSlot

from core.coordinates import (
    resolve_name, parse_ra, parse_dec, format_ra, format_dec,
    NameResolveError,
)
from core.camera import CameraProfile, DEFAULT_PROFILE

logger = logging.getLogger(__name__)


class _NameResolveWorker(QThread):
    """Background thread for name resolution."""
    resolved = pyqtSignal(float, float, str)
    error = pyqtSignal(str)

    def __init__(self, name: str) -> None:
        super().__init__()
        self._name = name

    def run(self) -> None:
        try:
            coord = resolve_name(self._name)
            self.resolved.emit(coord.ra.deg, coord.dec.deg, self._name)
        except NameResolveError as e:
            self.error.emit(str(e))


class ControlPanel(QWidget):
    """Left panel with target search, coordinates, camera params, and FOV."""

    target_changed = pyqtSignal(float, float)
    fov_changed = pyqtSignal(float)
    camera_changed = pyqtSignal(object)      # CameraProfile
    rotation_changed = pyqtSignal(float)
    mosaic_changed = pyqtSignal(int, int, float)  # h_panels, v_panels, overlap_pct

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setFixedWidth(300)
        self._worker = None
        self._updating = False

        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignmentFlag.AlignTop)

        # --- Target Search ---
        search_group = QGroupBox("Target")
        search_layout = QVBoxLayout(search_group)

        name_row = QHBoxLayout()
        self._name_edit = QLineEdit()
        self._name_edit.setPlaceholderText("Object name (e.g. M31)")
        self._name_edit.returnPressed.connect(self._on_search)
        self._search_btn = QPushButton("Go")
        self._search_btn.clicked.connect(self._on_search)
        name_row.addWidget(self._name_edit)
        name_row.addWidget(self._search_btn)
        search_layout.addLayout(name_row)

        self._search_status = QLabel("")
        self._search_status.setStyleSheet("color: gray; font-size: 11px;")
        search_layout.addWidget(self._search_status)

        layout.addWidget(search_group)

        # --- Coordinates ---
        coord_group = QGroupBox("Coordinates")
        coord_layout = QFormLayout(coord_group)

        self._ra_edit = QLineEdit()
        self._ra_edit.setPlaceholderText("HH:MM:SS or degrees")
        coord_layout.addRow("RA:", self._ra_edit)

        self._dec_edit = QLineEdit()
        self._dec_edit.setPlaceholderText("±DD:MM:SS or degrees")
        coord_layout.addRow("Dec:", self._dec_edit)

        go_btn = QPushButton("Navigate")
        go_btn.clicked.connect(self._on_go_coords)
        coord_layout.addRow(go_btn)

        layout.addWidget(coord_group)

        # --- Camera ---
        cam_group = QGroupBox("Camera")
        cam_layout = QFormLayout(cam_group)

        self._width_spin = QSpinBox()
        self._width_spin.setRange(1, 20000)
        self._width_spin.setValue(DEFAULT_PROFILE.sensor_width_px)
        self._width_spin.setSuffix(" px")
        self._width_spin.valueChanged.connect(self._on_camera_param_changed)
        cam_layout.addRow("Width:", self._width_spin)

        self._height_spin = QSpinBox()
        self._height_spin.setRange(1, 20000)
        self._height_spin.setValue(DEFAULT_PROFILE.sensor_height_px)
        self._height_spin.setSuffix(" px")
        self._height_spin.valueChanged.connect(self._on_camera_param_changed)
        cam_layout.addRow("Height:", self._height_spin)

        self._pixel_size_spin = QDoubleSpinBox()
        self._pixel_size_spin.setRange(0.1, 20.0)
        self._pixel_size_spin.setDecimals(2)
        self._pixel_size_spin.setSingleStep(0.01)
        self._pixel_size_spin.setValue(DEFAULT_PROFILE.pixel_size_um)
        self._pixel_size_spin.setSuffix(" µm")
        self._pixel_size_spin.valueChanged.connect(self._on_camera_param_changed)
        cam_layout.addRow("Pixel Size:", self._pixel_size_spin)

        self._focal_spin = QDoubleSpinBox()
        self._focal_spin.setRange(50, 10000)
        self._focal_spin.setDecimals(1)
        self._focal_spin.setSingleStep(10)
        self._focal_spin.setValue(DEFAULT_PROFILE.focal_length_mm)
        self._focal_spin.setSuffix(" mm")
        self._focal_spin.valueChanged.connect(self._on_camera_param_changed)
        cam_layout.addRow("Focal Length:", self._focal_spin)

        self._fov_label = QLabel()
        self._fov_label.setStyleSheet("color: #4488ff; font-size: 11px;")
        cam_layout.addRow("FOV:", self._fov_label)

        self._scale_label = QLabel()
        self._scale_label.setStyleSheet("color: #4488ff; font-size: 11px;")
        cam_layout.addRow("Scale:", self._scale_label)

        # Rotation
        self._rotation_spin = QDoubleSpinBox()
        self._rotation_spin.setRange(0, 360)
        self._rotation_spin.setDecimals(1)
        self._rotation_spin.setSingleStep(1.0)
        self._rotation_spin.setValue(0.0)
        self._rotation_spin.setSuffix("°")
        self._rotation_spin.setWrapping(True)
        self._rotation_spin.valueChanged.connect(self._on_rotation_changed)
        cam_layout.addRow("Rotation:", self._rotation_spin)

        layout.addWidget(cam_group)

        # --- Mosaic ---
        mosaic_group = QGroupBox("Mosaic")
        mosaic_layout = QFormLayout(mosaic_group)

        self._h_panels_spin = QSpinBox()
        self._h_panels_spin.setRange(1, 10)
        self._h_panels_spin.setValue(1)
        self._h_panels_spin.valueChanged.connect(self._on_mosaic_changed)
        mosaic_layout.addRow("H Panels:", self._h_panels_spin)

        self._v_panels_spin = QSpinBox()
        self._v_panels_spin.setRange(1, 10)
        self._v_panels_spin.setValue(1)
        self._v_panels_spin.valueChanged.connect(self._on_mosaic_changed)
        mosaic_layout.addRow("V Panels:", self._v_panels_spin)

        self._overlap_spin = QDoubleSpinBox()
        self._overlap_spin.setRange(0, 50)
        self._overlap_spin.setDecimals(1)
        self._overlap_spin.setSingleStep(1.0)
        self._overlap_spin.setValue(10.0)
        self._overlap_spin.setSuffix(" %")
        self._overlap_spin.valueChanged.connect(self._on_mosaic_changed)
        mosaic_layout.addRow("Overlap:", self._overlap_spin)

        self._mosaic_fov_label = QLabel("--")
        self._mosaic_fov_label.setStyleSheet("color: #4488ff; font-size: 11px;")
        mosaic_layout.addRow("Total:", self._mosaic_fov_label)

        self._export_btn = QPushButton("Copy Coords to Clipboard")
        self._export_btn.clicked.connect(self._on_export)
        mosaic_layout.addRow(self._export_btn)

        layout.addWidget(mosaic_group)

        # --- Field of View ---
        fov_group = QGroupBox("View FOV")
        fov_layout = QFormLayout(fov_group)

        self._fov_spin = QDoubleSpinBox()
        self._fov_spin.setRange(0.1, 20.0)
        self._fov_spin.setSingleStep(0.1)
        self._fov_spin.setDecimals(2)
        self._fov_spin.setSuffix("°")
        self._fov_spin.setValue(3.0)
        self._fov_spin.valueChanged.connect(self._on_fov_changed)
        fov_layout.addRow("FOV:", self._fov_spin)

        layout.addWidget(fov_group)
        layout.addStretch()

        # Initial FOV label update
        self._update_fov_labels()

    def _build_camera(self) -> CameraProfile:
        """Build a CameraProfile from current spinbox values."""
        return CameraProfile(
            name="Custom",
            sensor_width_px=self._width_spin.value(),
            sensor_height_px=self._height_spin.value(),
            pixel_size_um=self._pixel_size_spin.value(),
            focal_length_mm=self._focal_spin.value(),
        )

    def _update_fov_labels(self) -> None:
        """Update the computed FOV and pixel scale labels."""
        cam = self._build_camera()
        self._fov_label.setText(f"{cam.fov_width_deg:.2f}° × {cam.fov_height_deg:.2f}°")
        self._scale_label.setText(f"{cam.pixel_scale_arcsec:.2f} arcsec/px")

    def update_display(self, ra_deg: float, dec_deg: float, fov_deg: float) -> None:
        """Update displayed coordinates and FOV (called when view changes)."""
        self._updating = True
        self._ra_edit.setText(format_ra(ra_deg))
        self._dec_edit.setText(format_dec(dec_deg))
        self._fov_spin.setValue(fov_deg)
        self._updating = False

    def _on_search(self) -> None:
        name = self._name_edit.text().strip()
        if not name:
            return
        self._search_status.setText("Resolving...")
        self._search_status.setStyleSheet("color: yellow; font-size: 11px;")
        self._search_btn.setEnabled(False)
        self._worker = _NameResolveWorker(name)
        self._worker.resolved.connect(self._on_name_resolved)
        self._worker.error.connect(self._on_name_error)
        self._worker.start()

    @pyqtSlot(float, float, str)
    def _on_name_resolved(self, ra: float, dec: float, name: str) -> None:
        self._search_status.setText(f"{name} found")
        self._search_status.setStyleSheet("color: lightgreen; font-size: 11px;")
        self._search_btn.setEnabled(True)
        self.target_changed.emit(ra, dec)

    @pyqtSlot(str)
    def _on_name_error(self, msg: str) -> None:
        self._search_status.setText("Not found")
        self._search_status.setStyleSheet("color: red; font-size: 11px;")
        self._search_btn.setEnabled(True)

    def _on_go_coords(self) -> None:
        try:
            ra = parse_ra(self._ra_edit.text())
            dec = parse_dec(self._dec_edit.text())
            self.target_changed.emit(ra, dec)
        except ValueError as e:
            self._search_status.setText(str(e))
            self._search_status.setStyleSheet("color: red; font-size: 11px;")

    def _on_fov_changed(self, value: float) -> None:
        if not self._updating:
            self.fov_changed.emit(value)

    def _on_camera_param_changed(self) -> None:
        if self._updating:
            return
        self._update_fov_labels()
        self.camera_changed.emit(self._build_camera())

    def _on_rotation_changed(self, value: float) -> None:
        if not self._updating:
            self.rotation_changed.emit(value)

    def _on_mosaic_changed(self) -> None:
        if self._updating:
            return
        h = self._h_panels_spin.value()
        v = self._v_panels_spin.value()
        overlap = self._overlap_spin.value()
        self.mosaic_changed.emit(h, v, overlap)
        self._update_mosaic_label()

    def _update_mosaic_label(self) -> None:
        """Update the total mosaic FOV label."""
        cam = self._build_camera()
        h = self._h_panels_spin.value()
        v = self._v_panels_spin.value()
        overlap = self._overlap_spin.value() / 100.0
        total_w = cam.fov_width_deg + (h - 1) * cam.fov_width_deg * (1 - overlap)
        total_h = cam.fov_height_deg + (v - 1) * cam.fov_height_deg * (1 - overlap)
        self._mosaic_fov_label.setText(f"{total_w:.2f}° × {total_h:.2f}°")

    def _on_export(self) -> None:
        """Export mosaic coordinates to clipboard."""
        from PyQt6.QtWidgets import QApplication
        from core.mosaic import compute_mosaic, export_csv

        cam = self._build_camera()
        ra = parse_ra(self._ra_edit.text()) if self._ra_edit.text() else 0.0
        dec = parse_dec(self._dec_edit.text()) if self._dec_edit.text() else 0.0

        plan = compute_mosaic(
            ra, dec,
            cam.fov_width_deg, cam.fov_height_deg,
            self._h_panels_spin.value(), self._v_panels_spin.value(),
            self._overlap_spin.value(), self._rotation_spin.value(),
        )
        csv_text = export_csv(plan)
        QApplication.clipboard().setText(csv_text)
        self._search_status.setText("Coords copied to clipboard")
        self._search_status.setStyleSheet("color: lightgreen; font-size: 11px;")
