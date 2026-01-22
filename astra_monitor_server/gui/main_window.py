# astra_monitor_server/gui/main_window.py

import json
import os
import sys
import logging
import time
import base64
import asyncio
import hashlib
from threading import Thread, Lock
from collections import defaultdict, deque

from PyQt5.QtWidgets import (QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QTreeWidget,
                             QPushButton, QLabel, QTextEdit, QHeaderView, QMessageBox, QInputDialog, QFileDialog,
                             QTabWidget, QGroupBox, QAbstractItemView, QDialog, QStackedWidget, QStatusBar, QFormLayout, QSpinBox, QDialogButtonBox, QProgressDialog,
                             QListWidget, QListView, QListWidgetItem, QMenu, QSystemTrayIcon, QApplication, QComboBox,
                             QLineEdit, QCheckBox, QSlider)
from PyQt5.QtCore import pyqtSignal, Qt, QSize, QTimer, QVariant
from PyQt5.QtGui import QPixmap, QIcon, QBrush, QColor, QPainter, QLinearGradient, QPen, QFont, QImage
try:
    from PyQt5.QtSvg import QSvgRenderer
except ImportError:
    QSvgRenderer = None
from concurrent.futures import ThreadPoolExecutor

# Импортируем локальные модули
from ..config_loader import APP_CONFIG
from ..server.websocket_server import WebSocketServer
from .client_detail_tab import ClientDetailTab
from .custom_items import SortableTreeWidgetItem
from .icon_utils import load_icon_from_assets
from .widgets.toast import Toast


# --- Custom Log Handler ---
class QtLogHandler(logging.Handler):
    """
    Пользовательский обработчик логов, который отправляет записи в виде
    сигнала PyQt.
    """
    def __init__(self, log_signal):
        super().__init__()
        self.log_signal = log_signal

    def emit(self, record):
        msg = self.format(record)
        self.log_signal.emit(msg)

class ServerSettingsDialog(QDialog):
    """Диалог для настроек сервера."""
    def __init__(self, parent=None, current_interval=10, current_quality=30, current_max_size=100, current_chunk_size=4, current_theme='light', current_grid_card_size=260):
        super().__init__(parent)
        self.setWindowTitle("Настройки сервера")
        layout = QVBoxLayout(self)
        form_layout = QFormLayout()

        # Настройка темы
        self.theme_combo = QComboBox()
        self.theme_combo.addItems(['light', 'midnight', 'sand', 'graphite'])
        if current_theme not in ['light', 'midnight', 'sand', 'graphite']:
            current_theme = 'light'
        self.theme_combo.setCurrentText(current_theme)
        form_layout.addRow("Тема:", self.theme_combo)

        # Настройки сетки (скриншоты)
        self.grid_quality_spinbox = QSpinBox()
        self.grid_quality_spinbox.setRange(1, 100)
        self.grid_quality_spinbox.setValue(current_quality)
        self.grid_quality_spinbox.setSuffix(" %")
        form_layout.addRow("Качество скриншотов сетки:", self.grid_quality_spinbox)

        # Настройки сетки
        self.grid_interval_spinbox = QSpinBox()
        self.grid_interval_spinbox.setRange(1, 120)
        self.grid_interval_spinbox.setValue(current_interval)
        self.grid_interval_spinbox.setSuffix(" сек")
        form_layout.addRow("Интервал обновления сетки:", self.grid_interval_spinbox)

        self.grid_card_size_spinbox = QSpinBox()
        self.grid_card_size_spinbox.setRange(160, 520)
        self.grid_card_size_spinbox.setValue(current_grid_card_size)
        self.grid_card_size_spinbox.setSuffix(" px")
        form_layout.addRow("Размер карточки сетки:", self.grid_card_size_spinbox)

        # Настройки WebSocket
        self.max_size_spinbox = QSpinBox()
        self.max_size_spinbox.setRange(1, 2048)
        self.max_size_spinbox.setValue(current_max_size)
        self.max_size_spinbox.setSuffix(" МБ")
        form_layout.addRow("Макс. размер сообщения WebSocket:", self.max_size_spinbox)

        self.chunk_size_spinbox = QSpinBox()
        self.chunk_size_spinbox.setRange(1, 2048)
        self.chunk_size_spinbox.setValue(current_chunk_size)
        self.chunk_size_spinbox.setSuffix(" МБ")
        form_layout.addRow("Размер чанка для файлов:", self.chunk_size_spinbox)

        layout.addLayout(form_layout)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def get_values(self):
        return {
            'interval': self.grid_interval_spinbox.value(),
            'quality': self.grid_quality_spinbox.value(),
            'max_size': self.max_size_spinbox.value(),
            'chunk_size': self.chunk_size_spinbox.value(),
            'theme': self.theme_combo.currentText(),
            'grid_card_size': self.grid_card_size_spinbox.value()
        }

class ServerGUI(QMainWindow):
    log_signal = pyqtSignal(str)

    def __init__(self):
        super().__init__()        
        self.client_tabs = {}  # Для хранения вкладок клиентов
        self.tree_items = {}   # Кэш для быстрого доступа к элементам дерева по client_id
        self.grid_items = {}   # Кэш для быстрого доступа к элементам сетки по client_id
        self.download_contexts = {} # Для скачивания файлов по частям
        self.pending_downloads = {} # Для предварительно согласованных скачиваний
        self.client_meta = {}
        self._log_lines = []
        self.metrics_history = defaultdict(lambda: {
            "cpu": deque(maxlen=120),
            "mem": deque(maxlen=120),
            "disk": deque(maxlen=120),
        })
        self.scheduled_tasks = []
        self._toasts = []
        self.file_processing_executor = ThreadPoolExecutor(max_workers=os.cpu_count() or 2)
        self.load_settings()
        self.apply_theme()

        self.ws_server = WebSocketServer(
            host=APP_CONFIG['SERVER_HOST'],
            port=APP_CONFIG['SERVER_PORT'],
            max_size=self.websocket_max_size_mb * 1024 * 1024
        )

        self.init_ui()
        self.setup_logging()
        self.setup_tray_icon()

        self.placeholder_icon = self._build_placeholder_icon(self.clients_grid.iconSize())

        self._setup_message_handlers()
        self.setup_websocket_server()
        
    def apply_theme(self):
        """Применяет выбранную тему к приложению."""
        app = QApplication.instance()
        themes = {
            "light": """
                QWidget {
                    background-color: #f4f6fb;
                    color: #1f2937;
                    border: none;
                    font-family: "Segoe UI", "Ubuntu", "Helvetica Neue", sans-serif;
                    font-size: 12px;
                }
                QLabel {
                    background: transparent;
                }
                QCheckBox, QRadioButton {
                    background: transparent;
                }
                QGroupBox {
                    background-color: #ffffff;
                    border: 1px solid #e5e7eb;
                    border-radius: 10px;
                    margin-top: 10px;
                    padding: 8px;
                }
                QGroupBox::title {
                    subcontrol-origin: margin;
                    left: 12px;
                    padding: 0 6px;
                    color: #111827;
                    font-weight: 600;
                }
                QHeaderView::section {
                    background-color: #f9fafb;
                    color: #374151;
                    padding: 6px;
                    border: 1px solid #e5e7eb;
                    font-weight: 600;
                }
                QTabWidget::pane {
                    border: 1px solid #e5e7eb;
                    border-radius: 10px;
                    background: #ffffff;
                }
                QTabBar::tab {
                    background: #eef2ff;
                    color: #374151;
                    border: 1px solid #e5e7eb;
                    border-bottom: none;
                    padding: 8px 12px;
                    border-top-left-radius: 10px;
                    border-top-right-radius: 10px;
                    margin-right: 4px;
                }
                QTabBar::tab:selected {
                    background: #ffffff;
                    color: #111827;
                }
                QTabBar::close-button {
                    image: url(__CLOSE_ICON__);
                    subcontrol-position: right;
                    margin: 8px;
                    width: 12px;
                    height: 12px;
                }
                QTabBar::close-button:hover {
                    background: #e2e8f0;
                    border-radius: 6px;
                }
                QTreeWidget, QListWidget, QTreeView, QTableWidget {
                    background-color: #ffffff;
                    color: #111827;
                    border: 1px solid #e5e7eb;
                    border-radius: 10px;
                }
                #clientsGrid::item {
                    border: 1px solid #e5e7eb;
                    border-radius: 12px;
                    padding: 6px;
                    margin: 4px;
                    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                        stop:0 #ffffff, stop:1 #f8fafc);
                    color: #1f2937;
                    font-size: 11px;
                }
                #clientsGrid::item:selected {
                    border: 1px solid #2563eb;
                    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                        stop:0 #eff6ff, stop:1 #e0f2fe);
                    color: #1f2937;
                }
                QPushButton {
                    background-color: #ffffff;
                    color: #1f2937;
                    border: 1px solid #e5e7eb;
                    padding: 6px 12px;
                    border-radius: 8px;
                    qproperty-iconSize: 18px 18px;
                }
                QPushButton:hover {
                    background-color: #f1f5f9;
                }
                QPushButton:pressed {
                    background-color: #e2e8f0;
                }
                QPushButton:checked {
                    border: 1px solid #2563eb;
                    background-color: #eff6ff;
                }
                QLineEdit, QTextEdit, QSpinBox, QComboBox {
                    background-color: #ffffff;
                    color: #111827;
                    border: 1px solid #e5e7eb;
                    border-radius: 6px;
                    padding: 4px 6px;
                }
                QComboBox::drop-down {
                    border-left: 1px solid #e5e7eb;
                    width: 20px;
                }
                QSpinBox::up-button, QSpinBox::down-button {
                    width: 18px;
                    border-left: 1px solid #e5e7eb;
                    background: #f8fafc;
                }
                QSpinBox::up-button:hover, QSpinBox::down-button:hover {
                    background: #e2e8f0;
                }
                QSpinBox::up-arrow, QSpinBox::down-arrow,
                QComboBox::down-arrow {
                    width: 8px;
                    height: 8px;
                }
                QSpinBox::up-arrow {
                    image: url(__ARROW_UP__);
                }
                QSpinBox::down-arrow, QComboBox::down-arrow {
                    image: url(__ARROW_DOWN__);
                }
                QCheckBox::indicator {
                    width: 14px;
                    height: 14px;
                    border-radius: 4px;
                    border: 1px solid #cbd5f5;
                    background-color: #ffffff;
                }
                QCheckBox::indicator:checked {
                    background-color: #2563eb;
                }
                QRadioButton::indicator {
                    width: 14px;
                    height: 14px;
                    border-radius: 7px;
                    border: 1px solid #cbd5f5;
                    background-color: #ffffff;
                }
                QRadioButton::indicator:checked {
                    background-color: #2563eb;
                }
                QScrollBar:vertical {
                    background: #eef2ff;
                    width: 10px;
                    margin: 2px;
                    border-radius: 5px;
                }
                QScrollBar::handle:vertical {
                    background: #94a3b8;
                    min-height: 20px;
                    border-radius: 5px;
                }
                QScrollBar::handle:vertical:hover {
                    background: #64748b;
                }
                QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
                    height: 0px;
                }
                QScrollBar:horizontal {
                    background: #eef2ff;
                    height: 10px;
                    margin: 2px;
                    border-radius: 5px;
                }
                QScrollBar::handle:horizontal {
                    background: #94a3b8;
                    min-width: 20px;
                    border-radius: 5px;
                }
                QScrollBar::handle:horizontal:hover {
                    background: #64748b;
                }
                QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {
                    width: 0px;
                }
                QSplitter::handle {
                    background: #e5e7eb;
                }
                QMenuBar {
                    background-color: #ffffff;
                    color: #111827;
                }
                QMenuBar::item:selected {
                    background: #e5e7eb;
                }
            QMenu {
                background-color: #ffffff;
                color: #111827;
                border: 1px solid #e5e7eb;
                padding: 6px;
            }
            QMenu::item:selected {
                background-color: #e5e7eb;
            }
            QMenu::item {
                padding: 8px 16px 8px 16px;
                border-radius: 6px;
                background: transparent;
            }
            QMenu::icon {
                left: 6px;
                width: 12px;
                height: 12px;
            }
            QMenu::item:disabled {
                color: #9ca3af;
            }
            QMenu::separator {
                height: 1px;
                background: #e5e7eb;
                margin: 6px 10px;
            }
                QStatusBar {
                    background-color: #ffffff;
                    color: #374151;
                }
                QMessageBox, QDialog {
                    background-color: #ffffff;
                    color: #111827;
                }
                QMessageBox QLabel#qt_msgboxex_icon {
                    width: 0px;
                    height: 0px;
                }
            """,
            "midnight": """
                QWidget {
                    background-color: #0f172a;
                    color: #e2e8f0;
                    border: none;
                    font-family: "Segoe UI", "Ubuntu", "Helvetica Neue", sans-serif;
                    font-size: 12px;
                }
                QLabel {
                    background: transparent;
                }
                QCheckBox, QRadioButton {
                    background: transparent;
                }
                QGroupBox {
                    background-color: #111827;
                    border: 1px solid #1f2937;
                    border-radius: 10px;
                    margin-top: 10px;
                    padding: 8px;
                }
                QGroupBox::title {
                    subcontrol-origin: margin;
                    left: 12px;
                    padding: 0 6px;
                    color: #e2e8f0;
                    font-weight: 600;
                }
                QHeaderView::section {
                    background-color: #111827;
                    color: #cbd5f5;
                    padding: 6px;
                    border: 1px solid #1f2937;
                    font-weight: 600;
                }
                QTabWidget::pane {
                    border: 1px solid #1f2937;
                    border-radius: 10px;
                    background: #0f172a;
                }
                QTabBar::tab {
                    background: #111827;
                    color: #94a3b8;
                    border: 1px solid #1f2937;
                    border-bottom: none;
                    padding: 8px 12px;
                    border-top-left-radius: 10px;
                    border-top-right-radius: 10px;
                    margin-right: 4px;
                }
                QTabBar::tab:selected {
                    background: #0f172a;
                    color: #e2e8f0;
                }
                QTabBar::close-button {
                    image: url(__CLOSE_ICON__);
                    subcontrol-position: right;
                    margin: 8px;
                    width: 12px;
                    height: 12px;
                }
                QTabBar::close-button:hover {
                    background: #1e293b;
                    border-radius: 6px;
                }
                QTreeWidget, QListWidget, QTreeView, QTableWidget {
                    background-color: #0b1220;
                    color: #e2e8f0;
                    border: 1px solid #1f2937;
                    border-radius: 10px;
                }
                #clientsGrid::item {
                    border: 1px solid #1f2937;
                    border-radius: 12px;
                    padding: 6px;
                    margin: 4px;
                    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                        stop:0 #111827, stop:1 #0b1220);
                    color: #e2e8f0;
                    font-size: 11px;
                }
                #clientsGrid::item:selected {
                    border: 1px solid #38bdf8;
                    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                        stop:0 #1e293b, stop:1 #0f172a);
                    color: #e2e8f0;
                }
                QPushButton {
                    background-color: #111827;
                    color: #e2e8f0;
                    border: 1px solid #1f2937;
                    padding: 6px 12px;
                    border-radius: 8px;
                    qproperty-iconSize: 18px 18px;
                }
                QPushButton:hover {
                    background-color: #1e293b;
                }
                QPushButton:pressed {
                    background-color: #0f172a;
                }
                QPushButton:checked {
                    border: 1px solid #38bdf8;
                    background-color: #1e293b;
                }
                QLineEdit, QTextEdit, QSpinBox, QComboBox {
                    background-color: #0f172a;
                    color: #e2e8f0;
                    border: 1px solid #1f2937;
                    border-radius: 6px;
                    padding: 4px 6px;
                }
                QComboBox::drop-down {
                    border-left: 1px solid #1f2937;
                    width: 20px;
                }
                QSpinBox::up-button, QSpinBox::down-button {
                    width: 18px;
                    border-left: 1px solid #1f2937;
                    background: #0b1220;
                }
                QSpinBox::up-button:hover, QSpinBox::down-button:hover {
                    background: #1e293b;
                }
                QSpinBox::up-arrow, QSpinBox::down-arrow,
                QComboBox::down-arrow {
                    width: 8px;
                    height: 8px;
                }
                QSpinBox::up-arrow {
                    image: url(__ARROW_UP__);
                }
                QSpinBox::down-arrow, QComboBox::down-arrow {
                    image: url(__ARROW_DOWN__);
                }
                QCheckBox::indicator {
                    width: 14px;
                    height: 14px;
                    border-radius: 4px;
                    border: 1px solid #1f2937;
                    background-color: #0f172a;
                }
                QCheckBox::indicator:checked {
                    background-color: #0ea5e9;
                }
                QRadioButton::indicator {
                    width: 14px;
                    height: 14px;
                    border-radius: 7px;
                    border: 1px solid #1f2937;
                    background-color: #0f172a;
                }
                QRadioButton::indicator:checked {
                    background-color: #38bdf8;
                }
                QScrollBar:vertical {
                    background: #0b1220;
                    width: 10px;
                    margin: 2px;
                    border-radius: 5px;
                }
                QScrollBar::handle:vertical {
                    background: #334155;
                    min-height: 20px;
                    border-radius: 5px;
                }
                QScrollBar::handle:vertical:hover {
                    background: #475569;
                }
                QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
                    height: 0px;
                }
                QScrollBar:horizontal {
                    background: #0b1220;
                    height: 10px;
                    margin: 2px;
                    border-radius: 5px;
                }
                QScrollBar::handle:horizontal {
                    background: #334155;
                    min-width: 20px;
                    border-radius: 5px;
                }
                QScrollBar::handle:horizontal:hover {
                    background: #475569;
                }
                QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {
                    width: 0px;
                }
                QSplitter::handle {
                    background: #1f2937;
                }
                QMenuBar {
                    background-color: #0f172a;
                    color: #e2e8f0;
                }
                QMenuBar::item:selected {
                    background: #1f2937;
                }
            QMenu {
                background-color: #111827;
                color: #e2e8f0;
                border: 1px solid #1f2937;
                padding: 6px;
            }
            QMenu::item:selected {
                background-color: #1f2937;
            }
            QMenu::item {
                padding: 8px 16px 8px 16px;
                border-radius: 6px;
                background: transparent;
            }
            QMenu::icon {
                left: 6px;
                width: 12px;
                height: 12px;
            }
            QMenu::item:disabled {
                color: #64748b;
            }
            QMenu::separator {
                height: 1px;
                background: #1f2937;
                margin: 6px 10px;
            }
                QStatusBar {
                    background-color: #0f172a;
                    color: #cbd5f5;
                }
                QMessageBox, QDialog {
                    background-color: #111827;
                    color: #e2e8f0;
                }
                QMessageBox QLabel#qt_msgboxex_icon {
                    width: 0px;
                    height: 0px;
                }
            """,
            "sand": """
                QWidget {
                    background-color: #f8f4ef;
                    color: #3f3a2f;
                    border: none;
                    font-family: "Segoe UI", "Ubuntu", "Helvetica Neue", sans-serif;
                    font-size: 12px;
                }
                QLabel {
                    background: transparent;
                }
                QCheckBox, QRadioButton {
                    background: transparent;
                }
                QGroupBox {
                    background-color: #fffaf2;
                    border: 1px solid #eadfce;
                    border-radius: 10px;
                    margin-top: 10px;
                    padding: 8px;
                }
                QGroupBox::title {
                    subcontrol-origin: margin;
                    left: 12px;
                    padding: 0 6px;
                    color: #4b4031;
                    font-weight: 600;
                }
                QHeaderView::section {
                    background-color: #f6efe6;
                    color: #4b4031;
                    padding: 6px;
                    border: 1px solid #eadfce;
                    font-weight: 600;
                }
                QTabWidget::pane {
                    border: 1px solid #eadfce;
                    border-radius: 10px;
                    background: #fffaf2;
                }
                QTabBar::tab {
                    background: #f3e9dc;
                    color: #6b5a44;
                    border: 1px solid #eadfce;
                    border-bottom: none;
                    padding: 8px 12px;
                    border-top-left-radius: 10px;
                    border-top-right-radius: 10px;
                    margin-right: 4px;
                }
                QTabBar::tab:selected {
                    background: #fffaf2;
                    color: #3f3a2f;
                }
                QTabBar::close-button {
                    image: url(__CLOSE_ICON__);
                    subcontrol-position: right;
                    margin: 8px;
                    width: 12px;
                    height: 12px;
                }
                QTabBar::close-button:hover {
                    background: #eadfce;
                    border-radius: 6px;
                }
                QTreeWidget, QListWidget, QTreeView, QTableWidget {
                    background-color: #fffaf2;
                    color: #3f3a2f;
                    border: 1px solid #eadfce;
                    border-radius: 10px;
                }
                #clientsGrid::item {
                    border: 1px solid #eadfce;
                    border-radius: 12px;
                    padding: 6px;
                    margin: 4px;
                    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                        stop:0 #fffaf2, stop:1 #f4eadb);
                    color: #3f3a2f;
                    font-size: 11px;
                }
                #clientsGrid::item:selected {
                    border: 1px solid #d97706;
                    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                        stop:0 #fff1d6, stop:1 #f7e1b5);
                    color: #3f3a2f;
                }
                QPushButton {
                    background-color: #fffaf2;
                    color: #3f3a2f;
                    border: 1px solid #eadfce;
                    padding: 6px 12px;
                    border-radius: 8px;
                    qproperty-iconSize: 18px 18px;
                }
                QPushButton:hover {
                    background-color: #f6efe6;
                }
                QPushButton:pressed {
                    background-color: #eadfce;
                }
                QPushButton:checked {
                    border: 1px solid #d97706;
                    background-color: #fff1d6;
                }
                QLineEdit, QTextEdit, QSpinBox, QComboBox {
                    background-color: #fffaf2;
                    color: #3f3a2f;
                    border: 1px solid #eadfce;
                    border-radius: 6px;
                    padding: 4px 6px;
                }
                QComboBox::drop-down {
                    border-left: 1px solid #eadfce;
                    width: 20px;
                }
                QSpinBox::up-button, QSpinBox::down-button {
                    width: 18px;
                    border-left: 1px solid #eadfce;
                    background: #f6efe6;
                }
                QSpinBox::up-button:hover, QSpinBox::down-button:hover {
                    background: #eadfce;
                }
                QSpinBox::up-arrow, QSpinBox::down-arrow,
                QComboBox::down-arrow {
                    width: 8px;
                    height: 8px;
                }
                QSpinBox::up-arrow {
                    image: url(__ARROW_UP__);
                }
                QSpinBox::down-arrow, QComboBox::down-arrow {
                    image: url(__ARROW_DOWN__);
                }
                QCheckBox::indicator {
                    width: 14px;
                    height: 14px;
                    border-radius: 4px;
                    border: 1px solid #eadfce;
                    background-color: #fffaf2;
                }
                QCheckBox::indicator:checked {
                    background-color: #d97706;
                }
                QRadioButton::indicator {
                    width: 14px;
                    height: 14px;
                    border-radius: 7px;
                    border: 1px solid #eadfce;
                    background-color: #fffaf2;
                }
                QRadioButton::indicator:checked {
                    background-color: #d97706;
                }
                QScrollBar:vertical {
                    background: #f3e9dc;
                    width: 10px;
                    margin: 2px;
                    border-radius: 5px;
                }
                QScrollBar::handle:vertical {
                    background: #c7b299;
                    min-height: 20px;
                    border-radius: 5px;
                }
                QScrollBar::handle:vertical:hover {
                    background: #a98d6c;
                }
                QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
                    height: 0px;
                }
                QScrollBar:horizontal {
                    background: #f3e9dc;
                    height: 10px;
                    margin: 2px;
                    border-radius: 5px;
                }
                QScrollBar::handle:horizontal {
                    background: #c7b299;
                    min-width: 20px;
                    border-radius: 5px;
                }
                QScrollBar::handle:horizontal:hover {
                    background: #a98d6c;
                }
                QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {
                    width: 0px;
                }
                QSplitter::handle {
                    background: #eadfce;
                }
                QMenuBar {
                    background-color: #fffaf2;
                    color: #3f3a2f;
                }
                QMenuBar::item:selected {
                    background: #eadfce;
                }
            QMenu {
                background-color: #fffaf2;
                color: #3f3a2f;
                border: 1px solid #eadfce;
                padding: 6px;
            }
            QMenu::item:selected {
                background-color: #eadfce;
            }
            QMenu::item {
                padding: 8px 16px 8px 16px;
                border-radius: 6px;
                background: transparent;
            }
            QMenu::icon {
                left: 6px;
                width: 12px;
                height: 12px;
            }
            QMenu::item:disabled {
                color: #a89986;
            }
            QMenu::separator {
                height: 1px;
                background: #eadfce;
                margin: 6px 10px;
            }
                QStatusBar {
                    background-color: #fffaf2;
                    color: #6b5a44;
                }
                QMessageBox, QDialog {
                    background-color: #fffaf2;
                    color: #3f3a2f;
                }
                QMessageBox QLabel#qt_msgboxex_icon {
                    width: 0px;
                    height: 0px;
                }
            """,
            "graphite": """
                QWidget {
                    background-color: #111111;
                    color: #e5e5e5;
                    border: none;
                    font-family: "Segoe UI", "Ubuntu", "Helvetica Neue", sans-serif;
                    font-size: 12px;
                }
                QLabel {
                    background: transparent;
                }
                QCheckBox, QRadioButton {
                    background: transparent;
                }
                QGroupBox {
                    background-color: #1a1a1a;
                    border: 1px solid #2a2a2a;
                    border-radius: 10px;
                    margin-top: 10px;
                    padding: 8px;
                }
                QGroupBox::title {
                    subcontrol-origin: margin;
                    left: 12px;
                    padding: 0 6px;
                    color: #f5f5f5;
                    font-weight: 600;
                }
                QHeaderView::section {
                    background-color: #1a1a1a;
                    color: #cfcfcf;
                    padding: 6px;
                    border: 1px solid #2a2a2a;
                    font-weight: 600;
                }
                QTabWidget::pane {
                    border: 1px solid #2a2a2a;
                    border-radius: 10px;
                    background: #111111;
                }
                QTabBar::tab {
                    background: #1f1f1f;
                    color: #9ca3af;
                    border: 1px solid #2a2a2a;
                    border-bottom: none;
                    padding: 8px 12px;
                    border-top-left-radius: 10px;
                    border-top-right-radius: 10px;
                    margin-right: 4px;
                }
                QTabBar::tab:selected {
                    background: #111111;
                    color: #f3f4f6;
                }
                QTabBar::close-button {
                    image: url(__CLOSE_ICON__);
                    subcontrol-position: right;
                    margin: 8px;
                    width: 12px;
                    height: 12px;
                }
                QTabBar::close-button:hover {
                    background: #2a2a2a;
                    border-radius: 6px;
                }
                QTreeWidget, QListWidget, QTreeView, QTableWidget {
                    background-color: #111111;
                    color: #e5e5e5;
                    border: 1px solid #2a2a2a;
                    border-radius: 10px;
                }
                #clientsGrid::item {
                    border: 1px solid #2a2a2a;
                    border-radius: 12px;
                    padding: 6px;
                    margin: 4px;
                    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                        stop:0 #1a1a1a, stop:1 #111111);
                    color: #e5e5e5;
                    font-size: 11px;
                }
                #clientsGrid::item:selected {
                    border: 1px solid #22c55e;
                    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                        stop:0 #0f172a, stop:1 #111111);
                    color: #e5e5e5;
                }
                QPushButton {
                    background-color: #1a1a1a;
                    color: #e5e5e5;
                    border: 1px solid #2a2a2a;
                    padding: 6px 12px;
                    border-radius: 8px;
                    qproperty-iconSize: 18px 18px;
                }
                QPushButton:hover {
                    background-color: #262626;
                }
                QPushButton:pressed {
                    background-color: #0f0f0f;
                }
                QPushButton:checked {
                    border: 1px solid #22c55e;
                    background-color: #1f2937;
                }
                QLineEdit, QTextEdit, QSpinBox, QComboBox {
                    background-color: #111111;
                    color: #e5e5e5;
                    border: 1px solid #2a2a2a;
                    border-radius: 6px;
                    padding: 4px 6px;
                }
                QComboBox::drop-down {
                    border-left: 1px solid #2a2a2a;
                    width: 20px;
                }
                QSpinBox::up-button, QSpinBox::down-button {
                    width: 18px;
                    border-left: 1px solid #2a2a2a;
                    background: #1a1a1a;
                }
                QSpinBox::up-button:hover, QSpinBox::down-button:hover {
                    background: #262626;
                }
                QSpinBox::up-arrow, QSpinBox::down-arrow,
                QComboBox::down-arrow {
                    width: 8px;
                    height: 8px;
                }
                QSpinBox::up-arrow {
                    image: url(__ARROW_UP__);
                }
                QSpinBox::down-arrow, QComboBox::down-arrow {
                    image: url(__ARROW_DOWN__);
                }
                QCheckBox::indicator {
                    width: 14px;
                    height: 14px;
                    border-radius: 4px;
                    border: 1px solid #2a2a2a;
                    background-color: #111111;
                }
                QCheckBox::indicator:checked {
                    background-color: #22c55e;
                }
                QRadioButton::indicator {
                    width: 14px;
                    height: 14px;
                    border-radius: 7px;
                    border: 1px solid #2a2a2a;
                    background-color: #111111;
                }
                QRadioButton::indicator:checked {
                    background-color: #22c55e;
                }
                QScrollBar:vertical {
                    background: #1f1f1f;
                    width: 10px;
                    margin: 2px;
                    border-radius: 5px;
                }
                QScrollBar::handle:vertical {
                    background: #3f3f46;
                    min-height: 20px;
                    border-radius: 5px;
                }
                QScrollBar::handle:vertical:hover {
                    background: #52525b;
                }
                QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
                    height: 0px;
                }
                QScrollBar:horizontal {
                    background: #1f1f1f;
                    height: 10px;
                    margin: 2px;
                    border-radius: 5px;
                }
                QScrollBar::handle:horizontal {
                    background: #3f3f46;
                    min-width: 20px;
                    border-radius: 5px;
                }
                QScrollBar::handle:horizontal:hover {
                    background: #52525b;
                }
                QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {
                    width: 0px;
                }
                QSplitter::handle {
                    background: #2a2a2a;
                }
                QMenuBar {
                    background-color: #111111;
                    color: #e5e5e5;
                }
                QMenuBar::item:selected {
                    background: #2a2a2a;
                }
            QMenu {
                background-color: #111111;
                color: #e5e5e5;
                border: 1px solid #2a2a2a;
                padding: 6px;
            }
            QMenu::item:selected {
                background-color: #2a2a2a;
            }
            QMenu::item {
                padding: 8px 16px 8px 16px;
                border-radius: 6px;
                background: transparent;
            }
            QMenu::icon {
                left: 6px;
                width: 12px;
                height: 12px;
            }
            QMenu::item:disabled {
                color: #71717a;
            }
            QMenu::separator {
                height: 1px;
                background: #2a2a2a;
                margin: 6px 10px;
            }
                QStatusBar {
                    background-color: #111111;
                    color: #9ca3af;
                }
                QMessageBox, QDialog {
                    background-color: #111111;
                    color: #e5e5e5;
                }
                QMessageBox QLabel#qt_msgboxex_icon {
                    width: 0px;
                    height: 0px;
                }
            """
        }
        theme_key = self.theme
        if theme_key == "dark":
            theme_key = "midnight"
        close_icon_path = self._asset_path("assets", "icons", "close.svg").replace("\\", "/")
        arrow_up_path = self._asset_path("assets", "icons", "arrow_up.svg").replace("\\", "/")
        arrow_down_path = self._asset_path("assets", "icons", "arrow_down.svg").replace("\\", "/")
        theme_css = themes.get(theme_key, themes["light"])
        theme_css = theme_css.replace("__CLOSE_ICON__", close_icon_path)
        theme_css = theme_css.replace("__ARROW_UP__", arrow_up_path)
        theme_css = theme_css.replace("__ARROW_DOWN__", arrow_down_path)
        app.setStyleSheet(theme_css)
        if hasattr(self, "refresh_btn"):
            self._apply_action_icons()
            self._apply_view_icons()
            self._apply_tab_icons()

    def setup_logging(self):
        """Настраивает перехват логов для отображения в GUI."""
        self.log_signal.connect(self._append_log_line)
        self.log_signal.connect(self.statusBar().showMessage)
        handler = QtLogHandler(self.log_signal)
        
        # Устанавливаем формат для логов в GUI
        formatter = logging.Formatter('%(asctime)s [%(levelname)s] %(message)s')
        handler.setFormatter(formatter)
        
        # Добавляем обработчик к корневому логгеру
        # Он будет получать все сообщения уровня INFO и выше
        logging.getLogger().addHandler(handler)
        handler.setLevel(logging.INFO)

    def find_client_id_by_ip(self, ip_address):
        for client_id, data in self.client_data.items():
            # Статус 'Connected' и активное соединение в WebSocket сервере
            if data.get('ip') == ip_address and data.get('status') == 'Connected' and client_id in self.ws_server.clients:
                return client_id
        return None

    def _setup_message_handlers(self):
        """Инициализация диспетчера обработчиков сообщений от клиента."""
        self.message_handlers = {
            'files_list': self._handle_files_list,
            'full_system_info': self._handle_full_system_info,
            'file_upload_result': self._handle_file_upload_result,
            'screenshot': self._handle_screenshot_update,
            'file_delete_result': self._handle_file_delete_result,
            'command_result': self._handle_command_result,
            'command_error': self._handle_command_error,
            'prompt_update': self._handle_prompt_update,
            'client_settings': self._handle_client_settings,
            'download_file_start': self._handle_download_start,
            'download_file_chunk': self._handle_download_chunk,
            'download_file_end': self._handle_download_end,
            'rename_result': self._handle_rename_result,
            'apt_repo_data': self._handle_apt_repo_data,
            'apt_upgradable_list': self._handle_apt_upgradable_list,
            'apt_command_output': self._handle_apt_command_output,
            'apt_command_result': self._handle_apt_command_result,
            'install_output': self._handle_install_output,
            'install_result': self._handle_install_result,
            'message_result': self._handle_message_result,
            'interactive_started': self._handle_interactive_started,
            'interactive_output': self._handle_interactive_output,
            'interactive_stopped': self._handle_interactive_stopped,
        }

    def load_settings(self):
        """Загрузка настроек сервера из файла."""
        try:
            with open(APP_CONFIG['SETTINGS_FILE'], 'r', encoding='utf-8') as f:
                settings = json.load(f)
            self.custom_commands = settings.get('custom_commands', self.get_default_custom_commands())
            self.client_meta = settings.get('clients_meta', {})
            server_settings = settings.get('server_settings', {})
            self.grid_refresh_interval = server_settings.get('grid_refresh_interval', 10)
            self.quality_grid = server_settings.get('quality_grid', 30)
            self.grid_card_size = server_settings.get('grid_card_size', 260)
            self.websocket_max_size_mb = server_settings.get('websocket_max_size_mb', 100)
            self.websocket_chunk_size_mb = server_settings.get('websocket_chunk_size_mb', 4)
            self.theme = server_settings.get('theme', 'light')
        except (FileNotFoundError, json.JSONDecodeError):
            self.custom_commands = self.get_default_custom_commands()
            self.client_meta = {}
            self.grid_refresh_interval = 10
            self.quality_grid = 30
            self.grid_card_size = 260
            self.websocket_max_size_mb = 100
            self.websocket_chunk_size_mb = 4
            self.theme = 'light'
            self.save_settings()

    def save_settings(self):
        """Сохранение всех настроек сервера в файл."""
        all_settings = {
            'custom_commands': self.custom_commands,
            'clients_meta': self.client_meta,
            'server_settings': {
                'grid_refresh_interval': self.grid_refresh_interval,
                'quality_grid': self.quality_grid,
                'grid_card_size': self.grid_card_size,
                'websocket_max_size_mb': self.websocket_max_size_mb,
                'websocket_chunk_size_mb': self.websocket_chunk_size_mb,
                'theme': self.theme
            }
        }
        with open(APP_CONFIG['SETTINGS_FILE'], 'w', encoding='utf-8') as f:
            json.dump(all_settings, f, indent=4, ensure_ascii=False)

    def get_default_custom_commands(self):
        return {
            "Сетевые интерфейсы": "ip addr show",
            "Активные соединения": "ss -tuln",
            "Журнал системы": "sudo journalctl -n 20",
            "Службы системы": "systemctl list-units --type=service --state=running",
            "Дисковое пространство": "df -h",
            "Процессы (top)": "top -bn1 | head -20",
            "Информация о ОС": "cat /etc/os-release",
            "Активные пользователи": "who",
            "Uptime системы": "uptime"
        }
        
    def init_ui(self):
        self._set_app_icon()
        self.setWindowTitle('Astra Linux Monitoring Server')
        self.setGeometry(100, 100, 1200, 800)
        self.setWindowIcon(self.app_icon)
        self.setStatusBar(QStatusBar(self))
        
        # --- Menu Bar ---
        menu_bar = self.menuBar()
        view_menu = menu_bar.addMenu("Вид")
        
        self.show_clients_action = view_menu.addAction("Показать 'Клиенты'")
        self.show_clients_action.triggered.connect(self.show_clients_tab)
        
        self.show_log_action = view_menu.addAction("Показать 'Системный лог'")
        self.show_log_action.triggered.connect(self.show_log_tab)
        
        self.show_tasks_action = view_menu.addAction("Показать 'Задачи'")
        self.show_tasks_action.triggered.connect(self.show_tasks_tab)

        settings_menu = menu_bar.addMenu("Настройки")
        server_settings_action = settings_menu.addAction("Настройки сервера")
        server_settings_action.triggered.connect(self.open_server_settings)

        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        
        main_layout = QVBoxLayout(central_widget)
        
        # Status bar widgets
        self.status_label = QLabel(f"Сервер запущен на ws://{APP_CONFIG['SERVER_HOST']}:{APP_CONFIG['SERVER_PORT']}")
        self.clients_count_label = QLabel("Клиентов: 0")
        self.statusBar().addPermanentWidget(self.status_label)
        self.statusBar().addPermanentWidget(self.clients_count_label)
        
        # Main tabs
        self.tabs = QTabWidget()
        self.tabs.setTabsClosable(True)
        self.tabs.tabBar().setMovable(True)
        self.tabs.tabCloseRequested.connect(self.close_tab)
        
        # 1. Вкладка со списком клиентов
        self.clients_list_tab = QWidget()
        clients_layout = QVBoxLayout(self.clients_list_tab)

        # --- Панель действий ---
        actions_layout = QHBoxLayout()
        self.refresh_btn = QPushButton("Обновить")
        self.refresh_btn.clicked.connect(self.refresh_client_data)
        self.message_btn = QPushButton("Сообщение")
        self.message_btn.clicked.connect(self.send_message_to_clients)
        self.reboot_btn = QPushButton("Перезагрузить")
        self.reboot_btn.clicked.connect(self.reboot_client)
        self.shutdown_btn = QPushButton("Выключить")
        self.shutdown_btn.clicked.connect(self.shutdown_client)
        self.update_btn = QPushButton("Обновить клиент")
        self.update_btn.clicked.connect(self.update_selected_clients)
        self.disconnect_btn = QPushButton("Отключить")
        self.disconnect_btn.clicked.connect(self.disconnect_client)

        actions_layout.addWidget(self.refresh_btn)
        actions_layout.addWidget(self.message_btn)
        actions_layout.addWidget(self.reboot_btn)
        actions_layout.addWidget(self.shutdown_btn)
        actions_layout.addWidget(self.update_btn)
        actions_layout.addWidget(self.disconnect_btn)
        actions_layout.addStretch()

        search_icon = load_icon_from_assets("search.svg", QColor("#64748b"), size=16)
        if not search_icon.isNull():
            search_label = QLabel()
            search_label.setPixmap(search_icon.pixmap(16, 16))
            actions_layout.addWidget(search_label)
        else:
            actions_layout.addWidget(QLabel("Поиск:"))
        self.client_filter_input = QLineEdit()
        self.client_filter_input.setPlaceholderText("IP, hostname, теги...")
        self.client_filter_input.textChanged.connect(self.filter_clients)
        actions_layout.addWidget(self.client_filter_input)
        clients_layout.addLayout(actions_layout)

        # Дерево клиентов
        clients_group = QGroupBox("Подключенные клиенты")
        clients_group_layout = QVBoxLayout(clients_group)
        
        # --- Переключатель вида ---
        view_switcher_layout = QHBoxLayout()
        self.list_view_btn = QPushButton("Список")
        self.list_view_btn.setCheckable(True)
        self.list_view_btn.setChecked(True)
        self.grid_view_btn = QPushButton("Сетка")
        self.grid_view_btn.setCheckable(True)
        self.list_view_btn.clicked.connect(lambda: self.switch_view(0))
        self.grid_view_btn.clicked.connect(lambda: self.switch_view(1))
        view_switcher_layout.addWidget(self.list_view_btn)
        view_switcher_layout.addWidget(self.grid_view_btn)
        self.grid_scale_label = QLabel("Масштаб:")
        view_switcher_layout.addWidget(self.grid_scale_label)
        self.grid_size_slider = QSlider(Qt.Horizontal)
        self.grid_size_slider.setRange(160, 520)
        self.grid_size_slider.setValue(self.grid_card_size)
        self.grid_size_slider.setFixedWidth(160)
        self.grid_size_slider.valueChanged.connect(self.on_grid_size_changed)
        self.grid_size_slider.sliderReleased.connect(self._save_grid_size_from_slider)
        self.grid_size_label = QLabel(f"{self.grid_card_size}px")
        view_switcher_layout.addWidget(self.grid_size_slider)
        view_switcher_layout.addWidget(self.grid_size_label)
        view_switcher_layout.addStretch()
        clients_group_layout.addLayout(view_switcher_layout)

        # --- Стек для видов ---
        self.view_stack = QStackedWidget()

        # --- Вид "Список" (дерево) ---
        self.clients_tree = QTreeWidget()
        self.clients_tree.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.clients_tree.setSortingEnabled(True)
        self.clients_tree.setHeaderLabels(['IP адрес', 'Hostname', 'Примечание','Версия', 'CPU', 'RAM', 'Диск', 'Сеть (↓/↑)', 'Статус'])
        self.clients_tree.header().setSectionResizeMode(QHeaderView.ResizeToContents)
        self.clients_tree.itemDoubleClicked.connect(self.open_client_tab_from_double_click)
        self.clients_tree.setContextMenuPolicy(Qt.CustomContextMenu)
        self.clients_tree.customContextMenuRequested.connect(self.show_client_context_menu)
        self.view_stack.addWidget(self.clients_tree)

        # --- Вид "Сетка" ---
        self.clients_grid = QListWidget()
        self.clients_grid.setObjectName("clientsGrid")
        self.clients_grid.setViewMode(QListView.IconMode)
        self.clients_grid.setResizeMode(QListWidget.Fixed)
        self.clients_grid.setMovement(QListWidget.Static)
        self.clients_grid.setUniformItemSizes(True)
        self.clients_grid.setIconSize(QSize(self.grid_card_size - 20, int((self.grid_card_size - 20) * 0.75)))
        self.clients_grid.setSpacing(10)
        self.clients_grid.setWordWrap(True)
        self.clients_grid.setTextElideMode(Qt.ElideRight)
        self.clients_grid.itemDoubleClicked.connect(self.open_client_tab_from_double_click)
        self.clients_grid.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.clients_grid.setContextMenuPolicy(Qt.CustomContextMenu)
        self.clients_grid.customContextMenuRequested.connect(self.show_client_context_menu)
        self.view_stack.addWidget(self.clients_grid)
        
        clients_group_layout.addWidget(self.view_stack)
        self.clients_grid.setGridSize(QSize(self.grid_card_size, int(self.grid_card_size * 1.2)))
        self._set_grid_scale_visible(False)
        
        clients_layout.addWidget(clients_group)
        self._apply_action_icons()
        self._apply_view_icons()
        self._apply_grid_layout()
        
        # 2. Вкладка лога
        self.log_view_tab = QWidget()
        log_layout = QVBoxLayout(self.log_view_tab)
        log_filter_layout = QHBoxLayout()
        filter_icon = load_icon_from_assets("search.svg", QColor("#64748b"), size=16)
        if not filter_icon.isNull():
            filter_label = QLabel()
            filter_label.setPixmap(filter_icon.pixmap(16, 16))
            log_filter_layout.addWidget(filter_label)
        else:
            log_filter_layout.addWidget(QLabel("Фильтр:"))
        self.log_filter_input = QLineEdit()
        self.log_filter_input.setPlaceholderText("Поиск по логу...")
        self.log_filter_input.textChanged.connect(self.apply_log_filter)
        log_filter_layout.addWidget(self.log_filter_input)
        self.log_info_cb = QCheckBox("INFO")
        self.log_warn_cb = QCheckBox("WARNING")
        self.log_error_cb = QCheckBox("ERROR")
        self.log_info_cb.setChecked(True)
        self.log_warn_cb.setChecked(True)
        self.log_error_cb.setChecked(True)
        self.log_info_cb.stateChanged.connect(self.apply_log_filter)
        self.log_warn_cb.stateChanged.connect(self.apply_log_filter)
        self.log_error_cb.stateChanged.connect(self.apply_log_filter)
        log_filter_layout.addWidget(self.log_info_cb)
        log_filter_layout.addWidget(self.log_warn_cb)
        log_filter_layout.addWidget(self.log_error_cb)
        log_filter_layout.addStretch()
        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        log_layout.addWidget(QLabel("Системный лог:"))
        log_layout.addLayout(log_filter_layout)
        log_layout.addWidget(self.log_text)

        # 3. Вкладка задач
        self.tasks_tab = QWidget()
        tasks_layout = QVBoxLayout(self.tasks_tab)
        tasks_form = QHBoxLayout()
        tasks_form.addWidget(QLabel("Команда:"))
        self.task_command_input = QLineEdit()
        tasks_form.addWidget(self.task_command_input)
        tasks_form.addWidget(QLabel("Через (сек):"))
        self.task_delay_input = QLineEdit("60")
        self.task_delay_input.setFixedWidth(80)
        tasks_form.addWidget(self.task_delay_input)
        self.task_add_btn = QPushButton("Запланировать")
        self.task_add_btn.clicked.connect(self.add_scheduled_task)
        tasks_form.addWidget(self.task_add_btn)
        tasks_form.addStretch()

        self.tasks_list = QListWidget()
        tasks_layout.addLayout(tasks_form)
        tasks_layout.addWidget(QLabel("Очередь задач:"))
        tasks_layout.addWidget(self.tasks_list)
        
        # Добавляем вкладки
        self.tabs.addTab(self.clients_list_tab, "Клиенты")
        self.tabs.addTab(self.log_view_tab, "Системный лог")
        self.tabs.addTab(self.tasks_tab, "Задачи")
        self._apply_tab_icons()
        
        main_layout.addWidget(self.tabs)
        
        # Client data storage
        self.client_data = defaultdict(dict)

        # Таймер для обновления скриншотов в сетке
        self.grid_refresh_timer = QTimer(self)
        self.grid_refresh_timer.timeout.connect(self.request_grid_screenshots)

        # Таймер проверки задач
        self.tasks_timer = QTimer(self)
        self.tasks_timer.timeout.connect(self.process_scheduled_tasks)
        self.tasks_timer.start(1000)

    def _set_app_icon(self):
        """
        Загружает иконку приложения.
        Иконка 'icon.ico' должна находиться рядом с исполняемым файлом
        или в корневой директории проекта при запуске из исходников.
        """
        # Определяем базовый путь (рядом с .exe или в корне проекта)
        if getattr(sys, 'frozen', False) and hasattr(sys, "_MEIPASS"):
            base_path = sys._MEIPASS
        else:
            base_path = '.'

        icon_candidates = [
            os.path.join(base_path, 'assets', 'icons', 'app_icon.svg'),
            os.path.join(base_path, 'icon.ico')
        ]

        for icon_path in icon_candidates:
            if os.path.exists(icon_path):
                self.app_icon = QIcon(icon_path)
                logging.info(f"Иконка приложения успешно загружена из {icon_path}")
                return

        logging.warning("Файл иконки не найден. Будет использована иконка-заглушка.")
        pixmap = QPixmap(64, 64)
        pixmap.fill(Qt.gray)
        self.app_icon = QIcon(pixmap)

    def setup_tray_icon(self):
        """Настраивает иконку в системном трее."""
        self.tray_icon = QSystemTrayIcon(self.app_icon, self)
        self.tray_icon.setToolTip("Astra Monitor Server")

        # Создаем меню
        tray_menu = QMenu()
        
        toggle_action = tray_menu.addAction("Показать/Спрятать")
        toggle_action.triggered.connect(self.toggle_visibility)
        
        tray_menu.addSeparator()
        
        exit_action = tray_menu.addAction("Выход")
        exit_action.triggered.connect(self.quit_application)
        
        self.tray_icon.setContextMenu(tray_menu)
        
        # Обработка клика по иконке
        self.tray_icon.activated.connect(self.on_tray_icon_activated)
        
        self.tray_icon.show()

    def _asset_path(self, *parts):
        if getattr(sys, 'frozen', False) and hasattr(sys, "_MEIPASS"):
            base_path = sys._MEIPASS
        else:
            base_path = '.'
        return os.path.join(base_path, *parts)

    def _theme_accent_color(self):
        theme_key = self.theme
        if theme_key == "dark":
            theme_key = "midnight"
        return {
            "light": QColor("#2563eb"),
            "midnight": QColor("#38bdf8"),
            "sand": QColor("#b45309"),
            "graphite": QColor("#22c55e")
        }.get(theme_key, QColor("#2563eb"))

    def _make_tinted_icon(self, path, color):
        if path.lower().endswith(".svg"):
            if QSvgRenderer is None:
                return QIcon()
            renderer = QSvgRenderer(path)
            if not renderer.isValid():
                return QIcon()
            size = renderer.defaultSize()
            if size.isEmpty():
                size = QSize(24, 24)
            pixmap = QPixmap(size)
            pixmap.fill(Qt.transparent)
            painter = QPainter(pixmap)
            renderer.render(painter)
            painter.end()
            image = pixmap.toImage()
        else:
            image = QImage(path)
            if image.isNull():
                return QIcon()

        image = image.convertToFormat(QImage.Format_ARGB32)
        tinted = QImage(image.size(), QImage.Format_ARGB32)
        tinted.fill(color)
        painter = QPainter(tinted)
        painter.setCompositionMode(QPainter.CompositionMode_DestinationIn)
        painter.drawImage(0, 0, image)
        painter.end()
        return QIcon(QPixmap.fromImage(tinted))

    def _apply_action_icons(self):
        icon_map = {
            self.refresh_btn: ("assets/icons/refresh.svg", QColor("#2563eb")),
            self.message_btn: ("assets/icons/chat.svg", QColor("#0ea5e9")),
            self.reboot_btn: ("assets/icons/restart_alt.svg", QColor("#f59e0b")),
            self.shutdown_btn: ("assets/icons/power_settings_new.svg", QColor("#ef4444")),
            self.update_btn: ("assets/icons/system_update_alt.svg", QColor("#22c55e")),
            self.disconnect_btn: ("assets/icons/link_off.svg", QColor("#64748b"))
        }

        for button, (icon_rel, color) in icon_map.items():
            icon_path = self._asset_path(*icon_rel.split("/"))
            if os.path.exists(icon_path):
                button.setIcon(self._make_tinted_icon(icon_path, color))
                button.setIconSize(QSize(18, 18))

    def _apply_view_icons(self):
        accent = self._theme_accent_color()
        icon_map = {
            self.list_view_btn: ("list_view.svg", accent),
            self.grid_view_btn: ("grid_view.svg", accent),
        }
        for button, (icon_name, color) in icon_map.items():
            icon = load_icon_from_assets(icon_name, color, size=18)
            if not icon.isNull():
                button.setIcon(icon)
                button.setIconSize(QSize(18, 18))

    def _apply_tab_icons(self):
        accent = self._theme_accent_color()
        if hasattr(self, "tasks_tab"):
            icon = load_icon_from_assets("checklist.svg", accent, size=16)
            if not icon.isNull():
                index = self.tabs.indexOf(self.tasks_tab)
                if index != -1:
                    self.tabs.setTabIcon(index, icon)
        if hasattr(self, "clients_list_tab"):
            icon = load_icon_from_assets("list_view.svg", accent, size=16)
            if not icon.isNull():
                index = self.tabs.indexOf(self.clients_list_tab)
                if index != -1:
                    self.tabs.setTabIcon(index, icon)
        if hasattr(self, "log_view_tab"):
            icon = load_icon_from_assets("info.svg", accent, size=16)
            if not icon.isNull():
                index = self.tabs.indexOf(self.log_view_tab)
                if index != -1:
                    self.tabs.setTabIcon(index, icon)

    def toggle_visibility(self):
        """Переключает видимость главного окна."""
        if self.isVisible():
            self.hide()
        else:
            self.showNormal()
            self.activateWindow()

    def on_tray_icon_activated(self, reason):
        """Обработчик активации иконки в трее."""
        # Показываем/скрываем окно по левому клику (Trigger)
        if reason == QSystemTrayIcon.Trigger:
            self.toggle_visibility()

    def open_server_settings(self):
        """Открывает диалог настроек сервера."""
        dialog = ServerSettingsDialog(self, self.grid_refresh_interval, self.quality_grid, self.websocket_max_size_mb, self.websocket_chunk_size_mb, self.theme, self.grid_card_size)
        if dialog.exec_():
            values = dialog.get_values()
            new_interval = values['interval']
            new_quality = values['quality']
            new_max_size = values['max_size']
            new_chunk_size = values['chunk_size']
            new_theme = values['theme']
            new_card_size = values['grid_card_size']

            if new_chunk_size > new_max_size:
                self.show_toast("Размер чанка не может быть больше максимального размера сообщения WebSocket.", level="warning")
                return

            settings_changed = False
            websocket_settings_changed = False

            if self.quality_grid != new_quality:
                self.quality_grid = new_quality
                logging.info(f"Новое качество скриншотов на сетке: {new_quality}%")
                settings_changed = True

            if self.grid_refresh_interval != new_interval:
                self.grid_refresh_interval = new_interval
                logging.info(f"Интервал обновления сетки изменен на {new_interval} сек.")
                if self.grid_refresh_timer.isActive():
                    self.grid_refresh_timer.start(self.grid_refresh_interval * 1000)
                settings_changed = True

            if self.grid_card_size != new_card_size:
                self.grid_card_size = new_card_size
                self._apply_grid_layout()
                if hasattr(self, "grid_size_slider"):
                    self.grid_size_slider.blockSignals(True)
                    self.grid_size_slider.setValue(new_card_size)
                    self.grid_size_slider.blockSignals(False)
                    self.grid_size_label.setText(f"{new_card_size}px")
                settings_changed = True

            if self.websocket_max_size_mb != new_max_size or self.websocket_chunk_size_mb != new_chunk_size:
                self.websocket_max_size_mb = new_max_size
                self.websocket_chunk_size_mb = new_chunk_size
                logging.info(f"Настройки WebSocket изменены. Макс. размер: {new_max_size} МБ, чанк: {new_chunk_size} МБ.")
                settings_changed = True
                websocket_settings_changed = True
            
            if self.theme != new_theme:
                self.theme = new_theme
                logging.info(f"Тема изменена на {new_theme}")
                self.apply_theme()
                settings_changed = True

            if settings_changed:
                self.save_settings()

            if websocket_settings_changed:
                self.show_toast("Новые настройки WebSocket вступят в силу после перезапуска сервера.", level="warning")

    def show_client_context_menu(self, position):
        """Отображение контекстного меню для выбранного клиента."""
        widget = self.sender()
        if widget is None:
            return

        item = widget.itemAt(position)
        if not item:
            return

        selected_ids = self.get_selected_client_ids()
        if not selected_ids:
            return

        all_connected = all(self.client_data.get(cid, {}).get('status') == 'Connected' for cid in selected_ids)
        
        # Определяем, все ли клиенты имеют одинаковую ОС
        os_types = {self.client_data.get(cid, {}).get('os_type', 'Linux') for cid in selected_ids}
        is_homogeneous_os = len(os_types) == 1
        first_os_type = os_types.pop() if is_homogeneous_os else None

        menu = QMenu(self)

        if len(selected_ids) == 1:
            open_tab_action = menu.addAction("Открыть вкладку")
            icon = load_icon_from_assets("info.svg", QColor("#0ea5e9"), size=16)
            if not icon.isNull():
                open_tab_action.setIcon(icon)
            open_tab_action.triggered.connect(self.open_client_tab_from_button)
            if not all_connected:
                open_tab_action.setEnabled(False)
            menu.addSeparator()

        refresh_action = menu.addAction("Обновить данные")
        icon = load_icon_from_assets("refresh.svg", QColor("#2563eb"), size=16)
        if not icon.isNull():
            refresh_action.setIcon(icon)
        refresh_action.triggered.connect(self.refresh_client_data)
        
        send_message_action = menu.addAction("Отправить сообщение")
        icon = load_icon_from_assets("chat.svg", QColor("#0ea5e9"), size=16)
        if not icon.isNull():
            send_message_action.setIcon(icon)
        send_message_action.triggered.connect(self.send_message_to_clients)

        update_action = menu.addAction("Обновить клиент")
        icon = load_icon_from_assets("system_update_alt.svg", QColor("#22c55e"), size=16)
        if not icon.isNull():
            update_action.setIcon(icon)
        update_action.triggered.connect(self.update_selected_clients)
        # Блокируем кнопку обновления, если выбраны клиенты с разными ОС
        if not is_homogeneous_os:
            update_action.setEnabled(False)
            update_action.setToolTip("Можно обновлять только клиенты с одинаковой ОС")
        
        menu.addSeparator()

        reboot_action = menu.addAction("Перезагрузить")
        icon = load_icon_from_assets("restart_alt.svg", QColor("#f59e0b"), size=16)
        if not icon.isNull():
            reboot_action.setIcon(icon)
        reboot_action.triggered.connect(self.reboot_client)

        shutdown_action = menu.addAction("Выключить")
        icon = load_icon_from_assets("power_settings_new.svg", QColor("#ef4444"), size=16)
        if not icon.isNull():
            shutdown_action.setIcon(icon)
        shutdown_action.triggered.connect(self.shutdown_client)

        disconnect_action = menu.addAction("Отключить")
        icon = load_icon_from_assets("link_off.svg", QColor("#64748b"), size=16)
        if not icon.isNull():
            disconnect_action.setIcon(icon)
        disconnect_action.triggered.connect(self.disconnect_client)

        if not all_connected:
            for action in [refresh_action, send_message_action, update_action, reboot_action, shutdown_action, disconnect_action]:
                action.setEnabled(False)

        menu.exec_(widget.mapToGlobal(position))
        
    def quit_application(self):
        """Корректно завершает работу приложения."""
        logging.info("Получена команда на выход из трея. Завершение работы...")
        self.ws_server.stop_server()
        self.tray_icon.hide() # Скрываем иконку перед выходом
        QApplication.instance().quit()

    def setup_websocket_server(self):
        self.ws_server.new_connection.connect(self.handle_new_connection)
        self.ws_server.connection_lost.connect(self.handle_connection_lost)
        self.ws_server.new_message.connect(self.handle_new_message)
        
        self.server_thread = Thread(target=self.ws_server.start_server, daemon=True)
        self.server_thread.start()
        
    def handle_new_connection(self, connection_data_json):
        connection_data = json.loads(connection_data_json)
        client_id = connection_data['client_id']
        client_info = connection_data.get('client_info', {})
        ip_address = connection_data.get('client_ip') or client_id.split(':')[0]
        hostname = client_info.get('hostname', 'N/A')

        # --- Проверка на дубликат по hostname ---
        if hostname:
            for cid, cdata in self.client_data.items():
                # Проверяем, что это не тот же самый client_id (на случай быстрой переподключки)
                # и что найденный клиент действительно активен.
                if cid != client_id and cdata.get('hostname') == hostname and cdata.get('status') == 'Connected':
                    logging.warning(
                        f"Отклонено новое подключение от {ip_address} с hostname '{hostname}', "
                        f"т.к. клиент с таким именем уже подключен (ID: {cid})."
                    )
                    # Отправляем команду на закрытие нового соединения
                    asyncio.run_coroutine_threadsafe(
                        self.ws_server.client_disconnect(client_id),
                        self.ws_server.loop
                    )
                    return # Прерываем дальнейшую обработку

        # --- Поиск существующей записи для переподключившегося клиента ---
        old_client_id = None
        if client_id in self.client_data:
            old_client_id = client_id
        # Ищем по hostname, он более уникален чем IP в DHCP сетях.
        # Новая сессия всегда приоритетнее, поэтому ищем любого клиента с таким hostname,
        # даже если он еще числится подключенным (старая сессия могла "зависнуть").
        if not old_client_id and hostname:
            for cid, cdata in self.client_data.items():
                if cdata.get('hostname') == hostname:
                    old_client_id = cid
                    break
        
        # Если по hostname не нашли, пробуем по IP. Менее надежно, но лучше чем ничего.
        if not old_client_id and ip_address:
            for cid, cdata in self.client_data.items():
                # Статус не важен, новая сессия с этого IP главнее.
                if cdata.get('ip') == ip_address:
                    old_client_id = cid
                    break

        if old_client_id:
            # --- Клиент переподключился ---
            logging.info(f"Клиент '{hostname or ip_address}' переподключился. Старый ID: {old_client_id}, Новый ID: {client_id}")

            # 1. Переносим данные в новую запись, сохраняя настройки
            old_settings = self.client_data[old_client_id].get('settings', {})
            del self.client_data[old_client_id]
            
            self.client_data[client_id] = { 'status': 'Connected', 'ip': ip_address, 'settings': old_settings }
            self.client_data[client_id].update(client_info)
            if old_client_id in self.client_meta and old_client_id != client_id:
                self.client_meta[client_id] = self.client_meta.pop(old_client_id)
            self.client_data[client_id]['tags'] = self.client_meta.get(client_id, {}).get('tags', [])

            # 2. Обновляем ссылку на элемент дерева
            item = self.tree_items.pop(old_client_id)
            item.client_id = client_id
            self.tree_items[client_id] = item

            # 3. Обновляем ссылку на элемент сетки
            grid_item = self.grid_items.pop(old_client_id, None)
            if grid_item:
                grid_item.setData(Qt.UserRole, client_id)
                self.grid_items[client_id] = grid_item

        else:
            # --- Новый клиент ---
            logging.info(f"Новое подключение: {client_id} ({hostname})")
            self.client_data[client_id] = { 'status': 'Connected', 'ip': ip_address, 'settings': {} }
            self.client_data[client_id].update(client_info)
            self.client_data[client_id]['tags'] = self.client_meta.get(client_id, {}).get('tags', [])
            # Создаем для него элементы в GUI
            self._create_gui_items_for_client(client_id)

        self.update_tree_item(client_id)
        self.update_clients_count()
        # Запрашиваем актуальные настройки у клиента
        asyncio.run_coroutine_threadsafe(
            self.ws_server.send_command(client_id, "get_settings"),
            self.ws_server.loop
        )
        
    def handle_connection_lost(self, client_id):
        hostname = self.client_data.get(client_id, {}).get('hostname', client_id)
        logging.warning(f"[Отключение] {client_id} ({hostname})")
        if client_id in self.client_data:
            self.client_data[client_id]['status'] = 'Disconnected'
            self.update_tree_item(client_id)
        
        # Закрываем вкладку, если она была открыта для этого клиента
        if client_id in self.client_tabs:
            index = self.tabs.indexOf(self.client_tabs[client_id])
            if index != -1:
                self.close_tab(index)
        
        self.update_clients_count()
        
    def handle_new_message(self, data):
        client_id = data.get('client_id', 'unknown')
        if client_id == 'unknown' or client_id not in self.client_data:
            return
        
        if 'error' in data:
            client_ip = self.client_data[client_id].get('ip')
            logging.error(f"Ошибка от {client_ip}: {data['error']}")
            return
        
        # Обновляем данные клиента и главный список
        self.client_data[client_id].update(data)
        self._update_history(client_id, data)
        self.update_tree_item(client_id)
        
        # Делегирование обработки конкретным методам через диспетчер
        for msg_type, handler in self.message_handlers.items():
            if msg_type in data:
                handler(client_id, data)

        # Обновляем открытую вкладку клиента
        if client_id in self.client_tabs:
            self.client_tabs[client_id].update_client_data(data)

    # --- Новые приватные обработчики сообщений ---

    def _log_to_client_or_system(self, client_id, message):
        """Логирует сообщение во вкладку клиента или в системный лог."""
        if client_id in self.client_tabs:
            self.client_tabs[client_id].log_to_client(message)
        else:
            hostname = self.client_data.get(client_id, {}).get('hostname', 'unknown')
            logging.info(f"[{hostname}] {message}")

    def _handle_files_list(self, client_id, data):
        path = data.get('files_list', {}).get('path', 'N/A')
        self._log_to_client_or_system(client_id, f"Получен список файлов для '{path}'")
        if client_id in self.client_tabs:
            self.client_tabs[client_id].file_manager_widget.update_files_list(data['files_list'])

    def _handle_full_system_info(self, client_id, data):
        self._log_to_client_or_system(client_id, "Получена полная информация о системе.")
        if client_id in self.client_tabs:
            self.client_tabs[client_id].system_info_full_widget.update_info(data['full_system_info'])

    def _handle_screenshot_update(self, client_id, data):
        """Обрабатывает входящий скриншот для сетки и детальной вкладки."""
        # Обновляем иконку в сетке
        grid_item = self.grid_items.get(client_id)
        if grid_item and self.view_stack.currentIndex() == 1:
            logging.info(f"Получен скриншот для сетки от {self.client_data[client_id].get('hostname', client_id)}")
            try:
                img_data = base64.b64decode(data['screenshot'])
                pixmap = QPixmap()
                pixmap.loadFromData(img_data)
                if not pixmap.isNull():
                    grid_item.setIcon(QIcon(pixmap))
            except Exception as e:
                logging.warning(f"Ошибка обновления скриншота в сетке для %s: %s", client_id, e)

        # Обновляем виджет во вкладке, если она открыта
        if client_id in self.client_tabs:
            self.client_tabs[client_id].screenshot_widget.update_screenshot(
                data['screenshot'], data['quality'], data['timestamp']
            )

    def _handle_file_upload_result(self, client_id, data):
        if data['file_upload_result'] == 'success':
            msg = "Файл успешно загружен на клиент."
        else:
            msg = f"Ошибка загрузки файла на клиент: {data.get('error', 'Unknown error')}"
        self._log_to_client_or_system(client_id, msg)

    def _handle_file_delete_result(self, client_id, data):
        if data['file_delete_result'] == 'success':
            self._log_to_client_or_system(client_id, "Файл/папка успешно удалены.")
            if client_id in self.client_tabs:
                self.client_tabs[client_id].file_manager_widget.refresh_files()
        else:
            msg = f"Ошибка удаления на клиенте: {data.get('error', 'Unknown error')}"
            self._log_to_client_or_system(client_id, msg)

    def _handle_command_result(self, client_id, data):
        if client_id in self.client_tabs:
            self.client_tabs[client_id].append_to_terminal(data['command_result'])

    def _handle_command_error(self, client_id, data):
        if client_id in self.client_tabs:
            self.client_tabs[client_id].append_to_terminal(f"Ошибка: {data['command_error']}")

    def _handle_prompt_update(self, client_id, data):
        self._log_to_client_or_system(client_id, f"Директория изменена на: {data['prompt_update']}")
        if client_id in self.client_tabs:
            self.client_tabs[client_id].update_prompt(data['prompt_update'])

    def _handle_client_settings(self, client_id, data):
        self.client_data[client_id]['settings'] = data['client_settings']
        self._log_to_client_or_system(client_id, "Получены и применены настройки от клиента.")

    def _handle_rename_result(self, client_id, data):
        if data['rename_result'] == 'success':
            self._log_to_client_or_system(client_id, "Файл/папка успешно переименованы.")
            if client_id in self.client_tabs:
                self.client_tabs[client_id].file_manager_widget.refresh_files()
        else:
            msg = f"Ошибка переименования: {data.get('error', 'Unknown error')}"
            self._log_to_client_or_system(client_id, msg)

    def _handle_apt_repo_data(self, client_id, data):
        if client_id in self.client_tabs:
            self.client_tabs[client_id].update_manager_widget.handle_repo_data(data['apt_repo_data'])

    def _handle_apt_upgradable_list(self, client_id, data):
        if client_id in self.client_tabs:
            self.client_tabs[client_id].update_manager_widget.handle_upgradable_list(data['apt_upgradable_list'])

    def _handle_apt_command_output(self, client_id, data):
        if client_id in self.client_tabs:
            self.client_tabs[client_id].update_manager_widget.append_output(data['apt_command_output'])

    def _handle_apt_command_result(self, client_id, data):
        if client_id in self.client_tabs:
            self.client_tabs[client_id].update_manager_widget.append_output(data['apt_command_result'])
        
        original_command = data.get("original_command")
        if original_command == "sudo apt-get update":
            asyncio.run_coroutine_threadsafe(
                self.ws_server.send_command(client_id, "apt:list_upgradable"),
                self.ws_server.loop
            )

    def _handle_install_output(self, client_id, data):
        output = data['install_output']
        self._log_client_action(client_id, output, f"[{self.client_data[client_id].get('ip')}] {output}")

    def _handle_install_result(self, client_id, data):
        output = data['install_result']
        self._log_client_action(client_id, output, f"[{self.client_data[client_id].get('ip')}] {output}")

    def _handle_message_result(self, client_id, data):
        client_ip = self.client_data[client_id].get('ip')
        if data['message_result'] == 'success':
            msg = f"Сообщение успешно показано: {data.get('info', '')}"
            sys_msg = f"Сообщение успешно показано на {client_ip}: {data.get('info', '')}"
            self._log_client_action(client_id, msg, sys_msg)
        else:
            msg = f"Ошибка показа сообщения: {data.get('error', 'Unknown error')}"
            sys_msg = f"Ошибка показа сообщения на {client_ip}: {data.get('error', 'Unknown error')}"
            self._log_client_action(client_id, msg, sys_msg)

    def _handle_interactive_started(self, client_id, data):
        if client_id in self.client_tabs:
            self.client_tabs[client_id].handle_interactive_started()

    def _handle_interactive_output(self, client_id, data):
        output_data = data['interactive_output']
        if client_id in self.client_tabs:
            self.client_tabs[client_id].handle_interactive_output(output_data['data'])

    def _handle_interactive_stopped(self, client_id, data):
        if client_id in self.client_tabs:
            self.client_tabs[client_id].handle_interactive_stopped()

    def _cancel_download(self, client_id, remote_path):
        """Обработчик отмены скачивания файла с клиента."""
        context_key = (client_id, remote_path)
        context = self.download_contexts.get(context_key)
        # Проверяем, что контекст существует и что загрузка не была уже завершена.
        # Это предотвращает удаление файла, если диалог закрывается после успешного завершения.
        if not context or context.get('finished', False):
            return

        logging.warning(f"Отмена скачивания файла {remote_path} от клиента {client_id}.")

        # 1. Отправляем команду отмены клиенту
        asyncio.run_coroutine_threadsafe(
            self.ws_server.send_command(client_id, f"cancel_download:{remote_path}"),
            self.ws_server.loop
        )

        # 2. Закрываем и удаляем все серверные ресурсы
        context['progress_timer'].stop()
        with context['lock']:
            if not context['handle'].closed:
                context['handle'].close()
        self.download_contexts.pop(context_key, None) # Удаляем до попытки удаления файла
        self._remove_partial_file(context['path'], client_id)

    def register_pending_download(self, client_id, remote_path, local_path):
        """Регистрирует ожидаемое скачивание файла."""
        context_key = (client_id, remote_path)
        self.pending_downloads[context_key] = local_path
        logging.info(f"Ожидание скачивания {remote_path} от {client_id} в {local_path}")

    def update_download_progress(self, context_key):
        """Обновляет диалог прогресса скачивания."""
        context = self.download_contexts.get(context_key)
        if not context:
            return

        progress_dialog = context.get('progress_dialog')
        if not progress_dialog:
            return

        with context['lock']:
            received = context['received_size']
            total = context['expected_size']
        
        if total > 0:
            percent = int(received * 100 / total)
            progress_dialog.setValue(percent)
        
        progress_dialog.setLabelText(
            f"Скачивание файла '{os.path.basename(context['path'])}' ભ...\n"
            f"{received / 1024 / 1024:.2f} MB / {total / 1024 / 1024:.2f} MB"
        )

    def _handle_download_start(self, client_id, data):
        """Начало скачивания файла с клиента."""
        try:
            info = data['download_file_start']
            filename = info['filename']
            filesize = int(info['filesize'])
            remote_path = info['path']
            context_key = (client_id, remote_path)

            # Получаем пред-согласованный путь сохранения
            local_path = self.pending_downloads.pop(context_key, None)
            if not local_path:
                logging.error(f"Получено начало скачивания для {remote_path} от {client_id}, но путь не был согласован.")
                return

            # Создаем модальный диалог прогресса
            progress_dialog = QProgressDialog(f"Подготовка к скачиванию '{filename}'...", "Отмена", 0, 100, self)
            progress_dialog.setWindowModality(Qt.WindowModal)
            progress_dialog.setWindowTitle("Скачивание файла")
            progress_dialog.setValue(0)
            progress_dialog.setAutoClose(False)
            progress_dialog.setAutoReset(False)
            # Подключаем сигнал отмены
            progress_dialog.canceled.connect(lambda: self._cancel_download(client_id, remote_path))
            progress_dialog.show()

            # Таймер для обновления UI
            timer = QTimer(self)
            timer.timeout.connect(lambda: self.update_download_progress(context_key))
            timer.start(250) # Обновление 4 раза в секунду

            self.download_contexts[context_key] = {
                'handle': open(local_path, 'wb'),
                'path': local_path,
                'lock': Lock(),
                'expected_size': filesize,
                'received_size': 0,
                'last_logged_progress': -1,
                'progress_dialog': progress_dialog,
                'progress_timer': timer,
                'finished': False, # Флаг для предотвращения двойной обработки
            }
            self._log_client_action(client_id, f"[Загрузка] Началось скачивание файла '{filename}' ({filesize / 1024 / 1024:.2f} MB).", "")
        except Exception as e:
            self._log_client_action(client_id, f"Ошибка начала скачивания: {e}", f"Ошибка начала скачивания от {client_id}: {e}")
            if 'progress_dialog' in locals():
                progress_dialog.close()

    def _process_download_chunk(self, context, chunk_b64):
        """Обрабатывает чанк в фоновом потоке (декодирование и запись)."""
        try:
            chunk_bytes = base64.b64decode(chunk_b64)
            with context['lock']:
                if not context['handle'].closed:
                    context['handle'].write(chunk_bytes)
                    context['received_size'] += len(chunk_bytes)
        except Exception as e:
            logging.error(f"Ошибка обработки чанка в фоновом потоке: {e}")
            with context['lock']:
                if not context['handle'].closed:
                    context['handle'].close()

    def _handle_download_chunk(self, client_id, data):
        """Прием очередного чанка файла и передача в фоновый обработчик."""
        chunk_info = data['download_file_chunk']
        remote_path = chunk_info['path']
        context_key = (client_id, remote_path)

        context = self.download_contexts.get(context_key)
        if not context:
            return

        # Добавляем 'futures' при первом чанке
        if 'futures' not in context:
            context['futures'] = []

        future = self.file_processing_executor.submit(self._process_download_chunk, context, chunk_info['data'])
        context['futures'].append(future)

        # Логирование прогресса убрано отсюда, т.к. теперь есть диалог

    def _handle_download_end(self, client_id, data):
        """Завершение скачивания файла: ожидает завершения всех обработчиков."""
        end_info = data['download_file_end']
        remote_path = end_info['path']
        context_key = (client_id, remote_path)

        context = self.download_contexts.get(context_key)
        if not context or 'futures' not in context:
            return

        def check_completion():
            if all(f.done() for f in context['futures']):
                self._finalize_and_cleanup(context, client_id, context_key)
            else:
                QTimer.singleShot(200, check_completion)

        check_completion()

    def _create_gui_items_for_client(self, client_id):
        """Создает элементы GUI (для списка и сетки) для нового клиента."""
        # Элемент для дерева
        tree_item = SortableTreeWidgetItem(self.clients_tree)
        tree_item.client_id = client_id
        self.tree_items[client_id] = tree_item

        # Элемент для сетки
        grid_item = QListWidgetItem()
        grid_item.setIcon(self.placeholder_icon)
        grid_item.setData(Qt.UserRole, client_id)
        grid_item.setTextAlignment(Qt.AlignHCenter | Qt.AlignBottom)
        grid_item.setSizeHint(QSize(self.grid_card_size, int(self.grid_card_size * 1.2)))
        self.clients_grid.addItem(grid_item)
        self.grid_items[client_id] = grid_item

    def _remove_partial_file(self, file_path, client_id_for_log=None):
        """Безопасное удаление частично скачанного/загруженного файла."""
        try:
            if os.path.exists(file_path):
                os.remove(file_path)
                self._log_client_action(client_id_for_log, f"[Очистка] Частично переданный файл '{os.path.basename(file_path)}' удален.", "")
        except OSError as e:
            logging.error(f"Не удалось удалить частичный файл {file_path}: {e}")

    def _finalize_and_cleanup(self, context, client_id, context_key):
        """Выполняет финальную проверку размера, логирование и очистку контекста."""
        # Устанавливаем флаг, что обработка завершена, чтобы избежать вызова отмены.
        context['finished'] = True

        # Останавливаем таймер и получаем диалог
        context['progress_timer'].stop()
        progress_dialog = context.get('progress_dialog')

        with context['lock']:
            if not context['handle'].closed:
                context['handle'].close()
            final_size = context['received_size']

        expected_size = context['expected_size']
        path = context['path']

        if final_size != expected_size:
            msg = f"Ошибка: размер файла не совпадает. Ожидалось {expected_size}, получено {final_size}. Файл '{os.path.basename(path)}' может быть поврежден."
            self._log_client_action(client_id, msg, "")
            if progress_dialog:
                progress_dialog.close()
            QMessageBox.critical(self, "Ошибка скачивания", msg)
            self._remove_partial_file(path) # Удаляем поврежденный файл
        else:
            msg = f"Файл '{os.path.basename(path)}' успешно скачан."
            self._log_client_action(client_id, msg, "")
            if progress_dialog:
                progress_dialog.setValue(100)
                progress_dialog.close()
            self.show_toast(msg, level="success")

        self.download_contexts.pop(context_key, None)

    def update_tree_item(self, client_id):
        """Обновление или создание элемента в дереве клиентов."""
        tree_item = self.tree_items.get(client_id)
        grid_item = self.grid_items.get(client_id)

        if not tree_item or not grid_item:
            return

        data = self.client_data[client_id]
        hostname = data.get('hostname', 'N/A')
        tags = data.get('tags', [])
        info_text = data.get('settings', {}).get('info_text', '')
        note_text = info_text
        if tags:
            tag_str = ", ".join(tags)
            note_text = f"{info_text} | Теги: {tag_str}" if info_text else f"Теги: {tag_str}"
        cpu = round(data.get('cpu_percent', 0))
        mem = round(data.get('memory_percent', 0))
        status = data.get('status', 'Unknown')
        
        # --- Обновляем элемент дерева ---
        tree_item.setText(0, data.get('ip', 'N/A'))
        tree_item.setText(1, hostname)
        tree_item.setText(2, note_text)
        tree_item.setText(3, data.get('version', 'N/A'))
        tree_item.setText(4, f"{cpu}%")
        tree_item.setText(5, f"{mem}%")
        tree_item.setText(6, f"{round(data.get('disk_percent', 0))}%")
        
        recv = data.get('bytes_recv_speed', 0) / 1024
        sent = data.get('bytes_sent_speed', 0) / 1024
        tree_item.setText(7, f"{recv:.1f} / {sent:.1f} KB/s")
        
        gray_brush = QBrush(Qt.gray)

        if status == 'Connected':
            status_text = "Подключен"
            # Сбрасываем цвет на дефолтный
            for i in range(tree_item.columnCount()):
                tree_item.setData(i, Qt.ForegroundRole, QVariant())
            tree_item.setForeground(8, QBrush(QColor("green")))
            
            grid_item.setData(Qt.ForegroundRole, QVariant())
            # Включаем элемент
            grid_item.setFlags(grid_item.flags() | Qt.ItemIsEnabled)
            tree_item.setFlags(tree_item.flags() | Qt.ItemIsEnabled)
            # Обновляем текст в сетке
            grid_info = f"{hostname}"
            if info_text:
                grid_info += f" {info_text}"
            if tags:
                grid_info += f"\nТеги: {', '.join(tags)}"
            grid_item.setText(f"{grid_info}\nCPU: {cpu}% | RAM: {mem}%")
            # Если иконки нет (например, после переподключения), ставим заглушку, чтобы зарезервировать место
            if grid_item.icon().isNull():
                grid_item.setIcon(self.placeholder_icon)

        elif status == 'Disconnected':
            status_text = "Отключен"
            # Устанавливаем серый цвет
            for i in range(tree_item.columnCount()):
                tree_item.setForeground(i, gray_brush)
            grid_item.setForeground(gray_brush)
            tree_item.setForeground(8, QBrush(QColor("red")))
            # Отключаем элемент, чтобы он не был интерактивным
            grid_item.setFlags(grid_item.flags() & ~Qt.ItemIsEnabled)
            tree_item.setFlags(tree_item.flags() & ~Qt.ItemIsEnabled)
            # Обновляем текст и иконку в сетке
            grid_item.setText(f"{hostname}\n(Отключен)")
            grid_item.setIcon(QIcon())
        else:
            status_text = "Неизвестно"

        tree_item.setText(8, status_text)
        if self.clients_tree.isSortingEnabled():
            self.clients_tree.sortItems(self.clients_tree.sortColumn(), self.clients_tree.header().sortIndicatorOrder())

    def get_selected_client_ids(self):
        """Получение списка client_id выбранных клиентов."""
        current_view_idx = self.view_stack.currentIndex()
        
        if current_view_idx == 0: # Список
            selected_items = self.clients_tree.selectedItems()
            return [item.client_id for item in selected_items if hasattr(item, 'client_id')]
        elif current_view_idx == 1: # Сетка
            selected_items = self.clients_grid.selectedItems()
            return [item.data(Qt.UserRole) for item in selected_items]
        
        return []
    
    def update_clients_count(self):
        count = len([cid for cid, data in self.client_data.items() if data.get('status') == 'Connected'])
        self.clients_count_label.setText(f"Клиентов: {count}")

    def filter_clients(self):
        query = (self.client_filter_input.text() or "").strip().lower()
        for i in range(self.clients_tree.topLevelItemCount()):
            item = self.clients_tree.topLevelItem(i)
            client_id = getattr(item, "client_id", "")
            tags = self.client_data.get(client_id, {}).get("tags", [])
            haystack = " ".join([
                item.text(0),
                item.text(1),
                item.text(2),
                item.text(3),
                " ".join(tags) if tags else ""
            ]).lower()
            item.setHidden(bool(query) and query not in haystack)

        for i in range(self.clients_grid.count()):
            item = self.clients_grid.item(i)
            client_id = item.data(Qt.UserRole)
            tags = self.client_data.get(client_id, {}).get("tags", [])
            haystack = " ".join([item.text(), " ".join(tags) if tags else ""]).lower()
            item.setHidden(bool(query) and query not in haystack)

        if self.view_stack.currentIndex() == 1:
            self.request_grid_screenshots()

    def _append_log_line(self, line):
        self._log_lines.append(line)
        if self._log_filter_active():
            if self._log_line_matches(line):
                self.log_text.append(line)
            return
        self.log_text.append(line)

    def _log_filter_active(self):
        if (self.log_filter_input.text() or "").strip():
            return True
        return not (self.log_info_cb.isChecked() and self.log_warn_cb.isChecked() and self.log_error_cb.isChecked())

    def _log_line_matches(self, line):
        text = (self.log_filter_input.text() or "").strip().lower()
        if text and text not in line.lower():
            return False
        level_ok = False
        if "[INFO]" in line and self.log_info_cb.isChecked():
            level_ok = True
        if "[WARNING]" in line and self.log_warn_cb.isChecked():
            level_ok = True
        if "[ERROR]" in line and self.log_error_cb.isChecked():
            level_ok = True
        return level_ok

    def apply_log_filter(self):
        self.log_text.clear()
        for line in self._log_lines:
            if self._log_line_matches(line):
                self.log_text.append(line)

    def on_grid_size_changed(self, value):
        self.grid_card_size = value
        if hasattr(self, "grid_size_label"):
            self.grid_size_label.setText(f"{value}px")
        self._apply_grid_layout()

    def _save_grid_size_from_slider(self):
        self.save_settings()

    def _set_grid_scale_visible(self, visible):
        self.grid_scale_label.setVisible(visible)
        self.grid_size_slider.setVisible(visible)
        self.grid_size_label.setVisible(visible)

    def _toast_colors(self, level):
        theme_key = self.theme
        if theme_key == "dark":
            theme_key = "midnight"

        palettes = {
            "light": {
                "info": ("#1f2937", "#e0f2fe"),
                "success": ("#14532d", "#dcfce7"),
                "warning": ("#78350f", "#fef3c7"),
                "error": ("#7f1d1d", "#fee2e2"),
            },
            "midnight": {
                "info": ("#e2e8f0", "#1e293b"),
                "success": ("#dcfce7", "#14532d"),
                "warning": ("#fef3c7", "#78350f"),
                "error": ("#fee2e2", "#7f1d1d"),
            },
            "sand": {
                "info": ("#3f3a2f", "#f3e9dc"),
                "success": ("#14532d", "#f0fdf4"),
                "warning": ("#78350f", "#fef3c7"),
                "error": ("#7f1d1d", "#fee2e2"),
            },
            "graphite": {
                "info": ("#e5e5e5", "#1f1f1f"),
                "success": ("#dcfce7", "#14532d"),
                "warning": ("#fef3c7", "#78350f"),
                "error": ("#fee2e2", "#7f1d1d"),
            },
        }
        text, bg = palettes.get(theme_key, palettes["light"]).get(level, ("#1f2937", "#e0f2fe"))
        return text, bg

    def _toast_icon(self, level):
        accent = self._theme_accent_color()
        icon_map = {
            "info": ("info.svg", accent),
            "success": ("checklist.svg", QColor("#22c55e")),
            "warning": ("help.svg", QColor("#f59e0b")),
            "error": ("delete.svg", QColor("#ef4444")),
        }
        icon_name, color = icon_map.get(level, ("info.svg", accent))
        return load_icon_from_assets(icon_name, color, size=16)

    def show_toast(self, message, level="info", duration_ms=2500):
        text, bg = self._toast_colors(level)
        icon = self._toast_icon(level)
        toast = Toast(self, message, bg, text, duration_ms=duration_ms, icon=icon if not icon.isNull() else None)
        toast.show()
        self._toasts.append(toast)
        toast.destroyed.connect(lambda: self._on_toast_closed(toast))
        self._position_toasts()

    def _on_toast_closed(self, toast):
        if toast in self._toasts:
            self._toasts.remove(toast)
            self._position_toasts()

    def _position_toasts(self):
        if not self._toasts:
            return
        margin = 16
        gap = 10
        base_rect = self.rect()
        y = base_rect.bottom() - margin
        for toast in reversed(self._toasts):
            size = toast.sizeHint()
            x = base_rect.right() - margin - size.width()
            y -= size.height()
            toast.move(x, y)
            y -= gap

    def _build_placeholder_icon(self, size):
        width = max(1, size.width())
        height = max(1, size.height())
        pixmap = QPixmap(width, height)
        pixmap.fill(Qt.transparent)

        theme_key = self.theme
        if theme_key == "dark":
            theme_key = "midnight"

        if theme_key in ("midnight", "graphite"):
            bg_top = QColor("#111827") if theme_key == "midnight" else QColor("#1a1a1a")
            bg_bottom = QColor("#0b1220") if theme_key == "midnight" else QColor("#111111")
            border = QColor("#1f2937") if theme_key == "midnight" else QColor("#2a2a2a")
            text_color = QColor("#cbd5f5") if theme_key == "midnight" else QColor("#cfcfcf")
        else:
            bg_top = QColor("#f8fafc")
            bg_bottom = QColor("#e5e7eb")
            border = QColor("#cbd5f5")
            text_color = QColor("#6b7280")

        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.Antialiasing)

        gradient = QLinearGradient(0, 0, 0, height)
        gradient.setColorAt(0, bg_top)
        gradient.setColorAt(1, bg_bottom)
        painter.fillRect(0, 0, width, height, gradient)

        radius = max(6, min(14, int(min(width, height) * 0.08)))
        pen = QPen(border)
        pen.setWidth(2)
        painter.setPen(pen)
        painter.drawRoundedRect(2, 2, width - 4, height - 4, radius, radius)

        font = QFont()
        font.setPointSize(9)
        font.setBold(False)
        painter.setFont(font)
        painter.setPen(text_color)
        painter.drawText(0, int(height * 0.68), width, int(height * 0.25),
                         Qt.AlignHCenter | Qt.AlignTop, "Нет изображения")
        painter.end()
        return QIcon(pixmap)

    def _apply_grid_layout(self):
        icon_w = max(120, self.grid_card_size - 20)
        icon_h = int(icon_w * 0.75)
        self.clients_grid.setIconSize(QSize(icon_w, icon_h))
        text_area = 56
        grid_size = QSize(self.grid_card_size, icon_h + text_area)
        self.clients_grid.setGridSize(grid_size)
        self.placeholder_icon = self._build_placeholder_icon(self.clients_grid.iconSize())
        for item in self.grid_items.values():
            item.setSizeHint(grid_size)
            if item.icon().isNull():
                item.setIcon(self.placeholder_icon)

    def _update_history(self, client_id, data):
        history = self.metrics_history[client_id]
        cpu = data.get("cpu_percent")
        mem = data.get("memory_percent")
        disk = data.get("disk_percent")
        if isinstance(cpu, (int, float)):
            history["cpu"].append(float(cpu))
        if isinstance(mem, (int, float)):
            history["mem"].append(float(mem))
        if isinstance(disk, (int, float)):
            history["disk"].append(float(disk))
        self.client_data[client_id]["history"] = history
        if client_id in self.client_tabs:
            self.client_tabs[client_id].update_history(history)

    def add_scheduled_task(self):
        command = self.task_command_input.text().strip()
        if not command:
            self.show_toast("Введите команду для выполнения.", level="warning")
            return

        selected_ids = self.get_selected_client_ids()
        if not selected_ids:
            self.show_toast("Выберите одного или нескольких клиентов.", level="warning")
            return

        try:
            delay = int(self.task_delay_input.text().strip())
        except ValueError:
            self.show_toast("Задержка должна быть числом (сек).", level="warning")
            return

        delay = max(1, delay)
        run_at = time.time() + delay
        task = {
            "run_at": run_at,
            "command": command,
            "clients": list(selected_ids),
        }
        item_text = f"{command} -> {len(selected_ids)} клиент(ов) через {delay} сек"
        item = QListWidgetItem(item_text)
        self.tasks_list.addItem(item)
        task["item"] = item
        self.scheduled_tasks.append(task)
        self.task_command_input.clear()

    def process_scheduled_tasks(self):
        if not self.scheduled_tasks:
            return
        now = time.time()
        remaining = []
        for task in self.scheduled_tasks:
            if now < task["run_at"]:
                remaining.append(task)
                continue
            for client_id in task["clients"]:
                asyncio.run_coroutine_threadsafe(
                    self.ws_server.send_command(client_id, f"execute:{task['command']}"),
                    self.ws_server.loop
                )
            if task.get("item"):
                row = self.tasks_list.row(task["item"])
                if row != -1:
                    self.tasks_list.takeItem(row)
        self.scheduled_tasks = remaining
        
    def _log_client_action(self, client_id, message_for_client_log, message_for_system_log):
        """Логирует действие в лог клиента или в системный лог."""
        if client_id and client_id in self.client_tabs:
            if message_for_client_log:
                self.client_tabs[client_id].append_to_log_signal.emit(message_for_client_log)
        elif message_for_system_log:
            logging.info(message_for_system_log)

    def on_custom_commands_updated(self):
        """Слот для сохранения кастомных команд."""
        self.save_settings()
        logging.info("Пользовательские команды сохранены.")

    def on_client_settings_changed(self, client_id, new_settings):
        """Слот для сохранения настроек клиента."""
        if client_id in self.client_data:
            self.client_data[client_id]['settings'].update(new_settings)
            client_name = self.client_data[client_id].get('hostname', client_id)
            self._log_client_action(client_id, "Настройки клиента обновлены.", f"Настройки для клиента {client_name} обновлены в памяти сервера.")

    def on_client_meta_changed(self, client_id, meta):
        """Слот для сохранения метаданных клиента (теги и т.п.)."""
        if client_id not in self.client_data:
            return
        tags = meta.get("tags", [])
        self.client_data[client_id]["tags"] = tags
        self.client_meta[client_id] = {"tags": tags}
        self.save_settings()
        self.update_tree_item(client_id)
        self.filter_clients()

    def disconnect_client(self):
        selected_ids = self.get_selected_client_ids()
        if not selected_ids:
            self.show_toast("Пожалуйста, выберите клиента(ов) для отключения.", level="warning")
            return

        for client_id in selected_ids:
            self._log_client_action(client_id, "Отключаем клиента...", f"Отключаем клиента {self.client_data[client_id].get('ip')}...")
            asyncio.run_coroutine_threadsafe(
                self.ws_server.client_disconnect(client_id),
                self.ws_server.loop
            )
        self.show_toast(f"Команда на отключение отправлена {len(selected_ids)} клиентам.", level="info")

    def open_client_tab_from_double_click(self, item, column=None):
        self.open_client_tab(item)

    def open_client_tab_from_button(self):
        selected_items = self.clients_tree.selectedItems()
        if not selected_items:
            self.show_toast("Пожалуйста, выберите клиента для открытия вкладки.", level="warning")
            return
        self.open_client_tab(selected_items[0])

    def open_client_tab(self, item):
        """Открытие вкладки с детальной информацией о клиенте (для обоих видов)."""
        client_id = None
        # Определяем, из какого виджета пришел item
        if isinstance(item, SortableTreeWidgetItem): # Элемент из дерева
            if hasattr(item, 'client_id'):
                client_id = item.client_id
        else: # Элемент из сетки (QListWidgetItem)
            client_id = item.data(Qt.UserRole)

        if not client_id:
            return

        if self.client_data[client_id].get('status') != 'Connected':
            logging.warning(f"Попытка открыть вкладку для отключенного клиента: {client_id}")
            self.show_toast("Клиент не подключен.", level="error")
            return
            
        if client_id in self.client_tabs:
            index = self.tabs.indexOf(self.client_tabs[client_id])
            self.tabs.setCurrentIndex(index)
            logging.info(f"Переключение на уже открытую вкладку для клиента {self.client_data[client_id].get('hostname', client_id)}")
            return
            
        client_ip = self.client_data[client_id].get('ip')
        client_name = self.client_data[client_id].get('hostname', client_ip)
        logging.info(f"Открыта новая вкладка для клиента {client_name} ({client_id})")
        current_client_settings = self.client_data[client_id].get('settings', {})

        tab = ClientDetailTab(ws_server=self.ws_server, 
                              client_id=client_id, 
                              client_data=self.client_data[client_id],
                              custom_commands=self.custom_commands,
                              client_settings=current_client_settings,
                              main_window=self)
        tab.custom_commands_updated.connect(self.on_custom_commands_updated)
        tab.settings_changed.connect(lambda settings, cid=client_id: self.on_client_settings_changed(cid, settings))
        tab.meta_changed.connect(lambda meta, cid=client_id: self.on_client_meta_changed(cid, meta))
        history = self.client_data[client_id].get("history")
        if history:
            tab.update_history(history)
        
        tab_index = self.tabs.addTab(tab, f"{client_name}")
        self.tabs.setCurrentIndex(tab_index)
        self.client_tabs[client_id] = tab

    def show_clients_tab(self):
        """Показывает вкладку 'Клиенты', если она закрыта."""
        # Проверяем, не открыта ли уже вкладка
        for i in range(self.tabs.count()):
            if self.tabs.widget(i) == self.clients_list_tab:
                self.tabs.setCurrentIndex(i)
                return
        # Вставляем на первую позицию
        index = self.tabs.insertTab(0, self.clients_list_tab, "Клиенты")
        self.tabs.setCurrentIndex(index)

    def show_log_tab(self):
        """Показывает вкладку 'Системный лог', если она закрыта."""
        # Проверяем, не открыта ли уже вкладка
        for i in range(self.tabs.count()):
            if self.tabs.widget(i) == self.log_view_tab:
                self.tabs.setCurrentIndex(i)
                return
        
        # Ищем вкладку клиентов, чтобы вставить лог после нее
        client_tab_index = -1
        for i in range(self.tabs.count()):
            if self.tabs.widget(i) == self.clients_list_tab:
                client_tab_index = i
                break
        
        insert_pos = client_tab_index + 1 if client_tab_index != -1 else 0
        index = self.tabs.insertTab(insert_pos, self.log_view_tab, "Системный лог")
        self.tabs.setCurrentIndex(index)

    def show_tasks_tab(self):
        """Показывает вкладку 'Задачи', если она закрыта."""
        for i in range(self.tabs.count()):
            if self.tabs.widget(i) == self.tasks_tab:
                self.tabs.setCurrentIndex(i)
                return

        insert_pos = self.tabs.count()
        for i in range(self.tabs.count()):
            if self.tabs.widget(i) == self.clients_list_tab:
                insert_pos = i + 1
                break

        index = self.tabs.insertTab(insert_pos, self.tasks_tab, "Задачи")
        self.tabs.setCurrentIndex(index)

    def close_tab(self, index):
        """Закрытие вкладки."""
        widget = self.tabs.widget(index)
        if not widget:
            return

        # Вкладки клиентов имеют тип ClientDetailTab, остальные - системные
        if not isinstance(widget, ClientDetailTab):
            # Для системных вкладок - просто удаляем из QTabWidget, не удаляя сам виджет
            self.tabs.removeTab(index)
            return

        # Останавливаем интерактивную сессию перед закрытием вкладки
        widget.stop_interactive_session()

        # Для вкладок клиентов - логика с полным удалением
        client_id_to_remove = None
        for cid, tab_widget in self.client_tabs.items():
            if tab_widget == widget:
                client_id_to_remove = cid
                break
        
        if client_id_to_remove:
            del self.client_tabs[client_id_to_remove]
            logging.info(f"Закрыта вкладка для клиента {client_id_to_remove}")

        self.tabs.removeTab(index)
        widget.deleteLater()

    def send_message_to_clients(self):
        """Отправка сообщения выбранным клиентам."""
        selected_ids = self.get_selected_client_ids()
        if not selected_ids:
            self.show_toast("Пожалуйста, выберите одного или нескольких клиентов.", level="warning")
            return

        message, ok = QInputDialog.getMultiLineText(self, "Отправить сообщение", "Введите сообщение для выбранных клиентов:")
        if not (ok and message.strip()): return

        for client_id in selected_ids:
            client_ip = self.client_data[client_id].get('ip', 'unknown')
            self._log_client_action(client_id, "Отправка сообщения клиенту...", f"Отправка сообщения клиенту {client_ip}...")
            asyncio.run_coroutine_threadsafe(
                self.ws_server.send_command(client_id, f"show_message:{message}"),
                self.ws_server.loop
            )
        
        self.show_toast(f"Команда отправки сообщения была передана {len(selected_ids)} клиентам.", level="info")

    def update_selected_clients(self):
        selected_ids = self.get_selected_client_ids()
        if not selected_ids:
            self.show_toast("Пожалуйста, выберите одного или нескольких клиентов для обновления.", level="warning")
            return

        title = "Выберите .deb пакет для обновления"
        file_filter = "DEB Packages (*.deb)"

        package_path, _ = QFileDialog.getOpenFileName(self, title, "", file_filter)
        if not package_path: return
        
        reply = QMessageBox.question(self, "Подтверждение",
                                     f"Вы уверены, что хотите обновить {len(selected_ids)} клиент(ов)?\n"
                                     f"Файл: {os.path.basename(package_path)}\n"
                                     "Клиенты будут перезапущены в процессе.",
                                     QMessageBox.Yes | QMessageBox.No)
        
        if reply != QMessageBox.Yes: return

        for client_id in selected_ids:
            client_ip = self.client_data[client_id].get('ip', 'unknown')
            logging.info(f"Запуск обновления для клиента {client_ip}...")
            asyncio.run_coroutine_threadsafe(
                self._perform_update(client_id, package_path),
                self.ws_server.loop
            )

    async def _perform_update(self, client_id, deb_path):
        """Асинхронный процесс обновления клиента."""
        filename = os.path.basename(deb_path)
        remote_path = f"/tmp/{filename}"
        self._log_client_action(client_id, f"Начало обновления. Загрузка пакета '{filename}'...", "")
        try:
            file_size = os.path.getsize(deb_path)
            await self.ws_server.send_command(client_id, f"upload_file_start:{remote_path}:{file_size}")

            CHUNK_SIZE = self.websocket_chunk_size_mb * 1024 * 1024
            hasher = hashlib.sha256()
            with open(deb_path, 'rb') as f:
                while chunk := f.read(CHUNK_SIZE):
                    hasher.update(chunk)
                    chunk_b64 = base64.b64encode(chunk).decode('ascii')
                    await self.ws_server.send_command(client_id, f"upload_file_chunk:{chunk_b64}")
            
            await self.ws_server.send_command(client_id, f"upload_file_end:{hasher.hexdigest()}")
            self._log_client_action(client_id, f"Пакет '{filename}' успешно загружен в {remote_path}.", "")
            self._log_client_action(client_id, "Запуск установки пакета. Клиент будет перезапущен.", "")
            await self.ws_server.send_command(client_id, f"install_package:{remote_path}")
        except Exception as e:
            self._log_client_action(client_id, f"Ошибка в процессе обновления: {e}", "")

    def refresh_client_data(self):
        self.send_command_to_selected("refresh", "обновления")

    def shutdown_client(self):
        self.send_command_to_selected("shutdown", "выключения", needs_confirmation=True)

    def reboot_client(self):
        self.send_command_to_selected("reboot", "перезагрузки", needs_confirmation=True)

    def send_command_to_selected(self, command, command_name_rus, needs_confirmation=False):
        """Обобщенная функция для отправки команд выбранным клиентам."""
        selected_ids = self.get_selected_client_ids()
        if not selected_ids:
            self.show_toast(f"Пожалуйста, выберите клиента(ов) для {command_name_rus}.", level="warning")
            return

        if needs_confirmation:
            hostnames = ", ".join([self.client_data[cid].get('hostname', self.client_data[cid].get('ip')) for cid in selected_ids])
            reply = QMessageBox.question(self, "Подтверждение", 
                                         f"Вы уверены, что хотите выполнить команду '{command}' для клиентов: {hostnames}?",
                                         QMessageBox.Yes | QMessageBox.No)
            if reply != QMessageBox.Yes:
                return

        for client_id in selected_ids:
            asyncio.run_coroutine_threadsafe(
                self.ws_server.send_command(client_id, command), 
                self.ws_server.loop
            )
            self._log_client_action(client_id, f"Отправлена команда {command_name_rus}.", f"Отправлена команда {command_name_rus} клиенту {self.client_data[client_id].get('ip')}")
        
    def switch_view(self, index):
        """Переключение между списком и сеткой."""
        self.view_stack.setCurrentIndex(index)
        if index == 0: # Список
            self.list_view_btn.setChecked(True)
            self.grid_view_btn.setChecked(False)
            self._set_grid_scale_visible(False)
            self.grid_refresh_timer.stop()
        elif index == 1: # Сетка
            self.list_view_btn.setChecked(False)
            self.grid_view_btn.setChecked(True)
            self._set_grid_scale_visible(True)
            self.request_grid_screenshots() # Немедленное обновление
            self.grid_refresh_timer.start(self.grid_refresh_interval * 1000)

    def request_grid_screenshots(self):
        """Запрашивает скриншоты у всех подключенных клиентов для сетки."""
        if self.view_stack.currentIndex() != 1:
            return # Не запрашивать, если сетка не активна

        logging.info("Запрос скриншотов для вида 'Сетка'...")
        for i in range(self.clients_grid.count()):
            item = self.clients_grid.item(i)
            if item.isHidden():
                continue
            client_id = item.data(Qt.UserRole)
            if self.client_data.get(client_id, {}).get('status') == 'Connected':
                asyncio.run_coroutine_threadsafe(
                    self.ws_server.send_command(client_id, f"screenshot_quality:{self.quality_grid}"),
                    self.ws_server.loop
                )

    def closeEvent(self, event):
        # При закрытии окна - сворачиваем в трей, а не выходим
        if self.tray_icon.isVisible():
            event.ignore()
            self.hide()
            self.tray_icon.showMessage(
                "Приложение свернуто",
                "Astra Monitor Server продолжает работать в фоновом режиме.",
                QSystemTrayIcon.Information,
                2000
            )

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._position_toasts()
