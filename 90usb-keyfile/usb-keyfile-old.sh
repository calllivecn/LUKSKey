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

if [ -r "$moddir/conf" ];then
	info "not configure, exit"
	return 1
else
	. "$moddir/conf"
fi

RUN_USB="/run/usb"

if [ -z $TARGET_LUKS ];then
	info "not found LUKS DEV."
	return 1
else
	info "LUKS UUID=$TARGET_LUKS"
fi

# 函数：安全地读取密码（支持 Plymouth + 文本回退）
ask_for_password() {
    local prompt="$1"
    local password

    if [ -x /bin/plymouth ] && plymouth --ping; then
        # Plymouth 可用：使用图形密码输入
        password=$(/bin/plymouth ask-for-password --prompt="$prompt")
        # Plymouth 会自动隐藏输入，无需额外处理
    else
        # 回退到文本终端
        printf "%s" "$prompt" > /dev/console
        read -s -r password < /dev/console
    fi

    echo "$password"
}

info "Checking for USB keyfile (UUID=$USB_UUID)..."
LUKS_DEV=$(blkid -t "UUID=$TARGET_LUKS" -o device 2>/dev/null)
if [ -z "$LUKS_DEV" ];then
	warn "not found LUKS UUID: $TARGET_LUKS"
	return 1
fi

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
			systemd-cryptsetup attach "$NAME_LUKS" "/dev/disk/by-uuid/$TARGET_LUKS" "${RUN_USB}${KEYFILE_PATH}"
            info "LUKS Root unlock done."
            umount $RUN_USB
            rmdir $RUN_USB
        else
            warn "Keyfile not found: $KEYFILE"
			return 1
        fi
        umount $RUN_USB
    else
        warn "Failed to mount USB device"
    fi
    rmdir $RUN_USB

else
    info "USB device with UUID=$USB_UUID not found"
	systemd-ask-password -n "Please input passpharse for $NAME_LUKS: " > /run/pw </dev/console
	systemd-cryptsetup attach "$NAME_LUKS" "/dev/disk/by-uuid/$TARGET_LUKS" /run/pw
fi

# === 回退到交互式输入 ===
# 不输出任何内容，dracut 会自动进入密码提示
