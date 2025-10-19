`initramfs-tools` 是 Debian/Ubuntu 系统中用于生成 initramfs（即 `initrd.img`）的工具包。它通过收集系统中的必要文件（如内核模块、脚本、二进制程序等）并打包成一个压缩的 cpio 归档（通常用 gzip 或 lz4 压缩），供内核在启动早期阶段挂载根文件系统前使用。

如果你希望像 `dracut` 那样通过“模块”方式扩展 `initramfs-tools` 的功能，可以按照以下方式操作：

---

## 一、initramfs-tools 的结构概述

`initramfs-tools` 的主要组件包括：

- `/usr/share/initramfs-tools/`：存放核心脚本和默认 hook、脚本等。
  - `hooks/`：定义哪些文件/模块需要打包进 initramfs。
  - `scripts/`：定义 initramfs 启动时执行的脚本（如 `local-top`、`local-premount` 等）。
  - `modules/`：较少使用，但可放模块相关脚本。
- `/etc/initramfs-tools/`：系统管理员自定义配置目录。
  - `hooks/`：用户自定义 hook。
  - `scripts/`：用户自定义启动脚本。
  - `conf.d/`：配置文件。
  - `modules`：列出需要包含的内核模块。

---

## 二、添加自定义功能（类似 dracut 模块）

### 步骤 1：创建自定义 hook

Hook 负责将你的二进制、配置文件、内核模块等复制到 initramfs 的临时构建目录中。

例如，创建 `/etc/initramfs-tools/hooks/myfeature`：

```sh
#!/bin/sh
# /etc/initramfs-tools/hooks/myfeature

PREREQ=""

prereqs() {
    echo "$PREREQ"
}

case "$1" in
    prereqs)
        prereqs
        exit 0
        ;;
esac

. /usr/share/initramfs-tools/hook-functions

# 示例：复制一个二进制文件
copy_exec /usr/bin/mytool /bin/mytool

# 示例：复制一个配置文件
mkdir -p "${DESTDIR}/etc/myfeature"
cp -a /etc/myfeature/config "${DESTDIR}/etc/myfeature/"

# 示例：包含一个内核模块（如果需要）
manual_add_modules mymodule
```

确保脚本可执行：

```bash
chmod +x /etc/initramfs-tools/hooks/myfeature
```

### 步骤 2：创建启动脚本

在 initramfs 启动过程中，你需要在合适的阶段执行你的逻辑。脚本放在：

- `/etc/initramfs-tools/scripts/init-top/`：早期初始化（网络、设备尚未就绪）
- `/etc/initramfs-tools/scripts/init-premount/`
- `/etc/initramfs-tools/scripts/local-top/`：本地磁盘已识别，但根文件系统尚未挂载
- `/etc/initramfs-tools/scripts/local-bottom/`：根文件系统已挂载，即将切换根

例如，创建 `/etc/initramfs-tools/scripts/local-top/myfeature`：

```sh
#!/bin/sh
# /etc/initramfs-tools/scripts/local-top/myfeature

PREREQ=""

prereqs() {
    echo "$PREREQ"
}

case "$1" in
    prereqs)
        prereqs
        exit 0
        ;;
esac

# 实际逻辑
log_begin_msg "Running myfeature setup..."
if [ -x /bin/mytool ]; then
    /bin/mytool --initramfs-mode
fi
log_end_msg
```

同样，设为可执行：

```bash
chmod +x /etc/initramfs-tools/scripts/local-top/myfeature
```

### 步骤 3：更新 initramfs

生成新的 `initrd.img`：

```bash
sudo update-initramfs -u -k all
# 或只更新当前内核：
sudo update-initramfs -u
```

生成的文件通常位于 `/boot/initrd.img-$(uname -r)`。

---

## 三、调试技巧

- **解包 initramfs** 查看内容：

```bash
mkdir /tmp/initrd
cd /tmp/initrd
zcat /boot/initrd.img-$(uname -r) | cpio -idmv
```

- **查看 hook 执行过程**：

```bash
sudo update-initramfs -v -u
```

`-v` 参数会显示详细过程，包括哪些 hook 被调用、复制了哪些文件。

---

## 四、与 dracut 模块对比

| 功能 | dracut | initramfs-tools |
|------|--------|------------------|
| 模块机制 | 显式模块目录（`/usr/lib/dracut/modules.d/`） | 通过 hooks + scripts 实现 |
| 配置方式 | 模块 + 配置文件 | hook 脚本 + 启动脚本 |
| 扩展性 | 更模块化、灵活 | 更脚本化、轻量 |
| 发行版 | RHEL/Fedora/SUSE | Debian/Ubuntu |

虽然 `initramfs-tools` 没有 dracut 那样显式的“模块”概念，但通过 hook + script 的组合，完全可以实现类似功能。

---

## 五、进阶：打包为 deb 包（可选）

如果你希望将你的功能打包分发，可以创建一个 `.deb` 包，将 hook 和 script 安装到 `/usr/share/initramfs-tools/` 下（注意：系统级 hook 通常放这里，用户级放 `/etc/`）。

例如：

- `DEBIAN/postinst` 中调用 `update-initramfs -u`
- 文件结构：
  ```
  usr/share/initramfs-tools/hooks/myfeature
  usr/share/initramfs-tools/scripts/local-top/myfeature
  ```

---

如果你能具体说明你想添加什么功能（比如支持某种加密、网络启动、自定义设备识别等），我可以给出更针对性的 hook/script 示例。
