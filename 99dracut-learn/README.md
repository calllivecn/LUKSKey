# 学习dract


- 查看和解包一个dracut创建的initramfs镜像

    - lsinitrd 命令

    - lsinitrd <initrd.img> # 查看

    - lsinitrd --unpack <initrd.img> # 只能解包到当前目录, 注意进入一个空目录解压



## ⏳ $\text{dracut}$ 的超时与重试机制

- 这个机制主要由 $\text{dracut}$ 的 initqueue 机制和内核命令行参数共同控制：    

    1. initqueue (重试机制)：$\text{dracut}$ 的 /init 脚本有一个主循环，它会反复执行那些需要等待的异步脚本（例如网络配置）。只要脚本返回代码表明它还在等待（即它需要重试），$\text{dracut}$ 就会将它保留在队列中。这实现了重试。
    
    2. rd.timeout (超时时间)：启动过程的等待时间主要由内核命令行参数 $\text{rd.timeout}$ 控制（默认通常是 $\text{90}$ 秒）。一旦 $\text{initqueue}$ 中的所有脚本加起来的运行时间超过这个限制，$\text{dracut}$ 就会强制退出等待循环。