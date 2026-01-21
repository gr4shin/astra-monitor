import asyncio
import os
import pty
import termios
import struct
import fcntl
import sys
import json
import logging


class InteractiveShell:
    def __init__(self, client):
        self.client = client
        self.session = None
        self._read_task = None

    async def handle(self, websocket, action, payload):
        if action == "start":
            return await self._start(websocket, payload)
        if action == "input":
            return await self._input(websocket, payload)
        if action == "stop":
            return await self._stop(websocket)
        if action == "resize":
            return await self._resize(payload)
        return {"interactive_error": f"Unknown interactive action: {action}"}

    async def _start(self, websocket, cmd):
        logging.info("-> ⏯️ Получена команда interactive:start.")
        if self.session:
            logging.warning("-> ⚠️ Интерактивная сессия уже запущена, очистка старой.")
            await self.cleanup(websocket)

        pid, fd = pty.fork()
        if pid == 0:
            try:
                os.environ.pop('LD_LIBRARY_PATH', None)
                os.environ.pop('PYTHONPATH', None)
                os.environ.pop('PYINSTALLER_CONFIG_DIR', None)
                os.environ['LD_LIBRARY_PATH'] = ''
                os.environ.setdefault('TERM', 'xterm-256color')
                os.environ.setdefault('LANG', 'C.UTF-8')
                args = cmd.split()
                os.execvp(args[0], args)
            except Exception as e:
                os.write(sys.stdout.fileno(), str(e).encode())
                sys.exit(1)
        else:
            self.session = {"pid": pid, "fd": fd}
            fl = fcntl.fcntl(fd, fcntl.F_GETFL)
            fcntl.fcntl(fd, fcntl.F_SETFL, fl | os.O_NONBLOCK)
            self._read_task = asyncio.create_task(self._read_and_forward(websocket, fd))
            return {"interactive_started": True}

    async def _input(self, websocket, data):
        if not self.session:
            return {"interactive_error": "No interactive session is running."}
        fd = self.session["fd"]
        try:
            os.write(fd, data.encode())
        except (BrokenPipeError, OSError):
            await self.cleanup(websocket)
        return None

    async def _stop(self, websocket):
        if not self.session:
            return {"interactive_error": "No interactive session is running."}
        await self.cleanup(websocket)
        return {"interactive_stopped": True}

    async def _resize(self, payload):
        if not self.session:
            return {"interactive_error": "No interactive session is running."}
        rows, cols = map(int, payload.split(','))
        winsize = struct.pack("HHHH", rows, cols, 0, 0)
        fcntl.ioctl(self.session["fd"], termios.TIOCSWINSZ, winsize)
        return None

    async def _read_and_forward(self, websocket, fd):
        try:
            while self.session and self.session.get("fd") == fd:
                try:
                    await asyncio.sleep(0.01)
                    data = os.read(fd, 1024)
                    if not data:
                        break
                    async with self.client.send_lock:
                        await websocket.send(json.dumps({"interactive_output": {"data": data.decode(errors='replace')}}))
                except BlockingIOError:
                    continue
                except OSError:
                    break
        finally:
            await self.cleanup(websocket)

    async def cleanup(self, websocket=None):
        if not self.session:
            return

        session = self.session
        self.session = None

        pid = session.get("pid")
        fd = session.get("fd")
        if pid:
            try:
                os.kill(pid, 15)
            except ProcessLookupError:
                pass
        if fd:
            try:
                os.close(fd)
            except OSError:
                pass

        if self._read_task and not self._read_task.done():
            self._read_task.cancel()
        self._read_task = None

        if websocket:
            try:
                async with self.client.send_lock:
                    await websocket.send(json.dumps({"interactive_stopped": True}))
            except Exception:
                pass
