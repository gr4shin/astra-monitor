# astra_monitor_server/main.py

import sys
import os
import logging
from PyQt5.QtWidgets import QApplication

# Добавляем корневую папку проекта в sys.path, чтобы разрешить абсолютные импорты.
# Это позволяет запускать main.py напрямую из его папки.
if __package__ is None or __package__ == '':
    project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
    if project_root not in sys.path:
        sys.path.insert(0, project_root)

from astra_monitor_server.gui.main_window import ServerGUI

# Этот файл является точкой входа для запуска серверного приложения.
# Чтобы запустить его, выполните следующую команду из корневого каталога проекта:
# python -m astra_monitor_server.main

def main() -> None:
    """Главная функция для запуска приложения сервера."""
    # Настройка базового логирования в консоль и файл
    log_formatter = logging.Formatter('%(asctime)s - %(levelname)s - [%(name)s] - %(message)s')
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)

    # Обработчик для вывода в консоль
    stream_handler = logging.StreamHandler(sys.stdout)
    stream_handler.setFormatter(log_formatter)
    root_logger.addHandler(stream_handler)

    # Обработчик для вывода в файл
    file_handler = logging.FileHandler("astra_monitor_server.log", mode='w', encoding='utf-8')
    file_handler.setFormatter(log_formatter)
    root_logger.addHandler(file_handler)

    app = QApplication(sys.argv)
    # Запрещаем приложению завершаться при закрытии последнего окна,
    # чтобы оно могло оставаться в системном трее.
    app.setQuitOnLastWindowClosed(False)
    window = ServerGUI()
    window.show()
    logging.info("Серверное приложение запущено.")
    sys.exit(app.exec_())

if __name__ == "__main__":
    main()
    