#!/usr/bin/bash

DRACUT_MOD_DIR="/usr/lib/dracut/modules.d"

USB_KEYFILE_DIR="${DRACUT_MOD_DIR}/90usb-keyfile/"
USB_KEYFILE_CONF="usb-keyfile.toml"


if [ ! -f /etc/usb-keyfile.toml ];then
	install -m400 "${USB_KEYFILE_CONF}" "/etc/${USB_KEYFILE_CONF}"
fi


if [ -d "${USB_KEYFILE_DIR}" ];then
	rm -r "${USB_KEYFILE_DIR}"
	mkdir "${USB_KEYFILE_DIR}"
else
	mkdir "${USB_KEYFILE_DIR}"
fi

install -m755 module-setup.sh "${USB_KEYFILE_DIR}"

install -m755 dist/usb-keyfile "${USB_KEYFILE_DIR}"


