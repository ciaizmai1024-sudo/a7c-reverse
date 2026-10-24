# Round 9 FINDINGS — 分区表被接受：`/dev/nflasha*` 全部出现，`mount /dev/nflasha2` 通过，a15 读回哈希与真机一致

## ① MMC 轨迹结论（P0）
全命令轨迹（`r9_base.trace`，未改镜像 a7c_emmc.img，对照基线；sd.c 现打印 ZCMD/CMD6/EXTCSD/SDREAD/SDWRITE）：
- 驱动全程只用 **USER 分区（p=0）**；**没有任何 ext_csd 分区选择**：CMD6 仅 1 次 `acc=1 index=161 value=1`
  （非 172/179/175-183），`PARTITION_CONFIG(179)` 保持 QEMU 默认 0x8（仅 boot-ack），无 GP/ERASE 写。
- 全部读（LBA 原值，arg 字节）：
  - CMD23(cnt=8)+CMD18：**USER LBA 0..7**（加载器扫 4 KiB）
  - CMD17：**USER LBA 0**（probe_post 读 512 B 表）
  - 之后是分区数据读（a2 vfat：USER 0x800000+ 等）。**无 sector 0 以外地址、无 boot/GP 读、无 CMD0 boot 读**。
- **Round 8 的"表在 0x400000"是错位**：sd.c 的 `ZZSDREAD addr=` 打印的是 **加过 boot 前缀之后** 的值
  （bionz.c 已把 `boot_size=2MiB` patch 进 QEMU，USER 读 = 文件偏移 + 0x400000）。真实位置 = **USER LBA 0
  （USER 字节偏移 0，即 partinf 之前那 64 KiB EXBL/头区域的第一 sector）**。
- 推论：真机上驱动同样只读 USER LBA 0 ⇒ 真机 eMMC 的 USER 0x000000–0x000200 就是分区表所在
  （真机 a1 dump 从 0x10000 起，本来就没覆盖到它——这解释了 Round 8 在 a1 里找表 0 命中）。

## ② 表格式（P1；反汇编推得，无 DWARF——emmc.ko 无 .debug_*；置信度高，QEMU 实测通过）
`emmc.ko .init.text emmc_blk_plat_init+0x678..0x69c` 把字面值存进 kmalloc(0x218) 的 ptbl_info：
- **+0x000：512 B 表缓冲（设备读回来的表就放在这里，校验/条目都指向它）**
- +0x200 ptbl_magic = **0x36343238 = ASCII "8246"**（字面池、无 reloc ⇒ 是值不是指针）
- +0x204 ptbl_version = **0x30302e31 = ASCII "1.00"**
- +0x208 ptbl_part_max = **30**；+0x20c sz_bytes = 512（probe_post BUG_ON）；+0x210 in_sector；+0x214 in_part=0(USER)
- 校验（probe_post 0x7eb0）：`buf[0]==magic && buf[4]==version && buf[8]（n_partition）<=30`，否则 "partition table invalid"
- **设备上表 = 512 B**：hdr 0x20 B {magic,version,n_partition, pad=0}，条目 **从 +0x20 起，16 B/条**
  `{start_bytes, size_bytes, type, flag}`（Round 8 说条目在 +0x40 是错的）；
  flag bit0=active；start/size 必须 512 对齐；type==2⇒WBI、type==3⇒LZP；**内容可直接照抄 partinf.conf 的 4 字段 30 行**（实测通过）。
- `tbl=` 参数（insmod.sh 的 0x80000000）**在此版 emmc.ko 里是死参数**：全模块只有 1 个 xref，且在 `__param`
  段（内核写它），代码从不读 ⇒ 不需要在 0x80000000 预填 RAM 表。
- 生成器：`mk_nflasha_ptable_r9.py`（本目录），产物 `nflasha_ptable_r9.bin`（512 B，可直接十六进制看）。
- QEMU 镜像布局：文件 = [boot0 2MiB][boot1 2MiB][USER...]；表写文件偏移 0x400000。
  现成镜像：远端 `~/qemu-a7c/a7c_emmc_pt4.img`（4 MiB 前缀 + Round7 镜像 + USER LBA0 处写表）。

## ③ `/dev/nflasha*` 出现（P2）✅
`r9_pt5.ser`：`nflasha: nflasha1 nflasha2 nflasha3 nflasha4 nflasha5 nflasha6 nflasha7 nflasha10 nflasha11 nflasha12 nflasha13 nflasha15 nflasha16 nflasha17 nflasha18 nflasha23`
（正是 partinf 中 size>0 的 16 个；`partition table invalid` 消失）。
`/proc/partitions`（`r9_diag5.ser`，批量诊断 initrd `parts/initrd_diag.img`）：
major **252**：`nflasha`=252:0（整盘 1320960 KiB）、nflashaN=252:N、**nflashaB0/B1=252:126/127（各 2 MiB = QEMU boot0/boot1 前缀）**；
`ls -l /dev/nflasha{1,2,5,11,15}` 均为静态节点 252:x 且能读。

## ④ `mount /dev/nflasha2` 与 updater 新失败点（P4）✅ 过了
`r9_pt5.ser`：挂载 `/dev/nflasha2`（vfat，USER 0x800000 = 真机 a2 dump）**成功**，不再有 Error 72/73。
链条新走向：`backup.ko`(Backup_load=1) `backup_init() error (file_load)` → I/O error ⇒
`osal_ulogio/dmm/i2c/usb_portMonitor/usbg_sen` 全缺 `Backup_*` 符号；`get_power_IC_type: Backup_read() error -1` ⇒ `Power IC type : 255`；
继续到 `[VERSION] 100.101.014 / MODE=0`，最终 **sauu 段错误（page translation fault @0xffffffff）进 kernel exception monitor**。
新卡点=backup.ko 的 file_load（它没发任何 eMMC 读——失败在 VFS/文件层，疑似读 /setting/Backup.bin 相关；真机 /setting/Backup.bin 已 dump 过：`work/l2-camera/probe2/_setting_Backup.bin.bin`）。诊断 run 里 `mount -t ext2 /dev/nflasha15 /mnt2` 与 `mount -t vfat /dev/nflasha2 /mnt3` 都成功（仅 busybox 缺 `head`）。
B 线旗标（root/IAMLDUDWRT→PROD）未测。

## ⑤ a15 读回哈希 vs 真机 ✅（本 round 最高价值结论之一）
QEMU 里 `dd if=/dev/nflasha15 bs=65536 count=4 | md5sum` = **c325b0e201ddabb16c6c2b0eee5f0834**
真机 dump `work/l2-camera/nflasha15.bin` 前 256 KiB md5 = **c325b0e201ddabb16c6c2b0eee5f0834** ⇒ 完全一致。
（附带：QEMU 里 `dd if=/dev/nflasha2 bs=65536 count=1 | md5sum` = 810baf7da8d739fa7c4315c95e049e31。）
⇒ **真机 dump 数据 → 镜像 → QEMU eMMC → f_sdh30/emmc.ko 驱动 → 内核块层 → 用户态 dd** 整条读路径可信。

## ⑥ 真机下一步该 dump 什么
1. **eMMC USER 0x000000–0x010000（64 KiB，"a0/EXBL 区"）**：含本分区表(0x0–0x200)+EXBL+p1chksum——现在格式已知，比对即真机表的 ground truth（成本最低、优先级最高）。
2. **eMMC 硬件 boot 区 boot0/boot1 各 2 MiB**（=nflashaB0/B1，loader/pformat 与 Backup 备份载体；loader_writer.sh 会写 boot0）。
3.（可选）RPMB 区（QEMU 未模拟，updater 链暂未见用到）。

## ⑦ 偏离清单
1. `parts/kemco_a1_c1.txt`（amba2.console=1）沿用 Round 8（拿真串口输出）。
2. **QEMU sd.c 新调试打印**（ZCMD/ZCMD6/ZEXTCSD/ZZSDWRITE/ZBOOTREAD；ZZSDREAD 保留）：
   sd.c md5 `e13776d00063a02d3adbd2aef74e89a5`；新 qemu-system-arm md5 `d4103e35914e0609df6f57367c6e7efd`。
   **bionz.c 未动**，md5 仍 `87febf2ba7fc4f19aa05ed1829edf804`。上一轮 sd.c 备份：`/tmp/sd.c.round8state`（更早 `/tmp/sd.c.orig`）。
3. 镜像：新建 `a7c_emmc_pt4.img` = 4 MiB boot0/boot1 前缀(zeros) + Round7 a7c_emmc.img + 512 B 表@USER LBA0
   （原 a7c_emmc.img 未动）。pt4 内部所有分区数据相对 Round7 镜像整体 +0x400000（文件偏移），与 QEMU 的
   boot 前缀映射一致；这是与 Round 8 镜像的最重要偏离。
4. initrd：诊断 run 用 **重建 cramfs** `parts/initrd_diag.img`（7z 解包原 initrd → mknod 重建 /dev 节点
   nflasha=252:0/1..30、dnflasha=252:128+n、console/null/zero → 替换 usr/bin/insmod.sh 为诊断脚本 →
   `mkfs.cramfs` 重建；7z 解包报 2 个 sub-item 错误，个别 dev 节点以普通文件形态落盘后由 mknod 补齐；
   原 `parts/initrd.img` 未动）。**未做原地字节 patch**（原因：该 cramfs 是压缩版 "Compressed ROMFS"，
   明文搜不到 insmod.sh 内容，原地 patch 不可行）。
5. 内核/启动：与 Round 8 相同（V3h + `-initrd` + if=mtd drive）。
6. 时间盒内未做：B 线（PROD 旗标）；backup.ko file_load 根因；amba2 RX 未修。

## 文件清单
- `r9_base.trace` — 基线 MMC 全命令轨迹（未改镜像）
- `r9_pt4.ser` — 第一次尝试（表放 0x400000，仍 invalid）——定位 boot 前缀错位的关键证据
- `r9_pt5.ser` / `r9_pt5.trace` — 成功 run（表在 USER LBA0）串口 + MMC 轨迹
- `r9_diag5.ser` — 离线批量会话（/proc/partitions、ls /dev、md5、mount）
- `nflasha_ptable_r9.bin` + `mk_nflasha_ptable_r9.py` — 表与生成器
- `initrd_diag.img` — 诊断用重建 cramfs
- 远端镜像：`~/qemu-a7c/a7c_emmc_pt4.img`；运行脚本 `~/qemu-a7c/run_r9.sh` / `run_r9d.sh`（usage 见文件头）；
  远端副本 `~/qemu-a7c/results_round9/`
