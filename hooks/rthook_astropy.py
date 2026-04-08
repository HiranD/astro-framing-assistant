"""PyInstaller runtime hook — disable astropy IERS auto-download in frozen apps."""

from astropy.utils.iers import conf as iers_conf

iers_conf.auto_download = False
iers_conf.auto_max_age = None
iers_conf.iers_degraded_accuracy = 'silent'
