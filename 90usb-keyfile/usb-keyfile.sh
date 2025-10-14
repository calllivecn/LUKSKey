#!/bin/sh
# --> /usr/lib/dracut/modules.d/90usb-keyfile/usb-keyfile.sh

# ==============================
# 配置区（请按需修改！）
# ==============================
USB_UUID="1234-5678"          # ← 替换为你的 U 盘分区 UUID
KEYFILE_PATH="/keyfile.bin"   # ← U 盘上的 keyfile 路径
# ==============================

info "Checking for USB keyfile (UUID=$USB_UUID)..."

# 等待 USB 设备初始化（dracut 默认会等待，但保险起见）
sleep 3

# 使用 blkid 查找设备
USB_DEV=$(blkid -t "UUID=$USB_UUID" -o device 2>/dev/null | head -n1)

if [ -n "$USB_DEV" ] && [ -e "$USB_DEV" ]; then
    info "USB device found: $USB_DEV"

    mkdir -p /tmp/usb

    if mount -t auto "$USB_DEV" /tmp/usb; then
        info "USB mounted successfully"

        KEYFILE="/tmp/usb$KEYFILE_PATH"
        if [ -f "$KEYFILE" ]; then
            info "Keyfile found, attempting unlock..."

            # dracut 的 crypt 模块会从标准输入读取密码
            # 所以我们直接输出 keyfile 内容即可
            cat "$KEYFILE"
            umount /tmp/usb
            rmdir /tmp/usb
            exit 0
        else
            warn "Keyfile not found: $KEYFILE"
        fi
        umount /tmp/usb
    else
        warn "Failed to mount USB device"
    fi
    rmdir /tmp/usb 2>/dev/null
else
    warn "USB device with UUID=$USB_UUID not found"
fi

# === 回退到交互式输入 ===
info "Falling back to manual password entry..."
# 不输出任何内容，dracut 会自动进入密码提示
exit 1
