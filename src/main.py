"""Application bootstrap for Astro Framing Assistant."""

import datetime as _dt
import os as _os
import sys
import logging
import traceback
from pathlib import Path

# Log to file when frozen (no console)
if getattr(sys, 'frozen', False):
    log_path = Path.home() / '.astro-framing' / 'app.log'
    log_path.parent.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s %(name)s %(levelname)s: %(message)s',
        datefmt='%H:%M:%S',
        filename=str(log_path),
        # Append: prior session's tail (including a hang/crash) survives
        # into the next launch's log instead of being overwritten.
        filemode='a',
    )
    logging.info(
        "=== SESSION START %s pid=%d ===",
        _dt.datetime.now().isoformat(timespec='seconds'),
        _os.getpid(),
    )
    # Catch unhandled exceptions so PyQt6 doesn't abort
    def _excepthook(exc_type, exc_value, exc_tb):
        logging.critical("Unhandled exception", exc_info=(exc_type, exc_value, exc_tb))
    sys.excepthook = _excepthook
else:
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s %(name)s %(levelname)s: %(message)s',
        datefmt='%H:%M:%S',
    )


def run_app() -> None:
    """Create and run the application."""
    from PyQt6.QtWidgets import QApplication
    import qdarktheme

    from gui.app import FramingApp

    app = QApplication(sys.argv)

    # Force C locale so decimal separator is always "." (not ",")
    from PyQt6.QtCore import QLocale
    QLocale.setDefault(QLocale(QLocale.Language.C))

    app.setApplicationName("Astro Framing Assistant")
    app.setOrganizationName("AstroFraming")
    qdarktheme.setup_theme('dark')

    window = FramingApp()
    window.show()

    sys.exit(app.exec())
