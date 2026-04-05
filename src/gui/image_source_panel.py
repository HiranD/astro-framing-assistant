"""Image source panel — right sidebar for loading XISF user images."""

import logging
from pathlib import Path
from typing import Optional

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QGroupBox, QFormLayout, QListWidget, QListWidgetItem,
    QRadioButton, QSlider, QFileDialog, QButtonGroup,
)
from PyQt6.QtCore import pyqtSignal, Qt

from config import save_config
from core.image_loader import ImageData, load_image

logger = logging.getLogger(__name__)

IMAGE_FILTER = "XISF Images (*.xisf);;All Files (*)"


class ImageSourcePanel(QWidget):
    """Right panel for loading and managing user image overlays."""

    images_changed = pyqtSignal()

    def __init__(self, config: dict, parent=None) -> None:
        super().__init__(parent)
        self.setFixedWidth(280)
        self._config = config
        self._images: list[ImageData] = []

        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignmentFlag.AlignTop)

        # --- Load ---
        load_group = QGroupBox("User Images")
        load_layout = QVBoxLayout(load_group)

        btn_row = QHBoxLayout()
        load_btn = QPushButton("Load Image...")
        load_btn.clicked.connect(self._on_load)
        btn_row.addWidget(load_btn)

        remove_btn = QPushButton("Remove")
        remove_btn.clicked.connect(self._on_remove)
        btn_row.addWidget(remove_btn)
        load_layout.addLayout(btn_row)

        self._list_widget = QListWidget()
        self._list_widget.currentRowChanged.connect(self._on_selection_changed)
        load_layout.addWidget(self._list_widget)

        self._status_label = QLabel("")
        self._status_label.setStyleSheet("color: gray; font-size: 11px;")
        load_layout.addWidget(self._status_label)

        layout.addWidget(load_group)

        # --- Properties ---
        props_group = QGroupBox("Image Properties")
        props_layout = QFormLayout(props_group)

        # Display mode
        mode_row = QHBoxLayout()
        self._footprint_radio = QRadioButton("Footprint")
        self._full_radio = QRadioButton("Full Image")
        self._footprint_radio.setChecked(True)
        mode_group = QButtonGroup(self)
        mode_group.addButton(self._footprint_radio)
        mode_group.addButton(self._full_radio)
        self._footprint_radio.toggled.connect(self._on_mode_changed)
        mode_row.addWidget(self._footprint_radio)
        mode_row.addWidget(self._full_radio)
        props_layout.addRow("Display:", mode_row)

        # Opacity
        self._opacity_slider = QSlider(Qt.Orientation.Horizontal)
        self._opacity_slider.setRange(10, 100)
        self._opacity_slider.setValue(50)
        self._opacity_slider.setEnabled(False)
        self._opacity_slider.valueChanged.connect(self._on_opacity_changed)
        self._opacity_label = QLabel("50%")
        self._opacity_label.setStyleSheet("font-size: 11px;")
        opacity_row = QHBoxLayout()
        opacity_row.addWidget(self._opacity_slider)
        opacity_row.addWidget(self._opacity_label)
        props_layout.addRow("Opacity:", opacity_row)

        layout.addWidget(props_group)
        layout.addStretch()

        # Load previously saved images
        self._load_saved_images()

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
