# A7C 一代的网络/调试通道实况（2.00 与 2.03，`debugfs` 只读解包，E3）
产物：`work/net-tools/{A15_INVENTORY.md, a15_tree_full.tsv, a15_203_tree_full.tsv, a7_tree_full.tsv, a15_200_vs_203_diff.txt, busybox_applets_{a7,a15,a1initrd}.txt, extract/…}`

## 0. 先更正我之前的串取证误判（重要）
- **`/usr/bin/network.sh`、`WebApiLauncher.sh`、`qsi.elf` 其实不存在**——那些只是 `libIMDB.so` 里的**字符串引用**。真正的联网脚本在 **`/usr/wifi-scripts/`（12 个）**。
- **`bcmdhd-oob.ko / bcmdhd-no-oob.ko` 不存在**：a15 只有**一个** `bcmdhd.ko`（`-oob/-no-oob` 是脚本里的文本；已在 a1/a2/a3/a4/a7/a10/a13/a15×2/a23 全 grep 确认）。OOB 与否由 **`dhd_irq`** 参数决定（`dhd_enableOOB/dhd_bus_oob_intr_*`）。
- 脚本里写的 `/usr/bin/bcm4339.bin|.txt` **也不存在**：真固件在 **`/usr/wlan/bcm/`**（`bcm4339.bin` 564,167 B = `6.37.39.113 CY`，Ucode 918.2015，CLM 内建 `clm_43xx_sony_DI`，无独立 `.clm`；另有工厂版 `bcm4339_mfg.bin` 552,765 B），nvram 在 **`/usr/share/network/nvram/*/bcm4339_*.txt`（78 个）**。
- 没有 `brcmfmac/brcmutil`（`/usr/backport` 不存在）；没有 `ip` 命令（用 `ifconfig`）。

## 1. Wi-Fi 上电/bring-up 的真实顺序（照抄这个，别再猜）
`/usr/wifi-scripts/` 里：
1. `gpioctrl.elf w GPIO_S_4…1`（SDIO 供电）→ `w MMC_XRST…1`（**WL_REG_ON**）→ `iw GPIO_S_16 -n -l`
2. `echo 1 > /proc/irq/144/smp_affinity`；SDIO1 引脚复用
3. `insmod compat; cfg80211; mmc_core; mmcioWrapper; bcmdhd firmware_path=… nvram_path=… iface_name=wlan dhd_irq=144`（vermagic 3.0.27）
4. `mount -t tmpfs tmpfs /tmp_network`
5. `wpa_supplicant -Dnl80211 -i wlan0 -c /usr/lib/netconf/bss.conf -N -i p2p0 -c p2p.conf`（**`bss.conf` 里 `ap_scan=0`** ⇒ 相机走 WPS/enrollee 流程，不是我们熟悉的扫描-连接）
6. 拿地址：`wifi-test.sh` 用 `ifconfig wlan0 …`；另有 `pump`、`busybox udhcpc`；控制走 `wpa_cli -p /tmp_network/run/wpa_supplicant`
（2.00 与 2.03 的 `wifi-scripts`/netconf/nvram **同名同套**。）

## 2. busybox（权威，不是串取证）
- **a15 里没有 busybox**（`/bin/mkfifo → ../../bin/busybox`，借 a7 那颗）。
- a7 `/bin/busybox` = **v1.29.3（2021-02-04 构建）**；a1-initrd 另有一颗 v1.29.3（2018-12-07）；applet 表相同（**191 个**，静态提取，未在 guest 里 `--list` 复核）。
- 关键有无：**`nc` ✗、`telnetd` ✗、`httpd` ✗、`crond` ✗、`ip` ✗**；**`udhcpc` ✓、`tc` ✓、`logger` ✓、`switch_root` ✓**；另有 **`ftpd` / `ftpget` / `ntpd` / `ssl_client` / `scriptreplay` / `getty` / `login`** ⇒ **传大文件走 FTP（相机当客户端 `ftpget`，或当服务端 `ftpd`）最省事**，TLS 用 `ssl_client` 或 `/usr/bin/openssl`。

## 3. ★ulogio = 相机自带的内核级调试控制台（telnet 端口写死 **23**）
- 子命令全表（已提取 `work/net-tools/extract/ulogio_help.txt`）：
 `db dw dl logaddr` / **`mb mw ml mf mu`**（内存写：byte/word/line/float/unaligned）/ `switch ilist tlist ot it alog` / `filter trace_filter` / **`lsnap lstart lstop rewind`**（日志快照）/ `term efree uipc uipctxt crash timetag` / **`telnet up|down`**
- 端口来自 **`libosal_ulogio.so:ulogio_telnetd_init`**：`mov.w r12,#0x1700; strh [r7,#6]` ⇒ **htons(23)**，**无参数、无配置**；`a2(/setting)` 里没有 ulogio 配置。
- **`ulogio telnet up` 只是置内核 ko 的旗标，需要重启**才起 socket（串里也写明 `command 'ulogio telnet up' can up the socket`）。
- 它是**日志/内存终端，不是 shell**；但对我们最大的价值：它有 **dword/byte 级的内存读写命令** + 日志快照，比 `dd /dev/mem` 更受控（仍要注意：读非法物理地址可能锁总线）。

## 4. ssh 实况（最终版）
- **服务端：没有**（全镜像里没有任何 `sshd/dropbear` 可执行文件）。
- **客户端：只有库 `libssh2.so.1.0.1`**（静态内嵌两份的串在别的库里；含 md5 主机键钉死逻辑），**没有 `ssh/scp/sftp/ssh-keygen` CLI**。
- 加密件：2.00 = **OpenSSL 1.1.1a**（`libssl1.1/libcrypto1.1`、`/usr/bin/openssl` CLI）；2.03 = **OpenSSL 3.0.2（ssl3）**。另有 **strongSwan**（`/usr/lib/ipsec/`：`charon`、`swanctl`）。

## 5. 2.00 vs 2.03 的实用差异（`a15_200_vs_203_diff.txt`）
- **仅 2.00 有**：`iw`、`iw.so`、`top`、`libssl1.1/libcrypto1.1`。
- **仅 2.03 有**：**`curl 4.8.0`**、`ssl3`、`cdc_ncm.ko`、`jsoncpp`、`opus`、`procps`、`libInfraHttpClient*`。
- 334 个同名文件 size 变（版本差异）；两版 `wifi-scripts/netconf/nvram` 同名。
⇒ **对 2.03 的相机（如 gh issue #23 的作者）：`curl` 现成可用** ⇒ dump/大文件直接 `curl -T/-F` 推到笔记本（HTTP/FTP），**完全不必压在 Jiritsu USB 上**。我们 2.00 没有 curl ⇒ 用 `ftpget`/`ftpd` 或 `openssl s_client`。

## 6. 对我们的可用面（决定下一步选型）
- **控制台**：要"交互 shell"只能自己造（我们的 ARM32 worker 里 `socket()+connect()+dup2` 做**反向 shell**，笔记本 `nc -l 2222`；零新二进制）；要"日志/内存终端"就用现成的 **`ulogio telnet up` + 重启**（端口 23）。
- **传文件**：`ftpget`/`ftpd`（2.00/2.03 都有 busybox FTP）；2.03 直接 `curl`；两版都有 `/usr/bin/openssl` 做哈希/校验。
- **联网**：照抄 §1 的脚本顺序（含 `dhd_irq=144`、`iface_name=wlan`、`ap_scan=0`），别再猜路径。

## 复现（本机，纯只读）
```bash
brew install e2fsprogs    # 得到 /opt/homebrew/opt/e2fsprogs/sbin/debugfs
debugfs -R 'ls -l /' work/l2-camera/nflasha15.bin          # a15 = /usr（ext2）
debugfs -R 'dump <path> out' work/l2-camera/nflasha15.bin   # 取 wifi-scripts / netconf / nvram
python3 work/net-tools/dfls.py work/l2-camera/nflasha15.bin > work/net-tools/a15_tree_full.tsv
python3 work/net-tools/bbapplets.py work/l1-camera/nflasha7.bin   # busybox applet 表（静态提取）
```
