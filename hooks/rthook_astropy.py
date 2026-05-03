"""PyInstaller runtime hook — disable astropy IERS auto-download in frozen apps.

Also patches multiprocessing.resource_tracker BEFORE astropy is imported.
The astropy import below transitively pulls in numcodecs.blosc (via
astropy.io.fits.hdu.compressed), which creates a multiprocessing.Lock at
module load time. That triggers spawning a tracker child via
Popen([sys.executable, '-c', '...']); on a frozen .app sys.executable is
the bundle's bootloader binary, so every spawn is a full .app relaunch.
Worse: each relaunched helper also runs this hook, re-imports astropy,
re-creates a Lock, spawns another tracker → fork bomb (thousands of ghost
children, ~70 GB aggregate RSS, system swap-thrashing, eventual hang/reboot).

We never use multiprocessing for real work, so neutering the tracker is
safe: POSIX semaphores get reclaimed by the OS on process exit.
"""

import sys

if getattr(sys, 'frozen', False):
    try:
        import multiprocessing.resource_tracker as _rt
        _rt.ResourceTracker.ensure_running = lambda self: None
        _rt.ResourceTracker._send = lambda self, *a, **kw: None
    except Exception:
        pass

from astropy.utils.iers import conf as iers_conf

iers_conf.auto_download = False
iers_conf.auto_max_age = None
iers_conf.iers_degraded_accuracy = 'ignore'
