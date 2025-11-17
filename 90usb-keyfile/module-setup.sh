#!/bin/bash

# 模块名称
check() {
    # 只有在使用加密根文件系统时才启用此模块
    #[[ $hostonly ]] || [[ $mount_needs ]] && return 1
    # 检查是否启用了 crypt 模块（必须）
    #if ! dracut_module_included "systemd-cryptsetup"; then
    #    return 1
    #fi
    return 0
}

depends() {
    # 依赖 blkid、mount 等工具，以及基础文件系统支持
    #echo "systemd-cryptsetup"
    return 0
}

install() {
	# 关键：安装为 initqueue 阶段的 hook 脚本
    inst_hook initqueue 20 "$moddir/usb-keyfile.sh"

    # 安装运行时文件
    inst_simple "$moddir/usb-keyfile.conf" "/etc/usb-keyfile.conf"
    inst_simple "$moddir/luks_uuid.conf" "/etc/luks_uuid.conf"
	
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
