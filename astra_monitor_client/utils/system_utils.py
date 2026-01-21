import platform
import os
import subprocess
import socket
import shutil
import re
from datetime import datetime
import json



class SystemMonitor:
    @staticmethod
    def get_cpu_percent():
        try:
            with open('/proc/stat', 'r') as f:
                lines = f.readlines()
            for line in lines:
                if line.startswith('cpu '):
                    parts = line.split()
                    total = sum(int(x) for x in parts[1:])
                    idle = int(parts[4])
                    return 100 * (total - idle) / total if total > 0 else 0
        except:
            return 0
        return 0

    @staticmethod
    def get_memory_info():
        try:
            meminfo = {}
            with open('/proc/meminfo', 'r') as f:
                for line in f:
                    parts = line.split()
                    if len(parts) >= 2:
                        meminfo[parts[0].rstrip(':')] = int(parts[1]) * 1024

            total = meminfo.get('MemTotal', 0)
            free = meminfo.get('MemFree', 0)
            buffers = meminfo.get('Buffers', 0)
            cached = meminfo.get('Cached', 0)

            used = total - free - buffers - cached
            percent = (used / total) * 100 if total > 0 else 0

            return percent, used, total
        except:
            return 0, 0, 0

    @staticmethod
    def get_disk_usage():
        try:
            result = subprocess.run(['df', '/'], capture_output=True, text=True)
            lines = result.stdout.strip().split('\n')
            if len(lines) > 1:
                parts = lines[1].split()
                if len(parts) >= 5:
                    total = int(parts[1]) * 1024
                    used = int(parts[2]) * 1024
                    percent = float(parts[4].rstrip('%'))
                    return percent, used, total
        except:
            pass
        return 0, 0, 0

    @staticmethod
    def get_network_io():
        try:
            with open('/proc/net/dev', 'r') as f:
                lines = f.readlines()

            rx_total = 0
            tx_total = 0

            for line in lines[2:]:
                parts = line.split()
                if len(parts) >= 10:
                    iface = parts[0].rstrip(':')
                    if iface not in ['lo', 'docker0']:
                        rx_total += int(parts[1])
                        tx_total += int(parts[9])

            return rx_total, tx_total
        except:
            return 0, 0

    @staticmethod
    def get_boot_time():
        try:
            with open('/proc/uptime', 'r') as f:
                uptime_seconds = float(f.readline().split()[0])
            boot_time = datetime.now().timestamp() - uptime_seconds
            return datetime.fromtimestamp(boot_time).strftime("%d.%m.%Y %H:%M:%S")
        except:
            return datetime.now().strftime("%d.%m.%Y %H:%M:%S")

def get_full_system_info():
    return get_linux_full_system_info()

def get_linux_full_system_info():
    try:
        result = {
            'os_distro': 'Astra Linux',
            'os_version': get_astra_version(),
            'architecture': platform.machine(),
            'kernel': platform.release(),
            'uptime': get_uptime(),
            'install_date': get_install_date(),
            'cpu_model': get_cpu_info(),
            'cpu_cores': get_cpu_cores(),
            'cpu_freq': get_cpu_freq(),
            'ram_total': get_ram_total(),
            'gpu': get_gpu_info(),
            'motherboard': get_motherboard_info(),
            'bios': get_bios_info(),
            'storage': get_storage_info(),
            'network': get_network_info(),
            'usb_devices': get_usb_devices(),
            'audio_devices': get_audio_devices(),
            'cameras': get_camera_info()
        }
        
        return result
        
    except Exception as e:
        return {'error': str(e)}

def get_uptime():
    try:
        with open('/proc/uptime', 'r') as f:
            uptime_seconds = float(f.readline().split()[0])

        days = int(uptime_seconds // (24 * 3600))
        hours = int((uptime_seconds % (24 * 3600)) // 3600)
        minutes = int((uptime_seconds % 3600) // 60)

        parts = []
        if days > 0:
            parts.append(f"{days} д")
        if hours > 0:
            parts.append(f"{hours} ч")
        if minutes > 0 or not parts:
            parts.append(f"{minutes} м")
        return " ".join(parts)
    except:
        return "N/A"

def get_install_date():
    """
    Получает дату установки ОС.
    Для Linux пробует несколько методов для надежности.
    """
    # Method 1: Filesystem birth time (most reliable for modern systems)
    try:
        result = subprocess.run(
            ['stat', '-c', '%W', '/'],
            capture_output=True, text=True, check=True, stderr=subprocess.DEVNULL
        )
        timestamp_str = result.stdout.strip()
        if timestamp_str and timestamp_str != '0':
            timestamp = int(timestamp_str)
            return datetime.fromtimestamp(timestamp).strftime('%Y-%m-%d')
    except (subprocess.CalledProcessError, FileNotFoundError, ValueError):
        pass

    # Method 2: tune2fs (very reliable for ext filesystems)
    try:
        df_output = subprocess.check_output(['df', '/'], text=True)
        root_device = df_output.split('\n')[1].split()[0]
        if root_device.startswith('/dev/'):
            tune2fs_output = subprocess.check_output(['tune2fs', '-l', root_device], text=True, stderr=subprocess.DEVNULL)
            for line in tune2fs_output.split('\n'):
                if 'Filesystem created:' in line:
                    date_str = line.split(':', 1)[1].strip()
                    try:
                        return datetime.strptime(date_str, '%a %b %d %H:%M:%S %Y').strftime('%Y-%m-%d')
                    except ValueError:
                        pass
    except (subprocess.CalledProcessError, FileNotFoundError, IndexError, AttributeError):
        pass

    # Method 3: /var/log/installer/syslog
    try:
        if os.path.exists('/var/log/installer/syslog'):
            mtime = os.path.getmtime('/var/log/installer/syslog')
            return datetime.fromtimestamp(mtime).strftime('%Y-%m-%d')
    except OSError:
        pass

    # Method 4: dpkg log for base-files package
    try:
        if os.path.exists('/var/log/dpkg.log'):
            with open('/var/log/dpkg.log', 'r') as f:
                for line in f:
                    if 'status installed base-files' in line:
                        date_str = line.split(' ')[0]
                        datetime.strptime(date_str, '%Y-%m-%d')
                        return date_str
    except (IOError, ValueError):
        pass

    # Method 5: Creation time of /etc/passwd
    try:
        ctime = os.path.getctime('/etc/passwd')
        return datetime.fromtimestamp(ctime).strftime('%Y-%m-%d')
    except OSError:
        pass

    return "N/A"


def get_astra_version():
    """Получение версии системы"""
    try:
        result = subprocess.run(['cat', '/etc/astra_version'], 
                               capture_output=True, text=True)
        
        if result.returncode == 0:
            astra_version = result.stdout.strip()
            return astra_version
    except Exception as e:
        print(f"Ошибка при получении версии Astra: {e}")
    
    return "N/A"

def get_cpu_info():
    try:
        with open('/proc/cpuinfo', 'r') as f:
            for line in f:
                if line.startswith('model name'):
                    return line.split(':', 1)[1].strip()
    except:
        pass
    return "N/A"

def get_cpu_cores():
    try:
        with open('/proc/cpuinfo', 'r') as f:
            cores = 0
            for line in f:
                if line.startswith('processor'):
                    cores += 1
            return f"{cores} ядер"
    except:
        pass
    return "N/A"

def get_cpu_freq():
    try:
        with open('/proc/cpuinfo', 'r') as f:
            for line in f:
                if line.startswith('cpu MHz'):
                    freq = float(line.split(':', 1)[1].strip())
                    return f"{freq:.1f} MHz"
    except:
        pass
    return "N/A"

def get_ram_total():
    try:
        with open('/proc/meminfo', 'r') as f:
            for line in f:
                if line.startswith('MemTotal'):
                    kb = int(line.split()[1])
                    gb = kb / 1024 / 1024
                    return f"{gb:.1f} GB"
    except:
        pass
    return "N/A"

def get_gpu_info():
    try:
        result = subprocess.run(['lspci', '|', 'grep', '-i', 'vga'],
                            capture_output=True, text=True, shell=True)
        if result.returncode == 0:
            return result.stdout.strip()
    except:
        pass
    return "N/A"

def get_motherboard_info():
    try:
        result = subprocess.run(['dmidecode', '-t', 'baseboard'],
                            capture_output=True, text=True)
        if result.returncode == 0:
            for line in result.stdout.split('\n'):
                if 'Product Name:' in line:
                    return line.split(':', 1)[1].strip()
    except:
        pass
    return "N/A"

def get_bios_info():
    try:
        result = subprocess.run(['dmidecode', '-t', 'bios'],
                            capture_output=True, text=True)
        if result.returncode == 0:
            for line in result.stdout.split('\n'):
                if 'Version:' in line:
                    return line.split(':', 1)[1].strip()
    except:
        pass
    return "N/A"

def format_bytes(size_bytes):
    if size_bytes == 0: return "0B"
    size_names = ("B", "KB", "MB", "GB", "TB")
    i = 0
    while size_bytes >= 1024 and i < len(size_names) - 1:
        size_bytes /= 1024.0
        i += 1
    return f"{size_bytes:.1f} {size_names[i]}"

def get_fstype(device):
    try:
        result = subprocess.run(['lsblk', '-no', 'FSTYPE', device], capture_output=True, text=True)
        return result.stdout.strip() or "N/A"
    except:
        return "N/A"
        
def get_storage_info():
    try:
        result = subprocess.run(['df', '-P'], capture_output=True, text=True, check=True)
        lines = result.stdout.strip().split('\n')[1:]
        storage_info = []
        for line in lines:
            parts = line.split()
            if len(parts) >= 6:
                device, total, used, available, use_percent, mountpoint = parts
                total_hr = format_bytes(int(total) * 1024)
                used_hr = format_bytes(int(used) * 1024)
                storage_info.append({
                    'device': device,
                    'mountpoint': mountpoint,
                    'size': total_hr,
                    'used': f"{used_hr} ({use_percent})",
                    'fstype': get_fstype(device)
                })
        return storage_info
    except Exception:
        return []

def get_network_info():
    try:
        result = subprocess.run(['ip', '-j', 'addr'], capture_output=True, text=True, check=True)
        interfaces = json.loads(result.stdout)
        network_info = []
        for iface in interfaces:
            ip_v4 = 'N/A'
            for addr in iface.get('addr_info', []):
                if addr.get('family') == 'inet':
                    ip_v4 = addr.get('local', 'N/A')
                    break
            network_info.append({
                'interface': iface.get('ifname', 'N/A'),
                'ip': ip_v4,
                'mac': iface.get('address', 'N/A'),
                'status': iface.get('operstate', 'N/A')
            })
        return network_info
    except:
        return []

def get_usb_devices():
    try:
        result = subprocess.run(['lsusb'], capture_output=True, text=True, check=True)
        usb_devices = []
        pattern = re.compile(r"Bus\s+(\d+)\s+Device\s+(\d+):\s+ID\s+([0-9a-fA-F]{4}:[0-9a-fA-F]{4})\s+(.*)")
        for line in result.stdout.strip().split('\n'):
            match = pattern.match(line)
            if match:
                bus, device, id, description = match.groups()
                usb_devices.append({
                    'device': description.strip(),
                    'vendor': id,
                    'version': 'USB',
                    'status': 'Подключено'
                })
        return usb_devices
    except Exception:
        return []

def get_audio_devices():
    try:
        result = subprocess.run(['aplay', '-l'], capture_output=True, text=True, check=True)
        audio_devices = []
        pattern = re.compile(r"card\s+\d+:\s+.*? \[((?:.|)*?)\]")
        for line in result.stdout.strip().split('\n'):
            match = pattern.match(line)
            if match:
                device_name = match.group(1).strip()
                audio_devices.append({
                    'device': device_name,
                    'type': 'Аудио (воспроизведение)',
                    'status': 'Доступно'
                })
        return audio_devices
    except Exception:
        return []

def get_camera_info():
    try:
        result = subprocess.run(['find', '/dev', '-name', 'video*'], capture_output=True, text=True, check=True)
        cameras = []
        video_devices = result.stdout.strip().split('\n')
        
        v4l2_ctl_exists = shutil.which('v4l2-ctl') is not None

        for device_path in video_devices:
            if not device_path:
                continue
            
            device_name = device_path
            if v4l2_ctl_exists:
                try:
                    v4l2_result = subprocess.run(
                        ['v4l2-ctl', '--device', device_path, '--all'],
                        capture_output=True, text=True, timeout=2
                    )
                    if v4l2_result.returncode == 0:
                        card_type_match = re.search(r"Card type\s*:\s*(.*)", v4l2_result.stdout)
                        if card_type_match:
                            device_name = card_type_match.group(1).strip()
                except (FileNotFoundError, subprocess.TimeoutExpired):
                    pass

            cameras.append({
                'device': device_name,
                'type': 'Видео',
                'status': 'Доступно'
            })
        return cameras
    except Exception:
        return []

def get_local_ip():
    """Получение локального IP-адреса"""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except:
        return "127.0.0.1"


def get_active_graphical_session():
    """Возвращает (user, display, uid) активной графической сессии или (None, None, None)."""
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
                        display = None
                        uid = None
                        for info_line in info.stdout.split('\n'):
                            if info_line.startswith('Display='):
                                display = info_line.split('=', 1)[1]
                            if info_line.startswith('User='):
                                uid = info_line.split('=', 1)[1]
                        if display and uid:
                            return user, display, uid
    except Exception:
        pass

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
                uid_proc = subprocess.run(['id', '-u', user], capture_output=True, text=True)
                if uid_proc.returncode == 0:
                    uid = uid_proc.stdout.strip()
                    return user, display, uid
    except Exception:
        pass

    return None, None, None


def build_dbus_env(user, display, uid):
    """Готовит окружение для запуска GUI/DBUS команд от имени пользователя."""
    env = os.environ.copy()
    env['DISPLAY'] = display
    env['XAUTHORITY'] = f'/home/{user}/.Xauthority'
    env['HOME'] = f'/home/{user}'
    env['DBUS_SESSION_BUS_ADDRESS'] = f'unix:path=/run/user/{uid}/bus'
    env.pop('LD_LIBRARY_PATH', None)
    return env
