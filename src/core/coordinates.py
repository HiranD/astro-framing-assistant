"""Coordinate parsing, formatting, and name resolution."""

import re
from astropy.coordinates import SkyCoord
import astropy.units as u


class NameResolveError(Exception):
    """Raised when an object name cannot be resolved."""
    pass


def resolve_name(name: str, catalog_engine=None) -> SkyCoord:
    """Resolve an astronomical object name to coordinates.

    Uses local catalog DB first (offline), falls back to Sesame/CDS.

    Args:
        name: Object name (e.g. "M31", "NGC 7000", "Vega").
        catalog_engine: Optional CatalogSearchEngine for offline lookup.

    Returns:
        SkyCoord with resolved coordinates.

    Raises:
        NameResolveError: If the name cannot be resolved.
    """
    # Try local catalog first (offline, instant)
    if catalog_engine is not None:
        results = catalog_engine.search_by_name(name, max_results=1)
        if results:
            obj, score, _match = results[0]
            return SkyCoord(obj.ra_deg, obj.dec_deg, unit='deg')

    # Fallback to online resolution
    try:
        return SkyCoord.from_name(name)
    except Exception as e:
        raise NameResolveError(f"Could not resolve '{name}': {e}") from e


def parse_ra(text: str) -> float:
    """Parse RA text to decimal degrees.

    Accepts:
        - "12h 25m 3.7s" or "12h25m3.7s"
        - "12:25:03.7"
        - "186.265" (decimal degrees)

    Returns:
        RA in decimal degrees [0, 360).
    """
    text = text.strip()

    # Try decimal degrees first
    try:
        val = float(text)
        return val % 360.0
    except ValueError:
        pass

    # Try sexagesimal with h/m/s markers
    m = re.match(
        r'(\d+)\s*[hH]\s*(\d+)\s*[mM]\s*([\d.]+)\s*[sS]?',
        text,
    )
    if m:
        h, mi, s = float(m.group(1)), float(m.group(2)), float(m.group(3))
        return (h + mi / 60.0 + s / 3600.0) * 15.0

    # Try colon-separated (HH:MM:SS.s)
    parts = text.split(':')
    if len(parts) == 3:
        h, mi, s = float(parts[0]), float(parts[1]), float(parts[2])
        return (h + mi / 60.0 + s / 3600.0) * 15.0

    raise ValueError(f"Cannot parse RA: '{text}'")


def parse_dec(text: str) -> float:
    """Parse Dec text to decimal degrees.

    Accepts:
        - "+12° 53' 13\"" or "+12d 53m 13s"
        - "+12:53:13"
        - "12.887" (decimal degrees)

    Returns:
        Dec in decimal degrees [-90, 90].
    """
    text = text.strip()

    # Try decimal degrees first
    try:
        val = float(text)
        return max(-90.0, min(90.0, val))
    except ValueError:
        pass

    # Try sexagesimal with d/m/s or °/'/\" markers
    m = re.match(
        r'([+-]?\d+)\s*[d°]\s*(\d+)\s*[m\']\s*([\d.]+)\s*[s\"]?',
        text,
    )
    if m:
        d, mi, s = float(m.group(1)), float(m.group(2)), float(m.group(3))
        sign = -1 if d < 0 or text.startswith('-') else 1
        return sign * (abs(d) + mi / 60.0 + s / 3600.0)

    # Try colon-separated (±DD:MM:SS.s)
    parts = text.split(':')
    if len(parts) == 3:
        d, mi, s = float(parts[0]), float(parts[1]), float(parts[2])
        sign = -1 if d < 0 or text.startswith('-') else 1
        return sign * (abs(d) + mi / 60.0 + s / 3600.0)

    raise ValueError(f"Cannot parse Dec: '{text}'")


def format_ra(deg: float) -> str:
    """Format RA from decimal degrees to sexagesimal string.

    Returns:
        String like "12h 25m 04.8s"
    """
    deg = deg % 360.0
    total_hours = deg / 15.0
    h = int(total_hours)
    remainder = (total_hours - h) * 60.0
    m = int(remainder)
    s = (remainder - m) * 60.0
    return f"{h:02d}h {m:02d}m {s:05.2f}s"


def format_dec(deg: float) -> str:
    """Format Dec from decimal degrees to sexagesimal string.

    Returns:
        String like "+12° 53' 24.0\""
    """
    sign = '+' if deg >= 0 else '-'
    deg = abs(deg)
    d = int(deg)
    remainder = (deg - d) * 60.0
    m = int(remainder)
    s = (remainder - m) * 60.0
    return f"{sign}{d:02d}° {m:02d}' {s:04.1f}\""
