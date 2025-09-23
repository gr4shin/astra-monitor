# astra_monitor_server/gui/dialogs/command_dialog.py

from PyQt5.QtWidgets import QDialog, QFormLayout, QLineEdit, QDialogButtonBox

class CommandDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Выполнить команду")
        self.setModal(True)
        self.resize(500, 100)
        self.init_ui()
        
    def init_ui(self):
        layout = QFormLayout(self)
        
        self.command_input = QLineEdit()
        self.command_input.setPlaceholderText("Введите команду для выполнения (например: ls -la, df -h)")
        layout.addRow("Команда:", self.command_input)
        
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addRow(buttons)
        
    def get_command(self):
        return self.command_input.text().strip()