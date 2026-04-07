# astra_monitor_server/gui/widgets/update_manager_widget.py

import asyncio
import base64
import os
from PyQt5.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QGroupBox, QComboBox, 
                             QLabel, QPushButton, QTextEdit, QMessageBox, QTableWidget, 
                             QHeaderView, QAbstractItemView, QTableWidgetItem, QCheckBox,
                             QFileDialog, QProgressBar, QFrame)
from PyQt5.QtGui import QFont, QColor, QTextCursor
from PyQt5.QtCore import Qt, QSize, QTimer

from ..icon_utils import load_icon_from_assets

class UpdateManagerWidget(QWidget):

    def __init__(self, parent=None, ws_server=None, client_id=None):
        super().__init__(parent)
        self.ws_server = ws_server
        self.client_id = client_id
        self.repo_files_content = {}
        self.active_processes = {}  # {process_id: {"command": str, "start_time": str}}
        self.current_process_id = None
        self.auto_scroll = True
        self.init_ui()

    def init_ui(self):
        main_layout = QVBoxLayout(self)
        
        # --- Status Bar для процессов ---
        status_frame = QFrame()
        status_frame.setFrameStyle(QFrame.StyledPanel)
        status_layout = QHBoxLayout(status_frame)
        
        self.status_label = QLabel("✅ Готов")
        self.status_label.setStyleSheet("QLabel { padding: 5px; }")
        status_layout.addWidget(self.status_label)
        
        self.process_indicator = QProgressBar()
        self.process_indicator.setVisible(False)
        self.process_indicator.setMaximum(0)  # Infinite progress
        self.process_indicator.setFixedWidth(150)
        status_layout.addWidget(self.process_indicator)
        
        self.stop_process_btn = QPushButton("⏹️ Остановить")
        self.stop_process_btn.setVisible(False)
        self.stop_process_btn.clicked.connect(self.stop_current_process)
        status_layout.addWidget(self.stop_process_btn)
        
        self.reconnect_btn = QPushButton("🔄 Переподключиться")
        self.reconnect_btn.setVisible(False)
        self.reconnect_btn.clicked.connect(self.reconnect_to_process)
        status_layout.addWidget(self.reconnect_btn)
        
        status_layout.addStretch()
        main_layout.addWidget(status_frame)
        
        # --- Repositories ---
        repo_group = QGroupBox("Управление репозиториями")
        repo_layout = QVBoxLayout(repo_group)
        
        repo_actions_layout = QHBoxLayout()
        self.repo_selector = QComboBox()
        self.repo_selector.currentTextChanged.connect(self.display_repo_content)
        repo_actions_layout.addWidget(QLabel("Файл репозитория:"))
        repo_actions_layout.addWidget(self.repo_selector, 1)
        
        self.load_repos_btn = QPushButton("Загрузить")
        self.load_repos_btn.clicked.connect(self.load_repositories)
        repo_actions_layout.addWidget(self.load_repos_btn)
        
        self.save_repo_btn = QPushButton("Сохранить")
        self.save_repo_btn.clicked.connect(self.save_repository)
        repo_actions_layout.addWidget(self.save_repo_btn)
        
        self.repo_content_edit = QTextEdit()
        self.repo_content_edit.setFont(QFont("Monospace", 9))
        
        repo_layout.addLayout(repo_actions_layout)
        repo_layout.addWidget(self.repo_content_edit)
        main_layout.addWidget(repo_group)
        
        # --- Packages ---
        pkg_group = QGroupBox("Управление пакетами")
        pkg_layout = QVBoxLayout(pkg_group)
        
        pkg_actions_layout = QHBoxLayout()
        self.check_updates_btn = QPushButton("Шаг 1: Обновить списки пакетов (apt update)")
        self.check_updates_btn.clicked.connect(self.check_for_updates)
        
        self.list_upgradable_btn = QPushButton("Шаг 2: Показать обновляемые пакеты")
        self.list_upgradable_btn.clicked.connect(self.list_upgradable_packages)
        
        self.install_selected_btn = QPushButton("Установить выбранные")
        self.install_selected_btn.clicked.connect(self.install_selected_updates)
        
        self.install_all_btn = QPushButton("Обновить всю систему")
        self.install_all_btn.clicked.connect(self.install_all_updates)
        
        self.refresh_status_btn = QPushButton("🔄 Статус процессов")
        self.refresh_status_btn.clicked.connect(self.refresh_process_status)
        
        pkg_actions_layout.addWidget(self.check_updates_btn)
        pkg_actions_layout.addWidget(self.list_upgradable_btn)
        pkg_actions_layout.addWidget(self.install_selected_btn)
        pkg_actions_layout.addWidget(self.install_all_btn)
        pkg_actions_layout.addWidget(self.refresh_status_btn)
        pkg_actions_layout.addStretch()
        
        self.updates_table = QTableWidget()
        self.updates_table.setColumnCount(4)
        self.updates_table.setHorizontalHeaderLabels(["", "Пакет", "Текущая версия", "Новая версия"])
        self.updates_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.updates_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.updates_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.updates_table.setColumnWidth(0, 30)
        
        pkg_layout.addLayout(pkg_actions_layout)
        pkg_layout.addWidget(self.updates_table)

        # Output area with tabs
        output_layout = QVBoxLayout()
        self.output_label = QLabel("Вывод операций:")
        
        # Toolbar for output
        output_toolbar = QHBoxLayout()
        self.auto_scroll_cb = QCheckBox("Автопрокрутка")
        self.auto_scroll_cb.setChecked(True)
        self.auto_scroll_cb.stateChanged.connect(lambda: setattr(self, 'auto_scroll', self.auto_scroll_cb.isChecked()))
        output_toolbar.addWidget(self.auto_scroll_cb)
        
        self.output_view = QTextEdit()
        self.output_view.setReadOnly(True)
        self.output_view.setFont(QFont("Monospace", 9))
        
        self.clear_output_btn = QPushButton("Очистить вывод")
        self.clear_output_btn.clicked.connect(self.output_view.clear)
        output_toolbar.addWidget(self.clear_output_btn)
        
        output_toolbar.addStretch()
        
        output_layout.addWidget(self.output_label)
        output_layout.addLayout(output_toolbar)
        output_layout.addWidget(self.output_view)
        pkg_layout.addLayout(output_layout)
        
        main_layout.addWidget(pkg_group)
        
        main_layout.setStretch(2, 1)  # pkg_group
        self._apply_icons()

    def handle_detached_result(self, data):
        """Обработка результата остановки процесса"""
        if isinstance(data, dict) and 'detached_result' in data:
            result = data['detached_result']
            self.append_output(result)
            if "остановлен" in result:
                self.set_process_status(False)
                self.current_process_id = None


    def _apply_icons(self):
        icon_map = {
            self.load_repos_btn: ("download.svg", QColor("#2563eb")),
            self.save_repo_btn: ("save.svg", QColor("#22c55e")),
            self.check_updates_btn: ("refresh.svg", QColor("#0ea5e9")),
            self.list_upgradable_btn: ("search.svg", QColor("#64748b")),
            self.install_selected_btn: ("system_update_alt.svg", QColor("#22c55e")),
            self.install_all_btn: ("system_update_alt.svg", QColor("#16a34a")),
            self.clear_output_btn: ("clear_all.svg", QColor("#64748b")),
            self.refresh_status_btn: ("refresh.svg", QColor("#8b5cf6")),
        }
        for button, (icon_name, color) in icon_map.items():
            icon = load_icon_from_assets(icon_name, color=color, size=18)
            if not icon.isNull():
                button.setIcon(icon)
                button.setIconSize(QSize(18, 18))

    def load_repositories(self):
        asyncio.run_coroutine_threadsafe(
            self.ws_server.send_command(self.client_id, "apt:get_repos"),
            self.ws_server.loop
        )

    def save_repository(self):
        current_file = self.repo_selector.currentText()
        if not current_file:
            self.show_warning("Не выбран файл репозитория.")
            return
        
        content = self.repo_content_edit.toPlainText()
        content_b64 = base64.b64encode(content.encode('utf-8')).decode('ascii')
        
        asyncio.run_coroutine_threadsafe(
            self.ws_server.send_command(self.client_id, f"apt:save_repo:{current_file}:{content_b64}"),
            self.ws_server.loop
        )

    def check_for_updates(self):
        """Запуск apt update в фоне"""
        self.updates_table.setRowCount(0)
        self.append_output("🚀 Запуск apt update в фоновом режиме...")
        self.set_process_status(True, "Выполняется apt update...")
        
        asyncio.run_coroutine_threadsafe(
            self.ws_server.send_command(self.client_id, "apt:update"),
            self.ws_server.loop
        )

    def list_upgradable_packages(self):
        """Показать обновляемые пакеты"""
        self.updates_table.setRowCount(0)
        asyncio.run_coroutine_threadsafe(
            self.ws_server.send_command(self.client_id, "apt:list_upgradable"),
            self.ws_server.loop
        )

    def install_selected_updates(self):
        """Установка выбранных пакетов"""
        selected_packages = []
        for i in range(self.updates_table.rowCount()):
            checkbox_widget = self.updates_table.cellWidget(i, 0)
            if checkbox_widget and checkbox_widget.findChild(QCheckBox).isChecked():
                package_item = self.updates_table.item(i, 1)
                selected_packages.append(package_item.text())
        
        if not selected_packages:
            self.show_warning("Выберите пакеты для обновления.")
            return

        packages_str = ' '.join(selected_packages)
        self.append_output(f"🚀 Запуск установки пакетов в фоне: {packages_str}")
        self.set_process_status(True, f"Установка {len(selected_packages)} пакетов...")
        
        asyncio.run_coroutine_threadsafe(
            self.ws_server.send_command(self.client_id, f"apt:upgrade_packages:{packages_str}"),
            self.ws_server.loop
        )

    def install_all_updates(self):
        """Полное обновление системы"""
        reply = QMessageBox.question(self, "Подтверждение", 
                                    "Вы уверены, что хотите обновить всю систему?\n"
                                    "Это может занять длительное время и процесс продолжится даже при отключении.",
                                    QMessageBox.Yes | QMessageBox.No)
        if reply == QMessageBox.Yes:
            self.append_output("🚀 Запущено полное обновление системы в фоновом режиме...")
            self.set_process_status(True, "Полное обновление системы...")
            
            asyncio.run_coroutine_threadsafe(
                self.ws_server.send_command(self.client_id, "apt:full_upgrade"),
                self.ws_server.loop
            )

    def refresh_process_status(self):
        """Обновить статус всех apt процессов"""
        asyncio.run_coroutine_threadsafe(
            self.ws_server.send_command(self.client_id, "apt:list_processes"),
            self.ws_server.loop
        )

    def reconnect_to_process(self):
        """Переподключиться к последнему активному процессу"""
        if self.current_process_id:
            self.append_output(f"🔄 Переподключение к процессу {self.current_process_id}...")
            asyncio.run_coroutine_threadsafe(
                self.ws_server.send_command(self.client_id, f"apt:attach:{self.current_process_id}"),
                self.ws_server.loop
            )

    def stop_current_process(self):
        """Остановить текущий процесс"""
        if self.current_process_id:
            reply = QMessageBox.question(self, "Подтверждение", 
                                        f"Остановить процесс {self.current_process_id}?\n"
                                        "Это может привести к неполной установке пакетов.\n\n"
                                        "Процесс будет остановлен, но незавершенные операции могут оставить систему в нестабильном состоянии.",
                                        QMessageBox.Yes | QMessageBox.No)
            if reply == QMessageBox.Yes:
                self.append_output(f"⏹️ Отправка сигнала остановки процессу {self.current_process_id}...")
                asyncio.run_coroutine_threadsafe(
                    self.ws_server.send_command(self.client_id, f"stop_detached:{self.current_process_id}"),
                    self.ws_server.loop
                )
                # Меняем статус, но не очищаем сразу, ждем подтверждения
                self.stop_process_btn.setEnabled(False)
                self.stop_process_btn.setText("⏳ Остановка...")
                
                # Таймаут на случай если процесс не ответил
                QTimer.singleShot(10000, self._reset_stop_button)
                
    def _reset_stop_button(self):
        """Сброс кнопки остановки"""
        self.stop_process_btn.setEnabled(True)
        self.stop_process_btn.setText("⏹️ Остановить")
        if not self.current_process_id:
            self.set_process_status(False)

    def handle_apt_output(self, data):
        """Обработка вывода apt команд"""
        if isinstance(data, dict) and 'apt_command_output' in data:
            output = data['apt_command_output']
            self.append_output(output.strip())
            
            # Автоматическая прокрутка вниз
            if self.auto_scroll:
                cursor = self.output_view.textCursor()
                cursor.movePosition(QTextCursor.End)
                self.output_view.setTextCursor(cursor)

    def handle_apt_result(self, data):
        """Обработка результата apt команд"""
        if isinstance(data, dict) and 'apt_command_result' in data:
            result = data['apt_command_result']
            self.append_output(f"\n{result}\n")
            self.set_process_status(False)
            
            # Если команда успешно завершена и это был update, предложим показать обновления
            if "завершена с кодом: 0" in result and "apt-get update" in data.get('original_command', ''):
                reply = QMessageBox.question(self, "Обновление завершено", 
                                            "Списки пакетов обновлены. Показать доступные обновления?",
                                            QMessageBox.Yes | QMessageBox.No)
                if reply == QMessageBox.Yes:
                    self.list_upgradable_packages()

    def handle_apt_started(self, data):
        """Обработка запуска apt процесса"""
        if isinstance(data, dict) and 'apt_started' in data:
            process_id = data.get('process_id')
            command = data.get('command')
            self.current_process_id = process_id
            self.active_processes[process_id] = {
                'command': command,
                'start_time': data.get('timestamp', '')
            }
            self.append_output(f"✅ Процесс запущен (ID: {process_id})")
            self.status_label.setText(f"🔄 Выполняется: {command} (PID: {process_id[:12]}...)")

    def handle_process_status(self, data):
        """Обработка статуса процесса"""
        print(data)
        if isinstance(data, dict) and 'apt_process_status' in data:
            status = data['apt_process_status']
            process_id = status.get('process_id')
            state = status.get('status')
            
            if state == 'running':
                self.append_output(f"✅ Процесс {process_id} выполняется (PID: {status.get('pid')})")
                self.current_process_id = process_id
                self.set_process_status(True)
            elif state == 'completed':
                self.append_output(f"✅ Процесс {process_id} успешно завершен")
                self.set_process_status(False)
            elif state == 'not_found':
                self.append_output(f"⚠️ Процесс {process_id} не найден")
                self.set_process_status(False)

    def handle_processes_list(self, data):
        """Обработка списка процессов"""
        if isinstance(data, dict) and 'apt_processes' in data:
            processes = data['apt_processes']
            count = data.get('count', 0)
            
            if count > 0:
                self.append_output(f"\n📋 Найдено активных процессов: {count}")
                for pid, info in processes.items():
                    self.append_output(f"  • {pid}: {info.get('status')} - {info.get('command', '')[:80]}")
            else:
                self.append_output("📋 Активных apt процессов не найдено")

    def set_process_status(self, active, message=None):
        """Установка визуального статуса процесса"""
        self.process_indicator.setVisible(active)
        self.stop_process_btn.setVisible(active)
        self.reconnect_btn.setVisible(active and self.current_process_id is not None)
        
        if active:
            if message:
                self.status_label.setText(f"🔄 {message}")
            self.status_label.setStyleSheet("QLabel { padding: 5px; background-color: #fef3c7; color: #92400e; }")
        else:
            self.status_label.setText("✅ Готов")
            self.status_label.setStyleSheet("QLabel { padding: 5px; }")
            self.current_process_id = None

    def display_repo_content(self, filename):
        if filename in self.repo_files_content:
            self.repo_content_edit.setText(self.repo_files_content[filename])

    def handle_repo_data(self, data):
        self.repo_files_content = data
        self.repo_selector.clear()
        self.repo_selector.addItems(sorted(data.keys()))

    def handle_upgradable_list(self, packages):
        self.updates_table.setRowCount(len(packages))
        for i, pkg in enumerate(packages):
            # Checkbox
            checkbox_widget = QWidget()
            checkbox_layout = QHBoxLayout(checkbox_widget)
            checkbox = QCheckBox()
            checkbox_layout.addWidget(checkbox)
            checkbox_layout.setAlignment(Qt.AlignCenter)
            checkbox_layout.setContentsMargins(0,0,0,0)
            self.updates_table.setCellWidget(i, 0, checkbox_widget)
            
            self.updates_table.setItem(i, 1, QTableWidgetItem(pkg.get('name', '')))
            self.updates_table.setItem(i, 2, QTableWidgetItem(pkg.get('current', '')))
            self.updates_table.setItem(i, 3, QTableWidgetItem(pkg.get('new', '')))
        
        self.updates_table.resizeColumnsToContents()
        self.updates_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        
        if len(packages) > 0:
            self.append_output(f"📦 Найдено обновлений: {len(packages)}")

    def append_output(self, text):
        """Добавление текста в вывод с временной меткой"""
        from datetime import datetime
        timestamp = datetime.now().strftime("%H:%M:%S")
        self.output_view.append(f"[{timestamp}] {text}")

    def show_warning(self, message):
        """Показать предупреждение"""
        main_window = self.parent() if hasattr(self, "parent") else None
        if main_window and hasattr(main_window, "show_toast"):
            main_window.show_toast(message, level="warning")
        else:
            QMessageBox.warning(self, "Внимание", message)

    def cleanup(self):
        """Очистка ресурсов при закрытии"""
        # Отключаем обработчики
        if hasattr(self.ws_server, 'message_handlers'):
            self.ws_server.message_handlers.pop('apt_command_output', None)
            self.ws_server.message_handlers.pop('apt_command_result', None)
            self.ws_server.message_handlers.pop('apt_started', None)
            self.ws_server.message_handlers.pop('apt_process_status', None)
            self.ws_server.message_handlers.pop('apt_processes', None)