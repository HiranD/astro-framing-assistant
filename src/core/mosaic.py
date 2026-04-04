"""Mosaic planner — N×M panel grid with overlap and rotation."""

import math
import io
import csv
from dataclasses import dataclass, field

from core.coordinates import format_ra, format_dec


@dataclass
class MosaicPanel:
    """A single panel in a mosaic plan."""
    ra_deg: float
    dec_deg: float
    rotation_deg: float
    col: int
    row: int
    label: str


@dataclass
class MosaicPlan:
    """Complete mosaic plan with all panel positions."""
    center_ra: float
    center_dec: float
    h_panels: int
    v_panels: int
    overlap_pct: float
    rotation_deg: float
    fov_w_deg: float
    fov_h_deg: float
    panels: list[MosaicPanel] = field(default_factory=list)
    total_fov_w_deg: float = 0.0
    total_fov_h_deg: float = 0.0


def compute_mosaic(
    center_ra: float,
    center_dec: float,
    fov_w: float,
    fov_h: float,
    h_panels: int,
    v_panels: int,
    overlap_pct: float,
    rotation_deg: float,
) -> MosaicPlan:
    """Compute mosaic panel positions.

    Args:
        center_ra: Mosaic center RA in degrees.
        center_dec: Mosaic center Dec in degrees.
        fov_w: Single panel FOV width in degrees.
        fov_h: Single panel FOV height in degrees.
        h_panels: Number of horizontal panels.
        v_panels: Number of vertical panels.
        overlap_pct: Overlap percentage (0-50).
        rotation_deg: Mosaic rotation in degrees.

    Returns:
        MosaicPlan with computed panel positions.
    """
    overlap_frac = overlap_pct / 100.0
    step_w = fov_w * (1.0 - overlap_frac)
    step_h = fov_h * (1.0 - overlap_frac)

    rot = math.radians(rotation_deg)
    cos_r = math.cos(rot)
    sin_r = math.sin(rot)
    cos_dec = math.cos(math.radians(center_dec))
    # Clamp to avoid division by zero near poles
    cos_dec = max(cos_dec, 0.01)

    panels = []
    for row in range(v_panels):
        for col in range(h_panels):
            # Offset from mosaic center in tangent plane (degrees)
            offset_x = (col - (h_panels - 1) / 2.0) * step_w
            offset_y = (row - (v_panels - 1) / 2.0) * step_h

            # Apply rotation
            rx = offset_x * cos_r - offset_y * sin_r
            ry = offset_x * sin_r + offset_y * cos_r

            # Project onto sphere (RA corrected for cos(dec))
            panel_ra = center_ra + rx / cos_dec
            panel_dec = center_dec + ry

            panels.append(MosaicPanel(
                ra_deg=panel_ra % 360.0,
                dec_deg=max(-90.0, min(90.0, panel_dec)),
                rotation_deg=rotation_deg,
                col=col,
                row=row,
                label=f"({col + 1},{row + 1})",
            ))

    # Compute total bounding box (unrotated approximation)
    total_w = fov_w + (h_panels - 1) * step_w
    total_h = fov_h + (v_panels - 1) * step_h

    return MosaicPlan(
        center_ra=center_ra,
        center_dec=center_dec,
        h_panels=h_panels,
        v_panels=v_panels,
        overlap_pct=overlap_pct,
        rotation_deg=rotation_deg,
        fov_w_deg=fov_w,
        fov_h_deg=fov_h,
        panels=panels,
        total_fov_w_deg=total_w,
        total_fov_h_deg=total_h,
    )


def export_csv(plan: MosaicPlan) -> str:
    """Export mosaic panel coordinates as CSV string."""
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(['Panel', 'RA (HMS)', 'Dec (DMS)', 'RA (deg)', 'Dec (deg)', 'Rotation (deg)'])

    for panel in plan.panels:
        writer.writerow([
            panel.label,
            format_ra(panel.ra_deg),
            format_dec(panel.dec_deg),
            f"{panel.ra_deg:.6f}",
            f"{panel.dec_deg:.6f}",
            f"{panel.rotation_deg:.1f}",
        ])

    return output.getvalue()
