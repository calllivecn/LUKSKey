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
CONF_PATH = Path("/etc/usb-keyfile.toml")
MOUNT_POINT = Path("/run/usb")
INTERACTIVE_PW = Path("/run/usb-keyfile-pw-file")
MAX_RETRIES = 30
RETRY_INTERVAL = 1.0  # 秒

DEV_BY_UUID = Path("/dev/disk/by-uuid")


class Config:
    """配置类，直接存储解析后的 TOML 配置"""
    def __init__(self, usb_uuid: str = "", keyfile: str = ""):
        self.usb_uuid = usb_uuid
        self.keyfile = Path(keyfile)


class LUKSEntry:
    """LUKS 分区条目（uuid 和 name）"""
    def __init__(self, name: str, uuid: str, options: Optional[None]):
        self.name = name
        self.uuid = uuid
        self.options = options


# ===== 全局状态 =====
config:  Config
luks_entries: list[LUKSEntry]
_unlock_lock = threading.Lock()
# _unlock_done = False


# ===== 日志 =====
def info(msg: str):
    """输出 INFO 日志"""
    with open("dev/console", "w+") as console:
        print(f"usb-keyfile: INFO: {msg}", file=console, flush=True)


def warn(msg: str):
    """输出 WARN 日志"""
    with open("dev/console", "w+") as console:
        print(f"usb-keyfile: WARN: {msg}", file=console, flush=True)


# ===== 配置加载 =====
def load_config(path: Path = CONF_PATH) -> tuple[Config, list[LUKSEntry]]:
    """加载 TOML 配置文件，返回 Config 和 LUKS 条目列表"""
    if not path.is_file():
        raise FileNotFoundError(f"Config file not found: {path}")

    with open(path, "rb") as f:
        data = tomllib.load(f)

    # 解析 [usb] 部分
    usb_section = data["usb"]
    cfg = Config(usb_section["uuid"], usb_section["keyfile"])

    # 解析 [luks] 部分
    luks_section = data.get("luks", {})
    raw_partitions = luks_section.get("partitions", [])

    entries: list[LUKSEntry] = []
    for part in raw_partitions:
        if isinstance(part, dict):
            n = part["name"]
            u = part["uuid"]
            opt = part.get("options")
            if u and n:
                entries.append(LUKSEntry(u, n, opt))

    return cfg, entries


# ===== USB 相关操作 =====

def wait_for_device(uuid: str) -> bool:
    """等待 USB 设备出现（检查 /dev/disk/by-uuid 目录），最多重试 MAX_RETRIES 次"""
    target = DEV_BY_UUID / uuid
    info(f"Waiting for device {uuid}...")
    for _ in range(MAX_RETRIES):
        if target.exists():
            info(f"Device {uuid} found via {target.resolve()}")
            return True
        time.sleep(RETRY_INTERVAL)
    return False


def resolve_luks_device(uuid: str) -> Optional[Path]:
    """通过 /dev/disk/by-uuid 解析 UUID 对应的设备路径"""
    target = DEV_BY_UUID / uuid
    try:
        return target.resolve(strict=True)
    except (FileNotFoundError, RuntimeError):
        warn(f"Cannot resolve UUID {uuid} to a device")
        return None


def mount_usb(uuid: str) -> bool:
    """挂载 USB 设备为只读"""
    MOUNT_POINT.mkdir(parents=True, exist_ok=True)
    cmd = ["mount", "-vt", "auto", "-o", "ro", "-U", uuid, MOUNT_POINT]
    try:
        subprocess.run(cmd, check=True, capture_output=True, timeout=10)
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


# ===== LUKS 解锁 =====
def luks_unlock(keyfile: Path, entry: LUKSEntry) -> bool:
    """向 systemd-cryptsetup 提供密钥解锁一个 LUKS 分区"""
    dev = resolve_luks_device(entry.uuid)
    if not dev:
        warn(f"Cannot find device for LUKS UUID {entry.uuid}")
        return False

    
    cmd = ["systemd-cryptsetup", "attach", entry.name, dev, keyfile]
    if entry.options:
        cmd.append(entry.options)

    try:
        proc = subprocess.run(cmd, capture_output=True, timeout=30)
        if proc.returncode == 0:
            info(f"LUKS {entry.name} ({dev}) unlocked successfully")
            return True
        else:
            warn(f"systemd-cryptsetup failed for {entry.name} ...")
            return False
    except Exception as e:
        warn(f"Error unlocking {entry.name}: {e}")
        return False


def unlock_all_using_key(keyfile: Path) -> bool:
    """用给定密钥解锁所有 LUKS 分区（线程安全，通过 threading.Lock 保护）"""

    if keyfile.exists() and keyfile.is_file():
        pass
    else:
        raise FileNotFoundError(f"keyfile: {keyfile} is not found!")

    with _unlock_lock:
        any_ok = False
        for entry in luks_entries:
            if luks_unlock(keyfile, entry):
                any_ok = True

        if any_ok:
            info("All LUKS partitions unlocked")
            return True
        
        return False


# ===== USB 解锁循环 =====
def usb_loop(stop_event: threading.Event):
    """尝试 USB 自动解锁（循环）"""
    for i in range(1, MAX_RETRIES + 1):
        if stop_event.is_set():
            return

        info(f"USB attempt {i}/{MAX_RETRIES}...")
        if not wait_for_device(config.usb_uuid):
            warn("USB device not found, retrying...")
            time.sleep(RETRY_INTERVAL)
            continue

        info("USB device found")
        if not mount_usb(config.usb_uuid):
            continue

        info("USB keyfile found")

        if config.keyfile.is_file():
            info("Keyfile read, attempting unlock...")
            if unlock_all_using_key(config.keyfile):
                info("USB key unlock succeeded")
                stop_event.set()
                return
        else:
            warn("Keyfile not found on USB")

        time.sleep(RETRY_INTERVAL)

        umount_usb()

    warn("USB key unlock failed after all retries")


# ===== 交互式密码输入 =====
def interactive_input(stop_event: threading.Event):
    """从 /dev/console 读取密码作为 fallback"""
    info("Please enter the LUKS password (fallback):")

    try:
        with open("/dev/console", "rb") as console:
            for _ in range(MAX_RETRIES):
                if stop_event.is_set():
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
                info(f"当前的输入：{pw}")
                if not pw:
                    continue

                with open(INTERACTIVE_PW, "w") as f:
                    f.write(pw)
                
                os.chmod(INTERACTIVE_PW, 0o400)

                if unlock_all_using_key(INTERACTIVE_PW):
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
        if _unlock_lock.locked():
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
        config, luks_entries = load_config()
    except Exception as e:
        warn(f"Config load failed: {e}")
        sys.exit(1)

    if not config.usb_uuid or not config.keyfile:
        warn("USB_UUID and KEYFILE must be set in config")
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
