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

        def get_primary_geometry():
            try:
                result = subprocess.run(['xrandr', '--query'], capture_output=True, text=True)
                for line in result.stdout.splitlines():
                    if " connected primary " in line:
                        parts = line.split()
                        for part in parts:
                            if "+" in part and "x" in part:
                                size, x, y = part.split("+")
                                w, h = size.split("x")
                                return int(w), int(h), int(x), int(y)
                for line in result.stdout.splitlines():
                    if " connected " in line:
                        parts = line.split()
                        for part in parts:
                            if "+" in part and "x" in part:
                                size, x, y = part.split("+")
                                w, h = size.split("x")
                                return int(w), int(h), int(x), int(y)
            except Exception:
                return None
            return None

        def convert_image_data(input_data, convert_cmd, timeout=10):
            try:
                proc = subprocess.run(
                    convert_cmd,
                    input=input_data,
                    timeout=timeout,
                    capture_output=True
                )
                if proc.returncode == 0 and proc.stdout:
                    return proc.stdout
            except Exception as e:
                logging.warning("Ошибка convert: %s", e)
            return None

        try:
            quality = force_quality if force_quality is not None else self.client.screenshot_settings["quality"]
            monitor_mode = self.client.screenshot_settings.get("monitor_mode", "all")
            user, display, uid = get_active_graphical_session()
            if not (user and display and uid):
                return {"error": "❌ Не найдено активной графической сессии"}

            geometry = get_primary_geometry() if monitor_mode == "primary" else None

            try:
                subprocess.run(["xhost", "+SI:localuser:root"], timeout=5, capture_output=False)
                subprocess.run(["xhost", "+SI:localuser:" + user], timeout=5, capture_output=False)
                subprocess.run(["xhost", "+"], timeout=5, capture_output=False)
            except Exception:
                pass

            try:
                import_cmd = ['import', '-window', 'root']
                if geometry:
                    w, h, x, y = geometry
                    import_cmd += ['-crop', f'{w}x{h}+{x}+{y}']
                import_cmd += ['png:-']
                result = run_as_user(user, display, uid, import_cmd, timeout=15, capture_output=True)
                if result and result.returncode == 0 and result.stdout:
                    img_data = result.stdout
                    if quality < 100:
                        convert_result = convert_image_data(img_data, ['convert', 'png:-', '-quality', str(quality), 'jpg:-'], timeout=15)
                        if convert_result:
                            img_data = convert_result
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
                    img_data = result.stdout
                    convert_cmd = ['convert', 'xwd:-']
                    if geometry:
                        w, h, x, y = geometry
                        convert_cmd += ['-crop', f'{w}x{h}+{x}+{y}']
                    convert_cmd += ['png:-']
                    convert_result = convert_image_data(img_data, convert_cmd, timeout=15)
                    if convert_result:
                        img_data = convert_result
                        return {
                            "screenshot": base64.b64encode(img_data).decode(),
                            "quality": quality,
                            "timestamp": datetime.now().isoformat()
                        }
            except Exception as e:
                logging.warning("Метод скриншота (xwd в память) не удался: %s", e)

            if shutil.which("ffmpeg"):
                try:
                    if geometry:
                        w, h, x, y = geometry
                        ffmpeg_input = f"{display}+{x},{y}"
                        ffmpeg_cmd = [
                            'ffmpeg', '-f', 'x11grab', '-video_size', f'{w}x{h}', '-i', ffmpeg_input,
                            '-vframes', '1', '-q:v', str(max(1, 31 - quality // 3)),
                            '-f', 'image2pipe', '-c:v', 'mjpeg', '-'
                        ]
                    else:
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
                            convert_cmd = ['convert', 'png:-']
                            if geometry:
                                w, h, x, y = geometry
                                convert_cmd += ['-crop', f'{w}x{h}+{x}+{y}']
                            convert_cmd += ['-quality', str(quality), 'jpg:-']
                            convert_result = convert_image_data(img_data, convert_cmd, timeout=15)
                            if convert_result:
                                img_data = convert_result
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
                        convert_cmd = ['convert', 'png:-']
                        if geometry:
                            w, h, x, y = geometry
                            convert_cmd += ['-crop', f'{w}x{h}+{x}+{y}']
                        convert_cmd += ['-quality', str(quality), 'jpg:-']
                        convert_result = convert_image_data(img_data, convert_cmd, timeout=15)
                        if convert_result:
                            img_data = convert_result
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
