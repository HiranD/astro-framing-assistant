"""Image loader for astro images with embedded WCS.

Supported: XISF (FITS keywords or PixInsight AstrometricSolution properties),
FITS (header WCS), TIFF (FITS header in ImageDescription, or AVM XMP) and
PNG/JPEG (AVM XMP).
"""

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import numpy as np
from astropy.io import fits
from astropy.wcs import WCS

from core.memlog import log_snapshot

logger = logging.getLogger(__name__)

# PixInsight 1.9.5+ dropped the "PCL:" namespace from these property ids.
_PI_SOLUTION_PREFIXES = ('AstrometricSolution:', 'PCL:AstrometricSolution:')


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


def _image_ext(path: Path) -> str:
    """Lower-case extension, treating .fits.gz / .fit.gz as one suffix."""
    name = path.name.lower()
    for double in ('.fits.gz', '.fit.gz'):
        if name.endswith(double):
            return double
    return path.suffix.lower()


def load_image(filepath: str | Path) -> ImageData:
    """Load an image file and extract its WCS, if it carries one."""
    path = Path(filepath)
    ext = _image_ext(path)

    loader = _LOADERS.get(ext)
    if loader is None:
        supported = ' '.join(sorted(_LOADERS))
        raise ValueError(f"Unsupported format: {ext} (supported: {supported})")

    log_snapshot("image_load_enter", path=path.name)
    data, wcs = loader(path)
    log_snapshot(
        "image_load_data",
        path=path.name,
        shape=str(data.shape),
        dtype=str(data.dtype),
    )
    data = _normalize(data)
    log_snapshot("image_normalize_done", path=path.name, shape=str(data.shape))
    h, w = data.shape[:2]
    if wcs is not None:
        wcs.pixel_shape = (w, h)

    logger.info("Loaded %s (%dx%d, WCS=%s)", path.name, w, h, wcs is not None)
    log_snapshot("image_load_exit", path=path.name, w=w, h=h)
    return ImageData(
        filepath=path, data=data, wcs=wcs,
        label=path.stem.removesuffix('.fits').removesuffix('.fit'),
        width=w, height=h,
    )


def _wcs_from_header(header: fits.Header) -> Optional[WCS]:
    """Celestial WCS from a FITS header, or None if it has none."""
    try:
        w = WCS(header).celestial
    except Exception as e:
        logger.debug("No usable WCS in header: %s", e)
        return None
    return w if w.has_celestial else None


def _load_xisf(path: Path) -> tuple[np.ndarray, Optional[WCS]]:
    """Load XISF file with WCS from FITSKeywords or PixInsight AstrometricSolution."""
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
        wcs = _wcs_from_header(header)

    # Fallback: parse PixInsight's AstrometricSolution properties
    if wcs is None:
        props = meta.get('XISFProperties', {})
        wcs = _parse_pixinsight_wcs(props, im_data.shape)

    return _to_hwc(im_data), wcs


def _parse_pixinsight_wcs(props: dict, shape: tuple) -> Optional[WCS]:
    """Build WCS from PixInsight's AstrometricSolution XISF properties.

    PixInsight 1.9.5+ writes ``AstrometricSolution:*``; older versions wrote
    ``PCL:AstrometricSolution:*``. Both are accepted.
    """
    for prefix in _PI_SOLUTION_PREFIXES:
        ref_cel = props.get(f'{prefix}ReferenceCelestialCoordinates')
        ref_img = props.get(f'{prefix}ReferenceImageCoordinates')
        linear_matrix = props.get(f'{prefix}LinearTransformationMatrix')
        if ref_cel is not None and ref_img is not None and linear_matrix is not None:
            proj_sys = props.get(f'{prefix}ProjectionSystem')
            logger.debug("Using PixInsight solution properties with prefix %r", prefix)
            break
    else:
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


def _load_fits(path: Path) -> tuple[np.ndarray, Optional[WCS]]:
    """Load the first image HDU of a FITS file and its header WCS."""
    with fits.open(path, memmap=False) as hdul:
        for hdu in hdul:
            if hdu.data is not None and hdu.data.ndim >= 2:
                data = np.asarray(hdu.data)
                header = hdu.header
                break
        else:
            raise ValueError(f"No image data in {path.name}")
    return _to_hwc(data), _wcs_from_header(header)


def _load_tiff(path: Path) -> tuple[np.ndarray, Optional[WCS]]:
    """Load a TIFF; WCS from a FITS header in ImageDescription, else AVM XMP."""
    import tifffile

    with tifffile.TiffFile(path) as tif:
        data = tif.asarray()
        desc = tif.pages[0].description or ''

    wcs = None
    if 'CRVAL1' in desc:
        try:
            wcs = _wcs_from_header(fits.Header.fromstring(desc, sep='\n'))
        except Exception as e:
            logger.debug("ImageDescription is not a FITS header: %s", e)
    if wcs is None:
        wcs = _wcs_from_avm(path)
    data = _to_hwc(data)
    # FITS-convention WCS: pixel row 1 is the bottom row; TIFF rows run top-down
    if wcs is not None:
        data = data[::-1]
    return data, wcs


def _load_raster(path: Path) -> tuple[np.ndarray, Optional[WCS]]:
    """Load a PNG/JPEG with Pillow; WCS from AVM XMP metadata if present."""
    from PIL import Image

    with Image.open(path) as img:
        if img.mode not in ('L', 'I', 'I;16', 'I;16B', 'F', 'RGB', 'RGBA'):
            img = img.convert('RGB')
        data = np.asarray(img)

    wcs = _wcs_from_avm(path)
    data = _to_hwc(data)
    # AVM uses FITS convention (origin bottom-left); image rows run top-down
    if wcs is not None:
        data = data[::-1]
    return data, wcs


def _wcs_from_avm(path: Path) -> Optional[WCS]:
    """Celestial WCS from AVM XMP metadata embedded in the file, or None."""
    try:
        from pyavm import AVM
        wcs = AVM.from_image(str(path)).to_wcs()
    except Exception as e:
        logger.debug("No AVM WCS in %s: %s", path.name, e)
        return None
    return wcs if wcs.has_celestial else None


_LOADERS = {
    '.xisf': _load_xisf,
    '.fit': _load_fits,
    '.fits': _load_fits,
    '.fts': _load_fits,
    '.fz': _load_fits,
    '.fits.gz': _load_fits,
    '.fit.gz': _load_fits,
    '.tif': _load_tiff,
    '.tiff': _load_tiff,
    '.png': _load_raster,
    '.jpg': _load_raster,
    '.jpeg': _load_raster,
}


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
    data = np.nan_to_num(data.astype(np.float32))
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
