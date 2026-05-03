"""Application bootstrap for Astro Framing Assistant."""

import datetime as _dt
import os as _os
import sys
import logging
import traceback
from pathlib import Path

LOG_PREFIX = 'session-'
LOG_KEEP = 10  # retain at most this many per-session log files


def _rotate_session_logs(logs_dir: Path, keep: int) -> None:
    """Delete oldest session logs so that after the new one is created,
    at most `keep` files remain in `logs_dir`."""
    files = sorted(logs_dir.glob(f'{LOG_PREFIX}*.log'))
    while len(files) > keep - 1:
        try:
            files[0].unlink()
        except OSError:
            pass
        files.pop(0)


# Log to file when frozen (no console)
if getattr(sys, 'frozen', False):
    logs_dir = Path.home() / '.astro-framing' / 'logs'
    logs_dir.mkdir(parents=True, exist_ok=True)
    _rotate_session_logs(logs_dir, LOG_KEEP)
    _ts = _dt.datetime.now().strftime('%Y%m%d-%H%M%S')
    log_path = logs_dir / f'{LOG_PREFIX}{_ts}-{_os.getpid()}.log'
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s %(name)s %(levelname)s: %(message)s',
        datefmt='%H:%M:%S',
        filename=str(log_path),
        # Each session gets its own file — overwrite mode is fine; rotation
        # by _rotate_session_logs() keeps only the LOG_KEEP newest files.
        filemode='w',
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
