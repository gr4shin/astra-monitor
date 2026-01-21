#!/usr/bin/env python3
import sys
import os
import subprocess

def _ensure_venv():
    in_venv = getattr(sys, "base_prefix", sys.prefix) != sys.prefix
    venv_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".venv")
    venv_python = os.path.join(venv_dir, "bin", "python")

    if in_venv:
        return None

    if not os.path.exists(venv_python):
        print("Виртуальное окружение не найдено, создаю .venv...")
        subprocess.check_call([sys.executable, "-m", "venv", venv_dir])

    os.execv(venv_python, [venv_python] + sys.argv)


def _ensure_pyqt5():
    try:
        import PyQt5  # noqa: F401
        return
    except ImportError:
        print("PyQt5 не найден, устанавливаю...")
        try:
            subprocess.check_call([sys.executable, "-m", "pip", "install", "PyQt5"])
        except subprocess.CalledProcessError:
            print("Не удалось установить PyQt5. Установите вручную и повторите запуск.")
            sys.exit(1)
        os.execv(sys.executable, [sys.executable] + sys.argv)


_ensure_venv()
_ensure_pyqt5()

from PyQt5.QtWidgets import (
    QApplication,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QGroupBox,
    QLabel,
    QLineEdit,
    QPushButton,
    QTextEdit,
    QCheckBox,
    QMessageBox,
)
from PyQt5.QtCore import QProcess, Qt


class BuildGUI(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Astra Monitor Builder")
        self.resize(900, 600)
        self._queue = []
        self._current_process = None
        self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout(self)

        config_group = QGroupBox("Параметры сборки")
        config_layout = QVBoxLayout(config_group)

        row_host = QHBoxLayout()
        row_host.addWidget(QLabel("IP/host сервера (bind):"))
        self.server_host = QLineEdit("0.0.0.0")
        row_host.addWidget(self.server_host)
        config_layout.addLayout(row_host)

        row_client_host = QHBoxLayout()
        row_client_host.addWidget(QLabel("IP/host для клиентов:"))
        self.client_host = QLineEdit()
        row_client_host.addWidget(self.client_host)
        config_layout.addLayout(row_client_host)

        row_port = QHBoxLayout()
        row_port.addWidget(QLabel("Порт сервера:"))
        self.server_port = QLineEdit("8765")
        row_port.addWidget(self.server_port)
        config_layout.addLayout(row_port)

        row_token = QHBoxLayout()
        row_token.addWidget(QLabel("Токен:"))
        self.auth_token = QLineEdit()
        self.auth_token.setEchoMode(QLineEdit.Password)
        row_token.addWidget(self.auth_token)
        config_layout.addLayout(row_token)

        options_group = QGroupBox("Что собирать")
        options_layout = QVBoxLayout(options_group)
        self.build_server = QCheckBox("Сервер")
        self.build_client = QCheckBox("Клиент")
        self.build_deb = QCheckBox("Собирать .deb для клиента")
        self.build_server.setChecked(True)
        self.build_client.setChecked(True)
        self.build_deb.setChecked(True)
        options_layout.addWidget(self.build_server)
        options_layout.addWidget(self.build_client)
        options_layout.addWidget(self.build_deb)

        buttons_row = QHBoxLayout()
        self.start_btn = QPushButton("Запустить сборку")
        self.start_btn.clicked.connect(self._start_build)
        self.stop_btn = QPushButton("Остановить")
        self.stop_btn.clicked.connect(self._stop_build)
        self.stop_btn.setEnabled(False)
        buttons_row.addWidget(self.start_btn)
        buttons_row.addWidget(self.stop_btn)
        buttons_row.addStretch()

        self.log_output = QTextEdit()
        self.log_output.setReadOnly(True)
        self.log_output.setLineWrapMode(QTextEdit.NoWrap)

        layout.addWidget(config_group)
        layout.addWidget(options_group)
        layout.addLayout(buttons_row)
        layout.addWidget(QLabel("Лог сборки:"))
        layout.addWidget(self.log_output)

    def _start_build(self):
        if not self.build_server.isChecked() and not self.build_client.isChecked():
            QMessageBox.warning(self, "Ошибка", "Выберите хотя бы одну цель сборки.")
            return

        host = self.server_host.text().strip()
        client_host = self.client_host.text().strip()
        port = self.server_port.text().strip()
        token = self.auth_token.text().strip()

        if not host or not client_host or not port or not token:
            QMessageBox.warning(self, "Ошибка", "Все поля (host bind/host для клиента/port/token) должны быть заполнены.")
            return

        if not port.isdigit():
            QMessageBox.warning(self, "Ошибка", "Порт должен быть числом.")
            return

        self._queue.clear()
        if self.build_server.isChecked():
            self._queue.append([
                sys.executable,
                "build_server.py",
                f"--server-host={host}",
                f"--server-port={port}",
                f"--auth-token={token}",
            ])
        if self.build_client.isChecked():
            deb_flag = "--deb" if self.build_deb.isChecked() else "--no-deb"
            self._queue.append([
                sys.executable,
                "build_client.py",
                f"--server-host={client_host}",
                f"--server-port={port}",
                f"--auth-token={token}",
                deb_flag,
            ])

        self.log_output.clear()
        self.start_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)
        self._run_next()

    def _run_next(self):
        if not self._queue:
            self._append_log("✅ Сборка завершена.")
            self.start_btn.setEnabled(True)
            self.stop_btn.setEnabled(False)
            return

        cmd = self._queue.pop(0)
        self._append_log(f"\n▶️ Запуск: {' '.join(cmd)}\n")
        self._current_process = QProcess(self)
        self._current_process.setWorkingDirectory(os.path.dirname(os.path.abspath(__file__)))
        self._current_process.readyReadStandardOutput.connect(self._read_stdout)
        self._current_process.readyReadStandardError.connect(self._read_stderr)
        self._current_process.finished.connect(self._process_finished)
        self._current_process.start(cmd[0], cmd[1:])

    def _process_finished(self, code, _status):
        if code != 0:
            self._append_log(f"\n❌ Процесс завершился с кодом {code}\n")
            self.start_btn.setEnabled(True)
            self.stop_btn.setEnabled(False)
            self._queue.clear()
            return
        self._run_next()

    def _read_stdout(self):
        data = self._current_process.readAllStandardOutput().data().decode("utf-8", errors="replace")
        self._append_log(data)

    def _read_stderr(self):
        data = self._current_process.readAllStandardError().data().decode("utf-8", errors="replace")
        self._append_log(data)

    def _append_log(self, text):
        self.log_output.moveCursor(self.log_output.textCursor().End)
        self.log_output.insertPlainText(text)
        self.log_output.verticalScrollBar().setValue(self.log_output.verticalScrollBar().maximum())

    def _stop_build(self):
        if self._current_process and self._current_process.state() != QProcess.NotRunning:
            self._current_process.kill()
            self._append_log("\n⛔ Сборка остановлена пользователем.\n")
        self._queue.clear()
        self.start_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)


def main():
    app = QApplication(sys.argv)
    window = BuildGUI()
    window.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
