#!/usr/bin/bash

install -m400 usb-keyfile.conf "/etc/usb-keyfile.conf"
install -m400 luks_uuid.conf "/etc/luks_uuid.conf"

#mkdir -v /usr/lib/dracut/modules.d/90usb-keyfile/
#install -m600 README.md /usr/lib/dracut/modules.d/90usb-keyfile/README.md
#install -m600 module-setup.sh /usr/lib/dracut/modules.d/90usb-keyfile/module-setup.sh
#install -m600  usb-keyfile.sh /usr/lib/dracut/modules.d/90usb-keyfile/usb-keyfile.sh

