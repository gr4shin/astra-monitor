# astra_monitor_server/gui/widgets/update_manager_widget.py

import asyncio
import base64
from PyQt5.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QGroupBox, QComboBox, 
                             QLabel, QPushButton, QTextEdit, QMessageBox, QTableWidget, 
                             QHeaderView, QAbstractItemView, QTableWidgetItem, QCheckBox)
from PyQt5.QtGui import QFont
from PyQt5.QtCore import Qt

class UpdateManagerWidget(QWidget):
    def __init__(self, parent=None, ws_server=None, client_id=None, log_callback=None):
        super().__init__(parent)
        self.ws_server = ws_server
        self.client_id = client_id
        self.log_callback = log_callback or (lambda msg: print(msg))
        self.repo_files_content = {}
        self.init_ui()

    def init_ui(self):
        main_layout = QVBoxLayout(self)
        
        # --- Repositories ---
        repo_group = QGroupBox("📚 Управление репозиториями")
        repo_layout = QVBoxLayout(repo_group)
        
        repo_actions_layout = QHBoxLayout()
        self.repo_selector = QComboBox()
        self.repo_selector.currentTextChanged.connect(self.display_repo_content)
        repo_actions_layout.addWidget(QLabel("Файл репозитория:"))
        repo_actions_layout.addWidget(self.repo_selector, 1)
        
        self.load_repos_btn = QPushButton("📥 Загрузить")
        self.load_repos_btn.clicked.connect(self.load_repositories)
        repo_actions_layout.addWidget(self.load_repos_btn)
        
        self.save_repo_btn = QPushButton("💾 Сохранить")
        self.save_repo_btn.clicked.connect(self.save_repository)
        repo_actions_layout.addWidget(self.save_repo_btn)
        
        self.repo_content_edit = QTextEdit()
        self.repo_content_edit.setFont(QFont("Monospace", 9))
        
        repo_layout.addLayout(repo_actions_layout)
        repo_layout.addWidget(self.repo_content_edit)
        main_layout.addWidget(repo_group)
        
        # --- Packages ---
        pkg_group = QGroupBox("📦 Управление пакетами")
        pkg_layout = QVBoxLayout(pkg_group)
        
        pkg_actions_layout = QHBoxLayout()
        self.check_updates_btn = QPushButton("🔄 Проверить обновления")
        self.check_updates_btn.clicked.connect(self.check_for_updates)
        self.install_selected_btn = QPushButton("⬆️ Установить выбранные")
        self.install_selected_btn.clicked.connect(self.install_selected_updates)
        self.install_all_btn = QPushButton("🚀 Обновить всю систему")
        self.install_all_btn.clicked.connect(self.install_all_updates)
        pkg_actions_layout.addWidget(self.check_updates_btn)
        pkg_actions_layout.addWidget(self.install_selected_btn)
        pkg_actions_layout.addWidget(self.install_all_btn)
        pkg_actions_layout.addStretch()
        
        self.updates_table = QTableWidget()
        self.updates_table.setColumnCount(4)
        self.updates_table.setHorizontalHeaderLabels(["", "📦 Пакет", "Текущая версия", "Новая версия"])
        self.updates_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.updates_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.updates_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.updates_table.setColumnWidth(0, 30)
        
        pkg_layout.addLayout(pkg_actions_layout)
        pkg_layout.addWidget(self.updates_table)
        main_layout.addWidget(pkg_group)
        
        # --- Output Log ---
        output_group = QGroupBox("📜 Вывод команд")
        output_layout = QVBoxLayout(output_group)
        self.output_log = QTextEdit()
        self.output_log.setReadOnly(True)
        self.output_log.setFont(QFont("Monospace", 9))
        self.output_log.setStyleSheet("background-color: #2b2b2b; color: #f0f0f0;")
        output_layout.addWidget(self.output_log)
        main_layout.addWidget(output_group)
        
        main_layout.setStretch(1, 1) # pkg_group
        main_layout.setStretch(2, 1) # output_group

    def _send_command(self, command):
        asyncio.run_coroutine_threadsafe(
            self.ws_server.send_command(self.client_id, command),
            self.ws_server.loop
        )

    def load_repositories(self):
        self.output_log.clear()
        self.append_output("📚 Запрос списка репозиториев...")
        self._send_command("apt:get_repos")

    def save_repository(self):
        current_file = self.repo_selector.currentText()
        if not current_file:
            QMessageBox.warning(self, "⚠️ Ошибка", "Не выбран файл репозитория.")
            return
        
        content = self.repo_content_edit.toPlainText()
        content_b64 = base64.b64encode(content.encode('utf-8')).decode('ascii')
        
        self.output_log.clear()
        self.append_output(f"💾 Сохранение файла {current_file}...")
        self._send_command(f"apt:save_repo:{current_file}:{content_b64}")

    def check_for_updates(self):
        self.output_log.clear()
        self.updates_table.setRowCount(0)
        self.append_output("🔄 Выполнение 'apt update'...")
        self._send_command("apt:update")

    def install_selected_updates(self):
        selected_packages = []
        for i in range(self.updates_table.rowCount()):
            checkbox_widget = self.updates_table.cellWidget(i, 0)
            if checkbox_widget and checkbox_widget.findChild(QCheckBox).isChecked():
                package_item = self.updates_table.item(i, 1)
                selected_packages.append(package_item.text())
        
        if not selected_packages:
            QMessageBox.warning(self, "⚠️ Нет выбора", "Выберите пакеты для обновления.")
            return

        self.output_log.clear()
        self.append_output(f"⬆️ Обновление выбранных пакетов: {', '.join(selected_packages)}")
        self._send_command(f"apt:upgrade_packages:{' '.join(selected_packages)}")

    def install_all_updates(self):
        reply = QMessageBox.question(self, "❓ Подтверждение", "Вы уверены, что хотите обновить всю систему?", QMessageBox.Yes | QMessageBox.No)
        if reply == QMessageBox.Yes:
            self.output_log.clear()
            self.append_output("🚀 Выполнение 'apt upgrade'...")
            self._send_command("apt:full_upgrade")

    def display_repo_content(self, filename):
        if filename in self.repo_files_content:
            self.repo_content_edit.setText(self.repo_files_content[filename])

    def handle_repo_data(self, data):
        self.append_output("✅ Список репозиториев получен.")
        self.repo_files_content = data
        self.repo_selector.clear()
        self.repo_selector.addItems(sorted(data.keys()))

    def handle_upgradable_list(self, packages):
        self.append_output(f"✅ Найдено {len(packages)} пакетов для обновления.")
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

    def append_output(self, text):
        self.output_log.append(text.strip())
        self.output_log.verticalScrollBar().setValue(self.output_log.verticalScrollBar().maximum())