# A7C 网络/调试通道 权威清单（a15=`/usr` 2.00, a7=`/` 2.00, nflasha15_203=2.03 对照）

方法：**A（纯本机 debugfs，只读）**。`brew install e2fsprogs` → `/opt/homebrew/opt/e2fsprogs/sbin/debugfs` 1.47.4。
未使用远端 QEMU（本机没有 qemu-user，ARM 二进制无法执行；busybox 清单用静态解析取得，见 §3 说明）。
所有操作都是 `ls -l / stat / dump / icat`，未写镜像。**未碰相机、未碰远端 `~/a7c-jiritsu/`。**

产物：
- `work/net-tools/a15_tree_full.tsv`（a15 2.00 全树：path/mode/size/type[/symlink?]）1004 行 = 966 文件 + 38 目录 + 67 符号链接
- `work/net-tools/a15_203_tree_full.tsv`（2.03 全树）1023 行 = 983 + 40 + 73
- `work/net-tools/a7_tree_full.tsv`（a7 2.00 全树）622 行 = 588 + 34 + 86
- `work/net-tools/a15_200_vs_203_diff.txt`（2.00↔2.03 逐文件 size diff）
- `work/net-tools/extract/**`（脚本/配置/ELF 原文，见 §2）
- `work/net-tools/busybox_applets_a7.txt` / `busybox_applets_a15.txt`（+ `busybox_applets_a1initrd.txt`）
- 工具脚本：`work/net-tools/dfls.py`（递归 ls -l）、`dfdump.sh`（dump）、`bbapplets.py`（busybox applet 表静态提取）

---

## 1. 三份清单

### 1.1 a15 = `/usr`（2.00，ext2 ro，镜像根 == `/usr` 的内容）
顶层目录（文件数，含子目录内文件）：

| 目录 | 条目 | 说明 |
|---|---|---|
| `/bin` (= `/usr/bin`) | 51 | 见下全列 |
| `/sbin` (= `/usr/sbin`) | 7 | `tcpdump pump dhcpd iptables-multi` + 3 个 `iptables*`→`iptables-multi` 符号链接 |
| `/lib` (= `/usr/lib`) | 223 | 含 `netconf/`(6 配置)、`ipsec/`(strongSwan)、xtables 无（在 a7） |
| `/kmod` | 103 | 全部 .ko |
| `/wifi-scripts` | **12** | **Sony 自己的 WiFi 起机脚本（本次最重要发现）** |
| `/wlan/bcm` | 2 | `bcm4339.bin`(564167) `bcm4339_mfg.bin`(552765) |
| `/share` | 443 | `network/nvram`(78 个 bcm4339_*.txt + rankB.txt)、`network/cert`、`network/dlna`、`network/mtp`、`app`(uxc)、`terminfo`… |
| `/scenario` | 35 | `MPR_SCN_EXEC_WIFI_TEST.so` 等 |
| `/sabin` `/codec` | — | DSP 固件，与网络无关 |
| `/tool` | 7 | LeakTracer/libefence/jemalloc（2.03 只剩 5） |
| `/local/lib` | 0 | 空 |

`/bin` 全列（2.00，size 字节；E=ELF, S=脚本, L=符号链接）：

```
mpr_monio.elf E   usb_insmod.sh S   sndcmd.elf E   sen.elf E   us_remove_modes.sh S  doemparse.sh S
mwf_monio.elf E   startBTCore.sh S  appdbglv.sh S  im.elf E    iperf E(62402)        udtrbody.bin
compat_firmware.sh S  btblog.elf E  Wltestcmd E(30107)  NsBkSet.elf E  ud_datcnv.elf E  SetPort.elf E
mkfifo L(→ ../../bin/busybox)       bt_firm.hcd    btRFTest.elf E  bsa_server E(4802607)  ujlog.elf E
bt_firm_sar.hcd   netblog.elf E     gpioctrl.elf E(86824)  ulogio.elf E(19152)  change_mode.sh S(4022)
bootin.elf E      scenario.elf E    up.sh S(5008)  rcvcmd.elf E  ud_send_lsi.elf E  GPIO2SDIO.elf E
crypter.elf E     ulogio L(→ ulogio.elf)  adjstctl.elf E  swap_prepare.sh S  uuidgen E  openssl E(564529)
testcmd.elf E     wpa_supplicant E(766388)  dhd E(236796)  bk.elf E  common.src S  SDIO2GPIO.elf E
launch_shell.elf E(5092)  wl E(1160152)  top E(48410)  iw E(119232)
```

`/sbin` 全列：`tcpdump(1853201) pump(66129) dhcpd(1544299) iptables-multi(71285)` + `iptables / iptables-save / iptables-restore`（→ `iptables-multi`）。

`/kmod` 网络相关（其余是 sound/usb/mmc/scsi 等）：
```
bcmdhd.ko 491712   cfg80211.ko 193648   mac80211.ko 280800   compat.ko 8200
lib80211_crypt_{wep,tkip,ccmp}.ko   crc-ccitt.ko 2520   configfs.ko 29276
wlanIrq.ko 3784   wlanMemoryAllocator.ko 5148   mmc_core.ko 73336   mmcioWrapper.ko 6780
r8168.ko 424332   usbnet.ko asix.ko cdc_ether.ko rndis_host.ko mii.ko
ppp_generic.ko ppp_async.ko slhc.ko   osal_ulogio.ko 38988   osal_uipc.ko   kikilog.ko
```
**没有** `brcmfmac.ko / brcmutil.ko / bcmdhd-oob.ko / bcmdhd-no-oob.ko`（见 §6）。

网络相关 `/lib`（选）：`libcurl.so.4.7.0(364820)` `libssl.so.1.1(365040)` `libcrypto.so.1.1(1897552)` `libssh2.so.1.0.1(114004)` `libevent*` `libpcap.so.1.0` `libnl-3/route/genl/nf/cli-3.so.200` `libip4tc/libxtables`（iptables 后端）`libosal_ulogio.so(31132)` `libNetService.so(670204)` `libNetCommon.so` `libNetContUtil.so` `libInfraRemote.so(8692048)` `libInfraNetConnectionManager*.so` `libInfraNetInitializer/FunctionManager/DeviceInfo/NetworkServiceInfo.so` `libInfraFtpClient.so` `libInfraDlnaControl.so` `libInfraIPsec.so` `libWlan{Adjust,Resource,ControlCommon}.so` `libInfraBluetooth*.so` `libBT{Adjust,Utils}.so` `libgenuinetime.so`；`/lib/ipsec/`：`libexec/ipsec/charon(18379) libcharon.so.0 libstrongswan.so.0 libvici.so.0 plugins/{openssl,nonce,vici,kernel-netlink,socket-default} sbin/swanctl vici.conf openssl.conf`。

### 1.2 a7 = `/`（2.00）
`/bin` 51 条：44 个是 busybox 符号链接（目标 `busybox`，7 字节相对）+ 真 ELF：
`busybox(396600) cat(25172!) ps(59782) hostname(16729) dnsdomainname(16729) chattr(12429) lsattr(11599) compile_et mk_cmds`。
符号链接的 applet：`cp touch pwd login true rmdir mkdir echo fgrep chown egrep rm sleep ln tar dmesg grep sed mount chgrp mv ping zcat cpio ls umount gunzip dd gzip sh usleep ash ping6 mknod sync kill date uname pidof chmod mktemp`。

`/sbin` 17 条：符号链接（→ `../bin/busybox`）`lsmod ifconfig freeramdisk route insmod getty halt rmmod pivot_root swapon swapoff poweroff reboot` + 真 ELF `init(28524,Sony 自己的 init) sysctl mkdosfs dosfsck`。

`/kmod` 只有 6 个：`nand.ko lld.ko dmac.ko emmc.ko ldec.ko devno.ko`。
`/etc`、`/cert`、`/setting`、`/var`、`/initrd`、`/usr`(挂载 a15)、`/network -> cert`。
`/dev` 里关键符号链接：**`ttycons -> ttyAM0`**（串口控制台）、**`ttyBT -> ttyAM1`**（BT UART）、`fd`、`core`、`satauhs*`。
`/tmp_network /tmp_bt /tmp_cert /tmp_ipsec /log /mnt` 等空目录（运行时用 tmpfs 挂 `/tmp_network`）。
注意 `/bin/cat` 是真 ELF（不是 busybox 链接）→ 覆盖 a7 `/bin` 时不要破坏它。

### 1.3 2.00 vs 2.03（`work/v203/n15/nflasha15_203`）
- 规模：2.00 = 966 文件 / 38 目录 / 67 链接；2.03 = 983 / 40 / 73。
- **只有 2.00 有**：`/bin/iw`(119232)、`/bin/top`、`/lib/iw.so`、`/lib/libssl.so{,.1,.1.1}`、`/lib/libcrypto.so{,.1,.1.1}`、`/lib/libcurl.so.4.7.0`、`/tool/libefence.so`、`/tool/libmcheckb.so`
- **只有 2.03 有**：`/bin/soundstretch`、`/kmod/cdc_ncm.ko`、`/lib/libssl.so.3(.0)`、`/lib/libcrypto.so.3(.0)`、`/lib/ossl-modules/legacy.so`、`/lib/libcurl.so.4.8.0`、`/lib/libjsoncpp*`、`/lib/libopus*`、`/lib/libprocps*`、`/lib/libSoundTouch*`、`/lib/libInfraAccessLog*.so`、`/lib/libInfraHttpClient*.so`、`/lib/libSKDWrapperManager.so`、`/share/data/kikilog_pub.pem`、`/share/app/viewPrivacyNotice.uxc`
- 334 个同名文件 size 不同（Sony 重编，全部 ELF；见 `a15_200_vs_203_diff.txt`）。
- **`/wifi-scripts/` 12 个脚本、`/lib/netconf/` 6 个配置、`/wlan/bcm/*`、`/share/network/nvram/` 78 个 txt 在两版同名同名（size 略变）** → 2.03 的联网顺序不变，issue 作者的结论可以直接套 2.00。
- OpenSSL：**2.00 = 1.1.1a(2018-11-20)**，**2.03 = 3.0.2(2022-03-15)**；curl：2.00 = libcurl/7.74.0（文件名 4.7.0），2.03 = 4.8.0。

---

## 2. 提取的脚本原文 → `work/net-tools/extract/`

目录结构：`extract/a15/{*.sh,bin/,lib/,kmod/,wlan/,lib_netconf/}`、`extract/a7/`、`extract/a1_initrd/`。

**★纠正旧结论**（旧清单是串取证，不可靠）：
- `network.sh`、`WebApiLauncher.sh`：**整个镜像里根本没有这两个文件**（a15 2.00/2.03、a7、a1、a2、a3、a4、a10、a13、a23 全树/全卷文件名都查过）。它们的出处是 **`/usr/lib/libIMDB.so`（36052B，已存 `extract/a15/lib/`）里的 4 条字符串引用**：
  ```
  /usr/bin/WebApiLauncher.sh   /usr/bin/startBTCore.sh   /usr/bin/qsi.elf   /usr/bin/network.sh
  ```
  即主 App（IMDB）按这 4 条路径 fork/exec 联网与 BT 助手；A7C 出厂镜像里只有 `startBTCore.sh` 真的存在，**`network.sh`、`WebApiLauncher.sh`、`qsi.elf` 都被裁掉了**（`qsi.elf` 同样 0 命中）。⇒ “Sony 的联网顺序”在 A7C 上不是脚本，而是 App 内部（`libInfraNetInitializer/libNetService/libWlanControlCommon`）驱动；我们看到的脚本级顺序只能从 `/wifi-scripts/*` 取。
- `bcmdhd-oob.ko` 也只在 `wifi-scripts` 文本里出现（对 a1/a2/a3/a4/a7/a10/a13/a15(2.00)/a15(2.03)/a23 全镜像 grep：只有 a15 命中，且命中来自脚本内容，不是文件）。
- `us_error.sh`：不在 a15，在 **a1 updater initrd** `/usr/bin/us_error.sh`（已存 `extract/a1_initrd/`）。
- `us_remove_modes.sh`：a15 `/bin`（52 B）：`/bin/rm -f /setting/updater/mode*`。
- a15 里 `.sh` 文件总共只有 21 个：`/bin/{usb_insmod,us_remove_modes,doemparse,startBTCore,appdbglv,compat_firmware,change_mode,up,swap_prepare}.sh` + `/wifi-scripts/`12 个。

### 2.1 `/wifi-scripts/start_dhd.sh`（2529B）— WLAN 驱动/上电顺序（核心）
```sh
firm=/usr/bin/bcm4339.bin ; nvram=/usr/bin/bcm4339.txt ; ifname=wlan
#driver=/usr/kmod/bcmdhd-no-oob.ko        <-- 注释里才有 no-oob 变体
driver=/usr/kmod/bcmdhd.ko
case $SYSTEM_TYPE in cam) irq=144; intport=GPIO_S_16; reg_on=MMC_XRST
        gpioctrl.elf w GPIO_S_4 --gpio --dir o 1 ; sleep 1 ;;   # SDIO 电源
gpioctrl.elf w $reg_on --gpio --dir o 1      # WL_REG_ON
gpioctrl.elf iw $intport -n -l               # 中断复用
echo 1 > /proc/irq/$irq/smp_affinity         # IRQ 144 -> CPU1
gpioctrl.elf w SDIO1_DAT_0..3 --func --octrl-oen e --octrl-ien e --dir o   # SDIO 引脚复用
insmod /usr/kmod/compat.ko
insmod /usr/kmod/cfg80211.ko
insmod /usr/kmod/mmc_core.ko
insmod /usr/kmod/mmcioWrapper.ko
insmod /usr/kmod/bcmdhd.ko firmware_path=$firm nvram_path=$nvram iface_name=$ifname dhd_irq=$irq
# iface_name=wlan -> 接口名 wlan0
dhd -i wlan0 <msglevel>   # DHD_DEBUG 时；否则 echo "0 0 0 0" > /proc/sys/kernel/printk
echo "1" > /proc/kmalloc_trace
```
⚠ `/usr/bin/bcm4339.bin`、`/usr/bin/bcm4339.txt` **不在 a15 里**（实际在 `/usr/wlan/bcm/bcm4339.bin`、`/usr/share/network/nvram/*/bcm4339_*.txt`）→ 直接跑这个脚本会 insmod 失败，必须自己改路径或把文件拷到 `/usr/bin/`（`/usr` ro，拷到 `/tmp` 再指 `firmware_path=/tmp/...`）。

### 2.2 `/wifi-scripts/wifi-test.sh`（4224B）— 完整联网+iperf 试验（ Sony 现场测试脚本）
```sh
firm4339=/usr/bin/bcm4339.bin ; nvram4339=/usr/bin/bcm4339.txt
bss_conf=/usr/lib/netconf/bss.conf ; p2p_conf=/usr/lib/netconf/p2p.conf
bring_up_wifi:
  sndcmd.elf --sync 0xA503FB d:0x1020
  echo 1 > /proc/irq/144/smp_affinity
  insmod /usr/kmod/gpio-test.ko ; InitWlanISR.elf ; sleep 2
  insmod /usr/kmod/compat.ko ; cfg80211.ko ieee80211_regdom=JP ; mmc_core.ko ; mmcioWrapper.ko
  insmod /usr/kmod/bcmdhd-oob.ko "firmware_path=$firm4339" "nvram_path=$nvram4339"   # 该 ko 不在 a15！
  mount -t tmpfs /tmpfs /tmp_network ; mkdir /tmp_network/run
  wpa_supplicant -Dnl80211 -i wlan0 -c $bss_conf -N -Dnl80211 -i p2p0 -c $p2p_conf -dddt -B
  wpa_cli -ip2p0 -p /tmp_network/run/wpa_supplicant p2p_set discoverability 1 / p2p_find / p2p_peers
  wpa_cli -iwlan0 -p /tmp_network/run/wpa_supplicant ap_scan 1 ; scan ; scan_results
  wpa_cli ... add_network ; set_network 0 ssid \"mikawaya\" ; set_network 0 key_mgmt NONE ; select_network 0
  ifconfig wlan0 192.168.0.100 up ; ping 192.168.0.1        # 拿地址=手工 ifconfig（静态）
do_iperf_test: /log/iperf -c 192.168.11.2 -t 10
```

### 2.3 `/wifi-scripts/run_supplicant.sh`（925B）
```sh
IFACE=/tmp_network/run/wpa_supplicant ; WLAN_DEV=wlan0 ; P2P_DEV=p2p0
mount -t tmpfs tmpfs /tmp_network ; mkdir /tmp_network/run
mkdir /tmp_network/dhcpd ; touch /tmp_network/dhcpd/dhcpd.leases
kill -KILL <旧 wpa_supplicant pid>（从 ps -eo pid,comm 取）
/usr/bin/wpa_supplicant$VERSION -Dnl80211 -i wlan0 -c /usr/lib/netconf/bss.conf \
    -e /tmp_network/entropy.bin -N -Dnl80211 -i p2p0 -c /usr/lib/netconf/p2p.conf -dddt -f /supplicant-shell.log -B
```
`run_single_p2p.sh` = 同上但两个 supplicant 分开跑 + 自动 `p2p_set discoverability 1; p2p_find`。
`cli.sh` = `wpa_cli -i $1 -p /tmp_network/run/wpa_supplicant $@`；`cli_wlan0.sh` / `cli_p2p0.sh` 固定接口。
`stop_dhd.sh` = `rmmod bcmdhd; rmmod mmcioWrapper; rmmod mmc_core; rmmod cfg80211; rmmod compat` + `gpioctrl.elf w $reg_on ... 0`（cam: 再关 GPIO_S_4）。
`load_firm.sh` = 另一条 **brcmfmac** 路线：`rmmod brcmfmac/brcmutil/cfg80211/compat` → `insmod /usr/backport/kmod/{compat,cfg80211,brcmutil,brcmfmac}.ko debug=0`（**`/usr/backport` 在 a15 不存在**）→ 用 sysfs 手工喂固件：`echo 1 > /sys/class/firmware/mmc0:0000:1/loading; cat /usr/bin/bcm4339.bin > .../data; echo 0 > ...`（nvram 同理）。
`setwifi.sh` = 用 `bk.elf` 写 board-key 决定 WL_REG_ON 引脚：`bk.elf w 0xf90365 2`（BKID_PORT_GRP_XWLAN_RST）、`bk.elf w 0xf90366 0x16`（BKID_PORT_BIT_XWLAN_RST）、`bk.elf s` 保存；dsc-new 用 grp3/bit0x1a。
`set_gpio.sh` = 按 SYSTEM_TYPE 做 GPIO 复用（与 start_dhd 类似）。
`ulset.sh` = 打开 ulogio 过滤：`ulogio filter on 0xa5 INFO # R_WLAN`、`0xa6 B_NETWORKMANAGER`、`0xab I_WLANMANAGER`、`0x169 B_REMOTE`、`0x192/0x193`、`314..324 369 370 373 374`（Web API 等）。

### 2.4 `/lib/netconf/*`（提取到 `extract/a15/lib_netconf/`）
- `bss.conf`：`ctrl_interface=/tmp_network/run/wpa_supplicant`、`update_config=0`、**`ap_scan=0`**、`p2p_disabled=1`、`disable_scan_offload=1`、`wps_cred_processing=1`、WPS(manufacturer=Sony Corporation, model_name=SonyImagingDevice)。→ `ap_scan=0` 表示 Sony 用 wps/AP 模式，自己下发网络参数；**手动测试时要 `wpa_cli set_network N key_mgmt NONE` 或改 ap_scan=1**（wifi-test.sh 里就是这么干的）。
- `p2p.conf` / `p2p_multi_go.conf`：`p2p_go_intent=10`、`p2p_oper_reg_class=81`（5GHz 动态信道）、`max_num_sta=1`、`p2p_ssid_postfix=-WCM`。
- `dhcpd.conf`：`subnet 192.168.0.0/16`, range 192.168.0.1-192.168.11.255 / 192.168.122.100-200，routers 192.168.122.1，lease 86400，`ping-timeout 0`。
- `pump.conf`：`retries 3 / nogateway / nodns`，`device wlan0 { nodns autoip }`、`ath0/ath1`（老 Atheros 命名残留）。→ **拿地址的正统做法是 `pump`**（a15 `/usr/sbin/pump`），或 `ifconfig` 静态。

### 2.5 其它
- `/bin/change_mode.sh`（4022B）：写 `/setting/mode/dmode` + `/setting/mode/preload`，模式 0..f，含 `a`=(target gdb)、`b`=(**gdbserver**)、`e`=Electric Fence、`f`=jemalloc；改完调 `ud_send_lsi.elf <mode>`。⚠ 镜像里没有 gdbserver 可执行文件。
- `/bin/up.sh`（5008B）：updater 模式旗标（`/setting/updater/mode,mode1,mode3,mode4,mode5,mode6`）+ `func_modver/modmod/modreg` 用 `ud_datcnv.elf -d/-e` 读写 `/setting/updater/dat4`、`/dev/nflasha1` 的 `dat2/dat3`，最后 `ud_send_lsi.elf $mode_num`。**与网络无关**（旧清单把它当联网脚本是误解）。
- `/bin/startBTCore.sh`：`/usr/bin/bsa_server -k /tmp_bt/ble_local_keys -u /tmp_bt/ -d /dev/ttyBT -p /usr/bin/bt_firm.hcd -all=0 &`；开关文件 **`/tmp_bt/DEBUG`、`/tmp_bt/NOTLOAD`**（DEBUG→ `-b /tmp_bt/snoop.cfa -all=5 > /tmp_bt/bsa_log.txt`；NOTLOAD→ `-r 14` 不下载 BT 固件），然后 `pidof bsa_server` 死等。BT 走 `ttyBT=ttyAM1`。
- `/bin/compat_firmware.sh`：udev 固件加载器，`FIRMWARE_DIRS="/usr/wlan/ath/"`（**该目录不存在**；实际固件在 `/usr/wlan/bcm/`）→ 说明热补丁固件机制可用（`$DEVPATH/loading`）。
- `/bin/appdbglv.sh`（10088B）：用 `ulogio filter ...` 调 App 子系统日志（0x87/0x88/0x89…），自动选 `ulogio.elf` 或 `ulogio`。
- `/bin/usb_insmod.sh`：`insmod /kmod/...`（路径是 a7 的 `/kmod`，说明这些脚本假定运行在 initrd/updater 环境）。
- `/bin/common.src`、`doemparse.sh`、`swap_prepare.sh` 也已提取。

---

## 3. busybox applet 清单（权威回答 8 个 applet）

**a15 里没有 busybox 二进制**（全树 966 文件里无 busybox；`/bin/mkfifo -> ../../bin/busybox`，即运行期借用 **a7 的 `/bin/busybox`**；`/bin/ulogio -> ulogio.elf`）。
两处 busybox：
| 位置 | size | sha1 | 版本 |
|---|---|---|---|
| a7 `/bin/busybox` | 396600 | `2d794cd5…` | **BusyBox v1.29.3 (2021-02-04 23:04:59 JST)** ARM EABI5, 动态链接 `//lib/ld-linux.so.3`, stripped |
| a1 updater initrd `/bin/busybox` | 396600 | `19d34940…` | **BusyBox v1.29.3 (2018-12-07 16:14:33 JST)** |
| a15 | — | 无 | 无 busybox（用 a7 的） |

两者的 applet 集合**完全相同（191 个名字）**（`diff busybox_applets_a7.txt busybox_applets_a1initrd.txt` 无差异）。

取证方法（**没有真跑 `--list`**：macOS 无 qemu-user，ARM ELF 不能本机执行；远端 QEMU 未启用）：
`bbapplets.py` 在 `.text/.rodata` 里找“连续 NUL 分隔的短名 run”，命中唯一一段（偏移 `0x487e2`，191 项，按字母序，全部是合法 busybox applet 名，无 libc 符号混入）——即 busybox 的 `applet_names` 打包表。旁证：该二进制里 `Usage:` 串只有 4 条（`FEATURE_VERBOSE_USAGE` 关闭），所以无法用 usage 串反证；但表内名字完整、自洽（含 `[[`、`linuxrc`、`run-init`、`switch_root`、`ubirmvol` 这类只有 applet 表才会出现的名字）。若要 100% 权威，在 QEMU guest 里 `./busybox --list` 复核（1 分钟）。

问的 8 个（`grep -cx` on `busybox_applets_a7.txt`）：

| applet | 有? |
|---|---|
| `nc` | **无** |
| `telnetd` | **无** |
| `httpd` | **无** |
| `udhcpc` | **有** |
| `tc` | **有** |
| `crond` | **无** |
| `logger` | **有** |
| `switch_root` | **有** |

完整 191 个（同 `busybox_applets_a7.txt`）：
```
[[ acpid arch ash base64 basename beep blkdiscard blockdev bootchartd bunzip2 bzcat cat chgrp chmod chown
chroot cmp conspy cp cpio cut date dd dhcprelay dirname dmesg dnsdomainname dumpleases echo egrep env expr
factor fallocate false fatattr fgconsole fgrep flock freeramdisk fsfreeze fstrim fsync ftpd ftpget ftpput
fuser getty grep groups gunzip gzip halt hexedit i2cdetect i2cdump i2cget i2cset ifconfig ifdown ifplugd
ifup insmod ionice iostat ipneigh kill killall klogd link linux32 linux64 linuxrc ln logger login ls lsmod
lsof lspci lsscsi lsusb lzcat lzma lzop md5sum mkdir mkdosfs mke2fs mkfifo mkfs.ext2 mkfs.vfat mknod
mkpasswd mktemp modinfo modprobe mount mpstat mv nanddump nandwrite nbd-client nl nproc ntpd nuke partprobe
paste pidof ping ping6 pivot_root pmap poweroff powertop pstree pwd pwdx readlink reboot resume rev rm
rmdir rmmod route run-init scriptreplay sed setfattr setpriv setserial sfdisk sh sha1sum sha256sum sha3sum
sha512sum shred shuf sleep smemcap sort ssl_client stty svc svok swapoff swapon switch_root sync syslogd
tail tar taskset tc test timeout touch traceroute6 true truncate tunctl ubiattach ubidetach ubimkvol
ubirename ubirmvol ubirsvol ubiupdatevol udhcpc udhcpd uevent umount uname uniq unlink unshare unxz usleep
vconfig volname wc whois xargs xxd xz xzcat zcat
```
（`[` 可能被 run 边界切掉一个，实际应为 192；不影响结论。）
其它有用事实：**没有 `ip`**（只有 `ifconfig/route/tc/vconfig/tunctl`）；没有 `wget/tftp/nc/httpd/telnetd/telnet/crond/top/vi/awk/sed 有`；有 `ftpd/ftpget/ftpput`、`ntpd`、`ssl_client`、`scriptreplay`、`conspy`、`getty/login/linuxrc`（但 `init` 是 Sony 自己的 ELF，busybox 未编 `init`）。a7 只给 `/bin`、`/sbin` 建了少量符号链接，其余 applet（含 `udhcpc`、`tc`、`ftpd`）可用 `busybox <applet>` 直接调用。

---

## 4. ulogio：用法与 telnet 端口（结论）

文件（都在 a15，已提取）：
- `/usr/bin/ulogio.elf` 19152B（+ `/usr/bin/ulogio` → `ulogio.elf`）：CLI 客户端，直接读写 log 环形缓冲/`/dev/mem`/`/proc/klog`
- `/usr/kmod/osal_ulogio.ko` 38988B（vermagic `3.0.27_nl-rt106+ SMP preempt mod_unload ARMv7`；符号 `ulogio_filter_set_telnet / _get_telnet / ulogio_reg_listener / __ulogio_listener_thread_entry / ulogio_{suspend,resume}_listener`；源路径 `Etools-OSAL-ULOGIO_171H/driver/kif.c`）
- `/usr/lib/libosal_ulogio.so` 31132B（导出 `ulogio_telnetd_init / ulogio_telnetd_mainloop / ulogio_telnetd_exit / ulogio_telnetd_select_io_term_by_id / ulogio_telnetd_print_termlist / ulogio_filter_print_telnetinfo`）→ **telnetd 是链接进主 App（mpr/avmain）的库里的线程**，不是独立可执行文件。
- a1 updater initrd 也带 `/usr/bin/ulogio.elf`（19912B，另一构建）。

完整子命令表（`extract/ulogio_help.txt`，取自 `.elf` 的 help 串）：
```
db/dw/dl <base> <size>   dk <base> <size> <file>       logaddr [SubSystemID][SubArea]
mb/mw/ml <base> <data>   mf <base> <size> <data>       mu <base> <size> <file>
switch [SubSystemID]     ilist                         tlist
ot <idx>  it            alog [-p] PATH [-b] f [-d] f [-k] f [-t] f
filter on <SSID> [CID] <ERROR|WARNING|DEBUG|INFO> | filter off <SSID> | filter abort [clear] | filter info | filter clear
trace_filter on|off|clear|info <SSID>
lsnap <SSID> <file>   lstart <SSID> <file>   lstop <SSID>   rewind
term on|off   efree on|off   uipc <OSAL_ID> <data>x6   uipctxt <file>
help  exit  crash  timetag normal|limit|both|off
telnet down -- disable telnet output, must be reboot system
telnet up   -- enable telnet output,   must be reboot system
```
（`extract/ulogio_lib_telnet_strings.txt` 里库侧的报错串：
`[ulogio] socket ignore because telnet flag is down` / `command 'ulogio telnet up' can up the socket` /
`[ulogio] failed to bind telnetd port` / `[ulogio] failed to enable listen on listenerfd` /
`[ulogio] failed to create socket` / `failed to created telnet sessions` / `telnet flag update, now the flag = %s`）

**端口结论：写死的 telnet 默认端口 23，没有命令行参数也没有配置文件。**
证据（`extract/ulogio_telnetd_init_bind.asm`，Thumb 反汇编 `ulogio_telnetd_init`）：
```
4506: movs r0,#2 ; movs r1,#1 ; bl socket        -> AF_INET, SOCK_STREAM
451a: add r3,r7,#0x18 ; mov r8,#1 ; movs r2,#2 ; str r8,[r3,#-4]! ; str lr(=4),[sp]
      bl setsockopt                              -> SO_REUSEADDR
4536: add r1,r7,#4 ; movs r2,#0x10 ; movs r3,#2 ; mov.w r12,#0x1700
      strh r3,[r7,#4] ; str r5,[r7,#8] ; strh.w r12,[r7,#6]   ; bl bind   -> sin_port 字节 00 17 = htons(23)
4556: bl listen(fd, 2)
```
即 `sockaddr_in` 里 port 域被写 `0x1700`（内存布局 0x00,0x17 ⇒ **htons(23)**），AF_INET + INADDR_ANY。唯一入参是 `ulogio_telnetd_init(struct*)`，其 `+0x10` 是使能旗标（为 0 则直接打印 “socket ignore because telnet flag is down” 之类），**没有端口字段**。

telnet 配置文件搜索（都没找到）：a15 全树 grep `ulogio|telnet`（只有上 4 个文件）；a1 initrd（只有 `ulogio.elf`）；**a2 = `/setting` FAT 卷**根目录只有 `DMMCON~1.BIN / UPDATER/ / HASP~1 / BACKUP.BIN / FACEDMY.BIN / APPFW_/ KEMCO.TXT / FACEREC0.BIN`（无 ulogio 配置）；`strings` 在 ko/so 里找 `telnetd port|port=` 只有报错串。运行时开关只有 BT 侧的 `/tmp_bt/{DEBUG,NOTLOAD}`。
⇒ 起 telnet 的唯一办法：`ulogio telnet up`（写 ko 里的 filter 旗标，**需要重启**才生效，help 已注明），然后 TCP/23 出现。

---

## 5. SSH 结论

- **服务端：没有。** a15(966 文件)、a7(588)、a1 initrd 里都没有 `sshd/dropbear/dropkey/openssh` 任何可执行文件（文件名与 ELF 名都没有）。唯一的 TCP 监听者（除 Sony App 自己开的 5G4869/PTP/MTP/DPnP 等端口）是 ulogio 的 telnetd(23)。
- **客户端库：只有 libssh2**：`/usr/lib/libssh2.so.1.0.1`(114004) + `libssh2.so.1`、`libssh2.so` 符号链接。**没有 `ssh/scp/sftp/ssh-keygen/sftp-server` 可执行文件**（全树文件名匹配）。所谓 “libssh 串 210 次” 是 `libssh2` 的符号名。
- TLS：2.00 `/usr/lib/libssl.so.1.1`(365040)、`/usr/lib/libcrypto.so.1.1`(1897552)，版本串 **`OpenSSL 1.1.1a  20 Nov 2018`**；符号链接 `libssl.so.1 / libcrypto.so.1`（2.00）——2.03 换成 **`OpenSSL 3.0.2 15 Mar 2022`**（`libssl.so.3`=412204, `libcrypto.so.3`=2656568, 加 `ossl-modules/legacy.so`）。
- 有 **`/usr/bin/openssl`(564529)** CLI ⇒ 可以 `openssl s_server` / `s_client` 做临时（TLS）socket；`/usr/bin/uuidgen`、`/bin/iperf`(iperf 2.0.5)、`/sbin/tcpdump`(1853201, 依赖 `/usr/lib/libpcap.so.1.0`)。
- IPsec：`/usr/lib/ipsec/`（strongSwan：charon、libcharon.so.0、libvici.so.0、plugins openssl/nonce/vici/kernel-netlink/socket-default、`sbin/swanctl`、`vici.conf`）+ `/usr/lib/libInfraIPsec.so`、a7 `/tmp_ipsec` → 想借 IPsec 做通道也可，但比 telnet/自建 shell 复杂。

---

## 6. bcmdhd 三变体 与 固件

**a15(2.00 与 2.03) 只有一个 `bcmdhd.ko`**（2.00=491712B，2.03=522740B）。
`bcmdhd-oob.ko` / `bcmdhd-no-oob.ko` **不是文件**，只出现在脚本字符串里：
- `start_dhd.sh`：`#driver=/usr/kmod/bcmdhd-no-oob.ko`（注释）→ 实际用 `bcmdhd.ko`
- `wifi-test.sh`：`insmod /usr/kmod/bcmdhd-oob.ko "firmware_path=..."`（该 ko 不在 a15 ⇒ 这脚本是旧平台/内部版本遗留，直接跑会失败）
所以“三者差别”= **同一个 ko 里两套编译期都存在的代码路径**，用参数/编译选择：`bcmdhd.ko` 内含
`dhd_enableOOB`、`dhd_bus_oob_intr_set/register/unregister`、`gpioob`、错误串 `CANNOT SIGNAL CHIP TO CLEAR OOB!!`，参数说明 `parm=dhd_irq:DHD oob gpio number` ⇒ **OOB 中断开关就是 `dhd_irq`（cam=144）给不给**：给了就用 OOB 唤醒，不给则走 SDIO 数据轮询/带内中断。
导出/可见的 mod 参数（strings 里的 .param 名）：`firmware_path`、`nvram_path`、`iface_name`、`dhd_irq`（另有大量 `dhd_*` 内部 int）。vermagic `3.0.27_nl-rt106+ SMP preempt mod_unload ARMv7` ⇒ 只能插进相机那颗 3.0.27 内核（QEMU guest 里已验）。
没有 `brcmfmac.ko/brcmutil.ko`（`load_firm.sh` 引用的 `/usr/backport/kmod/` 整个不存在）→ brcmfmac 路线在 A7C 上不可用，只能 bcmdhd。

固件（提取到 `extract/a15/wlan/`）：
- `/usr/wlan/bcm/bcm4339.bin` 564167B = **完整运行固件**（roml + 主固件 + CLM 已内建）。头 16 个 32bit 向量 `80f1 3ebc 80f1 a4bf …`（dhd 加载时会搬 RAM），尾部含 `DVID 01-e…`，内嵌版本串：
  `4339a0-roml/sdio-ag-pool-p2p-pno-pktfilter-keepalive-aoe-sr-mchan-proptxstatus-lpc-autoabn-mfp-txbf-ipa-ecal-txpwr-ltxwat-clm_43xx_sony_DI-sndi-toe Version: 6.37.39.113 (r722271 CY) CRC: 6a730d52 Date: Mon 2020-03-16 00:01:42 CDT Ucode Ver: 918.2015 FWID 01-82ca9c40`
  （**没有独立 `.clm` 文件**，CLM 以 `clm_43xx_sony_DI` 编在固件里；也没有 `clm_bcm.hdr`）
- `/usr/wlan/bcm/bcm4339_mfg.bin` 552765B = **MFG(工厂测试)固件**，同一向量表开头，少 ~11KB。给 `wl`/`Wltestcmd`/`athtestcmd`/`btRFTest.elf` 用。
- nvram：`/usr/share/network/nvram/{2_4GHz_low_5GHz_low, 2_4GHz_low_5GHz_high, 2_4GHz_high_5GHz_high}/bcm4339_{L_L,L_H,H_H}_{01..26}.txt`（共 78 个，3112–3147B，按地区/功率档），每个目录还有 0 字节的 `rankB.txt` 旗标。**没有** `nvram.txt`/`bcmdhd.txt` 之类固定名文件；脚本默认要的 `/usr/bin/bcm4339.txt` 在镜像里不存在。

---

## 7. “root 起 Wi-Fi + 一个 TCP shell” 可行性（本轮结论）

1. **Wi-Fi：完全可行，顺序在 `/wifi-scripts/*` 里（不在 network.sh——那个文件不存在）**（`/wifi-scripts/start_dhd.sh` + `run_supplicant.sh` + `cli_wlan0.sh`）。照抄顺序即可：
   `gpioctrl.elf w GPIO_S_4 --gpio --dir o 1`（SDIO 供电，cam 变体）→ `gpioctrl.elf w MMC_XRST --gpio --dir o 1`（WL_REG_ON）→ `gpioctrl.elf iw GPIO_S_16 -n -l` → `echo 1 > /proc/irq/144/smp_affinity` → SDIO1 引脚 `--func` 复用 → `insmod compat/cfg80211/mmc_core/mmcioWrapper/bcmdhd firmware_path=/tmp/bcm4339.bin nvram_path=/tmp/<region>.txt iface_name=wlan dhd_irq=144` → `mount -t tmpfs tmpfs /tmp_network; mkdir /tmp_network/run` → `wpa_supplicant -Dnl80211 -i wlan0 -c /usr/lib/netconf/bss.conf -B`（bss.conf 有 `ap_scan=0`，手测要 `-c` 自己写的 conf 或 `wpa_cli set_network N key_mgmt NONE`）→ `wpa_cli -p /tmp_network/run/wpa_supplicant -i wlan0 …` → 地址用 **`busybox udhcpc -i wlan0`**（applet 有，只是没建链接）或 `/usr/sbin/pump -i wlan0`（conf 里是 autoip）或 `ifconfig wlan0 <ip> up`（静态，wifi-test.sh 就这么做）。唯一要补的是 **固件/nvram 的实际路径**（`/usr/wlan/bcm/bcm4339.bin`，不是 `/usr/bin/…`）与 `bcmdhd-oob.ko` 名字。
   硬件前提（A7C 的 SDIO 走哪个 controller / WL_REG_ON 是哪个 GPIO）由 `setwifi.sh` 的 board-key + `set_gpio.sh` 决定；本机是 `cam` 变体：irq=144、GPIO_S_16、MMC_XRST、SDIO1。
2. **TCP shell：现有固件里没有现成的 shell。** 没有 sshd/dropbear/nc/telnetd/httpd，busybox 也没有 `nc/telnetd/httpd`。
   - 唯一内置 TCP 监听 = **ulogio telnetd（TCP/23，htons(23) 写死，`ulogio telnet up` + 重启才起）**，但它是 **日志终端**（`tlist/ot/it` 选输入/输出终端，喂 ulogio 命令），**不是 shell**。
   - `launch_shell.elf`（5092B）用 `fork+execv+dup2+setsid+tcsetattr` 在 **`/dev/ttycons`（= `/dev/ttyAM0`，串口）** 上开 shell（updater 环境用），可作“把 shell 接到某个 fd”的模板，但它不是 TCP。
   - 现实路线：往相机拷一个 **自己编的静态 ARM busybox**（含 `nc`/`httpd`/`telnetd`）到 `/tmp`（tmpfs 可执行；`/usr` 是 ro，a7 `/` 是 ext2）——相机上没有编译器，也没有可用的现成 TCP shell。
   - 备选：busybox `ftpd/ftpget/ftpput`（有 applet）做文件通道；`/usr/bin/openssl s_server/s_client` 做加密 socket（但不能 exec）；`/bin/iperf`、`/sbin/tcpdump` 做网络观测。
3. `change_mode.sh` 的 `b` = gdbserver 模式说明产品支持 gdbserver 启动，但镜像里 **没有 gdbserver/gdb 可执行文件** → 别指望它。

---

## 8. 复现命令（全部只读）

```bash
DF=/opt/homebrew/opt/e2fsprogs/sbin/debugfs      # brew install e2fsprogs
A15=work/l2-camera/nflasha15.bin ; A7=work/l1-camera/nflasha7.bin ; A203=work/v203/n15/nflasha15_203

# 全树（path/mode/size/type）
python3 work/net-tools/dfls.py $A15  / > work/net-tools/a15_tree_full.tsv
python3 work/net-tools/dfls.py $A7   / > work/net-tools/a7_tree_full.tsv
python3 work/net-tools/dfls.py $A203 / > work/net-tools/a15_203_tree_full.tsv
# 2.00 vs 2.03（名字级 + size 级）
cut -f1,3 work/net-tools/a15_tree_full.tsv | sort > /tmp/t200
cut -f1,3 work/net-tools/a15_203_tree_full.tsv | sort > /tmp/t203
diff /tmp/t200 /tmp/t203 > work/net-tools/a15_200_vs_203_diff.txt
comm -23 <(cut -f1 /tmp/t200|sort) <(cut -f1 /tmp/t203|sort)   # only 2.00
comm -13 <(cut -f1 /tmp/t200|sort) <(cut -f1 /tmp/t203|sort)   # only 2.03

# 提取文件（路径是 a15 内部路径，即 /usr 去掉 /usr 前缀：/usr/wlan/... = /wlan/...）
work/net-tools/dfdump.sh $A15 work/net-tools/extract/a15 /wifi-scripts/start_dhd.sh /bin/up.sh /bin/ulogio.elf /wlan/bcm/bcm4339.bin
$DF -R "stat /bin/mkfifo" $A15 | grep 'Fast link dest'      # -> ../../bin/busybox
$DF -R 'ls -l /wifi-scripts' $A203                          # 2.03 里同名 12 个脚本

# busybox applet 表（静态；无 qemu-user）
python3 work/net-tools/bbapplets.py work/net-tools/extract/a7/busybox > work/net-tools/busybox_applets_a7.txt
strings -a work/net-tools/extract/a7/busybox | grep -m1 'BusyBox v'      # v1.29.3 (2021-02-04 JST)

# ulogio telnet 端口（=23）
strings -a work/net-tools/extract/a15/bin/ulogio.elf | sed -n '/^db <base_addr>/,/^telnet up/p'
objdump -d --triple=thumbv7el-linux-gnueabi --start-address=0x4506 --stop-address=0x455c \
        work/net-tools/extract/a15/lib/libosal_ulogio.so | grep -E 'socket|setsockopt|bind|listen|0x1700'
strings -a work/net-tools/extract/a15/kmod/bcmdhd.ko | grep -E 'dhd_enableOOB|parm=dhd_irq|vermagic'
```

### 待复核项（留给下一轮 / QEMU）
1. `busybox --list` 在 QEMU guest 里跑一遍（预计与 191 项一致）——本轮没有真执行。
2. ~~`network.sh`/`WebApiLauncher.sh` 宿主~~ → **已定位**：都在 `/usr/lib/libIMDB.so` 的字符串里（该 lib 还引用 `qsi.elf`），四个文件里只有 `startBTCore.sh` 存在。要确认运行期行为只能在 QEMU/相机上 `strace` 式观察。
3. `bcmdhd-oob.ko` 已在 a1/a2/a3/a4/a7/a10/a13/a15(2.00)/a15(2.03)/a23 全部镜像 grep 过：**只有文本引用，没有这个文件**；其余分区（a14/a16-a22 等）本轮没拿。
4. a2 FAT 子目录（`UPDATER/`、`APPFW_/`）本轮解析失败（LFN/cluster 链），没确认里面是否有 ulogio/telnet 开关文件；已确认根目录没有。
