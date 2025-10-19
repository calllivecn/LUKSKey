#!/usr/bin/bash

install -m400 usb-keyfile.conf "/etc/usb-keyfile.conf"
install -m400 luks_uuid.conf "/etc/luks_uuid.conf"
install -m500 usb-keyfile-hook "/etc/initramfs-tools/hooks/usb-keyfile"
install -m500 usb-keyfile-unlock "/etc/initramfs-tools/scripts/local-top/usb-keyfile-unlock"
