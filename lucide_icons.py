"""Locally bundled Lucide 0.468.0 icons. See lucide/LICENSE."""
from functools import cache
from pathlib import Path
import sys

from PySide6.QtCore import QByteArray, QSize, Qt
from PySide6.QtGui import QIcon, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer


@cache
def lucide_icon(name, color, size=18, *, filled=False):
    base = Path(getattr(sys, '_MEIPASS', Path(__file__).resolve().parent))
    svg = (base / 'lucide' / f'{name}.svg').read_bytes()
    if filled:
        svg = svg.replace(b'fill="none"', b'fill="currentColor"', 1)
    renderer = QSvgRenderer(QByteArray(svg.replace(b'currentColor', color.encode('ascii'))))
    icon = QIcon()
    for ratio in (1, 1.25, 1.5, 1.75, 2, 3):
        pixels = round(size * ratio)
        pixmap = QPixmap(QSize(pixels, pixels))
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        renderer.render(painter)
        painter.end()
        pixmap.setDevicePixelRatio(ratio)
        icon.addPixmap(pixmap)
    return icon
