#!/bin/sh
# --> /usr/lib/dracut/modules.d/90usb-keyfile/usb-keyfile.sh

USB_UUID=
KEYFILE_PATH=
NAME_LUKS=
LUKS_UUID=

CONF="/etc/usb-keyfile.conf"

if [ -r "$CONF" ];then
    info "$CONF not configure, exit"
    return 1
else
    . "$CONF"
fi

if [ -z "$USB_UUID" ] || [ -z "$KEYFILE_PATH" ] || [ -z "$NAME_LUKS" ] || [ -z "$LUKS_UUID" ];then
    warn "USB_UUID KEYFILE_PATH NAME_LUKS LUKS_UUID, require configure."
    return 1
fi

RUN_USB="/run/usb"

if [ -z "$LUKS_UUID" ];then
    info "not found LUKS DEV."
    return 1
else
    info "LUKS UUID=$LUKS_UUID"
fi

info "Checking for USB keyfile (UUID=$USB_UUID)..."
LUKS_DEV=$(blkid -t "UUID=$LUKS_UUID" -o device 2>/dev/null)
if [ -z "$LUKS_DEV" ];then
    warn "not found LUKS UUID: $LUKS_UUID"
    return 1
fi

# 使用 blkid 查找设备
USB_DEV=$(blkid -t "UUID=$USB_UUID" -o device 2>/dev/null)

usb_unlock(){
    if [ -n "$USB_DEV" ]; then
        info "USB device found: $USB_DEV UUID=$USB_UUID"

        mkdir -p $RUN_USB

        if mount -vt auto -U "$USB_UUID" $RUN_USB; then
            info "USB mounted successfully"
    
            KEYFILE="${RUN_USB}$KEYFILE_PATH"
            if [ -r "$KEYFILE" ]; then
                info "Keyfile found, attempting unlock..."
                systemd-cryptsetup attach "$NAME_LUKS" "$LUKS_DEV" "${RUN_USB}${KEYFILE_PATH}"
                info "LUKS Root unlock done."
                umount $RUN_USB
                rmdir $RUN_USB
                return 0
            else
                warn "Keyfile not found: $KEYFILE"
                return 1
            fi
            umount $RUN_USB
        else
            warn "Failed to mount USB device"
            return 1
        fi
        rmdir $RUN_USB
    fi
}


enter_password(){
    info "USB device with UUID=$USB_UUID not found"
    systemd-cryptsetup attach "$NAME_LUKS" "$LUKS_DEV"
}

# === 回退到交互式输入 ===
if usb_unlock;then
	enter_password
fi

