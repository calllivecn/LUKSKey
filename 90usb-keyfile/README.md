# 📁 dracut 模块结构

- 文件列表:

```
/usr/lib/dracut/modules.d/90usb-keyfile/
├── module-setup.sh    # 声明依赖、安装文件
├── usb-keyfile.sh     # 运行时脚本（在 initramfs 中执行）
└── usb-keyfile.conf   # 脚本配置（自动安装到 initramfs 中的）
```


## 安装与使用

- dracut 模块通常放在, 安装到这里：

```
/usr/lib/dracut/modules.d/90usb-keyfile/
```

- 修改dracut 配置

```
# vim /etc/dracut.conf.d/your-usbkeyfile.conf
add_dracutmodules+=" usb-keyfile " # 注意这里前后都要有空格
omit_dracutmodules+=" crypt systemd-cryptsetup " # 创建initramfs 时，排队系统自带的模块。
```
