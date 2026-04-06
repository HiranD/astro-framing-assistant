"""Catalog search engine using astro_objects.db."""

import bisect
import logging
import math
import re
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class CatalogObject:
    """An astronomical object from the catalog."""
    id: int
    name: str
    ra_deg: float
    dec_deg: float
    object_type: str
    magnitude: Optional[float]
    catalog: str
    catalog_number: str
    description: str
    major_axis_arcmin: Optional[float]
    minor_axis_arcmin: Optional[float]
    constellation: Optional[str]
    position_angle: Optional[float]


# Catalog pattern matchers: (regex, catalog_name)
_CATALOG_PATTERNS = [
    (re.compile(r'^M\s*(\d+)$', re.I), 'Messier'),
    (re.compile(r'^NGC\s*(\d+)$', re.I), 'NGC'),
    (re.compile(r'^IC\s*(\d+)$', re.I), 'IC'),
    (re.compile(r'^C\s*(\d+)$', re.I), 'Caldwell'),
    (re.compile(r'^SH\s*2?\s*-?\s*(\d+)$', re.I), 'Sharpless'),
    (re.compile(r'^CR\s*(\d+)$', re.I), 'Collinder'),
    (re.compile(r'^B\s*(\d+)$', re.I), 'Barnard'),
    (re.compile(r'^RCW\s*(\d+)$', re.I), 'RCW'),
    (re.compile(r'^LDN\s*(\d+)$', re.I), 'LDN'),
    (re.compile(r'^LBN\s*(\d+)$', re.I), 'LBN'),
    (re.compile(r'^VDB\s*(\d+)$', re.I), 'vdB'),
    (re.compile(r'^GUM\s*(\d+)$', re.I), 'Gum'),
    (re.compile(r'^ABELL\s*(\d+)$', re.I), 'Abell'),
]


class CatalogSearchEngine:
    """Fast offline search across 15,909 objects and 256K aliases."""

    def __init__(self, db_path: str) -> None:
        self._db_path = db_path
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row

        # In-memory indexes
        self._objects: dict[int, CatalogObject] = {}
        self._name_to_id: dict[str, int] = {}
        self._catalog_index: dict[str, dict[str, int]] = {}
        self._sorted_keys: list[str] = []

        self._build_index()

    def _build_index(self) -> None:
        """Build in-memory indexes from the database."""
        cursor = self._conn.cursor()

        # Load all objects
        cursor.execute("SELECT * FROM astronomical_objects")
        for row in cursor.fetchall():
            obj = CatalogObject(
                id=row['id'],
                name=row['name'],
                ra_deg=row['ra_deg'] or 0.0,
                dec_deg=row['dec_deg'] or 0.0,
                object_type=row['object_type'] or '',
                magnitude=row['magnitude'],
                catalog=row['catalog'] or '',
                catalog_number=row['catalog_number'] or '',
                description=row['description'] or '',
                major_axis_arcmin=row['major_axis'],
                minor_axis_arcmin=row['minor_axis'],
                constellation=row['constellation'],
                position_angle=row['position_angle'] if 'position_angle' in row.keys() else None,
            )
            self._objects[obj.id] = obj

            # Index by name
            key = obj.name.lower()
            self._name_to_id[key] = obj.id
            if obj.catalog and obj.catalog_number:
                cat = obj.catalog.lower()
                if cat not in self._catalog_index:
                    self._catalog_index[cat] = {}
                self._catalog_index[cat][obj.catalog_number.lstrip('0') or '0'] = obj.id

        # Load aliases
        cursor.execute("SELECT object_id, alias_name FROM object_aliases")
        for row in cursor.fetchall():
            key = row['alias_name'].lower()
            if key not in self._name_to_id and row['object_id'] in self._objects:
                self._name_to_id[key] = row['object_id']

        # Sort keys for binary search
        self._sorted_keys = sorted(self._name_to_id.keys())

        logger.info("Catalog index built: %d objects, %d name keys",
                     len(self._objects), len(self._sorted_keys))

    def search_by_name(self, query: str, max_results: int = 15) -> list[tuple[CatalogObject, int, str]]:
        """Search for objects by name using 5-stage ranked pipeline.

        Returns list of (CatalogObject, score, matched_name) tuples,
        sorted by score descending. matched_name is the alias/key that matched.
        """
        query = query.strip()
        if not query:
            return []

        results: dict[int, int] = {}  # object_id → best score
        matched: dict[int, str] = {}  # object_id → matched name key

        # Stage 1: Exact lookup
        key = query.lower()
        if key in self._name_to_id:
            oid = self._name_to_id[key]
            results[oid] = 1000 + self._bonus(oid)
            matched[oid] = key

        # Stage 2: Catalog pattern
        for pattern, catalog_name in _CATALOG_PATTERNS:
            m = pattern.match(query)
            if m:
                num = m.group(1).lstrip('0') or '0'
                cat_key = catalog_name.lower()
                if cat_key in self._catalog_index and num in self._catalog_index[cat_key]:
                    oid = self._catalog_index[cat_key][num]
                    score = 900 + self._bonus(oid)
                    if oid not in results or score > results[oid]:
                        results[oid] = score
                        matched[oid] = key
                break

        # Stage 2b: Pure number → try NGC then Messier
        if query.isdigit():
            num = query.lstrip('0') or '0'
            for cat, base_score in [('ngc', 850), ('messier', 840)]:
                if cat in self._catalog_index and num in self._catalog_index[cat]:
                    oid = self._catalog_index[cat][num]
                    score = base_score + self._bonus(oid)
                    if oid not in results or score > results[oid]:
                        results[oid] = score
                        matched[oid] = key

        # Stage 3: Prefix search — closer matches (shorter names) rank higher
        if len(results) < max_results:
            idx = bisect.bisect_left(self._sorted_keys, key)
            count = 0
            while idx < len(self._sorted_keys) and count < max_results * 2:
                k = self._sorted_keys[idx]
                if not k.startswith(key):
                    break
                oid = self._name_to_id[k]
                # Bonus for closer match: exact length match gets +50,
                # longer names get progressively less
                closeness = max(0, 50 - (len(k) - len(key)) * 10)
                score = 800 + closeness + self._bonus(oid)
                if oid not in results or score > results[oid]:
                    results[oid] = score
                    matched[oid] = k
                idx += 1
                count += 1

        # Stage 4: Substring (only if query >= 3 chars and need more results)
        if len(query) >= 3 and len(results) < max_results:
            count = 0
            for k in self._sorted_keys:
                if count >= max_results * 3:
                    break
                if key in k:
                    oid = self._name_to_id[k]
                    closeness = max(0, 30 - (len(k) - len(key)) * 5)
                    score = 600 + closeness + self._bonus(oid)
                    if oid not in results or score > results[oid]:
                        results[oid] = score
                        matched[oid] = k
                    count += 1

        # Sort by score, return top results
        sorted_results = sorted(results.items(), key=lambda x: x[1], reverse=True)
        return [
            (self._objects[oid], score, matched.get(oid, self._objects[oid].name))
            for oid, score in sorted_results[:max_results]
            if oid in self._objects
        ]

    def _bonus(self, oid: int) -> int:
        """Compute bonus score for an object."""
        obj = self._objects.get(oid)
        if not obj:
            return 0
        bonus = 0
        # All catalog objects get a base bonus; popular catalogs get more
        if obj.catalog in ('Messier',):
            bonus += 100
        elif obj.catalog in ('NGC', 'IC', 'Caldwell'):
            bonus += 80
        elif obj.catalog in ('Sharpless', 'RCW', 'Gum', 'Barnard'):
            bonus += 60
        elif obj.catalog:
            bonus += 40
        if obj.magnitude is not None:
            bonus += 20
            if obj.magnitude < 10:
                bonus += 10
            if obj.magnitude < 5:
                bonus += 20
        return bonus

    def search_region(
        self,
        ra_deg: float,
        dec_deg: float,
        radius_deg: float,
        mag_limit: Optional[float] = None,
    ) -> list[CatalogObject]:
        """Find objects within a radius of a sky position."""
        dec_min = dec_deg - radius_deg
        dec_max = dec_deg + radius_deg
        cos_dec = max(math.cos(math.radians(dec_deg)), 0.01)
        ra_range = radius_deg / cos_dec

        # Handle RA wraparound
        ra_min = ra_deg - ra_range
        ra_max = ra_deg + ra_range

        cursor = self._conn.cursor()
        if ra_min < 0 or ra_max > 360:
            # Wraparound query
            ra_min_norm = ra_min % 360
            ra_max_norm = ra_max % 360
            sql = """SELECT id FROM astronomical_objects
                     WHERE dec_deg BETWEEN ? AND ?
                     AND (ra_deg >= ? OR ra_deg <= ?)"""
            params = [dec_min, dec_max, ra_min_norm, ra_max_norm]
        else:
            sql = """SELECT id FROM astronomical_objects
                     WHERE dec_deg BETWEEN ? AND ?
                     AND ra_deg BETWEEN ? AND ?"""
            params = [dec_min, dec_max, ra_min, ra_max]

        if mag_limit is not None:
            sql += " AND (magnitude IS NULL OR magnitude <= ?)"
            params.append(mag_limit)

        cursor.execute(sql, params)
        results = []
        for row in cursor.fetchall():
            oid = row[0]
            if oid in self._objects:
                obj = self._objects[oid]
                # Verify angular distance
                dra = (obj.ra_deg - ra_deg)
                if dra > 180:
                    dra -= 360
                elif dra < -180:
                    dra += 360
                ddec = obj.dec_deg - dec_deg
                dist = math.sqrt((dra * cos_dec) ** 2 + ddec ** 2)
                if dist <= radius_deg:
                    results.append(obj)

        return results

    def get_catalogs(self) -> list[str]:
        """Get distinct catalog names."""
        return sorted(set(o.catalog for o in self._objects.values() if o.catalog))

    def get_types(self) -> list[str]:
        """Get distinct object types."""
        return sorted(set(o.object_type for o in self._objects.values() if o.object_type))

    def get_constellations(self) -> list[str]:
        """Get distinct constellation names."""
        return sorted(set(o.constellation for o in self._objects.values() if o.constellation))

    @property
    def object_count(self) -> int:
        return len(self._objects)
