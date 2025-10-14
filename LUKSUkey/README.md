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




