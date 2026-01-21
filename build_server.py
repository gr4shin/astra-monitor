#!/usr/bin/env python3
"""
Сборка автономного исполняемого файла сервера без зависимостей
"""

import argparse
import subprocess
import sys
import os
import shutil
import json

def create_config_file(data: dict, path: str):
    """Создает файл конфигурации JSON."""
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4, ensure_ascii=False)

def install_pyinstaller():
    """Установка PyInstaller"""
    print("📦 Установка PyInstaller...")
    subprocess.check_call([sys.executable, "-m", "pip", "install", "pyinstaller"])

def build_standalone(build_config=None):
    """Сборка автономного исполняемого файла"""
    print("🔨 Сборка исполняемого файла сервера...")
    
    # Используем python -m PyInstaller для кросс-платформенной сборки из venv
    pyinstaller_cmd = [sys.executable, "-m", "PyInstaller"]
    
    options = [
        "--name=astra-monitor-server",
        "--onefile",
        "--windowed", # Для GUI-приложения
        # Скрытые импорты для PyQt5 и других библиотек
        "--hidden-import=PyQt5.sip",
        "--hidden-import=PyQt5.QtWidgets",
        "--hidden-import=PyQt5.QtGui",
        "--hidden-import=PyQt5.QtCore",
        "--hidden-import=websockets",
        "--hidden-import=pkg_resources.py2_warn",
        "--clean",
        "--noconfirm",
    ]

    # Добавляем иконку для исполняемого файла, если она есть.
    # PyInstaller может сам конвертировать PNG в ICO/ICNS, если установлен Pillow.
    icon_path = "icon.ico"
    if os.path.exists(icon_path):
        print(f"🖼️  Найдена иконка: {icon_path}. Добавляем в сборку.")
        options.append(f"--icon={icon_path}")
    else:
        print("⚠️  Файл иконки 'icon.ico' не найден. Исполняемый файл будет без иконки.")
    
    temp_assets_dir = "build_server_assets"
    try:
        if build_config:
            os.makedirs(temp_assets_dir, exist_ok=True)
            config_file_path = os.path.join(temp_assets_dir, "server_config.json")
            create_config_file(build_config, config_file_path)
            
            # PyInstaller использует ':' как разделитель на всех платформах
            # Добавляем файл конфигурации в корень бандла
            options.append(f"--add-data={config_file_path}:.")
            print(f"⚙️ Внедрение конфигурации: {build_config}")

        # Точка входа для сервера
        entry_point = "astra_monitor_server/main.py"
        full_command = pyinstaller_cmd + options + [entry_point]
        
        print("Полная команда сборки:", " ".join(full_command))
        subprocess.check_call(full_command)

    finally:
        # Очищаем временную директорию с ассетами
        if build_config and os.path.exists(temp_assets_dir):
            shutil.rmtree(temp_assets_dir)
            print("🗑️ Временная директория с конфигурацией удалена.")

    print("[OK] Сборка сервера завершена!")
    executable_path = "./dist/astra-monitor-server"
    if os.path.exists(executable_path):
        print(f"📁 Исполняемый файл: {executable_path}")
        print(f"📊 Размер файла: {os.path.getsize(executable_path) / 1024 / 1024:.1f} MB")
    else:
        print("[ERROR] Исполняемый файл не найден в ./dist/")


def install_dependencies():
    """Установка всех необходимых зависимостей"""
    print("📦 Установка зависимостей сервера...")
    dependencies = ["websockets", "PyQt5", "Pillow"]
    
    for dep in dependencies:
        try:
            __import__(dep.split('==')[0])
            print(f"[OK] {dep} уже установлен")
        except ImportError:
            print(f"📦 Устанавливаем {dep}...")
            subprocess.check_call([sys.executable, "-m", "pip", "install", dep])

def main(argv=None):
    """Основная функция"""
    parser = argparse.ArgumentParser(description="Astra Monitor Server Builder")
    parser.add_argument("--server-host")
    parser.add_argument("--server-port")
    parser.add_argument("--auth-token")
    args = parser.parse_args(argv)

    print("🚀 Сборка автономного сервера мониторинга")
    print("=" * 50)
    
    try:
        install_dependencies()
        try:
            subprocess.check_call([sys.executable, "-m", "PyInstaller", "--version"],
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            print("[OK] PyInstaller уже установлен")
        except (subprocess.CalledProcessError, FileNotFoundError):
            install_pyinstaller()
        
        print("\n" + "-"*20)
        print("Внедрение конфигурации в сервер (обязательно)")
        
        if args.server_host and args.server_port and args.auth_token:
            server_ip = args.server_host
            server_port_str = args.server_port
            auth_token = args.auth_token
        else:
            while not (server_ip := input("Введите IP-адрес для прослушивания (например, 0.0.0.0): ").strip()):
                print("❌ IP-адрес не может быть пустым.")
            
            while not (server_port_str := input("Введите порт для прослушивания (например, 8765): ").strip()):
                print("❌ Порт не может быть пустым.")

            while not (auth_token := input("Введите токен аутентификации: ").strip()):
                print("❌ Токен аутентификации не может быть пустым.")

        print("-" * 20 + "\n")

        build_config = {
            "SERVER_HOST": server_ip,
            "AUTH_TOKEN": auth_token
        }
        try:
            build_config["SERVER_PORT"] = int(server_port_str)
        except ValueError:
            print(f"[ERROR] Неверный формат порта: '{server_port_str}'. Сборка прервана.")
            sys.exit(1)
        
        build_standalone(build_config)
        
        print("\n" + "=" * 50)
        print("[SUCCESS] Сборка сервера завершена успешно!")
        
    except Exception as e:
        print(f"[ERROR] Ошибка сборки: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
