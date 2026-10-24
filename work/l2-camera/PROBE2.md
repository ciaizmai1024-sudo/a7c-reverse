# A7C (FW2.00) 第二只读探针 L2 — 实测结果

日期：本机 2026-10-23；远端 Ubuntu 24.04 (`wubin@172.22.22.131`)，相机 `054c:0d29`（MSC）→ 鉴权后 `054c:0336`。
全程只读：`scan / mount / fget / dump / raw`；没有跑任何 `put/fput/del/fdel/wr/jir(写)`；没有重启相机。

---

## 0. 本轮最重要的两条"协议级"修正（比数据本身更值钱）

### 0.1 FileControl(0xff01) 的 `130` 是**工具的 framing bug**，不是相机拒绝
`pmca/usb/sony.py::_sendFileControlPacket` 与 `tools/jiritsu_send.py` 都用
```python
fn += b'\0' * (4 - len(fn) % 4)      # len(fn) % 4 == 0 时补 0 个 → 错
```
文件名长度**已经**是 4 的倍数时（`/setting/partinf.conf`=21→补 3 是对的，但 `/version.txt`=12、`/setting/kemco.txt`=18、`/dev/nflasha15`=16 等**一个字节都不补**）帧就错位 ⇒ 相机回 `130`。
已在远端打补丁（备份 `tools/jiritsu_send.py.prepatch.bak`，只改真实路径用的 `Jiriris.fread` 那一处，line 320）：
```python
fn += b'\0' * (-len(fn) % 4)
```
打完补丁后 **FileControl 全线可用**：路径读、块设备整读、`MemoryDump(0xff03)` 都通。
⇒ L1 报告里"FileControl 全部 130 / 只有 Jiritsu 通道能用"的结论要推翻。

### 0.2 每次命令后要 USB 硬复位，否则下一次鉴权 `No such device`
服务模式 `0x0336` 会滞留并变僵尸（`usb.core.USBError [Errno 19] No such device`）。
远端新增 `~/a7c-jiritsu/wrap2.sh`：每条命令前 `libusb reset`（等价拔插，不碰相机电源）+ 等回 `0d29`，再鉴权。整套 B/C 都是靠它跑通的。

### 0.3 顺带的只读冒烟（都是负结果，记下来省下次时间）
| 通道 | 结果 |
|---|---|
| `MemoryDump 0xff03 @0xffff0000,64B` | **通**（resp=1，BootROM 向量表可读）→ 以后可当"只读代码读回"手段 |
| `AdjustControl` pfunc `0x0000`/`0xff07` + `0x603/0x601` | **resp=128**（A7C 上不通；与 FX30 issue 记录的 128 一致） |
| `ProductInfo` pfunc `0xff00` | **resp=130**（我们用的 category/code 不对，或该 PFUNC 在 0336 下不服务） |
| Jiritsu `GET_FILE2 /tmp/jiritsu/libJit.so` | status `0x10000006`（不是 130）⇒ **ramdisk 区空**，见 §4 |

---

## 1. 鉴权 / 会话

```
timeout 60 scan   → 054C:0D29 bus=1 addr=41 (ILCE-7C)
timeout 200 mount → MSC 鉴权 → 服务模式 0x0336 出现 → 服务通道鉴权 OK → PFUNC 0x0040 len=4 01100200
```
**鉴权 OK**。`jir MOUNT(0x4002)` 返回 status=0（成功），但 `GET_VERSION(13)` 返回 `0x10000006`（见 §4）。

---

## 2. 路径矩阵（B）

完整表：`work/l2-camera/probe2/path_matrix_all.log`（81 条），原始日志 `probe2/path_matrix.log`。
判据：`OK size=…` = 可读；`130` = 不存在/是目录/未挂载；`0x10000006` = Jiritsu 侧没有该文件。

**可读（FileControl，绝对路径）**

| 路径 | 大小 | 备注 |
|---|---|---|
| `/version.txt` | 19 B `39119_05.2021111501` | 与包里 `nflasha7_unpacked/version.txt` **sha256 逐字节相同** ⇒ **FileControl 的 `/` = 运行中的 rootfs（nflasha7/initrd）** |
| `/setting/kemco.txt` | 1905 B | sha256 `ff9a739e2c01…` = 包 `0800_appli/setting/kemco.txt`（**未改**） |
| `/setting/Backup.bin` | 1210408 B | 校准备份（注意：不是笔记里写的 1235836） |
| `/setting/updater/comp` | **0 B** | 旗标，见 §5 |
| `/setting/updater/dat4` | 2 B `00 02` | 更新器认的当前版本 = 2.00 |
| `/usr/bin/crypter.elf` | 39036 B | 见 §3 对照表 |
| `/usr/bin/udtrbody.bin` | 143360 B | |
| `/usr/bin/up.sh` | 5008 B | |
| `/usr/bin/sen.elf` | 19164 B | **在 `/usr/bin`，不在 `/usr/local/bin`** |
| `/usr/bin/change_mode.sh` | 4022 B | 下一步清/设旗标要用的 |
| `/usr/bin/us_remove_modes.sh` | 52 B | 同上 |
| `/usr/lib/{libupdaterufp,libupdatertalk,libupdaterufunc,libupdatercommon,libupdatermedia,libJiritsu,libsencore}.so` | 12936/3404/4324/37004/3992/174816/369804 | 全部与包一致（§3） |
| `/tmp/{nsswitch.conf,kikilog.dat,toprc,services,config.spec}` | 261/1957888/617/19666/0 | `/tmp` = nflasha10 FAT，**`/tmp/etc/…` 不存在，就是 `/tmp/…`** |

**读不到（130）的关键项**
- `/setting/updater/{mode,mode1..mode6,uincomp,debug,version.txt,kikilog.dat,Backup.bin}` ⇒ **现在没有任何旗标文件**（`mode` 是历史残留，见 §5）
- `/setting/{partinf.conf,mount.conf}`、`/partinf.conf`、`/mount.conf` ⇒ **这两份 conf 不在运行系统的任何挂载点里**（只在包里）
- `/dat1 /dat2 /dat3 /dat4 /p1chksum /Backup.bin /boot/*`（`dat2/dat3/p1chksum` 只在 **nflasha1 自己的 FAT** 里，rootfs 没有；`/boot/…` 全 130）
- `/usr/bin/{mf,sauu,sauu.elf,mf.elf,us_mkfs.sh,endupdate.sh,us_crc32sum_appli.sh,ud_lerase.elf,ud_fsys_format.elf,udtrmain.sh}` ⇒ **官方更新的脚本/二进制不在 /usr**（在 nflasha1 的 initrd 里）
- 目录一律 130：`/setting /tmp /usr /lens /PMBP/PMHOME /tmp/jiritsu /hash` ⇒ FileControl 没有"列目录"能力，只能猜路径
- `/tmp/jiritsu/libJit.so`、`/tmp/jbusy` ⇒ 不存在（§4）

---

## 3. 分区 dump（C）与两次读一致性

远端 `~/a7c-jiritsu/work/l2/`，本机 `work/l2-camera/`（`shasum -a 256 -c SHA256SUMS` 全部 OK）。
吞吐实测 ≈ **12 MB/s**（a15 300 MB / 24.2 s）；除 a2 外全部 `--twice 2` 一致。

| 分区 | 长度 | 期望(partinf) | 读1 sha256[:8] | 读2 sha256[:8] | 一致 |
|---|---|---|---|---|---|
| nflasha23 | 2097152 | 0x200000 ✔ | `49415249` | 同 | ✔ |
| nflasha4 | 12582912 | 0xC00000 ✔ | `ec36067f` | 同 | ✔ |
| nflasha10 | 12582912 | 0xC00000 ✔ | `43c88729` | 同 | ✔ |
| nflasha2 | 20971520 | 0x1400000 ✔ | `70945a63` | `1de869dd` | ✗ 见下 |
| nflasha15 | 314572800 | 0x12C00000 ✔ | `fc0b6fcf` | 同 | ✔ |
| nflasha1 (补测) | 8323072 | 0x7F0000 ✔ | `82e1b199` | 同 | ✔ |
| nflasha6 (补测) | 16777216 | 0x1000000 ✔ | `b9d759a7` | 同 | ✔ |
| nflasha13 (补测) | 4194304 | 0x400000 ✔ | `0413532a` | 同 | ✔ |

**nflasha2 为什么两次不一致（已定位，不是 USB 坏了）**
再读一轮（`nflasha2_r2.bin` / `.r1`）后：
- 每个会话的**第 2 次读互相相同**：`nflasha2.bin.r1 == nflasha2_r2.bin.r1 == b5edce93…`；
- 会话内"第 1 次读"各不同 ⇒ 差异只在 **FAT 记账区**（FSInfo 偏移 1089/1104 的空簇计数 + FAT 表 2747/3451 等，总共 **10 个字节**）；
- 按 FAT 链把 `/setting` 全部文件抽出来比对：**除 `.hasp`(88 B) 和 `.etools`(4096 B) 外全部逐字节相同**（含 `Backup.bin`/`Backup.bak`/`psd.bin`/`kemco.txt`/`facerec*.bin`）。
⇒ `/setting` 上 `.hasp`/`.etools` 是**相机自己在写的活动文件**（每次 USB 会话都动），所以 a2 的"整卷两次一致"永远做不到；**文件级备份是稳的**。结论：a2 备份可用，但**要按文件取**，并在写阶梯前后各取一次做 diff。

### 3.1 机身 `/usr`(nflasha15) 是不是 2.00 原厂未改？——**是**
- 机身 a15 的**前 239,982,592 B** 与包内参照 `firmware.tar_unpacked/0700_part_image/dev/nflasha15` **sha256 完全相同**（`861b38b033c25094…`）；余下 74,590,208 B 全 `0x00`（包里没有这段）。
- 逐文件对照（机身 = FileControl 读回；包内 = `nflasha15_unpacked/`，已解密）：

| 包内 `/usr/` 路径 | 包 sha256 | 机身 sha256 | 判定 |
|---|---|---|---|
| `bin/crypter.elf` | `5721d6f3147d54ff…` | `5721d6f3147d54ff…` | **SAME** |
| `bin/udtrbody.bin` | `b0b344292be92fea…` | `b0b344292be92fea…` | **SAME** |
| `bin/up.sh` | `03a70fd0d0ef269c…` | `03a70fd0d0ef269c…` | **SAME** |
| `lib/libupdaterufp.so` | `881c9a54e0bafa16…` | `881c9a54e0bafa16…` | **SAME** |
| `lib/libupdatertalk.so` | `5a22e281c8ae0cac…` | `5a22e281c8ae0cac…` | **SAME** |
| `lib/libupdaterufunc.so` | `61a01288a888352c…` | `61a01288a888352c…` | **SAME** |
| `lib/libupdatercommon.so` | `a6b6bf200dad1af6…` | `a6b6bf200dad1af6…` | **SAME** |
| `lib/libupdatermedia.so` | `5a3cacedee7f669d…` | `5a3cacedee7f669d…` | **SAME** |
| `lib/libJiritsu.so` | `f1329a56b5134f01…` | `f1329a56b5134f01…` | **SAME** |
| `lib/libsencore.so` | `e6936d8b53d1dc30…` | `e6936d8b53d1dc30…` | **SAME** |
| `bin/sen.elf` | `5d58053f930ef387…` | `5d58053f930ef387…` | **SAME** |
| `bin/change_mode.sh` | `44a2c60b43b172e9…` | `44a2c60b43b172e9…` | **SAME** |
| `bin/us_remove_modes.sh` | `90a56f5b3d6e1a30…` | `90a56f5b3d6e1a30…` | **SAME** |

（注意：包里的 `0700_part_image/dev/nflasha15_unpacked/bin/crypter.elf` 的 MD5 与包里"密文"版不同——包里 0700 段是加密体，`_unpacked/` 是解密后的真身。机身 `/usr` 上的是解密体，所以上表才 SAME。）

### 3.2 nflasha4（`partinf` 里叫 "MPR Flash Backup"，12 MB）——**没有被擦空**
字节画像：`0x00` 12,051,288 / `0xFF` 421,589 / 其余 10 万+ 个非零散段（531,624 个非零字节）。
开头不是 MBR/FS 签名，而是表头：
```
0000  43 4d 4d 65 58 00 58 00 81 00 00 00 00 01 03 ff   "CMMex\0X\0" + 三元组表(addr,len,flag)
0020  b2 00 00 00 00 05 07 ff | ff ff ff … (空槽用 FF 填)
```
⇒ **"每次官方更新都 erase nflasha4" 这条假设不成立（至少 2.00 之后它不是全 0/全 FF）**：里面现在仍有 `CMMex` 结构的表 + 数据（0x98 起还有一批 `xx xx 00 03 ff…` 记录）。写阶梯里"反正会被擦"当安全垫的说法要降级。
（本轮只 dump、没解读 `CMMex` 语义。）

### 3.3 nflasha10（/tmp，FAT16，前 0x600 是 MBR 壳）与 nflasha23（PMBP）
- **nflasha10**：FAT16（OEM 串 `mkdosfs`），boot sector 在 **偏移 0x600**（sector 3），前 1536 B 是带 `55 AA` 的 MBR 壳（无分区表项）。根目录内容（=运行时 `/tmp`）：
  `config.spec(0B,空) images/(空) kikilog.dat(1957888) mtab.dat("../proc/mounts") nsswitch.conf(261) protoc.conf?(2859) services(19666) toprc(617) resolve.conf(34) uipc_set…txt(48526) `**`jiritsu/`（目录存在，但 FAT 链显示为空）**。
- **nflasha23**：不是 FAT 起始，前 0x1c0 全 0；`0x1c0` 有 `…A` + `55 AA` + 引导壳 + `FAT12 "NO NAME"` 影子，实内容是 **PMBP 的 `PMHOME / INFO / LICENSE`** 目录（0x1000）和一批 license 文本（`CFG80211TXT CLIBRARYTXT EULA PDF GPL_LGPLTXT IW TXT LIBNL3 TXT WPASUBCM TXT DHCP TXT EXPAT TXT GLIBC TXT JEMALLOC TXT LIBCURL TXT LIBEVENT TXT LIBPCAP TXT LIBSSH2 TXT NCURSES TXT OPENSSL TXT PCRE TXT TCPDUMP TXT ZLIB TXT`）⇒ PMBP 里装的是 **Linux 侧 license/EULA 资源**，不是分区表。
- **nflasha6（Jiritsu 工作区，16 MB）**：有 4,408,731 个非零字节、FAT 根为空 ⇒ **有历史数据（deleted/未挂）但没有在用的 libJit.so**。
- **nflasha13**：FAT16，含 `/history/UPDATE.LOG`(689 B) 与空目录 `/hash`。`update.log` 原文（节选）：
  ```
  [20110101 00:00:01] Updater: START. MODE=1 Serial
  [20110101 00:00:02] Base/Body Version: 100.101.014
  [20110101 00:00:02] EDISX START. → 00:00:03 EDISX END.
  [20110101 00:00:09] Darwin update START → 00:00:37 END
  [20110101 00:00:50] PFORMAT START → END ; DDR Training data update done
  [20110101 00:00:52] Updater: END. FIRMUP OK!
  [20110101 00:11:44] Updater: START. MODE=3 … Darwin update …
  ```
  ⇒ 本机历史上至少两次官方更新（MODE=1 走了 `edisx`+`pformat.elf`＝连 eMMC boot 分区都格式化过；另一次 MODE=3）。**注意 `MODE=1` 按 `us_mkfs.sh` 的表是 `PRODUCT=1`，属破坏最大那一类**；而 2.00 那次没留名（日志里没有 2.00 版本行）。

### 3.4 nflasha1（**唯一没出厂参照**的那个，现在有整机备份了）
FAT12/16 8 MiB，内容只有：
```
/boot/INITRD.IMG   4,812,800 B  md5 f4876456e026e0efe929592aeecb738b
/boot/VMLINUX.BIN  1,697,076 B  md5 7bb785fecb3161570c8fc2d7851a44a9
/boot/KEMCO.TXT    1,062 B      md5 1c5c0bab64c41162fe3af306815a0867   (console=ttyAM0,115200n8, cfg.uart=15 ⇒ 串口是活的!)
/boot/LOADADDR.TXT 33 B         md5 7911fe23c7d2327231d399f4ab98ea17   (与 2.03 一致)
/P1CHKSUM          105 B
/DAT2 4 B = 19 00 03 91   (= 机型码 91030019，与 mock 假设一致)
/DAT3 4 B = 00 00 00 00   (region 0)
```
- `p1chksum` 原文（**公开渠道第一次拿到**）：
  ```
  a6d9d7695e66a1301ca8f2a29eb42aea  ./boot/vmlinux.bin
  0f00bf40c7d13f84cf9abf8c068c5f7a  ./boot/initrd.img
  ```
  **但它对不上本卷里的 boot 文件**（我们算的是 `7bb785fe…` / `f4876456…`），也不是 2.03 的 `0dcd3b91…`/`bb50bfb5…`，也不是 nflasha3 的 `a73bf8a7…`/`ca8ae5d1…`；a1 整卷里找不到这串 ASCII 之外的第二处，也不是二进制形式。
  ⇒ 要么 `p1chksum` 校验的是"别的卷/别的时刻"的 boot 文件，要么 boot 链根本不按它校验。**这是路线 A（改 initrd）最大的未知点**，必须在改 a1 之前钉死。
- 与 2.03 的 a1（`work/v203/nflasha1_203.bin`）比：**66 个 64 KB 块里只有最后 7 块（尾部填充）相同**，前 7.7 MB 全不同 ⇒ 卷结构相同、内容随版本变。文件级：`loadaddr.txt` 与 2.03 完全一致，`kemco.txt` 同尺寸(1062)，`vmlinux/initrd` 随版本不同 —— 没有"被改过"的迹象，但 **A7C 2.00 包里没有 a1，缺一份 2.00 参照**（下次可从 2.00 升级器 FDAT 里取）。
- 好消息：a1 里 `kemco.txt` 是 `console=ttyAM0,115200n8 / cfg.uart=15`（**不静音**），而 `/setting/kemco.txt`（1905 B，运行系统用的）里是 `console=ttynull` —— 即 **boot/updater 阶段串口有输出**，值得接一条 USB-TTL。

---

## 4. Jiritsu 区现状（关系到"路线 B 能不能直接写 libJit.so"）

- `MOUNT(0x4002)` → status 0；`GET_VERSION(13)` → **`0x10000006`**；`GET_FILE2 /tmp/jiritsu/libJit.so` → **`0x10000006`**（不是 ZV-E10 的 130）。
- `/tmp/jiritsu`（nflasha10 上的目录）**存在但为空**；`/tmp/jbusy` 不存在；`nflasha6` 里没有在用的载荷。
⇒ **机身上现在没有任何 Jiritsu worker**：既没有 `libJit.so`，也没有原厂 `tmmc.jit/DIAC.csv/jinit/jcount`。
⇒ L1 报告里"原厂 worker 还在"不成立。下一步要注入就得**从零写入**（`write2/0x4010 → /tmp/jiritsu/libJit.so` 触发 dlopen），同时要知道**没有原厂 worker 可以备份**（nflasha6 里那 4.4 MB 非零数据是唯一"可能是原厂残留"的东西，值得先按文件抽一遍再决定）。
⇒ `0x10000011 (jiritsu running)` 也不会出现（无 `jbusy`），MOUNT 幂等风险低。

---

## 5. `/setting/updater/` 旗标状态（B/C 都查了）——**没有"旗标炸弹"，但有地雷的脚印**

实时读：`comp`=0 B（在）、`dat4`=`00 02`（=2.00），`mode/mode1..mode6/uincomp/debug` 全部 130（不存在）。
从 a2 dump 解 FAT 目录项（含被删项 + LFN + DOS 时间戳；注意 FAT 时间没有亚秒，全部是 2011-01-01 这个更新器 epoch）：
```
/setting/updater/   (目录 created 2011-01-01 00:00:02)
  COMP   0 B   c/m 2011-01-01 00:13:16          ← 现存（LFN "comp"）
  DAT4   2 B   c/m 2011-01-01 00:13:16  00 02   ← 现存（LFN "dat4"）
  MODE   0 B   c/m 2011-01-01 00:11:42          ← 【已删除】短名 + LFN 都被 0xE5 抹掉，LFN 残片解出 = "mode"
/setting/MODE/      (目录 created 2011-01-01 00:00:52)
  (已删除) 3 B 内容 `30 36 0a` = "06\n"，LFN 残片解出 = "mode"  ⇒ 就是 change_mode.sh 的 /setting/mode/mode?（见下）
```
对照 `nflasha13 /history/update.log` 的时间线（同一个 epoch）：`00:00:01 Updater START MODE=1 … EDISX … PFORMAT … 00:00:52 FIRMUP OK`，第二次 `00:11:44 Updater START MODE=3 … 00:12:19 Darwin END`。
⇒ 那个被删的 `mode` 旗标是在**第二次更新**（MODE=3）里 00:11:42 建立、00:11:43 被删；`COMP`/`DAT4` 则写在 00:13:16（更新之后，像"完成旗标 + 版本戳"）。**`mode` 到底是谁删的（更新链自己 vs `us_remove_modes.sh`）未定**，但至少说明这台机器**经历过"置 mode → 重启进更新模式"的完整循环**。
判读：
1. **现在 `/setting/updater/` 下没有任何 `mode*` 旗标 ⇒ 没有"下次开机进更新模式"的地雷**（`us_remove_modes.sh` 当年清过，或者更新链自己清过）。
2. 但 `up.sh func_verskip()` 会 `touch mode mode6`（`up.sh` line 41），`func_usermode()` 只 `touch mode`（line 27 分支），line 102 是 `touch mode mode1 mode4` —— **`mode6` 就是 VERSKIP=`edisx`+`-m full` 那颗雷**；`us_remove_modes.sh`(52 B) 就是拆雷工具：`rm -f /setting/updater/mode*`。
3. `/setting/mode/` 里那个被删的 3 字节 `"06\n"` 是 **`change_mode.sh` 的 boot 级开关文件**（`/setting/mode/dmode`，`0..6/a-f/10`，`6` = "kernel→infra(不分立驱动)→LIRO→appFw"；LFN 残片显示名字里含 "mode"，与 `dmode` 一致）。它**已被删除/目前不存在**（`/setting/mode/` 是空目录）⇒ 目前走默认（3）。**注意：`change_mode.sh` 在文件不存在时会先 `echo > dmode` 建空文件**，下次上串口/服务菜单时别顺手跑它。
4. `us_crc32sum_appli.sh`（在 nflasha1 的 updater 里，本轮没 dump 到它）按笔记会 `touch mode+mode6` ⇒ **任何官方刷之后第一件事是重读 `/setting/updater/`**（本轮给出可复用命令）。

---

## 6. 写阶梯下一步：该改哪个文件 / 风险点（本轮证据支撑）

1. **优先路线 B（Jiritsu 注入）**，原因没变、且更硬了：`/usr` 与 2.00 包**逐字节一致** ⇒ 任何改动都是显式改动；而 `up.sh`/`crypter.elf`/`libupdater*` 全在 `/usr`，**FileControl 现在能读写 `/usr/*`**（本轮证明读；写是同 PFUNC 的 code=1，风险另计），不必先碰 boot。
2. **注入点**：`SET_FILE2(0x4010)` 写 `/tmp/jiritsu/libJit.so`（同芯片 camtool 已证会 dlopen）。**当前 `/tmp/jiritsu` 空 ⇒ 没有原厂 worker 可备份**；`nflasha6` 已整机备份（`b9d759a7…`），写之前先把它按文件解一遍。
3. **别改 a1**：`p1chksum` 与 a1 里 boot 文件的 MD5 对不上（§3.4）⇒ 改 `initrd.img` 是否要同步改 `p1chksum` 目前**未知**，而且 A7C 2.00 没有 a1 参照。要改 a1 先拿到 2.00 的 a1（从 2.00 升级器 FDAT/`0400_updater`）。
4. **a2 的备份纪律**：整卷两次读永远不一致（`.hasp/.etools` 在写）⇒ **按文件抽 + 记 sha**（本轮已有全表），改旗标只写 `/setting/updater/`，且**每次刷后检查 `mode6`**。
5. **a4 不是"必然被擦"**（§3.2）⇒ 如果哪一步真触发 `ud_lerase /dev/nflasha 4`，`CMMex` 那份表可能真丢，别再当安全垫。
6. **串口可用**：boot 阶段用 a1 的 `kemco.txt`（`ttyAM0 115200`），运行阶段才被 `/setting/kemco.txt` 静音 ⇒ 接 USB-TTL 能在"下次启动读旗标"这个未知点上直接看到证据。
7. 待补的小口子（成本低）：`/tmp/uipc_settings.txt` 之类真名（LFN 没解全）、`/setting/updater/mode` 的历史 LFN 全名、`/PMBP` 与 `/wbi(nflasha5)`、`/android/system(nflasha16)`、`/log(nflasha11)`、以及 nflasha1 里 `sauu`/`mf`/`VerificationKey.pem` 的原文（从 a1 initrd/CRAMFS 解，已有脚本 `work/v203/cramfs_unpack.py`）。

---

## 7. 本机文件清单（都在 `work/l2-camera/`）

```
nflasha1.bin{,.r1}  nflasha2.bin{,.r1}  nflasha2_r2.bin{,.r1}  nflasha4.bin{,.r1}
nflasha6.bin{,.r1}  nflasha10.bin{,.r1} nflasha13.bin{,.r1}   nflasha15.bin{,.r1}  nflasha23.bin{,.r1}
SHA256SUMS                     # 9 个 .bin 全 OK（本机 shasum -a 256 -c 校验通过）
dump_nflasha{2,4,10,15,23}.log # 远端 dump 日志（含 sha256、长度核对、fs 指纹）
probe2/                        # 26 个 FileControl 读回文件 + path_matrix.log + path_matrix_all.log(81 条表)
fsview/                        # 从 a1 抽出的 boot/{initrd.img,vmlinux.bin,kemco.txt,loadaddr.txt}、p1chksum、dat2、dat3
PROBE2.md                      # 本文件
mount2.log  fc_probe.log  probe2b.run.log   # 鉴权/帧实验/整轮日志
```
远端：`~/a7c-jiritsu/work/l2/`、`~/a7c-jiritsu/probe2/`、`~/a7c-jiritsu/wrap2.sh`、`~/a7c-jiritsu/dump_ladder.sh`、
`~/a7c-jiritsu/tools/{probe2_paths.py,probe2b2.py,probe2b3.py,probe2b4.py,fc_probe.py}`、
`~/a7c-jiritsu/tools/jiritsu_send.py`（**已打 padding 补丁**，原件在 `jiritsu_send.py.prepatch.bak`）。

---

## 6. 更正（主会话复核，2026-10-23）：§3.4 的"`p1chksum` 对不上"是**本轮解析自己的 bug**，不是未知点
复核方法（可复现）：`work/l1-camera/fat12.py`（卷起点 = 0；BPB@0x0b：bps=512、spc=32、reserved=1、root=512 项 ⇒ FAT1@0x200、FAT2@0x4200、根目录@0x8200、数据@0xc200）对 **L2 的 `nflasha1.bin`** 现场重抽：
```
/boot/vmlinux.bin  cluster=298 chain=[298,299,…]  len=1,697,076  md5=a6d9d7695e66a1301ca8f2a29eb42aea
/boot/initrd.img   cluster=4   chain=[4,5,6,…]    len=4,812,800  md5=0f00bf40c7d13f84cf9abf8c068c5f7a
```
而 `p1chksum` 原文正是这两行（`a6d9d769… ./boot/vmlinux.bin`、`0f00bf40… ./boot/initrd.img`）⇒ **精确复现**；并且 `work/l1-camera/` 那份（另一轮、不同会话 dump 的 a1，sha256 同为 `82e1b199a8e80531…`）与本次抽出的**逐字节一致**（`cmp` 通过）。
⇒ 本轮 §3.4 里那些大写名（`VMLINUX.BIN`/`INITRD.IMG`）是 8.3 短名，且它算出的 md5 来自**错位的数据窗口**（a1 是裸 FAT 卷、没有 0x200 卷头，不像 nflasha6 那样有前导）。所以：
1. **`p1chksum` 是自洽的**：它就是 a1 里这两个 boot 文件的 MD5 清单，"校验的是别的卷/别的时刻"这一猜测**作废**。
2. ⇒ **改 a1 的 initrd/vmlinux 时必须同步改写 `p1chksum`**（105 B 文本，两行 md5 + 路径）；这仍然是"改 boot 链"路线上的**必做项**，而不是未知数。谁读它（EXBL 还是 loader2）留作后续（可用 QEMU/串口验）。
3. 顺带把 §3.4 的 `DAT2 = 19 00 03 91` 与 mock 假设一致这点保留（有用）。
