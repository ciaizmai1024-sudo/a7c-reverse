# Round 8 FINDINGS — nflasha 分区表定位（0x400000）+ updater 交互 shell 拿到（RX 断）

## A. `nflasha` 驱动在哪、表在哪（结论 + 证据）

**A.1 GPL 树里没有 ALFReD/nflasha 驱动**（更正 round7 备忘）：
`grep -rn 'nflasha|ALFReD' ~/sony-src/linux-7c-200/linux --include=*.c --include=*.h` = **0**（只有 `fs/partitions/check.c` 的通用
`unknown partition table` 字样与 vmlinux 二进制残留）。真正的驱动是 **updater initrd 里的闭源模块**
`/usr/kmod/emmc.ko`（`license=Proprietary`，`vermagic=3.0.27_nl-rt106 SMP preempt mod_unload ARMv7` ——
与我们 V3h 内核**逐字匹配**，能直接 insmod）。`insmod.sh`：`insmod $MODPATH/emmc.ko tbl=0x80000000`
⇒ bionz.c 早已在 PA 0x20000000 放了该"信息表"（CID/CSD，`tbl_valid()` 要求 +12..+40 非零）——round7 的
`Unknown PEF1G4` 即来自它。round7 日志的 `partition table invalid` = emmc.ko 字符串（.rodata.str1.1+0x2533）。
源码路径残骸（.rodata 内）：`.../Etools-eMMC_171H/driver/src/main/{controller/f_sdh30.c,plat-uz/uz_emmc.c,common/emmc_blk.c,common/emmc_seq.c,common/emmc_proc.c}`。

**A.2 表的设备位置（本轮最硬的成果，QEMU 实测）**：给远端 `qemu-sony/hw/sd/sd.c: sd_blk_read()` 加
`fprintf("ZZSDREAD p=%d addr=%#llx len=%u")` 重编（唯一 QEMU 改动；bionz.c 未动）。启动后驱动只读：
```
ZZSDREAD p=0 addr=0x400000 len=512   ×8（0x400000,0x400200,…,0x400e00 连续 4 KiB）
ZZSDREAD p=0 addr=0x400000 len=512   （第 9 次重读）
```
⇒ **分区表区 = eMMC USER 区分区字节 `0x400000..0x401000`（4 KiB）**（p=0=user；QEMU 里 user 区 = a7c_emmc.img 的 0 偏移）。
它落在 a1 区间内（a1=0x10000..0x800000 ⇒ a1 文件内 +0x3F0000..+0x3F1000）。真机 a1 dump 该处是**乱码/密文样子**
（可能加密，也可能真机 `ptbl_in_part`≠user；probe 循环 3 个 dev_params=3 个 eMMC 硬件分区）。

**A.3 校验逻辑（emmc.ko .text 反汇编，`emmc_blk_plat_probe_post` @0x7d30，emmc_load_partition_tbl 已内联）**：
- 0x7d4c：扫 `dev_params[3]`（每项 0xc0 字节，bss）：`[e+0xbc]`!=0 且 `[e+0xac]==[ptbl_info+0x214]`（=in_part 匹配）；
  不匹配 → `"partition table not defined in any part (%d)"`（emmc_blk.c:1459）。
- 0x7dc8：BUG 除非 `[ptbl_info+0x20c]==0x200`；0x7ddc：`sz<<23` 必须溢出为 0（=512 字节或 512 扇区，二义）。
- 0x7e34–0x7e60：组 12 B 读请求表 {ptr,sector,len}，调 `emmc_seq_read`（0x7e78）。
- 0x7eb0–0x7ef8（判定点）：`buf[0x000]==buf[0x200] && buf[0x004]==buf[0x204] && buf[0x008]==buf[0x208]`
  否则 `printk "partition table invalid"`（0x7ef4）。字段名（dump_ptbl_info 字符串序）：
  `ptbl->{magic,version,n_partition}`；ptbl_info->{ptbl,ptbl_magic,ptbl_version,ptbl_part_max,ptbl_sz_bytes,ptbl_in_sector,ptbl_in_part}。
- 表项：**16 B 槽**，代码读 `[r7,#0x20]=start(字节,512 对齐校验 lsls#23；lsr#9 转扇区), [r7,#0x24]=size, [r7,#0x28]=type, [r7,#0x2c]=flag`
  （r7=base+0x20+16i ⇒ 表项在 base+0x40+16i）；`type==2` → WBI（`wb_register_device`，@0x8234 比较），`type==3` → LZP 压缩
  （`uz_emmc_lzp_part_size`，@0x7f54）；flag=0xFFFFFFFF=激活。**分区编号 = 表项位置**（partinf.conf 注释 a1..a30 顺序；
  /dev 静态节点 nflasha1..31 = **block major 252, minor=编号**，dnflasha1..31 = 252:128+n，decomp 通道）。
  devno.ko 有字符串 `nflasha/nflashaB0/nflashaB1/dnflasha`。`nflasha: unknown partition table` 只是内核 add_disk
  后 DOS 扫描（正常），分区由模块自己注册。
- 创建表：GPL 树和 updater 用户态都没发现写表路径（`pformat` 无；partinf.conf 只被
  `usr/lib/libInfraMediaCommon.so`/`libInfraFsys.so` 引用）⇒ 表由工厂/主系统侧写，updater 只读。

## B. 造表（mk_nflasha_ptable.py，已放 round8/）
输入 partinf.conf + 镜像 → 在 0x400000 写 4 KiB：hdr{magic 'PTAL',ver=1,n_partition} 于 +0x0，**同一 hdr 在 +0x200**
（满足 A/B 对偶），16 B 表项从 +0x40（start/size 用 partinf 字节值，type/flag 照抄），n=28/30 两档。
产物 `a7c_emmc_pt.img`(n=30 表+0x200 单独 hdr)、`a7c_emmc_pt2.img`（n=28，A/B hdr 全同）、`a7c_emmc_pt3.img`（hdr 全 0 + 24 表项）。
**没把握的字段**：magic 值（任意假设）、n_partition 语义（28/30 谁对）、0x400..0xFFF（备份/CRC？）、start 是设备绝对字节
还是 per-part 相对、以及 0x7eb0 比较对究竟读的是 RAM 结构还是设备缓冲——**三档全部仍报 `partition table invalid`**
（零 hdr 也报 ⇒ 被比较的内存不是（或不只是）设备 4 KiB 缓冲；很可能 emmc.ko 还要与 `tbl=` RAM 表里的
dev_params 默认表比对，真机由 bootloader 填）。**下一步该用 camtool 直接 dump 真机 0x400000..0x401000 抄格式**（若该处密文，
连带 `tbl=` RAM（0x20000000, ~0x300 B）一起 dump）。

## C1. 新表 + amba2.console=1
`parts/kemco_a1_c1.txt`（仅 `amba2.console=0→1`）⇒ **串口真出字**（round7 猜的方法成立）。
`nflasha: unknown partition table`（DOS 扫描，无害）与 `partition table invalid` 未消失；无分区注册；
`VFS: Mounted root (cramfs)` 后 updater 链自己跑起来：`insmod.sh → mount -t vfat /dev/nflasha2 /setting` 失败
（No such device or address，节点在但 minor 无分区）→ `[FIRMUP NG] Error 72/73`。

## C2. shell（拿到，但 RX 断）
`parts/kemco_a1_sh.txt`（再改 `init=/sbin/init → init=/bin/sh`+3 个空参数填充）⇒
`BusyBox v1.29.3 ash` 横幅 + `/ #` 提示符出现（`shell_session.txt`）——**QEMU 里 updater 环境的 init=/bin/sh 成立**。
但 **Sony amba2 驱动的 RX 在 QEMU 收不到任何输入**：-serial stdio（先喂/延迟喂）与 -chardev socket 三种方式都不回显、
不执行命令 ⇒ 本轮拿不到 `ls /dev/nflasha*`/`/proc/partitions`/mount 会话输出（节点是 cramfs 静态：
252:0/1..31、dnflasha=252:128+n，已从 initrd 反解确认）。RX 修复思路：QEMU pl011 的 FIFO/中断触发 vs amba2.c 的
RX 轮询/DMASR 期望；或走 `-chardev pty` + 内核 `console=` 之外的 ttyAM 口。

## D. 冒烟（R1 恢复演练第一步）
`a7c_emmc_wipe15.img`（pt3 基础上把 0xB800000 起 288 MiB 置零）：启动链失败点与未擦时**完全一致**
（nflasha2 mount → Error 72/73），**在碰到 a15 之前就死** ⇒ a15 状态此刻不影响 updater 进度；
恢复演练的真正前置条件仍是分区表被判 invalid。

## E. 真机该 dump 什么（进 BACKUP_MANIFEST）
1. eMMC **USER 区 0x400000–0x401000（4 KiB）** = nflasha 分区表区（本轮实测；在 a1 区间内，a1 dump 的 +0x3F0000 起）。
2. eMMC USER 区 **0x000000–0x010000（前 64 KiB，a1 之前的"机身头部"）**：DOS 扫描未见表，但 `ptbl_in_part` 有 3 个候选
   （eMMC 硬件 boot 分区可能性未排除；QEMU 不模拟 boot 区读，真机 dump 可顺带排除）。
3.（可选，需 camtool mem 读）RAM **0x20000000 起 ~0x400 B** = `tbl=` 信息/dev_params 源表（含 CID/CSD，可能含默认分区表）。

## 产物/偏离
- 本机 `work/qemu-a7c/results/round8/`：`FINDINGS.md`、`mk_nflasha_ptable.py`、`emmc.ko`（从 initrd 抽出，212 684 B）、
  `emmc_dis.txt/emmc_rel.txt/emmc_rela.txt/strxrefs.txt/rodataxrefs.txt`（分析中间产物）、
  `r8_c1t.err`（★ZZSDREAD 表位置 trace）、`r8_c1.ser r8_c1b.ser r8_c1c.ser r8_d.ser`（C1 三档 + D 串口日志）、
  `r8_shell_raw.txt`=`shell_session.txt`（ash 横幅+提示符）、`r8_shell2.txt`。
- 远端 `~/qemu-a7c/`：`a7c_emmc_pt.img / a7c_emmc_pt2.img / a7c_emmc_pt3.img / a7c_emmc_wipe15.img`（原 `a7c_emmc.img` 未动）、
  `parts/kemco_a1_c1.txt parts/kemco_a1_sh.txt`、`mk_nflasha_ptable.py`、`hw/sd/sd.c` 加 1 行 ZZSDREAD
  （重编 `arm-softmmu/qemu-system-arm`，2024-10-24 06:19；原文件备份 `/tmp/sd.c.orig`）。
- **bionz.c 未改**，md5 仍 `87febf2ba7fc4f19aa05ed1829edf804`（远端实测）。
- 偏离清单：①`amba2.console=0→1`（拿真串口）②`init=/sbin/init→/bin/sh`+空参填充（C2）③QEMU sd.c 调试打印
  ④`KCFLAGS=-fno-builtin-memset`/`LOG_BUF_SHIFT=17`/`BLK_DEV_RAM_SIZE=8192`（沿用 round7）。
