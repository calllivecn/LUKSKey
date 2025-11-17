# 📁 dracut 模块结构

- 文件列表:

```
/usr/lib/dracut/modules.d/90usb-keyfile/
├── module-setup.sh    # 声明依赖、安装文件
├── usb-keyfile.sh     # 运行时脚本（在 initramfs 中执行）
└── usb-keyfile.conf   # 脚本配置（自动安装到 initramfs 中的）
```


## 安装与使用

- dracut 模块通常放在, 安装到这里(ubuntu25.10)：

```
/usr/lib/dracut/modules.d/90usb-keyfile/
```

- 修改dracut 配置

```
# vim /etc/dracut.conf.d/your-usbkeyfile.conf
add_dracutmodules+=" usb-keyfile " # 注意这里前后都要有空格
omit_dracutmodules+=" crypt systemd-cryptsetup " # 创建initramfs 时，排队系统自带的模块。
```

- 更新initramfs

```
dracut --force
```

- 重启系统开始


## 调试

- linux 命令参数中添加:

- rd.shell：

    作用： 如果 dracut 无法完成启动（例如找不到根文件系统），它将停止并为您提供一个 debug shell（紧急 shell）。

- rd.debug:

    ```text
    启用 dracut shell 脚本中的 set -x 模式。这意味着执行的每条命令及其参数都会被打印到控制台或日志中。

    移除干扰参数：
    移除 rhgb 和 quiet： 它们会隐藏大部分启动信息，调试时应将其移除，以便您能看到所有启动信息和 dracut 的详细输出。

    使用报告文件 (rdsosreport.txt):
    如果 dracut 失败并进入紧急 shell，它会生成一个包含大量系统信息和日志的报告文件。

    报告文件路径： /run/initramfs/rdsosreport.txt
    ```

- rd.break:
    作用： 允许您在 dracut 流程中的特定断点暂停并进入 shell。这对于检查特定阶段（如设备初始化、udev 规则执行、挂载前等）的状态非常有用。

    常见断点示例：
    
    rd.break=cmdline
    
    rd.break=pre-udev
    
    rd.break=initqueue
    
    rd.break=pre-mount
    
    rd.break=mount
    
    rd.break=pre-pivot
    
    rd.break=cleanup

    提示：您可以通过搜索 /usr/lib/dracut/modules.d/*/init.sh 或使用 egrep 'rd.?break' /usr/lib/dracut/modules.d/99base/init.sh 来查看所有可用的断点。


---

## 完整的调试流程

这是一个非常精确且高效的调试方法！在 `rd.break` 模式下手动执行特定模块脚本，可以完全隔离该模块的逻辑，避免其他模块的干扰。

由于您是高级用户，我们可以直接使用 shell 的内置功能来实现这一目标。

-----

## 在 `rd.break` Shell 中手动调试模块脚本

### 1\. 准备工作：定位脚本和选择断点

#### A. 确定模块脚本路径

您需要知道您的模块脚本在 **`initramfs` 内部**的完整路径。

  * **如果它是模块的主脚本：** 通常是 `/usr/lib/dracut/modules.d/<NNmodule>/init.sh`。
  * **如果它是 Hook 脚本：** 它将位于 `dracut` 的 hooks 目录中，例如：
      * `pre-mount` 阶段的 Hook：`/lib/dracut/hooks/pre-mount/<NN-script.sh>`
      * `initqueue` 阶段的 Hook：`/lib/dracut/hooks/initqueue/<NN-script.sh>`

#### B. 选择调试断点 (`rd.break`)

您选择的断点必须是**在您的模块脚本正常执行之前**的阶段。

  * **如果您的模块是在 `pre-mount` 之前运行，** 推荐使用 **`rd.break=initqueue`** 或 **`rd.break=pre-udev`**。
  * **如果您的模块是处理命令行参数，** 推荐使用 **`rd.break=cmdline`**。

> **重要提示：** 请确保您使用的内核参数中**移除**了 `quiet` 和 `rhgb`，以便看到完整的输出。

### 2\. 执行步骤：隔离与追踪

假设您要调试的模块脚本路径是 `MY_MODULE_SCRIPT="/usr/lib/dracut/modules.d/90mymodule/init.sh"`，并且您在 GRUB 中设置了 `rd.break=initqueue`。

#### Step 1: 进入 `rd.break` Debug Shell

重启系统，在 GRUB 菜单中添加 `rd.break=<breakpoint>`，系统会在指定阶段暂停，并提示您进入 debug shell。

#### Step 2: 准备调试环境

在进入的 shell 中，执行以下命令：

```bash
# 1. 设置变量（如果需要），并指定要调试的脚本路径
# 确保您了解您的模块依赖哪些环境变量或函数。
MY_MODULE_SCRIPT="/usr/lib/dracut/modules.d/90mymodule/init.sh"

# 2. 开启 Shell 追踪 (set -x)
# 这是调试的核心。它会打印出脚本执行的每一行命令及其参数，
# 让您清楚地看到数据流和逻辑判断。
set -x
```

#### Step 3: 手动执行模块脚本

使用 **`.` (点号，即 `source`)** 命令来执行您的模块脚本。

```bash
# 使用 . 命令（source）来执行脚本，使其在当前 shell 环境中运行
# 这样脚本中设置的变量、定义的函数等都会保留在当前 shell 中，
# 就像 dracut 正常执行它一样。
. "${MY_MODULE_SCRIPT}"
```

执行完毕后，屏幕上将滚动显示脚本执行的每一个步骤。

#### Step 4: 检查状态和关闭追踪

脚本运行完成后，您可以检查其执行的结果：

  * 使用 `echo $?` 检查脚本的退出状态码。
  * 检查模块应该创建或修改的文件（例如 `/etc/cmdline.d/` 或 `/dev/` 下的设备）。
  * 检查任何全局变量是否如预期设置。

调试完成后，关闭追踪以清理环境：

```bash
# 关闭 Shell 追踪
set +x

# 检查结果，例如：
# ls -l /dev/mapper/
# echo $MY_ROOT_DEVICE
```

#### Step 5: 继续启动流程

当您完成调试和检查后，键入 `exit` 命令，`dracut` 将从上次中断的地方继续正常的启动流程。

```bash
exit
```

-----

## 💡 为什么使用 `.` (点号)

在 Linux Shell 编程中：

  * **`bash /path/to/script.sh` (或 `./script.sh`)：** 会启动一个新的子 Shell 来执行脚本。脚本中的任何变量或函数定义在脚本执行完毕后都会消失，不会影响父 Shell（即当前的 `rd.break` Shell）。
  * **`. /path/to/script.sh` (或 `source /path/to/script.sh`)：** 会在**当前** Shell 环境中执行脚本。这与 `dracut` 运行 Hook 脚本的方式一致。您的模块中设置的任何重要状态（例如 `udev` 变量、全局的根设备变量等）都会保留在当前环境中，以便您检查，或在 `exit` 后影响后续的 `dracut` 启动流程。