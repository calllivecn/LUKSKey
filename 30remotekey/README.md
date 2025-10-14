# 还未完成，只在保留一下。

# dracut 模块放置与安装（简述）

- 模块目录（示例）：

```
/usr/lib/dracut/modules.d/90remotekey/
  module-setup.sh
  30remotekey.sh
  lan-multicast-key      # 你的可执行文件（或用 inst_simple 指定路径）
```

	module-setup.sh 会把 lan-multicast-key 和 hook 脚本打进 initramfs，并声明依赖（比如 crypt、network）。

- module-setup.sh（示例）

```
说明：

我用 pre-mount，这样会在挂载 root 之前尝试解锁。你也可以用 pre-pivot（在 pivot_root 前）。根据实际流程选一个，但必须保证在 cryptsetup 被调用之前运行。

inst_simple / inst_hook 是 dracut 的 helper。
```

- 30remotekey.sh（主 hook 脚本 — 完整、可用）

```
放到模块里并用 inst_hook 或 inst_script 安装。脚本里有充分注释，按你环境修改变量名和超时。

脚本说明（关键点）

lan-multicast-key 被启动并把接收到的 key 写进 $TMPFILE。脚本并不要求该二进制做锁；监视/抢占逻辑在脚本层做统一控制（更稳）。

mkdir $LOCKDIR 用作原子“claim”。只有成功的那方把 key 写到 $FINALKEY。

控制台 I/O 使用 /dev/console，并用 stty -echo 隐藏回显。若 initramfs 缺 stty，脚本会退化（你可以在 module-setup.sh 中 inst_multiple 把 stty 对应的 busybox 或 coreutils 放进去）。

使用 cryptsetup --key-file="$FINALKEY" 打开。成功后立即 shred -u（如可用）或 rm -f 清除 key。

全局超时 GLOBAL_TIMEOUT 控制整个等待时间。PROMPT_TIMEOUT 控制单次 prompt 的超时长度（脚本把剩余时间与单次 prompt 时间比较）。

trap 会在脚本退出时尝试清理监听进程与临时文件。
```



