# astra_monitor_server/gui/widgets/update_manager_widget.py

import asyncio
import base64
import os
from PyQt5.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QGroupBox, QComboBox, 
                             QLabel, QPushButton, QTextEdit, QMessageBox, QTableWidget, 
                             QHeaderView, QAbstractItemView, QTableWidgetItem, QCheckBox,
                             QFileDialog)
from PyQt5.QtGui import QFont
from PyQt5.QtCore import Qt, pyqtSignal

class UpdateManagerWidget(QWidget):
    run_in_terminal_requested = pyqtSignal(str)

    def __init__(self, parent=None, ws_server=None, client_id=None):
        super().__init__(parent)
        self.ws_server = ws_server
        self.client_id = client_id
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
        self.check_updates_btn = QPushButton("Шаг 1: Обновить списки пакетов (apt update)")
        self.check_updates_btn.clicked.connect(self.check_for_updates)
        self.list_upgradable_btn = QPushButton("Шаг 2: Показать обновляемые пакеты")
        self.list_upgradable_btn.clicked.connect(self.list_upgradable_packages)
        self.install_selected_btn = QPushButton("⬆️ Установить выбранные")
        self.install_selected_btn.clicked.connect(self.install_selected_updates)
        self.install_all_btn = QPushButton("🚀 Обновить всю систему")
        self.install_all_btn.clicked.connect(self.install_all_updates)
        pkg_actions_layout.addWidget(self.check_updates_btn)
        pkg_actions_layout.addWidget(self.list_upgradable_btn)
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
        
        main_layout.setStretch(1, 1) # pkg_group

    def load_repositories(self):
        asyncio.run_coroutine_threadsafe(
            self.ws_server.send_command(self.client_id, "apt:get_repos"),
            self.ws_server.loop
        )

    def save_repository(self):
        current_file = self.repo_selector.currentText()
        if not current_file:
            QMessageBox.warning(self, "⚠️ Ошибка", "Не выбран файл репозитория.")
            return
        
        content = self.repo_content_edit.toPlainText()
        content_b64 = base64.b64encode(content.encode('utf-8')).decode('ascii')
        
        asyncio.run_coroutine_threadsafe(
            self.ws_server.send_command(self.client_id, f"apt:save_repo:{current_file}:{content_b64}"),
            self.ws_server.loop
        )

    def check_for_updates(self):
        self.updates_table.setRowCount(0)
        QMessageBox.information(self, "ℹ️ Информация", "Запущена команда 'apt-get update'.\nОтследить ее выполнение можно в терминале.\nПосле ее завершения, нажмите 'Шаг 2'.")
        self.run_in_terminal_requested.emit("sudo apt-get update")

    def list_upgradable_packages(self):
        self.updates_table.setRowCount(0)
        asyncio.run_coroutine_threadsafe(
            self.ws_server.send_command(self.client_id, "apt:list_upgradable"),
            self.ws_server.loop
        )

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

        self.run_in_terminal_requested.emit(f"sudo apt-get install --only-upgrade -y {' '.join(selected_packages)}")
        QMessageBox.information(self, "ℹ️ Информация", "Запущена установка выбранных пакетов.\nПосле завершения, нажмите 'Шаг 2', чтобы обновить список.")

    def install_all_updates(self):
        reply = QMessageBox.question(self, "❓ Подтверждение", "Вы уверены, что хотите обновить всю систему?", QMessageBox.Yes | QMessageBox.No)
        if reply == QMessageBox.Yes:
            self.run_in_terminal_requested.emit("sudo apt-get upgrade -y --enable-upgrade")
            QMessageBox.information(self, "ℹ️ Информация", "Запущено полное обновление системы.\nПосле завершения, нажмите 'Шаг 2', чтобы обновить список.")

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