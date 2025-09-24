
import asyncio
import sys
import time
import websockets
import json
import platform
import os
import logging

from astra_monitor_client.utils.config import deobfuscate_config, OBFUSCATION_KEY
from astra_monitor_client.utils.system_utils import SystemMonitor, get_local_ip
from astra_monitor_client.handlers.command_handler import CommandHandler

class SystemMonitorClient:
    def __init__(self, version="0.0.0-dev"):
        self.CLIENT_VERSION = version
        if platform.system() == "Windows":
            self.CONFIG_DIR = os.path.join(os.getenv('APPDATA'), 'AstraMonitorClient')
        else:
            self.CONFIG_DIR = "/etc/astra-monitor-client"
        self.CONFIG_FILE = os.path.join(self.CONFIG_DIR, "config.json")
        
        self.settings = {
            "monitoring_interval": 10,
            "reconnect_delay": 5,
            "screenshot": {
                "quality": 85,
                "refresh_delay": 5,
                "enabled": False
            }
        }

        embedded_config = self._load_embedded_config()
        if embedded_config:
            logging.info("📦 Загружена встроенная конфигурация.")
        
        self.SERVER_HOST = embedded_config.get("server_host")
        self.SERVER_PORT = int(embedded_config.get("server_port", 8765))
        self.AUTH_TOKEN = embedded_config.get("auth_token")

        if not self.SERVER_HOST or not self.AUTH_TOKEN:
            logging.critical("❌ Критическая ошибка: IP-адрес сервера или токен аутентификации не встроены в клиент.")
            logging.critical("   Пожалуйста, пересоберите клиент, указав эти параметры при сборке.")
            sys.exit(1)

        for key, value in embedded_config.items():
            if key in self.settings:
                if isinstance(self.settings.get(key), dict) and isinstance(value, dict):
                    self.settings[key].update(value)
                else:
                    self.settings[key] = value

        external_config = self._load_external_config()
        if external_config:
            logging.info("📄 Внешняя конфигурация из %s загружена.", self.CONFIG_FILE)
            if "server_host" in external_config or "server_port" in external_config or "auth_token" in external_config:
                logging.warning("⚠️ Внешний файл конфигурации содержит 'server_host', 'server_port' или 'auth_token'. Эти параметры игнорируются и могут быть заданы только при сборке.")
            for key, value in external_config.items():
                if key in self.settings:
                    if isinstance(self.settings.get(key), dict) and isinstance(value, dict):
                        self.settings[key].update(value)
                    else:
                        self.settings[key] = value

        self.REFRESH_INTERVAL = self.settings.get("monitoring_interval", 10)
        self.screenshot_settings = self.settings.get("screenshot", {})

        self.hostname = platform.node()
        self.local_ip = get_local_ip()
        self.cwd = os.path.expanduser("~")
        if not os.path.isdir(self.cwd):
            self.cwd = "/"
        self.upload_context = {}
        self.last_net_rx, self.last_net_tx = SystemMonitor.get_network_io()
        self.last_net_ts = time.time()
        self.send_lock = asyncio.Lock()
        self.command_handler = CommandHandler(self)
        self.is_running = False

    def stop(self):
        self.is_running = False

    def _load_embedded_config(self) -> dict:
        """Загружает и дешифрует встроенную конфигурацию, возвращая словарь."""
        try:
            base_path = getattr(sys, '_MEIPASS', os.path.dirname(os.path.abspath(__file__)))
            embedded_config_path = os.path.join(base_path, 'assets', 'config.dat')
            if os.path.exists(embedded_config_path):
                with open(embedded_config_path, 'r', encoding='utf-8') as f:
                    obfuscated_data = f.read().strip()
                if obfuscated_data:
                    return deobfuscate_config(obfuscated_data, OBFUSCATION_KEY)
        except Exception as e:
            logging.warning("⚠️ Не удалось загрузить/расшифровать встроенную конфигурацию: %s", e)
        return {}

    def _load_external_config(self) -> dict:
        """Загружает конфигурацию из внешнего файла, возвращая словарь."""
        try:
            with open(self.CONFIG_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            pass
        return {}

    def save_config(self):
        """Сохранение конфигурации в файл"""
        try:
            if not os.path.exists(self.CONFIG_DIR):
                os.makedirs(self.CONFIG_DIR)
            with open(self.CONFIG_FILE, 'w', encoding='utf-8') as f:
                json.dump(self.settings, f, indent=4)
        except Exception as e:
            logging.error("❌ Не удалось сохранить конфигурацию: %s", e, exc_info=True)
        else:
            logging.info("✅ Конфигурация успешно сохранена в %s", self.CONFIG_FILE)
    
    def get_system_info(self):
        """Сбор информации о системе без psutil"""
        try:
            cpu_percent = SystemMonitor.get_cpu_percent()
            memory_percent, memory_used, memory_total = SystemMonitor.get_memory_info()
            disk_percent, disk_used, disk_total = SystemMonitor.get_disk_usage()
            uptime = SystemMonitor.get_boot_time()
            current_rx, current_tx = SystemMonitor.get_network_io()
            current_ts = time.time()
            
            time_delta = current_ts - self.last_net_ts
            bytes_recv_speed = 0
            bytes_sent_speed = 0
            
            if time_delta > 0:
                bytes_recv_speed = (current_rx - self.last_net_rx) / time_delta
                bytes_sent_speed = (current_tx - self.last_net_tx) / time_delta
                
            self.last_net_rx, self.last_net_tx = current_rx, current_tx
            self.last_net_ts = current_ts
            
            return {
                "version": self.CLIENT_VERSION,
                "hostname": self.hostname,
                "cpu_percent": round(cpu_percent, 1),
                "memory_percent": round(memory_percent, 1),
                "disk_percent": round(disk_percent, 1),
                "disk_total": disk_total,
                "disk_used": disk_used,
                "uptime": uptime,
                "bytes_sent": current_tx,
                "bytes_recv": current_rx,
                "bytes_sent_speed": bytes_sent_speed,
                "bytes_recv_speed": bytes_recv_speed,
                "platform": platform.platform(),
                "local_ip": self.local_ip
            }
        except Exception as e:
            return {"error": str(e)}

    async def send_screenshot(self, websocket):
        """Отправка скриншота на сервер"""
        try:
            screenshot_data = await self.command_handler.take_screenshot()
            if "screenshot" in screenshot_data:
                async with self.send_lock:
                    await websocket.send(json.dumps({
                        "screenshot_update": screenshot_data,
                        "timestamp": datetime.now().isoformat()
                    }))
        except Exception as e:
            logging.error("❌ Ошибка отправки скриншота: %s", e)

    async def connect_to_server(self):
        server_uri = f"ws://{self.SERVER_HOST}:{self.SERVER_PORT}"
        
        logging.info("Запуск клиента: %s (%s)", self.hostname, self.local_ip)
        logging.info("Подключение к серверу: %s", server_uri)

        while self.is_running:
            last_screenshot_time = 0
            screenshot_task = None
            last_info_sent_time = 0
            try:
                async with websockets.connect(
                    server_uri,
                    max_size=100 * 1024 * 1024,
                    ping_interval=30,
                    ping_timeout=60
                ) as websocket:
                    auth_data = json.dumps({
                        "auth_token": self.AUTH_TOKEN,
                        "client_info": {
                            "hostname": self.hostname,
                            "ip": self.local_ip,
                            "os_type": platform.system(),
                            "platform_full": platform.platform(),
                            "settings": self.settings

                        }
                    })
                    async with self.send_lock:
                        await websocket.send(auth_data)
                    logging.info("✅ Аутентификация успешна")
                    
                    while self.is_running:
                        current_time = time.time()
                        if current_time - last_info_sent_time >= self.REFRESH_INTERVAL:
                            system_info = self.get_system_info()
                            async with self.send_lock:
                                await websocket.send(json.dumps(system_info))
                            last_info_sent_time = current_time
                        
                        if (self.settings["screenshot"]["enabled"] and 
                            current_time - last_screenshot_time >= self.settings["screenshot"]["refresh_delay"]):
                            
                            if screenshot_task is None or screenshot_task.done():
                                screenshot_task = asyncio.create_task(self.send_screenshot(websocket))
                                last_screenshot_time = current_time
                        
                        try:
                            command = await asyncio.wait_for(websocket.recv(), timeout=1.0)
                            command_data = json.loads(command)
                            
                            if "command" in command_data:
                                response = await self.command_handler.handle_command(websocket, command_data["command"])
                                if response is not None:
                                    async with self.send_lock:
                                        await websocket.send(json.dumps(response))
                                    
                        except asyncio.TimeoutError:
                            continue
                        except websockets.exceptions.ConnectionClosed:
                            break # Exit inner loop on connection close
                            
            except websockets.exceptions.ConnectionClosed:
                logging.warning("🔌 Соединение разорвано, повторная попытка через %s секунд...", self.settings['reconnect_delay'])
                logging.info("-> 🧹 Соединение разорвано, запускается очистка интерактивной сессии...")
                await self.command_handler.cleanup_interactive_session()
                await asyncio.sleep(self.settings['reconnect_delay'])
            except ConnectionRefusedError:
                logging.error("❌ Сервер недоступен, повторная попытка через %s секунд...", self.settings['reconnect_delay'])
                logging.info("-> 🧹 Соединение недоступно, запускается очистка интерактивной сессии...")
                await self.command_handler.cleanup_interactive_session()
                await asyncio.sleep(self.settings['reconnect_delay'])
            except Exception:
                logging.exception("🔌 Непредвиденная ошибка подключения, повтор через %s секунд...", self.settings['reconnect_delay'])
                logging.info("-> 🧹 Непредвиденная ошибка, запускается очистка интерактивной сессии...")
                await self.command_handler.cleanup_interactive_session()
                await asyncio.sleep(self.settings['reconnect_delay'])
    
    def run(self):
        """Запуск клиента"""
        self.is_running = True
        try:
            asyncio.run(self.connect_to_server())
        except KeyboardInterrupt:
            logging.info("🛑 Клиент остановлен")
        except Exception:
            logging.critical("❌ Критическая ошибка в главном цикле.", exc_info=True)
        finally:
            self.is_running = False
