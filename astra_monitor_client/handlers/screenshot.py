import base64
import logging
import shutil
import subprocess
from datetime import datetime

from astra_monitor_client.utils.system_utils import get_active_graphical_session, build_dbus_env


class ScreenshotHandler:
    def __init__(self, client):
        self.client = client

    async def take_screenshot(self, force_quality=None):
        logging.info("📸 Попытка создания скриншота...")

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

        try:
            quality = force_quality if force_quality is not None else self.client.screenshot_settings["quality"]
            user, display, uid = get_active_graphical_session()
            if not (user and display and uid):
                return {"error": "❌ Не найдено активной графической сессии"}

            try:
                subprocess.run(["xhost", "+SI:localuser:root"], timeout=5, capture_output=False)
                subprocess.run(["xhost", "+SI:localuser:" + user], timeout=5, capture_output=False)
                subprocess.run(["xhost", "+"], timeout=5, capture_output=False)
            except Exception:
                pass

            try:
                import_cmd = ['import', '-window', 'root', 'png:-']
                result = run_as_user(user, display, uid, import_cmd, timeout=15, capture_output=True)
                if result and result.returncode == 0 and result.stdout:
                    img_data = result.stdout
                    if quality < 100:
                        convert_cmd = ['convert', 'png:-', '-quality', str(quality), 'jpg:-']
                        convert_result = run_as_user(user, display, uid, convert_cmd, timeout=10, capture_output=True)
                        if convert_result and convert_result.returncode == 0 and convert_result.stdout:
                            img_data = convert_result.stdout
                    return {
                        "screenshot": base64.b64encode(img_data).decode(),
                        "quality": quality,
                        "timestamp": datetime.now().isoformat()
                    }
            except Exception as e:
                logging.warning("Метод скриншота (import в память) не удался: %s", e)

            try:
                xwd_cmd = ['xwd', '-root', '-silent']
                result = run_as_user(user, display, uid, xwd_cmd, timeout=15, capture_output=True)
                if result and result.returncode == 0 and result.stdout:
                    convert_cmd = ['convert', 'xwd:-', 'png:-']
                    convert_result = run_as_user(user, display, uid, convert_cmd, timeout=10, capture_output=True)
                    if convert_result and convert_result.returncode == 0 and convert_result.stdout:
                        img_data = convert_result.stdout
                        return {
                            "screenshot": base64.b64encode(img_data).decode(),
                            "quality": quality,
                            "timestamp": datetime.now().isoformat()
                        }
            except Exception as e:
                logging.warning("Метод скриншота (xwd в память) не удался: %s", e)

            if shutil.which("ffmpeg"):
                try:
                    ffmpeg_cmd = [
                        'ffmpeg', '-f', 'x11grab', '-video_size', '1920x1080', '-i', display,
                        '-vframes', '1', '-q:v', str(max(1, 31 - quality // 3)),
                        '-f', 'image2pipe', '-c:v', 'mjpeg', '-'
                    ]
                    result = run_as_user(user, display, uid, ffmpeg_cmd, timeout=15, capture_output=True)
                    if result and result.returncode == 0 and result.stdout:
                        img_data = result.stdout
                        return {
                            "screenshot": base64.b64encode(img_data).decode(),
                            "quality": quality,
                            "timestamp": datetime.now().isoformat()
                        }
                except Exception as e:
                    logging.warning("Метод скриншота (ffmpeg в память) не удался: %s", e)

            if shutil.which("scrot"):
                try:
                    scrot_cmd = ['scrot', '-o', '-']
                    result = run_as_user(user, display, uid, scrot_cmd, timeout=10, capture_output=True)
                    if result and result.returncode == 0 and result.stdout:
                        img_data = result.stdout
                        if quality < 100:
                            convert_cmd = ['convert', 'png:-', '-quality', str(quality), 'jpg:-']
                            convert_result = run_as_user(user, display, uid, convert_cmd, timeout=5, capture_output=True)
                            if convert_result and convert_result.returncode == 0 and convert_result.stdout:
                                img_data = convert_result.stdout
                        return {
                            "screenshot": base64.b64encode(img_data).decode(),
                            "quality": quality,
                            "timestamp": datetime.now().isoformat()
                        }
                except Exception as e:
                    logging.warning("Метод скриншота (scrot) не удался: %s", e)

            try:
                gnome_cmd = ['gnome-screenshot', '-f', '-', '--include-pointer']
                result = run_as_user(user, display, uid, gnome_cmd, timeout=10, capture_output=True)
                if result and result.returncode == 0 and result.stdout:
                    img_data = result.stdout
                    if quality < 100:
                        convert_cmd = ['convert', 'png:-', '-quality', str(quality), 'jpg:-']
                        convert_result = run_as_user(user, display, uid, convert_cmd, timeout=5, capture_output=True)
                        if convert_result and convert_result.returncode == 0 and convert_result.stdout:
                            img_data = convert_result.stdout
                    return {
                        "screenshot": base64.b64encode(img_data).decode(),
                        "quality": quality,
                        "timestamp": datetime.now().isoformat()
                    }
            except Exception as e:
                logging.warning("Метод скриншота (gnome-screenshot) не удался: %s", e)

            return {"error": "❌ Все методы создания скриншота не удались"}

        except Exception as e:
            logging.error("Критическая ошибка создания скриншота: %s", e)
            return {"error": f"❌ Ошибка создания скриншота: {str(e)}"}
