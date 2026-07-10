这是一个非常好的问题。要理解 dracut 的启动阶段，首先需要明确一个关键点：**现代 dracut 有两套并行的阶段体系**——一套是传统的 **dracut hook 阶段**（基于 shell 脚本），另一套是 **systemd target 阶段**（当 initramfs 使用 systemd 作为 PID 1 时）。两者同时存在，但作用机制不同。

---

# 一、Systemd Target 阶段（initrd 专用）

当 dracut 使用 `systemd` 模块（现代发行版默认），PID 1 是 systemd，整个 initrd 阶段由以下 target 和关键 service 串联：

## 完整启动顺序图

```
内核加载 initramfs，执行 /sbin/init (即 systemd)
         │
         ▼
┌─────────────────────────────────────────────────────────┐
│  ① sysinit.target                                       │
│     ├─ systemd-udevd.service        (启动 udev 守护进程) │
│     ├─ systemd-journald.service     (启动日志服务)        │
│     ├─ systemd-vconsole-setup.service(配置虚拟控制台)     │
│     ├─ dracut-cmdline.service       (解析内核命令行参数)   │
│     ├─ dracut-pre-udev.service      (udev 启动前的准备)   │
│     ├─ dracut-pre-trigger.service   (udev trigger 前)    │
│     ├─ systemd-udev-trigger.service (触发 udev 设备事件)  │
│     ├─ dracut-initqueue.service     (★ 设备发现主循环)    │
│     ├─ swap.target                  (交换设备)            │
│     └─ ...各种底层初始化服务                              │
└─────────────────────────────────────────────────────────┘
         │
         ▼
┌─────────────────────────────────────────────────────────┐
│  ② basic.target                                         │
│     ├─ sockets.target               (各种 socket 单元)   │
│     ├─ timers.target                (定时器单元)         │
│     ├─ paths.target                 (路径监控单元)       │
│     └─ 提供日志、dbus 等基础通信能力                      │
└─────────────────────────────────────────────────────────┘
         │
         ▼
┌─────────────────────────────────────────────────────────┐
│  ③ initrd-root-device.target          ★ 根设备就绪       │
│     含义：根设备已被识别并可用                             │
│     例如：LUKS 已解密、RAID 已组装、LVM 已激活、           │
│           网络设备已获取到 iSCSI/NFS 目标                  │
│     关键服务：systemd-cryptsetup@.service                 │
│              lvm2-activation.service                      │
│              mdadm 相关 service                           │
└─────────────────────────────────────────────────────────┘
         │
         ▼
┌─────────────────────────────────────────────────────────┐
│  ④ initrd-root-fs.target              ★ 根文件系统挂载    │
│     含义：根文件系统已挂载到 /sysroot                      │
│     关键服务：sysroot.mount (挂载根分区到 /sysroot)        │
│     此时 /sysroot 下是真实的根文件系统（只读挂载）          │
└─────────────────────────────────────────────────────────┘
         │
         ▼
┌─────────────────────────────────────────────────────────┐
│  ⑤ initrd-parse-etc.service           (关键 service)     │
│     含义：解析 /sysroot/etc/fstab                        │
│     作用：读取真实根文件系统中的 fstab，                   │
│           为需要额外挂载的分区（如 /usr）生成 mount 单元    │
└─────────────────────────────────────────────────────────┘
         │
         ▼
┌─────────────────────────────────────────────────────────┐
│  ⑥ initrd-fs.target                   ★ 额外文件系统挂载 │
│     含义：/sysroot/etc/fstab 中标记了                    │
│           x-initrd.mount 的文件系统已挂载                 │
│     典型场景：/usr 在单独分区上，必须在 switch-root 前挂载  │
└─────────────────────────────────────────────────────────┘
         │
         ▼
┌─────────────────────────────────────────────────────────┐
│  ⑦ initrd.target                      ★ initrd 最终目标  │
│     含义：initrd 阶段的所有工作已完成                      │
│     这是 initrd 阶段的 "终点站"                           │
│     所有需要在 switch-root 前完成的工作                    │
│     都必须在此 target 之前完成                             │
└─────────────────────────────────────────────────────────┘
         │
         ▼
┌─────────────────────────────────────────────────────────┐
│  ⑧ initrd-cleanup.service             (关键 service)     │
│     含义：切换根之前的清理工作                             │
│     作用：停止不再需要的 initrd 服务、                     │
│           卸载不需要的挂载点、准备 pivot_root/switch_root  │
└─────────────────────────────────────────────────────────┘
         │
         ▼
┌─────────────────────────────────────────────────────────┐
│  ⑨ initrd-switch-root.service         (关键 service)     │
│     含义：执行 switch_root (pivot_root)                   │
│     作用：将 /sysroot 切换为新的 /，                      │
│           并执行真实根文件系统中的 /sbin/init               │
│     ★ 从此刻起，离开 initramfs，进入真实系统               │
└─────────────────────────────────────────────────────────┘
         │
         ▼
   真实系统的 systemd 启动（multi-user.target / graphical.target）
```

## 汇总表

| 序号 | Target / Service | 类型 | 核心含义 | 你的模块应该挂载在这里吗？ |
|:---:|---|:---:|---|---|
| ① | `sysinit.target` | Target | 系统底层初始化完成（udev、日志、早期 hook） | ✅ 适合大多数早期初始化 service |
| ② | `basic.target` | Target | 基础能力就绪（socket、timer、path） | 很少直接使用 |
| ③ | `initrd-root-device.target` | **Target** | **根设备就绪**（解密/RAID/LVM 完成） | ✅ 需要在根设备可用后、挂载前做的事 |
| ④ | `initrd-root-fs.target` | **Target** | **根文件系统已挂载到 /sysroot** | ✅ 需要访问根文件系统内容的操作 |
| ⑤ | `initrd-parse-etc.service` | Service | 解析 /sysroot/etc/fstab | 一般不干预 |
| ⑥ | `initrd-fs.target` | **Target** | **额外文件系统（如 /usr）已挂载** | ✅ 需要访问 /usr 等额外分区的操作 |
| ⑦ | `initrd.target` | **Target** | **initrd 阶段最终目标** | ✅ 需要在 switch-root 前完成的收尾工作 |
| ⑧ | `initrd-cleanup.service` | Service | 清理 initrd 环境 | 一般不干预 |
| ⑨ | `initrd-switch-root.service` | Service | 执行 switch_root | 一般不干预 |

---

# 二、传统 Dracut Hook 阶段（非 systemd 或与 systemd 并行）

即使在使用 systemd 的模式下，dracut 仍然保留了一套 **hook 阶段**（通过 `inst_hook` 安装）。这些 hook 在 systemd 的 service 中被调用执行。完整顺序如下：

```
┌──────────────────────────────────────────────────────────────────┐
│  阶段 1: cmdline                                                 │
│  时机：内核命令行参数解析时                                       │
│  用途：解析自定义内核参数（如 rd.my_module.option=xxx）           │
│  对应 service: dracut-cmdline.service                            │
├──────────────────────────────────────────────────────────────────┤
│  阶段 2: pre-udev                                                │
│  时机：udev 守护进程启动之前                                     │
│  用途：加载内核模块、早期设备配置                                 │
│  对应 service: dracut-pre-udev.service                           │
├──────────────────────────────────────────────────────────────────┤
│  阶段 3: pre-trigger                                             │
│  时机：udev 设备事件触发（udevadm trigger）之前                   │
│  用途：在 udev 开始枚举设备前做准备工作                           │
│  对应 service: dracut-pre-trigger.service                        │
├──────────────────────────────────────────────────────────────────┤
│  阶段 4: initqueue                    ★★★ 最复杂、最重要的阶段    │
│  时机：udev 触发后，等待根设备就绪的循环中                        │
│  本质：一个反复执行的事件循环（见上一轮讨论）                     │
│  子阶段：                                                        │
│    ├─ initqueue/           每次循环迭代都执行                     │
│    ├─ initqueue/settled/   udev 事件队列清空后执行                │
│    ├─ initqueue/finished/  循环即将结束时执行                     │
│    └─ initqueue/timeout/   超时时执行                             │
│  对应 service: dracut-initqueue.service                          │
├──────────────────────────────────────────────────────────────────┤
│  阶段 5: pre-mount                                               │
│  时机：根设备已找到，挂载根文件系统之前                            │
│  用途：在挂载前做最后检查或修改（如 fsck、修改挂载选项）           │
│  对应 service: dracut-pre-mount.service                          │
├──────────────────────────────────────────────────────────────────┤
│  阶段 6: mount                                                   │
│  时机：挂载根文件系统时                                           │
│  用途：自定义挂载逻辑（极少使用）                                 │
│  对应 service: dracut-mount.service                              │
├──────────────────────────────────────────────────────────────────┤
│  阶段 7: pre-pivot                                               │
│  时机：switch_root (pivot_root) 之前                              │
│  用途：最后的清理、将状态信息传递到真实根文件系统                  │
│  对应 service: dracut-pre-pivot.service                          │
├──────────────────────────────────────────────────────────────────┤
│  阶段 8: cleanup                                                 │
│  时机：switch_root 前的最终清理                                   │
│  用途：删除临时文件、停止不需要的进程                              │
│  对应 service: dracut-initrd-cleanup.service                     │
└──────────────────────────────────────────────────────────────────┘
```

---

# 三、两套体系的对应关系

这是最关键的部分——理解 hook 阶段和 systemd target 如何交织：

```
时间线 →→→→→→→→→→→→→→→→→→→→→→→→→→→→→→→→→→→→→→→→→→→→→→→→→→→→→→→

Systemd Target:
  sysinit.target          basic.target    initrd-root-device.target
       │                       │                  │
       ▼                       ▼                  ▼
  ┌─────────┐            ┌─────────┐        ┌──────────┐
  │cmdline   │            │         │        │          │
  │pre-udev  │            │         │        │          │
  │pre-trigger│           │         │        │          │
  │initqueue │            │         │        │          │
  └─────────┘            └─────────┘        └──────────┘
       │                                          │
       ▼                                          ▼
  initrd-root-fs.target ──→ initrd-parse-etc ──→ initrd-fs.target
       │                                              │
       ▼                                              ▼
  ┌──────────┐                                  ┌──────────┐
  │pre-mount │                                  │          │
  │mount     │                                  │          │
  └──────────┘                                  └──────────┘
                                                      │
                                                      ▼
                                               initrd.target
                                                      │
                                                      ▼
                                              ┌──────────────┐
                                              │ pre-pivot    │
                                              │ cleanup      │
                                              └──────────────┘
                                                      │
                                                      ▼
                                           initrd-switch-root
                                                      │
                                                      ▼
                                              真实系统启动
```

---

# 四、你的自定义 service 应该放在哪里？

## 决策流程图

```
你的模块需要做什么？
         │
         ├── 需要在根设备发现前执行？（如加载驱动、配置网络）
         │     → Before=initrd-root-device.target
         │     → 或使用 cmdline / pre-udev / pre-trigger hook
         │
         ├── 需要在根设备就绪后、挂载前执行？（如自定义解密、检查）
         │     → After=initrd-root-device.target
         │     → Before=initrd-root-fs.target
         │
         ├── 需要读取根文件系统上的文件？（如读取 /etc 下的配置）
         │     → After=initrd-root-fs.target
         │     → Before=initrd.target
         │
         ├── 需要在 switch-root 前做收尾工作？
         │     → After=initrd-fs.target
         │     → Before=initrd.target
         │     → 或使用 pre-pivot hook
         │
         └── 需要与用户交互（输入密码等）？
               → 创建独立 service
               → Before=initrd-root-device.target（如果是解密密码）
               → StandardInput=tty-force
               → 使用 systemd-ask-password
```

## 常用 .service 模板

### 模板 1：在设备发现阶段运行（替代 initqueue hook）

```ini
[Unit]
Description=My Device Setup
DefaultDependencies=no
Before=initrd-root-device.target
After=sysinit.target systemd-udevd.service
ConditionKernelCommandLine=rd.my_module

[Service]
Type=oneshot
RemainAfterExit=yes
ExecStart=/usr/bin/my-device-setup.sh

[Install]
WantedBy=sysinit.target
```

### 模板 2：在根文件系统挂载后运行

```ini
[Unit]
Description=My Post Mount Setup
DefaultDependencies=no
After=initrd-root-fs.target
Before=initrd.target

[Service]
Type=oneshot
RemainAfterExit=yes
ExecStart=/usr/bin/my-post-mount.sh

[Install]
WantedBy=initrd.target
```

### 模板 3：密码交互（你最开始的需求）

```ini
[Unit]
Description=Ask Password for Custom Encryption
DefaultDependencies=no
Before=initrd-root-device.target
After=systemd-vconsole-setup.service systemd-udevd.service
# 确保不与 LUKS 密码提示冲突
After=systemd-cryptsetup@.service

[Service]
Type=oneshot
RemainAfterExit=yes
ExecStart=/usr/bin/my-ask-password.sh
StandardInput=tty-force
StandardOutput=tty
StandardError=tty
TTYPath=/dev/console
TimeoutSec=120

[Install]
WantedBy=sysinit.target
```

---

# 五、如何在运行时查看当前处于哪个阶段

当你在 initramfs 的紧急 shell 中调试时，可以用以下命令查看当前 target 状态：

```bash
# 查看当前活跃的 target
systemctl list-units --type=target

# 查看 initrd 相关 target 的依赖树
systemctl list-dependencies initrd.target

# 查看所有 initrd 相关的 unit
systemctl list-units --type=service --all | grep -E "dracut|initrd"

# 查看某个 target 是否已达到
systemctl is-active initrd-root-fs.target

# 查看完整的启动顺序（带时间）
systemd-analyze    # 如果可用
```

---

# 六、总结：完整 Target 清单

| 类别 | Target / Service | 说明 |
|------|-----------------|------|
| **通用基础** | `sysinit.target` | 系统初始化（initrd 和正常启动共用） |
| **通用基础** | `basic.target` | 基础能力就绪 |
| **initrd 专用** | `initrd-root-device.target` | ★ 根设备就绪 |
| **initrd 专用** | `initrd-root-fs.target` | ★ 根文件系统挂载到 /sysroot |
| **initrd 专用** | `initrd-fs.target` | ★ 额外文件系统挂载（如 /usr） |
| **initrd 专用** | `initrd.target` | ★ initrd 阶段的最终目标 |
| **关键 Service** | `initrd-parse-etc.service` | 解析 /sysroot/etc/fstab |
| **关键 Service** | `initrd-cleanup.service` | 清理 initrd 环境 |
| **关键 Service** | `initrd-switch-root.service` | 执行 switch_root |
| **dracut hook Service** | `dracut-cmdline.service` | 执行 cmdline hook |
| **dracut hook Service** | `dracut-pre-udev.service` | 执行 pre-udev hook |
| **dracut hook Service** | `dracut-pre-trigger.service` | 执行 pre-trigger hook |
| **dracut hook Service** | `dracut-initqueue.service` | 执行 initqueue hook（主循环） |
| **dracut hook Service** | `dracut-pre-mount.service` | 执行 pre-mount hook |
| **dracut hook Service** | `dracut-mount.service` | 执行 mount hook |
| **dracut hook Service** | `dracut-pre-pivot.service` | 执行 pre-pivot hook |
| **异常处理** | `emergency.target` | 紧急模式（严重错误） |
| **异常处理** | `rescue.target` | 救援模式（单用户） |

**最核心的 4 个 initrd target** 就是：
1. `initrd-root-device.target` — 设备就绪
2. `initrd-root-fs.target` — 根挂载完成
3. `initrd-fs.target` — 额外挂载完成
4. `initrd.target` — initrd 结束

记住这 4 个，你的自定义 service 的 `Before=` / `After=` 就有了明确的锚点。
