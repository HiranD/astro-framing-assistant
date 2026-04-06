"""Altitude chart widget — bottom panel showing target visibility."""

import logging
from datetime import date

import numpy as np
import pytz
import matplotlib
matplotlib.use('Agg')
from matplotlib.figure import Figure
from matplotlib.dates import DateFormatter, HourLocator
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg

from PyQt6.QtWidgets import QWidget, QVBoxLayout
from PyQt6.QtCore import QThread, pyqtSignal, pyqtSlot

from core.visibility import VisibilityCalculator, ObserverConfig, AltitudeData

logger = logging.getLogger(__name__)


class _AltitudeWorker(QThread):
    """Background thread for altitude computation."""
    finished = pyqtSignal(object, list, list, str)  # AltitudeData, sun_times, sun_alts, timezone

    def __init__(self, calculator: VisibilityCalculator, ra: float, dec: float,
                 obs_date: date = None) -> None:
        super().__init__()
        self._calc = calculator
        self._ra = ra
        self._dec = dec
        self._obs_date = obs_date

    def run(self) -> None:
        try:
            alt_data = self._calc.compute_altitude_curve(self._ra, self._dec, self._obs_date)
            sun_times, sun_alts = self._calc.compute_sun_altitudes(self._obs_date)
            self.finished.emit(alt_data, sun_times, sun_alts, self._calc.timezone)
        except Exception:
            logger.exception("Altitude computation failed")


class AltitudeWidget(QWidget):
    """Bottom panel altitude/visibility chart."""

    def __init__(self, observer_config: ObserverConfig, parent=None) -> None:
        super().__init__(parent)
        self.setFixedHeight(200)

        self._calculator = VisibilityCalculator(observer_config)
        self._worker = None
        self._ra = None
        self._dec = None
        self._obs_date = date.today()

        self._figure = Figure(facecolor='#1a1a2e', figsize=(10, 2))
        self._canvas = FigureCanvasQTAgg(self._figure)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._canvas)

        self._draw_empty()

    def update_observer(self, config: ObserverConfig) -> None:
        """Update observer location and recompute."""
        self._calculator = VisibilityCalculator(config)
        if self._ra is not None:
            self.set_target(self._ra, self._dec)

    def set_target(self, ra_deg: float, dec_deg: float) -> None:
        """Compute and display altitude chart for a target."""
        self._ra = ra_deg
        self._dec = dec_deg
        self._recompute()

    def _recompute(self) -> None:
        """Launch altitude computation with current target and date."""
        if self._ra is None:
            return
        self._worker = _AltitudeWorker(
            self._calculator, self._ra, self._dec, self._obs_date)
        self._worker.finished.connect(self._on_computed)
        self._worker.start()

    def set_date(self, obs_date: date) -> None:
        """Update observation date and recompute."""
        self._obs_date = obs_date
        self._recompute()

    @pyqtSlot(object, list, list, str)
    def _on_computed(self, alt_data: AltitudeData, sun_times: list, sun_alts: list, timezone: str) -> None:
        self._draw_chart(alt_data, sun_times, sun_alts, timezone)

    def _draw_empty(self) -> None:
        """Draw empty chart placeholder."""
        self._figure.clear()
        ax = self._figure.add_subplot(111)
        ax.set_facecolor('#1a1a2e')
        ax.text(0.5, 0.5, "No target selected",
                color='gray', fontsize=10, ha='center', va='center',
                transform=ax.transAxes)
        ax.set_xticks([])
        ax.set_yticks([])
        for spine in ax.spines.values():
            spine.set_color('#333')
        self._canvas.draw_idle()

    def _draw_chart(self, alt_data: AltitudeData, sun_times: list, sun_alts: list, timezone: str) -> None:
        """Draw the full altitude chart."""
        self._figure.clear()
        ax = self._figure.add_subplot(111)
        ax.set_facecolor('#0a0a1e')

        # Convert UTC times to local timezone for display
        tz = pytz.timezone(timezone)
        utc = pytz.utc
        target_dates = [utc.localize(t.to_datetime()).astimezone(tz).replace(tzinfo=None) for t in alt_data.times]
        sun_dates = [utc.localize(t.to_datetime()).astimezone(tz).replace(tzinfo=None) for t in sun_times]
        sun_alt_arr = np.array(sun_alts)

        # Twilight shading bands using sun altitude
        twilight_colors = [
            (-90, -18, '#0a0a1e'),     # Night (astronomical dark)
            (-18, -12, '#0f1035'),     # Astronomical twilight
            (-12, -6, '#1a1a4e'),      # Nautical twilight
            (-6, 0, '#2a2a6e'),        # Civil twilight
            (0, 90, '#3a3a8e'),        # Daytime
        ]

        for low, high, color in twilight_colors:
            mask = (sun_alt_arr >= low) & (sun_alt_arr < high)
            if np.any(mask):
                # Find contiguous regions
                for start, end in self._contiguous_regions(mask):
                    ax.axvspan(
                        sun_dates[start], sun_dates[min(end, len(sun_dates) - 1)],
                        color=color, alpha=1.0, linewidth=0,
                    )

        # Horizon line
        ax.axhline(y=0, color='#666', linewidth=0.5, linestyle='-')
        ax.axhline(y=30, color='#333', linewidth=0.3, linestyle='--')
        ax.axhline(y=60, color='#333', linewidth=0.3, linestyle='--')

        # Target altitude curve
        altitudes = np.array(alt_data.altitudes)
        ax.plot(target_dates, altitudes, color='white', linewidth=1.5, zorder=5)

        # Fill under curve (above horizon only)
        alt_clipped = np.maximum(altitudes, 0)
        ax.fill_between(target_dates, 0, alt_clipped,
                         color='#4488ff', alpha=0.15, zorder=4)

        # Transit marker
        if alt_data.transit_time is not None:
            transit_dt = utc.localize(alt_data.transit_time.to_datetime()).astimezone(tz).replace(tzinfo=None)
            ax.axvline(x=transit_dt, color='#ff6644', linewidth=1,
                       linestyle='--', alpha=0.7, zorder=6)
            ax.text(transit_dt, alt_data.transit_altitude + 3,
                    f"{alt_data.transit_altitude:.0f}° Transit",
                    color='#ff6644', fontsize=7, ha='center', va='bottom',
                    zorder=7)

        # Styling
        ax.set_ylim(-5, 90)
        ax.set_xlim(target_dates[0], target_dates[-1])
        ax.set_ylabel("Alt (°)", color='#aaa', fontsize=8)

        ax.xaxis.set_major_locator(HourLocator(interval=3))
        ax.xaxis.set_major_formatter(DateFormatter('%H:%M'))

        ax.tick_params(axis='x', colors='#aaa', labelsize=7)
        ax.tick_params(axis='y', colors='#aaa', labelsize=7)

        for spine in ax.spines.values():
            spine.set_color('#333')

        self._figure.tight_layout(pad=0.5)
        self._canvas.draw_idle()

    @staticmethod
    def _contiguous_regions(mask: np.ndarray) -> list[tuple[int, int]]:
        """Find contiguous True regions in a boolean array."""
        regions = []
        in_region = False
        start = 0
        for i, val in enumerate(mask):
            if val and not in_region:
                start = i
                in_region = True
            elif not val and in_region:
                regions.append((start, i))
                in_region = False
        if in_region:
            regions.append((start, len(mask)))
        return regions
