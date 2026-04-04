"""Application bootstrap for Astro Framing Assistant."""

import sys
import logging

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
    app.setApplicationName("Astro Framing Assistant")
    app.setOrganizationName("AstroFraming")
    qdarktheme.setup_theme('dark')

    window = FramingApp()
    window.show()

    sys.exit(app.exec())
