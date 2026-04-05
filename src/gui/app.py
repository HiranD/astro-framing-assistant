"""Main application window."""

import logging
from pathlib import Path

from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QFileDialog, QMessageBox, QDockWidget,
)
from PyQt6.QtCore import Qt

from config import load_config, save_config
from core.visibility import ObserverConfig
from core.catalog import CatalogSearchEngine
from sky.tile_cache import TileCache
from gui.sky_widget import SkyWidget
from gui.control_panel import ControlPanel
from gui.altitude_widget import AltitudeWidget
from gui.status_bar import StatusBar
from gui.settings_dialog import SettingsDialog
from gui.catalog_dialog import CatalogDialog
from gui.image_source_panel import ImageSourcePanel

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
        self._catalog_engine = None
        self._catalog_dialog = None

        # Observer config
        self._observer_config = ObserverConfig(
            latitude=self._config.get('observer_latitude', 0.0),
            longitude=self._config.get('observer_longitude', 0.0),
            elevation=self._config.get('observer_elevation', 0.0),
            timezone=self._config.get('observer_timezone', 'UTC'),
        )

        # Control panel (left)
        self._control_panel = ControlPanel()
        left_dock = QDockWidget("Controls", self)
        left_dock.setWidget(self._control_panel)
        left_dock.setFeatures(QDockWidget.DockWidgetFeature.NoDockWidgetFeatures)
        self.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, left_dock)

        # Altitude chart (bottom)
        self._altitude_widget = AltitudeWidget(self._observer_config)
        bottom_dock = QDockWidget("Altitude", self)
        bottom_dock.setWidget(self._altitude_widget)
        bottom_dock.setFeatures(QDockWidget.DockWidgetFeature.NoDockWidgetFeatures)
        self.addDockWidget(Qt.DockWidgetArea.BottomDockWidgetArea, bottom_dock)

        # Image source panel (right)
        self._image_panel = ImageSourcePanel(self._config)
        right_dock = QDockWidget("Image Sources", self)
        right_dock.setWidget(self._image_panel)
        right_dock.setFeatures(QDockWidget.DockWidgetFeature.DockWidgetClosable)
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, right_dock)
        self._right_dock = right_dock

        # Status bar
        self._status_bar = StatusBar(self)
        self.setStatusBar(self._status_bar)

        self._setup_menu()
        self._load_catalog()
        self._try_load_cache()

    def _setup_menu(self) -> None:
        menu_bar = self.menuBar()
        file_menu = menu_bar.addMenu("&File")

        set_cache_action = file_menu.addAction("Set Cache Path...")
        set_cache_action.triggered.connect(self._on_set_cache_path)

        settings_action = file_menu.addAction("Settings...")
        settings_action.triggered.connect(self._on_settings)

        file_menu.addSeparator()

        exit_action = file_menu.addAction("E&xit")
        exit_action.triggered.connect(self.close)

        view_menu = menu_bar.addMenu("&View")
        atlas_action = view_menu.addAction("Sky Atlas...")
        atlas_action.triggered.connect(self._on_sky_atlas)

        images_action = view_menu.addAction("Image Sources")
        images_action.triggered.connect(lambda: self._right_dock.show())

    def _load_catalog(self) -> None:
        """Load the catalog database."""
        app_dir = Path(__file__).resolve().parent.parent.parent
        db_path = app_dir / 'data' / 'astro_objects.db'
        if db_path.exists():
            self._catalog_engine = CatalogSearchEngine(str(db_path))
            self._control_panel.set_catalog_engine(self._catalog_engine)
            self._status_bar.set_status(
                f"Catalog: {self._catalog_engine.object_count} objects loaded"
            )
        else:
            logger.warning("Catalog DB not found at %s", db_path)

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

        # Set catalog engine on sky canvas
        if self._catalog_engine:
            self._sky_widget.sky_canvas.set_catalog_engine(self._catalog_engine)

        # Wire signals
        self._control_panel.target_changed.connect(self._sky_widget.set_center)
        self._control_panel.target_changed.connect(self._altitude_widget.set_target)
        self._control_panel.fov_changed.connect(self._sky_widget.set_fov)
        self._control_panel.camera_changed.connect(self._sky_widget.set_camera)
        self._control_panel.rotation_changed.connect(self._sky_widget.set_camera_rotation)
        self._control_panel.mosaic_changed.connect(self._sky_widget.set_mosaic)
        self._sky_widget.cursor_moved.connect(self._status_bar.update_cursor)
        self._sky_widget.view_changed.connect(self._control_panel.update_display)
        self._sky_widget.view_changed.connect(self._status_bar.update_fov)

        # Wire image panel
        self._image_panel.images_changed.connect(self._on_images_changed)

        self._sky_widget.show_initial_view()
        self._altitude_widget.set_target(10.685, 41.269)

        # Render any pre-loaded images from previous session
        if self._image_panel.images:
            self._on_images_changed()

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

    def _on_settings(self) -> None:
        old_cache = self._config.get('cache_path', '')
        dialog = SettingsDialog(self)
        if dialog.exec():
            self._config = load_config()
            self._observer_config = dialog.get_observer_config()
            self._altitude_widget.update_observer(self._observer_config)
            new_cache = self._config.get('cache_path', '')
            if new_cache and new_cache != old_cache:
                self._load_cache(new_cache)

    def _on_sky_atlas(self) -> None:
        """Open the Sky Atlas catalog search dialog."""
        if self._catalog_engine is None:
            QMessageBox.warning(self, "No Catalog", "Catalog database not found.")
            return

        if self._catalog_dialog is None:
            self._catalog_dialog = CatalogDialog(self._catalog_engine, self)
            self._catalog_dialog.target_selected.connect(self._on_atlas_target)

        self._catalog_dialog.show()
        self._catalog_dialog.raise_()

    def _on_images_changed(self) -> None:
        """Handle user image list changes."""
        if self._sky_widget:
            self._sky_widget.sky_canvas.set_user_images(self._image_panel.images)

    def _on_atlas_target(self, ra: float, dec: float, name: str) -> None:
        """Handle target selected from Sky Atlas."""
        if self._sky_widget:
            self._sky_widget.set_center(ra, dec)
        self._altitude_widget.set_target(ra, dec)

    def closeEvent(self, event) -> None:
        size = self.size()
        self._config['window_width'] = size.width()
        self._config['window_height'] = size.height()
        save_config(self._config)
        super().closeEvent(event)
