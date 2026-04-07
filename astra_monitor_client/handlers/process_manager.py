# Полностью исправленный process_manager.py

import asyncio
import json
import logging
import os
import signal
import subprocess
import shutil
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, Any

class ManagedProcess:
    """Класс для управления отдельным процессом"""
    
    def __init__(self, process_id: str, command: str, work_dir: Path):
        self.process_id = process_id
        self.command = command
        self.work_dir = work_dir
        self.pid_file = work_dir / f"{process_id}.pid"
        self.log_file = work_dir / f"{process_id}.log"
        self.script_file = work_dir / f"{process_id}.sh"
        self.status_file = work_dir / f"{process_id}.status"
        
        self.process: Optional[asyncio.subprocess.Process] = None
        self.reader_task: Optional[asyncio.Task] = None
        self.start_time: Optional[datetime] = None
        self.end_time: Optional[datetime] = None
        self.returncode: Optional[int] = None
        
    def save_status(self, status: str, message: str = ""):
        """Сохраняет статус процесса"""
        status_data = {
            "status": status,
            "message": message,
            "pid": self.get_pid(),
            "start_time": self.start_time.isoformat() if self.start_time else None,
            "end_time": self.end_time.isoformat() if self.end_time else None,
            "returncode": self.returncode
        }
        try:
            self.status_file.write_text(json.dumps(status_data, indent=2))
        except:
            pass
        
    def get_pid(self) -> Optional[int]:
        """Получает PID процесса из файла"""
        try:
            if self.pid_file.exists():
                return int(self.pid_file.read_text().strip())
        except:
            pass
        return None
        
    def is_running(self) -> bool:
        """Проверяет, жив ли процесс"""
        pid = self.get_pid()
        if pid:
            try:
                os.kill(pid, 0)
                return True
            except (ProcessLookupError, PermissionError):
                pass
        return False
        
    def cleanup(self):
        """Очищает временные файлы"""
        for file in [self.pid_file, self.script_file, self.status_file]:
            try:
                if file.exists():
                    file.unlink()
            except:
                pass


class ProcessManager:
    """Менеджер фоновых процессов с возможностью подключения"""
    
    def __init__(self, work_dir: str = "/tmp/astra_monitor_processes"):
        self.work_dir = Path(work_dir)
        self.work_dir.mkdir(exist_ok=True, mode=0o755)
        
        self.processes: Dict[str, ManagedProcess] = {}
        self.active_readers: Dict[str, asyncio.Task] = {}
        
        logging.info(f"ProcessManager инициализирован, рабочая директория: {self.work_dir}")
        
    def generate_id(self) -> str:
        """Генерирует уникальный ID для процесса"""
        return f"proc_{int(time.time())}_{uuid.uuid4().hex[:8]}"
        
    async def start_process(
        self, 
        command: str, 
        process_id: Optional[str] = None,
        capture_output: bool = True,
        websocket = None,
        message_key: str = "process_output",
        result_key: str = "process_result"
    ) -> str:
        """
        Запускает процесс в фоне с возможностью отслеживания
        """
        if not process_id:
            process_id = self.generate_id()
            
        # Создаем объект управляемого процесса
        proc = ManagedProcess(process_id, command, self.work_dir)
        self.processes[process_id] = proc
        proc.start_time = datetime.now()
        
        # Создаем скрипт-обертку
        script_content = self._create_wrapper_script(proc)
        proc.script_file.write_text(script_content)
        proc.script_file.chmod(0o755)
        
        # Создаем пустой лог файл
        proc.log_file.touch()
        
        # Запускаем процесс
        try:
            # Всегда используем bash с nohup для надежности
            cmd = ['nohup', 'bash', str(proc.script_file)]
            
            logging.info(f"Запуск команды: {' '.join(cmd)}")
            
            subprocess.Popen(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                stdin=subprocess.DEVNULL,
                start_new_session=True
            )
            
            # Ждем создания PID файла (увеличим время ожидания)
            for _ in range(30):  # 3 секунды
                if proc.pid_file.exists():
                    pid = proc.get_pid()
                    logging.info(f"PID файл создан, PID: {pid}")
                    break
                await asyncio.sleep(0.1)
            
            if not proc.pid_file.exists():
                logging.warning(f"PID файл не создан для {process_id}, но продолжаем")
                # Вручную ищем процесс по имени скрипта
                try:
                    result = subprocess.run(
                        ['pgrep', '-f', str(proc.script_file)],
                        capture_output=True, text=True
                    )
                    if result.stdout.strip():
                        pid = int(result.stdout.strip())
                        proc.pid_file.write_text(str(pid))
                        logging.info(f"PID {pid} найден через pgrep")
                except Exception as e:
                    logging.error(f"Не удалось найти PID: {e}")
            
            proc.save_status("running", "Процесс запущен")
            
            logging.info(f"Процесс {process_id} запущен: {command[:100]}")
            
            # Запускаем мониторинг лога если нужно
            if capture_output and websocket:
                reader_task = asyncio.create_task(
                    self._monitor_log_file(proc, websocket, message_key, result_key)
                )
                self.active_readers[process_id] = reader_task
            
            # Отправляем сообщение о запуске
            if websocket:
                try:
                    await self._send_process_status(websocket, process_id, {
                        "status": "running",
                        "pid": proc.get_pid(),
                        "command": command[:100],
                        "start_time": proc.start_time.isoformat()
                    })
                except Exception as e:
                    logging.error(f"Ошибка отправки сообщения о запуске: {e}")
            
            return process_id
            
        except Exception as e:
            logging.error(f"Ошибка запуска процесса {process_id}: {e}")
            proc.save_status("failed", str(e))
            proc.cleanup()
            del self.processes[process_id]
            raise   
            
    async def _send_process_status(self, websocket, process_id, status_data):
        """Отправляет статус процесса на сервер"""
        try:
            await websocket.send(json.dumps({
                "apt_process_status": status_data,
                "process_id": process_id
            }))
        except Exception as e:
            logging.error(f"Ошибка отправки статуса: {e}")
        
            
            
    def _create_wrapper_script(self, proc: ManagedProcess) -> str:
        """Создает скрипт-обертку с перенаправлением вывода в файл"""
        return f"""#!/bin/bash
# Процесс {proc.process_id}
# Запущен: {proc.start_time}

# Сохраняем PID
echo $$ > {proc.pid_file}

# Функция для логирования
log() {{
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1" >> {proc.log_file}
}}

log "=== START ==="
log "PID: $$"
log "Команда: {proc.command}"
log "PATH: $PATH"
log "USER: $(whoami)"

# Проверяем sudo доступ
sudo -n true 2>/dev/null
if [ $? -eq 0 ]; then
    log "SUDO: доступ есть"
else
    log "SUDO: доступа нет или нужен пароль"
fi

# Запускаем команду с перенаправлением вывода
log "=== OUTPUT START ==="

# Выполняем команду
{proc.command} >> {proc.log_file} 2>&1

EXIT_CODE=$?

log "=== OUTPUT END ==="
log "Код выхода: $EXIT_CODE"
echo "[EXIT_CODE:$EXIT_CODE]" >> {proc.log_file}

exit $EXIT_CODE
"""
            
    async def _monitor_log_file(
        self, 
        proc: ManagedProcess, 
        websocket, 
        message_key: str, 
        result_key: str
    ):
        """Мониторит лог файл процесса и отправляет новые строки в WebSocket"""
        last_position = 0
        send_lock = self._get_send_lock(websocket)
        exit_code = None
        
        logging.info(f"Начат мониторинг лога для {proc.process_id}")
        
        # Проверим содержимое лога сразу
        if proc.log_file.exists():
            with open(proc.log_file, 'r') as f:
                content = f.read()
                logging.info(f"Начальное содержимое лога {proc.process_id}: {content[:200]}")
        
        while True:
            try:
                if proc.log_file.exists():
                    with open(proc.log_file, 'r', encoding='utf-8', errors='replace') as f:
                        f.seek(last_position)
                        new_content = f.read()
                        last_position = f.tell()
                        
                        if new_content:
                            logging.info(f"Новый вывод для {proc.process_id}: {len(new_content)} байт")
                            # Разбиваем на строки и отправляем
                            for line in new_content.split('\n'):
                                if line.strip():
                                    # Проверяем на код выхода
                                    if line.startswith("[EXIT_CODE:"):
                                        exit_code = line[11:-1]
                                        try:
                                            proc.returncode = int(exit_code)
                                        except:
                                            proc.returncode = -1
                                        proc.end_time = datetime.now()
                                        proc.save_status("completed", f"Завершен с кодом {exit_code}")
                                        
                                        logging.info(f"Процесс {proc.process_id} завершен с кодом {exit_code}")
                                        
                                        try:
                                            async with send_lock:
                                                await self._send_process_status(websocket, proc.process_id, {
                                                    "status": "completed",
                                                    "returncode": proc.returncode,
                                                    "end_time": proc.end_time.isoformat() if proc.end_time else None
                                                })
                                        except Exception as e:
                                            logging.error(f"Ошибка отправки результата: {e}")
                                        return  # Выходим из функции
                                    else:
                                        # Отправляем обычный вывод
                                        try:
                                            async with send_lock:
                                                await websocket.send(json.dumps({
                                                    message_key: line + '\n',
                                                    "process_id": proc.process_id
                                                }))
                                        except Exception as e:
                                            logging.error(f"Ошибка отправки вывода: {e}")
                
                # Проверяем жив ли процесс
                if not proc.is_running():
                    pid = proc.get_pid()
                    if pid is None:
                        logging.warning(f"Процесс {proc.process_id} не создал PID файл")
                        # Отправляем сообщение об ошибке
                        try:
                            async with send_lock:
                                await websocket.send(json.dumps({
                                    result_key: f"❌ Процесс не смог запуститься. Проверьте лог: {proc.log_file}",
                                    "process_id": proc.process_id,
                                    "original_command": proc.command
                                }))
                        except:
                            pass
                        break
                    elif exit_code is None:
                        # Процесс завершился, но мы не получили EXIT_CODE
                        logging.warning(f"Процесс {proc.process_id} завершился без EXIT_CODE")
                        break
                
                await asyncio.sleep(0.5)
                
            except Exception as e:
                logging.error(f"Ошибка мониторинга лога {proc.process_id}: {e}")
                await asyncio.sleep(0.5)
        
        logging.info(f"Мониторинг лога для {proc.process_id} завершен")
        await self._cleanup_process(proc.process_id)
    
    async def get_processes_status(self, websocket):
        """Отправляет список всех процессов на сервер"""
        processes = await self.list_processes()
        try:
            await websocket.send(json.dumps({
                "apt_processes": processes.get("processes", {}),
                "count": processes.get("count", 0)
            }))
        except Exception as e:
            logging.error(f"Ошибка отправки списка процессов: {e}")
    
    def _get_send_lock(self, websocket):
        """Получает блокировку для отправки сообщений"""
        if hasattr(websocket, 'send_lock'):
            return websocket.send_lock
        # Создаем временную заглушку
        class DummyLock:
            async def __aenter__(self): return None
            async def __aexit__(self, *args): pass
        return DummyLock()
        
    async def attach_to_process(
        self, 
        process_id: str, 
        websocket,
        message_key: str = "process_output",
        result_key: str = "process_result"
    ) -> bool:
        """Подключается к запущенному процессу для мониторинга"""
        proc = self.processes.get(process_id)
        if not proc:
            proc = await self._recover_process(process_id)
            if not proc:
                return False
                
        if not proc.is_running():
            await self._cleanup_process(process_id)
            send_lock = self._get_send_lock(websocket)
            async with send_lock:
                await websocket.send(json.dumps({
                    result_key: f"❌ Процесс {process_id} не найден или уже завершен",
                    "process_id": process_id
                }))
            return False
            
        if process_id in self.active_readers:
            self.active_readers[process_id].cancel()
            
        reader_task = asyncio.create_task(
            self._monitor_log_file(proc, websocket, message_key, result_key)
        )
        self.active_readers[process_id] = reader_task
        
        # Отправляем последние строки лога
        if proc.log_file.exists():
            try:
                with open(proc.log_file, 'r') as f:
                    lines = f.readlines()
                    last_lines = lines[-50:] if len(lines) > 50 else lines
                    if last_lines:
                        send_lock = self._get_send_lock(websocket)
                        async with send_lock:
                            await websocket.send(json.dumps({
                                message_key: f"\n--- Лог процесса {process_id} ---\n" + ''.join(last_lines),
                                "process_id": process_id
                            }))
            except:
                pass
                
        return True
        
    async def _recover_process(self, process_id: str) -> Optional[ManagedProcess]:
        """Восстанавливает процесс из файлов"""
        proc = ManagedProcess(process_id, "", self.work_dir)
        
        if proc.pid_file.exists() and proc.is_running():
            if proc.script_file.exists():
                script_content = proc.script_file.read_text()
                for line in script_content.split('\n'):
                    if 'Команда:' in line:
                        proc.command = line.split('Команда:')[1].strip()
                        break
                        
            if proc.status_file.exists():
                try:
                    status = json.loads(proc.status_file.read_text())
                    if status.get('start_time'):
                        proc.start_time = datetime.fromisoformat(status['start_time'])
                except:
                    proc.start_time = datetime.fromtimestamp(proc.pid_file.stat().st_ctime)
            else:
                proc.start_time = datetime.fromtimestamp(proc.pid_file.stat().st_ctime)
                
            self.processes[process_id] = proc
            proc.save_status("running", "Восстановлен")
            logging.info(f"Процесс {process_id} восстановлен")
            return proc
            
        return None
        
    async def send_signal(self, process_id: str, signal_num: int = signal.SIGTERM) -> bool:
        """Отправляет сигнал процессу"""
        proc = self.processes.get(process_id)
        if not proc:
            return False
            
        pid = proc.get_pid()
        if pid:
            try:
                os.kill(pid, signal_num)
                return True
            except ProcessLookupError:
                pass
        return False
        
    async def stop_process(self, process_id: str, force: bool = False) -> bool:
        """Останавливает процесс"""
        proc = self.processes.get(process_id)
        if not proc:
            return False
            
        if await self.send_signal(process_id, signal.SIGTERM):
            for _ in range(50):
                if not proc.is_running():
                    break
                await asyncio.sleep(0.1)
                
        if force and proc.is_running():
            await self.send_signal(process_id, signal.SIGKILL)
            
        await self._cleanup_process(process_id)
        return True
        
    async def get_process_status(self, process_id: str) -> Dict[str, Any]:
        """Получает статус процесса"""
        proc = self.processes.get(process_id)
        if not proc:
            proc = await self._recover_process(process_id)
            if not proc:
                return {"status": "not_found", "process_id": process_id}
                
        status_data = {
            "process_id": process_id,
            "status": "running" if proc.is_running() else "stopped",
            "command": proc.command[:100] if proc.command else "",
            "start_time": proc.start_time.isoformat() if proc.start_time else None,
            "end_time": proc.end_time.isoformat() if proc.end_time else None,
            "pid": proc.get_pid(),
            "returncode": proc.returncode
        }
        
        if proc.status_file.exists():
            try:
                saved_status = json.loads(proc.status_file.read_text())
                status_data.update(saved_status)
            except:
                pass
                
        return status_data
        
    async def list_processes(self) -> Dict[str, Any]:
        """Список всех процессов"""
        for pid_file in self.work_dir.glob("*.pid"):
            process_id = pid_file.stem
            if process_id not in self.processes:
                await self._recover_process(process_id)
                
        processes_status = {}
        for process_id, proc in self.processes.items():
            processes_status[process_id] = {
                "status": "running" if proc.is_running() else "stopped",
                "command": proc.command[:100] + "..." if proc.command and len(proc.command) > 100 else proc.command,
                "start_time": proc.start_time.isoformat() if proc.start_time else None
            }
            
        return {"processes": processes_status, "count": len(processes_status)}
        
    async def _cleanup_process(self, process_id: str):
        """Очищает ресурсы процесса"""
        if process_id in self.active_readers:
            self.active_readers[process_id].cancel()
            del self.active_readers[process_id]
            
        proc = self.processes.get(process_id)
        if proc:
            proc.cleanup()
            del self.processes[process_id]
            
    async def cleanup_all(self):
        """Очищает все ресурсы"""
        for process_id in list(self.processes.keys()):
            await self._cleanup_process(process_id)