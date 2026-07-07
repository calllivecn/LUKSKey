#!/usr/bin/python3

"""
usb-keyfile.py - dracut initramfs hook 的 Python 实现
功能：在 initramfs 阶段检测 USB 设备、读取 keyfile 并解锁 LUKS 分区，
同时提供交互式密码输入作为 fallback。

依赖：Python 3.12+ 标准库（无第三方依赖）
"""

import os
import sys
import time
import tomllib
import subprocess
import threading
from pathlib import Path
from typing import Optional

# ===== 常量 =====
CONF_PATH = "/etc/usb-keyfile.toml"
MOUNT_POINT = Path("/run/usb")
MAX_RETRIES = 30
RETRY_INTERVAL = 1.0  # 秒

DEV_BY_UUID = Path("/dev/disk/by-uuid")


class Config:
    """配置文件 /etc/usb-keyfile.conf 的解析结果"""
    def __init__(self, usb_uuid: str = "", keyfile_path: str = "", luks_conf: str = LUKS_CONF_PATH):
        self.usb_uuid = usb_uuid
        self.keyfile_path = keyfile_path
        self.luks_conf = luks_conf


class LUKSEntry:
    """LUKS 分区条目（uuid 和 name）"""
    def __init__(self, uuid: str, name: str):
        self.uuid = uuid
        self.name = name


# ===== 全局状态 =====
config: Optional[Config] = None
luks_entries: list[LUKSEntry] = []
_unlock_lock = threading.Lock()
_unlock_done = False


# ===== 日志 =====
def info(msg: str):
    """输出 INFO 日志"""
    print(f"usb-keyfile: INFO: {msg}", flush=True)


def warn(msg: str):
    """输出 WARN 日志"""
    print(f"usb-keyfile: WARN: {msg}", flush=True)


# ===== 辅助函数：检查/设置解锁完成状态（线程安全） =====
def is_unlock_done() -> bool:
    with _unlock_lock:
        return _unlock_done


def set_unlock_done():
    global _unlock_done
    with _unlock_lock:
        _unlock_done = True


# ===== 配置加载 =====
def load_config(path: str = CONF_PATH) -> Config:
    """加载主配置文件，返回 Config 对象"""
    cfg = Config()
    if not os.path.isfile(path):
        raise FileNotFoundError(f"Config file not found: {path}")

    with open(path, "r") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip().strip("'\"")
            if key == "USB_UUID":
                cfg.usb_uuid = value
            elif key == "KEYFILE_PATH":
                cfg.keyfile_path = value
            elif key == "LUKS_CONF":
                cfg.luks_conf = value
    return cfg


def load_luks_conf(path: str) -> list[LUKSEntry]:
    """加载 LUKS UUID 配置，返回条目列表"""
    entries = []
    if not os.path.isfile(path):
        raise FileNotFoundError(f"LUKS config file not found: {path}")

    with open(path, "r") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.split()
            if len(parts) >= 2:
                entries.append(LUKSEntry(uuid=parts[0], name=parts[1]))
    return entries


# ===== USB 相关操作 =====

def wait_for_device(uuid: str) -> bool:
    """等待 USB 设备出现（检查 /dev/disk/by-uuid 目录），最多重试 MAX_RETRIES 次"""
    target = DEV_BY_UUID / uuid
    info(f"Waiting for device {uuid}...")
    for i in range(MAX_RETRIES):
        if target.exists():
            info(f"Device {uuid} found via {target.resolve()}")
            return True
        time.sleep(RETRY_INTERVAL)
    return False


def resolve_luks_device(uuid: str) -> Optional[str]:
    """通过 /dev/disk/by-uuid 解析 UUID 对应的设备路径"""
    target = DEV_BY_UUID / uuid
    try:
        return str(target.resolve(strict=True))
    except (FileNotFoundError, RuntimeError):
        warn(f"Cannot resolve UUID {uuid} to a device")
        return None


def mount_usb(uuid: str) -> bool:
    """挂载 USB 设备为只读"""
    MOUNT_POINT.mkdir(parents=True, exist_ok=True)
    try:
        subprocess.run(
            ["mount", "-vt", "auto", "-o", "ro", "-U", uuid, MOUNT_POINT],
            check=True, capture_output=True, timeout=10
        )
        return True
    except subprocess.CalledProcessError as e:
        warn(f"mount failed: {e.stderr.decode() if e.stderr else ''}")
        return False


def umount_usb():
    """卸载 USB 并清理挂载点"""
    subprocess.run(["umount", MOUNT_POINT], capture_output=True)
    try:
        os.rmdir(MOUNT_POINT)
    except OSError:
        pass


def read_keyfile(rel_path: str) -> Optional[bytes]:
    """从 USB 挂载点读取密钥文件内容"""
    abs_path =  MOUNT_POINT / rel_path
    
    try:
        with open(abs_path.absolute(), "rb") as f:
            return f.read()
    except Exception as e:
        warn(f"Cannot read keyfile {abs_path}: {e}")
        return None


# ===== LUKS 解锁 =====
def luks_unlock(entry: LUKSEntry, key: bytes) -> bool:
    """向 systemd-cryptsetup 提供密钥解锁一个 LUKS 分区"""
    dev = resolve_luks_device(entry.uuid)
    if not dev:
        warn(f"Cannot find device for LUKS UUID {entry.uuid}")
        return False
    try:
        # 通过 stdin 管道传递密钥
        proc = subprocess.Popen(
            ["systemd-cryptsetup", "attach", entry.name, "--key-file=-", dev],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE
        )
        stdout, stderr = proc.communicate(input=key, timeout=30)
        if proc.returncode == 0:
            info(f"LUKS {entry.name} ({dev}) unlocked successfully")
            return True
        else:
            warn(f"systemd-cryptsetup failed for {entry.name}: {stderr.decode()}")
            return False
    except Exception as e:
        warn(f"Error unlocking {entry.name}: {e}")
        return False


def unlock_all_using_key(key: bytes) -> bool:
    """用给定密钥解锁所有 LUKS 分区（线程安全，通过 threading.Lock 保护）"""
    if is_unlock_done():
        return True

    global _unlock_done
    with _unlock_lock:
        if _unlock_done:
            return True

        any_ok = False
        for entry in luks_entries:
            if luks_unlock(entry, key):
                any_ok = True

        if any_ok:
            _unlock_done = True
            info("All LUKS partitions unlocked")
            return True
        return False


# ===== USB 解锁循环 =====
def usb_loop(stop_event: threading.Event):
    """尝试 USB 自动解锁（循环）"""
    for i in range(1, MAX_RETRIES+1):
        if stop_event.is_set() or is_unlock_done():
            return

        info(f"USB attempt {i}/{MAX_RETRIES}...")
        if not wait_for_device(config.usb_uuid):
            warn("USB device not found, retrying...")
            time.sleep(RETRY_INTERVAL)
            continue

        info("USB device found")
        if not mount_usb(config.usb_uuid):
            continue

        key = read_keyfile(config.keyfile_path)
        umount_usb()

        if key is not None:
            info("Keyfile read, attempting unlock...")
            if unlock_all_using_key(key):
                info("USB key unlock succeeded")
                stop_event.set()
                return
        else:
            warn("Keyfile not found on USB")

        time.sleep(RETRY_INTERVAL)

    warn("USB key unlock failed after all retries")


# ===== 交互式密码输入 =====
def interactive_input(stop_event: threading.Event):
    """从 /dev/console 读取密码作为 fallback"""
    info("Please enter the LUKS password (fallback):")
    try:
        with open("/dev/console", "rb") as console:
            for i in range(MAX_RETRIES):
                if stop_event.is_set() or is_unlock_done():
                    return
                
                sys.stderr.write("Password: ")
                sys.stderr.flush()
                
                try:
                    line = console.readline()
                except Exception:
                    time.sleep(RETRY_INTERVAL)
                    continue
                
                if not line:
                    continue
                pw = line.decode("utf-8", errors="replace").rstrip("\n\r")
                if not pw:
                    continue
                if unlock_all_using_key(pw.encode()):
                    info("Password unlock succeeded")
                    stop_event.set()
                    return
                else:
                    warn("Password incorrect, try again")
    except Exception as e:
        warn(f"Interactive input error: {e}")


# ===== 监控线程 =====
def monitor_unlock(stop_event: threading.Event):
    """监控解锁完成事件，完成后退出程序"""
    while not stop_event.is_set():
        time.sleep(0.5)
        if is_unlock_done():
            stop_event.set()
            time.sleep(1)
            os._exit(0)


# ===== 信号处理 =====
def on_signal(signum, frame):
    """收到 SIGTERM 等信号时退出"""
    os._exit(0)


# ===== 主程序 =====
def main():
    global config, luks_entries

    # 加载配置
    try:
        config = load_config()
    except Exception as e:
        warn(f"Config load failed: {e}")
        sys.exit(1)

    if not config.usb_uuid or not config.keyfile_path:
        warn("USB_UUID and KEYFILE_PATH must be set in config")
        sys.exit(1)

    if not config.luks_conf:
        config.luks_conf = LUKS_CONF_PATH

    try:
        luks_entries = load_luks_conf(config.luks_conf)
    except Exception as e:
        warn(f"LUKS config load failed: {e}")
        sys.exit(1)

    if not luks_entries:
        warn("No LUKS entries in config")
        sys.exit(1)

    # 注册信号处理
    import signal as sig
    sig.signal(sig.SIGTERM, on_signal)

    # 创建停止事件
    stop_event = threading.Event()

    # 启动线程
    usb_thread = threading.Thread(target=usb_loop, args=(stop_event,), daemon=True)
    usb_thread.start()

    interactive_thread = threading.Thread(target=interactive_input, args=(stop_event,), daemon=True)
    interactive_thread.start()

    # 监控线程（在主线程中运行）
    monitor_unlock(stop_event)


if __name__ == "__main__":
    main()
