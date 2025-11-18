

check(){

    # 模块总是启用
    return 0

}



# 模块处理顺序与 Hook 执行顺序之间的关系确实容易让人感到困惑。我们来回顾一下这个机制，确保你的概念基础是稳固的。
depends(){
    :
}


install(){
    # 动态安装 hook 脚本
    inst_hook pre-mount 99 "$moddir/hello-dracut.sh"
}

