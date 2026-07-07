#!/usr/bin/bash


if [ ! -f /etc/usb-keyfile.toml ];then
	install -m400 usb-keyfile.toml "/etc/usb-keyfile.toml"
fi


if [ -d /usr/lib/dracut/modules.d/90usb-keyfile/ ];then
	rm -r /usr/lib/dracut/modules.d/90usb-keyfile/
fi


cp -av . /usr/lib/dracut/modules.d/90usb-keyfile/


