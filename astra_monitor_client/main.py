import logging
import sys
import platform
import traceback
import os 

# --- Версия клиента ---
CLIENT_VERSION = "2.10.08a"
# --------------------

def setup_logging():
    log_formatter = logging.Formatter('%(asctime)s - %(levelname)s - [%(name)s] - %(message)s')
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)

    # Очищаем все предыдущие обработчики
    for handler in root_logger.handlers[:]:
        root_logger.removeHandler(handler)

    # Логирование в stderr
    stream_handler = logging.StreamHandler(sys.stderr)
    stream_handler.setFormatter(log_formatter)
    root_logger.addHandler(stream_handler)

    # Дополнительное логирование в файл
    log_file = "astra-monitor-client.log"
    try:
        # Попытка записи в текущую директорию
        file_handler = logging.FileHandler(log_file, mode='w', encoding='utf-8')
    except (IOError, PermissionError):
        # Если не получилось, пробуем в /tmp или %TEMP%
        temp_dir = os.path.join(os.path.expanduser("~"), "AppData", "Local", "Temp") if platform.system() == "Windows" else "/tmp"
        log_file = os.path.join(temp_dir, log_file)
        file_handler = logging.FileHandler(log_file, mode='w', encoding='utf-8')
        
    file_handler.setFormatter(log_formatter)
    root_logger.addHandler(file_handler)
    root_logger.info(f"Logging to file: {log_file}")

# --- Main Entry Point ---
def main() -> None:
    """Главная функция для запуска приложения."""
    setup_logging()
    try:
        logging.info("=" * 50)
        logging.info("Starting Astra Monitor Client in console mode")
        logging.info("Version: %s", CLIENT_VERSION)
        logging.info("OS: %s", platform.system())
        logging.info("=" * 50)

        from astra_monitor_client.client.websocket_client import SystemMonitorClient
        client = SystemMonitorClient(version=CLIENT_VERSION)
        client.run()

    except Exception as e:
        logging.critical("A critical error occurred during client execution:")
        logging.critical(traceback.format_exc())
        sys.exit(1)

if __name__ == "__main__":
    main()