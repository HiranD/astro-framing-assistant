"""Astro Framing Assistant — Entry point."""

import sys
import os
from multiprocessing import freeze_support

# Add src/ to path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))


def main():
    from main import run_app
    run_app()


if __name__ == '__main__':
    freeze_support()
    main()
