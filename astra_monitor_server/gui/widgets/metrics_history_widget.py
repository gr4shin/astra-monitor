from PyQt5.QtWidgets import QWidget, QVBoxLayout, QGroupBox
from PyQt5.QtGui import QPainter, QColor, QPen, QFontMetrics
from PyQt5.QtCore import Qt


class LineChartWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.cpu = []
        self.mem = []
        self.disk = []
        self.setMinimumHeight(200)

    def set_data(self, cpu, mem, disk):
        self.cpu = cpu[-120:]
        self.mem = mem[-120:]
        self.disk = disk[-120:]
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        rect = self.rect()
        painter.fillRect(rect, self.palette().base())

        if not (self.cpu or self.mem or self.disk):
            painter.setPen(self.palette().text().color())
            painter.drawText(rect, Qt.AlignCenter, "Нет данных")
            painter.end()
            return

        padding_left = 36
        padding_right = 12
        padding_top = 18
        padding_bottom = 26
        chart_rect = rect.adjusted(padding_left, padding_top, -padding_right, -padding_bottom)

        grid_pen = QPen(self.palette().mid().color(), 1, Qt.DotLine)
        painter.setPen(grid_pen)
        for i in range(1, 5):
            y = chart_rect.top() + int(chart_rect.height() * i / 5)
            painter.drawLine(chart_rect.left(), y, chart_rect.right(), y)

        axis_pen = QPen(self.palette().text().color(), 1)
        painter.setPen(axis_pen)
        painter.drawLine(chart_rect.left(), chart_rect.bottom(), chart_rect.right(), chart_rect.bottom())
        painter.drawLine(chart_rect.left(), chart_rect.top(), chart_rect.left(), chart_rect.bottom())

        font_metrics = QFontMetrics(painter.font())
        for value in (0, 25, 50, 75, 100):
            y = chart_rect.bottom() - int(chart_rect.height() * value / 100)
            label = f"{value}%"
            painter.drawText(chart_rect.left() - font_metrics.horizontalAdvance(label) - 6,
                             y + int(font_metrics.ascent() / 2),
                             label)

        max_len = max(len(self.cpu), len(self.mem), len(self.disk), 2)

        def draw_series(values, color):
            if len(values) < 2:
                return
            pen = QPen(color, 2)
            painter.setPen(pen)
            for i in range(1, len(values)):
                x1 = chart_rect.left() + int(chart_rect.width() * (i - 1) / (max_len - 1))
                x2 = chart_rect.left() + int(chart_rect.width() * i / (max_len - 1))
                y1 = chart_rect.bottom() - int(chart_rect.height() * values[i - 1] / 100)
                y2 = chart_rect.bottom() - int(chart_rect.height() * values[i] / 100)
                painter.drawLine(x1, y1, x2, y2)

        draw_series(self.cpu, QColor("#ef4444"))
        draw_series(self.mem, QColor("#22c55e"))
        draw_series(self.disk, QColor("#3b82f6"))

        legend_y = rect.top() + 2
        legend_x = chart_rect.left()
        legend_gap = 10
        for name, color in (("CPU", QColor("#ef4444")),
                            ("RAM", QColor("#22c55e")),
                            ("Disk", QColor("#3b82f6"))):
            painter.setPen(QPen(color, 2))
            painter.drawLine(legend_x, legend_y + 6, legend_x + 12, legend_y + 6)
            painter.setPen(self.palette().text().color())
            painter.drawText(legend_x + 16, legend_y + 10, name)
            legend_x += 16 + font_metrics.horizontalAdvance(name) + legend_gap

        painter.end()


class MetricsHistoryWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.chart_widget = LineChartWidget()
        self.init_ui()

    def init_ui(self):
        layout = QVBoxLayout(self)
        group = QGroupBox("История метрик")
        group_layout = QVBoxLayout(group)

        group_layout.addWidget(self.chart_widget)
        layout.addWidget(group)

    def update_history(self, history):
        cpu = list(history.get("cpu", []))
        mem = list(history.get("mem", []))
        disk = list(history.get("disk", []))
        self.chart_widget.set_data(cpu, mem, disk)
