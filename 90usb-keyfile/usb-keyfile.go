package main

import (
    "bufio"
    "fmt"
    "os"
    "os/exec"
    "path/filepath"
    "strings"
    "sync"
    "syscall"
    "time"
)

// Config 从 /etc/usb-keyfile.conf 读取
type Config struct {
    USBUUID     string
    KeyfilePath string
    LUKSConf    string
}

// LUKSEntry 从 /etc/luks_uuid.conf 读取
type LUKSEntry struct {
    UUID string
    Name string
}

const (
    defaultConfPath = "/etc/usb-keyfile.conf"
    defaultLuksConf = "/etc/luks_uuid.conf"
    lockFile        = "/run/usb-keyfile-unlock.lock"
    okFile          = "/run/usb-keyfile-unlock.lock-ok"
    mountPoint      = "/run/usb"
    maxRetries      = 30
    retryInterval   = 1 * time.Second
)

var (
    config     Config
    luksList   []LUKSEntry
    unlockDone bool
    mu         sync.Mutex
)

// dracut 日志输出：直接写 stdout（在 initramfs 中 stdout 被重定向到控制台）
func info(msg string) {
    fmt.Printf("usb-keyfile: INFO: %s\n", msg)
}

func warn(msg string) {
    fmt.Printf("usb-keyfile: WARN: %s\n", msg)
}

func loadConfig(path string) error {
    f, err := os.Open(path)
    if err != nil {
        return fmt.Errorf("cannot open config %s: %w", path, err)
    }
    defer f.Close()

    scanner := bufio.NewScanner(f)
    for scanner.Scan() {
        line := strings.TrimSpace(scanner.Text())
        if line == "" || strings.HasPrefix(line, "#") {
            continue
        }
        parts := strings.SplitN(line, "=", 2)
        if len(parts) != 2 {
            continue
        }
        key := strings.TrimSpace(parts[0])
        val := strings.TrimSpace(parts[1])
        // 去掉可能的引号
        val = strings.Trim(val, `"'`)
        switch key {
        case "USB_UUID":
            config.USBUUID = val
        case "KEYFILE_PATH":
            config.KeyfilePath = val
        case "LUKS_CONF":
            config.LUKSConf = val
        }
    }
    return scanner.Err()
}

func loadLUKSConf(path string) ([]LUKSEntry, error) {
    f, err := os.Open(path)
    if err != nil {
        return nil, fmt.Errorf("cannot open LUKS conf %s: %w", path, err)
    }
    defer f.Close()

    var entries []LUKSEntry
    scanner := bufio.NewScanner(f)
    for scanner.Scan() {
        line := strings.TrimSpace(scanner.Text())
        if line == "" || strings.HasPrefix(line, "#") {
            continue
        }
        fields := strings.Fields(line)
        if len(fields) < 2 {
            continue
        }
        entries = append(entries, LUKSEntry{UUID: fields[0], Name: fields[1]})
    }
    return entries, scanner.Err()
}

// waitForDevice 轮询等待 USB 设备出现
func waitForDevice(uuid string) error {
    for i := 0; i < maxRetries; i++ {
        cmd := exec.Command("blkid", "-t", "UUID="+uuid, "-o", "device")
        out, err := cmd.Output()
        if err == nil && len(out) > 0 {
            return nil
        }
        time.Sleep(retryInterval)
    }
    return fmt.Errorf("USB device with UUID %s not found after %d retries", uuid, maxRetries)
}

// mountUSB 挂载 USB 设备为只读
func mountUSB(uuid string) error {
    if err := os.MkdirAll(mountPoint, 0755); err != nil {
        return err
    }
    cmd := exec.Command("mount", "-vt", "auto", "-o", "ro", "-U", uuid, mountPoint)
    return cmd.Run()
}

// umountUSB 卸载并清理
func umountUSB() {
    exec.Command("umount", mountPoint).Run()
    os.Remove(mountPoint)
}

// readKeyfile 从 USB 挂载点读取密钥文件内容
func readKeyfile(relPath string) ([]byte, error) {
    absPath := filepath.Join(mountPoint, relPath)
    return os.ReadFile(absPath)
}

// resolveLuksDevice 通过 UUID 找到对应的块设备路径
func resolveLuksDevice(uuid string) (string, error) {
    cmd := exec.Command("blkid", "-t", "UUID="+uuid, "-o", "device")
    out, err := cmd.Output()
    if err != nil {
        return "", fmt.Errorf("cannot resolve UUID %s to device: %w", uuid, err)
    }
    dev := strings.TrimSpace(string(out))
    if dev == "" {
        return "", fmt.Errorf("no device found for UUID %s", uuid)
    }
    return dev, nil
}

// luksUnlock 使用密钥字节解锁一个 LUKS 分区（通过 stdin 传递密钥）
func luksUnlock(entry LUKSEntry, key []byte) error {
    dev, err := resolveLuksDevice(entry.UUID)
    if err != nil {
        return fmt.Errorf("cannot find LUKS device: %w", err)
    }

    cmd := exec.Command("systemd-cryptsetup", "attach", entry.Name,
        "--key-file=-",
        dev)
    stdin, err := cmd.StdinPipe()
    if err != nil {
        return err
    }
    go func() {
        defer stdin.Close()
        stdin.Write(key)
    }()
    out, err := cmd.CombinedOutput()
    if err != nil {
        return fmt.Errorf("cryptsetup attach failed: %s: %s", err, string(out))
    }
    info(fmt.Sprintf("LUKS %s (%s) unlocked successfully", entry.Name, dev))
    return nil
}

// unlockAllUsingKey 用给定的密钥解锁所有 LUKS 分区（带文件锁）
func unlockAllUsingKey(key []byte) error {
    mu.Lock()
    defer mu.Unlock()
    if unlockDone {
        return nil
    }

    // 文件锁
    flock, err := os.Create(lockFile)
    if err != nil {
        return fmt.Errorf("cannot create lock file: %w", err)
    }
    defer flock.Close()
    if err := syscall.Flock(int(flock.Fd()), syscall.LOCK_EX); err != nil {
        return fmt.Errorf("cannot acquire lock: %w", err)
    }
    defer syscall.Flock(int(flock.Fd()), syscall.LOCK_UN)

    // 检查是否已经解锁
    if _, err := os.Stat(okFile); err == nil {
        info("Already unlocked, skip")
        return nil
    }

    for _, entry := range luksList {
        if err := luksUnlock(entry, key); err != nil {
            warn(fmt.Sprintf("Failed to unlock %s: %s", entry.Name, err))
        }
    }

    // 标记已解锁
    if err := os.WriteFile(okFile, []byte("ok"), 0644); err != nil {
        warn("cannot write ok file: " + err.Error())
    }
    unlockDone = true
    return nil
}

// usbKey 一次 USB 检测解锁尝试，返回是否成功解锁了至少一个分区
func usbKey() bool {
    info("Checking USB device...")
    if err := waitForDevice(config.USBUUID); err != nil {
        warn(err.Error())
        return false
    }
    info("USB device found.")

    if err := mountUSB(config.USBUUID); err != nil {
        warn("Failed to mount USB: " + err.Error())
        return false
    }
    defer umountUSB()

    key, err := readKeyfile(config.KeyfilePath)
    if err != nil {
        warn("Keyfile not found: " + err.Error())
        return false
    }
    info("Keyfile read successfully.")

    if err := unlockAllUsingKey(key); err != nil {
        warn("Unlock attempt failed: " + err.Error())
        return false
    }
    return true
}

// usbLoop 循环尝试 USB 解锁
func usbLoop(done chan struct{}) {
    for i := 0; i < maxRetries; i++ {
        select {
        case <-done:
            return
        default:
        }
        mu.Lock()
        already := unlockDone
        mu.Unlock()
        if already {
            return
        }
        if usbKey() {
            info("USB key unlock succeeded.")
            return
        }
        time.Sleep(retryInterval)
    }
    warn("USB key unlock failed after all retries.")
}

// interactiveInput 从控制台读取密码并解锁（fallback）
func interactiveInput(done chan struct{}) {
    info("Please enter the LUKS password (fallback):")
    console, err := os.OpenFile("/dev/console", os.O_RDONLY, 0)
    if err != nil {
        warn("Cannot open /dev/console: " + err.Error())
        return
    }
    defer console.Close()

    reader := bufio.NewReader(console)
    for i := 0; i < maxRetries; i++ {
        select {
        case <-done:
            return
        default:
        }
        mu.Lock()
        already := unlockDone
        mu.Unlock()
        if already {
            return
        }
        fmt.Fprint(os.Stderr, "Password: ")
        line, err := reader.ReadString('\n')
        if err != nil {
            warn("Read password error: " + err.Error())
            continue
        }
        pw := strings.TrimRight(line, "\n\r")
        if pw == "" {
            continue
        }
        if err := unlockAllUsingKey([]byte(pw)); err != nil {
            warn("Password incorrect, try again.")
        } else {
            info("Password unlock succeeded.")
            return
        }
    }
    warn("Password unlock failed after retries.")
}

func main() {
    // 加载配置
    if err := loadConfig(defaultConfPath); err != nil {
        warn("Config load failed: " + err.Error())
        os.Exit(1)
    }
    if config.USBUUID == "" || config.KeyfilePath == "" {
        warn("USB_UUID and KEYFILE_PATH must be set in config")
        os.Exit(1)
    }
    if config.LUKSConf == "" {
        config.LUKSConf = defaultLuksConf
    }

    var err error
    luksList, err = loadLUKSConf(config.LUKSConf)
    if err != nil {
        warn("LUKS config load failed: " + err.Error())
        os.Exit(1)
    }
    if len(luksList) == 0 {
        warn("No LUKS entries in " + config.LUKSConf)
        os.Exit(1)
    }

    // 创建 done channel，任意一个成功解锁后关闭以通知其他 goroutine 退出
    done := make(chan struct{})

    // 启动 USB 检测 goroutine
    go usbLoop(done)

    // 启动交互式密码输入作为 fallback
    go interactiveInput(done)

    // 启动监控 goroutine：如果解锁完成则关闭 done 并退出
    go func() {
        ticker := time.NewTicker(1 * time.Second)
        defer ticker.Stop()
        for range ticker.C {
            mu.Lock()
            if unlockDone {
                mu.Unlock()
                close(done)
                // 给其他 goroutine 一点时间清理，然后退出
                time.Sleep(500 * time.Millisecond)
                os.Exit(0)
            }
            mu.Unlock()
        }
    }()

    // 保持主 goroutine 运行
    select {}
}