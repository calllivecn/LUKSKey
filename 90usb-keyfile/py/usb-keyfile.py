#!/usr/bin/python3

"""
usb-keyfile.py - dracut initramfs hook 的 Python 实现
功能：在 initramfs 阶段检测 USB 设备、读取 keyfile 并解锁 LUKS 分区，
同时提供交互式密码输入作为 fallback。

依赖：Python 3.12+ 标准库（无第三方依赖）
"""

import os
import io
import sys
import time
import tomllib
import termios
import subprocess
import atexit
import threading
from pathlib import Path
from typing import Optional

# ===== 常量 =====
CONF_PATH = Path("/etc/usb-keyfile.toml")
MOUNT_POINT = Path("/run/usb")
INTERACTIVE_PW = Path("/run/usb-keyfile-pw-file")
MAX_RETRIES = 180
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
global config, luks_entries
config:  Config
luks_entries: list[LUKSEntry]

_unlock_lock = threading.Lock()
# _unlock_done = False


# ===== 输入/输出/日志 =====

class InputAndLog:

    def __init__(self):
        # 方案一完美封装
        raw_console = open('/dev/console', 'r+b', buffering=0)
        # self.console = io.TextIOWrapper(raw_console, encoding='ascii', line_buffering=True)
        self.console = io.TextIOWrapper(raw_console, encoding='utf-8', errors='surrogateescape', line_buffering=True)

    def log(self, msg: str):
        # 安全地输出到控制台，防止楼梯输出
        print(f"usb-keyfile: INFO: {msg}", file=self.console, end="\r\n", flush=True)

    def ask(self, prompt: str) -> str:
        p = subprocess.run(["systemd-ask-password", "--echo=no", prompt], stdout=subprocess.PIPE, check=True)
        return p.stdout.strip().decode("utf-8")

    def ask_old(self, prompt: str) -> str:
        # 1. 打印提示词（注意 \r\n 换行适配）
        print(prompt, file=self.console, end="", flush=True)

        # 2. 获取底层的系统文件描述符 (FD)
        fd = self.console.fileno()

        # 3. 备份原始终端属性
        old_attr = termios.tcgetattr(fd)
        new_attr = termios.tcgetattr(fd)

        # 4. 关闭 ECHO (回显) 和 ICANON (行缓冲，可选，但关闭 ECHO 核心是这个)
        # lflag [3] 是本地模式标志
        new_attr[3] = new_attr[3] & ~termios.ECHO

        try:
            # 应用新属性（TCSAFLUSH 表示清空输入队列后应用）
            termios.tcsetattr(fd, termios.TCSAFLUSH, new_attr)

            # 5. 读取密码（此时键盘输入在屏幕上不可见）
            # 注意：因为重定向了，这里直接用 self.console 读一行
            password = self.console.readline()

            # 换个行，免得接下来的日志和提示词挤在同一行
            print("", file=self.console, end="\r\n", flush=True)
            return password.rstrip('\r\n')

        finally:
            # 6. 无论如何，一定要恢复原有的终端属性，否则后续系统终端会卡死或无法显示
            termios.tcsetattr(fd, termios.TCSAFLUSH, old_attr)

    def info(self, msg: str):
        """输出 INFO 日志"""
        print(f"usb-keyfile: INFO: {msg}", file=self.console, end="\r\n", flush=True)

    def warn(self, msg: str):
        """输出 WARN 日志"""
        print(f"usb-keyfile: WARN: {msg}", file=self.console, end="\r\n", flush=True)
    
    def close(self):
        self.console.close()


ial = InputAndLog()
atexit.register(lambda: ial.close())

# ===== 配置加载 =====
def load_config(path: Path = CONF_PATH) -> tuple[Config, list[LUKSEntry]]:
    """加载 TOML 配置文件，返回 Config 和 LUKS 条目列表"""
    if not path.is_file():
        raise FileNotFoundError(f"Config file not found: {path}")

    with open(path, "rb") as f:
        data = tomllib.load(f)
    
    # ial.info(f"usb-keyfile.toml -> {data}")

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
                entries.append(LUKSEntry(n, u, opt))

    return cfg, entries


# ===== USB 相关操作 =====

def wait_for_device(uuid: str) -> bool:
    """等待 USB 设备出现（检查 /dev/disk/by-uuid 目录），最多重试 MAX_RETRIES 次"""
    target = DEV_BY_UUID / uuid
    ial.info(f"Waiting for device {uuid}...")
    for _ in range(MAX_RETRIES):
        if target.exists():
            ial.info(f"Device {uuid} found via {target.resolve()}")
            return True
        time.sleep(RETRY_INTERVAL)
    return False


def resolve_luks_device(uuid: str) -> Optional[Path]:
    """通过 /dev/disk/by-uuid 解析 UUID 对应的设备路径"""
    target = DEV_BY_UUID / uuid
    try:
        return target.resolve(strict=True)
    except (FileNotFoundError, RuntimeError):
        ial.warn(f"Cannot resolve UUID {uuid} to a device")
        return None


def mount_usb(uuid: str) -> bool:
    """挂载 USB 设备为只读"""
    MOUNT_POINT.mkdir(parents=True, exist_ok=True)
    cmd = ["mount", "-vt", "auto", "-o", "ro", "-U", uuid, MOUNT_POINT]
    try:
        subprocess.run(cmd, check=True, capture_output=True, timeout=10)
        return True
    except subprocess.CalledProcessError as e:
        ial.warn(f"mount failed: {e.stderr.decode() if e.stderr else ''}")
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
        ial.warn(f"Cannot find device for LUKS UUID {entry.uuid}")
        return False

    
    cmd = ["systemd-cryptsetup", "attach", entry.name, dev, keyfile]
    if entry.options:
        cmd.append(entry.options)

    try:
        proc = subprocess.run(cmd, capture_output=True, timeout=30)
        if proc.returncode == 0:
            ial.info(f"LUKS {entry.name} ({dev}) unlocked successfully")
            return True
        else:
            ial.warn(f"systemd-cryptsetup failed for {entry.name} ...")
            return False
    except Exception as e:
        ial.warn(f"Error unlocking {entry.name}: {e}")
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
            ial.info("All LUKS partitions unlocked")
            return True
        
        return False


# ===== USB 解锁循环 =====
def usb_loop(stop_event: threading.Event):
    """尝试 USB 自动解锁（循环）"""

    global config

    if not config.usb_uuid or not config.keyfile:
        ial.warn("USB_UUID and KEYFILE must be set in config")
        return


    for i in range(1, MAX_RETRIES + 1):
        if stop_event.is_set():
            return

        ial.info(f"USB attempt {i}/{MAX_RETRIES}...")
        if not wait_for_device(config.usb_uuid):
            ial.warn("USB device not found, retrying...")
            time.sleep(RETRY_INTERVAL)
            continue

        ial.info("USB device found")
        if not mount_usb(config.usb_uuid):
            continue

        ial.info("USB keyfile found")

        if config.keyfile.is_file():
            ial.info("Keyfile read, attempting unlock...")
            if unlock_all_using_key(config.keyfile):
                ial.info("USB key unlock succeeded")
                stop_event.set()
                break
        else:
            ial.warn("Keyfile not found on USB")

        time.sleep(RETRY_INTERVAL)

    umount_usb()
    ial.warn("USB key unlock failed after all retries")


# ===== 交互式密码输入 =====
def interactive_input(stop_event: threading.Event):
    """从 /dev/console 读取密码作为 fallback"""

    try:
        for _ in range(MAX_RETRIES):
            if stop_event.is_set():
                return

            try:
                pw = ial.ask("Please enter the LUKS password: ")
            except Exception:
                time.sleep(RETRY_INTERVAL)
                continue

            if not pw:
                continue

            with open(INTERACTIVE_PW, "w") as f:
                f.write(pw)
            
            os.chmod(INTERACTIVE_PW, 0o400)

            if unlock_all_using_key(INTERACTIVE_PW):
                ial.info("Password unlock succeeded")
                stop_event.set()
                INTERACTIVE_PW.unlink()
                break
            else:
                ial.warn("Password incorrect, try again")
                INTERACTIVE_PW.unlink()

    except Exception as e:
        ial.warn(f"Interactive input error: {e}")


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
        ial.warn(f"Config load failed: {e}")
        sys.exit(1)

    if not luks_entries:
        ial.warn("No LUKS entries in config")
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

    # 核心修改：让主线程在这里安全地阻塞，静静等待任何一个子线程解锁成功后发出信号
    stop_event.wait()

    # 醒来代表解锁成功了，优雅退出
    ial.info("Exiting usb-keyfile securely.")
    sys.exit(0)

if __name__ == "__main__":
    main()
