#!/usr/bin/env python3
"""
Сборка автономного исполняемого файла и .deb пакета для клиента
"""

import subprocess
import sys
import os
import shutil
import json
import base64
import tempfile
import re
from pathlib import Path

OBFUSCATION_KEY = "AstraMonitorKey2024!@#" # Ключ должен совпадать с ключом в client_monitor.py

def get_version():
    """Читает версию из файла astra_monitor_client/main.py."""
    try:
        main_py_path = Path(__file__).parent / "astra_monitor_client" / "main.py"
        main_py_content = main_py_path.read_text(encoding="utf-8")
        match = re.search(r"^CLIENT_VERSION\s*=\s*[\"\"](.*?)[\"\"]", main_py_content, re.MULTILINE)
        if match:
            return match.group(1)
    except Exception as e:
        print(f"Не удалось прочитать версию из main.py: {e}")
    
    print("Не удалось определить версию, используется 0.0.0-fallback")
    return "all"

def obfuscate_config(data: dict, key: str) -> str:
    """Обусцирует словарь конфигурации в шифротекст."""
    json_str = json.dumps(data).encode('utf-8')
    b64_bytes = base64.b64encode(json_str)
    
    xored_bytes = bytearray()
    for i, byte in enumerate(b64_bytes):
        xored_bytes.append(byte ^ ord(key[i % len(key)]))
        
    final_b64_str = base64.b64encode(bytes(xored_bytes)).decode('ascii')
    return final_b64_str

def install_pyinstaller():
    """Установка PyInstaller"""
    print("📦 Установка PyInstaller...")
    subprocess.check_call([sys.executable, "-m", "pip", "install", "pyinstaller"])

def build_standalone(build_config=None):
    """Сборка автономного исполняемого файла"""
    print("🔨 Сборка исполняемого файла...")
    
    # Используем python -m PyInstaller для кросс-платформенной сборки из venv
    pyinstaller_cmd = [sys.executable, "-m", "PyInstaller"]
    
    options = [
        "--name=astra-monitor-client",
        "--onefile",
    ]

    if sys.platform == "win32":
        options.append("--windowed")
    else:
        options.append("--console")

    options.extend([
        "--hidden-import=websockets",
        "--hidden-import=pyautogui",
        "--hidden-import=psutil",
        "--hidden-import=pkg_resources.py2_warn", # Для совместимости
    ])

    if sys.platform == "win32":
        options.extend([
            "--hidden-import=WMI",
        ])
    
    options.extend([
        "--clean",
        "--noconfirm",
    ])
    
    temp_assets_dir = "build_assets"
    try:
        if build_config:
            os.makedirs(temp_assets_dir, exist_ok=True)
            config_file_path = os.path.join(temp_assets_dir, "config.dat")

            obfuscated_data = obfuscate_config(build_config, OBFUSCATION_KEY)
            with open(config_file_path, "w", encoding="utf-8") as f:
                f.write(obfuscated_data)
            
            # PyInstaller использует ':' как разделитель на всех платформах
            # Добавляем всю директорию 'build_assets' как 'assets' в бандл
            options.append(f"--add-data={temp_assets_dir}:assets")
            print(f"⚙️ Внедрение зашифрованной конфигурации: {build_config}")

        full_command = pyinstaller_cmd + options + ["astra_monitor_client/main.py"]
        subprocess.check_call(full_command)

    finally:
        # Очищаем временную директорию с ассетами
        if build_config and os.path.exists(temp_assets_dir):
            shutil.rmtree(temp_assets_dir)
            print("🗑️ Временная директория с конфигурацией удалена.")

    print("[OK] Сборка исполняемого файла завершена!")
    executable_path = Path("./dist/astra-monitor-client")
    if sys.platform == "win32":
        executable_path = executable_path.with_suffix(".exe")

    if executable_path.exists():
        print(f"📁 Исполняемый файл: {executable_path}")
        print(f"📊 Размер файла: {executable_path.stat().st_size / 1024 / 1024:.1f} MB")
        return executable_path
    else:
        print("[ERROR] Исполняемый файл не найден.")
        return None

def create_deb_package(executable_path: Path):
    """Создание .deb пакета на основе собранного исполняемого файла."""
    if not executable_path or not executable_path.exists():
        print("[ERROR] Исполняемый файл клиента не найден. Пропуск создания .deb пакета.")
        return None

    print("\n" + "=" * 20)
    print("📦 Создание .deb пакета...")
    
    temp_dir = Path(tempfile.mkdtemp())
    version = get_version()
    package_name = f"astra-monitor-client_{version}_amd64"
    package_dir = temp_dir / package_name
    
    # Структура каталогов
    debian_dir = package_dir / "DEBIAN"
    usr_bin_dir = package_dir / "usr" / "local" / "bin"
    
    debian_dir.mkdir(parents=True, exist_ok=True)
    usr_bin_dir.mkdir(parents=True, exist_ok=True)
    
    # Копируем исполняемый файл
    target_executable = usr_bin_dir / "astra-monitor-client"
    shutil.copy2(executable_path, target_executable)
    target_executable.chmod(0o755)
    
    # Создаем control файл
    control_content = f"""Package: astra-monitor-client
Version: {version}
Section: admin
Priority: optional
Architecture: amd64
Maintainer: gr4shin <admin@gr4shin.ru>
Description: Клиент мониторинга для Astra Linux
 Автономный клиент для системы удаленного мониторинга и управления.
"""
    (debian_dir / "control").write_text(control_content, encoding="utf-8")
    
    # Создаем postinst скрипт
    postinst_content = """#!/bin/bash
# Post-installation script

# Создаем директорию для конфига, если ее нет
mkdir -p /etc/astra-monitor-client

# Устанавливаем права (на всякий случай)
chmod 755 /usr/local/bin/astra-monitor-client

# Создаем службу systemd
cat > /etc/systemd/system/astra-monitor.service << 'EOL'
[Unit]
Description=Astra Linux Monitor Client
After=network.target

[Service]
Type=simple
ExecStart=/usr/local/bin/astra-monitor-client
Restart=always
RestartSec=5
User=root

[Install]
WantedBy=multi-user.target
EOL

systemctl daemon-reload
systemctl enable astra-monitor.service
systemctl start astra-monitor.service

echo "Клиент мониторинга установлен и запущен"
"""
    postinst_path = debian_dir / "postinst"
    postinst_path.write_text(postinst_content, encoding="utf-8")
    postinst_path.chmod(0o755)
    
    # Создаем prerm скрипт
    prerm_content = """#!/bin/bash
# Pre-removal script

systemctl stop astra-monitor.service 2>/dev/null || true
systemctl disable astra-monitor.service 2>/dev/null || true
rm -f /etc/systemd/system/astra-monitor.service 2>/dev/null || true
systemctl daemon-reload 2>/dev/null || true
"""
    prerm_path = debian_dir / "prerm"
    prerm_path.write_text(prerm_content, encoding="utf-8")
    prerm_path.chmod(0o755)
    
    # Собираем .deb пакет
    original_dir = Path.cwd()
    os.chdir(temp_dir)
    
    deb_file_path = None
    try:
        subprocess.run(
            ["dpkg-deb", "--build", package_name], 
            capture_output=True, text=True, check=True
        )
        
        deb_file_name = f"{package_name}.deb"
        created_deb_file = Path(deb_file_name)
        
        if created_deb_file.exists():
            target_path = original_dir / deb_file_name
            shutil.copy2(created_deb_file, target_path)
            print(f"[OK] .deb пакет создан: {target_path}")
            print(f"📊 Размер пакета: {target_path.stat().st_size / 1024 / 1024:.1f} MB")
            deb_file_path = target_path
        else:
            raise FileNotFoundError("DEB файл не был создан")
            
    except subprocess.CalledProcessError as e:
        print(f"Ошибка dpkg-deb: {e.stderr}")
        raise
    finally:
        os.chdir(original_dir)
        shutil.rmtree(temp_dir)
    
    return deb_file_path

def install_dependencies():
    """Установка всех необходимых зависимостей"""
    print("📦 Установка зависимостей...")
    dependencies = [
        "websockets", 
        "pyautogui",
        "psutil",
    ]
    if sys.platform == "win32":
        dependencies.append("WMI")

    for dep in dependencies:
        try:
            # Проверяем, установлена ли зависимость
            __import__(dep)
            print(f"[OK] {dep} уже установлен")
        except ImportError:
            print(f"📦 Устанавливаем {dep}...")
            subprocess.check_call([sys.executable, "-m", "pip", "install", dep])

def main():
    """Основная функция"""
    print("🚀 Сборка автономного клиента мониторинга")
    print("=" * 50)
    
    try:
        install_dependencies()
        try:
            subprocess.check_call([sys.executable, "-m", "PyInstaller", "--version"],
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            print("[OK] PyInstaller уже установлен")
        except:
            install_pyinstaller()
        
        print("\n" + "-"*20)
        print("Внедрение конфигурации в клиент (обязательно)")

        while not (server_ip := input("Введите IP-адрес сервера: ").strip()):
            print("❌ IP-адрес сервера не может быть пустым.")

        while not (server_port_str := input("Введите порт сервера (например, 8765): ").strip()):
            print("❌ Порт сервера не может быть пустым.")

        while not (auth_token := input("Введите токен аутентификации: ").strip()):
            print("❌ Токен аутентификации не может быть пустым.")

        print("-" * 20 + "\n")

        build_config = {
            "server_host": server_ip,
            "auth_token": auth_token,
        }
        try:
            build_config["server_port"] = int(server_port_str)
        except ValueError:
            print(f"[ERROR] Неверный формат порта: '{server_port_str}'. Сборка прервана.")
            sys.exit(1)
        
        executable_path = build_standalone(build_config)

        if executable_path:
            if sys.platform != "win32":
                create_deb = input("\nСоздать .deb пакет? (y/n): ").strip().lower()
                if create_deb == 'y':
                    deb_path = create_deb_package(executable_path)
                    if deb_path:
                        print("\n" + "=" * 50)
                        print("[SUCCESS] Сборка для Linux завершена успешно!")
                        print(f"📁 Исполняемый файл: {executable_path}")
                        print(f"📦 Пакет для установки: {deb_path}")
                        print("\nДля установки пакета:")
                        print(f"  sudo dpkg -i {deb_path}")
                        print("  sudo apt-get install -f  # если нужны зависимости")
                        print("\nДля удаления:")
                        print("  sudo dpkg -r astra-monitor-client")
                    else:
                        print("\n[WARN] Сборка исполняемого файла завершена, но не удалось создать .deb пакет.")
                else:
                    print("\n" + "=" * 50)
                    print("[SUCCESS] Сборка для Linux завершена успешно!")
                    print(f"📁 Исполняемый файл: {executable_path}")
                    print("Создание .deb пакета пропущено.")
            else:
                print("\n" + "=" * 50)
                print("[SUCCESS] Сборка для Windows завершена успешно!")
                print(f"📁 Исполняемый файл: {executable_path}")
                print("\nДля добавления в автозагрузку:")
                print("1. Нажмите Win + R")
                print("2. Введите shell:startup и нажмите Enter.")
                print("3. Скопируйте или создайте ярлык для файла astra-monitor-client.exe в открывшуюся папку.")

        else:
             raise Exception("Не удалось создать исполняемый файл.")
        
    except Exception as e:
        print(f"[ERROR] Ошибка сборки: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
