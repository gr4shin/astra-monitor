import asyncio
import json
import logging
import os
import base64
import subprocess
import shutil
import re
import platform
import sys
from datetime import datetime

if platform.system() == "Linux":
    import pty
    import termios
    import struct
    import fcntl

from astra_monitor_client.utils.system_utils import get_full_system_info, SystemMonitor

class CommandHandler:
    def __init__(self, client):
        self.client = client
        self.interactive_session = None

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
                
                # Correct path for Windows
                if platform.system() == "Windows":
                    import tempfile
                    filename = os.path.basename(remote_path)
                    save_path = os.path.join(tempfile.gettempdir(), filename)
                else:
                    save_path = remote_path

                try:
                    os.makedirs(os.path.dirname(save_path), exist_ok=True)
                    file_handle = open(save_path, 'wb')
                    self.client.upload_context = {
                        'handle': file_handle,
                        'path': save_path, # Store the corrected path
                        'original_path': remote_path, # Keep original for context if needed
                        'expected_size': int(file_size_str),
                        'received_size': 0
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
                    self.client.upload_context['received_size'] += len(chunk_bytes)
                    return None
                except Exception as e:
                    if self.client.upload_context.get('handle'):
                        self.client.upload_context['handle'].close()
                    self.client.upload_context = {}
                    return {"file_upload_result": "error", "error": f"❌ Error writing chunk: {str(e)}"}

            elif command == "upload_file_end":
                path_to_log = self.client.upload_context.get('path', 'N/A')
                logging.info("-> ✅ Выполнение: завершение приема файла '%s'.", path_to_log)
                if not self.client.upload_context.get('handle'):
                    return {"file_upload_result": "error", "error": "❌ Upload not initiated"}

                self.client.upload_context['handle'].close()
                final_size = self.client.upload_context['received_size']
                expected_size = self.client.upload_context['expected_size']
                path = self.client.upload_context['path']
                self.client.upload_context = {}

                if final_size != expected_size:
                    try:
                        os.remove(path)
                    except OSError:
                        pass
                    return {"file_upload_result": "error", "error": f"❌ File size mismatch. Expected {expected_size}, got {final_size}"}
                
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
                    logging.warning("-> ⚠️ Запрос на отмену приема для '%s', но загрузка не активна.", remote_.path)
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
                if platform.system() == "Linux":
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
                else:
                    return {"error": "Command not supported on this platform"}

            elif command.startswith("interactive:"):
                return await self.handle_interactive_command(websocket, command)

            elif command.startswith("install_package:"):
                package_path = command.split(":", 1)[1]
                logging.info("-> 🚀 Выполнение: запуск установки пакета '%s'.", package_path)

                if platform.system() == "Linux":
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
                
                elif platform.system() == "Windows":
                    import tempfile
                    # Reconstruct the actual path where the file was saved
                    filename = os.path.basename(package_path)
                    actual_package_path = os.path.join(tempfile.gettempdir(), filename)

                    current_exe = sys.executable
                    exe_dir = os.path.dirname(current_exe)

                    updater_bat_path = os.path.join(tempfile.gettempdir(), "update_helper.bat")
                    log_file = os.path.join(tempfile.gettempdir(), "updater_log.txt")

                    bat_content = f"""@echo off
set LOGFILE=\"{log_file}\" 

echo Starting update... > %LOGFILE% 

echo Waiting for old process to terminate... >> %LOGFILE%
ping 127.0.0.1 -n 5 > nul

echo Attempting to replace executable... >> %LOGFILE%
move /Y \"{actual_package_path}\" \"{current_exe}\" >> %LOGFILE% 2>&1

echo Restarting the application... >> %LOGFILE%
cd /D \"{exe_dir}\" 
start "" \"{current_exe}\" 

rem Self-destruct
(goto) 2>nul & del \"%~f0\"
"""
                    try:
                        with open(updater_bat_path, "w", encoding='cp866') as f:
                            f.write(bat_content)

                        subprocess.Popen([updater_bat_path], creationflags=subprocess.DETACHED_PROCESS, close_fds=True)

                        async with self.client.send_lock:
                            await websocket.send(json.dumps({"install_result": "🚀 Процесс обновления запущен. Клиент перезапускается..."}))
                        await asyncio.sleep(1)
                        sys.exit(0)

                    except Exception as e:
                        return {"install_result": f"❌ Не удалось запустить обновление Windows: {e}"}

                else:
                    return {"error": "Update command not supported on this platform"}

            elif command.startswith("screenshot_quality:"):
                quality = int(command.split(":", 1)[1])
                quality = max(1, min(100, quality))
                logging.info("-> 📸 Выполнение: создание скриншота с качеством %d%%.", quality)
                return await self.take_screenshot(force_quality=quality)
                
            elif command == "screenshot":
                logging.info("-> 📸 Выполнение: создание скриншота с настройками по умолчанию.")
                return await self.take_screenshot()

            elif command == "get_settings":
                logging.info("-> ⚙️ Выполнение: отправка текущих настроек.")
                return {"client_settings": self.client.settings}

            elif command == "shutdown":
                logging.warning("-> 🔌 Выполнение: ВЫКЛЮЧЕНИЕ СИСТЕМЫ.")
                if platform.system() == "Windows":
                    os.system("shutdown /s /t 0")
                else:
                    os.system("shutdown now")
                return {"status": "shutting_down"}

            elif command == "reboot":
                logging.warning("-> 🔄 Выполнение: ПЕРЕЗАГРУЗКА СИСТЕМЫ.")
                if platform.system() == "Windows":
                    os.system("shutdown /r /t 0")
                else:
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
                        try:
                            return output_bytes.decode('utf-8')
                        except UnicodeDecodeError:
                            return output_bytes.decode('cp866', errors='replace')

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

    async def handle_interactive_command(self, websocket, command):
        parts = command.split(":", 2)
        action = parts[1]

        if platform.system() == "Windows":
            if action == "start":
                if self.interactive_session:
                    return {"interactive_error": "An interactive session is already running."}

                cmd = parts[2]
                try:
                    process = await asyncio.create_subprocess_shell(
                        cmd,
                        stdout=asyncio.subprocess.PIPE,
                        stderr=asyncio.subprocess.PIPE,
                        stdin=asyncio.subprocess.PIPE,
                        cwd=self.client.cwd,
                        creationflags=subprocess.CREATE_NEW_PROCESS_GROUP
                    )
                    self.interactive_session = {"process": process}
                    asyncio.create_task(self.read_and_forward_win_output(websocket, process.stdout, "stdout"))
                    asyncio.create_task(self.read_and_forward_win_output(websocket, process.stderr, "stderr"))
                    return {"interactive_started": True}
                except Exception as e:
                    return {"interactive_error": f"Failed to start interactive session: {e}"}

            elif action == "input":
                if not self.interactive_session or not self.interactive_session.get("process"):
                    return {"interactive_error": "No interactive session is running."}
                
                data = parts[2]
                process = self.interactive_session["process"]
                try:
                    process.stdin.write(data.encode('cp866'))
                    await process.stdin.drain()
                except (BrokenPipeError, ConnectionResetError):
                    await self.cleanup_interactive_session(websocket)
                return None

            elif action == "stop":
                if not self.interactive_session:
                    return {"interactive_error": "No interactive session is running."}
                
                await self.cleanup_interactive_session(websocket)
                return {"interactive_stopped": True}

            elif action == "resize":
                # Not applicable on Windows
                return None

            else:
                return {"interactive_error": f"Unknown interactive action: {action}"}

        else: # Linux
            if action == "start":
                logging.info("-> ⏯️ Получена команда interactive:start.")
                logging.debug(f"Текущее состояние интерактивной сессии: {self.interactive_session}")
                if self.interactive_session:
                    logging.warning("-> ⚠️ Попытка запустить интерактивную сессию, когда она уже существует. Попытка очистить старую.")
                    await self.cleanup_interactive_session(websocket)

                cmd = parts[2]
                logging.info(f"-> 🚀 Запуск нового pty с командой: {cmd}")
                pid, fd = pty.fork()
                if pid == 0:  # Child
                    try:
                        # ОЧИСТКА ОКРУЖЕНИЯ ПЕРЕД ЗАПУСКОМ КОМАНДЫ
                        os.environ.pop('LD_LIBRARY_PATH', None)
                        os.environ.pop('PYTHONPATH', None)
                        os.environ.pop('PYINSTALLER_CONFIG_DIR', None)
                        
                        # Устанавливаем чистое окружение
                        os.environ['LD_LIBRARY_PATH'] = ''
                        args = cmd.split()
                        os.execvp(args[0], args)
                    except Exception as e:
                        os.write(sys.stdout.fileno(), str(e).encode())
                        sys.exit(1)
                else:  # Parent
                    self.interactive_session = {"pid": pid, "fd": fd}
                    logging.info(f"-> ✅ PTY запущен. PID: {pid}, FD: {fd}")
                    # Set non-blocking
                    fl = fcntl.fcntl(fd, fcntl.F_GETFL)
                    fcntl.fcntl(fd, fcntl.F_SETFL, fl | os.O_NONBLOCK)
                    asyncio.create_task(self.read_and_forward_pty_output(websocket, fd))
                    return {"interactive_started": True}

            elif action == "input":
                if not self.interactive_session:
                    return {"interactive_error": "No interactive session is running."}
                
                data = parts[2]
                fd = self.interactive_session["fd"]
                try:
                    os.write(fd, data.encode())
                except (BrokenPipeError, OSError):
                    await self.cleanup_interactive_session(websocket)
                return None

            elif action == "stop":
                if not self.interactive_session:
                    return {"interactive_error": "No interactive session is running."}
                
                await self.cleanup_interactive_session(websocket)
                return {"interactive_stopped": True}

            elif action == "resize":
                if not self.interactive_session:
                    return {"interactive_error": "No interactive session is running."}
                
                fd = self.interactive_session["fd"]
                rows, cols = map(int, parts[2].split(','))
                winsize = struct.pack("HHHH", rows, cols, 0, 0)
                fcntl.ioctl(fd, termios.TIOCSWINSZ, winsize)
                return None

            else:
                return {"interactive_error": f"Unknown interactive action: {action}"}

    async def read_and_forward_pty_output(self, websocket, fd):
        try:
            while self.interactive_session and self.interactive_session.get("fd") == fd:
                try:
                    await asyncio.sleep(0.01)
                    data = os.read(fd, 1024)
                    if not data:
                        break
                    await websocket.send(json.dumps({"interactive_output": {"data": data.decode(errors='replace')}}))
                except BlockingIOError:
                    continue
                except OSError:
                    break
        finally:
            await self.cleanup_interactive_session(websocket)

    async def read_and_forward_win_output(self, websocket, stream, stream_name):
        # Use cp866 for cmd.exe output
        decoder = asyncio.StreamReader(stream)
        try:
            while self.interactive_session and self.interactive_session.get("process"):
                try:
                    data = await asyncio.wait_for(stream.read(1024), timeout=1.0)
                    if not data:
                        break
                    # We try to decode with cp866, as it's the default for Russian Windows cmd.
                    # Fallback to utf-8, then replace errors.
                    try:
                        decoded_data = data.decode('cp866')
                    except UnicodeDecodeError:
                        try:
                            decoded_data = data.decode('utf-8')
                        except UnicodeDecodeError:
                            decoded_data = data.decode('latin-1', errors='replace')
                    
                    await websocket.send(json.dumps({"interactive_output": {"data": decoded_data}}))
                except asyncio.TimeoutError:
                    continue
                except (BrokenPipeError, ConnectionResetError):
                    break
        finally:
            await self.cleanup_interactive_session(websocket)

    async def cleanup_interactive_session(self, websocket=None):
        logging.debug("-> 🧹 Вызов cleanup_interactive_session.")
        if not self.interactive_session:
            logging.debug("-> 🧹 Интерактивная сессия не активна, очистка не требуется.")
            return

        session = self.interactive_session
        logging.info(f"-> 🧹 Очистка интерактивной сессии: {session}")
        self.interactive_session = None
        logging.info("-> 🧹 interactive_session установлена в None.")

        if platform.system() == "Windows":
            process = session.get("process")
            if process and process.returncode is None:
                try:
                    # Forcefully terminate the process tree
                    subprocess.run(f"taskkill /F /T /PID {process.pid}", check=True, capture_output=True)
                except (subprocess.CalledProcessError, FileNotFoundError):
                    try:
                        process.terminate()
                    except ProcessLookupError:
                        pass # Already terminated
        else: # Linux
            pid = session.get("pid")
            fd = session.get("fd")
            if pid:
                try:
                    os.kill(pid, 15)  # SIGTERM
                except ProcessLookupError:
                    pass  # Process already terminated
            if fd:
                try:
                    os.close(fd)
                except OSError:
                    pass
        
        if websocket:
            try:
                await websocket.send(json.dumps({"interactive_stopped": True}))
            except:
                pass # Websocket might be closed already

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
                encoding = 'utf-8' if platform.system() == "Windows" else 'utf-8'
                while True:
                    line = await pipe.readline()
                    if not line:
                        break
                    async with self.client.send_lock:
                        await websocket.send(json.dumps({message_key: line.decode(encoding, errors='replace')}))

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
            self.client.settings.update(settings)
            
            if 'monitoring_interval' in settings:
                self.client.REFRESH_INTERVAL = settings['monitoring_interval']

            if "quality" in self.client.settings["screenshot"]:
                quality = max(1, min(100, int(self.client.settings["screenshot"]["quality"])))
                self.client.settings["screenshot"]["quality"] = quality
                
            if "refresh_delay" in self.client.settings["screenshot"]:
                delay = max(1, min(60, int(self.client.settings["screenshot"]["refresh_delay"])))
                self.client.settings["screenshot"]["refresh_delay"] = delay
                    
            self.client.save_config()
            logging.info("✅ Новые настройки применены и сохранены: %s", self.client.settings)
            return {"settings_applied": "success", "new_settings": self.client.settings}
            
        except Exception as e:
            return {"settings_applied": "error", "error": f"❌ {str(e)}"}

    async def show_message(self, message):
        if platform.system() == "Windows":
            import ctypes
            ctypes.windll.user32.MessageBoxW(0, message, "Сообщение от администратора", 0)
            return {"message_result": "success"}
        else:
            
            def _find_active_session():
                """Находит активную графическую сессию и пользователя."""
                try:
                    p = subprocess.run(['who'], capture_output=True, text=True, check=True)
                    for line in p.stdout.strip().split('\n'):
                        if ':0' in line or ':1' in line or '(:' in line:
                            parts = line.split()
                            user = parts[0]
                            display = ':0'
                            
                            for part in parts:
                                if part.startswith('(:') or (part.startswith(':') and len(part) > 1):
                                    display = part.strip('()')
                                    break
                            
                            try:
                                uid_proc = subprocess.run(['id', '-u', user], capture_output=True, text=True)
                                if uid_proc.returncode == 0:
                                    uid = uid_proc.stdout.strip()
                                    return user, display, uid
                            except:
                                continue
                except Exception:
                    pass
                
                return None, None, None

            def _get_dbus_address(user, uid):
                """Получает актуальный D-BUS адрес для пользователя."""
                methods = [
                    # Метод 1: стандартный путь в /run/user/{uid}/bus (самый надежный)
                    lambda: f'unix:path=/run/user/{uid}/bus',
                    # Метод 2: из активных процессов пользователя
                    lambda: _get_dbus_from_processes(user),
                    # Метод 3: через переменную окружения текущей сессии
                    lambda: _get_dbus_from_current_session(user),
                    # Метод 4: из файла .dbus/session-bus (последний созданный) - НАИМЕНЕЕ надежный
                    lambda: _get_dbus_from_session_file(user),
                ]
                
                for method in methods:
                    try:
                        dbus_addr = method()
                        if dbus_addr:
                            logging.info(f"🔍 Проверяем D-BUS адрес: {dbus_addr}")
                            if _test_dbus_address(dbus_addr, user):
                                logging.info(f"✅ Используется РАБОЧИЙ D-BUS адрес: {dbus_addr}")
                                return dbus_addr
                            else:
                                logging.warning(f"❌ D-BUS адрес нерабочий: {dbus_addr}")
                    except Exception as e:
                        logging.debug(f"Метод не сработал: {e}")
                        continue
                
                logging.warning("⚠️ Не найден рабочий D-BUS адрес, будет использован автодетект")
                return None

            def _get_dbus_from_processes(user):
                """Получает D-BUS адрес из активных процессов пользователя."""
                # Сначала ищем в любых процессах пользователя
                try:
                    # Команда для поиска всех процессов пользователя и их переменных D-BUS
                    cmd = ['pgrep', '-u', user]
                    pgrep_result = subprocess.run(cmd, capture_output=True, text=True)
                    
                    if pgrep_result.returncode == 0:
                        pids = pgrep_result.stdout.strip().split('\n')
                        for pid in pids:
                            if pid.strip():
                                try:
                                    # Читаем environ процесса
                                    with open(f'/proc/{pid.strip()}/environ', 'rb') as f:
                                        env_data = f.read()
                                    # Разбираем переменные окружения
                                    for env_var in env_data.split(b'\x00'):
                                        try:
                                            env_str = env_var.decode('utf-8', errors='ignore')
                                            if env_str.startswith('DBUS_SESSION_BUS_ADDRESS='):
                                                dbus_addr = env_str.split('=', 1)[1]
                                                # Проверяем что это не старый /tmp адрес
                                                if '/run/user/' in dbus_addr:
                                                    logging.info(f"Найден актуальный D-BUS из процесса {pid}: {dbus_addr}")
                                                    return dbus_addr
                                        except:
                                            continue
                                except:
                                    continue
                except:
                    pass
                
                return None

            def _get_dbus_from_current_session(user):
                """Пытается получить D-BUS из текущей сессии пользователя."""
                try:
                    # Пробуем выполнить команду как пользователь и получить актуальный D-BUS
                    cmd = ['runuser', '-u', user, '--', 'bash', '-c', 'echo $DBUS_SESSION_BUS_ADDRESS']
                    result = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
                    if result.returncode == 0 and result.stdout.strip():
                        dbus_addr = result.stdout.strip()
                        if dbus_addr and not dbus_addr.isspace():
                            logging.info(f"Найден D-BUS из текущей сессии: {dbus_addr}")
                            return dbus_addr
                except:
                    pass
                return None

            def _get_dbus_from_session_file(user):
                """Получает D-BUS адрес из файла сессии (используем только если содержит /run/user/)."""
                try:
                    import glob
                    dbus_pattern = f'/home/{user}/.dbus/session-bus/*-0'
                    dbus_files = glob.glob(dbus_pattern)
                    
                    if dbus_files:
                        # Берем самый новый файл
                        newest_file = max(dbus_files, key=os.path.getmtime)
                        with open(newest_file, 'r') as f:
                            content = f.read()
                            for line in content.split('\n'):
                                if line.startswith('DBUS_SESSION_BUS_ADDRESS='):
                                    dbus_addr = line.split('=', 1)[1].strip().strip("'")
                                    # Используем только если это актуальный путь /run/user/
                                    if '/run/user/' in dbus_addr:
                                        logging.info(f"Найден актуальный D-BUS из файла: {dbus_addr}")
                                        return dbus_addr
                                    else:
                                        logging.warning(f"Пропускаем устаревший D-BUS из файла: {dbus_addr}")
                except:
                    pass
                return None

            def _test_dbus_address(dbus_addr, user):
                """Проверяет, рабочий ли D-BUS адрес."""
                try:
                    test_cmd = [
                        'runuser', '-u', user, '--', 'dbus-send', '--session',
                        '--dest=org.freedesktop.DBus', '/org/freedesktop/DBus',
                        'org.freedesktop.DBus.ListNames', '--print-reply', '--timeout=1000'
                    ]
                    result = subprocess.run(
                        test_cmd, 
                        capture_output=True, 
                        text=True, 
                        timeout=2,
                        env={'DBUS_SESSION_BUS_ADDRESS': dbus_addr}
                    )
                    return result.returncode == 0
                except:
                    return False

            if not shutil.which('notify-send'):
                return {"message_result": "error", "error": "❌ Команда 'notify-send' не найдена."}

            try:
                user, display, uid = _find_active_session()
                if not (user and display and uid):
                    return {"error": "❌ Не найдено активной графической сессии"}

                # Получаем актуальный РАБОЧИЙ D-BUS адрес
                dbus_address = _get_dbus_address(user, uid)
                
                def run_as_user_with_dbus(user, display, uid, dbus_addr, cmd, timeout=5):
                    """Запуск команды от имени пользователя с D-BUS"""
                    try:
                        full_cmd = ['runuser', '-u', user, '--'] + cmd
                        
                        env = os.environ.copy()
                        env['DISPLAY'] = display
                        env['HOME'] = f'/home/{user}'
                        env['XAUTHORITY'] = f'/home/{user}/.Xauthority'
                        
                        # Устанавливаем D-BUS адрес только если он рабочий
                        if dbus_addr:
                            env['DBUS_SESSION_BUS_ADDRESS'] = dbus_addr
                        
                        # Очищаем проблемные переменные
                        env.pop('LD_LIBRARY_PATH', None)
                        
                        result = subprocess.run(
                            full_cmd, 
                            env=env,
                            timeout=timeout,
                            capture_output=True,
                            text=True
                        )
                        return result
                    except Exception as e:
                        logging.error(f"Ошибка runuser: {e}")
                        return None

                # Попытка 1: с проверенным D-BUS адресом
                command = [
                    '/usr/bin/notify-send', '--icon=dialog-information', 
                    'Сообщение от администратора', message
                ]
                
                result = run_as_user_with_dbus(user, display, uid, dbus_address, command, timeout=5)

                if result and result.returncode == 0:
                    logging.info("Уведомление успешно отправлено")
                    return {"message_result": "success", "info": f"✅ Сообщение отправлено пользователю {user}"}
                
                # Если не сработало, пробуем без D-BUS (автодетект системой)
                if result:
                    logging.warning(f"С D-BUS не сработало: {result.stderr.strip()}")
                
                # Попытка 2: без указания D-BUS (система сама найдет)
                result2 = run_as_user_with_dbus(user, display, uid, None, command, timeout=5)
                
                if result2 and result2.returncode == 0:
                    logging.info("Уведомление успешно отправлено (без D-BUS)")
                    return {"message_result": "success", "info": f"✅ Сообщение отправлено пользователю {user}"}

                return {
                    "message_result": "error", 
                    "error": f"❌ Не удалось отправить уведомление пользователю {user}."
                }

            except Exception as e:
                return {"message_result": "error", "error": f"❌ Критическая ошибка: {str(e)}"}


    async def take_screenshot(self, force_quality=None):
        if platform.system() == "Windows":
            try:
                import pyautogui
            except ImportError:
                return {"error": "PyAutoGUI library not installed"}
            try:
                screenshot = pyautogui.screenshot()
                import io
                buf = io.BytesIO()
                quality = force_quality if force_quality is not None else self.client.screenshot_settings.get("quality", 85)
                screenshot.save(buf, format='JPEG', quality=quality)
                img_data = buf.getvalue()
                return {
                    "screenshot": base64.b64encode(img_data).decode(),
                    "quality": quality,
                    "timestamp": datetime.now().isoformat()
                }
            except Exception as e:
                return {"error": f"❌ Ошибка: {str(e)}"}
        else:
            logging.info("📸 Попытка создания скриншота...")

            def _find_active_session():
                """Находит активную графическую сессию и пользователя."""
                # Сначала пробуем новый метод для Astra 1.8
                try:
                    p = subprocess.run(['loginctl', 'list-sessions'], capture_output=True, text=True)
                    for line in p.stdout.split('\n'):
                        if 'seat0' in line or 'graphical' in line:
                            parts = line.split()
                            if len(parts) >= 3:
                                session_id = parts[0]
                                user = parts[2]
                                
                                info_cmd = ['loginctl', 'show-session', session_id, '-p', 'Display', '-p', 'User', '-p', 'Active']
                                info = subprocess.run(info_cmd, capture_output=True, text=True)
                                if 'yes' in info.stdout:
                                    for info_line in info.stdout.split('\n'):
                                        if 'Display=' in info_line:
                                            display = info_line.split('=')[1]
                                        if 'User=' in info_line:
                                            uid = info_line.split('=')[1]
                                    if display and uid:
                                        return user, display, uid
                except Exception as e:
                    logging.warning(f"Ошибка поиска сессии через loginctl: {e}")

                # Старый метод для Astra 1.7 и fallback
                try:
                    p = subprocess.run(['who'], capture_output=True, text=True, check=True)
                    for line in p.stdout.strip().split('\n'):
                        if ':0' in line or ':1' in line or '(:' in line:
                            parts = line.split()
                            user = parts[0]
                            display = ':0'
                            
                            for part in parts:
                                if part.startswith('(:') or (part.startswith(':') and len(part) > 1):
                                    display = part.strip('()')
                                    break
                            
                            try:
                                uid_proc = subprocess.run(['id', '-u', user], capture_output=True, text=True)
                                if uid_proc.returncode == 0:
                                    uid = uid_proc.stdout.strip()
                                    return user, display, uid
                            except:
                                continue
                except Exception:
                    pass
                
                return None, None, None

            def run_as_user_astra18(user, display, uid, cmd, timeout=15, capture_output=True):
                """Для Astra Linux 1.8 - используем runuser"""
                try:
                    full_cmd = ['runuser', '-u', user, '--'] + cmd
                    
                    env = os.environ.copy()
                    env['DISPLAY'] = display
                    env['XAUTHORITY'] = f'/home/{user}/.Xauthority'
                    env['HOME'] = f'/home/{user}'
                    env['DBUS_SESSION_BUS_ADDRESS'] = f'unix:path=/run/user/{uid}/bus'
                    
                    # Очищаем проблемные переменные
                    env.pop('LD_LIBRARY_PATH', None)
                    
                    if capture_output:
                        result = subprocess.run(
                            full_cmd, 
                            env=env,
                            timeout=timeout,
                            capture_output=True  # Используем только capture_output
                        )
                    else:
                        result = subprocess.run(
                            full_cmd, 
                            env=env,
                            timeout=timeout,
                            capture_output=False
                        )
                    return result
                except Exception as e:
                    logging.error(f"Ошибка runuser: {e}")
                    return None

            def run_as_user_astra17(user, display, uid, cmd, timeout=15, capture_output=True):
                """Для Astra Linux 1.7 - используем sudo"""
                try:
                    full_cmd = [
                        'sudo', '-u', user,
                        'env', f'DISPLAY={display}', f'XAUTHORITY=/home/{user}/.Xauthority',
                        f'HOME=/home/{user}', f'DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/{uid}/bus'
                    ] + cmd
                    
                    if capture_output:
                        result = subprocess.run(
                            full_cmd,
                            timeout=timeout,
                            capture_output=True  # Используем только capture_output
                        )
                    else:
                        result = subprocess.run(
                            full_cmd,
                            timeout=timeout,
                            capture_output=False
                        )
                    return result
                except Exception as e:
                    logging.error(f"Ошибка sudo: {e}")
                    return None

            def run_as_user_auto(user, display, uid, cmd, timeout=15, capture_output=True):
                """Автоматически выбирает метод в зависимости от версии Astra"""
                # Пробуем сначала runuser (Astra 1.8)
                result = run_as_user_astra18(user, display, uid, cmd, timeout, capture_output)
                if result is not None and (not capture_output or result.returncode == 0):
                    return result
                
                # Если runuser не сработал, пробуем sudo (Astra 1.7)
                logging.info("🔄 runuser не сработал, пробуем sudo...")
                return run_as_user_astra17(user, display, uid, cmd, timeout, capture_output)

            try:
                quality = force_quality if force_quality is not None else self.client.screenshot_settings["quality"]
                user, display, uid = _find_active_session()
                if not (user and display and uid):
                    return {"error": "❌ Не найдено активной графической сессии"}

                # Даем доступ к X11
                try:
                    subprocess.run(["xhost", "+SI:localuser:root"], timeout=5, capture_output=False)
                    subprocess.run(["xhost", "+SI:localuser:" + user], timeout=5, capture_output=False)
                    subprocess.run(["xhost", "+"], timeout=5, capture_output=False)
                except:
                    pass

                # Метод 1: import напрямую в stdout (без файлов)
                try:
                    import_cmd = ['import', '-window', 'root', 'png:-']
                    result = run_as_user_auto(user, display, uid, import_cmd, timeout=15, capture_output=True)
                    
                    if result and result.returncode == 0 and result.stdout:
                        img_data = result.stdout
                        
                        # Если нужно сжать качество, используем convert в памяти
                        if quality < 100:
                            convert_cmd = ['convert', 'png:-', '-quality', str(quality), 'jpg:-']
                            convert_result = run_as_user_auto(user, display, uid, convert_cmd, timeout=10, capture_output=True)
                            
                            if convert_result and convert_result.returncode == 0 and convert_result.stdout:
                                img_data = convert_result.stdout
                        
                        return {
                            "screenshot": base64.b64encode(img_data).decode(),
                            "quality": quality,
                            "timestamp": datetime.now().isoformat()
                        }
                except Exception as e:
                    logging.warning(f"Метод скриншота (import в память) не удался: {e}")

                # Метод 2: xwd в stdout
                try:
                    xwd_cmd = ['xwd', '-root', '-silent']
                    result = run_as_user_auto(user, display, uid, xwd_cmd, timeout=15, capture_output=True)
                    
                    if result and result.returncode == 0 and result.stdout:
                        # Конвертируем xwd в png в памяти
                        convert_cmd = ['convert', 'xwd:-', 'png:-']
                        convert_result = run_as_user_auto(user, display, uid, convert_cmd, timeout=10, capture_output=True)
                        
                        if convert_result and convert_result.returncode == 0 and convert_result.stdout:
                            img_data = convert_result.stdout
                            return {
                                "screenshot": base64.b64encode(img_data).decode(),
                                "quality": quality,
                                "timestamp": datetime.now().isoformat()
                            }
                            
                except Exception as e:
                    logging.warning(f"Метод скриншота (xwd в память) не удался: {e}")

                # Метод 3: ffmpeg в stdout (самый эффективный)
                if shutil.which("ffmpeg"):
                    try:
                        ffmpeg_cmd = [
                            'ffmpeg', '-f', 'x11grab', '-video_size', '1920x1080', '-i', display,
                            '-vframes', '1', '-q:v', str(max(1, 31 - quality // 3)), 
                            '-f', 'image2pipe', '-c:v', 'mjpeg', '-'
                        ]
                        
                        result = run_as_user_auto(user, display, uid, ffmpeg_cmd, timeout=15, capture_output=True)
                        
                        if result and result.returncode == 0 and result.stdout:
                            img_data = result.stdout
                            return {
                                "screenshot": base64.b64encode(img_data).decode(),
                                "quality": quality,
                                "timestamp": datetime.now().isoformat()
                            }
                            
                    except Exception as e:
                        logging.warning(f"Метод скриншота (ffmpeg в память) не удался: {e}")

                # Метод 4: scrot в stdout (если установлен)
                if shutil.which("scrot"):
                    try:
                        scrot_cmd = ['scrot', '-o', '-']
                        result = run_as_user_auto(user, display, uid, scrot_cmd, timeout=10, capture_output=True)
                        
                        if result and result.returncode == 0 and result.stdout:
                            img_data = result.stdout
                            
                            # Сжимаем если нужно
                            if quality < 100:
                                convert_cmd = ['convert', 'png:-', '-quality', str(quality), 'jpg:-']
                                convert_result = run_as_user_auto(user, display, uid, convert_cmd, timeout=5, capture_output=True)
                                
                                if convert_result and convert_result.returncode == 0 and convert_result.stdout:
                                    img_data = convert_result.stdout
                            
                            return {
                                "screenshot": base64.b64encode(img_data).decode(),
                                "quality": quality,
                                "timestamp": datetime.now().isoformat()
                            }
                            
                    except Exception as e:
                        logging.warning(f"Метод скриншота (scrot) не удался: {e}")

                # Метод 5: gnome-screenshot в stdout (для GNOME)
                try:
                    gnome_cmd = ['gnome-screenshot', '-f', '-', '--include-pointer']
                    result = run_as_user_auto(user, display, uid, gnome_cmd, timeout=10, capture_output=True)
                    
                    if result and result.returncode == 0 and result.stdout:
                        img_data = result.stdout
                        
                        if quality < 100:
                            convert_cmd = ['convert', 'png:-', '-quality', str(quality), 'jpg:-']
                            convert_result = run_as_user_auto(user, display, uid, convert_cmd, timeout=5, capture_output=True)
                            
                            if convert_result and convert_result.returncode == 0 and convert_result.stdout:
                                img_data = convert_result.stdout
                        
                        return {
                            "screenshot": base64.b64encode(img_data).decode(),
                            "quality": quality,
                            "timestamp": datetime.now().isoformat()
                        }
                except Exception as e:
                    logging.warning(f"Метод скриншота (gnome-screenshot) не удался: {e}")

                return {"error": "❌ Все методы создания скриншота не удались"}

            except Exception as e:
                logging.error(f"Критическая ошибка создания скриншота: {e}")
                return {"error": f"❌ Ошибка создания скриншота: {str(e)}"}
