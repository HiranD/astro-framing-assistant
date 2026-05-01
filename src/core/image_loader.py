"""Image loader for XISF files with WCS extraction from PixInsight."""

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import numpy as np
from astropy.io import fits
from astropy.wcs import WCS

from core.memlog import log_snapshot

logger = logging.getLogger(__name__)


@dataclass
class ImageData:
    """A loaded user image with optional WCS."""
    filepath: Path
    data: np.ndarray              # (H, W, 3) float32 normalized 0-1
    wcs: Optional[WCS]
    label: str
    width: int
    height: int
    visible: bool = True
    show_full: bool = False
    opacity: float = 0.5


def load_image(filepath: str | Path) -> ImageData:
    """Load an XISF image file and extract WCS."""
    path = Path(filepath)
    ext = path.suffix.lower()

    if ext != '.xisf':
        raise ValueError(f"Unsupported format: {ext} (only .xisf is supported)")

    log_snapshot("xisf_load_enter", path=path.name)
    data, wcs = _load_xisf(path)
    log_snapshot(
        "xisf_load_data",
        path=path.name,
        shape=str(data.shape),
        dtype=str(data.dtype),
    )
    data = _normalize(data)
    log_snapshot("xisf_normalize_done", path=path.name, shape=str(data.shape))
    h, w = data.shape[:2]

    logger.info("Loaded %s (%dx%d, WCS=%s)", path.name, w, h, wcs is not None)
    log_snapshot("xisf_load_exit", path=path.name, w=w, h=h)
    return ImageData(
        filepath=path, data=data, wcs=wcs,
        label=path.stem, width=w, height=h,
    )


def _load_xisf(path: Path) -> tuple[np.ndarray, Optional[WCS]]:
    """Load XISF file with WCS from FITSKeywords or PCL:AstrometricSolution."""
    from xisf import XISF

    xisf_obj = XISF(str(path))
    im_data = xisf_obj.read_image(0)
    meta = xisf_obj.get_images_metadata()[0]
    wcs = None

    # Try FITSKeywords first (has standard WCS keys like CRVAL1, CD1_1)
    fits_kw = meta.get('FITSKeywords', {})
    if fits_kw:
        header = fits.Header()
        for key, entries in fits_kw.items():
            if entries and len(entries) > 0:
                val = entries[0].get('value', '')
                try:
                    val = float(val)
                    if val == int(val):
                        val = int(val)
                except (ValueError, TypeError):
                    pass
                try:
                    header[key] = val
                except Exception:
                    pass
        try:
            w = WCS(header)
            if w.has_celestial:
                wcs = w
        except Exception:
            pass

    # Fallback: parse PixInsight's PCL:AstrometricSolution properties
    if wcs is None:
        props = meta.get('XISFProperties', {})
        wcs = _parse_pixinsight_wcs(props, im_data.shape)

    return _to_hwc(im_data), wcs


def _parse_pixinsight_wcs(props: dict, shape: tuple) -> Optional[WCS]:
    """Build WCS from PixInsight's PCL:AstrometricSolution XISF properties."""
    prefix = 'PCL:AstrometricSolution:'

    ref_cel = props.get(f'{prefix}ReferenceCelestialCoordinates')
    ref_img = props.get(f'{prefix}ReferenceImageCoordinates')
    linear_matrix = props.get(f'{prefix}LinearTransformationMatrix')
    proj_sys = props.get(f'{prefix}ProjectionSystem')

    if ref_cel is None or ref_img is None or linear_matrix is None:
        return None

    try:
        crval = ref_cel['value']   # [RA_deg, Dec_deg]
        crpix = ref_img['value']   # [x_px, y_px] (0-based from PixInsight)
        cd = linear_matrix['value']  # 2x2 CD matrix

        # PixInsight projection: Gnomonic = TAN
        proj = 'TAN'
        if proj_sys and 'stereographic' in proj_sys.get('value', '').lower():
            proj = 'STG'

        w = WCS(naxis=2)
        w.wcs.crval = [float(crval[0]), float(crval[1])]
        # PixInsight uses 0-based coords, FITS WCS uses 1-based
        w.wcs.crpix = [float(crpix[0]) + 1.0, float(crpix[1]) + 1.0]
        w.wcs.ctype = [f'RA---{proj}', f'DEC--{proj}']
        w.wcs.cd = [[float(cd[0, 0]), float(cd[0, 1])],
                     [float(cd[1, 0]), float(cd[1, 1])]]
        # Set pixel dimensions so calc_footprint() works
        h, w_px = shape[0], shape[1] if len(shape) >= 2 else shape[0]
        if len(shape) == 3 and shape[0] in (1, 3, 4):
            # (C, H, W) format
            h, w_px = shape[1], shape[2]
        w.pixel_shape = (w_px, h)

        if w.has_celestial:
            logger.info("Built WCS from PixInsight AstrometricSolution")
            return w
    except Exception as e:
        logger.warning("Failed to parse PixInsight WCS: %s", e)

    return None


def _to_hwc(data: np.ndarray) -> np.ndarray:
    """Convert image data to (H, W, 3) format."""
    if data.ndim == 2:
        return np.stack([data, data, data], axis=-1)
    elif data.ndim == 3:
        if data.shape[0] in (1, 3, 4):
            data = np.moveaxis(data, 0, -1)
        if data.shape[2] == 1:
            data = np.repeat(data, 3, axis=2)
        elif data.shape[2] == 4:
            data = data[:, :, :3]
        return data
    raise ValueError(f"Unexpected image shape: {data.shape}")


def _normalize(data: np.ndarray) -> np.ndarray:
    """Normalize to float32 0-1 with percentile stretch."""
    data = data.astype(np.float32)
    lo = np.percentile(data, 1)
    hi = np.percentile(data, 99.5)
    if hi <= lo:
        hi = lo + 1.0
    data = np.clip((data - lo) / (hi - lo), 0.0, 1.0)
    return data


def downsample_for_display(data: np.ndarray, max_dim: int = 2048) -> tuple[np.ndarray, int]:
    """Downsample image using stride slicing. Returns (downsampled_data, factor)."""
    h, w = data.shape[:2]
    factor = max(1, max(h, w) // max_dim)
    if factor <= 1:
        return data, 1
    return data[::factor, ::factor], factor
