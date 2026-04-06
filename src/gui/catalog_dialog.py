"""Sky Atlas / Catalog search dialog."""

import logging

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLineEdit, QPushButton,
    QComboBox, QDoubleSpinBox, QGroupBox, QFormLayout,
    QTableWidget, QTableWidgetItem, QHeaderView, QLabel, QAbstractItemView,
)
from PyQt6.QtCore import pyqtSignal, Qt, QTimer

from core.catalog import CatalogSearchEngine, CatalogObject
from core.coordinates import format_ra, format_dec

logger = logging.getLogger(__name__)


class CatalogDialog(QDialog):
    """Sky Atlas search dialog with filters and sortable results."""

    target_selected = pyqtSignal(float, float, str)  # ra, dec, name

    def __init__(self, catalog_engine: CatalogSearchEngine, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Sky Atlas")
        self.setMinimumSize(800, 500)
        self._engine = catalog_engine
        self._results: list[CatalogObject] = []
        self._matched_names: dict[int, str] = {}  # obj.id → matched alias

        layout = QVBoxLayout(self)

        # Search bar
        search_row = QHBoxLayout()
        self._search_edit = QLineEdit()
        self._search_edit.setPlaceholderText("Search by name (e.g. M31, NGC 7000, Crab Nebula, RCW 16)")
        search_btn = QPushButton("Search")
        search_btn.clicked.connect(self._on_search)
        self._search_edit.returnPressed.connect(self._on_search)
        search_row.addWidget(self._search_edit)
        search_row.addWidget(search_btn)
        layout.addLayout(search_row)

        # Filters
        filter_group = QGroupBox("Filters")
        filter_layout = QHBoxLayout(filter_group)

        form1 = QFormLayout()
        self._type_combo = QComboBox()
        self._type_combo.addItem("All Types")
        for t in catalog_engine.get_types():
            self._type_combo.addItem(t)
        self._type_combo.currentIndexChanged.connect(self._on_filter_changed)
        form1.addRow("Type:", self._type_combo)

        self._catalog_combo = QComboBox()
        self._catalog_combo.addItem("All Catalogs")
        for c in catalog_engine.get_catalogs():
            self._catalog_combo.addItem(c)
        self._catalog_combo.currentIndexChanged.connect(self._on_filter_changed)
        form1.addRow("Catalog:", self._catalog_combo)
        filter_layout.addLayout(form1)

        form2 = QFormLayout()
        self._const_combo = QComboBox()
        self._const_combo.addItem("All")
        for c in catalog_engine.get_constellations():
            self._const_combo.addItem(c)
        self._const_combo.currentIndexChanged.connect(self._on_filter_changed)
        form2.addRow("Constellation:", self._const_combo)

        mag_row = QHBoxLayout()
        self._mag_min = QDoubleSpinBox()
        self._mag_min.setRange(-5, 30)
        self._mag_min.setValue(-5)
        self._mag_min.setSpecialValueText("--")
        self._mag_max = QDoubleSpinBox()
        self._mag_max.setRange(-5, 30)
        self._mag_max.setValue(30)
        self._mag_max.setSpecialValueText("--")
        mag_row.addWidget(self._mag_min)
        mag_row.addWidget(QLabel("to"))
        mag_row.addWidget(self._mag_max)
        form2.addRow("Mag:", mag_row)
        filter_layout.addLayout(form2)

        layout.addWidget(filter_group)

        # Results table
        self._table = QTableWidget()
        self._table.setColumnCount(7)
        self._table.setHorizontalHeaderLabels([
            "Name", "Type", "RA", "Dec", "Mag", "Size", "Constellation"
        ])
        self._table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self._table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._table.setSortingEnabled(True)
        self._table.doubleClicked.connect(self._on_double_click)
        layout.addWidget(self._table)

        # Bottom bar
        bottom_row = QHBoxLayout()
        self._count_label = QLabel(f"0 / {catalog_engine.object_count}")
        bottom_row.addWidget(self._count_label)
        bottom_row.addStretch()
        send_btn = QPushButton("Send to Framing")
        send_btn.clicked.connect(self._on_send)
        bottom_row.addWidget(send_btn)
        layout.addLayout(bottom_row)

        # Debounce timer for filter changes
        self._filter_timer = QTimer()
        self._filter_timer.setSingleShot(True)
        self._filter_timer.setInterval(300)
        self._filter_timer.timeout.connect(self._apply_filters)

    def _on_search(self) -> None:
        """Run name search with live results."""
        query = self._search_edit.text().strip()
        if not query:
            self._results = []
            self._matched_names.clear()
            self._populate_table(self._results)
            return

        results = self._engine.search_by_name(query, max_results=50)
        self._results = []
        self._matched_names.clear()
        for obj, score, match_key in results:
            self._results.append(obj)
            if match_key.lower() != obj.name.lower():
                self._matched_names[obj.id] = match_key
        self._populate_table(self._results)

    def _on_filter_changed(self) -> None:
        """Debounce filter changes."""
        self._filter_timer.start()

    def _apply_filters(self) -> None:
        """Apply filter criteria via SQL."""
        type_filter = self._type_combo.currentText()
        catalog_filter = self._catalog_combo.currentText()
        const_filter = self._const_combo.currentText()
        mag_min = self._mag_min.value()
        mag_max = self._mag_max.value()

        # Build filtered query
        conditions = []
        params = []

        if type_filter != "All Types":
            conditions.append("object_type = ?")
            params.append(type_filter)
        if catalog_filter != "All Catalogs":
            conditions.append("catalog = ?")
            params.append(catalog_filter)
        if const_filter != "All":
            conditions.append("constellation = ?")
            params.append(const_filter)
        if mag_min > -5:
            conditions.append("magnitude >= ?")
            params.append(mag_min)
        if mag_max < 30:
            conditions.append("magnitude <= ?")
            params.append(mag_max)

        sql = "SELECT id FROM astronomical_objects"
        if conditions:
            sql += " WHERE " + " AND ".join(conditions)
        sql += " ORDER BY magnitude ASC NULLS LAST LIMIT 500"

        cursor = self._engine._conn.cursor()
        cursor.execute(sql, params)

        self._results = []
        for row in cursor.fetchall():
            oid = row[0]
            if oid in self._engine._objects:
                self._results.append(self._engine._objects[oid])

        self._populate_table(self._results)

    def _populate_table(self, objects: list[CatalogObject]) -> None:
        """Fill the table with objects."""
        self._table.setSortingEnabled(False)
        self._table.setRowCount(len(objects))

        for i, obj in enumerate(objects):
            # Show matched alias if different from primary name
            alias = self._matched_names.get(obj.id)
            name_text = f"{alias.upper()} ({obj.name})" if alias else obj.name
            self._table.setItem(i, 0, QTableWidgetItem(name_text))
            self._table.setItem(i, 1, QTableWidgetItem(obj.object_type))
            self._table.setItem(i, 2, QTableWidgetItem(format_ra(obj.ra_deg)))
            self._table.setItem(i, 3, QTableWidgetItem(format_dec(obj.dec_deg)))

            mag_item = QTableWidgetItem()
            if obj.magnitude is not None:
                mag_item.setText(f"{obj.magnitude:.1f}")
                mag_item.setData(Qt.ItemDataRole.UserRole, obj.magnitude)
            else:
                mag_item.setText("--")
                mag_item.setData(Qt.ItemDataRole.UserRole, 999.0)
            self._table.setItem(i, 4, mag_item)

            size_str = ""
            if obj.major_axis_arcmin:
                size_str = f"{obj.major_axis_arcmin:.1f}'"
                if obj.minor_axis_arcmin:
                    size_str += f" × {obj.minor_axis_arcmin:.1f}'"
            self._table.setItem(i, 5, QTableWidgetItem(size_str))
            self._table.setItem(i, 6, QTableWidgetItem(obj.constellation or ""))

        self._table.setSortingEnabled(True)
        self._count_label.setText(f"{len(objects)} / {self._engine.object_count}")

    def _on_double_click(self, index) -> None:
        """Send double-clicked object to framing."""
        row = index.row()
        if 0 <= row < len(self._results):
            obj = self._results[row]
            self.target_selected.emit(obj.ra_deg, obj.dec_deg, obj.name)

    def _on_send(self) -> None:
        """Send selected object to framing."""
        rows = self._table.selectionModel().selectedRows()
        if rows:
            row = rows[0].row()
            if 0 <= row < len(self._results):
                obj = self._results[row]
                self.target_selected.emit(obj.ra_deg, obj.dec_deg, obj.name)
