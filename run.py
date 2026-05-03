"""Astro Framing Assistant — Entry point."""

import sys
import os

# CRITICAL: detect multiprocessing helper re-launches and exit early before
# any other imports. PyInstaller's pyi_rth_multiprocessing hook patches
# multiprocessing.freeze_support() to do this, but only AFTER we call
# freeze_support() — which in turn means after run.py's other imports have
# already executed inside the helper child. On a frozen macOS .app each
# helper relaunch re-runs the bundle's bootloader; if astropy/numcodecs ends
# up imported during that relaunch (directly or transitively), a new
# multiprocessing.Lock is created → another resource_tracker spawns → fork
# bomb (thousands of ghost AstroFramingAssistant processes, ~70 GB aggregate
# RSS, system swap-thrashing).
if getattr(sys, 'frozen', False) and '-c' in sys.argv:
    try:
        _cmd = sys.argv[sys.argv.index('-c') + 1]
    except (IndexError, ValueError):
        _cmd = ''
    if _cmd.startswith((
        'from multiprocessing.resource_tracker import main',
        'from multiprocessing.forkserver import main',
        'import sys; from multiprocessing.forkserver import main',
    )):
        exec(_cmd)
        sys.exit(0)

# Disable multiprocessing.resource_tracker spawning entirely. The previous
# `-c` early-exit above prevents *recursive* fork bombs (helper relaunches
# importing the full app), but doesn't stop the original spawn that happens
# when numcodecs.blosc — pulled in transitively by astropy.io.fits — creates
# a multiprocessing.Lock at module load time. Under macOS memory pressure
# jetsam may kill the tracker child; Python then respawns it on every
# subsequent Lock operation. Each respawn is a brief .app launch that
# forces ~64 MB of DYLD page unnesting (kernel: "triggered unnest of range
# ... in VM map ... increases system memory footprint until the target
# exits"), and at the rate Python respawns under pressure this churns
# through physical memory and contributes to the very pressure that's
# killing it. We never actually use multiprocessing for real work, so
# losing the tracker just means POSIX semaphores aren't auto-cleaned on
# crash — they get reclaimed by the OS on process exit anyway.
if getattr(sys, 'frozen', False):
    try:
        import multiprocessing.resource_tracker as _rt
        _rt.ResourceTracker.ensure_running = lambda self: None
        _rt.ResourceTracker._send = lambda self, *a, **kw: None
    except Exception:
        pass

from multiprocessing import freeze_support

# Set macOS app name in menu bar (must run before any Qt imports)
if sys.platform == 'darwin':
    try:
        from Foundation import NSBundle
        info = NSBundle.mainBundle().infoDictionary()
        info['CFBundleName'] = 'Astro Framing Assistant'
    except Exception:
        pass

# Add src/ to path for imports
if getattr(sys, 'frozen', False):
    _base = sys._MEIPASS
else:
    _base = os.path.dirname(__file__)
sys.path.insert(0, os.path.join(_base, 'src'))


def main():
    from main import run_app
    run_app()


if __name__ == '__main__':
    freeze_support()
    main()
