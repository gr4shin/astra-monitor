from PyQt5.QtWidgets import QWidget, QVBoxLayout, QGroupBox, QTextEdit
from PyQt5.QtGui import QPainter

try:
    from PyQt5.QtChart import QChart, QChartView, QLineSeries, QValueAxis
    HAS_CHART = True
except ImportError:
    HAS_CHART = False


class MetricsHistoryWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.cpu_series = QLineSeries() if HAS_CHART else None
        self.mem_series = QLineSeries() if HAS_CHART else None
        self.disk_series = QLineSeries() if HAS_CHART else None
        self.text_view = None
        self.init_ui()

    def init_ui(self):
        layout = QVBoxLayout(self)
        group = QGroupBox("История метрик")
        group_layout = QVBoxLayout(group)

        if HAS_CHART:
            self.chart = QChart()
            self.chart.addSeries(self.cpu_series)
            self.chart.addSeries(self.mem_series)
            self.chart.addSeries(self.disk_series)
            self.chart.legend().setVisible(True)
            self.chart.legend().setAlignment(self.chart.legend().AlignmentBottom)
            self.chart.setBackgroundVisible(False)
            self.chart.setTitle("CPU / RAM / Disk")

            self.cpu_series.setName("CPU")
            self.mem_series.setName("RAM")
            self.disk_series.setName("Disk")

            axis_x = QValueAxis()
            axis_x.setLabelFormat("%d")
            axis_x.setRange(0, 120)
            axis_x.setTickCount(7)
            axis_x.setTitleText("Последние точки")

            axis_y = QValueAxis()
            axis_y.setRange(0, 100)
            axis_y.setTickCount(6)
            axis_y.setTitleText("%")

            self.chart.addAxis(axis_x, self.chart.AxisBottom)
            self.chart.addAxis(axis_y, self.chart.AxisLeft)
            for series in (self.cpu_series, self.mem_series, self.disk_series):
                series.attachAxis(axis_x)
                series.attachAxis(axis_y)

            chart_view = QChartView(self.chart)
            chart_view.setRenderHint(QPainter.Antialiasing)
            group_layout.addWidget(chart_view)
        else:
            self.text_view = QTextEdit()
            self.text_view.setReadOnly(True)
            self.text_view.setLineWrapMode(QTextEdit.NoWrap)
            group_layout.addWidget(self.text_view)
        layout.addWidget(group)

    def update_history(self, history):
        cpu = list(history.get("cpu", []))
        mem = list(history.get("mem", []))
        disk = list(history.get("disk", []))
        if not HAS_CHART:
            self.text_view.setPlainText(
                "\n".join([
                    self._format_series("CPU", cpu),
                    self._format_series("RAM", mem),
                    self._format_series("Disk", disk),
                ])
            )
            return

        max_len = max(len(cpu), len(mem), len(disk), 1)

        self.cpu_series.clear()
        self.mem_series.clear()
        self.disk_series.clear()

        for i, val in enumerate(cpu[-120:]):
            self.cpu_series.append(i, val)
        for i, val in enumerate(mem[-120:]):
            self.mem_series.append(i, val)
        for i, val in enumerate(disk[-120:]):
            self.disk_series.append(i, val)

        self.chart.axisX().setRange(0, max(max_len - 1, 1))

    def _format_series(self, name, values):
        vals = values[-30:]
        if not vals:
            return f"{name}: нет данных"
        blocks = " .:-=+*#%@"
        scaled = [min(9, int(v / 10)) for v in vals]
        bar = "".join(blocks[i] for i in scaled)
        return f"{name}: {bar} ({vals[-1]:.1f}%)"
