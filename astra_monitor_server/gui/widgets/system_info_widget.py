# astra_monitor_server/gui/widgets/system_info_widget.py

from PyQt5.QtWidgets import QWidget, QVBoxLayout, QGroupBox, QLabel, QProgressBar
from PyQt5.QtGui import QFont

class SystemInfoWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.init_ui()
        
    def init_ui(self):
        layout = QVBoxLayout(self)
        
        # CPU
        cpu_group = QGroupBox("Процессор (CPU)")
        cpu_layout = QVBoxLayout(cpu_group)
        self.cpu_label = QLabel("0%")
        self.cpu_label.setFont(QFont("Arial", 16, QFont.Bold))
        self.cpu_bar = QProgressBar()
        cpu_layout.addWidget(self.cpu_label)
        cpu_layout.addWidget(self.cpu_bar)
        
        # Memory
        mem_group = QGroupBox("Память (RAM)")
        mem_layout = QVBoxLayout(mem_group)
        self.mem_label = QLabel("0%")
        self.mem_label.setFont(QFont("Arial", 16, QFont.Bold))
        self.mem_bar = QProgressBar()
        mem_layout.addWidget(self.mem_label)
        mem_layout.addWidget(self.mem_bar)
        
        # Disk
        disk_group = QGroupBox("Диск (Storage)")
        disk_layout = QVBoxLayout(disk_group)
        self.disk_label = QLabel("0%")
        self.disk_label.setFont(QFont("Arial", 16, QFont.Bold))
        self.disk_bar = QProgressBar()
        disk_layout.addWidget(self.disk_label)
        disk_layout.addWidget(self.disk_bar)
        
        layout.addWidget(cpu_group)
        layout.addWidget(mem_group)
        layout.addWidget(disk_group)
        
    def update_info(self, data):
        cpu = data.get('cpu_percent', 0)
        mem = data.get('memory_percent', 0)
        disk = data.get('disk_percent', 0)
        
        self.cpu_label.setText(f"{cpu}%")
        self.cpu_bar.setValue(int(cpu))
        self.cpu_bar.setStyleSheet(self.get_bar_style(cpu))
        
        self.mem_label.setText(f"{mem}%")
        self.mem_bar.setValue(int(mem))
        self.mem_bar.setStyleSheet(self.get_bar_style(mem))

        disk_used = data.get('disk_used')
        disk_total = data.get('disk_total')
        if all(isinstance(v, (int, float)) for v in [disk_used, disk_total]):
            used_gb = disk_used / (1024**3)
            total_gb = disk_total / (1024**3)
            self.disk_label.setText(f"{disk:.1f}% ({used_gb:.1f}/{total_gb:.1f} GB)")
        else:
            self.disk_label.setText(f"{disk}%")
        self.disk_bar.setValue(int(disk))
        self.disk_bar.setStyleSheet(self.get_bar_style(disk))
        
    def get_bar_style(self, value):
        if value > 90:
            return "QProgressBar::chunk { background-color: #dc3545; }"
        elif value > 70:
            return "QProgressBar::chunk { background-color: #ffc107; }"
        else:
            return "QProgressBar::chunk { background-color: #28a745; }"