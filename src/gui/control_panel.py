"""Control panel — left sidebar with target, coordinates, camera, and FOV controls."""

import logging

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QDoubleSpinBox, QSpinBox, QGroupBox, QFormLayout,
    QCompleter, QComboBox, QMenu, QInputDialog,
)
from PyQt6.QtCore import pyqtSignal, Qt, QThread, pyqtSlot, QTimer, QStringListModel

from core.coordinates import (
    resolve_name, parse_ra, parse_dec, format_ra, format_dec,
    NameResolveError,
)
from core.camera import CameraProfile, DEFAULT_PROFILE, load_profiles, save_profiles

logger = logging.getLogger(__name__)


class _NameResolveWorker(QThread):
    """Background thread for name resolution."""
    resolved = pyqtSignal(float, float, str)
    error = pyqtSignal(str)

    def __init__(self, name: str, catalog_engine=None) -> None:
        super().__init__()
        self._name = name
        self._catalog_engine = catalog_engine

    def run(self) -> None:
        try:
            coord = resolve_name(self._name, self._catalog_engine)
            self.resolved.emit(coord.ra.deg, coord.dec.deg, self._name)
        except NameResolveError as e:
            self.error.emit(str(e))


class ControlPanel(QWidget):
    """Left panel with target search, coordinates, camera params, and FOV."""

    target_changed = pyqtSignal(float, float)
    fov_changed = pyqtSignal(float)
    camera_changed = pyqtSignal(object)      # CameraProfile
    rotation_changed = pyqtSignal(float)

    def __init__(self, config: dict = None, parent=None) -> None:
        super().__init__(parent)
        self.setFixedWidth(300)
        self._worker = None
        self._updating = False
        self._catalog_engine = None
        self._config = config or {}
        self._suggest_mapping: dict = {}  # formatted string -> CatalogObject

        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignmentFlag.AlignTop)

        # --- Target Search ---
        search_group = QGroupBox("Target")
        search_layout = QVBoxLayout(search_group)

        name_row = QHBoxLayout()
        self._name_edit = QLineEdit()
        self._name_edit.setPlaceholderText("Object name (e.g. M31)")
        self._name_edit.setToolTip("Enter object name (M31, NGC 7000, Horsehead, etc.)")
        self._name_edit.returnPressed.connect(self._on_search)

        # Autosuggest completer
        self._suggest_model = QStringListModel()
        self._completer = QCompleter(self._suggest_model, self)
        self._completer.setCompletionMode(QCompleter.CompletionMode.UnfilteredPopupCompletion)
        self._completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        self._completer.setMaxVisibleItems(10)
        self._completer.activated.connect(self._on_suggestion_selected)
        self._name_edit.setCompleter(self._completer)

        # Debounce timer for autosuggest
        self._suggest_timer = QTimer()
        self._suggest_timer.setSingleShot(True)
        self._suggest_timer.setInterval(100)
        self._suggest_timer.timeout.connect(self._on_suggest)
        self._name_edit.textChanged.connect(self._on_suggest_text_changed)

        self._search_btn = QPushButton("Go")
        self._search_btn.setToolTip("Search for object and navigate to it")
        self._search_btn.clicked.connect(self._on_search)
        name_row.addWidget(self._name_edit)
        name_row.addWidget(self._search_btn)
        search_layout.addLayout(name_row)

        self._search_status = QLabel("")
        self._search_status.setStyleSheet("color: gray; font-size: 11px;")
        search_layout.addWidget(self._search_status)

        # Recent targets
        self._recent_combo = QComboBox()
        self._recent_combo.setPlaceholderText("Recent targets...")
        self._recent_combo.setToolTip("Previously visited targets")
        self._recent_combo.activated.connect(self._on_recent_selected)
        search_layout.addWidget(self._recent_combo)
        self._recent_targets: list[dict] = self._config.get('recent_targets', [])
        for t in self._recent_targets:
            self._recent_combo.addItem(t['name'])

        # Bookmarked targets
        bookmark_row = QHBoxLayout()
        self._bookmark_combo = QComboBox()
        self._bookmark_combo.setPlaceholderText("Bookmarks...")
        self._bookmark_combo.setToolTip("Saved target bookmarks")
        self._bookmark_combo.activated.connect(self._on_bookmark_selected)
        bookmark_row.addWidget(self._bookmark_combo, 1)

        bookmark_btn = QPushButton("\u2606")
        bookmark_btn.setFixedWidth(30)
        bookmark_btn.setToolTip("Bookmark the current target")
        bookmark_btn.clicked.connect(self._on_bookmark)
        bookmark_row.addWidget(bookmark_btn)

        remove_bookmark_btn = QPushButton("\u2715")
        remove_bookmark_btn.setFixedWidth(30)
        remove_bookmark_btn.setToolTip("Remove selected bookmark")
        remove_bookmark_btn.clicked.connect(self._on_remove_bookmark)
        bookmark_row.addWidget(remove_bookmark_btn)
        search_layout.addLayout(bookmark_row)

        self._bookmarks: list[dict] = self._config.get('bookmarked_targets', [])
        for b in self._bookmarks:
            self._bookmark_combo.addItem(b['name'])
        self._last_resolved: dict | None = None

        layout.addWidget(search_group)

        # --- Coordinates ---
        coord_group = QGroupBox("Coordinates")
        coord_layout = QFormLayout(coord_group)

        self._ra_edit = QLineEdit()
        self._ra_edit.setPlaceholderText("HH:MM:SS or degrees")
        self._ra_edit.setToolTip("Right Ascension in HH:MM:SS or decimal degrees")
        self._ra_edit.textChanged.connect(lambda: self._set_field_error(self._ra_edit, False))
        coord_layout.addRow("RA:", self._ra_edit)

        self._dec_edit = QLineEdit()
        self._dec_edit.setPlaceholderText("±DD:MM:SS or degrees")
        self._dec_edit.setToolTip("Declination in ±DD:MM:SS or decimal degrees")
        self._dec_edit.textChanged.connect(lambda: self._set_field_error(self._dec_edit, False))
        coord_layout.addRow("Dec:", self._dec_edit)

        go_btn = QPushButton("Navigate")
        go_btn.clicked.connect(self._on_go_coords)
        coord_layout.addRow(go_btn)

        layout.addWidget(coord_group)

        # --- Camera ---
        cam_group = QGroupBox("Camera")
        cam_layout = QFormLayout(cam_group)

        # Profile selector — full width dropdown
        self._profiles = load_profiles()
        self._profile_combo = QComboBox()
        self._profile_combo.setToolTip("Select a saved camera profile")
        for p in self._profiles:
            self._profile_combo.addItem(p.name)
        self._profile_combo.currentIndexChanged.connect(self._on_profile_selected)
        cam_layout.addRow(self._profile_combo)

        # Save / Delete buttons row
        btn_row = QHBoxLayout()
        save_btn = QPushButton("Save")
        save_btn.setToolTip("Save current settings as a profile")
        save_btn.clicked.connect(self._on_save_profile)
        btn_row.addWidget(save_btn)
        del_btn = QPushButton("Delete")
        del_btn.setToolTip("Delete selected profile")
        del_btn.clicked.connect(self._on_delete_profile)
        btn_row.addWidget(del_btn)
        cam_layout.addRow(btn_row)

        self._width_spin = QSpinBox()
        self._width_spin.setRange(1, 20000)
        self._width_spin.setValue(DEFAULT_PROFILE.sensor_width_px)
        self._width_spin.setSuffix(" px")
        self._width_spin.setToolTip("Camera sensor width in pixels")
        self._width_spin.valueChanged.connect(self._on_camera_param_changed)
        cam_layout.addRow("Width:", self._width_spin)

        self._height_spin = QSpinBox()
        self._height_spin.setRange(1, 20000)
        self._height_spin.setValue(DEFAULT_PROFILE.sensor_height_px)
        self._height_spin.setSuffix(" px")
        self._height_spin.setToolTip("Camera sensor height in pixels")
        self._height_spin.valueChanged.connect(self._on_camera_param_changed)
        cam_layout.addRow("Height:", self._height_spin)

        self._pixel_size_spin = QDoubleSpinBox()
        self._pixel_size_spin.setRange(0.1, 20.0)
        self._pixel_size_spin.setDecimals(2)
        self._pixel_size_spin.setSingleStep(0.01)
        self._pixel_size_spin.setValue(DEFAULT_PROFILE.pixel_size_um)
        self._pixel_size_spin.setSuffix(" µm")
        self._pixel_size_spin.setToolTip("Camera pixel size in micrometers")
        self._pixel_size_spin.valueChanged.connect(self._on_camera_param_changed)
        cam_layout.addRow("Pixel Size:", self._pixel_size_spin)

        self._focal_spin = QDoubleSpinBox()
        self._focal_spin.setRange(50, 10000)
        self._focal_spin.setDecimals(1)
        self._focal_spin.setSingleStep(10)
        self._focal_spin.setValue(DEFAULT_PROFILE.focal_length_mm)
        self._focal_spin.setSuffix(" mm")
        self._focal_spin.setToolTip("Telescope focal length in millimeters")
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
        self._rotation_spin.setToolTip("Camera rotation angle (North through East)")
        self._rotation_spin.valueChanged.connect(self._on_rotation_changed)
        cam_layout.addRow("Rotation:", self._rotation_spin)

        layout.addWidget(cam_group)

        # --- Field of View ---
        fov_group = QGroupBox("View FOV")
        fov_layout = QFormLayout(fov_group)

        # FOV + Step on one row
        fov_row = QHBoxLayout()
        fov_row.addWidget(QLabel("FOV:"))
        self._fov_spin = QDoubleSpinBox()
        self._fov_spin.setRange(0.5, 20.0)
        self._fov_spin.setSingleStep(0.5)
        self._fov_spin.setDecimals(2)
        self._fov_spin.setSuffix("°")
        self._fov_spin.setValue(3.0)
        self._fov_spin.setToolTip("Sky view field of view in degrees")
        fov_row.addWidget(self._fov_spin)
        fov_row.addWidget(QLabel("Step:"))
        self._fov_step_combo = QComboBox()
        self._fov_step_combo.setToolTip("Step size for FOV arrows")
        for step in [0.10, 0.25, 0.50, 1.00, 2.00]:
            self._fov_step_combo.addItem(f"{step:.2f}°", step)
        self._fov_step_combo.setCurrentIndex(2)  # default 0.50°
        self._fov_step_combo.currentIndexChanged.connect(self._on_fov_step_changed)
        fov_row.addWidget(self._fov_step_combo)
        fov_layout.addRow(fov_row)

        # Apply button — full width
        self._fov_apply_btn = QPushButton("Apply")
        self._fov_apply_btn.clicked.connect(self._on_fov_apply)
        fov_layout.addRow(self._fov_apply_btn)

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

    def set_catalog_engine(self, engine) -> None:
        """Set the catalog engine for offline name resolution."""
        self._catalog_engine = engine

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
        self._worker = _NameResolveWorker(name, self._catalog_engine)
        self._worker.resolved.connect(self._on_name_resolved)
        self._worker.error.connect(self._on_name_error)
        self._worker.start()

    @pyqtSlot(float, float, str)
    def _on_name_resolved(self, ra: float, dec: float, name: str) -> None:
        self._search_status.setText(f"{name} found")
        self._search_status.setStyleSheet("color: lightgreen; font-size: 11px;")
        self._search_btn.setEnabled(True)
        self._last_resolved = {'name': name, 'ra': ra, 'dec': dec}
        self._add_recent_target(name, ra, dec)
        self.target_changed.emit(ra, dec)

    @pyqtSlot(str)
    def _on_name_error(self, msg: str) -> None:
        self._search_status.setText("Not found")
        self._search_status.setStyleSheet("color: red; font-size: 11px;")
        self._search_btn.setEnabled(True)

    # --- Autosuggest ---

    def _on_suggest_text_changed(self, text: str) -> None:
        """Restart debounce timer when text changes."""
        if text.strip():
            self._suggest_timer.start()
        else:
            self._suggest_timer.stop()
            self._suggest_model.setStringList([])

    def _on_suggest(self) -> None:
        """Run catalog search and update completer popup."""
        text = self._name_edit.text().strip()
        if not text or not self._catalog_engine:
            return
        results = self._catalog_engine.search_by_name(text, max_results=10)
        self._suggest_mapping.clear()
        items = []
        for obj, _score, match_key in results:
            # Show matched alias if different from primary name
            if match_key.lower() != obj.name.lower():
                label = f"{match_key.upper()} ({obj.name}) — {obj.object_type}"
            else:
                label = f"{obj.name} — {obj.object_type}"
            items.append(label)
            self._suggest_mapping[label] = obj
        self._suggest_model.setStringList(items)
        if items:
            self._completer.complete()

    def _on_suggestion_selected(self, text: str) -> None:
        """Navigate to the selected suggestion."""
        obj = self._suggest_mapping.get(text)
        if obj is None:
            return
        self._suggest_timer.stop()
        self._last_resolved = {'name': obj.name, 'ra': obj.ra_deg, 'dec': obj.dec_deg}
        self._add_recent_target(obj.name, obj.ra_deg, obj.dec_deg)
        self._search_status.setText(f"{obj.name} found")
        self._search_status.setStyleSheet("color: lightgreen; font-size: 11px;")
        self.target_changed.emit(obj.ra_deg, obj.dec_deg)
        # QCompleter overwrites the line edit after activated fires,
        # so we defer setting just the object name
        QTimer.singleShot(0, lambda: self._set_name_quietly(obj.name))

    def _set_name_quietly(self, name: str) -> None:
        """Set the name edit text without triggering autosuggest."""
        self._name_edit.blockSignals(True)
        self._name_edit.setText(name)
        self._name_edit.blockSignals(False)

    # --- Recent Targets ---

    def _add_recent_target(self, name: str, ra: float, dec: float) -> None:
        """Add a target to the recent list, deduped, max 15."""
        self._recent_targets = [
            t for t in self._recent_targets if t['name'] != name
        ]
        self._recent_targets.insert(0, {'name': name, 'ra': ra, 'dec': dec})
        self._recent_targets = self._recent_targets[:15]

        self._recent_combo.clear()
        for t in self._recent_targets:
            self._recent_combo.addItem(t['name'])
        self._recent_combo.setCurrentIndex(-1)

        self._config['recent_targets'] = self._recent_targets
        from config import save_config
        save_config(self._config)

    def _on_recent_selected(self, index: int) -> None:
        """Navigate to a recent target."""
        if 0 <= index < len(self._recent_targets):
            t = self._recent_targets[index]
            self._name_edit.setText(t['name'])
            self._last_resolved = t.copy()
            self._search_status.setText(f"{t['name']} found")
            self._search_status.setStyleSheet("color: lightgreen; font-size: 11px;")
            self.target_changed.emit(t['ra'], t['dec'])

    # --- Bookmarks ---

    def _on_bookmark(self) -> None:
        """Bookmark the current target."""
        if self._last_resolved is None:
            self._search_status.setText("Navigate to a target first")
            self._search_status.setStyleSheet("color: #ff8844; font-size: 11px;")
            return
        name = self._last_resolved['name']
        # Dedup by name
        self._bookmarks = [b for b in self._bookmarks if b['name'] != name]
        self._bookmarks.insert(0, self._last_resolved.copy())

        self._bookmark_combo.clear()
        for b in self._bookmarks:
            self._bookmark_combo.addItem(b['name'])
        self._bookmark_combo.setCurrentIndex(-1)

        self._config['bookmarked_targets'] = self._bookmarks
        from config import save_config
        save_config(self._config)

        self._search_status.setText(f"{name} bookmarked")
        self._search_status.setStyleSheet("color: lightgreen; font-size: 11px;")

    def _on_remove_bookmark(self) -> None:
        """Show a menu listing all bookmarks for removal."""
        if not self._bookmarks:
            return
        menu = QMenu(self)
        for b in self._bookmarks:
            menu.addAction(f"Remove \"{b['name']}\"")
        action = menu.exec(self.sender().mapToGlobal(self.sender().rect().bottomLeft()))
        if action is None:
            return
        # Find which bookmark was selected
        for i, b in enumerate(self._bookmarks):
            if action.text() == f"Remove \"{b['name']}\"":
                self._bookmarks.pop(i)
                self._bookmark_combo.removeItem(i)
                self._bookmark_combo.setCurrentIndex(-1)

                self._config['bookmarked_targets'] = self._bookmarks
                from config import save_config
                save_config(self._config)

                self._search_status.setText(f"{b['name']} removed")
                self._search_status.setStyleSheet("color: gray; font-size: 11px;")
                break

    def _on_bookmark_selected(self, index: int) -> None:
        """Navigate to a bookmarked target."""
        if 0 <= index < len(self._bookmarks):
            t = self._bookmarks[index]
            self._name_edit.setText(t['name'])
            self._last_resolved = t.copy()
            self._search_status.setText(f"{t['name']} found")
            self._search_status.setStyleSheet("color: lightgreen; font-size: 11px;")
            self.target_changed.emit(t['ra'], t['dec'])

    _default_tooltips: dict = {}

    def _set_field_error(self, field: QLineEdit, error: bool, msg: str = "") -> None:
        """Set or clear error styling on a QLineEdit."""
        if field not in self._default_tooltips:
            self._default_tooltips[field] = field.toolTip()
        if error:
            field.setStyleSheet("border: 1px solid red;")
            field.setToolTip(msg)
        else:
            field.setStyleSheet("")
            field.setToolTip(self._default_tooltips.get(field, ""))

    def _on_go_coords(self) -> None:
        self._set_field_error(self._ra_edit, False)
        self._set_field_error(self._dec_edit, False)
        try:
            ra = parse_ra(self._ra_edit.text())
        except ValueError as e:
            self._set_field_error(self._ra_edit, True, str(e))
            self._search_status.setText(str(e))
            self._search_status.setStyleSheet("color: red; font-size: 11px;")
            return
        try:
            dec = parse_dec(self._dec_edit.text())
        except ValueError as e:
            self._set_field_error(self._dec_edit, True, str(e))
            self._search_status.setText(str(e))
            self._search_status.setStyleSheet("color: red; font-size: 11px;")
            return
        self.target_changed.emit(ra, dec)

    def _on_fov_apply(self) -> None:
        self._fov_apply_btn.setText("Loading...")
        self._fov_apply_btn.setEnabled(False)
        self.fov_changed.emit(self._fov_spin.value())

    def set_rendering(self, active: bool) -> None:
        """Update Apply button state based on rendering status."""
        if active:
            self._fov_apply_btn.setText("Loading...")
            self._fov_apply_btn.setEnabled(False)
        else:
            self._fov_apply_btn.setText("Apply")
            self._fov_apply_btn.setEnabled(True)

    def _on_fov_step_changed(self) -> None:
        step = self._fov_step_combo.currentData() or 0.5
        self._fov_spin.setSingleStep(step)

    def _on_profile_selected(self, index: int) -> None:
        if self._updating or index < 0 or index >= len(self._profiles):
            return
        p = self._profiles[index]
        self._updating = True
        self._width_spin.setValue(p.sensor_width_px)
        self._height_spin.setValue(p.sensor_height_px)
        self._pixel_size_spin.setValue(p.pixel_size_um)
        self._focal_spin.setValue(p.focal_length_mm)
        self._updating = False
        self._update_fov_labels()
        self.camera_changed.emit(self._build_camera())

    def _on_save_profile(self) -> None:
        name, ok = QInputDialog.getText(
            self, "Save Profile", "Profile name:",
            text=self._profile_combo.currentText(),
        )
        if not ok or not name.strip():
            return
        name = name.strip()
        profile = self._build_camera()
        profile = CameraProfile(
            name=name,
            sensor_width_px=profile.sensor_width_px,
            sensor_height_px=profile.sensor_height_px,
            pixel_size_um=profile.pixel_size_um,
            focal_length_mm=profile.focal_length_mm,
        )
        # Replace existing or add new
        self._profiles = [p for p in self._profiles if p.name != name]
        self._profiles.append(profile)
        save_profiles(self._profiles)
        # Refresh combo
        self._updating = True
        self._profile_combo.clear()
        for p in self._profiles:
            self._profile_combo.addItem(p.name)
        self._profile_combo.setCurrentText(name)
        self._updating = False

    def _on_delete_profile(self) -> None:
        index = self._profile_combo.currentIndex()
        if index < 0 or index >= len(self._profiles):
            return
        self._profiles.pop(index)
        save_profiles(self._profiles)
        self._updating = True
        self._profile_combo.removeItem(index)
        self._updating = False

    def _on_camera_param_changed(self) -> None:
        if self._updating:
            return
        self._update_fov_labels()
        self.camera_changed.emit(self._build_camera())

    def _on_rotation_changed(self, value: float) -> None:
        if not self._updating:
            self.rotation_changed.emit(value)

