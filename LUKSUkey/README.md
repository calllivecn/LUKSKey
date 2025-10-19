# 优先尝试使用 U 盘上的密钥文件自动解锁 LUKS，若 U 盘未插入或密钥无效，则回退到交互式密码输入。

- ✅ 前提条件

    你的根分区已用 LUKS 加密（例如 /dev/sda2）
    你有一个 U 盘，格式化为 ext4/vfat 等，并知道其 文件系统 UUID

    ```shell
    sudo blkid /dev/sdX1  # 查看 UUID
    # 示例输出：/dev/sdb1: UUID="1234-5678" TYPE="vfat"
    U 盘上有一个 keyfile，例如 /keyfile.bin
    该 keyfile 已添加到 LUKS 卷的密钥槽：
    sudo cryptsetup luksAddKey /dev/sdX2 /path/to/keyfile.bin
    ```

## 调试技巧

- 在启动时中断 initramfs：

- 在 GRUB 启动项中添加 break=local-top，系统会在执行 local-top 脚本前进入 shell。

- 可手动运行你的脚本、检查设备、测试命令。

```
你想做什么？	推荐阶段
加载关键内核模块（如 NVMe、加密）               init-top
启动网络、连接远程存储                      init-premount
解密本地根分区、激活 LVM                    local-top
清理资源、传递状态给真实系统                    local-bottom
```

- 日志输出：

    - 所有 log_* 输出会显示在控制台。

    - 也可重定向到 /run/initramfs/log（如果启用了日志缓冲）。
