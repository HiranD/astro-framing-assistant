"""Image source panel — right sidebar for images and observer locations."""

import logging
from pathlib import Path
from typing import Optional

from datetime import date, timedelta

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QGroupBox, QFormLayout, QListWidget, QListWidgetItem,
    QRadioButton, QSlider, QFileDialog, QButtonGroup,
    QComboBox, QDoubleSpinBox, QSpinBox,
    QInputDialog, QDateEdit,
)
from PyQt6.QtCore import pyqtSignal, Qt, QDate

from config import save_config
from core.image_loader import ImageData, load_image
from core.visibility import ObserverConfig
from timezonefinder import TimezoneFinder

_tz_finder = TimezoneFinder()

logger = logging.getLogger(__name__)

IMAGE_FILTER = "XISF Images (*.xisf);;All Files (*)"


class ImageSourcePanel(QWidget):
    """Right panel for images, mosaic, and observer locations."""

    images_changed = pyqtSignal()
    location_changed = pyqtSignal(object)  # ObserverConfig
    mosaic_changed = pyqtSignal(int, int, float)  # h_panels, v_panels, overlap_pct
    date_changed = pyqtSignal(object)  # datetime.date

    def __init__(self, config: dict, parent=None) -> None:
        super().__init__(parent)
        self._config = config
        self._images: list[ImageData] = []

        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignmentFlag.AlignTop)

        # --- 1. Mosaic ---
        mosaic_group = QGroupBox("Mosaic")
        mosaic_layout = QFormLayout(mosaic_group)

        self._h_panels_spin = QSpinBox()
        self._h_panels_spin.setRange(1, 10)
        self._h_panels_spin.setValue(1)
        self._h_panels_spin.setToolTip("Number of horizontal mosaic panels")
        self._h_panels_spin.valueChanged.connect(self._on_mosaic_changed)
        mosaic_layout.addRow("H Panels:", self._h_panels_spin)

        self._v_panels_spin = QSpinBox()
        self._v_panels_spin.setRange(1, 10)
        self._v_panels_spin.setValue(1)
        self._v_panels_spin.setToolTip("Number of vertical mosaic panels")
        self._v_panels_spin.valueChanged.connect(self._on_mosaic_changed)
        mosaic_layout.addRow("V Panels:", self._v_panels_spin)

        self._overlap_spin = QDoubleSpinBox()
        self._overlap_spin.setRange(0, 50)
        self._overlap_spin.setDecimals(1)
        self._overlap_spin.setSingleStep(1.0)
        self._overlap_spin.setValue(10.0)
        self._overlap_spin.setSuffix(" %")
        self._overlap_spin.setToolTip("Overlap between adjacent mosaic panels")
        self._overlap_spin.valueChanged.connect(self._on_mosaic_changed)
        mosaic_layout.addRow("Overlap:", self._overlap_spin)

        self._mosaic_fov_label = QLabel("--")
        self._mosaic_fov_label.setStyleSheet("color: #4488ff; font-size: 11px;")
        mosaic_layout.addRow("Total:", self._mosaic_fov_label)

        self._export_btn = QPushButton("Copy Coords to Clipboard")
        self._export_btn.setToolTip("Copy mosaic panel coordinates to clipboard as CSV")
        self._export_btn.clicked.connect(self._on_export)
        mosaic_layout.addRow(self._export_btn)

        layout.addWidget(mosaic_group)

        # --- 2. Observer Location ---
        loc_group = QGroupBox("Observer Location")
        loc_layout = QFormLayout(loc_group)

        self._locations = self._config.get('observer_locations', [])
        self._loc_combo = QComboBox()
        for loc in self._locations:
            self._loc_combo.addItem(loc.get('name', ''))
        self._loc_combo.currentIndexChanged.connect(self._on_location_selected)
        loc_layout.addRow(self._loc_combo)

        ll_row = QHBoxLayout()
        ll_row.addWidget(QLabel("Lat:"))
        self._lat_spin = QDoubleSpinBox()
        self._lat_spin.setRange(-90, 90)
        self._lat_spin.setDecimals(4)
        self._lat_spin.setSuffix("°")
        self._lat_spin.setValue(self._config.get('observer_latitude', 0.0))
        ll_row.addWidget(self._lat_spin)
        ll_row.addWidget(QLabel("Lon:"))
        self._lon_spin = QDoubleSpinBox()
        self._lon_spin.setRange(-180, 180)
        self._lon_spin.setDecimals(4)
        self._lon_spin.setSuffix("°")
        self._lon_spin.setValue(self._config.get('observer_longitude', 0.0))
        ll_row.addWidget(self._lon_spin)
        loc_layout.addRow(ll_row)

        # Auto-detect timezone from coordinates
        self._detected_tz = self._config.get('observer_timezone', 'UTC')
        self._lat_spin.valueChanged.connect(self._auto_detect_tz)
        self._lon_spin.valueChanged.connect(self._auto_detect_tz)

        loc_btn_row = QHBoxLayout()
        loc_save_btn = QPushButton("Save")
        loc_save_btn.setToolTip("Save current location as a preset")
        loc_save_btn.clicked.connect(self._on_save_location)
        loc_btn_row.addWidget(loc_save_btn)
        loc_del_btn = QPushButton("Delete")
        loc_del_btn.setToolTip("Delete selected location")
        loc_del_btn.clicked.connect(self._on_delete_location)
        loc_btn_row.addWidget(loc_del_btn)
        loc_layout.addRow(loc_btn_row)

        loc_apply_btn = QPushButton("Apply Location")
        loc_apply_btn.clicked.connect(self._on_apply_location)
        loc_layout.addRow(loc_apply_btn)

        layout.addWidget(loc_group)

        # --- 3. Observation Date ---
        date_group = QGroupBox("Observation Date")
        date_layout = QHBoxLayout(date_group)

        prev_btn = QPushButton("<")
        prev_btn.setFixedWidth(30)
        prev_btn.clicked.connect(self._on_prev_day)
        date_layout.addWidget(prev_btn)

        self._date_edit = QDateEdit()
        self._date_edit.setCalendarPopup(True)
        self._date_edit.setDate(QDate.currentDate())
        self._date_edit.setDisplayFormat("yyyy-MM-dd")
        self._date_edit.dateChanged.connect(self._on_date_changed)
        date_layout.addWidget(self._date_edit, 1)

        next_btn = QPushButton(">")
        next_btn.setFixedWidth(30)
        next_btn.clicked.connect(self._on_next_day)
        date_layout.addWidget(next_btn)

        today_btn = QPushButton("Today")
        today_btn.setFixedWidth(50)
        today_btn.clicked.connect(self._on_today)
        date_layout.addWidget(today_btn)

        layout.addWidget(date_group)

        # --- 4. User Images (with properties inside) ---
        img_group = QGroupBox("User Images")
        img_layout = QVBoxLayout(img_group)

        btn_row = QHBoxLayout()
        load_btn = QPushButton("Load Image...")
        load_btn.setToolTip("Load a plate-solved XISF image")
        load_btn.clicked.connect(self._on_load)
        btn_row.addWidget(load_btn)
        remove_btn = QPushButton("Remove")
        remove_btn.setToolTip("Remove selected image from overlay")
        remove_btn.clicked.connect(self._on_remove)
        btn_row.addWidget(remove_btn)
        img_layout.addLayout(btn_row)

        self._list_widget = QListWidget()
        self._list_widget.currentRowChanged.connect(self._on_selection_changed)
        img_layout.addWidget(self._list_widget)

        self._status_label = QLabel("")
        self._status_label.setStyleSheet("color: gray; font-size: 11px;")
        img_layout.addWidget(self._status_label)

        # Image properties (inline)
        props_layout = QFormLayout()
        mode_row = QHBoxLayout()
        self._footprint_radio = QRadioButton("Footprint")
        self._footprint_radio.setToolTip("Show image boundary outline only (fast)")
        self._full_radio = QRadioButton("Full Image")
        self._full_radio.setToolTip("Show full reprojected image on sky (slower)")
        self._footprint_radio.setChecked(True)
        mode_group = QButtonGroup(self)
        mode_group.addButton(self._footprint_radio)
        mode_group.addButton(self._full_radio)
        self._footprint_radio.toggled.connect(self._on_mode_changed)
        mode_row.addWidget(self._footprint_radio)
        mode_row.addWidget(self._full_radio)
        props_layout.addRow("Display:", mode_row)

        self._opacity_slider = QSlider(Qt.Orientation.Horizontal)
        self._opacity_slider.setRange(10, 100)
        self._opacity_slider.setValue(50)
        self._opacity_slider.setToolTip("Adjust image overlay transparency")
        self._opacity_slider.setEnabled(False)
        self._opacity_slider.valueChanged.connect(self._on_opacity_changed)
        self._opacity_label = QLabel("50%")
        self._opacity_label.setStyleSheet("font-size: 11px;")
        opacity_row = QHBoxLayout()
        opacity_row.addWidget(self._opacity_slider)
        opacity_row.addWidget(self._opacity_label)
        props_layout.addRow("Opacity:", opacity_row)
        img_layout.addLayout(props_layout)

        layout.addWidget(img_group)
        layout.addStretch()

        # Load previously saved images
        self._load_saved_images()

        # Restore last-applied location in combo
        saved_lat = self._config.get('observer_latitude', 0.0)
        saved_lon = self._config.get('observer_longitude', 0.0)
        match_idx = 0
        for i, loc in enumerate(self._locations):
            if (abs(loc.get('latitude', 0.0) - saved_lat) < 0.001
                    and abs(loc.get('longitude', 0.0) - saved_lon) < 0.001):
                match_idx = i
                break
        if self._locations:
            self._loc_combo.setCurrentIndex(match_idx)

    def _save_paths(self) -> None:
        """Save current image paths to config."""
        self._config['user_image_paths'] = [str(img.filepath) for img in self._images]
        save_config(self._config)

    def _load_saved_images(self) -> None:
        """Reload images from paths saved in config."""
        paths = self._config.get('user_image_paths', [])
        for path in paths:
            if not Path(path).exists():
                logger.info("Skipping missing image: %s", path)
                continue
            try:
                img = load_image(path)
                self._images.append(img)
                item = QListWidgetItem(img.label)
                item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                item.setCheckState(Qt.CheckState.Checked)
                self._list_widget.addItem(item)
            except Exception as e:
                logger.error("Failed to reload %s: %s", path, e)

        if self._images:
            self._list_widget.itemChanged.connect(self._on_check_changed)
            self._list_widget.setCurrentRow(0)

    @property
    def images(self) -> list[ImageData]:
        return self._images

    def _selected_image(self) -> Optional[ImageData]:
        row = self._list_widget.currentRow()
        if 0 <= row < len(self._images):
            return self._images[row]
        return None

    def _on_load(self) -> None:
        last_dir = self._config.get('last_image_dir', str(Path.home()))
        paths, _ = QFileDialog.getOpenFileNames(
            self, "Load Image", last_dir, IMAGE_FILTER,
        )
        if not paths:
            return

        self._config['last_image_dir'] = str(Path(paths[0]).parent)

        for path in paths:
            try:
                img = load_image(path)
                self._images.append(img)
                item = QListWidgetItem(img.label)
                item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                item.setCheckState(Qt.CheckState.Checked)
                self._list_widget.addItem(item)
                self._list_widget.setCurrentRow(len(self._images) - 1)
                if img.wcs:
                    self._status_label.setText(f"Loaded with WCS")
                    self._status_label.setStyleSheet("color: lightgreen; font-size: 11px;")
                else:
                    self._status_label.setText(f"No WCS (plate solve in PixInsight first)")
                    self._status_label.setStyleSheet("color: #ff8844; font-size: 11px;")
            except Exception as e:
                logger.error("Failed to load %s: %s", path, e)
                self._status_label.setText(f"Error: {e}")
                self._status_label.setStyleSheet("color: red; font-size: 11px;")

        self._list_widget.itemChanged.connect(self._on_check_changed)
        self._save_paths()
        self.images_changed.emit()

    def _on_remove(self) -> None:
        row = self._list_widget.currentRow()
        if 0 <= row < len(self._images):
            self._images.pop(row)
            self._list_widget.takeItem(row)
            self._save_paths()
            self.images_changed.emit()
            self._update_props_display()

    def _on_check_changed(self, item: QListWidgetItem) -> None:
        row = self._list_widget.row(item)
        if 0 <= row < len(self._images):
            self._images[row].visible = item.checkState() == Qt.CheckState.Checked
            self.images_changed.emit()

    def _on_selection_changed(self, row: int) -> None:
        self._update_props_display()

    def _update_props_display(self) -> None:
        img = self._selected_image()
        if img is None:
            self._footprint_radio.setChecked(True)
            self._opacity_slider.setEnabled(False)
            self._status_label.setText("")
            return

        if img.wcs is not None:
            self._status_label.setText("WCS: Found")
            self._status_label.setStyleSheet("color: lightgreen; font-size: 11px;")
        else:
            self._status_label.setText("WCS: Not found (plate solve in PixInsight)")
            self._status_label.setStyleSheet("color: #ff8844; font-size: 11px;")

        if img.show_full:
            self._full_radio.setChecked(True)
        else:
            self._footprint_radio.setChecked(True)

        self._opacity_slider.setValue(int(img.opacity * 100))
        self._opacity_slider.setEnabled(img.show_full)

    def _on_mode_changed(self) -> None:
        img = self._selected_image()
        if img is None:
            return
        img.show_full = self._full_radio.isChecked()
        self._opacity_slider.setEnabled(img.show_full)
        self.images_changed.emit()

    def _on_opacity_changed(self, value: int) -> None:
        img = self._selected_image()
        if img is None:
            return
        img.opacity = value / 100.0
        self._opacity_label.setText(f"{value}%")
        self.images_changed.emit()

    # --- Date methods ---

    def _on_date_changed(self, qdate: QDate) -> None:
        d = date(qdate.year(), qdate.month(), qdate.day())
        self.date_changed.emit(d)

    def _on_prev_day(self) -> None:
        qd = self._date_edit.date()
        d = date(qd.year(), qd.month(), qd.day()) - timedelta(days=1)
        self._date_edit.setDate(QDate(d.year, d.month, d.day))

    def _on_next_day(self) -> None:
        qd = self._date_edit.date()
        d = date(qd.year(), qd.month(), qd.day()) + timedelta(days=1)
        self._date_edit.setDate(QDate(d.year, d.month, d.day))

    def _on_today(self) -> None:
        self._date_edit.setDate(QDate.currentDate())

    def restore_state(self, config: dict) -> None:
        """Restore mosaic state from config."""
        self._h_panels_spin.blockSignals(True)
        self._v_panels_spin.blockSignals(True)
        self._overlap_spin.blockSignals(True)
        self._h_panels_spin.setValue(config.get('last_mosaic_h', 1))
        self._v_panels_spin.setValue(config.get('last_mosaic_v', 1))
        self._overlap_spin.setValue(config.get('last_mosaic_overlap', 10.0))
        self._h_panels_spin.blockSignals(False)
        self._v_panels_spin.blockSignals(False)
        self._overlap_spin.blockSignals(False)

    def save_state(self, config: dict) -> None:
        """Save mosaic state to config dict."""
        config['last_mosaic_h'] = self._h_panels_spin.value()
        config['last_mosaic_v'] = self._v_panels_spin.value()
        config['last_mosaic_overlap'] = self._overlap_spin.value()

    # --- Mosaic methods ---

    def _on_mosaic_changed(self) -> None:
        h = self._h_panels_spin.value()
        v = self._v_panels_spin.value()
        overlap = self._overlap_spin.value()
        self.mosaic_changed.emit(h, v, overlap)

    def _on_export(self) -> None:
        """Export mosaic coordinates to clipboard."""
        from PyQt6.QtWidgets import QApplication
        self._export_btn.setText("Copied!")
        QApplication.clipboard().setText("Mosaic export placeholder")

    def _auto_detect_tz(self) -> None:
        """Auto-detect timezone from current lat/lon."""
        lat = self._lat_spin.value()
        lon = self._lon_spin.value()
        try:
            tz = _tz_finder.timezone_at(lat=lat, lng=lon)
            if tz:
                self._detected_tz = tz
        except Exception:
            pass

    # --- Location methods ---

    def _on_location_selected(self, index: int) -> None:
        if index < 0 or index >= len(self._locations):
            return
        loc = self._locations[index]
        self._lat_spin.setValue(loc.get('latitude', 0.0))
        self._lon_spin.setValue(loc.get('longitude', 0.0))
        self._detected_tz = loc.get('timezone', 'UTC')

    def _on_apply_location(self) -> None:
        config = ObserverConfig(
            latitude=self._lat_spin.value(),
            longitude=self._lon_spin.value(),
            elevation=0.0,
            timezone=self._detected_tz,
        )
        # Update config for persistence
        self._config['observer_latitude'] = config.latitude
        self._config['observer_longitude'] = config.longitude
        self._config['observer_timezone'] = config.timezone
        save_config(self._config)
        self.location_changed.emit(config)

    def _on_save_location(self) -> None:
        name, ok = QInputDialog.getText(
            self, "Save Location", "Location name:",
            text=self._loc_combo.currentText() if self._loc_combo.count() > 0 else "",
        )
        if not ok or not name.strip():
            return
        name = name.strip()
        loc = {
            'name': name,
            'latitude': self._lat_spin.value(),
            'longitude': self._lon_spin.value(),
            'elevation': 0.0,
            'timezone': self._detected_tz,
        }
        # Replace existing or add new
        self._locations = [l for l in self._locations if l.get('name') != name]
        self._locations.append(loc)
        self._config['observer_locations'] = self._locations
        save_config(self._config)
        # Refresh combo
        self._loc_combo.blockSignals(True)
        self._loc_combo.clear()
        for l in self._locations:
            self._loc_combo.addItem(l.get('name', ''))
        self._loc_combo.setCurrentText(name)
        self._loc_combo.blockSignals(False)

    def _on_delete_location(self) -> None:
        index = self._loc_combo.currentIndex()
        if index < 0 or index >= len(self._locations):
            return
        self._locations.pop(index)
        self._config['observer_locations'] = self._locations
        save_config(self._config)
        self._loc_combo.removeItem(index)
