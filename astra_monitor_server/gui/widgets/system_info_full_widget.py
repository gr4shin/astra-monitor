# astra_monitor_server/gui/widgets/system_info_full_widget.py

from PyQt5.QtWidgets import (QWidget, QVBoxLayout, QScrollArea, QGroupBox, QFormLayout, 
                             QLabel, QTableWidget, QHeaderView, QTableWidgetItem)

class SystemInfoFullWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.init_ui()
        
    def init_ui(self):
        layout = QVBoxLayout(self)
        
        # Scroll area для длинной информации
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        
        content_widget = QWidget()
        content_layout = QVBoxLayout(content_widget)
        
        # 1. Информация об ОС
        os_group = QGroupBox("Информация об операционной системе")
        os_layout = QFormLayout(os_group)
        self.os_info_labels = {}
        
        os_fields = [
            ("Дистрибутив", "distro"),
            ("Версия", "version"),
            ("Архитектура", "architecture"),
            ("Ядро", "kernel"),
            ("Время работы", "uptime"),
            ("Дата установки", "install_date")
        ]
        
        for name, key in os_fields:
            label = QLabel("Загрузка...")
            self.os_info_labels[key] = label
            os_layout.addRow(f"{name}:", label)
        
        content_layout.addWidget(os_group)
        
        # 2. Аппаратная информация
        hardware_group = QGroupBox("Аппаратная информация")
        hardware_layout = QFormLayout(hardware_group)
        self.hardware_info_labels = {}
        
        hardware_fields = [
            ("Процессор", "cpu"),
            ("Ядер/потоков", "cpu_cores"),
            ("Частота CPU", "cpu_freq"),
            ("Оперативная память", "ram"),
            ("Видеокарта", "gpu"),
            ("Материнская плата", "motherboard"),
            ("Биос", "bios")
        ]
        
        for name, key in hardware_fields:
            label = QLabel("Загрузка...")
            self.hardware_info_labels[key] = label
            hardware_layout.addRow(f"{name}:", label)
        
        content_layout.addWidget(hardware_group)
        
        # 3. Диски и хранилище
        storage_group = QGroupBox("Диски и хранилище")
        storage_layout = QVBoxLayout(storage_group)
        
        self.storage_table = QTableWidget()
        self.storage_table.setColumnCount(5)
        self.storage_table.setHorizontalHeaderLabels(["Устройство", "Точка монтирования", "Размер", "Использовано", "Тип"])
        self.storage_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.storage_table.setMinimumHeight(120)
        
        storage_layout.addWidget(self.storage_table)
        content_layout.addWidget(storage_group)
        
        # 4. Сетевые интерфейсы
        network_group = QGroupBox("Сетевые интерфейсы")
        network_layout = QVBoxLayout(network_group)
        
        self.network_table = QTableWidget()
        self.network_table.setColumnCount(4)
        self.network_table.setHorizontalHeaderLabels(["Интерфейс", "IP адрес", "MAC адрес", "Статус"])
        self.network_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.network_table.setMinimumHeight(120)
        
        network_layout.addWidget(self.network_table)
        content_layout.addWidget(network_group)
        
        # 5. USB устройства
        usb_group = QGroupBox("USB устройства")
        usb_layout = QVBoxLayout(usb_group)
        
        self.usb_table = QTableWidget()
        self.usb_table.setColumnCount(4)
        self.usb_table.setHorizontalHeaderLabels(["Устройство", "Производитель", "Версия USB", "Статус"])
        self.usb_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.usb_table.setMinimumHeight(120)
        
        usb_layout.addWidget(self.usb_table)
        content_layout.addWidget(usb_group)
        
        # 6. Аудио устройства
        audio_group = QGroupBox("Аудио устройства")
        audio_layout = QVBoxLayout(audio_group)
        
        self.audio_table = QTableWidget()
        self.audio_table.setColumnCount(3)
        self.audio_table.setHorizontalHeaderLabels(["Устройство", "Тип", "Статус"])
        self.audio_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.audio_table.setMinimumHeight(100)
        
        audio_layout.addWidget(self.audio_table)
        content_layout.addWidget(audio_group)
        
        # 7. Камеры
        camera_group = QGroupBox("Видео устройства")
        camera_layout = QVBoxLayout(camera_group)
        
        self.camera_table = QTableWidget()
        self.camera_table.setColumnCount(3)
        self.camera_table.setHorizontalHeaderLabels(["Устройство", "Тип", "Статус"])
        self.camera_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.camera_table.setMinimumHeight(100)
        
        camera_layout.addWidget(self.camera_table)
        content_layout.addWidget(camera_group)
        
        content_layout.addStretch(1)
        
        scroll_area.setWidget(content_widget)
        layout.addWidget(scroll_area)
        
    def update_info(self, data):
        """Обновление информации о системе"""
        # ОС информация
        self.os_info_labels['distro'].setText(data.get('os_distro', 'N/A'))
        self.os_info_labels['version'].setText(data.get('os_version', 'N/A'))
        self.os_info_labels['architecture'].setText(data.get('architecture', 'N/A'))
        self.os_info_labels['kernel'].setText(data.get('kernel', 'N/A'))
        self.os_info_labels['uptime'].setText(data.get('uptime', 'N/A'))
        self.os_info_labels['install_date'].setText(data.get('install_date', 'N/A'))
        
        # Аппаратная информация
        self.hardware_info_labels['cpu'].setText(data.get('cpu_model', 'N/A'))
        self.hardware_info_labels['cpu_cores'].setText(data.get('cpu_cores', 'N/A'))
        self.hardware_info_labels['cpu_freq'].setText(data.get('cpu_freq', 'N/A'))
        self.hardware_info_labels['ram'].setText(data.get('ram_total', 'N/A'))
        self.hardware_info_labels['gpu'].setText(data.get('gpu', 'N/A'))
        self.hardware_info_labels['motherboard'].setText(data.get('motherboard', 'N/A'))
        self.hardware_info_labels['bios'].setText(data.get('bios', 'N/A'))
        
        # Диски
        storage_data = data.get('storage', [])
        self.storage_table.setRowCount(len(storage_data))
        for i, disk in enumerate(storage_data):
            self.storage_table.setItem(i, 0, QTableWidgetItem(disk.get('device', 'N/A')))
            self.storage_table.setItem(i, 1, QTableWidgetItem(disk.get('mountpoint', 'N/A')))
            self.storage_table.setItem(i, 2, QTableWidgetItem(disk.get('size', 'N/A')))
            self.storage_table.setItem(i, 3, QTableWidgetItem(disk.get('used', 'N/A')))
            self.storage_table.setItem(i, 4, QTableWidgetItem(disk.get('fstype', 'N/A')))
        
        # Сеть
        network_data = data.get('network', [])
        self.network_table.setRowCount(len(network_data))
        for i, net in enumerate(network_data):
            self.network_table.setItem(i, 0, QTableWidgetItem(net.get('interface', 'N/A')))
            self.network_table.setItem(i, 1, QTableWidgetItem(net.get('ip', 'N/A')))
            self.network_table.setItem(i, 2, QTableWidgetItem(net.get('mac', 'N/A')))
            self.network_table.setItem(i, 3, QTableWidgetItem(net.get('status', 'N/A')))
        
        # USB устройства
        usb_data = data.get('usb_devices', [])
        self.usb_table.setRowCount(len(usb_data))
        for i, usb in enumerate(usb_data):
            self.usb_table.setItem(i, 0, QTableWidgetItem(usb.get('device', 'N/A')))
            self.usb_table.setItem(i, 1, QTableWidgetItem(usb.get('vendor', 'N/A')))
            self.usb_table.setItem(i, 2, QTableWidgetItem(usb.get('version', 'N/A')))
            self.usb_table.setItem(i, 3, QTableWidgetItem(usb.get('status', 'N/A')))
        
        # Аудио устройства
        audio_data = data.get('audio_devices', [])
        self.audio_table.setRowCount(len(audio_data))
        for i, audio in enumerate(audio_data):
            self.audio_table.setItem(i, 0, QTableWidgetItem(audio.get('device', 'N/A')))
            self.audio_table.setItem(i, 1, QTableWidgetItem(audio.get('type', 'N/A')))
            self.audio_table.setItem(i, 2, QTableWidgetItem(audio.get('status', 'N/A')))
        
        # Камеры
        camera_data = data.get('cameras', [])
        self.camera_table.setRowCount(len(camera_data))
        for i, camera in enumerate(camera_data):
            self.camera_table.setItem(i, 0, QTableWidgetItem(camera.get('device', 'N/A')))
            self.camera_table.setItem(i, 1, QTableWidgetItem(camera.get('type', 'N/A')))
            self.camera_table.setItem(i, 2, QTableWidgetItem(camera.get('status', 'N/A')))