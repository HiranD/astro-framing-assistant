"""Astro Framing Assistant — Entry point."""

import sys
import os
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
