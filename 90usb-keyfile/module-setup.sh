#!/bin/bash

check() {
    local fs
    # if cryptsetup is not installed, then we cannot support encrypted devices.
    require_binaries "$systemdutildir"/systemd-cryptsetup || return 1

    [[ $hostonly_mode == "strict" ]] || [[ $mount_needs ]] && {
        for fs in "${host_fs_types[@]}"; do
            [[ $fs == "crypto_LUKS" ]] && return 0
        done
        return 255
    }

    return 0
}


depends() {
    # 依赖 blkid、mount 等工具，以及基础文件系统支持
    # deps="systemd-cryptsetup" 不添加依赖, 是因为 systemd-cryptsetup 会依赖crypt模块。
    deps="bash lvm systemd-ask-password"
    echo "$deps"
    return 0
}

install() {
    # ~~关键：安装为 initqueue 阶段的 hook 脚本~~
    # inst_hook initqueue 20 "$moddir/boot-usb-keyfile.sh"
    inst_hook initqueue 20 "$moddir/usb-keyfile.sh"

    # inst_hook pre-mount 20 "$moddir/usb-keyfile.sh"

    # 安装文件到initramfs配置目录
    inst_simple "/etc/usb-keyfile.conf"
    inst_simple "/etc/luks_uuid.conf"
    # inst_simple "$moddir/usb-keyfile.sh" /bin/usb-keyfile.sh

    # 安装必要工具
    inst_multiple \
        systemd-cryptsetup \
        flock \
        blkid \
        mount \
        umount \
        mkdir \
        rmdir \
        cat \
        sleep

    # 安装文件系统模块（vfat, ext4 等）
    inst_multiple -o \
        /sbin/fsck.vfat \
        /sbin/fsck.ext4 \
        /lib/modules/$(uname -r)/kernel/fs/vfat/vfat.ko \
        /lib/modules/$(uname -r)/kernel/fs/ext4/ext4.ko

    # 确保 udev 规则能识别块设备（通常已包含）
}
