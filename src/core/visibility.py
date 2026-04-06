"""Visibility and altitude calculations for targets."""

import logging
from dataclasses import dataclass, field
from datetime import datetime, date, timedelta
from typing import Optional

import numpy as np
import pytz
from astropy.coordinates import SkyCoord, EarthLocation, AltAz, get_sun, get_body
from astropy.time import Time
import astropy.units as u
from astroplan import Observer, FixedTarget

logger = logging.getLogger(__name__)


@dataclass
class ObserverConfig:
    """Observer location configuration."""
    latitude: float = 0.0
    longitude: float = 0.0
    elevation: float = 0.0        # meters
    timezone: str = "UTC"


@dataclass
class TwilightTimes:
    """Twilight boundary times (UTC)."""
    sunset: Optional[Time] = None
    civil_dusk: Optional[Time] = None
    nautical_dusk: Optional[Time] = None
    astronomical_dusk: Optional[Time] = None
    astronomical_dawn: Optional[Time] = None
    nautical_dawn: Optional[Time] = None
    civil_dawn: Optional[Time] = None
    sunrise: Optional[Time] = None


@dataclass
class AltitudeData:
    """Computed altitude curve data."""
    times: list = field(default_factory=list)          # astropy Time objects
    altitudes: list = field(default_factory=list)       # degrees
    transit_time: Optional[Time] = None
    transit_altitude: float = 0.0


class VisibilityCalculator:
    """Computes target altitude curves and twilight times."""

    def __init__(self, config: ObserverConfig) -> None:
        self._config = config
        self._location = EarthLocation(
            lat=config.latitude * u.deg,
            lon=config.longitude * u.deg,
            height=config.elevation * u.m,
        )
        self._observer = Observer(
            location=self._location,
            timezone=config.timezone,
        )

    def compute_altitude_curve(
        self,
        ra_deg: float,
        dec_deg: float,
        obs_date: date = None,
    ) -> AltitudeData:
        """Compute altitude over 24 hours centered on midnight.

        Args:
            ra_deg: Target RA in degrees.
            dec_deg: Target Dec in degrees.
            obs_date: Date for computation (default: today).

        Returns:
            AltitudeData with times and altitudes.
        """
        if obs_date is None:
            obs_date = date.today()

        target = FixedTarget(
            coord=SkyCoord(ra=ra_deg * u.deg, dec=dec_deg * u.deg),
        )

        # 24h from local noon to local noon, 5-minute intervals
        local_noon = self._local_noon_utc(obs_date)
        times = local_noon + np.linspace(0, 24, 288) * u.hour

        # Compute altitudes
        altaz_frame = AltAz(obstime=times, location=self._location)
        target_coord = SkyCoord(ra=ra_deg * u.deg, dec=dec_deg * u.deg)
        altaz = target_coord.transform_to(altaz_frame)
        altitudes = altaz.alt.deg

        # Find transit (max altitude)
        max_idx = np.argmax(altitudes)
        transit_time = times[max_idx]
        transit_alt = float(altitudes[max_idx])

        return AltitudeData(
            times=list(times),
            altitudes=list(altitudes),
            transit_time=transit_time,
            transit_altitude=transit_alt,
        )

    def compute_twilight_times(self, obs_date: date = None) -> TwilightTimes:
        """Compute twilight boundary times for a given date.

        Args:
            obs_date: Date for computation (default: today).

        Returns:
            TwilightTimes with all twilight boundaries.
        """
        if obs_date is None:
            obs_date = date.today()

        ref_time = self._local_noon_utc(obs_date)

        twilight = TwilightTimes()

        try:
            twilight.sunset = self._observer.sun_set_time(ref_time, which='next')
            twilight.sunrise = self._observer.sun_rise_time(ref_time + 1 * u.day, which='nearest')

            twilight.civil_dusk = self._observer.twilight_evening_civil(ref_time, which='next')
            twilight.nautical_dusk = self._observer.twilight_evening_nautical(ref_time, which='next')
            twilight.astronomical_dusk = self._observer.twilight_evening_astronomical(ref_time, which='next')

            twilight.astronomical_dawn = self._observer.twilight_morning_astronomical(ref_time + 1 * u.day, which='nearest')
            twilight.nautical_dawn = self._observer.twilight_morning_nautical(ref_time + 1 * u.day, which='nearest')
            twilight.civil_dawn = self._observer.twilight_morning_civil(ref_time + 1 * u.day, which='nearest')
        except Exception:
            logger.exception("Error computing twilight times")

        return twilight

    def compute_sun_altitudes(self, obs_date: date = None) -> tuple[list, list]:
        """Compute sun altitude curve (for twilight shading).

        Returns:
            (times, sun_altitudes) tuple.
        """
        if obs_date is None:
            obs_date = date.today()

        local_noon = self._local_noon_utc(obs_date)
        times = local_noon + np.linspace(0, 24, 288) * u.hour

        altaz_frame = AltAz(obstime=times, location=self._location)
        sun_altaz = get_sun(times).transform_to(altaz_frame)

        return list(times), list(sun_altaz.alt.deg)

    def compute_moon_altitudes(self, obs_date: date = None) -> tuple[list, list, float]:
        """Compute moon altitude curve and illumination.

        Returns:
            (times, moon_altitudes, illumination) tuple.
            illumination is a fraction 0-1 at midnight.
        """
        if obs_date is None:
            obs_date = date.today()

        local_noon = self._local_noon_utc(obs_date)
        times = local_noon + np.linspace(0, 24, 288) * u.hour

        altaz_frame = AltAz(obstime=times, location=self._location)
        moon_altaz = get_body('moon', times).transform_to(altaz_frame)

        # Moon illumination at local midnight
        midnight = local_noon + 12 * u.hour
        illumination = float(self._observer.moon_illumination(midnight))

        return list(times), list(moon_altaz.alt.deg), illumination

    @property
    def timezone(self) -> str:
        return self._config.timezone

    def _local_noon_utc(self, obs_date: date) -> Time:
        """Get local noon as a UTC Time object."""
        tz = pytz.timezone(self._config.timezone)
        local_noon = tz.localize(datetime(obs_date.year, obs_date.month, obs_date.day, 12, 0))
        return Time(local_noon.astimezone(pytz.utc).replace(tzinfo=None))
