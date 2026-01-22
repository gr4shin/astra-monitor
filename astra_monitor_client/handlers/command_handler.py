import asyncio
import json
import logging
import os
import base64
import subprocess
import shutil
import re
import sys
import hashlib
from datetime import datetime

from astra_monitor_client.utils.system_utils import get_full_system_info, get_active_graphical_session, get_active_graphical_sessions, build_dbus_env
from astra_monitor_client.handlers.interactive_shell import InteractiveShell
from astra_monitor_client.handlers.screenshot import ScreenshotHandler

class CommandHandler:
    def __init__(self, client):
        self.client = client
        self.interactive_shell = InteractiveShell(client)
        self.screenshot_handler = ScreenshotHandler(client)

    async def handle_command(self, websocket, command):
        """Обработка команд от сервера"""
        try:
            if command == "refresh":
                return self.client.get_system_info()
            
            elif command.startswith("list_files:"):
                path = command.split(":", 1)[1]
                return await self.list_files(path)
                
            elif command.startswith("download_file_chunked:"):
                payload = command.split(":", 1)[1]
                
                parts = payload.split(":", 1)
                if len(parts) == 2 and parts[0].isdigit():
                    chunk_size_str, file_path = parts
                    chunk_size = int(chunk_size_str)
                else:
                    file_path = payload
                    chunk_size = 4 * 1024 * 1024
                
                asyncio.create_task(self.stream_file_to_server(websocket, file_path, chunk_size))
                return None

            elif command.startswith("screenshot_settings:"):
                settings_json = command.split(":", 1)[1]
                new_settings = json.loads(settings_json)
                
                if "quality" in new_settings:
                    quality = max(1, min(100, int(new_settings["quality"])))
                    new_settings["quality"] = quality
                    
                if "refresh_delay" in new_settings:
                    delay = max(1, min(60, int(new_settings["refresh_delay"])))
                    new_settings["refresh_delay"] = delay
                    
                if "monitor_mode" in new_settings:
                    if new_settings["monitor_mode"] not in ("all", "primary"):
                        new_settings["monitor_mode"] = "all"

                self.client.screenshot_settings.update(new_settings)
                self.client.settings["screenshot"] = self.client.screenshot_settings
                self.client.save_config()
                
                return {"screenshot_settings_updated": self.client.screenshot_settings}

            elif command == "get_full_system_info":
                full_info = get_full_system_info()
                return {"full_system_info": full_info}

            elif command == "get_screenshot_settings":
                return {"screenshot_settings": self.client.screenshot_settings}

            elif command.startswith("upload_file_start:"):
                parts = command.split(":", 2)
                remote_path, file_size_str = parts[1], parts[2]
                save_path = remote_path

                try:
                    os.makedirs(os.path.dirname(save_path), exist_ok=True)
                    file_handle = open(save_path, 'wb')
                    self.client.upload_context = {
                        'handle': file_handle,
                        'path': save_path, # Store the corrected path
                        'original_path': remote_path, # Keep original for context if needed
                        'expected_size': int(file_size_str),
                        'received_size': 0,
                        'hasher': hashlib.sha256()
                    }
                    logging.info("-> 📤 Выполнение: начало приема файла '%s' (размер: %s).", save_path, file_size_str)
                    return None
                except Exception as e:
                    self.client.upload_context = {}
                    return {"file_upload_result": "error", "error": f"❌ Failed to start upload: {str(e)}"}

            elif command.startswith("upload_file_chunk:"):
                if not self.client.upload_context.get('handle'):
                    return {"file_upload_result": "error", "error": "❌ Upload not initiated"}
                
                chunk_data = command.split(":", 1)[1]
                try:
                    chunk_bytes = base64.b64decode(chunk_data)
                    self.client.upload_context['handle'].write(chunk_bytes)
                    hasher = self.client.upload_context.get('hasher')
                    if hasher:
                        hasher.update(chunk_bytes)
                    self.client.upload_context['received_size'] += len(chunk_bytes)
                    return None
                except Exception as e:
                    if self.client.upload_context.get('handle'):
                        self.client.upload_context['handle'].close()
                    self.client.upload_context = {}
                    return {"file_upload_result": "error", "error": f"❌ Error writing chunk: {str(e)}"}

            elif command.startswith("upload_file_end"):
                path_to_log = self.client.upload_context.get('path', 'N/A')
                logging.info("-> ✅ Выполнение: завершение приема файла '%s'.", path_to_log)
                if not self.client.upload_context.get('handle'):
                    return {"file_upload_result": "error", "error": "❌ Upload not initiated"}

                self.client.upload_context['handle'].close()
                final_size = self.client.upload_context['received_size']
                expected_size = self.client.upload_context['expected_size']
                path = self.client.upload_context['path']
                expected_hash = None
                if ":" in command:
                    expected_hash = command.split(":", 1)[1].strip() or None
                actual_hash = None
                hasher = self.client.upload_context.get('hasher')
                if hasher:
                    actual_hash = hasher.hexdigest()
                self.client.upload_context = {}

                if final_size != expected_size:
                    try:
                        os.remove(path)
                    except OSError:
                        pass
                    return {"file_upload_result": "error", "error": f"❌ File size mismatch. Expected {expected_size}, got {final_size}"}

                if expected_hash and actual_hash and expected_hash != actual_hash:
                    try:
                        os.remove(path)
                    except OSError:
                        pass
                    return {"file_upload_result": "error", "error": "❌ File hash mismatch after upload"}
                
                return {"file_upload_result": "success"}

            elif command.startswith("cancel_upload:"):
                remote_path = command.split(":", 1)[1]
                if self.client.upload_context and self.client.upload_context.get('path') == remote_path:
                    logging.info("-> ⏹️ Получен запрос на отмену приема файла '%s'.", remote_path)
                    self.client.upload_context['handle'].close()
                    try:
                        os.remove(self.client.upload_context['path'])
                        logging.info("-> 🗑️ Частично полученный файл '%s' удален.", self.client.upload_context['path'])
                    except OSError as e:
                        logging.error("❌ Не удалось удалить частично полученный файл '%s': %s", self.client.upload_context['path'], e)
                    self.client.upload_context = {}
                else:
                    logging.warning("-> ⚠️ Запрос на отмену приема для '%s', но загрузка не активна.", remote_path)
                return None

            elif command.startswith("apply_settings:"):
                settings_json = command.split(":", 1)[1]
                settings = json.loads(settings_json)
                logging.info("-> ⚙️ Выполнение: применение новых настроек.")
                return await self.apply_settings(settings)
                    
            elif command.startswith("delete:"):
                path = command.split(":", 1)[1]
                logging.info("-> 🗑️ Выполнение: удаление '%s'.", path)
                return await self.delete_path(path)

            elif command.startswith("create_folder:"):
                path = command.split(":", 1)[1]
                logging.info("-> ➕ Выполнение: создание папки '%s'.", path)
                return await self.create_folder(path)
            
            elif command.startswith("rename_path:"):
                parts = command.split(":", 2)
                logging.info("-> ✏️ Выполнение: переименование '%s' в '%s'.", parts[1], parts[2])
                return await self.rename_path(parts[1], parts[2])

            elif command.startswith("apt:"):
                apt_cmd = command.split(":", 1)[1]
                logging.info("-> 📦 Выполнение: apt команда '%s'.", apt_cmd.split(':', 1)[0])
                
                if apt_cmd == "get_repos":
                    repo_files = {}
                    main_repo = "/etc/apt/sources.list"
                    if os.path.exists(main_repo):
                        try:
                            with open(main_repo, 'r', encoding='utf-8') as f:
                                repo_files[main_repo] = f.read()
                        except Exception as e:
                            repo_files[main_repo] = f"❌ Error reading file: {e}"
                    
                    repo_dir = "/etc/apt/sources.list.d"
                    if os.path.isdir(repo_dir):
                        for filename in sorted(os.listdir(repo_dir)):
                            if filename.endswith(".list"):
                                filepath = os.path.join(repo_dir, filename)
                                try:
                                    with open(filepath, 'r', encoding='utf-8') as f:
                                        repo_files[filepath] = f.read()
                                except Exception as e:
                                    repo_files[filepath] = f"❌ Error reading file: {e}"
                    return {"apt_repo_data": repo_files}

                elif apt_cmd.startswith("save_repo:"):
                    parts = apt_cmd.split(":", 2)
                    filepath, content_b64 = parts[1], parts[2]
                    
                    resolved_path = os.path.abspath(filepath)
                    if not (resolved_path.startswith("/etc/apt/sources.list.d/") or resolved_path == "/etc/apt/sources.list"):
                        return {"apt_command_result": f"❌ Ошибка безопасности: запись разрешена только в /etc/apt/."}
                    
                    try:
                        content = base64.b64decode(content_b64).decode('utf-8')
                        with open(filepath, 'w', encoding='utf-8') as f:
                            f.write(content)
                        return {"apt_command_result": f"✅ Файл {filepath} успешно сохранен."}
                    except Exception as e:
                        return {"apt_command_result": f"❌ Ошибка сохранения файла {filepath}: {e}"}

                elif apt_cmd == "update":
                    asyncio.create_task(self.stream_command_output(websocket, "sudo apt-get update"))
                    return None

                elif apt_cmd == "list_upgradable":
                    proc = await asyncio.create_subprocess_shell("apt list --upgradable", stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
                    stdout, stderr = await proc.communicate()
                    if proc.returncode != 0:
                        return {"apt_command_result": f"❌ Ошибка: {stderr.decode()}"}
                    
                    output = stdout.decode()
                    packages = []
                    lines = output.strip().split('\n')
                    
                    # Regex to find "[upgradable from: 1.2.3]"
                    from_regex = re.compile(r'\[upgradable from:\s*(.*?)\]')

                    if len(lines) > 1:
                        for line in lines[1:]: # Skip "Listing..."
                            parts = line.split()
                            if len(parts) < 2: continue
                            
                            name = parts[0].split('/')[0]
                            new_version = parts[1]
                            
                            current_version_match = from_regex.search(line)
                            current_version = current_version_match.group(1) if current_version_match else 'N/A'
                            
                            packages.append({"name": name, "current": current_version, "new": new_version})
                    return {"apt_upgradable_list": packages}

                elif apt_cmd.startswith("upgrade_packages:"):
                    packages_str = command.split(":", 1)[1]
                    packages = ' '.join(re.findall(r'[\w.\-:]+', packages_str))
                    if packages: asyncio.create_task(self.stream_command_output(websocket, f"sudo apt-get install --only-upgrade -y {packages}"))
                    return None

                elif apt_cmd == "full_upgrade":
                    asyncio.create_task(self.stream_command_output(websocket, "sudo apt update && sudo apt-get dist-upgrade"))
                    return None

            elif command.startswith("interactive:"):
                parts = command.split(":", 2)
                action = parts[1]
                payload = parts[2] if len(parts) > 2 else ""
                return await self.interactive_shell.handle(websocket, action, payload)

            elif command.startswith("install_package:"):
                package_path = command.split(":", 1)[1]
                logging.info("-> 🚀 Выполнение: запуск установки пакета '%s'.", package_path)
                update_script_path = "/tmp/monitor_update.sh"
                script_content = f"""#!/bin/bash
# Скрипт самоубновления для клиента мониторинга

echo \"Запуск скрипта обновления...\" > /tmp/monitor_update.log

sleep 3

echo \"Запуск dpkg -i...\" >> /tmp/monitor_update.log
DEBIAN_FRONTEND=noninteractive sudo dpkg -i \"{package_path}\" >> /tmp/monitor_update.log 2>&1

echo \"Перезапуск службы...\" >> /tmp/monitor_update.log
sudo systemctl restart astra-monitor.service >> /tmp/monitor_update.log 2>&1

echo \"Скрипт обновления завершен.\" >> /tmp/monitor_update.log

rm -f \"{package_path}\" 
rm -- \"$0\"
"""
                try:
                    with open(update_script_path, "w") as f:
                        f.write(script_content)
                    os.chmod(update_script_path, 0o755)

                    if shutil.which('systemd-run'):
                        cmd = ['systemd-run', '--scope', update_script_path]
                    else:
                        cmd = ['nohup', update_script_path]

                    subprocess.Popen(cmd,
                                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                    stdin=subprocess.DEVNULL, start_new_session=True)

                    async with self.client.send_lock:
                        await websocket.send(json.dumps({"install_result": "🚀 Процесс обновления запущен. Клиент перезапускается..."}))
                    await asyncio.sleep(1)
                    sys.exit(0)
                except Exception as e:
                    return {"install_result": f"❌ Не удалось запустить обновление: {e}"}

            elif command.startswith("screenshot_quality:"):
                quality = int(command.split(":", 1)[1])
                quality = max(1, min(100, quality))
                logging.info("-> 📸 Выполнение: создание скриншота с качеством %d%%.", quality)
                return await self.screenshot_handler.take_screenshot(force_quality=quality)
                
            elif command == "screenshot":
                logging.info("-> 📸 Выполнение: создание скриншота с настройками по умолчанию.")
                return await self.screenshot_handler.take_screenshot()

            elif command == "get_settings":
                logging.info("-> ⚙️ Выполнение: отправка текущих настроек.")
                settings = {k: v for k, v in self.client.settings.items() if k != "client_id"}
                return {"client_settings": settings}

            elif command == "shutdown":
                logging.warning("-> 🔌 Выполнение: ВЫКЛЮЧЕНИЕ СИСТЕМЫ.")
                os.system("shutdown now")
                return {"status": "shutting_down"}

            elif command == "reboot":
                logging.warning("-> 🔄 Выполнение: ПЕРЕЗАГРУЗКА СИСТЕМЫ.")
                os.system("reboot")
                return {"status": "rebooting"}

            elif command.startswith("execute:"):
                cmd = command.split(":", 1)[1].strip()
                logging.info("-> ▶️ Выполнение: shell команда '%s'.", cmd)
                
                if cmd.startswith("cd "):
                    path = cmd[3:].strip()
                    if not path:
                        path = "~"
                    
                    expanded_path = os.path.expanduser(path)
                    
                    if not os.path.isabs(expanded_path):
                        new_path = os.path.join(self.client.cwd, expanded_path)
                    else:
                        new_path = expanded_path
                    
                    new_path = os.path.normpath(new_path)

                    if os.path.isdir(new_path):
                        self.client.cwd = new_path
                        return {"prompt_update": self.client.cwd}
                    else:
                        return {"command_error": f"❌ cd: no such file or directory: {path}"}
                
                try:
                    # Capture output as bytes
                    proc = subprocess.run(cmd, shell=True, capture_output=True, cwd=self.client.cwd, timeout=30)
                    
                    def decode_output(output_bytes):
                        return output_bytes.decode('utf-8', errors='replace')

                    stdout = decode_output(proc.stdout)
                    stderr = decode_output(proc.stderr)
                    
                    if proc.returncode != 0:
                        return {"command_error": stdout + stderr}
                    else:
                        return {"command_result": stdout}

                except subprocess.TimeoutExpired:
                    return {"command_error": "⌛ Timeout expired"}
                except Exception as e:
                    return {"command_error": str(e)}

            elif command.startswith("show_message:"):
                message = command.split(":", 1)[1]
                logging.info("-> 💬 Выполнение: отображение сообщения для пользователя.")
                return await self.show_message(message)

            else:
                logging.error("❓ Неизвестная команда от сервера: %s", command)
                return {"error": f"❓ Unknown command: {command}"}
        except Exception as e:
            logging.exception("❌ Ошибка при выполнении команды '%s'", command.split(':', 1)[0])
            return {"error": f"❌ Command execution failed: {str(e)}"}

    async def cleanup_interactive_session(self, websocket=None):
        await self.interactive_shell.cleanup(websocket)

    async def list_files(self, path):
        """Список файлов в директории"""
        try:
            if not os.path.exists(path):
                return {"error": f"❌ Путь не существует: {path}"}
            files = []
            for item in os.listdir(path):
                full_path = os.path.join(path, item)
                if os.path.isdir(full_path):
                    files.append({"name": item, "type": "directory", "size": 0})
                else:
                    try:
                        size = os.path.getsize(full_path)
                    except Exception as e:
                        size = -1
                    files.append({"name": item, "type": "file", "size": size})
                    
            return {"files_list": {"path": path, "files": files}}
            
        except Exception as e:
            return {"error": f"❌ Ошибка чтения директории: {str(e)}"}

    async def delete_path(self, path):
        """Удаление файла или директории"""
        try:
            if not os.path.exists(path):
                return {"file_delete_result": "error", "error": "❌ Путь не существует"}

            if os.path.isdir(path):
                shutil.rmtree(path)
            else:
                os.remove(path)
                
            return {"file_delete_result": "success"}
            
        except Exception as e:
            return {"file_delete_result": "error", "error": f"❌ {str(e)}"}

    async def create_folder(self, path):
        """Создание папки"""
        try:
            os.makedirs(path, exist_ok=True)
            return {"folder_created": "success"}
        except Exception as e:
            return {"folder_created": "error", "error": f"❌ {str(e)}"}

    async def rename_path(self, old_path, new_path):
        """Переименование файла или папки"""
        try:
            os.rename(old_path, new_path)
            return {"rename_result": "success"}
        except Exception as e:
            return {"rename_result": "error", "error": f"❌ {str(e)}"}

    async def stream_file_to_server(self, websocket, file_path, chunk_size: int = 4 * 1024 * 1024):
        """Отправка файла на сервер по частям."""
        try:
            if not os.path.exists(file_path) or os.path.isdir(file_path):
                async with self.client.send_lock:
                    await websocket.send(json.dumps({"error": f"❌ Файл не найден или является директорией: {file_path}"}))
                return

            file_size = os.path.getsize(file_path)
            filename = os.path.basename(file_path)

            start_payload = {"download_file_start": {"filename": filename, "filesize": file_size, "path": file_path}}
            async with self.client.send_lock:
                await websocket.send(json.dumps(start_payload))

            CHUNK_SIZE = chunk_size
            loop = asyncio.get_running_loop()
            with open(file_path, 'rb') as f:
                while True:
                    chunk = f.read(CHUNK_SIZE)
                    if not chunk:
                        break
                    
                    chunk_b64_bytes = await loop.run_in_executor(
                        None, base64.b64encode, chunk
                    )
                    
                    chunk_payload = {
                        "download_file_chunk": {"data": chunk_b64_bytes.decode('ascii'), "path": file_path}
                    }
                    json_payload = await loop.run_in_executor(None, json.dumps, chunk_payload)

                    async with self.client.send_lock:
                        await websocket.send(json_payload)

            async with self.client.send_lock:
                await websocket.send(json.dumps({"download_file_end": {"path": file_path}}))

        except Exception as e:
            logging.error("❌ Ошибка при отправке файла '%s': %s", file_path, e, exc_info=True)
            try:
                async with self.client.send_lock:
                    await websocket.send(json.dumps({"error": f"❌ Ошибка при отправке файла: {e}"}))
            except:
                pass

    async def stream_command_output(self, websocket, command, message_key="apt_command_output", result_key="apt_command_result"):
        """Запускает команду и стримит ее вывод на сервер."""
        try:
            process = await asyncio.create_subprocess_shell(
                command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )

            async def stream_pipe(pipe):
                while True:
                    line = await pipe.readline()
                    if not line:
                        break
                    async with self.client.send_lock:
                        await websocket.send(json.dumps({message_key: line.decode('utf-8', errors='replace')}))

            await asyncio.gather(
                stream_pipe(process.stdout),
                stream_pipe(process.stderr)
            )

            await process.wait()
            async with self.client.send_lock:
                await websocket.send(json.dumps({result_key: f"✅ Команда завершена с кодом: {process.returncode}", "original_command": command}))
        except Exception as e:
            async with self.client.send_lock:
                await websocket.send(json.dumps({result_key: f"❌ Критическая ошибка выполнения команды: {e}", "original_command": command}))

    async def apply_settings(self, settings):
        """Применение настроек"""
        try:
            settings.pop("client_id", None)
            self.client.settings.update(settings)

            if 'monitoring_interval' in settings:
                self.client.REFRESH_INTERVAL = settings['monitoring_interval']

            if "screenshot" in settings:
                if not isinstance(settings["screenshot"], dict):
                    settings["screenshot"] = {}
                self.client.screenshot_settings.update(settings["screenshot"])
                self.client.settings["screenshot"] = self.client.screenshot_settings

            screenshot_settings = self.client.settings.get("screenshot", {})
            if "quality" in screenshot_settings:
                quality = max(1, min(100, int(screenshot_settings["quality"])))
                screenshot_settings["quality"] = quality

            if "refresh_delay" in screenshot_settings:
                delay = max(1, min(60, int(screenshot_settings["refresh_delay"])))
                screenshot_settings["refresh_delay"] = delay

            if "monitor_mode" in screenshot_settings:
                if screenshot_settings["monitor_mode"] not in ("all", "primary"):
                    screenshot_settings["monitor_mode"] = "all"

            self.client.save_config()
            logging.info("✅ Новые настройки применены и сохранены: %s", self.client.settings)
            return {"settings_applied": "success", "new_settings": self.client.settings}
            
        except Exception as e:
            return {"settings_applied": "error", "error": f"❌ {str(e)}"}

    async def show_message(self, message):
        def run_as_user(user, display, uid, cmd, timeout=15, capture_output=True):
            full_cmd = ['runuser', '-u', user, '--'] + cmd
            env = build_dbus_env(user, display, uid)
            try:
                return subprocess.run(
                    full_cmd,
                    env=env,
                    timeout=timeout,
                    capture_output=capture_output
                )
            except Exception as e:
                logging.error("Ошибка runuser: %s", e)
                return None

        if not shutil.which('notify-send'):
            return {"message_result": "error", "error": "❌ Команда 'notify-send' не найдена."}

        try:
            try:
                subprocess.run(["xhost", "+SI:localuser:root"], timeout=5, capture_output=False)
                subprocess.run(["xhost", "+SI:localuser:*"], timeout=5, capture_output=False)
            except Exception:
                pass

            sessions = get_active_graphical_sessions()
            if not sessions:
                return {"error": "❌ Не найдено активных графических сессий"}

            notify_cmd = [
                'notify-send',
                '--icon=dialog-information',
                '--urgency=normal',
                '--expire-time=10000',
                'Сообщение от администратора',
                message
            ]
            failed = 0
            delivered = 0
            for user, display, uid in sessions:
                result = run_as_user(user, display, uid, notify_cmd, timeout=10, capture_output=True)
                if result and result.returncode == 0:
                    delivered += 1
                    continue

                if shutil.which('zenity'):
                    short_msg = message[:200] + "..." if len(message) > 200 else message
                    zenity_cmd = [
                        'zenity',
                        '--info',
                        '--title=Сообщение от администратора',
                        '--text=' + short_msg,
                        '--width=400',
                        '--timeout=10'
                    ]
                    result = run_as_user(user, display, uid, zenity_cmd, timeout=15, capture_output=True)
                    if result and result.returncode == 0:
                        delivered += 1
                        continue

                failed += 1

            if failed:
                return {"message_result": "error", "error": f"❌ Не удалось отправить уведомление для {failed} сессий."}

            return {"message_result": "success", "info": f"✅ Сообщение отправлено в {delivered} сессий."}
        except Exception as e:
            logging.error("Критическая ошибка отправки сообщения: %s", e)
            return {"message_result": "error", "error": f"❌ Критическая ошибка: {str(e)}"}
