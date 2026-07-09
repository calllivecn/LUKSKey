#!/usr/bin/python3

"""
usb-keyfile.py - dracut initramfs 模块的 Python 实现
功能：在 initramfs 阶段检测 USB 设备、读取 keyfile 并解锁 LUKS 分区，
同时提供交互式密码输入作为并行方案。

依赖：Python 3.12+ 标准库（打包时依赖pyinstaller）
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
from dataclasses import dataclass

# ===== 常量 =====
CONF_PATH = Path("/etc/usb-keyfile.toml")
MOUNT_POINT = Path("/run/usb")
INTERACTIVE_PW = Path("/run/usb-keyfile-pw-file")
MAX_RETRIES = 180

DEV_BY_UUID = Path("/dev/disk/by-uuid")


@dataclass
class LUKSEntry:
    """LUKS 分区条目（uuid 和 name）"""
    name: str
    uuid: str
    options: str|None


class Config:

    def __init__(self, path: Path = CONF_PATH):
        """加载 TOML 配置文件，返回 Config 和 LUKS 条目列表"""
        if not path.is_file():
            raise FileNotFoundError(f"Config file not found: {path}")

        with open(path, "rb") as f:
            data = tomllib.load(f)
        
        # ial.info(f"usb-keyfile.toml -> {data}")

        self.luks_unlocking = threading.Lock()
        # 创建停止事件
        self.stop_event = threading.Event()

        # 解析 [usb] 部分
        usb = data["usb"]
        self.usb_uuid: str = usb["uuid"]
        self.usb_keyfile: str = usb["keyfile"]

        # 解析 [luks] 部分
        luks_list = data["luks"]

        self.entries: list[LUKSEntry] = []
        for part in luks_list:
            if isinstance(part, dict):
                n = part["name"]
                u = part["uuid"]
                opt = part.get("options")
                if u and n:
                    self.entries.append(LUKSEntry(n, u, opt))
    

    def check_usb(self) -> bool:
        self.keyfile_path = MOUNT_POINT / self.usb_keyfile
        if self.keyfile_path.exists() and self.keyfile_path.is_file():
            return True
        else:
            return False


# ===== 输入/输出/日志 =====
class InputAndLog:

    def __init__(self):
        # 方案一完美封装
        raw_console = open('/dev/console', 'r+b', buffering=0)
        # self.console = io.TextIOWrapper(raw_console, encoding='ascii', line_buffering=True)
        self.console = io.TextIOWrapper(raw_console, encoding='utf-8', errors='surrogateescape', line_buffering=True)

    def log(self, msg: str, level: str = "INFO"):
        # 安全地输出到控制台，防止楼梯输出
        print(f"usb-keyfile: {level}: {msg}", file=self.console, end="\r\n", flush=True)
    
    def info(self, msg: str):
        """输出 INFO 日志"""
        self.log(msg, "INFO")

    def warn(self, msg: str):
        """输出 WARN 日志"""
        self.log(msg, "WARN")

    def ask(self, prompt: str) -> str:
        p = subprocess.run(["systemd-ask-password", "--echo=no", "--timeout=30", prompt], stdout=subprocess.PIPE, check=True)
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
    
    def close(self):
        self.console.close()


ial = InputAndLog()
atexit.register(lambda: ial.close())


# ===== USB 相关操作 =====

def wait_for_device(uuid: str) -> bool:
    """等待 USB 设备出现（检查 /dev/disk/by-uuid 目录），最多重试 MAX_RETRIES 次"""
    target = DEV_BY_UUID / uuid
    ial.info(f"Waiting for device {uuid}...")
    if target.exists():
        ial.info(f"Device {uuid} found via {target.resolve()}")
        return True
    else:
        return False


def resolve_luks_device(uuid: str) -> Path|None:
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
        subprocess.run(cmd, check=True, timeout=30)
        return True
    except subprocess.CalledProcessError as e:
        ial.warn(f"mount failed: {e.stderr.decode() if e.stderr else ''}")
        return False


def umount_usb():
    """卸载 USB 并清理挂载点"""
    subprocess.run(["umount", MOUNT_POINT], timeout=30)
    try:
        MOUNT_POINT.unlink()
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
        proc = subprocess.run(cmd, timeout=90)
        if proc.returncode == 0:
            ial.info(f"LUKS {entry.name} ({dev}) unlocked successfully")
            return True
        else:
            ial.warn(f"systemd-cryptsetup failed for {entry.name} {entry.uuid} ...")
            return False
    except Exception as e:
        ial.warn(f"Error unlocking {entry.name}: {e}")
        return False


def unlock_all_using_usb_key(config: Config) -> bool:
    """用给定密钥解锁所有 LUKS 分区（线程安全，通过 threading.Lock 保护）"""

    if not config.check_usb():
        raise FileNotFoundError(f"keyfile: {config.usb_keyfile} is not found!")

    with config.luks_unlocking:
        all_ok = []
        for entry in config.entries:
            if luks_unlock(config.keyfile_path, entry):
                all_ok.append(True)
            else:
                ial.warn(f"Unlock {entry.name} {entry.uuid} failed.")
                all_ok.append(False)

        if all(all_ok):
            ial.info("All LUKS partitions unlocked")
            return True
        
        return False


def unlock_all_using_password(config: Config, pwfile: Path) -> bool:
    """用给定密钥解锁所有 LUKS 分区（线程安全，通过 threading.Lock 保护）"""

    if pwfile.exists() and pwfile.is_file():
        pass
    else:
        raise FileNotFoundError(f"password file: {pwfile} is not found!")

    with config.luks_unlocking:
        all_ok = []
        for entry in config.entries:
            if luks_unlock(pwfile, entry):
                all_ok.append(True)
            else:
                ial.warn(f"Unlock {entry.name} {entry.uuid} failed.")
                all_ok.append(False)

        if all(all_ok):
            ial.info("All LUKS partitions unlocked")
            return True
        
        return False


# ===== USB 解锁循环 =====
def usb_loop(config: Config):
    """尝试 USB 自动解锁（循环）"""

    if not config.usb_uuid or not config.keyfile_path:
        ial.warn("USB_UUID and KEYFILE must be set in config")
        return

    sleep = 10
    for i in range(1, MAX_RETRIES + 1, sleep):
        if config.stop_event.is_set():
            return

        ial.info(f"USB attempt {i}/{MAX_RETRIES}...")
        if not wait_for_device(config.usb_uuid):
            ial.warn("USB device not found, retrying...")
            time.sleep(sleep)
            continue

        ial.info("USB device found")
        if not mount_usb(config.usb_uuid):
            continue

        if config.check_usb():
            ial.info("USB keyfile found, attempting unlock...")
            if unlock_all_using_usb_key(config):
                ial.info("USB key unlock succeeded")
                config.stop_event.set()
                break
        else:
            ial.warn("Keyfile not found on USB")


        time.sleep(sleep)

    umount_usb()
    ial.warn("USB key unlock failed after all retries")


# ===== 交互式密码输入 =====
def interactive_input(config: Config):
    """从 /dev/console 读取密码解锁"""

    try:
        for _ in range(5):
            if config.stop_event.is_set():
                return

            try:
                while (pw := ial.ask("Please enter the LUKS password: ")) == "":
                    if config.stop_event.is_set():
                        return
                    
            except Exception:
                continue

            if not pw:
                continue

            with open(INTERACTIVE_PW, "w") as f:
                f.write(pw)
            
            os.chmod(INTERACTIVE_PW, 0o400)

            if unlock_all_using_password(config, INTERACTIVE_PW):
                ial.info("Password unlock succeeded")
                config.stop_event.set()
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
    sys.exit(0)


# ===== 主程序 =====
def main():

    # 加载配置
    try:
        config = Config()
    except Exception as e:
        ial.warn(f"Config load failed: {e}")
        sys.exit(1)

    # 注册信号处理
    import signal as sig
    sig.signal(sig.SIGTERM, on_signal)

    # 启动线程
    usb_thread = threading.Thread(target=usb_loop, args=(config,), daemon=True)
    usb_thread.start()

    interactive_thread = threading.Thread(target=interactive_input, args=(config,), daemon=True)
    interactive_thread.start()

    # 核心修改：让主线程在这里安全地阻塞，静静等待任何一个子线程解锁成功后发出信号
    config.stop_event.wait()

    # 醒来代表解锁成功了，优雅退出
    ial.info("Exiting usb-keyfile securely.")
    sys.exit(0)

if __name__ == "__main__":
    main()
