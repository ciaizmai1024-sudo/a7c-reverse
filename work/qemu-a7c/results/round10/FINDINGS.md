# Round 10 FINDINGS — backup.ko file_load 复现与排除矩阵；sauu 崩溃精确定位到 `mcmn_log_init`（0xffffffff 哨兵）；P5 镜像数据源清单完成

本轮 **未改 QEMU 源码**（bionz.c md5 仍 `87febf2ba7fc4f19aa05ed1829edf804`；sd.c 仍 `e13776d00063a02d3adbd2aef74e89a5`，二进制仍 Round9 的 `d4103e35914e0609df6f57367c6e7efd`）；**镜像 pt4 未改**。新增：诊断 initrd（3 个版本）+ vermagic-patch 的 a15 backup.ko。

## ① P0：backup.ko file_load —— 未修好，但根因范围被大幅收窄（E1 排除 + E2 判断）

**调用链（反汇编 `usr/kmod/backup.ko`=initrd 版，md5 `0a38eec6…`，110248B；`r10/bk_dis.txt`/`text_ann.txt` 有全量标注）**：
`backup_init()` → `backupfile_select_path()`(@5e38，helper @5cb8 构造 `<dir>/<name>.bak` 并用 `kern_path(,0x101)` 检查存在性) → `backupfile_load()`(@6684)：
`backupfile_load_file()`(@5fec：`vfs_stat` → `vmalloc(size)` → `filp_open(path,0o644,0o644)` → `vfs_read` 整文件 → 校验读满) ×2（pri/sec）→ `Data_check(buf1,buf2,0)`(@54e4，要求返回 1/2) → `backupfile_init`(@6404：再 load_file 二次 + `Data_init`) → `Data_init`(@4664：**先比较 `buf+0x0c` 与模块内一个静态版本串**，然后 `data=buf+0x100`，`records=hdr@0x10..0x13 ×6`，再调 `bl 41c0`)；任一环节失败 → `backup_init() error (file_load)` → insmod EIO(5)。

**真机数据确认（镜像侧）**：
- 镜像 a2 区（USER 0x800000）**已含真机 /setting 全部内容**（`parts/nflasha2.bin` = FULLMATCH）；其中 `Backup.bin` md5 `7a549d06…` ≡ 真机 dump `work/l2-camera/probe2/_setting_Backup.bin.bin`；`Backup.bak` md5 不同（比 .bin 晚一代：hdr@0x20/0x2c 计数 2884→2885，全文件仅 265 字节差异）。头 0x0c=**"BK4\0"**，hdr@0x10/0x14=0x2ee/0x756f，hdr@0x14… Data_init 语义下 record count 字段在 +0x10..13=0x2ee(750) → data 应止于 0x100+6*750，与文件 0x127828 不符（0x127828 更像 0x100+Σsize）。
- 挂载选项来自 initrd `usr/bin/common.src`：`-o posix_attr,rw,nodiratime,noatime,shortname=mixed,sync`；QEMU 内挂载**成功**，`ls -la /setting` 列出 `Backup.bin`（vfat 权限位显示为 `---x------`，真机 vfat 就是这种 Sony 风格 mode 位；内核态 `filp_open` 以 root 权限不受阻）。
- 从 trace 看，**file_load 全程没读任何 Backup 数据簇**（整轮 eMMC 读只有 205 个 512B：分区表/引导扇区/FAT/根目录/psd.bin 一段）；把文件 cp 到 tmpfs 后仍失败 → **不是 vfat/权限/簇链问题**。

**实验矩阵（全部 r10 新 initrd，见 §偏离清单）**：
| run | 模块 | 位置/内容 | 结果 |
|---|---|---|---|
| r9_pt5（基线，未动）| initrd 版 backup.ko | /setting vfat | file_load 失败（EIO）|
| r10b | initrd 版 | cp 到 tmpfs，原样 bin+bak | 同样失败（EIO）|
| r10c | initrd 版 + `Backup_debug=1` | tmpfs | 同样失败；**file_load 阶段无任何调试输出**（backup_init 里 file_load 在 `backup_osal_init` 之前，osal 日志通道未建立）|
| r10g | **a15 版 backup.ko**（vermagic `106+`→`106 ` patch，md5 `638881c5…`，insmod 接受）| tmpfs bin+bak | 同样失败 |
| r10g2 | a15 版 | tmpfs **两份内容相同**（排除 .bin/.bak 差异假设）| 同样失败 |
| r10h | a15 版 | tmpfs，hdr+0x0c `BK4`→`Back` 变异 | 同样失败（magic 字面假设未证）|
| r10i（**最终配置**）| a15 版 + **全部 /dev 真节点** + 原版 insmod.sh | /setting vfat | 同样失败（`file_load` EIO）|

**结论/判断（E2）**：两版 Sony 模块（rescue-initrd 版与 a15 产品版，文本段差一倍、vermagic 不同）对**真机原样 Backup.bin** 都在 `backupfile_load` 内失败且与文件系统无关 ⇒ 失败在 `Data_check/Data_init/bl 41c0` 这一层的**数据格式/头校验**；initrd 版模块里 `Data_init` 的比较目标（.rodata 池重定位后落在串池内）可疑，疑为 `Etools-Backup_171H` 分支期望另一种（Rescue/serial-cfg 生成的）Backup 格式。**未做真机对照前不定论**。
**真机侧便宜判据（下一步）**：真机 shell `insmod /path/a15_backup.ko`（同 vermagic 内核）加载看 file_load 是否同样失败；若真机成功 → 差异在运行时上下文（如 osal 消息队列/子系统注册先行），不是数据格式。

## ② P1：sauu 崩溃根因定位（E1）
`r10_r10i.ser`（原链 + a15 backup + 真 /dev 节点）：MODE=0（USER）→ `exec sauu` → `UdrMAIN,0,UpdaterModeMain.cpp:92,"Begin main()"` → **崩溃**。内核异常监视器自带符号解码：
```
function entry : 0x04393ebd -- mcmn_log_init @ /usr/lib/libInfraMediaCommon.so : 0x1d00a
 <- mcmn_list_get_node_count @ libInfraMediaCommon.so : 0x1c9da
page translation fault at 0xffffffff ; r4=fp=0xffffffff, r10=0xaa55
```
对照：r10f（/dev 节点不全）里 sauu 先打 `[ERR]astra_data.c AstraData_Init osal_reg_sync_msg_queue_cb -9`、`FixedAreaTop/Size: FFFFFFFF`、`ERROR: Failed to open stream driver!`，然后空指针(pc=0x041f1774)；r9_pt5（原 initrd、真节点）pc=0xffffffff 跳飞。三次的公共因：**Backup/FixedArea 数据缺失时 updater 拿 0xffffffff 哨兵继续跑**，USER 模式 sauu 在 `mcmn_log_init`（libInfraMediaCommon）里解引用/跳转 0xffffffff。
⇒ **阻塞链是单点的**：修好 backup 数据层 → FixedArea/mcmn 有值 → sauu 应能走到状态机（`BeginningState -> WaitingConnectionState`，之后才需要 PC 侧 USB 通信）。本轮未见任何 WaitingConnection 日志（还没到）。

## ③④ P2/P3：未做（时间盒）——但 P0/P1 已说明 **R1 演练当前被 backup 数据层单点卡死**，payload/写分区测试应等 file_load 打通（或在 initrd 里伪造 Backup_load=1 的 serial-cfg 文件路线，下轮做）。P4（B 线 PROD）未做。

## ⑤ P5：镜像 `a7c_emmc_pt4.img` 各分区数据来源表（脚本 `r10/p5.py`，E1，逐区 md5 对比）
| 分区 | 镜像内偏移(USER) | 来源 | 备注 |
|---|---|---|---|
| a1 | 0x00010000 | **旧的不完整 a1 dump**：0x000000–0x3EFFFF 与 `parts/nflasha1.bin` 一致，**0x3F0000 起为空洞(零)**；新 dump(0x7F0000B) 已存在未回填 | 建议下轮换填 |
| a2 | 0x00800000 | 真机 dump FULLMATCH（含真 Backup.bin/ulogio/DmmConfig）| |
| a3 | 0x01C00000 | 官方 2.00 包 `0700_part_image/dev/nflasha3`，槽尾零 | |
| a4 | 0x04C00000 | 真机 dump FULLMATCH | |
| a5 | 0x05800000 | 官方包 nflasha5，槽尾零 | |
| a6 | 0x09400000 | 真机 dump FULLMATCH | |
| a7 | 0x0A400000 | 真机 a1 dump(l1) FULLMATCH | |
| a10 | 0x0AC00000 | 真机 dump FULLMATCH | |
| a11 | 0x0B800000 | **合成空 vfat**（mkfs.vfat 满槽）| |
| a12 | 0x2AC00000 | **合成空 vfat** | |
| a13 | 0x2D400000 | 真机 dump FULLMATCH | |
| a15 | 0x2D800000 | 真机 dump（Round7 时点；与现 `parts/nflasha15.bin` 仅 ext2 superblock 附近几十字节差异，前 256KiB 中 0x430 处不同）| 读路径已在 R9 证真 |
| a16 | 0x40400000 | **全零**（无来源，占位）| |
| a17 | 0x49000000 | **合成空 vfat** | |
| a18 | 0x4F400000 | **合成空 vfat** | |
| a23 | 0x50800000 | 真机 dump FULLMATCH | |
| 其余 a8/a9/a14/a19-a22/a24-a30 | — | size=0（表里不存在）| |
| 文件 0x0–0x400000 | boot0/boot1 | **全零**（真机 eMMC 硬件 boot 区未 dump）| |
| USER 0x0–0x10000 | | 0x0 处 512B = Round9 生成表（真机此区域未 dump，p1chksum/EXBL 是空白）| |

## ⑥ 真机下一步（只读优先）
1. 真机 shell 里直接 `insmod` a15 backup.ko（其内核 vermagic 本就匹配）对 /setting/Backup.bin 做同一 file_load —— 判定是格式还是上下文（最高价值、只读）。
2. dump eMMC USER 0x000000–0x010000（真分区表+p1chksum）与 boot0/boot1（补镜像空区，让 p1chksum/EXBL 机制可演练）。
3. dump 真机 `usr/lib/libInfraMediaCommon.so`+`libupdatertalk`（若尚未），对 `mcmn_log_init` 做静态确认（E1 定位已在 QEMU 完成）。

## ⑦ 偏离清单
1. **未做**：P2 卡 payload、P3 写分区/reboot、P4 B 线；原因：P0 深挖 + 时间盒。基线对照 = Round9 的 `r9_pt5.ser`（未动）+ 本轮 `r10_r10f/i`（原始 insmod.sh 链）。
2. 新产物（远端 `~/qemu-a7c/`）：`r10/initrd_r10i.img`（md5 `0fbf9bb6…`；原始目录树 cp 自 loop-mount 的原 initrd → 保留全部真 /dev 节点；替换 `usr/kmod/backup.ko`=vermagic-patch 的 a15 版、`usr/bin/insmod.sh`=原版）；`r10/backup_15p.ko`；诊断 initrd `initrd_r10diag.img`/`r10f`（其 /dev 节点由 7z 解包重建，**stream/uipc/backup 等退化为普通文件**——r10b/c/f 的 stream/uipc 报错含此假象，勿过度解读；r10i 起已修正）。
3. 镜像：pt4 未改；`a2` 内文件读出验证（`r10/aa2x/Backup.bin` 7z 提取，md5 同真机）。
4. 日志：`r10_r10a/b/c/d/e/f/g/h/i.ser`（本地=远端 `results_round10/`）；反汇编标注：`r10/text_ann.txt`（initrd 版）、`r10/bk_dis.txt`；P5 脚本 `r10/p5.py`。
5. 未动文件：bionz.c/sd.c/vmlinux/pt4 均同 Round9 md5；`work/sony-src/`、`work/sauu/` 未触碰。
6. 已知坑记录：(a) 7z 解 cramfs 会把设备节点变成普通文件，mknod 需先 rm -f；最稳是 loop-mount 原 cramfs 后 cp -a。(b) busybox 无 `head/tail/cmp/stat`（部分脚本分支静默失效）。(c) sudo 里 `~` 展开为 /root。
