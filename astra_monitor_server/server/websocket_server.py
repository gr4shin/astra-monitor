# astra_monitor_server/server/websocket_server.py

import asyncio
import json
import os
import base64
import websockets
from PyQt5.QtCore import QObject, pyqtSignal
import uuid
import hashlib

# Используем относительный импорт для доступа к config.py
from ..config_loader import APP_CONFIG

class WebSocketServer(QObject):
    new_message = pyqtSignal(dict)
    new_connection = pyqtSignal(str)
    connection_lost = pyqtSignal(str)
    
    def __init__(self, host, port, max_size=100 * 1024 * 1024):
        super().__init__()
        self.host = host
        self.port = port
        self.clients = {}
        self.pending_acks = {}
        self.server = None
        self.loop = None
        self.max_size = max_size
        
    def start_server(self):
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)

        async def _start_server():
            self.server = await websockets.serve(
                self.handler, self.host, self.port,
                max_size=self.max_size,
                ping_interval=30,      # Отправлять пинг каждые 30 секунд
                ping_timeout=60        # Ожидать понг в течение 60 секунд
            )
            print(f"Server started on ws://{self.host}:{self.port} with max_size={self.max_size / 1024 / 1024:.0f}MB")

        self.loop.run_until_complete(_start_server())
        self.loop.run_forever()
        
    async def handler(self, websocket):
        client_ip = websocket.remote_address[0]
        client_port = websocket.remote_address[1]
        client_id = f"{client_ip}:{client_port}"
        
        try:
            # Ждем аутентификации в течение 10 секунд
            try:
                auth_message = await asyncio.wait_for(websocket.recv(), timeout=10.0)
                data = json.loads(auth_message)
                
                # Проверяем токен аутентификации
                if 'auth_token' not in data or data.get('auth_token') != APP_CONFIG['AUTH_TOKEN']:
                    print(f"❌ Неверный токен от {client_id}")
                    await websocket.close(code=4001, reason="Invalid authentication token")
                    return
                    
                print(f"✅ Успешная аутентификация: {client_id}")
                
            except asyncio.TimeoutError:
                print(f"⏰ Таймаут аутентификации: {client_id}")
                await websocket.close(code=4002, reason="Authentication timeout")
                return
            except json.JSONDecodeError:
                print(f"Неверный JSON от {client_id}")
                await websocket.close(code=4003, reason="Invalid JSON format")
                return
            
            # Если аутентификация успешна - добавляем клиента
            client_info = data.get('client_info', {})
            auth_client_id = data.get('client_id')
            if isinstance(auth_client_id, str) and auth_client_id.strip():
                client_id = auth_client_id.strip()

            if 'protocol_version' in data:
                client_info['protocol_version'] = data.get('protocol_version')
            if 'capabilities' in data:
                client_info['capabilities'] = data.get('capabilities')

            old_ws = self.clients.get(client_id)
            if old_ws and old_ws.open:
                await old_ws.close(code=4000, reason="Replaced by new connection")

            self.clients[client_id] = websocket
            # Отправляем ID и информацию о клиенте для немедленного отображения
            self.new_connection.emit(json.dumps({
                'client_id': client_id,
                'client_info': client_info,
                'client_ip': client_ip,
                'client_port': client_port
            }))
            
            # Основной цикл обработки сообщений
            async for message in websocket:
                try:
                    # Выполняем парсинг JSON в отдельном потоке, чтобы не блокировать event loop
                    # при обработке очень больших сообщений (например, чанков файлов).
                    data = await self.loop.run_in_executor(None, json.loads, message)
                    data['client_id'] = client_id
                    data['client_ip'] = client_ip
                    if 'command_ack' in data:
                        command_id = data.get('command_ack')
                        event = self.pending_acks.get(command_id)
                        if event:
                            event.set()
                            self.pending_acks.pop(command_id, None)
                        continue
                    self.new_message.emit(data)
                except json.JSONDecodeError:
                    error_msg = {"error": "Invalid JSON", "message": message, "client_id": client_id}
                    self.new_message.emit(error_msg)
                    
        except websockets.exceptions.ConnectionClosed:
            print(f"Соединение закрыто: {client_id}")
        except Exception as e:
            print(f"⚠️  Ошибка обработчика: {client_id} - {e}")
        finally:
            if client_id in self.clients:
                del self.clients[client_id]
            self.connection_lost.emit(client_id)
            
    def stop_server(self):
        if self.loop and self.loop.is_running():
            self.loop.call_soon_threadsafe(self.loop.stop)
            
    async def send_command(self, client_id, command, expect_ack=False, ack_timeout=5, retries=0):
        if client_id in self.clients:
            try:
                command_id = uuid.uuid4().hex
                payload = {"command": command, "command_id": command_id}
                if not expect_ack:
                    await self.clients[client_id].send(json.dumps(payload))
                    return True

                event = asyncio.Event()
                self.pending_acks[command_id] = event
                for attempt in range(retries + 1):
                    await self.clients[client_id].send(json.dumps(payload))
                    try:
                        await asyncio.wait_for(event.wait(), timeout=ack_timeout)
                        return True
                    except asyncio.TimeoutError:
                        event.clear()
                        if attempt == retries:
                            break
                self.pending_acks.pop(command_id, None)
                return False
            except:
                self.connection_lost.emit(client_id)
                return False
        return False

    async def upload_file_to_client(self, client_id, local_path, remote_path):
        if client_id not in self.clients:
            return False
        try:
            file_size = os.path.getsize(local_path)
            await self.send_command(client_id, f"upload_file_start:{remote_path}:{file_size}")

            hasher = hashlib.sha256()
            with open(local_path, 'rb') as f:
                while True:
                    chunk = f.read(4 * 1024 * 1024) # 4MB chunks
                    if not chunk:
                        break
                    hasher.update(chunk)
                    chunk_b64 = base64.b64encode(chunk).decode('ascii')
                    await self.send_command(client_id, f"upload_file_chunk:{chunk_b64}")
            
            await self.send_command(client_id, f"upload_file_end:{hasher.hexdigest()}")
            return True
        except Exception as e:
            print(f"Error uploading file: {e}")
            return False
            
    async def client_disconnect(self, client_id):
        if client_id in self.clients:
            try:
                await self.clients[client_id].close()
                return True
            except:
                self.connection_lost.emit(client_id)
                return False
        return False
