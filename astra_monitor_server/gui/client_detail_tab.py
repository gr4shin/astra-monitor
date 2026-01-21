# astra_monitor_server/gui/client_detail_tab.py

import json
import asyncio
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGroupBox, QListWidget,
    QStackedWidget, QPushButton, QSplitter, QTextEdit,
    QLineEdit, QLabel, QMessageBox, QSpinBox, QCheckBox, QFormLayout)
from PyQt5.QtCore import Qt, pyqtSignal, QTimer
from PyQt5.QtGui import QFont, QIntValidator, QFontMetrics

# Импортируем локальные модули
from .dialogs.custom_command_dialog import CustomCommandDialog
from .widgets.system_info_widget import SystemInfoWidget
from .widgets.system_info_full_widget import SystemInfoFullWidget
from .widgets.file_manager_widget import FileManagerWidget
from .widgets.update_manager_widget import UpdateManagerWidget
from .widgets.screenshot_widget import ScreenshotWidget
from .widgets.metrics_history_widget import MetricsHistoryWidget
from .terminal_emulator import TerminalEmulator


class TerminalView(QTextEdit):
    resized = pyqtSignal(int, int)
    keyPressed = pyqtSignal(object)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        metrics = QFontMetrics(self.font())
        cols = max(1, self.viewport().width() // metrics.horizontalAdvance("M"))
        rows = max(1, self.viewport().height() // metrics.height())
        self.resized.emit(rows, cols)

    def keyPressEvent(self, event):
        self.keyPressed.emit(event)
        if event.isAccepted():
            return
        super().keyPressEvent(event)

class ClientDetailTab(QWidget):
    log_message_requested = pyqtSignal(str)
    custom_commands_updated = pyqtSignal()
    settings_changed = pyqtSignal(dict)
    meta_changed = pyqtSignal(dict)
    append_to_log_signal = pyqtSignal(str)

    def __init__(self, parent=None, ws_server=None, client_id=None, client_data=None, custom_commands=None, client_settings=None, main_window=None):
        super().__init__(parent)
        self.ws_server = ws_server
        self.custom_commands = custom_commands if custom_commands is not None else {}
        self.client_id = client_id
        self.client_data = client_data or {}
        self.client_settings = client_settings or {}
        self.client_tags = self.client_data.get('tags', [])
        self.main_window = main_window # Store main window reference
        self.interactive_session = False
        self.terminal_emulator = TerminalEmulator()
        self._terminal_rows = None
        self._terminal_cols = None
        self._terminal_buffer = ""
        self._terminal_flush_timer = QTimer(self)
        self._terminal_flush_timer.setInterval(50)
        self._terminal_flush_timer.timeout.connect(self._flush_terminal_buffer)
        self._terminal_focus_mode = False
        self.init_ui()
        self.log_message_requested.connect(self.log_to_client)
        self.append_to_log_signal.connect(self.log_to_client)
        
    def init_ui(self):
        layout = QHBoxLayout(self)
        
        # Левая панель - меню
        left_widget = QWidget()
        left_layout = QVBoxLayout(left_widget)
        left_layout.setContentsMargins(0, 0, 0, 0)
        
        menu_group = QGroupBox("Меню")
        menu_layout = QVBoxLayout(menu_group)
        
        self.menu_list = QListWidget()
        self.content_stack = QStackedWidget()

        # Create a map of menu item names to their corresponding widgets and visibility
        self.menu_map = {
            "Информация о системе": (SystemInfoFullWidget(), True),
            "Файловый менеджер": (FileManagerWidget(ws_server=self.ws_server, client_id=self.client_id, log_callback=self.append_to_log_signal.emit, main_window=self.main_window), True),
            "Команды": (self._create_commands_widget(), True),
            "Управление обновлениями": (UpdateManagerWidget(ws_server=self.ws_server, client_id=self.client_id), True),
            "Экран клиента": (ScreenshotWidget(ws_server=self.ws_server, client_id=self.client_id, log_callback=self.append_to_log_signal.emit, settings_screenshot=self.client_data.get('settings')), True),
            "История метрик": (MetricsHistoryWidget(), True),
            "Журнал клиента": (QTextEdit(), True),
            "Настройки": (self._create_settings_widget(), True),
        }

        self.visible_menu_items = []
        for name, (widget, is_visible) in self.menu_map.items():
            if is_visible:
                self.menu_list.addItem(name)
                self.content_stack.addWidget(widget)
                self.visible_menu_items.append(name)

        # Assign widgets to instance variables for later access
        self.system_info_full_widget = self.menu_map["Информация о системе"][0]
        self.file_manager_widget = self.menu_map["Файловый менеджер"][0]
        self.commands_widget = self.menu_map["Команды"][0]
        self.update_manager_widget = self.menu_map["Управление обновлениями"][0]
        self.screenshot_widget = self.menu_map["Экран клиента"][0]
        self.metrics_history_widget = self.menu_map["История метрик"][0]
        self.client_log_output = self.menu_map["Журнал клиента"][0]
        self.client_log_output.setReadOnly(True)

        self.menu_list.currentRowChanged.connect(self.change_content)
        menu_layout.addWidget(self.menu_list)
        left_layout.addWidget(menu_group)
        
        layout.addWidget(left_widget, 1)
        layout.addWidget(self.content_stack, 3)
        
        self.menu_list.setCurrentRow(0)

    def _create_commands_widget(self):
        commands_widget = QWidget()
        commands_layout = QVBoxLayout(commands_widget)
        
        splitter = QSplitter(Qt.Vertical)

        # Верхняя часть: Списки команд
        command_lists_widget = QWidget()
        command_lists_layout = QHBoxLayout(command_lists_widget)

        # ... Быстрые команды
        quick_commands_group = QGroupBox("Быстрые команды")
        quick_commands_layout = QVBoxLayout(quick_commands_group)

        quick_commands = [("Очистить кэш", "sudo apt autoremove -y && sudo apt clean"), ("Проверить диски", "df -h"), ("Сетевые соединения", "ss -tuln"), ("Активные пользователи", "who"), ("Uptime системы", "uptime")]

        for name, cmd in quick_commands:
            btn = QPushButton(name)
            btn.clicked.connect(lambda ch, c=cmd, n=name: self.execute_command(c, n))
            quick_commands_layout.addWidget(btn)
        quick_commands_layout.addStretch()
        command_lists_layout.addWidget(quick_commands_group)

        # ... Пользовательские команды
        custom_commands_group = QGroupBox("Пользовательские команды")
        custom_commands_layout = QVBoxLayout(custom_commands_group)
        self.custom_commands_list = QListWidget()
        self.custom_commands_list.addItems(self.custom_commands.keys())
        self.custom_commands_list.itemDoubleClicked.connect(self.edit_custom_command)
        
        custom_buttons_layout = QHBoxLayout()
        
        exec_btn = QPushButton("Выполнить")
        exec_btn.setToolTip("Выполнить выбранную команду")
        exec_btn.clicked.connect(self.execute_selected_custom_command)
        
        add_btn = QPushButton("Добавить")
        add_btn.setToolTip("Добавить новую команду")
        add_btn.clicked.connect(self.add_custom_command)
        
        edit_btn = QPushButton("Редактировать")
        edit_btn.setToolTip("Редактировать выбранную команду")
        edit_btn.clicked.connect(self.edit_custom_command)
        
        remove_btn = QPushButton("Удалить")
        remove_btn.setToolTip("Удалить выбранную команду")
        remove_btn.clicked.connect(self.remove_custom_command)
        
        custom_buttons_layout.addWidget(exec_btn)
        custom_buttons_layout.addWidget(add_btn)
        custom_buttons_layout.addWidget(edit_btn)
        custom_buttons_layout.addWidget(remove_btn)
        custom_buttons_layout.addStretch()
        
        custom_commands_layout.addWidget(self.custom_commands_list)
        custom_commands_layout.addLayout(custom_buttons_layout)
        command_lists_layout.addWidget(custom_commands_group)

        splitter.addWidget(command_lists_widget)

        # Нижняя часть: Терминал
        terminal_group = QGroupBox("Терминал")
        terminal_layout = QVBoxLayout(terminal_group)
        self.terminal_output = TerminalView()
        self.terminal_output.setReadOnly(True)
        self.terminal_output.setFont(QFont("Monospace", 10))
        self.terminal_output.setStyleSheet("background-color: #2b2b2b; color: #f0f0f0;")
        self.terminal_output.setLineWrapMode(QTextEdit.NoWrap)
        self.terminal_output.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOn)
        self.terminal_output.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOn)
        self.terminal_output.resized.connect(self._on_terminal_resize)
        self.terminal_output.keyPressed.connect(self._handle_terminal_key)
        
        self.terminal_input = QLineEdit()
        self.terminal_input.setFont(QFont("Monospace", 10))
        self.terminal_input.returnPressed.connect(self.execute_terminal_command)

        self.focus_hint = QLabel("Фокус в терминале: F2, выход — Esc")
        self.focus_hint.setAlignment(Qt.AlignRight)
        self.focus_hint.setStyleSheet("color: #b0b0b0;")
        self.focus_hint.setVisible(False)

        terminal_layout.addWidget(self.terminal_output)
        terminal_layout.addWidget(self.focus_hint)
        terminal_layout.addWidget(self.terminal_input)
        splitter.addWidget(terminal_group)
        splitter.setSizes([250, 400])

        commands_layout.addWidget(splitter)
        return commands_widget

    def _create_settings_widget(self):
        settings_widget = QWidget()
        settings_layout = QVBoxLayout(settings_widget)
        
        # Скриншоты
        screenshot_group = QGroupBox("Настройки экрана")
        screenshot_layout = QFormLayout(screenshot_group)

        self.screenshot_quality = QSpinBox()
        self.screenshot_quality.setRange(1, 100)
        self.screenshot_quality.setValue(self.client_settings.get('screenshot', {}).get('quality', 85))
        self.screenshot_quality.setSuffix("%")
        screenshot_layout.addRow("Качество скриншота:", self.screenshot_quality)

        self.screenshot_delay = QSpinBox()
        self.screenshot_delay.setRange(1, 60)
        self.screenshot_delay.setValue(self.client_settings.get('screenshot', {}).get('refresh_delay', 5))
        self.screenshot_delay.setSuffix(" сек")
        screenshot_layout.addRow("Задержка автообновления:", self.screenshot_delay)

        self.screenshot_auto = QCheckBox("Автоматическое обновление экрана")
        self.screenshot_auto.setChecked(self.client_settings.get('screenshot', {}).get('enabled', True))
        screenshot_layout.addRow(self.screenshot_auto)

        # Группа настроек мониторинга
        monitoring_group = QGroupBox("Настройки мониторинга")
        monitoring_layout = QFormLayout(monitoring_group)

        self.monitoring_interval = QLineEdit(str(self.client_settings.get('monitoring_interval', 10)))
        self.monitoring_interval.setValidator(QIntValidator(1, 3600))
        monitoring_layout.addRow("Интервал обновления (сек):", self.monitoring_interval)

        self.auto_refresh = QCheckBox("Автоматическое обновление")
        self.auto_refresh.setChecked(self.client_settings.get('auto_refresh', True))
        monitoring_layout.addRow(self.auto_refresh)

        # Группа настроек соединения
        connection_group = QGroupBox("Настройки соединения")
        connection_layout = QFormLayout(connection_group)

        self.reconnect_delay = QLineEdit(str(self.client_settings.get('reconnect_delay', 5)))
        self.reconnect_delay.setValidator(QIntValidator(1, 60))
        connection_layout.addRow("Задержка переподключения (сек):", self.reconnect_delay)

        self.max_reconnect_attempts = QLineEdit(str(self.client_settings.get('max_reconnect_attempts', 10)))
        self.max_reconnect_attempts.setValidator(QIntValidator(1, 100))
        connection_layout.addRow("Макс. попыток переподключения:", self.max_reconnect_attempts)

        # Группа настроек безопасности
        security_group = QGroupBox("Настройки безопасности")
        security_layout = QFormLayout(security_group)

        self.enable_encryption = QCheckBox("Включить шифрование")
        self.enable_encryption.setChecked(self.client_settings.get('enable_encryption', False))
        security_layout.addRow(self.enable_encryption)

        self.log_sensitive_commands = QCheckBox("Логировать чувствительные команды")
        self.log_sensitive_commands.setChecked(self.client_settings.get('log_sensitive_commands', True))
        security_layout.addRow(self.log_sensitive_commands)

        # Группа настроек примечаний
        info_group = QGroupBox("Примечание")
        info_layout = QFormLayout(info_group)
        self.info_text = QLineEdit(str(self.client_settings.get('info_text', '')))        
        info_layout.addRow("Примечание:", self.info_text)
        self.tags_input = QLineEdit(", ".join(self.client_tags))
        self.tags_input.setPlaceholderText("например: бухгалтерия, 1 этаж")
        info_layout.addRow("Теги:", self.tags_input)


        # Кнопки применения настроек
        settings_buttons_layout = QHBoxLayout()
        save_settings_btn = QPushButton("Сохранить настройки")
        save_settings_btn.clicked.connect(self.save_settings)
        reset_settings_btn = QPushButton("Сбросить настройки")
        reset_settings_btn.clicked.connect(self.reset_settings)

        settings_buttons_layout.addWidget(save_settings_btn)
        settings_buttons_layout.addWidget(reset_settings_btn)

        settings_layout.addWidget(screenshot_group)
        settings_layout.addWidget(monitoring_group)
        settings_layout.addWidget(connection_group)
        settings_layout.addWidget(security_group)
        settings_layout.addWidget(info_group)
        settings_layout.addLayout(settings_buttons_layout)
        settings_layout.addStretch()
        return settings_widget

    def get_full_system_info(self):
        """Запрос полной информации о системе"""
        future = asyncio.run_coroutine_threadsafe(
            self.ws_server.send_command(self.client_id, "get_full_system_info"), 
            self.ws_server.loop
        )
        self.log_message_requested.emit("ℹ️ Запрос полной информации о системе...")
    
    def change_content(self, index):
        """Изменение отображаемого контента"""
        self.content_stack.setCurrentIndex(index)
        selected_item_name = self.visible_menu_items[index]

        if selected_item_name == "Информация о системе":
            self.get_full_system_info()
        elif selected_item_name == "Команды":
            self.start_interactive_session_if_not_running()
        
    def update_client_data(self, new_data):
        """Обновление данных клиента"""
        self.client_data.update(new_data)

    def update_history(self, history):
        if hasattr(self, "metrics_history_widget"):
            self.metrics_history_widget.update_history(history)

    def log_to_client(self, message):
        """Добавление сообщения в лог клиента."""
        self.client_log_output.append(message)
        self.client_log_output.verticalScrollBar().setValue(self.client_log_output.verticalScrollBar().maximum())

    def append_to_terminal(self, text):
        """Добавление текста в окно терминала"""
        self._terminal_buffer += text
        if not self._terminal_flush_timer.isActive():
            self._terminal_flush_timer.start()

    def _flush_terminal_buffer(self):
        if not self._terminal_buffer:
            self._terminal_flush_timer.stop()
            return

        scrollbar = self.terminal_output.verticalScrollBar()
        at_bottom = scrollbar.value() >= scrollbar.maximum() - 2

        self.terminal_emulator.feed(self._terminal_buffer)
        self._terminal_buffer = ""
        self.terminal_output.setUpdatesEnabled(False)
        self.terminal_output.setHtml(self.terminal_emulator.render_html())
        self.terminal_output.setUpdatesEnabled(True)
        if at_bottom:
            scrollbar.setValue(scrollbar.maximum())

    def _toggle_terminal_focus(self):
        self._terminal_focus_mode = not self._terminal_focus_mode
        self.terminal_output.setFocus()
        self.focus_hint.setVisible(self._terminal_focus_mode)
        if self._terminal_focus_mode:
            self.log_message_requested.emit("Фокус терминала включен. Выход: Esc.")
        else:
            self.log_message_requested.emit("Фокус терминала выключен.")

    def _exit_terminal_focus(self):
        if self._terminal_focus_mode:
            self._terminal_focus_mode = False
            self.focus_hint.setVisible(False)
            self.terminal_input.setFocus()
            self.log_message_requested.emit("Фокус терминала выключен.")

    def _handle_terminal_key(self, event):
        if event.key() == Qt.Key_F2:
            self._toggle_terminal_focus()
            event.accept()
            return

        if not self._terminal_focus_mode:
            return

        if event.key() == Qt.Key_Escape:
            self._exit_terminal_focus()
            event.accept()
            return

        seq = self._qt_key_to_ansi(event)
        if seq:
            asyncio.run_coroutine_threadsafe(
                self.ws_server.send_command(self.client_id, f"interactive:input:{seq}"),
                self.ws_server.loop
            )
        event.accept()

    def _qt_key_to_ansi(self, event):
        key = event.key()
        modifiers = event.modifiers()

        if key == Qt.Key_Return or key == Qt.Key_Enter:
            return "\n"
        if key == Qt.Key_Backspace:
            return "\x7f"
        if key == Qt.Key_Tab:
            return "\t"

        arrows = {
            Qt.Key_Up: "\x1b[A",
            Qt.Key_Down: "\x1b[B",
            Qt.Key_Right: "\x1b[C",
            Qt.Key_Left: "\x1b[D",
            Qt.Key_Home: "\x1b[H",
            Qt.Key_End: "\x1b[F",
            Qt.Key_PageUp: "\x1b[5~",
            Qt.Key_PageDown: "\x1b[6~",
            Qt.Key_Insert: "\x1b[2~",
            Qt.Key_Delete: "\x1b[3~",
        }
        if key in arrows:
            return arrows[key]

        if modifiers & Qt.ControlModifier:
            if Qt.Key_A <= key <= Qt.Key_Z:
                return chr(key - Qt.Key_A + 1)
            if key == Qt.Key_Space:
                return "\x00"
            return None

        text = event.text()
        if text:
            return text
        return None

    def handle_interactive_output(self, data):
        self.append_to_terminal(data)

    def handle_interactive_started(self):
        self.interactive_session = True
        self.terminal_emulator.reset()
        self.terminal_output.setHtml(self.terminal_emulator.render_html())
        self._sync_terminal_size()
        self.log_message_requested.emit(f"Интерактивная сессия запущена.")

    def handle_interactive_stopped(self):
        self.interactive_session = False
        self.log_message_requested.emit(f"Интерактивная сессия завершена.")
        self.append_to_terminal("\n[+] Сессия завершена. Для старта новой сессии, введите команду.\n")

    def _on_terminal_resize(self, rows, cols):
        if rows <= 0 or cols <= 0:
            return
        if rows == self._terminal_rows and cols == self._terminal_cols:
            return
        self._terminal_rows = rows
        self._terminal_cols = cols
        self.terminal_emulator.resize(rows, cols)
        if self.interactive_session:
            asyncio.run_coroutine_threadsafe(
                self.ws_server.send_command(self.client_id, f"interactive:resize:{rows},{cols}"),
                self.ws_server.loop
            )

    def _sync_terminal_size(self):
        metrics = QFontMetrics(self.terminal_output.font())
        cols = max(1, self.terminal_output.viewport().width() // metrics.horizontalAdvance("M"))
        rows = max(1, self.terminal_output.viewport().height() // metrics.height())
        self._on_terminal_resize(rows, cols)

    def update_prompt(self, path): # DEPRECATED
        pass

    def run_command_in_terminal(self, command):
        """Runs a command in the interactive terminal session without switching tabs."""
        if self.interactive_session:
            self.execute_command(command)
        else:
            # Start the session if not running, then execute the command
            self.start_interactive_session_if_not_running(initial_command=command)

    def execute_command(self, command, name=""):
        """Общий метод для выполнения команд"""
        if self.interactive_session:
            future = asyncio.run_coroutine_threadsafe(
                self.ws_server.send_command(self.client_id, f"interactive:input:{command}\n"), 
                self.ws_server.loop
            )
        else:
            # Fallback for non-interactive quick commands
            self.append_to_terminal(f"> {command}\n")
            future = asyncio.run_coroutine_threadsafe(
                self.ws_server.send_command(self.client_id, f"execute:{command}"), 
                self.ws_server.loop
            )
        
        client_name = self.client_data.get('hostname', self.client_id)
        log_name = name if name else command
        self.log_message_requested.emit(f"▶️ Выполнение команды на {client_name}: {log_name}")
    
    def execute_selected_custom_command(self):
        """Выполнение выбранной кастомной команды"""
        current_item = self.custom_commands_list.currentItem()
        if current_item:
            command_name = current_item.text()
            self.execute_custom_command(command_name)

    def execute_custom_command(self, command_name):
        """Выполнение кастомной команды по имени"""
        command = self.custom_commands.get(command_name, "")
        if command:
            self.execute_command(command, command_name)

    def execute_terminal_command(self):
        """Выполнение команды из строки ввода терминала"""
        command = self.terminal_input.text().strip()
        if command:
            if self.interactive_session:
                self.execute_command(command)
            else:
                # If session is not active, the first command will start it.
                self.start_interactive_session_if_not_running(command)
            
            self.terminal_input.clear()

    def start_interactive_session_if_not_running(self, initial_command=None):
        if not self.interactive_session:
            shell_cmd = "bash -i"
            self.log_message_requested.emit(f"Запуск интерактивной сессии ({shell_cmd})...")
            asyncio.run_coroutine_threadsafe(
                self.ws_server.send_command(self.client_id, f"interactive:start:{shell_cmd}"),
                self.ws_server.loop
            )
            if initial_command:
                # Wait a bit for the session to start before sending the first command
                asyncio.get_event_loop().call_later(0.5, lambda: self.execute_command(initial_command))

    def stop_interactive_session(self):
        """Stops the interactive terminal session.""" 
        if self.interactive_session:
            self.log_message_requested.emit("Остановка интерактивной сессии...")
            asyncio.run_coroutine_threadsafe(
                self.ws_server.send_command(self.client_id, "interactive:stop"),
                self.ws_server.loop
            )
    
    def add_custom_command(self):
        """Добавление новой кастомной команды"""
        dialog = CustomCommandDialog(self)
        if dialog.exec_():
            command_data = dialog.get_command_data()
            name = command_data['name']
            command = command_data['command']
            
            if name and command:
                if name in self.custom_commands:
                    QMessageBox.warning(self, "⚠️ Внимание", f"Команда с именем '{name}' уже существует.")
                    return
                
                self.custom_commands[name] = command
                self.custom_commands_list.addItem(name)
                self.log_message_requested.emit(f"✅ Добавлена новая команда: {name}")
                self.custom_commands_updated.emit()

    def edit_custom_command(self):
        """Редактирование выбранной кастомной команды"""
        current_item = self.custom_commands_list.currentItem()
        if not current_item:
            QMessageBox.warning(self, "⚠️ Внимание", "Пожалуйста, выберите команду для редактирования.")
            return

        old_name = current_item.text()
        command = self.custom_commands.get(old_name, "")
        
        dialog = CustomCommandDialog(self, command_data={"name": old_name, "command": command})
        
        if dialog.exec_():
            new_data = dialog.get_command_data()
            new_name = new_data['name']
            new_command = new_data['command']

            if not new_name or not new_command:
                QMessageBox.warning(self, "⚠️ Внимание", "Название и команда не могут быть пустыми.")
                return

            if old_name == new_name:
                self.custom_commands[old_name] = new_command
                self.log_message_requested.emit(f"✏️ Команда '{old_name}' обновлена.")
            else:
                if new_name in self.custom_commands:
                    QMessageBox.warning(self, "⚠️ Внимание", f"Команда с именем '{new_name}' уже существует.")
                    return
                del self.custom_commands[old_name]
                self.custom_commands[new_name] = new_command
                current_item.setText(new_name)
                self.log_message_requested.emit(f"✏️ Команда '{old_name}' переименована в '{new_name}'.")
            
            self.custom_commands_updated.emit()

    def remove_custom_command(self):
        """Удаление кастомной команды"""
        current_item = self.custom_commands_list.currentItem()
        if current_item:
            command_name = current_item.text()
            reply = QMessageBox.question(
                self, 
                "❓ Подтверждение", 
                f"Вы уверены, что хотите удалить команду '{command_name}'?",
                QMessageBox.Yes | QMessageBox.No
            )
            if reply == QMessageBox.Yes:
                if command_name in self.custom_commands:
                    del self.custom_commands[command_name]
                    self.custom_commands_list.takeItem(self.custom_commands_list.row(current_item))
                    self.log_message_requested.emit(f"[Удаление] Команда удалена: {command_name}")
                    self.custom_commands_updated.emit()
    
    def save_settings(self):
        """Сохранение настроек"""
        try:
            settings = {
                'monitoring_interval': int(self.monitoring_interval.text()),
                'auto_refresh': self.auto_refresh.isChecked(),
                'reconnect_delay': int(self.reconnect_delay.text()),
                'max_reconnect_attempts': int(self.max_reconnect_attempts.text()),
                'enable_encryption': self.enable_encryption.isChecked(),
                'log_sensitive_commands': self.log_sensitive_commands.isChecked(),
                'info_text': str(self.info_text.text()),
                'screenshot': {
                    'quality': self.screenshot_quality.value(),
                    'refresh_delay': self.screenshot_delay.value(),
                    'enabled': self.screenshot_auto.isChecked()
                }
            }
            
            future = asyncio.run_coroutine_threadsafe(
                self.ws_server.send_command(self.client_id, f"apply_settings:{json.dumps(settings)}"), 
                self.ws_server.loop
            )
            
            self.settings_changed.emit(settings)
            tags = [t.strip() for t in self.tags_input.text().split(",") if t.strip()]
            self.meta_changed.emit({"tags": tags})
            client_name = self.client_data.get('hostname', self.client_id)
            self.log_message_requested.emit(f"Настройки отправлены клиенту {client_name}. Полностью применяться после переподключения клиента.")
            QMessageBox.information(self, "✅ Успех", "Настройки успешно отправлены клиенту! Полностью применяться после переподключения клиента.")
            
        except ValueError:
            QMessageBox.warning(self, "⚠️ Ошибка", "Проверьте правильность введенных значений")
    
    def reset_settings(self):
        """Сброс настроек к значениям по умолчанию"""
        reply = QMessageBox.question(
            self, 
            "❓ Подтверждение", 
            "Вы уверены, что хотите сбросить настройки к значениям по умолчанию?",
            QMessageBox.Yes | QMessageBox.No
        )
        
        if reply == QMessageBox.Yes:
            self.monitoring_interval.setText("10")
            self.auto_refresh.setChecked(True)
            self.reconnect_delay.setText("5")
            self.max_reconnect_attempts.setText("10")
            self.enable_encryption.setChecked(False)
            self.log_sensitive_commands.setChecked(True)
            self.info_text.setText("")
            self.screenshot_quality.setValue(85)
            self.screenshot_delay.setValue(5)
            self.screenshot_auto.setChecked(True)
            client_name = self.client_data.get('hostname', self.client_id)
            self.log_message_requested.emit(f"[Сброс] Настройки клиента {client_name}")
