import platform
import os
import subprocess
import socket
import shutil
import re
from datetime import datetime
import json

try:
    import psutil
except ImportError:
    psutil = None

try:
    import wmi
except ImportError:
    wmi = None

class SystemMonitor:
    @staticmethod
    def get_cpu_percent():
        if platform.system() == "Windows":
            if psutil:
                return psutil.cpu_percent(interval=1)
            return 0
        else:
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
        if platform.system() == "Windows":
            if psutil:
                mem = psutil.virtual_memory()
                return mem.percent, mem.used, mem.total
            return 0, 0, 0
        else:
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
        if platform.system() == "Windows":
            if psutil:
                disk = psutil.disk_usage('C:\\')
                return disk.percent, disk.used, disk.total
            return 0, 0, 0
        else:
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
        if platform.system() == "Windows":
            if psutil:
                net = psutil.net_io_counters()
                return net.bytes_recv, net.bytes_sent
            return 0, 0
        else:
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
        if platform.system() == "Windows":
            if psutil:
                return datetime.fromtimestamp(psutil.boot_time()).strftime("%d.%m.%Y %H:%M:%S")
            return "N/A"
        else:
            try:
                with open('/proc/uptime', 'r') as f:
                    uptime_seconds = float(f.readline().split()[0])
                boot_time = datetime.now().timestamp() - uptime_seconds
                return datetime.fromtimestamp(boot_time).strftime("%d.%m.%Y %H:%M:%S")
            except:
                return datetime.now().strftime("%d.%m.%Y %H:%M:%S")

def get_full_system_info():
    if platform.system() == "Windows":
        return get_windows_full_system_info()
    else:
        return get_linux_full_system_info()

def get_windows_full_system_info():
    if not wmi:
        return {"error": "WMI library not installed"}
    
    c = wmi.WMI()

    def get_wmi_property(wmi_class, prop, index=0, default="N/A"):
        try:
            result = getattr(wmi_class()[index], prop)
            return result if result is not None else default
        except Exception:
            return default

    try:
        # GPU: Join list into a string
        gpu_list = [gpu.Name for gpu in c.Win32_VideoController()]
        gpu_info = ", ".join(gpu_list) if gpu_list else "N/A"

        # Audio: Create list of dicts
        audio_devices = []
        try:
            for audio in c.Win32_SoundDevice():
                audio_devices.append({
                    'device': audio.Name,
                    'type': 'Аудио (воспроизведение)',
                    'status': 'Доступно' if audio.Status == 'OK' else 'Ошибка'
                })
        except Exception:
            pass

        # Cameras: Create list of dicts
        cameras = []
        try:
            for cam in c.Win32_PnPEntity():
                if cam.Description and 'camera' in cam.Description.lower():
                    cameras.append({
                        'device': cam.Name,
                        'type': 'Видео',
                        'status': 'Доступно' if cam.Status == 'OK' else 'Ошибка'
                    })
        except Exception:
            pass

        result = {
            'os_distro': platform.system(),
            'os_version': platform.version(),
            'architecture': platform.machine(),
            'kernel': platform.release(),
            'uptime': get_uptime(),
            'install_date': 'N/A',
            'cpu_model': get_wmi_property(c.Win32_Processor, "Name"),
            'cpu_cores': f"{get_wmi_property(c.Win32_Processor, 'NumberOfCores', default=1)} ядер",
            'cpu_freq': f"{get_wmi_property(c.Win32_Processor, 'MaxClockSpeed', default=0)} MHz",
            'ram_total': f"{float(get_wmi_property(c.Win32_ComputerSystem, 'TotalPhysicalMemory', default=0)) / 1024**3:.1f} GB",
            'gpu': gpu_info,
            'motherboard': get_wmi_property(c.Win32_BaseBoard, "Product"),
            'bios': get_wmi_property(c.Win32_BIOS, "Caption"),
            'storage': get_storage_info(),
            'network': get_network_info(),
            'usb_devices': get_usb_devices(),
            'audio_devices': audio_devices,
            'cameras': cameras
        }
        return result
    except Exception as e:
        import traceback
        return {'error': str(e), 'traceback': traceback.format_exc()}

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
    if platform.system() == "Windows":
        if psutil:
            boot_time = datetime.fromtimestamp(psutil.boot_time())
            uptime_seconds = (datetime.now() - boot_time).total_seconds()
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
        return "N/A"
    else:
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
    if platform.system() == "Windows":
        return "N/A"
    else:
        try:
            if os.path.exists('/var/log/installer/syslog'):
                mtime = os.path.getmtime('/var/log/installer/syslog')
                return datetime.fromtimestamp(mtime).strftime('%Y-%m-%d')
        except Exception:
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
    if platform.system() == "Windows":
        if wmi:
            return wmi.WMI().Win32_Processor()[0].Name
        return "N/A"
    else:
        try:
            with open('/proc/cpuinfo', 'r') as f:
                for line in f:
                    if line.startswith('model name'):
                        return line.split(':', 1)[1].strip()
        except:
            pass
        return "N/A"

def get_cpu_cores():
    if platform.system() == "Windows":
        if wmi:
            return f"{wmi.WMI().Win32_Processor()[0].NumberOfCores} ядер"
        return "N/A"
    else:
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
    if platform.system() == "Windows":
        if wmi:
            return f"{wmi.WMI().Win32_Processor()[0].MaxClockSpeed} MHz"
        return "N/A"
    else:
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
    if platform.system() == "Windows":
        if wmi:
            return f"{float(wmi.WMI().Win32_ComputerSystem()[0].TotalPhysicalMemory) / 1024 / 1024 / 1024:.1f} GB"
        return "N/A"
    else:
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
    if platform.system() == "Windows":
        if wmi:
            return [gpu.Name for gpu in wmi.WMI().Win32_VideoController()]
        return "N/A"
    else:
        try:
            result = subprocess.run(['lspci', '|', 'grep', '-i', 'vga'], 
                                capture_output=True, text=True, shell=True)
            if result.returncode == 0:
                return result.stdout.strip()
        except:
            pass
        return "N/A"

def get_motherboard_info():
    if platform.system() == "Windows":
        if wmi:
            return wmi.WMI().Win32_BaseBoard()[0].Product
        return "N/A"
    else:
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
    if platform.system() == "Windows":
        if wmi:
            return wmi.WMI().Win32_BIOS()[0].Caption
        return "N/A"
    else:
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
    if platform.system() == "Windows":
        return "N/A"
    else:
        try:
            result = subprocess.run(['lsblk', '-no', 'FSTYPE', device], capture_output=True, text=True)
            return result.stdout.strip() or "N/A"
        except:
            return "N/A"
        
def get_storage_info():
    if platform.system() == "Windows":
        if psutil:
            storage_info = []
            for part in psutil.disk_partitions():
                try:
                    usage = psutil.disk_usage(part.mountpoint)
                    storage_info.append({
                        'device': part.device,
                        'mountpoint': part.mountpoint,
                        'size': format_bytes(usage.total),
                        'used': f"{format_bytes(usage.used)} ({usage.percent}%)",
                        'fstype': part.fstype
                    })
                except Exception:
                    continue
            return storage_info
        return []
    else:
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
    if platform.system() == "Windows":
        if psutil:
            network_info = []
            for iface, addrs in psutil.net_if_addrs().items():
                ip_v4 = 'N/A'
                mac = 'N/A'
                for addr in addrs:
                    if addr.family == socket.AF_INET:
                        ip_v4 = addr.address
                    if addr.family == psutil.AF_LINK:
                        mac = addr.address
                network_info.append({
                    'interface': iface,
                    'ip': ip_v4,
                    'mac': mac,
                    'status': 'UP' if psutil.net_if_stats()[iface].isup else 'DOWN'
                })
            return network_info
        return []
    else:
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
    if platform.system() == "Windows":
        if wmi:
            usb_devices = []
            for device in wmi.WMI().Win32_USBHub():
                usb_devices.append({
                    'device': device.Description,
                    'vendor': device.DeviceID,
                    'version': 'USB',
                    'status': 'Подключено'
                })
            return usb_devices
        return []
    else:
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
    if platform.system() == "Windows":
        if wmi:
            return [audio.Name for audio in wmi.WMI().Win32_SoundDevice()]
        return []
    else:
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
    if platform.system() == "Windows":
        if wmi:
            return [cam.Name for cam in wmi.WMI().Win32_PnPEntity() if cam.Description and 'camera' in cam.Description.lower()]
        return []
    else:
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
        except:
            pass
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