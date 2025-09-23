# astra_monitor_server/config_loader.py

import json
import sys
import os
import logging

# Конфигурация по умолчанию
DEFAULT_CONFIG = {
    "SERVER_HOST": "0.0.0.0",
    "SERVER_PORT": 8765,
    "AUTH_TOKEN": "astra_secret_token_2025",
    "SETTINGS_FILE": "settings.json"
}

def get_base_path():
    """Получает базовый путь, для собранного или обычного приложения."""
    if getattr(sys, 'frozen', False) and hasattr(sys, '_MEIPASS'):
        return sys._MEIPASS
    return os.path.dirname(os.path.abspath(__file__))

def load_config():
    """
    Загружает конфигурацию с приоритетом:
    1. Внешний config (server_config.json рядом с исполняемым файлом)
    2. Встроенный в исполняемый файл config (server_config.json)
    3. Значения по умолчанию
    """
    config = DEFAULT_CONFIG.copy()
    
    # Путь для встроенного файла конфигурации
    bundled_config_path = os.path.join(get_base_path(), 'server_config.json')

    # Путь для внешнего файла конфигурации (рядом с .exe)
    external_config_dir = os.path.dirname(sys.executable) if getattr(sys, 'frozen', False) else '.'
    external_config_path = os.path.join(external_config_dir, 'server_config.json')

    # Сначала загружаем встроенную конфигурацию
    if os.path.exists(bundled_config_path):
        try:
            with open(bundled_config_path, 'r', encoding='utf-8') as f:
                config.update(json.load(f))
            logging.info(f"Загружена встроенная конфигурация из {bundled_config_path}")
        except (json.JSONDecodeError, IOError) as e:
            logging.warning(f"Не удалось загрузить встроенную конфигурацию: {e}")

    # Затем загружаем внешнюю, она переопределит встроенную
    if os.path.exists(external_config_path):
        try:
            with open(external_config_path, 'r', encoding='utf-8') as f:
                config.update(json.load(f))
            logging.info(f"Загружена внешняя конфигурация из {external_config_path}, переопределяя предыдущие настройки.")
        except (json.JSONDecodeError, IOError) as e:
            logging.warning(f"Не удалось загрузить внешнюю конфигурацию: {e}")

    config['SETTINGS_FILE'] = os.path.join(external_config_dir, 'settings.json')
    return config

# Загружаем конфигурацию один раз при импорте модуля
APP_CONFIG = load_config()