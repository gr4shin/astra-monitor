import os
import re
import json
import uuid
import time
import base64
import shutil
import logging
import subprocess
from datetime import datetime, timedelta
from pathlib import Path

from astra_monitor_client.utils.system_utils import capture_camera_snapshot


class EvidenceHandler:
    def __init__(self, client):
        self.client = client
        self.pending_reports = []
        self.last_report_time = {}
        self.load_settings()
        self._ensure_store_dir()
        self._load_pending_reports()

    def load_settings(self):
        evidence_settings = self.client.settings.get("evidence", {})
        if not isinstance(evidence_settings, dict):
            evidence_settings = {}

        self.enabled = bool(evidence_settings.get("enabled", False))
        self.check_interval = max(5, int(evidence_settings.get("interval", 10)))
        self.camera_enabled = bool(evidence_settings.get("camera_enabled", False))
        self.min_report_interval = max(60, int(evidence_settings.get("min_report_interval", 300)))
        self.retention_days = max(1, int(evidence_settings.get("retention_days", 30)))
        self.store_dir = os.path.expanduser(evidence_settings.get("store_dir", "~/.astra_monitor_client/evidence"))

        raw_blacklist = evidence_settings.get("monitor_blacklist", [
            "firefox", "chrome", "google-chrome", "chromium", "steam", "wine", "playonlinux",
            "lutris", "discord", "minecraft", "thunderbird", "skype", "opera", "brave"
        ])
        if isinstance(raw_blacklist, str):
            raw_blacklist = [raw_blacklist]
        self.monitor_blacklist = [entry.strip().lower() for entry in raw_blacklist if entry and isinstance(entry, str)]

        raw_suspicious = evidence_settings.get("suspicious_patterns", [
            "sudo", "su", "passwd", "chage", "usermod", "groupadd", "groupdel", "useradd", "userdel",
            "visudo", "sudoedit", "ssh", "scp", "sftp", "nc", "netcat", "nmap", "tcpdump",
            "iptables", "ufw", "systemctl", "journalctl", "dmesg", "mount", "umount"
        ])
        if isinstance(raw_suspicious, str):
            raw_suspicious = [raw_suspicious]
        self.suspicious_patterns = [entry.strip().lower() for entry in raw_suspicious if entry and isinstance(entry, str)]

    def _ensure_store_dir(self):
        try:
            os.makedirs(self.store_dir, exist_ok=True)
        except Exception as e:
            logging.warning("Не удалось создать каталог для доказательств: %s", e)

    def _load_pending_reports(self):
        if not os.path.isdir(self.store_dir):
            return

        for entry in sorted(os.scandir(self.store_dir), key=lambda x: x.name):
            if not entry.is_dir():
                continue
            metadata_path = os.path.join(entry.path, "metadata.json")
            if not os.path.exists(metadata_path):
                continue
            try:
                with open(metadata_path, "r", encoding="utf-8") as f:
                    report = json.load(f)
                if report.get("sent"):
                    continue
                report["storage_path"] = entry.path
                screenshot_path = os.path.join(entry.path, "screenshot.jpg")
                if os.path.exists(screenshot_path) and not report.get("screenshot"):
                    try:
                        with open(screenshot_path, "rb") as f:
                            report["screenshot"] = base64.b64encode(f.read()).decode()
                    except Exception:
                        pass
                camera_path = os.path.join(entry.path, "camera.jpg")
                if os.path.exists(camera_path) and not report.get("camera_snapshot"):
                    try:
                        with open(camera_path, "rb") as f:
                            report["camera_snapshot"] = base64.b64encode(f.read()).decode()
                    except Exception:
                        pass
                self.pending_reports.append(report)
            except Exception:
                continue

    def update_settings(self):
        self.load_settings()
        self._ensure_store_dir()

    def _cleanup_old_reports(self):
        if not os.path.isdir(self.store_dir):
            return

        cutoff = datetime.now() - timedelta(days=self.retention_days)
        for entry in os.scandir(self.store_dir):
            if not entry.is_dir():
                continue
            try:
                stat = entry.stat()
                if datetime.fromtimestamp(stat.st_mtime) < cutoff:
                    shutil.rmtree(entry.path, ignore_errors=True)
            except Exception:
                pass

    def _find_suspicious_processes(self):
        suspicious = []
        if not self.monitor_blacklist:
            return suspicious

        try:
            result = subprocess.run(
                ["ps", "-eo", "pid=,comm=,args="],
                capture_output=True,
                text=True,
                check=True
            )
            current_pid = os.getpid()
            for line in result.stdout.splitlines():
                line = line.strip()
                if not line:
                    continue
                parts = line.split(None, 2)
                if len(parts) < 2:
                    continue
                pid = parts[0]
                command = parts[1]
                args = parts[2] if len(parts) > 2 else command
                if pid == str(current_pid):
                    continue

                normalized = f"{command} {args}".lower()
                matched = False
                for pattern in self.monitor_blacklist:
                    if not pattern:
                        continue
                    if re.search(rf"\b{re.escape(pattern)}\b", normalized):
                        suspicious.append({
                            "pid": pid,
                            "command": command,
                            "args": args,
                            "matched_keyword": pattern
                        })
                        matched = True
                        break
                if not matched:
                    for pattern in self.suspicious_patterns:
                        if not pattern:
                            continue
                        if pattern in ["/etc/", "/root", "/var/log", "/boot", "/proc", "/sys", "/dev"]:
                            if pattern in args.lower() and not re.search(rf"\b(systemd|dbus|Xorg|vmnet|wpa_supplicant|ssh-agent|gcr-ssh-agent|at-spi|kde|plasmashell)\b", normalized):
                                suspicious.append({
                                    "pid": pid,
                                    "command": command,
                                    "args": args,
                                    "matched_keyword": pattern
                                })
                                break
                        else:
                            if re.search(rf"\b{re.escape(pattern)}\b", normalized):
                                suspicious.append({
                                    "pid": pid,
                                    "command": command,
                                    "args": args,
                                    "matched_keyword": pattern
                                })
                                break
        except Exception as e:
            logging.warning("Не удалось просканировать процессы для доказательств: %s", e)
        return suspicious

    async def check_activity(self, websocket=None):
        if not self.enabled:
            return

        suspicious = self._find_suspicious_processes()
        now = time.time()
        new_reports = []

        for proc in suspicious:
            key = f"{proc['pid']}|{proc['command']}|{proc['matched_keyword']}"
            if now - self.last_report_time.get(key, 0) < self.min_report_interval:
                continue
            self.last_report_time[key] = now

            screenshot_data = await self.client.command_handler.screenshot_handler.take_screenshot()
            camera_snapshot = None
            if self.camera_enabled:
                logging.info("📷 Попытка захвата кадра с камеры для события %s PID %s", proc['command'], proc['pid'])
                camera_snapshot = capture_camera_snapshot()
                if camera_snapshot is None:
                    logging.warning("📷 Не удалось захватить кадр с камеры для %s (PID %s)", proc['command'], proc['pid'])
                else:
                    logging.info("📷 Кадр с камеры успешно снят для %s (PID %s)", proc['command'], proc['pid'])

            report = self._build_report(proc, screenshot_data, camera_snapshot)
            self.pending_reports.append(report)
            self._save_report_to_disk(report)
            new_reports.append(report)

            if websocket is not None:
                await self.send_report(websocket, report)

        self._cleanup_old_reports()
        return new_reports

    def _build_report(self, proc, screenshot_data, camera_snapshot):
        event_id = uuid.uuid4().hex
        timestamp = datetime.now().isoformat()
        description = (
            f"Обнаружен подозрительный процесс '{proc['command']}' "
            f"(PID {proc['pid']}), совпадение по ключу '{proc['matched_keyword']}'."
        )

        report = {
            "event_id": event_id,
            "event_type": "suspicious_process",
            "description": description,
            "timestamp": timestamp,
            "process": {
                "pid": proc["pid"],
                "command": proc["command"],
                "args": proc["args"],
                "matched_keyword": proc["matched_keyword"]
            },
            "screenshot": screenshot_data.get("screenshot") if isinstance(screenshot_data, dict) else None,
            "screenshot_quality": screenshot_data.get("quality") if isinstance(screenshot_data, dict) else None,
            "camera_snapshot": base64.b64encode(camera_snapshot).decode() if camera_snapshot else None,
            "sent": False,
            "storage_path": None
        }
        return report

    def _save_report_to_disk(self, report):
        if not self.store_dir:
            return

        event_dir = os.path.join(self.store_dir, report["event_id"])
        try:
            os.makedirs(event_dir, exist_ok=True)
            report["storage_path"] = event_dir

            meta_copy = {k: v for k, v in report.items() if k not in ("screenshot", "camera_snapshot")}
            if report.get("screenshot"):
                screenshot_path = os.path.join(event_dir, "screenshot.jpg")
                with open(screenshot_path, "wb") as f:
                    f.write(base64.b64decode(report["screenshot"]))
                meta_copy["screenshot_path"] = screenshot_path

            if report.get("camera_snapshot"):
                camera_path = os.path.join(event_dir, "camera.jpg")
                with open(camera_path, "wb") as f:
                    f.write(base64.b64decode(report["camera_snapshot"]))
                meta_copy["camera_path"] = camera_path

            with open(os.path.join(event_dir, "metadata.json"), "w", encoding="utf-8") as f:
                json.dump(meta_copy, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logging.warning("Не удалось сохранить доказательства на диск: %s", e)

    def _build_payload(self, report):
        payload = {
            "event_id": report.get("event_id"),
            "event_type": report.get("event_type"),
            "description": report.get("description"),
            "timestamp": report.get("timestamp"),
            "process": report.get("process"),
            "screenshot": report.get("screenshot"),
            "screenshot_quality": report.get("screenshot_quality"),
            "camera_snapshot": report.get("camera_snapshot")
        }
        return {"evidence_report": payload}

    async def send_report(self, websocket, report):
        if websocket is None:
            return False

        payload = self._build_payload(report)
        try:
            async with self.client.send_lock:
                await websocket.send(json.dumps(payload))
            report["sent"] = True
            self._mark_report_sent(report)
            return True
        except Exception as e:
            logging.warning("Не удалось отправить доказательства на сервер: %s", e)
            return False

    async def send_pending(self, websocket):
        if websocket is None or not self.pending_reports:
            return

        for report in list(self.pending_reports):
            if report.get("sent"):
                self.pending_reports.remove(report)
                continue
            sent = await self.send_report(websocket, report)
            if sent:
                self.pending_reports.remove(report)

    def _mark_report_sent(self, report):
        metadata_path = None
        if report.get("storage_path"):
            metadata_path = os.path.join(report["storage_path"], "metadata.json")
        if metadata_path and os.path.exists(metadata_path):
            try:
                with open(metadata_path, "r", encoding="utf-8") as f:
                    meta = json.load(f)
                meta["sent"] = True
                with open(metadata_path, "w", encoding="utf-8") as f:
                    json.dump(meta, f, ensure_ascii=False, indent=2)
            except Exception:
                pass
