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
