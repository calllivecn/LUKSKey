#!/bin/bash
# module-setup.sh for dracut 90remotekey

check() {
    # 要求 cryptsetup 和 ip 命令存在（network 功能）
    require_binaries cryptsetup || return 1
    require_binaries ip || return 1
    # 要求你的二进制存在
    [ -x "${moddir}/lan-multicast-key" ] || return 1
    return 0
}

depends() {
    # 需要 dracut 的 crypt 和 network 支持
    echo "crypt"
    echo "network"
    # 如需 LVM，追加 lvm
    # echo "lvm"
}

install() {
    # 把你的二进制放进 initramfs；如果它在 /usr/sbin/，改路径
    inst_simple "${moddir}/lan-multicast-key" "/usr/sbin/lan-multicast-key"

    # 安装 hook：在 pre-mount 或 pre-pivot 执行（要在切换真实根之前解锁）
    inst_hook pre-mount 05 "${moddir}/30remotekey.sh"

    # 安装脚本到 initramfs（inst_simple 会拷贝并设置可执行）
    inst_script "${moddir}/30remotekey.sh" "/usr/lib/dracut/hooks/initqueue/30remotekey.sh"
}

# end of file

