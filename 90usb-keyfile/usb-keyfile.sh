#!/bin/sh
# --> /usr/lib/dracut/modules.d/90usb-keyfile/usb-keyfile.sh

# ==============================
# 配置区（请按需修改！）
# ==============================
USB_UUID="1234-5678"          # ← 替换为你的 U 盘分区 UUID
KEYFILE_PATH="/keyfile.bin"   # ← U 盘上的 keyfile 路径
NAME_LUKS="root"
TARGET_LUKS="xxxxxxxxxx"
# ==============================


RUN_USB="/run/usb"

if [ -z $TARGET_LUKS ];then
	info "not found LUKS DEV."
	exit 0
else
	info "LUKS UUID=$TARGET_LUKS"
fi

info "Checking for USB keyfile (UUID=$USB_UUID)..."

info "manual trigger ontime udevadm trigger ..."
udevadm trigger
info "等待 USB 设备初始化（dracut 默认会等待，但保险起见）"
udevadm wait -t 50 "/dev/disk/by-uuid/$TARGET_LUKS"

# 使用 blkid 查找设备
USB_DEV=$(blkid -t "UUID=$USB_UUID" -o device 2>/dev/null)

if [ -n "$USB_DEV" ]; then
    info "USB device found: $USB_DEV UUID=$USB_UUID"

    mkdir -p $RUN_USB

    if mount -vt auto -U "$USB_UUID" $RUN_USB; then
        info "USB mounted successfully"

        KEYFILE="${RUN_USB}$KEYFILE_PATH"
        if [ -r "$KEYFILE" ]; then
            info "Keyfile found, attempting unlock..."

            # dracut 的 crypt 模块会从标准输入读取密码
            # 所以我们直接输出 keyfile 内容即可
			systemd-cryptsetup attach "$NAME_LUKS" "/dev/disk/by-uuid/$TARGET_LUKS" "${RUN_USB}${KEYFILE_PATH}"
            info "LUKS Root unlock done."
            umount $RUN_USB
            rmdir $RUN_USB
            exit 0
        else
            warn "Keyfile not found: $KEYFILE"
        fi
        umount $RUN_USB
    else
        warn "Failed to mount USB device"
    fi
    rmdir $RUN_USB 2>/dev/null
else
    info "USB device with UUID=$USB_UUID not found"

fi

# === 回退到交互式输入 ===
info "Falling back to manual password entry..."
# 不输出任何内容，dracut 会自动进入密码提示
exit 1
