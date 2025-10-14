# 📁 dracut 模块结构

- dracut 模块通常放在, 安装到这里：

```
/usr/lib/dracut/modules.d/90usb-keyfile/
```

- 文件:

```
/usr/lib/dracut/modules.d/90usb-keyfile/
├── module-setup.sh    # 声明依赖、安装文件
└── usb-keyfile.sh     # 运行时脚本（在 initramfs 中执行）
```
