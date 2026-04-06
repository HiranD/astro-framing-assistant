"""Settings dialog for observer location and preferences."""

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QFormLayout, QGroupBox,
    QDialogButtonBox, QLineEdit, QPushButton,
    QHBoxLayout, QFileDialog,
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

