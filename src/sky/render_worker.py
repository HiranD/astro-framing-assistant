"""Background worker thread for tile rendering."""

import numpy as np
from PyQt6.QtCore import QThread, pyqtSignal
from astropy.wcs import WCS

from sky.tile_renderer import TileRenderer


class RenderWorker(QThread):
    """Runs tile rendering off the main thread.

    Only does numpy/reproject operations (thread-safe).
    All matplotlib calls must happen on the main thread.
    """

    finished = pyqtSignal(object, object)  # image (ndarray), wcs

    def __init__(self, renderer: TileRenderer, target_wcs: WCS,
                 canvas_shape: tuple[int, int]) -> None:
        super().__init__()
        self._renderer = renderer
        self._target_wcs = target_wcs
        self._canvas_shape = canvas_shape

    def run(self) -> None:
        image = self._renderer.render(self._target_wcs, self._canvas_shape)
        self.finished.emit(image, self._target_wcs)
