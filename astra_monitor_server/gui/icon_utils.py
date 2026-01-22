import os
import sys

from PyQt5.QtCore import QSize, Qt
from PyQt5.QtGui import QIcon, QPixmap, QImage, QPainter, QColor

try:
    from PyQt5.QtSvg import QSvgRenderer
except ImportError:
    QSvgRenderer = None


def asset_path(*parts):
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        base_path = sys._MEIPASS
    else:
        base_path = "."
    return os.path.join(base_path, *parts)


def load_icon(path, color=None, size=None):
    image = None
    if path.lower().endswith(".svg"):
        if QSvgRenderer is None:
            return QIcon()
        renderer = QSvgRenderer(path)
        if not renderer.isValid():
            return QIcon()
        target_size = renderer.defaultSize()
        if target_size.isEmpty():
            target_size = QSize(24, 24)
        if size:
            target_size = QSize(size, size)
        pixmap = QPixmap(target_size)
        pixmap.fill(Qt.transparent)
        painter = QPainter(pixmap)
        renderer.render(painter)
        painter.end()
        image = pixmap.toImage()
    else:
        image = QImage(path)
        if image.isNull():
            return QIcon()
        if size:
            image = image.scaled(size, size, Qt.KeepAspectRatio, Qt.SmoothTransformation)

    if color:
        image = image.convertToFormat(QImage.Format_ARGB32)
        tinted = QImage(image.size(), QImage.Format_ARGB32)
        tinted.fill(color)
        painter = QPainter(tinted)
        painter.setCompositionMode(QPainter.CompositionMode_DestinationIn)
        painter.drawImage(0, 0, image)
        painter.end()
        image = tinted

    return QIcon(QPixmap.fromImage(image))


def load_icon_from_assets(name, color=None, size=None):
    icon_path = asset_path("assets", "icons", name)
    if not os.path.exists(icon_path):
        return QIcon()
    return load_icon(icon_path, color=color, size=size)
