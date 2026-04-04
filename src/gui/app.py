"""Main application window."""

import logging
from pathlib import Path

from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QFileDialog, QMessageBox, QDockWidget,
)
from PyQt6.QtCore import Qt

from config import load_config, save_config
from sky.tile_cache import TileCache
from gui.sky_widget import SkyWidget
from gui.control_panel import ControlPanel
from gui.status_bar import StatusBar

logger = logging.getLogger(__name__)


class FramingApp(QMainWindow):
    """Main window for Astro Framing Assistant."""

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Astro Framing Assistant")
        self._config = load_config()

        self.resize(
            self._config.get('window_width', 1400),
            self._config.get('window_height', 900),
        )

        self._tile_cache = None
        self._sky_widget = None

        # Control panel (left)
        self._control_panel = ControlPanel()
        left_dock = QDockWidget("Controls", self)
        left_dock.setWidget(self._control_panel)
        left_dock.setFeatures(QDockWidget.DockWidgetFeature.NoDockWidgetFeatures)
        self.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, left_dock)

        # Placeholder bottom panel (Phase 5: altitude chart)
        bottom_dock = QDockWidget("Altitude", self)
        bottom_dock.setWidget(QWidget())
        bottom_dock.setFeatures(QDockWidget.DockWidgetFeature.NoDockWidgetFeatures)
        self.addDockWidget(Qt.DockWidgetArea.BottomDockWidgetArea, bottom_dock)

        # Status bar
        self._status_bar = StatusBar(self)
        self.setStatusBar(self._status_bar)

        self._setup_menu()
        self._try_load_cache()

    def _setup_menu(self) -> None:
        menu_bar = self.menuBar()
        file_menu = menu_bar.addMenu("&File")

        set_cache_action = file_menu.addAction("Set Cache Path...")
        set_cache_action.triggered.connect(self._on_set_cache_path)

        file_menu.addSeparator()

        exit_action = file_menu.addAction("E&xit")
        exit_action.triggered.connect(self.close)

    def _try_load_cache(self) -> None:
        cache_path = self._config.get('cache_path')
        if cache_path and Path(cache_path).is_dir():
            self._load_cache(cache_path)
            return

        app_dir = Path(__file__).resolve().parent.parent.parent
        default_cache = app_dir / 'FramingAssistantCache'
        if default_cache.is_dir():
            self._load_cache(str(default_cache))
            return

        self._status_bar.set_status(
            "No cache found. Use File → Set Cache Path to load sky tiles."
        )

    def _load_cache(self, cache_path: str) -> None:
        self._tile_cache = TileCache(cache_path)

        if self._tile_cache.tile_count == 0:
            QMessageBox.warning(
                self, "Cache Empty",
                f"No tile files found at:\n{cache_path}\n\n"
                "Please select a valid FramingAssistantCache directory."
            )
            return

        self._sky_widget = SkyWidget(self._tile_cache, self)
        self.setCentralWidget(self._sky_widget)

        # Wire signals
        self._control_panel.target_changed.connect(self._sky_widget.set_center)
        self._control_panel.fov_changed.connect(self._sky_widget.set_fov)
        self._control_panel.camera_changed.connect(self._sky_widget.set_camera)
        self._control_panel.rotation_changed.connect(self._sky_widget.set_camera_rotation)
        self._control_panel.mosaic_changed.connect(self._sky_widget.set_mosaic)
        self._sky_widget.cursor_moved.connect(self._status_bar.update_cursor)
        self._sky_widget.view_changed.connect(self._control_panel.update_display)
        self._sky_widget.view_changed.connect(self._status_bar.update_fov)

        self._sky_widget.show_initial_view()

        self._status_bar.set_status(
            f"Loaded {self._tile_cache.tile_count} sky positions"
        )

    def _on_set_cache_path(self) -> None:
        current = self._config.get('cache_path', '')
        path = QFileDialog.getExistingDirectory(
            self,
            "Select FramingAssistantCache Directory",
            current or str(Path.home()),
        )
        if not path:
            return

        self._config['cache_path'] = path
        save_config(self._config)
        self._load_cache(path)

    def closeEvent(self, event) -> None:
        size = self.size()
        self._config['window_width'] = size.width()
        self._config['window_height'] = size.height()
        save_config(self._config)
        super().closeEvent(event)
