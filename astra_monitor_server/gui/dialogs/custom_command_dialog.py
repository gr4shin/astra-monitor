# astra_monitor_server/gui/dialogs/custom_command_dialog.py

from PyQt5.QtWidgets import QDialog, QFormLayout, QLineEdit, QDialogButtonBox

class CustomCommandDialog(QDialog):
    def __init__(self, parent=None, command_data=None):
        super().__init__(parent)
        self.is_edit = command_data is not None
        title = "Редактировать кастомную команду" if self.is_edit else "Добавить кастомную команду"
        self.setWindowTitle(title)
        self.setModal(True)
        self.resize(500, 150)
        self.init_ui()

        if self.is_edit and command_data:
            self.name_input.setText(command_data.get("name", ""))
            self.command_input.setText(command_data.get("command", ""))
        
    def init_ui(self):
        layout = QFormLayout(self)
        
        self.name_input = QLineEdit()
        self.name_input.setPlaceholderText("Название команды (например: Проверка диска)")
        layout.addRow("Название:", self.name_input)
        
        self.command_input = QLineEdit()
        self.command_input.setPlaceholderText("Команда для выполнения (например: df -h)")
        layout.addRow("Команда:", self.command_input)
        
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addRow(buttons)
        
    def get_command_data(self):
        return {
            "name": self.name_input.text().strip(),
            "command": self.command_input.text().strip()
        }