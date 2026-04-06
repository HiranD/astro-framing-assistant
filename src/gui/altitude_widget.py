"""Altitude chart widget — bottom panel showing target visibility."""

import logging
from datetime import date

import math

import numpy as np
import pytz
import matplotlib
matplotlib.use('Agg')
from matplotlib.figure import Figure
from matplotlib.dates import DateFormatter, HourLocator, num2date
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg

from PyQt6.QtWidgets import QWidget, QVBoxLayout, QToolButton
from PyQt6.QtCore import QThread, pyqtSignal, pyqtSlot, Qt, QSize
from PyQt6.QtGui import QPixmap, QPainter, QColor, QIcon, QPainterPath

from core.visibility import VisibilityCalculator, ObserverConfig, AltitudeData

logger = logging.getLogger(__name__)


class _AltitudeWorker(QThread):
    """Background thread for altitude computation."""
    finished = pyqtSignal(object, list, list, list, list, float, str)

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
            moon_times, moon_alts, moon_illum = self._calc.compute_moon_altitudes(self._obs_date)
            self.finished.emit(alt_data, sun_times, sun_alts, moon_times, moon_alts, moon_illum, self._calc.timezone)
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

        # Mouse-over state
        self._chart_dates = None
        self._chart_alts = None
        self._chart_moon_dates = None
        self._chart_moon_alts = None
        self._hover_vline = None
        self._hover_hline = None
        self._hover_text = None
        self._canvas.mpl_connect('motion_notify_event', self._on_mouse_move)

        # Moon toggle button (overlaid on chart)
        self._show_moon = True
        self._moon_illumination = 0.0
        self._moon_btn = QToolButton(self)
        self._moon_btn.setCheckable(True)
        self._moon_btn.setChecked(True)
        self._moon_btn.setToolTip("Toggle moon altitude curve\nClick to show/hide")
        self._moon_btn.setFixedSize(30, 30)
        self._moon_btn.setStyleSheet(
            "QToolButton { background: rgba(40,40,60,180); border: 1px solid #555; border-radius: 4px; }"
            "QToolButton:checked { border: 1px solid #ffaa00; }"
        )
        self._moon_btn.clicked.connect(self._on_moon_toggled)
        self._update_moon_icon(0.0)
        self._moon_line = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._canvas)

        # Raise moon button above canvas
        self._moon_btn.raise_()

        self._draw_empty()

    def resizeEvent(self, event) -> None:
        """Position moon button in top-right corner."""
        super().resizeEvent(event)
        self._position_moon_btn()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self._position_moon_btn()

    def _position_moon_btn(self) -> None:
        self._moon_btn.move(self.width() - 36, 6)
        self._moon_btn.raise_()

    def _update_moon_icon(self, illumination: float) -> None:
        """Draw a moon phase icon based on illumination fraction (0-1)."""
        size = 22
        pm = QPixmap(size, size)
        pm.fill(QColor(0, 0, 0, 0))
        p = QPainter(pm)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        cx, cy, r = size / 2, size / 2, size / 2 - 1

        # Dark moon background
        p.setBrush(QColor(40, 40, 55))
        p.setPen(QColor(100, 100, 100))
        p.drawEllipse(int(cx - r), int(cy - r), int(r * 2), int(r * 2))

        # Draw lit portion using vertical slices
        if illumination > 0.01:
            lit = QPainterPath()
            steps = 60
            # Terminator x-offset from center
            # At 0% → tx = -r (terminator at left edge, nothing lit on right)
            # At 50% → tx = 0 (half moon)
            # At 100% → tx = +r (terminator at right edge, fully lit)
            tx = r * (2 * illumination - 1)

            # Lit region: from terminator to right edge
            points_right = []
            points_term = []
            for i in range(steps + 1):
                angle = math.pi * i / steps  # 0 to pi (top to bottom)
                y = cy - r * math.cos(angle)
                sin_a = math.sin(angle)
                points_right.append((cx + r * sin_a, y))
                points_term.append((cx - tx * sin_a, y))

            # Path: go down right edge, come back up along terminator
            lit.moveTo(points_right[0][0], points_right[0][1])
            for x, y in points_right[1:]:
                lit.lineTo(x, y)
            for x, y in reversed(points_term):
                lit.lineTo(x, y)
            lit.closeSubpath()

            # Clip to moon circle
            circle = QPainterPath()
            circle.addEllipse(cx - r, cy - r, r * 2, r * 2)
            lit = lit.intersected(circle)

            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(210, 210, 190))
            p.drawPath(lit)

        p.end()
        self._moon_btn.setIcon(QIcon(pm))
        self._moon_btn.setIconSize(QSize(size, size))

    def _on_moon_toggled(self) -> None:
        """Toggle moon curve visibility."""
        self._show_moon = self._moon_btn.isChecked()
        if self._moon_line:
            self._moon_line.set_visible(self._show_moon)
            self._canvas.draw_idle()

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

    @pyqtSlot(object, list, list, list, list, float, str)
    def _on_computed(self, alt_data: AltitudeData, sun_times: list, sun_alts: list,
                     moon_times: list, moon_alts: list, moon_illum: float, timezone: str) -> None:
        self._update_moon_icon(moon_illum)
        self._moon_illumination = moon_illum
        self._moon_btn.setToolTip(f"Moon {moon_illum * 100:.0f}% illuminated\nClick to toggle")
        self._draw_chart(alt_data, sun_times, sun_alts, moon_times, moon_alts, timezone)

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

    def _draw_chart(self, alt_data: AltitudeData, sun_times: list, sun_alts: list,
                     moon_times: list, moon_alts: list, timezone: str) -> None:
        """Draw the full altitude chart."""
        self._figure.clear()
        ax = self._figure.add_subplot(111)
        ax.set_facecolor('#0a0a1e')

        # Convert UTC times to local timezone for display
        # Use fixed UTC offset (from noon) to avoid DST fold causing non-monotonic times
        tz = pytz.timezone(timezone)
        utc = pytz.utc
        noon_utc = utc.localize(alt_data.times[0].to_datetime())
        fixed_offset = noon_utc.astimezone(tz).utcoffset()

        def to_local(t):
            return t.to_datetime() + fixed_offset

        target_dates = [to_local(t) for t in alt_data.times]
        sun_dates = [to_local(t) for t in sun_times]
        sun_alt_arr = np.array(sun_alts)
        moon_dates = [to_local(t) for t in moon_times]
        moon_alt_arr = np.array(moon_alts)

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

        # Moon altitude curve
        moon_line, = ax.plot(moon_dates, moon_alt_arr, color='#ffaa00', linewidth=0.8,
                             alpha=0.6, zorder=4)
        self._moon_line = moon_line
        moon_line.set_visible(self._show_moon)

        # Transit marker
        if alt_data.transit_time is not None:
            transit_dt = to_local(alt_data.transit_time)
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

        # Store data for mouse-over
        self._chart_dates = target_dates
        self._chart_alts = altitudes
        self._chart_moon_dates = moon_dates
        self._chart_moon_alts = moon_alt_arr
        self._hover_vline = ax.axvline(x=target_dates[0], color='#aaa', linewidth=0.5,
                                        linestyle=':', visible=False, zorder=8)
        self._hover_hline = ax.axhline(y=0, color='#aaa', linewidth=0.5,
                                        linestyle=':', visible=False, zorder=8)
        self._hover_text = ax.text(0, 0, '', color='#fff', fontsize=7,
                                    ha='left', va='bottom', zorder=9,
                                    bbox=dict(boxstyle='round,pad=0.3',
                                              facecolor='#333', edgecolor='#555', alpha=0.9))
        self._hover_text.set_visible(False)

        self._figure.tight_layout(pad=0.5)
        self._canvas.draw_idle()

    def _on_mouse_move(self, event) -> None:
        """Show time and altitude on mouse hover."""
        if (self._chart_dates is None or event.inaxes is None
                or event.xdata is None):
            if self._hover_vline and self._hover_vline.get_visible():
                self._hover_vline.set_visible(False)
                self._hover_hline.set_visible(False)
                self._hover_text.set_visible(False)
                self._canvas.draw_idle()
            return

        hover_dt = num2date(event.xdata).replace(tzinfo=None)
        # Find nearest index for target
        idx = np.argmin(np.abs(np.array([
            (d - hover_dt).total_seconds() for d in self._chart_dates])))
        alt = float(self._chart_alts[idx])
        t = self._chart_dates[idx]

        # Find nearest moon altitude
        moon_alt = 0.0
        if self._chart_moon_dates is not None:
            moon_idx = np.argmin(np.abs(np.array([
                (d - hover_dt).total_seconds() for d in self._chart_moon_dates])))
            moon_alt = float(self._chart_moon_alts[moon_idx])

        self._hover_vline.set_xdata([t, t])
        self._hover_vline.set_visible(True)
        self._hover_hline.set_ydata([alt, alt])
        self._hover_hline.set_visible(True)

        label = f"Time: {t.strftime('%H:%M')}\nAlt: {alt:.1f}°\nMoon: {moon_alt:.1f}°"
        self._hover_text.set_text(label)
        self._hover_text.set_position((event.xdata, alt + 3))
        self._hover_text.set_visible(True)
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
