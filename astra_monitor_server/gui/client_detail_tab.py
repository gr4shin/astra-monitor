# astra_monitor_server/gui/client_detail_tab.py

import json
import asyncio
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGroupBox, QListWidget,
    QStackedWidget, QPushButton, QSplitter, QTextEdit,
    QLineEdit, QLabel, QMessageBox, QSpinBox, QCheckBox, QFormLayout)
from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtGui import QFont, QIntValidator

# Импортируем локальные модули
from .dialogs.custom_command_dialog import CustomCommandDialog
from .widgets.system_info_widget import SystemInfoWidget
from .widgets.system_info_full_widget import SystemInfoFullWidget
from .widgets.file_manager_widget import FileManagerWidget
from .widgets.update_manager_widget import UpdateManagerWidget
from .widgets.screenshot_widget import ScreenshotWidget

class ClientDetailTab(QWidget):
    log_message_requested = pyqtSignal(str)
    custom_commands_updated = pyqtSignal()
    settings_changed = pyqtSignal(dict)
    append_to_log_signal = pyqtSignal(str)

    def __init__(self, parent=None, ws_server=None, client_id=None, client_data=None, custom_commands=None, client_settings=None, main_window=None):
        super().__init__(parent)
        self.ws_server = ws_server
        self.custom_commands = custom_commands if custom_commands is not None else {}
        self.client_id = client_id
        self.client_data = client_data or {}
        self.os_type = self.client_data.get('os_type', 'Linux') # Default to Linux for safety
        self.client_settings = client_settings or {}
        self.main_window = main_window # Store main window reference
        self.init_ui()
        self.log_message_requested.connect(self.log_to_client)
        self.append_to_log_signal.connect(self.log_to_client)
        
    def init_ui(self):
        layout = QHBoxLayout(self)
        
        # Левая панель - меню
        left_widget = QWidget()
        left_layout = QVBoxLayout(left_widget)
        left_layout.setContentsMargins(0, 0, 0, 0)
        
        menu_group = QGroupBox("🗂️ Меню")
        menu_layout = QVBoxLayout(menu_group)
        
        self.menu_list = QListWidget()
        self.content_stack = QStackedWidget()

        # Create a map of menu item names to their corresponding widgets and visibility
        self.menu_map = {
            "ℹ️Информация о системе": (SystemInfoFullWidget(), True),
            "📂 Файловый менеджер": (FileManagerWidget(ws_server=self.ws_server, client_id=self.client_id, log_callback=self.append_to_log_signal.emit, main_window=self.main_window), True),
            "⌨️ Команды": (self._create_commands_widget(), True),
            "🔄 Управление обновлениями": (UpdateManagerWidget(ws_server=self.ws_server, client_id=self.client_id), self.os_type == 'Linux'),
            "🖼️ Экран клиента": (ScreenshotWidget(ws_server=self.ws_server, client_id=self.client_id, log_callback=self.append_to_log_signal.emit, settings_screenshot=self.client_data.get('settings')), True),
            "📜 Журнал клиента": (QTextEdit(), True),
            "⚙️ Настройки": (self._create_settings_widget(), True),
        }

        self.visible_menu_items = []
        for name, (widget, is_visible) in self.menu_map.items():
            if is_visible:
                self.menu_list.addItem(name)
                self.content_stack.addWidget(widget)
                self.visible_menu_items.append(name)

        # Assign widgets to instance variables for later access
        self.system_info_full_widget = self.menu_map["ℹ️Информация о системе"][0]
        self.file_manager_widget = self.menu_map["📂 Файловый менеджер"][0]
        # The commands widget is created and assigned in the map, but we need to access its children
        commands_widget = self.menu_map["⌨️ Команды"][0]
        if self.os_type == 'Linux':
            self.update_manager_widget = self.menu_map["🔄 Управление обновлениями"][0]
        self.screenshot_widget = self.menu_map["🖼️ Экран клиента"][0]
        self.client_log_output = self.menu_map["📜 Журнал клиента"][0]
        self.client_log_output.setReadOnly(True)

        self.menu_list.currentRowChanged.connect(self.change_content)
        menu_layout.addWidget(self.menu_list)
        left_layout.addWidget(menu_group)
        
        layout.addWidget(left_widget, 1)
        layout.addWidget(self.content_stack, 3)
        
        # Показываем системную инфу по умолчанию
        self.menu_list.setCurrentRow(0)
        self.terminal_output.append("🖥️ Добро пожаловать в терминал клиента!\n")

    def _create_commands_widget(self):
        commands_widget = QWidget()
        commands_layout = QVBoxLayout(commands_widget)
        
        splitter = QSplitter(Qt.Vertical)

        # Верхняя часть: Списки команд
        command_lists_widget = QWidget()
        command_lists_layout = QHBoxLayout(command_lists_widget)

        # ... Быстрые команды
        quick_commands_group = QGroupBox("⚡ Быстрые команды")
        quick_commands_layout = QVBoxLayout(quick_commands_group)

        if self.os_type == 'Linux':
            quick_commands = [("🧹 Очистить кэш", "sudo apt autoremove -y && sudo apt clean"), ("📊 Проверить диски", "df -h"), ("🌐 Сетевые соединения", "ss -tuln"), ("👥 Активные пользователи", "who"), ("⏰ Uptime системы", "uptime")]
        else: # Windows
            quick_commands = [("📦 Показать обновления", "winget upgrade"), ("⬆️ Обновить все пакеты", "winget upgrade --all --accept-source-agreements"), ("📊 Проверить диски", "wmic logicaldisk get size,freespace,caption"), ("🌐 Сетевые соединения", "netstat -an"), ("👥 Активные пользователи", "query user"), ("⏰ Uptime системы", "systeminfo | find \"System Boot Time\"")]

        for name, cmd in quick_commands:
            btn = QPushButton(name)
            btn.clicked.connect(lambda ch, c=cmd, n=name: self.execute_command(c, n))
            quick_commands_layout.addWidget(btn)
        quick_commands_layout.addStretch()
        command_lists_layout.addWidget(quick_commands_group)

        # ... Пользовательские команды
        custom_commands_group = QGroupBox("📝 Пользовательские команды")
        custom_commands_layout = QVBoxLayout(custom_commands_group)
        self.custom_commands_list = QListWidget()
        self.custom_commands_list.addItems(self.custom_commands.keys())
        self.custom_commands_list.itemDoubleClicked.connect(self.edit_custom_command)
        
        custom_buttons_layout = QHBoxLayout()
        
        exec_btn = QPushButton("▶️ Выполнить")
        exec_btn.setToolTip("Выполнить выбранную команду")
        exec_btn.clicked.connect(self.execute_selected_custom_command)
        
        add_btn = QPushButton("➕ Добавить")
        add_btn.setToolTip("Добавить новую команду")
        add_btn.clicked.connect(self.add_custom_command)
        
        edit_btn = QPushButton("✏️ Редактировать")
        edit_btn.setToolTip("Редактировать выбранную команду")
        edit_btn.clicked.connect(self.edit_custom_command)
        
        remove_btn = QPushButton("➖ Удалить")
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
        terminal_group = QGroupBox("⌨️ Терминал")
        terminal_layout = QVBoxLayout(terminal_group)
        self.terminal_output = QTextEdit()
        self.terminal_output.setReadOnly(True)
        self.terminal_output.setFont(QFont("Monospace", 10))
        self.terminal_output.setStyleSheet("background-color: #2b2b2b; color: #f0f0f0;")
        
        input_layout = QHBoxLayout()
        self.prompt_label = QLabel(f"{self.client_data.get('hostname', 'client')}:~>")
        self.terminal_input = QLineEdit()
        self.terminal_input.setFont(QFont("Monospace", 10))
        self.terminal_input.returnPressed.connect(self.execute_terminal_command)
        input_layout.addWidget(self.prompt_label)
        input_layout.addWidget(self.terminal_input)

        terminal_layout.addWidget(self.terminal_output)
        terminal_layout.addLayout(input_layout)
        splitter.addWidget(terminal_group)
        splitter.setSizes([250, 400])

        commands_layout.addWidget(splitter)
        return commands_widget

    def _create_settings_widget(self):
        settings_widget = QWidget()
        settings_layout = QVBoxLayout(settings_widget)
        
        # Скриншоты
        screenshot_group = QGroupBox("🖼️ Настройки экрана")
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
        monitoring_group = QGroupBox("📊 Настройки мониторинга")
        monitoring_layout = QFormLayout(monitoring_group)

        self.monitoring_interval = QLineEdit(str(self.client_settings.get('monitoring_interval', 10)))
        self.monitoring_interval.setValidator(QIntValidator(1, 3600))
        monitoring_layout.addRow("Интервал обновления (сек):", self.monitoring_interval)

        self.auto_refresh = QCheckBox("Автоматическое обновление")
        self.auto_refresh.setChecked(self.client_settings.get('auto_refresh', True))
        monitoring_layout.addRow(self.auto_refresh)

        # Группа настроек соединения
        connection_group = QGroupBox("🔌 Настройки соединения")
        connection_layout = QFormLayout(connection_group)

        self.reconnect_delay = QLineEdit(str(self.client_settings.get('reconnect_delay', 5)))
        self.reconnect_delay.setValidator(QIntValidator(1, 60))
        connection_layout.addRow("Задержка переподключения (сек):", self.reconnect_delay)

        self.max_reconnect_attempts = QLineEdit(str(self.client_settings.get('max_reconnect_attempts', 10)))
        self.max_reconnect_attempts.setValidator(QIntValidator(1, 100))
        connection_layout.addRow("Макс. попыток переподключения:", self.max_reconnect_attempts)

        # Группа настроек безопасности
        security_group = QGroupBox("🔒 Настройки безопасности")
        security_layout = QFormLayout(security_group)

        self.enable_encryption = QCheckBox("Включить шифрование")
        self.enable_encryption.setChecked(self.client_settings.get('enable_encryption', False))
        security_layout.addRow(self.enable_encryption)

        self.log_sensitive_commands = QCheckBox("Логировать чувствительные команды")
        self.log_sensitive_commands.setChecked(self.client_settings.get('log_sensitive_commands', True))
        security_layout.addRow(self.log_sensitive_commands)

        # Кнопки применения настроек
        settings_buttons_layout = QHBoxLayout()
        save_settings_btn = QPushButton("💾 Сохранить настройки")
        save_settings_btn.clicked.connect(self.save_settings)
        reset_settings_btn = QPushButton("🗑️ Сбросить настройки")
        reset_settings_btn.clicked.connect(self.reset_settings)

        settings_buttons_layout.addWidget(save_settings_btn)
        settings_buttons_layout.addWidget(reset_settings_btn)

        # Добавляем все группы в layout
        settings_layout.addWidget(screenshot_group)
        settings_layout.addWidget(monitoring_group)
        settings_layout.addWidget(connection_group)
        settings_layout.addWidget(security_group)
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
        # Если выбрана информация о системе, запрашиваем данные
        if index == 0:
            self.get_full_system_info()
        
    def update_client_data(self, new_data):
        """Обновление данных клиента"""
        self.client_data.update(new_data)
        # Данные для виджета полной информации обновляются через main_window
        # при получении сообщения 'full_system_info'

    def log_to_client(self, message):
        """Добавление сообщения в лог клиента."""
        self.client_log_output.append(message)
        self.client_log_output.verticalScrollBar().setValue(self.client_log_output.verticalScrollBar().maximum())

    def append_to_terminal(self, text, is_command=False):
        """Добавление текста в окно терминала"""
        if is_command:
            prompt = self.prompt_label.text()
            self.terminal_output.append(f"<font color='#87d7ff'>{prompt}</font> <font color='white'>{text}</font>")
        else:
            # Экранируем HTML-сущности и заменяем переносы строк
            text = text.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
            text = text.replace('\n', '<br>')
            self.terminal_output.append(f"<font color='#d3d3d3'>{text}</font>")
        self.terminal_output.verticalScrollBar().setValue(self.terminal_output.verticalScrollBar().maximum())

    def update_prompt(self, path):
        """Обновление промпта терминала с новым путем"""
        hostname = self.client_data.get('hostname', 'client')
        self.prompt_label.setText(f"{hostname}:{path}>")

    def execute_command(self, command, name=""):
        """Общий метод для выполнения команд"""
        self.append_to_terminal(command, is_command=True)
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
            self.execute_command(command)
            self.terminal_input.clear()
    
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

            # Если имя не изменилось, просто обновляем команду
            if old_name == new_name:
                self.custom_commands[old_name] = new_command
                self.log_message_requested.emit(f"✏️ Команда '{old_name}' обновлена.")
            else:
                # Если имя изменилось, нужно проверить, не занято ли новое имя
                if new_name in self.custom_commands:
                    QMessageBox.warning(self, "⚠️ Внимание", f"Команда с именем '{new_name}' уже существует.")
                    return
                # Удаляем старую команду и добавляем новую
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
                    self.log_message_requested.emit(f"🗑️ Удалена команда: {command_name}")
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
                'screenshot': {
                    'quality': self.screenshot_quality.value(),
                    'refresh_delay': self.screenshot_delay.value(),
                    'enabled': self.screenshot_auto.isChecked()
                }
            }
            
            # Отправляем настройки клиенту
            future = asyncio.run_coroutine_threadsafe(
                self.ws_server.send_command(self.client_id, f"apply_settings:{json.dumps(settings)}"), 
                self.ws_server.loop
            )
            
            # Сообщаем главному окну об изменении, чтобы оно сохранило их
            self.settings_changed.emit(settings)
            client_name = self.client_data.get('hostname', self.client_id)
            self.log_message_requested.emit(f"⚙️ Настройки отправлены клиенту {client_name}. Полностью применяться после переподключения клиента.")
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
            self.screenshot_quality.setValue(85)
            self.screenshot_delay.setValue(5)
            self.screenshot_auto.setChecked(True)
            client_name = self.client_data.get('hostname', self.client_id)
            self.log_message_requested.emit(f"🗑️ Настройки сброшены к значениям по умолчанию для клиента {client_name}")
