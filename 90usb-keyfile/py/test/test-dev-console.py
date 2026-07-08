import io
import sys
import termios

# 测试ok
class InputAndLog:
    def __init__(self):
        # 方案一完美封装
        raw_console = open('/dev/console', 'r+b', buffering=0)
        self.console = io.TextIOWrapper(raw_console, encoding='ascii', line_buffering=True)

    def log(self, msg):
        # 安全地输出到控制台，防止楼梯输出
        print(f"usb-keyfile: INFO: {msg}", file=self.console, end="\r\n", flush=True)

    def ask(self, prompt):
        # 临时将 stdin/stdout 切到 console 供 input() 使用
        old_stdin, old_stdout = sys.stdin, sys.stdout
        try:
            sys.stdin = self.console
            sys.stdout = self.console
            # 注意：input 内部也会用到 sys.stdout 打印 prompt
            return input(prompt)
        finally:
            sys.stdin = old_stdin
            sys.stdout = old_stdout

# 使用示例
#ial = InputAndLog()
#ial.log("detect USB keyfile...")
#passwd = ial.ask("password: ")
#ial.log("unlocking...")


# 在测试关闭echo功能
class InputAndLog2(InputAndLog):
    def __init__(self):
        super().__init__()

    def ask(self, prompt):
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


ial = InputAndLog2()
ial.log("detect USB keyfile...")
passwd = ial.ask("password: ")
ial.log(f"this input password: {passwd}")
ial.log("unlocking...")

