"""Settings dialog for observer location and preferences."""

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QFormLayout, QGroupBox,
    QDoubleSpinBox, QDialogButtonBox, QLineEdit,
    QPushButton, QHBoxLayout, QFileDialog,
)

from config import load_config, save_config


class SettingsDialog(QDialog):
    """Settings dialog with observer location configuration."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Settings")
        self.setMinimumWidth(350)

        self._config = load_config()
        layout = QVBoxLayout(self)

        # Observer Location
        obs_group = QGroupBox("Observer Location")
        obs_layout = QFormLayout(obs_group)

        self._lat_spin = QDoubleSpinBox()
        self._lat_spin.setRange(-90, 90)
        self._lat_spin.setDecimals(4)
        self._lat_spin.setSuffix("°")
        self._lat_spin.setValue(self._config.get('observer_latitude', 6.9271))
        obs_layout.addRow("Latitude:", self._lat_spin)

        self._lon_spin = QDoubleSpinBox()
        self._lon_spin.setRange(-180, 180)
        self._lon_spin.setDecimals(4)
        self._lon_spin.setSuffix("°")
        self._lon_spin.setValue(self._config.get('observer_longitude', 79.8612))
        obs_layout.addRow("Longitude:", self._lon_spin)

        self._elev_spin = QDoubleSpinBox()
        self._elev_spin.setRange(0, 5000)
        self._elev_spin.setDecimals(0)
        self._elev_spin.setSuffix(" m")
        self._elev_spin.setValue(self._config.get('observer_elevation', 0.0))
        obs_layout.addRow("Elevation:", self._elev_spin)

        self._tz_edit = QLineEdit()
        self._tz_edit.setText(self._config.get('observer_timezone', 'Asia/Colombo'))
        self._tz_edit.setPlaceholderText("e.g. Asia/Colombo, US/Eastern")
        obs_layout.addRow("Timezone:", self._tz_edit)

        layout.addWidget(obs_group)

        # Sky Tiles Cache
        cache_group = QGroupBox("Sky Tiles Cache")
        cache_layout = QFormLayout(cache_group)

        cache_row = QHBoxLayout()
        self._cache_edit = QLineEdit()
        self._cache_edit.setText(self._config.get('cache_path', ''))
        self._cache_edit.setPlaceholderText("Path to FramingAssistantCache folder")
        cache_browse = QPushButton("Browse...")
        cache_browse.clicked.connect(self._browse_cache)
        cache_row.addWidget(self._cache_edit)
        cache_row.addWidget(cache_browse)
        cache_layout.addRow("Path:", cache_row)

        layout.addWidget(cache_group)

        # Buttons
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._save_and_accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _save_and_accept(self) -> None:
        self._config['observer_latitude'] = self._lat_spin.value()
        self._config['observer_longitude'] = self._lon_spin.value()
        self._config['observer_elevation'] = self._elev_spin.value()
        self._config['observer_timezone'] = self._tz_edit.text().strip()
        cache_path = self._cache_edit.text().strip()
        if cache_path:
            self._config['cache_path'] = cache_path
        save_config(self._config)
        self.accept()

    def _browse_cache(self) -> None:
        path = QFileDialog.getExistingDirectory(
            self, "Select FramingAssistantCache Directory",
            self._cache_edit.text() or str(__import__('pathlib').Path.home()),
        )
        if path:
            self._cache_edit.setText(path)

    def get_observer_config(self):
        """Return the current observer config from the dialog values."""
        from core.visibility import ObserverConfig
        return ObserverConfig(
            latitude=self._lat_spin.value(),
            longitude=self._lon_spin.value(),
            elevation=self._elev_spin.value(),
            timezone=self._tz_edit.text().strip(),
        )
