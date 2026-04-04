"""WCS construction utilities for the sky canvas."""

import math
from astropy.wcs import WCS


def build_canvas_wcs(
    ra_deg: float,
    dec_deg: float,
    fov_deg: float,
    rotation_deg: float,
    width_px: int,
    height_px: int,
) -> WCS:
    """Build a TAN (gnomonic) WCS for the canvas view.

    Args:
        ra_deg: Center RA in degrees.
        dec_deg: Center Dec in degrees.
        fov_deg: Field of view in degrees (along the longest axis).
        rotation_deg: Rotation angle in degrees (N through E).
        width_px: Canvas width in pixels.
        height_px: Canvas height in pixels.

    Returns:
        An astropy WCS object for the canvas projection.
    """
    w = WCS(naxis=2)
    w.wcs.crpix = [width_px / 2.0, height_px / 2.0]
    w.wcs.crval = [ra_deg, dec_deg]
    w.wcs.ctype = ['RA---TAN', 'DEC--TAN']

    pixel_scale = fov_deg / max(width_px, height_px)  # deg/pixel

    rot = math.radians(rotation_deg)
    cos_r = math.cos(rot)
    sin_r = math.sin(rot)

    w.wcs.cd = [
        [-pixel_scale * cos_r, pixel_scale * sin_r],
        [pixel_scale * sin_r, pixel_scale * cos_r],
    ]

    return w
