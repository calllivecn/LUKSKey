# 代理说明

## 仓库结构

- 仓库包含多个 initramfs 实验。当前维护的 USB dracut 实现是 `90usb-keyfile/py`；`90usb-keyfile/sh` 是旧版 hook 实现，`90usb-keyfile/go` 尚未完成。
- Python 实现不会在 initramfs 中直接运行源码：`usb-keyfile.spec` 构建自包含的 PyInstaller 可执行文件，`install.sh` 部署 `dist/usb-keyfile`。
- 运行时 wiring 位于 `90usb-keyfile/py/module-setup.sh` 和 `usb-keyfile.service`：服务链接到 initramfs 的 `sysinit.target.wants`，在 `initrd-root-device.target` 之前运行，并启动 `/usr/local/bin/usb-keyfile`。

## 构建与部署

- 使用 Python 3.12（见 `.python-version`）。仓库没有测试运行器或 CI 配置；`pyproject.toml` 不是 dracut 可执行文件的构建配置。
- 在 `90usb-keyfile/py` 目录执行 `pyinstaller usb-keyfile.spec` 构建部署用可执行文件。必须先构建再运行 `install.sh`，因为安装脚本要求存在 `dist/usb-keyfile`。
- 仍在该目录执行 `sudo ./install.sh`。脚本将模块安装到 `/usr/lib/dracut/modules.d/90usb-keyfile/`，仅当 `/etc/usb-keyfile.toml` 不存在时才创建它；脚本会删除并重新创建已安装的模块目录，执行前不要留下未经检查的工作树内容。
- 修改模块文件或 `/etc/usb-keyfile.toml` 后，通常使用 `sudo dracut -v --force` 重建目标 initramfs。确认 dracut 配置包含 `add_dracutmodules+=" usb-keyfile "`，重启前用 `lsinitrd` 检查生成的镜像。

## 运行时与配置

- `module-setup.sh` 会把 `/etc/usb-keyfile.toml` 复制进镜像；该文件定义一个 `[usb]` UUID/keyfile 以及一个或多个 `[[luks]]` 条目。仓库中的 UUID 是示例值，不是生产设备标识。
- 可执行文件轮询 `/dev/disk/by-uuid`，将 USB 只读挂载到 `/run/usb`，对每个 LUKS 条目调用 `systemd-cryptsetup attach`，同时等待 `systemd-ask-password` 输入；任一路径成功后退出。
- 模块会打包 `systemd-cryptsetup`、`mount`、`umount`、选定的 `vfat`/`ext4` 支持和服务单元，但依赖宿主机、内核以及 dracut 的 systemd 配置。修改服务顺序或模块依赖后必须进行 initramfs 启动测试。
- `module-setup.sh` 使用 systemd 服务，而不是 `inst_hook initqueue` hook；其中提到旧 initqueue 方案的注释已经过时。

## 验证与调试

- 仓库没有自动化测试。`90usb-keyfile/py/test/test-dev-console.py` 是手动 `/dev/console` 实验，不能作为普通单元测试运行；`test/systemdcryptsetup.service` 是手动 initramfs 实验。
- 构建前执行以下廉价检查：`python3 -m py_compile 90usb-keyfile/py/usb-keyfile.py` 和 `bash -n 90usb-keyfile/py/module-setup.sh 90usb-keyfile/py/install.sh`。功能验证需要可丢弃的加密启动环境、真实 USB 设备和 LUKS 卷。
- 启动失败时移除 `quiet`/`rhgb`，使用 `rd.shell`/`rd.debug`，并使用 `rd.break=initqueue` 或其他相关 dracut 断点。检查 `/run/initramfs/rdsosreport.txt` 和生成的镜像，不要只调试宿主机中的脚本副本。
