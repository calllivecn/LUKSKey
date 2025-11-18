#!/bin/bash
# --> /usr/lib/dracut/modules.d/90usb-keyfile/usb-keyfile.sh

USB_UUID=
KEYFILE_PATH=
NAME_LUKS=
LUKS_UUID=

CONF="/etc/usb-keyfile.conf"

if [ -r "$CONF" ];then
    . "$CONF"
else
    info "$CONF not configure, exit"
    return 1
fi

if [ -z "$USB_UUID" ] || [ -z "$KEYFILE_PATH" ];then
    warn "USB_UUID KEYFILE_PATH NAME_LUKS LUKS_UUID, require configure."
    return 1
fi


if [ ! -r "$LUKS_CONF" ];then
    log_warning_msg "LUKS_CONF: $LUKS_CONF not found."
    log_end_msg
    return 1
fi


TMP_UNLOCK="/run/usb-keyfile-unlock.lock"
TMP_UNLOCK_OK="/run/usb-keyfile-unlock.lock-ok"

trap "rm $TMP_UNLOCK $TMP_UNLOCK_OK" EXIT


luks_unlock(){
    {
        flock 20
        if [ -f "$TMP_UNLOCK_OK" ];then
            info "Detected already unlocked, exit current operation."
            return 0
        fi

        local keyfile="$1"
        info "Keyfile found, attempting unlock..."
        while read luksuuid luksname;
        do
            # 跳过空行和注释行
            [ -z "$luksuuid" ] && continue
            case "$luksuuid" in \#*)
                continue
                ;;
            esac

            luks_dev=$(blkid -t "UUID=$luksuuid" -o device 2>/dev/null)
            if [ -z "$luks_dev" ];then
                warn "not found LUKS UUID: $luksuuid"
                continue
            fi

            if systemd-cryptsetup attach "$luksname" "$luks_dev" "$keyfile";then
                info "LUKS $luksname unlock done."
            else
                warn "LUKS $luksname unlock failed."
            fi

        done < "$LUKS_CONF"
        
        :>"$TMP_UNLOCK_OK"

    } 20 > "$TMP_UNLOCK"
}


usb_key(){

    local recode
	local RUN_USB="/run/usb"
	udevadm wait "/dev/disk/by-uuid/$USB_UUID"
	# 使用 blkid 查找设备
	USB_DEV=$(blkid -t "UUID=$USB_UUID" -o device 2>/dev/null)

    if [ -n "$USB_DEV" ]; then
        info "USB device found: USB_KEY"

        mkdir -p $RUN_USB

        if mount -vt auto -o ro -U "$USB_UUID" $RUN_USB; then
            info "USB mounted successfully"
    
            KEYFILE="${RUN_USB}$KEYFILE_PATH"
            if [ -r "$KEYFILE" ]; then
                info "Keyfile found, attempting unlock..."
                if luks_unlock "$KEYFILE";then
                    info "LUKS unlock succeeded using keyfile."
                    recode=0
                else
                    warn "LUKS unlock failed using keyfile."
                    recode=1
                fi
                info "LUKS Root unlock done."
                recode=0
            else
                warn "Keyfile not found with USB_KEY"
                recode=1
            fi
            umount $RUN_USB
        else
            warn "Failed to mount USB device"
            recode=1
        fi
        rmdir $RUN_USB

	else
		recode=1
    fi

    return $recode
}


usb(){
    for _ in {1..30}
    do
        if usb_key;then
            break
        fi
    done
}

user_input(){
    # === 交互式密码输入 ===
    for _ in {1..30}
    do
        info "Please enter the password to decrypt LUKS:"
        read -s pw < /dev/console

        if [ -n "$pw" ];then
            printf "$pw" > /run/usb-keyfile-pw-file
            if luks_unlock "/run/usb-keyfile-pw-file";then
                rm /run/usb-keyfile-pw-file
                break
            else
                rm /run/usb-keyfile-pw-file
                warn "Password incorrect, please try again."
            fi
        fi

    done
}


manager_proc(){
    while :;
    do
        if [ -f "$TMP_UNLOCK_OK" ];then
            kill "$1" "$2" 2>/dev/null
            return 0
        fi
        sleep 1
    done
}

usb &
pid_usb=$!

manager_proc $$ $pid_usb &

# 需要交互，不能使用( .. ) 子shell，否则无法读取用户输入
user_input

