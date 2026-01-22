from PyQt5.QtCore import Qt, QTimer, QSize
from PyQt5.QtWidgets import QFrame, QLabel, QHBoxLayout


class Toast(QFrame):
    def __init__(self, parent, message, bg_color, text_color, duration_ms=2500, icon=None, icon_size=16):
        super().__init__(parent)
        self.setWindowFlags(Qt.ToolTip | Qt.FramelessWindowHint)
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 8, 12, 8)
        layout.setSpacing(6)

        if icon:
            icon_label = QLabel()
            icon_label.setPixmap(icon.pixmap(QSize(icon_size, icon_size)))
            layout.addWidget(icon_label)

        label = QLabel(message)
        label.setStyleSheet(f"color: {text_color};")
        layout.addWidget(label)

        self.setStyleSheet(
            f"background-color: {bg_color}; border-radius: 8px;"
        )

        QTimer.singleShot(duration_ms, self.close)
