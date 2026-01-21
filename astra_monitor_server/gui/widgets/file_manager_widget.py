# astra_monitor_server/gui/widgets/file_manager_widget.py

import os
import posixpath
import base64
import asyncio
import logging

from PyQt5.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QFrame,
                             QTreeWidget, QTreeWidgetItem, QMessageBox, QFileDialog, QInputDialog, QLineEdit,
                             QProgressDialog, QMenu)
from PyQt5.QtCore import Qt, pyqtSignal

class FileManagerWidget(QWidget):
    # Сигналы для безопасного обновления GUI из другого потока
    upload_progress = pyqtSignal(int, str)
    upload_finished = pyqtSignal(bool, str)

    def __init__(self, parent=None, ws_server=None, client_id=None, log_callback=None, main_window=None):
        super().__init__(parent)
        self.ws_server = ws_server
        self.client_id = client_id
        self.current_path = "/"
        self.back_stack = []
        self.forward_stack = []
        self.log_callback = log_callback or (lambda msg: print(msg))
        self.main_window = main_window # Store main window reference
        self.upload_task = None
        self.init_ui()
        
    def init_ui(self):
        layout = QVBoxLayout(self)
        
        # Путь и кнопки навигации
        path_layout = QHBoxLayout()
        self.back_button = QPushButton("Назад")
        self.back_button.clicked.connect(self.go_back)
        self.forward_button = QPushButton("Вперед")
        self.forward_button.clicked.connect(self.go_forward)
        self.home_button = QPushButton("Домой")
        self.home_button.clicked.connect(self.go_home)
        self.up_button = QPushButton("Вверх")
        self.up_button.clicked.connect(self.go_up)
        self.refresh_button = QPushButton("Обновить")
        self.refresh_button.clicked.connect(self.refresh_files)
        self.path_input = QLineEdit(self.current_path)
        self.path_input.returnPressed.connect(self.navigate_to_path)

        path_layout.addWidget(self.back_button)
        path_layout.addWidget(self.forward_button)
        path_layout.addWidget(self.home_button)
        path_layout.addWidget(self.up_button)
        path_layout.addWidget(self.refresh_button)
        path_layout.addWidget(QLabel("Путь:"))
        path_layout.addWidget(self.path_input, 1)
        
        # Список файлов
        files_frame = QFrame()
        files_layout = QVBoxLayout(files_frame)
        search_layout = QHBoxLayout()
        search_layout.addWidget(QLabel("Поиск:"))
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Имя файла или папки...")
        self.search_input.textChanged.connect(self.filter_files)
        search_layout.addWidget(self.search_input, 1)
        files_layout.addLayout(search_layout)

        self.files_list = QTreeWidget()
        self.files_list.setHeaderLabels(["Имя", "Тип", "Размер"])
        self.files_list.setColumnWidth(0, 360)
        self.files_list.setSortingEnabled(True)
        self.files_list.setSelectionMode(self.files_list.ExtendedSelection)
        self.files_list.itemDoubleClicked.connect(self.on_item_double_clicked)
        self.files_list.setContextMenuPolicy(Qt.CustomContextMenu)
        self.files_list.customContextMenuRequested.connect(self.show_file_context_menu)
        files_layout.addWidget(self.files_list)
        
        layout.addLayout(path_layout)
        layout.addWidget(files_frame)
        
        self.load_files()
        
    def load_files(self):
        """Загрузка списка файлов"""
        self.files_list.clear()
        
        # Запрашиваем список файлов у клиента
        command = f"list_files:{self.current_path}"
        future = asyncio.run_coroutine_threadsafe(
            self.ws_server.send_command(self.client_id, command), 
            self.ws_server.loop
        )
        
    def update_files_list(self, files_data):
        """Обновление списка файлов"""
        self.files_list.clear()
        
        if 'files' in files_data:
            # Добавляем папки
            for file_info in files_data['files']:
                if file_info['type'] == 'directory':
                    name = file_info['name']
                    item = QTreeWidgetItem([name, "Папка", ""])
                    path = posixpath.join(self.current_path, name)
                    item.setData(0, Qt.UserRole, {"type": "directory", "path": path})
                    self.files_list.addTopLevelItem(item)
            
            # Добавляем файлы
            for file_info in files_data['files']:
                if file_info['type'] == 'file':
                    name, size = file_info['name'], self.format_size(file_info['size'])
                    item = QTreeWidgetItem([name, "Файл", size])
                    path = posixpath.join(self.current_path, name)
                    item.setData(0, Qt.UserRole, {
                        "type": "file", 
                        "path": path, 
                        "size": file_info['size']
                    })
                    self.files_list.addTopLevelItem(item)
        self.filter_files()

    def format_size(self, size_bytes):
        """Форматирование размера файла"""
        if size_bytes == 0:
            return "0B"
        size_names = ["B", "KB", "MB", "GB"]
        i = 0
        while size_bytes >= 1024 and i < len(size_names)-1:
            size_bytes /= 1024.0
            i += 1
        return f"{size_bytes:.1f}{size_names[i]}"
    
    def on_item_double_clicked(self, item):
        """Обработка двойного клика по файлу/папке"""
        file_info = item.data(0, Qt.UserRole)
        if file_info['type'] == 'directory':
            self._set_path(file_info['path'])
    
    def go_up(self):
        """Переход на уровень выше"""
        if self.current_path != "/":
            self._set_path(posixpath.dirname(self.current_path))
    
    def go_home(self):
        """Переход в домашнюю директорию"""
        self._set_path("/")

    def go_back(self):
        if not self.back_stack:
            return
        self.forward_stack.append(self.current_path)
        path = self.back_stack.pop()
        self._set_path(path, push_history=False)

    def go_forward(self):
        if not self.forward_stack:
            return
        self.back_stack.append(self.current_path)
        path = self.forward_stack.pop()
        self._set_path(path, push_history=False)
    
    def refresh_files(self):
        """Обновление списка файлов"""
        self.load_files()

    def navigate_to_path(self):
        path = self.path_input.text().strip()
        if not path:
            return
        self._set_path(path)

    def _set_path(self, path, push_history=True):
        if not path.startswith("/"):
            path = posixpath.join(self.current_path, path)
        path = posixpath.normpath(path)
        if push_history and path != self.current_path:
            self.back_stack.append(self.current_path)
            self.forward_stack.clear()
        self.current_path = path
        self.path_input.setText(self.current_path)
        self.load_files()

    def filter_files(self):
        query = (self.search_input.text() or "").lower().strip()
        for i in range(self.files_list.topLevelItemCount()):
            item = self.files_list.topLevelItem(i)
            name = (item.text(0) or "").lower()
            item.setHidden(bool(query) and query not in name)
    
    def download_file(self, item=None):
        """Скачивание выбранного файла"""
        current_item = item or self.files_list.currentItem()
        if not current_item:
            QMessageBox.warning(self, "Ошибка", "Выберите файл для скачивания")
            return
            
        file_info = current_item.data(0, Qt.UserRole)
        if not file_info:
            QMessageBox.warning(self, "Ошибка", "Не удалось получить информацию о файле.")
            return
        if file_info['type'] != 'file':
            QMessageBox.warning(self, "Ошибка", "Можно скачивать только файлы")
            return

        remote_path = file_info['path']
        filename = os.path.basename(remote_path)

        # 1. Сначала спрашиваем у пользователя, куда сохранить файл
        local_save_path, _ = QFileDialog.getSaveFileName(self, "Сохранить файл", filename)
        if not local_save_path:
            self.log_callback(f"Скачивание файла '{filename}' отменено пользователем.")
            return

        # 2. Регистрируем ожидаемое скачивание в главном окне
        if self.main_window:
            self.main_window.register_pending_download(self.client_id, remote_path, local_save_path)
        else:
            QMessageBox.critical(self, "Критическая ошибка", "Не удалось получить доступ к главному окну.")
            return

        # 3. Отправляем команду клиенту на начало передачи
        if self.main_window:
            chunk_size_bytes = self.main_window.websocket_chunk_size_mb * 1024 * 1024
        else:
            chunk_size_bytes = 4 * 1024 * 1024 # Fallback
        command = f"download_file_chunked:{chunk_size_bytes}:{remote_path}"
        asyncio.run_coroutine_threadsafe(
            self.ws_server.send_command(self.client_id, command), 
            self.ws_server.loop
        )
        self.log_callback(f"[Скачивание] Запрос на скачивание файла '{filename}' отправлен.")

    def upload_file(self):
        """Загрузка файла на клиента (с поддержкой чанков)"""
        file_path, _ = QFileDialog.getOpenFileName(self, "Выберите файл для загрузки")
        if not file_path:
            return

        filename = os.path.basename(file_path)
        file_size = os.path.getsize(file_path)

        progress_dialog = QProgressDialog(f"Подготовка к загрузке '{filename}'...", "Отмена", 0, 100, self)
        progress_dialog.setWindowModality(Qt.WindowModal)
        progress_dialog.setWindowTitle("Загрузка файла на клиент")
        progress_dialog.setAutoClose(False)
        progress_dialog.setAutoReset(False)

        # Подключаем сигналы
        self.upload_progress.connect(progress_dialog.setValue)
        self.upload_progress.connect(lambda _, text: progress_dialog.setLabelText(text))
        self.upload_finished.connect(lambda success, msg: self.on_upload_finished(success, msg, progress_dialog))
        progress_dialog.canceled.connect(self.cancel_upload)

        progress_dialog.show()

        # Запускаем корутину в фоновом потоке asyncio
        self.upload_task = asyncio.run_coroutine_threadsafe(
            self._send_file_in_chunks_async(file_path, filename, file_size),
            self.ws_server.loop
        )

    def on_upload_finished(self, success, message, dialog):
        """Слот для обработки завершения загрузки."""
        dialog.close()
        self.log_callback(message)
        if not success and "отменена" not in message:
             QMessageBox.critical(self, "Ошибка загрузки", message)

    def cancel_upload(self):
        """Слот для отмены загрузки."""
        if self.upload_task and not self.upload_task.done():
            # Потокобезопасно отменяем задачу в цикле asyncio
            self.ws_server.loop.call_soon_threadsafe(self.upload_task.cancel)
        self.log_callback("[Загрузка] Отмена загрузки файла...")

    async def _send_file_in_chunks_async(self, file_path, filename, file_size):
        """Асинхронная корутина для отправки файла по частям."""
        remote_path = posixpath.join(self.current_path, filename)
        try:
            self.log_callback(f"[Загрузка] Начало загрузки файла '{filename}' ({file_size / 1024 / 1024:.2f} MB).")

            # 1. Отправляем команду начала
            start_cmd = f"upload_file_start:{remote_path}:{file_size}"
            await self.ws_server.send_command(self.client_id, start_cmd)

            # 2. Отправляем файл по частям
            if self.main_window:
                CHUNK_SIZE = self.main_window.websocket_chunk_size_mb * 1024 * 1024
            else:
                CHUNK_SIZE = 4 * 1024 * 1024 # Fallback

            with open(file_path, 'rb') as f:
                sent_bytes = 0
                while chunk := f.read(CHUNK_SIZE):
                    chunk_b64 = base64.b64encode(chunk).decode('ascii')
                    chunk_cmd = f"upload_file_chunk:{chunk_b64}"
                    await self.ws_server.send_command(self.client_id, chunk_cmd)
                    sent_bytes += len(chunk)

                    # Обновляем прогресс через сигнал
                    if file_size > 0:
                        percent = int(sent_bytes * 100 / file_size)
                        progress_text = (f"Загрузка файла '{filename}'...\n"
                                         f"{sent_bytes / 1024 / 1024:.2f} MB / {file_size / 1024 / 1024:.2f} MB")
                        self.upload_progress.emit(percent, progress_text)
                    await asyncio.sleep(0) # Уступаем управление

            # 3. Отправляем команду завершения
            await self.ws_server.send_command(self.client_id, "upload_file_end")
            self.upload_finished.emit(True, f"Загрузка файла '{filename}' завершена.")

        except asyncio.CancelledError:
            await self.ws_server.send_command(self.client_id, f"cancel_upload:{remote_path}")
            self.upload_finished.emit(False, "Загрузка отменена пользователем.")
            raise # Важно для корректной отмены задачи
        except Exception as e:
            error_message = f"Ошибка при загрузке файла: {e}"
            self.upload_finished.emit(False, error_message)

    def rename_file(self, item=None):
        """Переименование файла или папки"""
        current_item = item or self.files_list.currentItem()
        if not current_item:
            QMessageBox.warning(self, "Ошибка", "Выберите файл или папку для переименования")
            return

        file_info = current_item.data(0, Qt.UserRole)
        if not file_info:
            QMessageBox.warning(self, "Ошибка", "Не удалось получить информацию о файле.")
            return
        old_name = os.path.basename(file_info['path'])

        new_name, ok = QInputDialog.getText(
            self, "Переименовать", "Введите новое имя:",
            QLineEdit.Normal, old_name
        )

        if ok and new_name and new_name != old_name:
            old_path = file_info['path']
            new_path = posixpath.join(posixpath.dirname(old_path), new_name)
            
            command = f"rename_path:{old_path}:{new_path}"
            future = asyncio.run_coroutine_threadsafe(
                self.ws_server.send_command(self.client_id, command),
                self.ws_server.loop
            )
            self.log_callback(f"Отправлен запрос на переименование '{old_name}' в '{new_name}'.")

    def delete_file(self, item=None):
        """Удаление выбранного файла/папки"""
        current_item = item or self.files_list.currentItem()
        if not current_item:
            QMessageBox.warning(self, "Ошибка", "Выберите файл или папку для удаления")
            return
            
        file_info = current_item.data(0, Qt.UserRole)
        if not file_info:
            QMessageBox.warning(self, "Ошибка", "Не удалось получить информацию о файле.")
            return
        name = os.path.basename(file_info['path'])
        
        reply = QMessageBox.question(
            self, "Подтверждение", 
            f"Вы уверены, что хотите удалить {'папку' if file_info['type'] == 'directory' else 'файл'} '{name}'?",
            QMessageBox.Yes | QMessageBox.No
        )
        
        if reply == QMessageBox.Yes:
            command = f"delete:{file_info['path']}"
            future = asyncio.run_coroutine_threadsafe(
                self.ws_server.send_command(self.client_id, command), 
                self.ws_server.loop
            )
    
    def create_folder(self):
        """Создание новой папки"""
        folder_name, ok = QInputDialog.getText(
            self, "Новая папка", "Введите название папки:"
        )
        
        if ok and folder_name:
            new_path = posixpath.join(self.current_path, folder_name)
            command = f"create_folder:{new_path}"
            future = asyncio.run_coroutine_threadsafe(
                self.ws_server.send_command(self.client_id, command), 
                self.ws_server.loop
            )

    def show_file_context_menu(self, position):
        menu = QMenu()
        selected_item = self.files_list.itemAt(position)

        # Actions that are always available
        refresh_action = menu.addAction("Обновить")
        upload_action = menu.addAction("Загрузить")
        new_folder_action = menu.addAction("Новая папка")
        menu.addSeparator()

        # Actions that depend on selection
        download_action = menu.addAction("Скачать")
        rename_action = menu.addAction("Переименовать")
        delete_action = menu.addAction("Удалить")

        if selected_item:
            file_info = selected_item.data(0, Qt.UserRole)
            if file_info:
                is_file = file_info.get('type') == 'file'
                download_action.setEnabled(is_file)
            else:
                download_action.setEnabled(False)
                rename_action.setEnabled(False)
                delete_action.setEnabled(False)
        else:
            download_action.setEnabled(False)
            rename_action.setEnabled(False)
            delete_action.setEnabled(False)

        # Connect signals to slots
        refresh_action.triggered.connect(self.refresh_files)
        upload_action.triggered.connect(self.upload_file)
        new_folder_action.triggered.connect(self.create_folder)
        download_action.triggered.connect(lambda: self.download_file(selected_item))
        rename_action.triggered.connect(lambda: self.rename_file(selected_item))
        delete_action.triggered.connect(lambda: self.delete_file(selected_item))

        menu.exec_(self.files_list.mapToGlobal(position))
