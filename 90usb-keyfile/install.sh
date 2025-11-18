#!/usr/bin/bash

if [ ! -f /etc/usb-keyfile.conf ];then
	install -m400 usb-keyfile.conf "/etc/usb-keyfile.conf"
fi

if [ ! -f  /etc/luks_uuid.conf ];then
	install -m400 luks_uuid.conf "/etc/luks_uuid.conf"
fi


if [ -d /usr/lib/dracut/modules.d/90usb-keyfile/ ];then
	rm -r /usr/lib/dracut/modules.d/90usb-keyfile/
fi

cp -av . /usr/lib/dracut/modules.d/90usb-keyfile/


