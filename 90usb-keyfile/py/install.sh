#!/usr/bin/bash

DRACUT_MOD_DIR="/usr/lib/dracut/modules.d"

USB_KEYFILE_DIR="${DRACUT_MOD_DIR}/90usb-keyfile/"


if [ ! -f /etc/usb-keyfile.toml ];then
	install -m400 usb-keyfile.toml "/etc/usb-keyfile.toml"
fi


if [ ! -d "${DRACUT_MOD_DIR}" ];then
    mkdir -v "${DRACUT_MOD_DIR}"
fi

if [ -d "${USB_KEYFILE_DIR}" ];then
	rm -r "${USB_KEYFILE_DIR}"
fi


cp -av . "${USB_KEYFILE_DIR}"



