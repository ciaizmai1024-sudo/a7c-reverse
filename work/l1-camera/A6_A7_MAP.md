# A6 / A7 机身 dump 解析报告（A7C 一代, 离线）

日期：分析于 dump 文件（`work/l1-camera/`，抓取时间戳 Oct 23 20:12）。
所有解析纯离线（手写 FAT12 + ext2 读取器，本机无 mtools/debugfs）。

## 0. 输入文件核验（.r1 重复抓取一致）

| 文件 | 大小 | SHA256 |
|---|---|---|
| nflasha6.bin | 16,777,216 | `b9d759a7a09f210f28df1380c7f7758c08d456b6e0cf3ac8f7eccc52875187e8` |
| nflasha6.bin.r1 | 同上 | 同上（一致）|
| nflasha7.bin | 8,388,608 | `c2b7af2f9f02e57319201af13362e0682c96e3520229a388a5293621d6da6107` |
| nflasha7.bin.r1 | 同上 | 同上（一致）|
| nflasha1.bin | 8,323,072 | `82e1b199a8e80531730b220899ff1a1ba9ba91a60d3de7d49a67546959b79a1a` |

注：本次 dump 只有 a1/a6/a7；**nflasha15（/usr, 300MB）未 dump**。

## 1. nflasha6 = Jiritsu 专用 vfat（FAT12）

### 1.1 BPB（boot @0x000，OEM "mkdosfs"）
- bytes/sec=512, **sectors/cluster=32 (16 KiB cluster)**, reserved=1, **FAT copies=1**, root entries=512, media 0xF8, FAT size=3 扇区, total16=32768 扇区(=16 MiB), vol-id=0x4D1E6E83, label 空, FSInfo: FAT12。
- FAT12 判定：数据簇数 = (16MiB−0x4800)/16384 = **1022** (<4085) → FAT12。
- 布局：FAT @0x200 (1536 B)，根目录 @0x800 (512×32 B)，数据区 @0x4800。
- 与包内 `0100_config/mount.conf` 完全吻合：`/dev/nflasha6 none vfat 16777216 16384`；`0300_partconf/partinf.conf` 注释：`/dev/nflasha6 ... (System Group Jiritsu /dev/nflasha6) 0x09400000,0x01000000`。**a6 就是 Jiritsu 分区**，相机侧由 libJiritsu `sys_mount('/dev/nflasha6','/tmp/jiritsu',0)` 挂载（见 notes/jiritsu.md §3.2）——即 **挂载点本身就是 /tmp/jiritsu，分区内部没有 "jiritsu/" 这一层目录**。

### 1.2 根目录全量条目（@0x800，共 10 条，全部 0xE5 已删除；明细见 `a6_root_entries.txt`）

| LFN | SFN(删首字母) | 起始簇 | 大小 | attr | 备注 |
|---|---|---|---|---|---|
| jiritsu.hash | JIRITSU~1.HAS | 3 | 16 | 0x20 | |
| ramdsk_libJit | RAMDSK_L~1 | 4 | (dir) | 0x10 | jiritsu ramdisk 目录 |
| **libJit.so** | LIBJIT  .SO | 5 | **409,551** | 0x21 | cdate **2019-12-13** |
| DIAC.csv | DIAC    CSV | 119 | 89,868 | 0x20 | cdate 2021-04-02 |
| tmmc.jit | MMC     JIT | 35 | 770,108 | 0x20 | cdate 2021-04-02 |
| de_FilesCam_AdjustGui | CAM_AD~1 | 83 | (dir) | 0x10 | LFN 两槽拼接 |
| Ver.txt | VER     TXT | 118 | 454 | 0x20 | |
| jcount | JCOUNT | 30 | 4 | 0x20 | |
| history.txt | HISTORY  TXT | 31 | 2,158 | 0x20 | |
| jit.log | JIT   LOG | 32 | 3,244,032 | 0x20 | |

- **FAT[2..1023] 全 0x000**：没有任何存活簇链 ⇒ 该卷按现在的状态挂载时**目录为空**（所有历史文件已被删除、簇已释放）。
- 之后根目录槽位为 0x00 终止符，无 LFN 残留在存活条目上。

### 1.3 空闲簇里的残留内容（carve；簇在删除后被复用/打乱，多数文件已碎片化）
全分区仅 1 个 ELF 魔数命中：@**0x10800**（簇 3 起点），完整 ARM32 ET_DYN，尺寸恰=已删条目 libJit.so 的 409,551 B（0x63FCF），dynstr 含 **`libJit_NB.so`**、`jiritsu_uart_thread`、`CDiAdjCtl*`、`/tmp/jiritsu/jcount`、`USB_KIKILOG_*` ⇒ 这是 **Sony 自家 400KB 完整 jiritsu worker 的整份影分身**（不是我们 6,288B 的玩具 libJit；两者 sha 不同：ours `b550c0fd...`, carved `47f614e4...`）。
其余文本区为旧 jit.log/history.txt 碎片（0x80800 起、0x460000–0x500000 大段 jiritsu 会话日志，含 `log_file("/tmp/jiritsu/jit.log")`、`sen_print_flush("/tmp/jiritsu/history.txt")`、`JIRITSU_FILE_NAME jiritsu_20210402_01_NB_SDPW_AUTO.tar.dat`、`JIRITSU_BOOT_COUNT 11/12/13/14` 等）与 hash 清单残片。

### 1.4 a6 提取清单（`work/l1-camera/a6_extracted/`）
| 文件 | 来源偏移 | 长度 | SHA256 |
|---|---|---|---|
| a6_libJit_recovered.so | 0x10800 | 409,551 | `47f614e4ec2d9cccbf7191856920510919d9a0dd5e4c3dc6187dd3a0ea986884` |
| a6_jiritsu_hashlist.txt | 0x1d4800 | 175 | `1fbd0417fd3b0db42ca459313b96f32894ce0e5b96c50c0cce94ad2277ca2ab4` |
| a6_tmmc_jit_sample.txt | 0x90800 (簇35) | 4,096 | `9690525f99905a41f017b2ce2fc93e9e1e2067a5864e7a667d9e94573bf0f2d8` |
| a6_DIAC_csv_sample.txt | 0x1e0800 (簇119) | 4,096 | `17a7fc397ac2d335071ef2cf2f014dff71ca80292d7287b32ff96203216b6ca1` |
| a6_jitlog_history_sample.txt | 0x484000 | 8,192 | `964ba75fcaecd4b4a0da042a8f8d17259f5cfb602f85b382a65b511fbcef71d4` |

hashlist 前 300B（原文照贴）：
```
0,jiritsu_20210402_01_NB_SDPW_AUTO.tar.dat,2021040201NBSDPWAUTO
1,tmmc.jit,20210402161103
2,libJit.so,20191213190038
3,DIAC.csv,20210402161102
4,TOOLBAR_VERSION,18.04.03
5,00_
```
（jiritsu_20210402 会话与 libJit cdate 2019-12-13 互相印证。）
tmmc/DIAC 采样均从"簇 35/119 起点"读取——内容中段（非文件头），证明删除后簇已被复用，**原始小文件（jcount=4B、Ver.txt=454B、jiritsu.hash=16B）的字节不可靠恢复**。

## 2. nflasha7 = /rootfs（ext2，updater/启动 rootfs）

### 2.1 文件系统参数
ext2（magic `0xEF53` @0x438，**非 vfat**）：block=1024B，blocks=4872（fs 只占前 4,988,928B，其余 ~3.4MB 为 0），1 组，inodes=1224（已用 624），inode_size=128，inode_table @0x6000，根目录数据块 177 (@0x2c400)，s_wtime=**2021-11-14 19:41:54 UTC**，state=clean。
`mount.conf`: `/dev/nflasha7 /rootfs raw 8388608 0`；`partinf.conf`: `Rootfs 0x0A400000,0x00800000`。**a7 = 原始 ext2 镜像，挂载到 /rootfs**（更新/启动环境），不是卡（无 MS/PMBP/DCIM/AVCHD/XAVC 痕迹），也不是 /system(/nflasha3) 或 /usr(/nflasha15)。

### 2.2 文件树（完整 622 行见 `work/l1-camera/a7_ext2_tree.txt`）
顶层：`bin cert dev etc initrd kmod lens lib log mnt network(->cert) proc root sbin setting sys system tmp tmp_updater usr var version.txt`
- 多数目录为空壳（etc/system/setting/tmp/tmp_updater/usr/lib/initrd…）→ 运行时才填充的最小 rootfs。
- `/bin`：busybox(396,600B) + 符号链接家族；`/sbin/init`(28,524B ELF)。
- `/kmod/{nand,lld,dmac,emmc,ldec,devno}.ko`。
- `/lib/libc-2.11.2.so`(984,292B)。
- `/root/chassis` = `CXD90045\n`（9B，A7C 主控芯片名！）、`/root/common.src`（2,595B shell 公共库，含 `ERROR_UINCOMP=54`、`MODE_PROD/SERVICE`、`P2_DEV=/dev/nflasha2 P3_DEV=/dev/nflasha3`、`blink_error/udtr 相关 uc_portctl.elf`）。
- `/version.txt`（19B）= `39119_05.2021111501` ⇒ **与我们真机取回的 `cfg__version.txt` SHA 完全一致**（`57a441d2...`），反证 a7 dump 与真机 /rootfs 挂载内容同源，也证明当年 `cfg__*` 抓取走的就是这套文件。

### 2.3 a7 提取清单（`work/l1-camera/a7_extracted/`）
| 文件 | 大小 | SHA256 |
|---|---|---|
| version.txt | 19 | `57a441d21bef2cf7669aca113b458cb466ec7adfbb5dad1b47a6be6828afaaa4` |
| root/chassis | 9 | `a30d9500a9473383…`（内容 `CXD90045`）|
| root/common.src | 2,595 | `8b1df32b53993a93…` |
| bin/busybox | 396,600 | `a40ecc7e3fb5acb0…` |
| bin/cat / ps / hostname | 25,172 / 59,782 / 16,729 | `7d9c89c7… / bf0c5275… / e5d5fff0…` |
| sbin/init / sbin/sysctl | 28,524 / 8,562 | `170b94c1… / 004e7c97…` |
| kmod/nand,lld,emmc,dmac,ldec,devno .ko | 152,212/79,340/214,252/17,096/15,840/4,368 | `4e9a3f96… f0b2df04… 7b34a8f3… c418cd80… b3e9799d… df6eecc5…` |
| lib/libc-2.11.2.so | 984,292 | `fbbe14d19b28c91a…` |

文本类摘录：common.src 前 300B 已在正文粘贴（见提取文件）。

## 3. (c) 字节级搜索（13 个名字 × 3 dump，大小写不敏感）

| 名字 | a1 (8.32MB) | a6 (16MB) | a7 (8.39MB) | 关键位置与上下文（±32B）|
|---|---|---|---|---|
| jiritsu | **0** | **2307** | 0 | a6 全部位于已删日志区（0x80800–0xC4800、0x460000–0x500000）与 libJit ELF 字符串表；如 @0x485037: `* Ext [10] /tmp/jiritsu/history.txt`；@0x486316: `log_file[25] /tmp/jiritsu/jit.log` |
| libJit | 0 | **2** | 0 | a6 @0x1e8f1 `..._end\x00libJit_NB.so\x00GLIBC_2.4\x00GCC_3.5...`（carved ELF .dynstr）；@0x1d485c `2,libJit.so,20191213190038`（hash 清单）|
| jinit | 0 | 0 | 0 | — |
| cmd.txt | 0 | 0 | 0 | —（三块 dump 都没有；别处提到的 cmd.txt 不在 a1/a6/a7）|
| uincomp | 0 | 0 | **1** | a7 @0x113971 `/root/common.src` 内 `ERROR_INVALID_FIRMWARE=41\nERROR_UINCOMP=54\nERROR_NAND_MOUNT=72` |
| mode6 | 0 | 0 | 0 | `/setting/updater/mode6` 字串不在 dump（mode6 在 nflasha2=/setting，本次未 dump）|
| kikilog | 1 | 10 | 3 | a1@0x1640c 模块表 `gadgetcore/kikilog/massstorage`；a6@0x4be40.. `USB_KIKILOG_DELETE/GET/GET_VERSION/GET_CATECODE`（carved ELF 内）+@0x1e529c DIAC.csv 残区；a7@0x13642c `/usr/kmod/kikilog.ko`（sbin/init 内路径串）、@0x2098c0、@0x2839d5 `/dev/usb/kikilog`（devno.ko 内）|
| partinf | 0 | 0 | 0 | —（partinf.conf 只在包内 a1 区域? 本次 a1 也无命中）|
| mount.conf | 0 | 0 | 0 | — |
| nsswitch | 0 | 0 | 1 | a7@0x3f4369 在 `/lib/libc-2.11.2.so`：`[NOTFOUND=return] files\x00/etc/nsswitch.conf\x00libnss_` |
| BOOTREC | 0 | 0 | 0 | — |
| libupdater | **4** | 0 | 0 | a1@0x17468/88/a8/c8：`libul_xml.so / libupdater0604.so / libupdatercommon.so / libupdatertalk.so / libupdaterufunc.so`（a1 FAT 内某二进制的 dlopen 名单——a1 由另一代理处理）|
| udtrbody | 0 | 0 | 0 | — |

（a15 未 dump，故 a15 内的 libJiritsu.so 与 `/usr/lib/appFw.so` 等不参与本轮搜索。）

## 4. 判定 a–d

**(a) a6 上有无 `jiritsu/` 目录？** 没有也不需要：a6 **本身就挂载为 /tmp/jiritsu**。a6 根目录历史上有 10 个条目（jiritsu.hash, ramdsk_libJit/, **libJit.so(409,551B, 2019-12-13)**, DIAC.csv, tmmc.jit, de_FilesCam_AdjustGui/, Ver.txt, jcount, history.txt, jit.log），**全部已删除、FAT 链已清零 ⇒ 现在挂载是空目录**。没有 cmd.txt/uincomp/kikilog 等别人留下的活文件。

**(b) a7 是什么？** ext2 原始镜像（非 vfat），对应 `mount.conf` 行 `/dev/nflasha7 /rootfs raw 8388608 0`（partinf 注释 "Rootfs"）。内容 = busybox+init+libc+kmod(nand/emmc/lld…)+updater 公共脚本(/root/common.src)+`/version.txt`，即**更新/早期启动用的最小 rootfs**；不是存储卡（无 MS/PMBP/DCIM/AVCHD/XAVC），不是 /system 也不是 /usr。

**(c)** 见上表。

**(d) 首次写 libJit.so 是全新创建吗？** **是（针对"当前文件系统状态"）**：a6 无存活目录条目/FAT 链，`ls /tmp/jiritsu`（挂载后）应为空；我们的 WRITE 会在 8.3 短名表新建 `LIBJIT  .SO`。但**磁盘空闲簇里存在旧的 libJit.so 完整镜像（含 Sony 400KB `libJit_NB.so` worker）**——别的机型"机身自带 libJit.so"的先例就在这台机器上出现过（工厂 2019-12-13 会话写入，后删除）。

**(4) 需要相机侧先 mkdir /tmp/jiritsu 吗？（推测/待实测）** 按 notes/jiritsu.md §3.2 `adj_cmd_set_file2@0x5b00` 机器码级结论：mode=0 会先 `sys_mount('/dev/nflasha6','/tmp/jiritsu',0)`，随后 **`sys_dir_create2(path)` 自动创建目标路径的父目录**，再 `open(path,0x241,0600)+write`；写 `libJit.so` 前还检查 `sys_file_chk_exist('/tmp/jbusy')==0` 并对写入内容做 `dlopen+dlclose` 校验，配额 `sys_get_dir_size('/tmp/jiritsu') ≤ 0x500000`。⇒ **我们不需要自己创建目录**：用 cmd 15(set_file_path, mode0) 存自定义路径 + cmd 16(set_file2, mode=0, id=0xff, flag=0) 写 `/tmp/jiritsu/libJit.so`，挂载和目录创建都由相机做。注意点（推测/待实测）：(i) 我们的 libJit.so 必须是能被 dlopen 的 ARM32 ET_DYN，否则状态码 0x10000000；(ii) 5MiB 配额按目录已用量算，空卷无碍；(iii) mode=0xff 只做 DMM 登记不写文件，别误用；(iv) FileControl WRITE（若指 16 之外的 7/set_file）同样会挂 a6 并按 area-id 表落盘（§3.5）。

## 5. 下一轮真机只读探针清单（建议顺序）

1. `jiritsu(cmd 2=MOUNT)` 或任何 mode=0 的 GET 触发挂载后：`get_file2 mode=0 id=<area>` 逐个取包内 area id（3=DIAC.csv 等）确认 id 表行为。
2. `get_file2(17, mode=0, id=0xff, flag=0)` + 先 `set_file_path(15, b'\0'+path+'\0')`，读回：
   - `/tmp/jiritsu/jiritsu.hash`（判断当前是否有新工厂会话写入；预期不存在）
   - `/tmp/jiritsu/jit.log`、`/tmp/jiritsu/history.txt`（确认运行日志是否实时存在）
   - `/tmp/jiritsu/../../rootfs/version.txt` 与 `../../root/chassis`（验证 `..` 归一化到 a7 rootfs 的可见性；chassis 应为 `CXD90045`）
   - `/tmp/jiritsu/../../usr/lib/appFw.so`（复核 a15 可读；本轮 dump 不含 a15）
3. `ls /tmp/jiritsu`（预期：空）与 `get /setting/updater/*`（a2 未 dump，mode6/updater.dat4 需在真机侧复核）。
4. 对 `cmd.txt`/`jinit`/`uincomp`/`mode6`/`BOOTREC`/`partinf`：三 dump 均 0 命中 ⇒ 这些字串只可能在 a2(/setting)、a3(/system)、a15；下轮 dump a2+a3 或先用 GET_FILE2 路径穿越读取（`../../setting/...`）。
5. 写探针（最后）：`set_file2(mode=0, id=0xff)` 写 `libJit_test.so`（合法 ET_DYN）→ 观察状态码 0 与 dlopen 校验；确认 `/tmp/jbusy` 语义；写完用 cmd 18 delete2 清理。

## 6. 产物文件
- `work/l1-camera/A6_A7_MAP.md`（本文）
- `work/l1-camera/a6_root_entries.txt`、`a7_ext2_tree.txt`（622 行完整树）
- `work/l1-camera/a6_extracted/`（5 个文件，哈希见 §1.4）
- `work/l1-camera/a7_extracted/`（17 个文件，哈希见 §2.3）

未改动 `notes/updater_flow.md`。遗留：a2/a3/a15 未 dump；a1 FAT 细节留给 a1 子代理（本报告只做了字串搜索）；a6 中被复用簇的原始小文件字节不可靠。
