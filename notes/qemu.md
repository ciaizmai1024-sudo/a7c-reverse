# QEMU（cxd90045）离线环境：状态与结论

工具链：`work/qemu-a7c/qemu-sony/` = `ma1co/qemu` master（**QEMU 5.1.0**，`hw/arm/bionz.c` 有 `cxd90045`）
+ `refs/zve10-qemu/patches/qemu/{bionz.patch,sd-cid.patch}`（**对 master 干净应用**）+ 我们的 A7C 改动
（`TEXT_OFFSET=0x00108000`、命令行写 `0x00103000`/`0x00133000`、`cxd90045_load_wbi()` 注释掉、DDR 调整）。
远端构建：`wubin@172.22.22.131:~/qemu-a7c/qemu-sony/arm-softmmu/qemu-system-arm`（gcc-13.3，坑：`ui/keycodemapdb` 要 pin 到 v5.1.0 的 `6b3d716`；5.1.0 自身 `machine-init-done` 多重定义要加 `weak`）。

## 1. 真机启动链在 QEMU 里的对应关系（已核对一致）
- a1 `loadaddr.txt = 0x00108000,0x00700000,0x00103000`：zImage 放在 **PA 0x108000**（= QEMU `TEXT_OFFSET`）、initrd 暂存 **PA 0x700000**（= QEMU `INITRD_OFFSET`，与 a1 `kemco.txt` 的 `initrd=0x00700000,0x00800000` 一致）、第三值疑似引导器写参数/命令行处（zve10 补丁在 `0x133000` 写 `"kemco … *"`，我们把两处都写）。
- a1 的 `vmlinux.bin` 是 **zImage**（不是裸内核）：QEMU `-kernel` 会按 zImage 头解压到**内核自身链接地址**。

## 2. ★Round 2 拿到的日志（log_buf 在 PA/VA `0x6047d000`，`strings` 直接可见）
```
Linux version 3.0.27_nl-rt106 … SMP PREEMPT RT   lowmem: 0x60000000-0xdf800000 (2040 MB)
[<601a3fd4>] ____cache_alloc_node  from kmem_cache_alloc_node+0x120/0x1a8
 from setup_cpu_cache+0xc8/0x194  from kmem_cache_create+0x3a8
 from kmem_cache_init+0x274/0x4cc  from start_kernel+0x16c/0x444
DataAbort, do_translation_fault, DFSC 0x805, r8=0xdf000000
kernel BUG at kernel/panic.c:106!
Unable to handle kernel NULL pointer dereference at virtual address 00000000
Internal error: Oops: 805 [#12] PREEMPT SMP   → 级联 #13…（时间戳 0.137→0.1527）
PC is at __bug+0x24/0x30   LR is at vprintk+0x37c/0x3b8   Process swapper (pid 0)
```
⇒ **不是 hang**：第一个错在 **slab 初始化**（`kmem_cache_init → setup_cpu_cache → ____cache_alloc_node` 触发 DataAbort，r8≈`0xdf000000`），随后 `panic.c:106` BUG + oops 级联；Round 1 看到的"PC 卡在 `0x603643bc`（`ldrex/strex` 轮询 `[r4]!=0`，r4=0x6047e5dc 紧邻 `"ttyAM"`）"= **ttyAM console 的 port mutex**——panic 要打印、console 锁被反复重入 ⇒ 永久自旋。**因为 console/ttyAM 在 QEMU 里不好使，panic 全程没输出**，才被误判成"静默死锁"。
- 试验 `maxcpus=0`：**无变化**（同一 slab trace）⇒ 与 SMP 无关。
- 不带 initrd、`root=/dev/nflasha7`：崩在 slab init，**没有任何 VFS 输出** ⇒ `mpr`/nflasha 分区驱动能否造 `/dev/nflasha*` 仍无法验证。

## 3.（机制已被 §7 更正）当初的推断：内存图不对 —— 方向对、机制猜错
- 内核 `PAGE_OFFSET/lowmem = 0x60000000`，`Linux version` 行里 lowmem 到 `0xdf800000`（2040 MB）⇒ **真芯 CXD90045 把 DRAM 镜像(alias/mirror)到 `0x60000000` 窗口**，所以"链接地址 `0x60000000`"其实就是 PA 0。
- QEMU 里我们把 DDR0 扩到 2 GB（PA 0–0x80000000），于是内核解压落到 **PA 0x60000000**（真机上是镜像区），内核线性映射又去碰 `0xdf000000` ⇒ 翻译错误。
- **Round 3 的假设（待源码确证）**：DDR0 保持真实大小 + 在 `0x60000000` 做一段 **alias MemoryRegion 指回 PA 0**（pre-MMU 解压用镜像窗，MMU 打开后内核 section 映射 `VA 0x60000000 → PA 0`，两处共用同一块 RAM）；bank 的大小/数量要按 **Sony GPL 源码里的 machine 定义/`memory.h`** 给，而不是我们自己猜。

## 4. 整机挂载图（`firmware.tar_unpacked/0100_config/mount.conf`，权威）
```
a1 none vfat 8323072        a2 /setting vfat 20971520     a3 /system vfat 50331648
a4 none raw 12582912        a5 /wbi wbi 62914560          a6 none vfat 16777216
a7 /rootfs raw 8388608      a10 /tmp vfat 12582912        a11 /log vfat 524288000
a12 /cert vfat 41943040     a13 none vfat 4194304         a15 /usr raw 314572800
a16 /android/system raw 146800640   a17 /android/data vfat 104857600   a18 /lens vfat 20971520
a23 /PMBP prfile 2097152
```
- **`/rootfs` = a7**（真机 dump 在本机 `work/l1-camera/nflasha7.bin`，8,388,608 B；ext2 **superblock 在分区内 0x400**，`EF53` 在 `0x438`；**更正：raw 分区没有 0x400 字节头**，文件系统就是分区偏移 0）。
- 小分区（真机 a2/a6/a10/a13）都是 `mkdosfs` 默认几何的 FAT12/16；`mount.conf` 里的 `16384` 是 mount 参数不是簇大小 ⇒ QEMU 镜像里的 a11/a12/a17/a18 用 `mkfs.vfat` 默认几何即可（若 mpr 驱动校验簇大小，Round 3 再验）。
- `a16(/android/system)` 尚无来源（留零）；`a18(/lens 20 MB vfat)` 很可能是**逐机镜头校准** ⇒ 真机 L1.5 补 dump 的首选目标。

## 5. 三级目标与判据（不变）
1. **updater 链**：源码内核 + 真机 a1 initrd ⇒ 串口出现 `UdtrMain` / `[DETAIL] MODE=` / `mkramdsk`。
2. **整机链**：`root=/dev/nflasha7` → 按 mount.conf 挂 `/system //usr /tmp /setting /log /cert /lens /wbi` → 起 `im.elf/sen.elf` ⇒ 才叫"模拟真机"。Jiritsu/FileControl 能否在 QEMU 里跑取决于 USB 建模（退路：串口控制台）。
3. **审查要的 R1 演练**：镜像里故意擦 a15 → 走官方更新流程 → 看能否重建；再做 **L0' 离线预演**（改载荷 + 重算 DEND CRC）。这两步一过，恢复能力从 `R0 推断` 升到 `R1 离线演练过`。

## 6. 缺口清单（按代价从低到高）
1. **内存图**：等 GPL 源码里的 machine/`memory.h`/bank 定义（正在取，`01a16982`）。
2. **console/ttyAM**：驱动期望的 MMIO/IRQ 与 ma1co 模型不一致 ⇒ panic 打不出来（源码可给权威基址/IRQ；没有就先在关键路径上直接读 log_buf）。
3. **EXBL/boot0（设备偏移 `0x0–0x10000`）**：无副本 ⇒ 只能走 `-kernel` 路线。
4. **A7C 的 WBI 9 段表**：在 `nflasha5` 的 `WBI1` 头（magic@0、头长 `0x290`、段数 9 @+8）里；zve10 那张 7 段表不适用，已注释掉。
5. **a11 `/log` 必须是合法 vfat**（已做）；**a16 `/android/system` 缺来源**。
6. `a12(/cert)`、`a18(/lens)` 用空 vfat ⇒ 证书/镜头校准相关服务会报错（预期内，别当故障）。

## 7. ★Sony GPL 源码到手后的权威结论（详证见 `work/sony-src/SONY_SRC_NOTES.md`，222 行）
包：`linux-kernel.tar.gz` 54,211,353 B（md5 `4c1f897a…`）→ 内核 **3.0.27_nl-rt106**（`Makefile:1-3` + `localversion-rt`）+ **出厂 `.config`**。编译成功（gcc 6.4 Bootlin；只需补 `compiler-gcc6.h` + 30 处 `.section …,"ax"`；**gcc≥7 会挂 `asm/uaccess.h` 的 `__asmeq`**）→ `System.map` 里 `_text=60108000`。**同地铁证**：`nflasha3.bin` 里有 `3.0.27_nl-rt106`、`kemco`、`cmdline override at %p`。
- **装载机制（更正 §3）**：`PAGE_OFFSET=0x60000000`(`.config:601`、`memory.h:33,56-69`)、`TEXT_OFFSET=0x00108000`(`.config:347`、`vmlinux.lds.S:86`) ⇒ 链接 `0x60108000`、装载 `0x108000`；原厂镜像是**未压缩 `vmlinux.bin`**（`arch/arm/Makefile:319-323` + `CONFIG_SNSC_BOOT_BIN=y`）⇒ **不该按 zImage 解压到链接地址**；正确做法 = 按原机把 `vmlinux.bin` 放 PA `0x108000`，由**内核自己的 head code**（`arch/arm/kernel/boot.S:124 ej_head_init`）建 VA→PA 映射。`loadaddr` 第二值 `0x00700000` 源码里没有（EXBL 私有）。⇒ **不需要 alias 窗**。
- **console/ttyAM**：驱动 = **`drivers/tty/serial/amba2.c`**（ttyAM0/1）；UART0 **`0xf2000000`**(`platform.h:55`)、GIC SPI **118**(`irqs.h:69`)、`request_irq` 在 `amba2.c:477`；控制台默认关（`amba2.c:89`），靠 **`amba2.console=1`** 与 **`cfg.uart=0xf`**(`mach/cfg.c:63`)；**死锁点 = `amba2.c:829-835`（`do{}while(!UART_TX_READY)`）与 `:875-877`（`while(FR&BUSY)`）** ⇒ 未建模区读回 `0xFFFFFFFF` 就永远转（Round 2 看到的 `0x603643bc` 自旋正是这里；`:855` 才是 RT spinlock 的 `ldrex/strex`）。修法：建模 `0xf2000000`（`FR` = 偏移 `0x18`，**未实现处必须读 0 而不是 `0xFFFFFFFF`**）。
- **SMP**：`SMP=y / NR_CPUS=4`；secondary 走 **ESRAM 信箱 `0xfe000000+0x5000`**（`VEC +0xc`、`FLAG +0x1c`）+ `boot.S:75-83` 的 `pen:` 轮询（`platsmp.c:75-123`）；`CONFIG_CXD900X0_QEMU=y` 走 **SIMPLE_LOADER**（`boot.S:69-72,98-116`）跳过信箱。
- ★**Sony 自带 QEMU 配置**：`arch/arm/configs/cxd90045_qemu_nfs_defconfig`（`CONFIG_CXD900X0_QEMU=y` → `SIMPLE_LOADER`+`SIMPLE_SUSPEND`、`TEXT_OFFSET=0x138000`、**`CMDLINE_PHYS_OFFSET=0x133000`**（与 zve10 补丁写 kemco 的地址一致 ⇒ ma1co 走的就是这条路）、cmdline 含 `mem=512M@0 memrsv=0x00128000@0 console=ttyAM0,115200n8 amba2.console=1 … klog.addr=0x02120000 tmonitor.addr=0x03000000`）⇒ **观测面是现成的**：`klog` 由 `kernel/klog.c` 实现在**固定地址**（该配置里就是 `0x02120000`），另有 `mach/tmonitor.c`、`CONFIG_EXCEPTION_MONITOR_STOP_SIBLING_TIMEOUT=7000`。ATAGS 传 `0xffffffff`（`boot.S:182`）⇒ 靠内置 `init_tags` + `mem=`/`early_param(memrsv)`(`init.c:610,695`)。
- **kemco 命令行的读取者**：`arch/arm/kernel/setup.c:915-946` + **`CONFIG_CMDLINE_PHYS_OFFSET=0x00103000`**（= `loadaddr.txt` 第三个值！）。`p1chksum`/`loadaddr` 内核里都不出现（EXBL/闭源；另有 2.00 未开的 `drivers/char/snsc_nblargs.c`）。
- ~~**`nflasha` 驱动不在 GPL**（`CONFIG_MTD` 关；只有 OSAL/UDIF 框架 + 资源声明：`mach-cxd900x0/udif/platform.c:257-266` eMMC **`0xF0304000`**、`NANDC 0xf5000000`）⇒ **eMMC/NAND 驱动本体闭源***。★**此结论已被 §12 更正**：Round 7 日志里 `ALFReD/eMMC: 1286MiB`、`nflasha: unknown partition table` 都是树内代码打的 ⇒ **eMMC + `nflasha` 分区层在 GPL 里就有**，当时只搜了 `CONFIG_MTD`/`drivers/udif` 没搜 `ALFReD`/`nflasha` 字符串。包里的 `dosfstools/e2fsprogs` src.rpm 只对应格式化。
- **FAT 写语义（回答之前的约束 #3）**：走内核 VFS + **Sony 改过的 `fs/fat`**（新增 `gc.c`/`tz.c`；`.config:2139-2165` 开 `batch_sync/posix_attr/avoid_dlink/fix_utf8`、**关 `FAT_GC/timezone/clnshutbit`**；`open=generic_file_open`(`file.c:491,510`)；私有 ioctl **`FAT_IOCTL_CLOSE_NOSYNC 'r' 0x60`**）⇒ 「写完是否 sync」有源码级答案：相机侧很可能用 `CLOSE_NOSYNC`；`/tmp`、`/setting` 的挂载选项源码里没有（在用户态）。
- ★**`WBI1` 就是内核 warmboot 头**：`include/asm/mach/warmboot.h:59`（`struct wb_header` 48 B + `struct wb_section` 32 B）、`.config:771-775` `WBI_DVERSION=0x20060224`、flag 位 `COMPRESS|LZ77=0x09`；WBI 由**内核在 suspend 时生成**（`arch/arm/common/warm.c:1131-1169,1215`、`pm.c:340,448-461`）⇒ **`nflasha5(/wbi)` 是「休眠热启动镜像」**，不是固件配置表；更新流程里的 `wbi_data_file` 就是刷这块（mode 5 有它由此说得通）。把九段搬到 `0x2002xxxx/0x11000000/0x20200000` 的搬运工在 EXBL/闭源里（这些地址源码里查不到）。也解释了我们 Round 1 拿 ZV-E10 的 7 段表去 load A7C 的 WBI 会断言挂掉。
- 没有 bootloader/EXBL、没有相机用户态（只有 busybox/coreutils/dosfstools/e2fsprogs 等 src.rpm）。Sony 特有目录：`mach-cxd900x0`(95 文件)/`mach-emxx`/`mach-ne1`/`drivers/udif`/`drivers/tty/serial`(amba2)/`kernel/power/ssboot`/`kernel/klog.c`/`fs/fat`/`fs/axfs`/`KMC`/`tools/ltt`。
- GPL 页：**2.03 存在**（busybox 升到 1.34.1，未下载）、`Ver201`/`ILCE-7C` 也在；`Ver202`/`Ver100`=404；`/DI/` 无目录索引。

## 8. ★真机 cmdline 原文（FAT 里正式取出：`work/cmdlines/kemco_a1.txt` 1062 B、`kemco_a2.txt` 1905 B）
**a1 = updater 阶段**（`boot/kemco.txt`，cluster 402）：`ip=off initrd=0x00700000,0x00800000 root=/dev/ram0`、`rw noatime noalign`、`init=/sbin/init`、`exception.reboot=1 exception.console_option=115200n8`、`wdt.timeout=500`、`warm.boot_drop=0 warm.ignore_drop=1`、`pcie.*`、`error.led=0,0`、`cfg.poff=0,10`、
**`console=ttyAM0,115200n8 amba2.console=0 xrstreq=0 wdt.mode=0 stack_usage=y cxd90014.bam=Y`**、`cfg.uart=15`、`tmonitor.addr=0x1A00000 tmonitor.size=0x500000`、`wbi_memclr=0x200210e8`、**`em_console=0x200210ec`**、`boottime=0x20000@0x03480000`、**`klog.addr=0x034A0000 klog.size=0x20000`**、`mem=1G@0`、`memrsv=1M@0`、`memrsv=0x75e000@0x02E68000`、`memrsv=0x500000@0x09b00000`、**`memrsv=0x20000000@0x20000000:uc`**、**`mem=1016M@0x80000000@1`**、结尾 `*`。
**a2 = 主系统**（`/setting/kemco.txt`，cluster 90）关键差异：`console=ttynull … cxd900x0.bam=N mmu.dac=Y exec.coremode=1`、`ramdisk_size=8192`、`rootfstype=ext2 root=/dev/ram0 init=/sbin/init initrd=0x700000,8M`、`adrs_conv.debug=1 adrs_conv.null=Y`、`pgd.n=15`、`cache_l2x0.wait=3 cache_l2x0.prio=130`（**PL310 L2**）、`cfg.uart=9`、`tmonitor.addr=0xF00000 tmonitor.size=0x8000`、`klog.addr=0x035A5000 klog.size=0x20000`、`alog.addr=0x03524FC0 alog.size=0x60040`、`warm.mode=2 warm.tmo=100000 warm.resume_drop=0 warm.boot_drop=0 warm.ignore_drop=1`、`pm.resume=0x20021054 pm.sus_error=0x20021060 pm.ddr_ctrl=sref pm.pasr*=0xff`、`cmpr.path=/system/sabin/ssboot.bin cmpr.path2=/system/sabin/ssboot_any.bin`、`exception.reboot=1`、`wdt.timeout=500`、`cgroup_disable=memory`、`mem=1G@0 memrsv=1M@0 memrsv=0x8000@0xF00000 memrsv=0x1A5E000@0x02E68000 memrsv=0xAEEB000@0x0A915000 memrsv=680M@0x15800000:uc mem=256M@0x80000000@1 memrsv=256M@0x80000000:uc`。
- ★**A7C 的 WBI 段表（修 `cxd90045_load_wbi()` 就靠它）**：`wbimem=0x1000@0x20021000`、`0xEC000@0x20028000`、`0x8000@0x20145000`、`0x500000@0x03085000`、`0x96D000@0x11000000`、`0x2948000@0x20200000`、`0x200000@0x23E00000`；另有 `cmpr.mem=0x8000@0x15800000`、`warm.mem_dst=0xC00000@0x15900000`、`warm.mem_work=0x600000@0x16500000`、`wbi_cmpr.waddr=0x6AA00000 wbi_cmpr.wsize=0x100000 wbi_cmpr.nbuf=12`、`wbi_memclr=0x200210e8`。
- **两个阶段的 bank 声明不同**：updater `mem=1016M@0x80000000@1`（几乎全部第二片 DRAM 给更新用），主系统 `mem=256M@0x80000000@1` ⇒ 第二片 DRAM 在 0x80000000，主系统只取 256 MB（其余留作 `:uc`/WBI/相机用）。
- **`klog.addr` 两个阶段不同**：updater `0x034A0000`、主系统 `0x035A5000`（都在 `memrsv` 区里）⇒ **离线取日志要用对应阶段的地址**。
- `cxd90014.bam=Y`（updater）vs `cxd900x0.bam=N`+`mmu.dac=Y`（主系统）+ `adrs_conv.*` ⇒ 疑似"boot address map/地址转换"开关，与 node1@0x80000000 能否被平坦进线性窗直接相关（Round 4 正在验）。

## 9. Round 4 结论（可用配置 M4 + A7C 的 DRAM 结构）
- **可用配置 M4**：QEMU **2 GB 平坦 RAM@PA 0**（`A7C_MAP=f`）+ kemco 里 **`mem=1016M@0x40000000@1`**（其余逐字照 a1）。进展：`l2x0 enabled`、`high_memory: df800000`、`Normal 0x00000000->0x0007f800`、`node0 127650 / node1 260096 pages` ⇒ zone 初始化全过。
- **A7C 的 DRAM 结构（推断已被 M1/M3/M4 三组对照支持）**：共 **2 GB DRAM**；第二片经 **DDRC/EXBL 地址重映射**，在 updater 阶段从 CPU 视角看落在 **PA 0x40000000–0x7F800000**；而内核命令行仍按芯片基址写 `mem=1016M@0x80000000@1`。中间 **`memrsv=0x20000000@0x20000000:uc`（512 MB uncached 窗）** 正好把 `0x20000000–0x40000000` 抠掉 ⇒ `0–0x20000000` + `0x40000000–0x7F800000` 与 2 GB 严丝合缝。对照：**内核只按声明的 bank 建页表**——M3（2040 MB 平坦 + 1016 MB@0x80000000，RAM 兜得住）与 M1（只 2 GB 平坦）都照旧死在 `nodeorder_init memset+0x2c`，**加 alias/补 RAM 无效，必须改声明的 bank 基址**。
- `cxd90014.bam` = **Bus Activity Monitor（memchk）使能**（源码查明），**不是**地址转换开关。a2 主系统用 `cxd900x0.bam=N mmu.dac=Y`。
- Round 4 卡点：`PC=0xffff1000 LR=0xffff1004`、**ABT 模式**、`R04=0xdf7fe000`、`R05=0x00132c01`（疑似 abort 递归/vectors 页问题）；观测只有 **log_buf 环（PA `~0x0049fe88`）可用**，且要在级联刷满前抓（`SNAPEVERY≤5`）；`klog@0x034A0000` 全空（死在 initcalls 之前）；em_console mailbox 未见写。
- bionz.c 终态 md5 `11abc8c7d5a3c0ec0a50bfe4262e3c70`：`A7C_MAP` 加 `e(2040M+1016M)/f(2G)`、新增 `A7C_CMDLINE_FILE`（逐字节写 blob@`0x133000`）、bootrom 去 readonly；`TEXT=0x138000`、`initrd=0x700000`。

## 10. Round 5 结论：卡点的真实机制（不是缺外设、不是 oops 级联）
`-d int` 全量统计（4.1 GB 日志）：**真错只有一次** —— `Taking exception 4 [Data Abort] ESR 0x25 DFSR 0x5 DFAR 0x0`；随后 **`Taking exception 3 [Prefetch Abort] IFSR 0x7 IFAR 0xffff1000` ×35,848,113** 死循环。`-d int,exec`：DA 前最后 TB = **`paging_init+0x534`（在 `bl bootmem_init` 之后）**；DA 后 CPU 在 **全零的 vectors 页**里 `0xffff0010 → 0xffff0400 → …` NOP 滑到 `0xffff1000`（PTE=0）取指失败 ⇒ 无限 PrefetchAbort。
- **`0x132c00`** = Sony 静态页表区 `top_pmd_page+0xc00` 的 **L2 表（全 0）**；**`R05=0x132c01`** = `swapper_pg_dir[0xfff]` 的 L1 描述符 ⇒ **VA `0xffff0000`（vectors）的 L2 项从没被填**（`early_trap_init` 拷过之后被 `devicemaps_init` 的 **`CONFIG_EJ_STATIC_VECTOR_PAGE`** memset 抹掉）⇒ 崩溃时永远自锁死，这就是"观测面一直只有一段死循环"的原因。
- **死亡公式**：`bootmem_init` 之后的尾部例程按 **`pfn = (VA − 0x20000000) >> PAGE_SHIFT`** 查 `mem_section[]` **且不判空**：`VA = high_memory−0x2000 = 0xdf7fe000` ⇒ `pfn = 0xbf7fe`、section 索引 `R02 = 0xbf7`、`mem_section[0xbf7] = 0` ⇒ 空指针（DFAR=0）。参数量与总 RAM 都无关（M6/M7/M8 全同一卡点）。
- **前进最多 = M10**：`mem=512M@0` + **删 `memrsv=0x20000000@0x20000000:uc`** + **`mem=1016M@0x20000000@1`** ⇒ 风暴消失、**oops handler 能用**（`Internal error: Oops: 805 [#14]`、`Unable to handle kernel paging request at e59f312c`），最后停在 `paging_init` 栈内 `_raw_spin_lock_irqsave+0x90` 自旋。⇒ **那个 `0x20000000` 就是关键**（Round 6 去源码里查它的宏身份：`mach/memory.h` 的 `PHYS_OFFSET/ARCH_PHYS_ADDR_START`？还是 `adrs_conv` 的 bus↔phys 转换）。
- 观测面现状：只有 **log_buf 环**可用（要在级联刷满前抓，`SNAPEVERY≤5`）；`klog@0x034A0000` 全空（死在 initcalls 之前）；em_console mailbox 未见写；串口 0 字节；本 QEMU **没有 `unassigned` log target**（`-d help` 里没有）。

## 11. Round 6：内存图的权威答案（源码级）+ 观测面打通
- **`0x20000000` 的身份**（`arch/arm/mach-cxd900x0/include/mach/memory.h:68-69`，Sony 自定义 `__virt_to_phys`）：
  `VA < 0xa0000000 → PA = VA − 0x60000000`；否则 `PA = VA − VA_DDR1 + DDR1_BASE = VA − 0x20000000`，其中 `VA_DDR1 = PAGE_OFFSET + SIZE_DDR0(0x40000000) = 0xa0000000`、`DDR1_BASE = 0x80000000`。
  ⇒ **线性映射是"VA 连续、PA 有洞"**：DDR0(1 GB) 接 DDR1(1016 MB) 紧挨着排 VA，PA `0x40000000–0x7FFFFFFF` 是**物理洞**。**QEMU 定论布局 = `A7C_MAP=g`：DDR0 1 GB@0 + DDR1 1016 MB@0x80000000 + 中间留洞**（不要 mirror/alias，也不要 sram2 填洞）。
- **`adrs_conv`** = `arch/arm/mach-cxd900x0/adrs_conv.c`：运行期 `VA↔PA↔uncached 别名` 转换 + `memrsv=…:uc` 的消费钩子（`arch_va_to_phys:100`）；**不是** boot 期组件（所以补 `adrs_conv.*` 参数改不了早期崩溃）。
- **`paging_init` 尾部那次空指针不是 Sony 函数**：是 `arch/arm/mm/mmu.c:1704-1706` 里内联的 `virt_to_page(zero_page)` → `pfn_to_page`，**sparsemem 的判空只护了子表偏移**、`ldr r1,[r3]` 无条件执行 ⇒ DFAR=0。`SECTION_SIZE_BITS = CONFIG_SNSC_SPARSE_SECTION_SHIFT = 20`（两份 config 一样）。
- **EJ 静态向量页缺口（为什么崩溃一定变成死循环）**：`head.S:60-65` 把向量页**定死在 PA `0x133000`**（= QEMU defconfig 的 `CMDLINE_PHYS_OFFSET` ⇒ **向量子页和 cmdline blob 共用同一页**）；`devicemaps_init`(`mmu.c:1571-1583,1618-1626`) 只给 `0xffff0000` 那一页建 PTE（实测槽 `0x132fc0 = 0x13367e` → 指向 PA `0x133000`）**并把内容 memset 清零**；内容要到 `setup_arch` 末尾的 `early_trap_init`(`setup.c:1094`) 才填 ⇒ **`bootmem_init` 阶段任何异常都会踩全零向量页，滑进 PTE=0 的 `0xffff1000`**。预写页表槽(`0x132fc4/fc8`)会被内核清掉 ⇒ 根治办法是把内存布局摆对（g）。
- **观测面打通后的验证输出**（C2，无 PrefetchAbort 风暴；串口仍 0 字节，文本读自 log_buf 环 PA `0x49fe88`）：
  `Unable to handle kernel NULL pointer dereference at virtual address 00000000` / `Internal error: Oops: 805 [#14] PREEMPT SMP` / `pc [<60140d3c>] lr [<6015fb70>] = __bug+0x20 ← vprintk+0x1dc` / `Kernel panic - not syncing: Attempted to kill the idle task!`
- **各档结果**：C1（a1 逐字 + g）**最远**：到 `start_kernel → nodeorder_init`（2.8 s）；首错 DA `DFSR 0x805 DFAR 0xdf800000 = high_memory`，最后 TB `nodeorder_init+0x18/0x2c ↔ memset`（memset 返回漂移 ⇒ 循环不终止、踩穿窗顶；`mem_map` 实测落在 `~0xde5ee000`）。C2（a2 逐字）：`vprintk` 里 `BUG()` 级联 ⇒ 可读 panic（见上）。C3（bank1 挪回 `0x80000000` 的 m10g）：退回 `0xffff1000` 风暴，环尾停在 `bootmem_init: max_low=…` ⇒ **判别变量是 bank0=512M 与缺 `:uc`**。都没到 `/init`（缺口仍在内核早期内存管理，不是 `/dev/nflasha`）。
- 最优基线：**`A7C_MAP=g` + a1 kemco 逐字**（md5 `614f102b`）；bionz.c md5 **`df3a4c3b51e15da2f6a7e2fa0c3cddc8`**（含 `g` 布局与 PTEFIX）。产物 `work/qemu-a7c/results/round6/`（`FINDINGS.md`、`vectors_fix.patch`、`rings6.txt`、`kemco_m10g`）。

## 12. ★Round 7：跑到 updater rootfs（`VFS: Mounted root (cramfs)`）——离线环境成立
**关键结果**：`Memory: 1024MB 1016MB = 2040MB` → `console [ttyAM0] enabled` → `RAMDISK: cramfs filesystem found at block 0` → **`VFS: Mounted root (cramfs filesystem) readonly on device 1:0`** → `Freeing init memory: 176K`；环里能看到 updater rootfs 的 **`UdtrMain.sh`/`mkramdsk.sh`**，以及 **`ALFReD/eMMC: 1286MiB`** 与 **`nflasha: unknown partition table` / `partition table invalid`**（日志止于 0.913 s）。⇒ **下一缺口是 eMMC 上的 nflasha 分区表，不是内存管理。**
- ★**更正 §7**：eMMC/flash + `nflasha` 分区层**在 GPL 源码里就有**（日志里 `ALFReD/eMMC`、`nflasha: unknown partition table` 都是它打的）。之前"源码里没有、闭源"的说法作废（当时只查了 `CONFIG_MTD`/`drivers/udif`）。
- **`nodeorder_init` 真因（反汇编 + `memset.S` 实证）**：gcc 6.4 把 **`memset` 的返回值当循环游标**（`add r3,r0,#76; cmp r3,r5(=base+684)`），而 **Sony 的 `arch/arm/lib/memset.S` 返回 `dst+len`** ⇒ 游标每轮 **+144 而不是 +76**、`cmp` 永不相等 ⇒ 无限循环涨到线性窗顶。**与 `mem=`/RAM 布局无关**；加 **`KCFLAGS=-fno-builtin-memset`** 后游标变成纯指针算术（`add r5,r5,#76`），9 轮干净结束。⇒ 这是**编译器与 Sony 汇编约定不匹配**造成的（真机当年多半用更老的 gcc），属诊断偏离，已留 `v3-unpatched` vs `v3-patched` 对照。
- **DDR 常量是 CONFIG 值**：`mach/memory.h:49-58,65-69`（`SECTION_SIZE_BITS=CONFIG_SNSC_SPARSE_SECTION_SHIFT`、`VA_DDR1=VA_DDR0+SIZE_DDR0`、`__virt_to_phys`）；`Kconfig:38-43` **`SIZE_DDR0=0x40000000`、`SIZE_DDR1=0x10000000`（256 MB）**；`vmalloc.h:47 VMALLOC_START=PAGE_OFFSET+SIZE_DDR0+SIZE_DDR1+8M=0xB1000000` ⇒ **GPL 这份 config 是"主系统"的**（a2 cmdline 的 `mem=256M@0x80000000@1` 与它自洽），**a1 的 `mem=1016M@…` 说明 updater 阶段是另一份 config**（GPL 里没给 updater 的）。但 C2（QEMU 256 MB + `256M` cmdline）证明这个不自洽**不是**崩溃原因（首错只是从 `0xdf800008` 变成 `0xb0000018`，同族：都是越线性窗顶）。
- **V3（出厂 config + `CONFIG_CXD900X0_QEMU=y`）**：`_text=0x60108000`（`TEXT_OFFSET=0x108000`）、**`vector_page` PA=`0x103000`=`CMDLINE_PHYS_OFFSET`（同一页）** ⇒ **`loadaddr.txt` 第三值 `0x00103000` 的身份 = 向量页/cmdline 页**（闭环）；`__log_buf=0x604e32a8` 且 **环只有 8 KB（`LOG_BUF_SHIFT=13`）**；`BLK_DEV_INITRD(y)`、`BLK_DEV_RAM(y, SIZE=4096)`、`CRAMFS(y)`。3.0.27 拒绝 `make O=`（`prepare3`）⇒ 用 `cp -a` 的 `~/qemu-a7c/ksrc-v3`。唯一源码改动是纯链接桩 `pcie_link_fix.patch`（`QEMU=y` 关了 `PCIE2_DME` ⇒ `pcie.o` 不编，`pciehp/probe.c` 仍引用）。
- 其它诊断偏离（都有对照存档）：`LOG_BUF_SHIFT 13→17/21`（**21 会把 bss 顶到 `0x700000` ⇒ `INITRD … disabling initrd`**）；**`BLK_DEV_RAM_SIZE 4096→8192`**（a1 initrd 实测 4700 KiB cramfs，出厂值装不下 ⇒ 又一个"出厂 config ≠ updater kernel"的证据）。
- **`em_console` 更正**：它是**标志**不是 FIFO——`mach-cxd900x0/error.c:249 early_param("em_console", parse_adc_param)`、`:400 em_console_enable_triggered = errind_console_enable_triggered`、`amba2.c:987` 内核**读**它（EM 要求开 console）。串口 0 字节的真因是 **a1 blob 里 `amba2.console=0`**；本轮环里已有 `console [ttyAM0] enabled` ⇒ **把 `amba2.console=0` 改成 `1` 就能要真串口输出**。
- 运行参数（可用）：`A7C_MAP=g A7C_TEXT_OFFSET=0x108000 A7C_CMDLINE_OFFSET=0x103000 A7C_CMDLINE_FILE=parts/kemco_a1.txt -kernel ksrc-v3/arch/arm/boot/vmlinux.bin -initrd parts/initrd.img`；bionz.c md5 **`87febf2ba7fc4f19aa05ed1829edf804`**（新增 `A7C_MAP=h`＝DDR1 256 MB；PTEFIX 按 TEXT_OFFSET 推导 `0x102fc4/0x102fc8=0x10367e`；修 `0x103000` rom 重叠 abort）。产物 `work/qemu-a7c/results/round7/`。

## 13. Round 8：updater 用户态链已经跑通，只差 `/dev/nflasha*`；但"分区表在 0x400000"这条对不上
**已确证的好消息**
- `amba2.console=1` ⇒ **真串口出字**（以后不必刮 log_buf）。
- updater 用户态链跑到了：`insmod.sh` → `mount /dev/nflasha2` **失败** ⇒ **`FIRMUP NG 72/73`**。⇒ 除 `/dev/nflasha*` 之外，initrd 里的脚本链、模块加载、根文件系统都工作。
- `init=/bin/sh` ⇒ **拿到 BusyBox 1.29.3 ash**（`/ #`），但 **QEMU 里 amba2 的 RX 收不到输入**（stdio/延迟/socket 三种都不回显）⇒ 还不能交互。
- 冒烟 `wipe-a15`（置零 a15 的 288 MiB）：失败点与没擦时**完全相同**（在 `nflasha2` 挂载之前）⇒ a15 内容目前不影响 updater 走到那一步。

**`nflasha` 驱动的身份（更正 §12 的"更正"）**
- GPL 树里 `grep nflasha/ALFReD` = **0 命中** ⇒ `ALFReD/eMMC: 1286MiB`、`nflasha: unknown partition table` 都是 **updater initrd 里的闭源模块 `emmc.ko`** 打的（已从 initrd 取出，存 `work/qemu-a7c/results/round8/emmc.ko`）。★**它的 vermagic 与我们编的 V3h 完全匹配** ⇒ 真机模块能直接装进我们的内核（这才是"离线环境能用真机驱动"的关键事实）。
- Round 8 在 QEMU `sd.c:sd_blk_read()` 加打印：驱动只读 **USER 区 `0x400000–0x401000`**（8×512 B + 重读 `0x400000`）。`emmc_blk_plat_probe_post@0x7d30`、`0x7eb0` 判据：`buf[0/4/8] == buf[0x200/0x204/0x208]`（hdr `{magic,version,n_partition}` 在 `+0` 与 `+0x200` 各一份），失配打 `partition table invalid`(str+0x2533)；表项 **16 B 槽 @ `+0x40+16i`**，字段 `+0x20 start`(字节、512 对齐)、`+0x24 size`、`+0x28 type`、`+0x2c flag`；**type**：`0=raw, 1=vfat, 2=WBI`(`0x8234 wb_register_device`)、`3=LZP`(`0x7f54 uz_emmc_lzp_part_size`)；**分区编号 = 表项位置**（按 partinf a1..a30 顺序），`/dev` 静态节点 **block 主设备 252、minor=编号**，`dnflasha`=252:`128+n`（压缩通道），名字由 `devno.ko` 注册。
- Round 8 用 `partinf.conf` 合成表（`mk_nflasha_ptable.py`，pt/pt2/pt3 三档）写进 `0x400000` ⇒ **全部仍 invalid**：判定还拿 `tbl=`（RAM 里的默认表，真机由 bootloader 填）比对 ⇒ **magic/CRC 字段没吃透**。

## 14. ★我本地复核：**分区表不在 a1 里面**（"表在 0x400000"与 a1 dump 矛盾）
`a1` 起点 `0x10000` ⇒ 设备 `0x400000` = **a1+`0x3F0000`**。用真机 a1 dump 直接验：
- 该 4 KiB 全是高熵数据（**字节熵 7.952/8**），且**落在 `initrd.img` 的数据覆盖范围**（a1 的 FAT 数据区起点 `~0x8340`，initrd 从 cluster 4 起、覆盖 `~0x10340–0x4a7340`）⇒ **那是文件内容，不是表**。
- 驱动判据 `buf[0/4/8]==buf[0x200/…]` 三条**全不匹配**；再把该判据扫遍整个 a1（所有 512 B 对齐位置）⇒ **0 命中**。
⇒ 结论：**要么 QEMU 把驱动选中的 eMMC 地址空间（boot0/boot1/GP/`PARTITION_SEL`）当成 USER 落错了地方，要么 `0x400000` 只是备份探测而主表来自 RAM `tbl=`（EXBL 填）**。这条必须在下一步用"完整 MMC 命令轨迹"分辨，不能再猜。
- 因此 §12/L1.5 里"机身 boot 区 = `0x0–0x10000`"也还没被证实；**该 dump 什么仍未定**（Round 8 给的候选：USER `0x400000–0x401000`、USER `0x000000–0x010000`、camtool mem `0x20000000` ~0x400 B＝`tbl=`/dev_params 源）。

## 15. 本地新事实：`insmod.sh` 全文 + `emmc.ko` 未 strip（这两条改变打法）
`work/l1-camera/a1_initrd/usr/bin/insmod.sh`（明文 shell）：
- 模块顺序：`devno, dmac, ldec, **emmc.ko tbl=0x80000000**, osal_utm, osal_uipc, utimer, stream, stream2, sio`，然后：
  - `if [ -e /root/IAMLDUDWRT ]`（recovery/工厂旗标）⇒ 挂 **tmpfs** 到 `$P2_MNT_DIR` + `ud_get_serial_cfg_file.elf 6/7/8` 取 `Backup.bin/ulogio.bin/DmmConfig.bin` + `insmod backup.ko Backup_load=1 Backup_save=0` ⇒ **这条路完全不碰 `/dev/nflasha2`**！
  - `else` ⇒ `echo "mount /dev/nflasha2"`；`mount -t vfat /dev/nflasha2 $P2_MNT_DIR $VFAT_MOUNT_OPTION_SYNC` 失败即 `blink_error_exit $ERROR_NAND_MOUNT`（**就是我们看到的 72/73**），成功则 `insmod backup.ko Backup_save=0`；
  - 之后 `osal_ulogio.ko ulogio_initfile=$P2_MNT_DIR/ulogio.bin`、`dmm.ko DmmConfig=/etc/DmmConfig.bin`、`i2c.ko`、（`POWER_IC_CA` 时）`ca.ko ...`。
- ★`tbl=0x80000000` 是**传给模块的参数**（不是"从 RAM 读默认表"那么被动）⇒ 离线时我们可以**自己预填 PA `0x80000000`**（`A7C_MAP=g` 下 DDR1 起点，QEMU 里是真 RAM），或改这个参数指向我们控制的地址。
- ★但注意 `UdtrMain.sh:10 test -f /root/IAMLDUDWRT && return $MODE_PROD` ⇒ 用该旗标绕路会**顺带把 updater 模式变成 PROD**。所以离线要分两条线：A 线修表（保持 USER 模式语义），B 线用旗标探后段（明确标注它改了模式）。
`emmc.ko`（initrd 里的 `usr/kmod/emmc.ko`）：**ELF relocatable、not stripped**，源路径 `/home/9004041779/git-work/work_Updater_NB/Etools-eMMC_171H/driver/src/main/{controller/f_sdh30.c, plat-uz/uz_emmc.c}`；有 `al_req_count_init`/`al_req_count_set_discard_params`（**AL = Sony 的 Advanced Layout 层**，其上限校验：`size ≤ 0x400000`、`count > 511` 等）⇒ 反汇编里那些 `0x400000` **不是分区表地址**（§13 的那条要靠完整命令轨迹重新证实）。
initrd `/dev` 里 **66 个 nflash 节点**（`nflasha1..30` + `dnflasha1..30` + `dnflasha`）全是**静态节点**；另有 `mmca1..4 / mmcaa1 / mmcab1 / mmcac` 等 Sony eMMC 命名节点 ⇒ 下一步要查 `devno.ko` 与 `mmca*`/`nflasha*` 的映射关系。
另外 initrd 里有 `etc/VerificationKey.pem` 与 `usr/bin/{sdfileinput.elf, crypter.elf}` ⇒ **updater 阶段自己带着验签公钥**，这是对 §SIG_VERIFY_200「2.00 无 RSA 门」的一个补充线索，回头要查 `sdfileinput.elf` 是否用这个 PEM。

## 16. Round 9：`/dev/nflasha*` 出现、`mount /dev/nflasha2` 通过、**a15 读回哈希与真机一致**
**§13/§14 的矛盾解开了**：Round 8 打印的 `0x400000` 是 **QEMU 侧 boot 前缀**造成的（bionz.c 里 Sony BSP `boot_size=2MiB`×2）。驱动实际读的是 **USER 区字节偏移 0（USER LBA 0）**，也就是 **partinf 起点之前那 64 KiB 头区（EXBL 区）的第一个 sector**。真机 a1 从 `0x10000` 起 ⇒ 表当然不在 a1 dump 里 ✔（我 §14 的判据与 0 命中都成立）。

**分区表（反汇编推得、无 DWARF；QEMU 实测证实，置信度高）**
- 设备上就是 **512 B**：hdr `0x20` `{magic=ASCII "8246", version=ASCII "1.00", part_max=30(≤30), pad}`；**条目在 `+0x20`，16 B/条 `{start, size, type, flag(bit0=active)}`**，与 `partinf.conf` 30 行逐字一致。（Round 8 猜的条目偏移 `+0x40`、magic `"PTAL"` 都错。）
- `probe_post` 校验 `buf[0]==magic && buf[4]==ver && buf[8]<=30`；kmalloc 的 `ptbl_info`(0x218) 里 `+0x200` 放期望值副本。
- ★**`tbl=0x80000000` 是死参数**：全模块只有 `__param` 一处 xref，代码从不读 ⇒ 不需要往 RAM 预填（§15 的推测作废）。
- 驱动只用 USER 区，**没有任何 ext_csd 分区选择**（CMD6 仅 1 次、index=161，非 172/179/GP）。
**QEMU 现状（`a7c_emmc_pt4.img`：4 MiB boot 前缀 + Round7 镜像 + 表 @ 文件 0x400000）**
- 内核注册 16 个块设备；`/proc/partitions`：`nflasha=252:0`（**裸节点=整块设备**）、`nflashaN=252:N`、**`nflashaB0/B1=252:126/127`**（QEMU 的 boot0/boot1 前缀也生效）。
- `mount -t vfat /dev/nflasha2` 与 `mount -t ext2 /dev/nflasha15` **都成功**；不再有 72/73。
- ★**读路径证真**：QEMU 内 `dd if=/dev/nflasha15 bs=64k count=4 | md5sum = c325b0e201ddabb16c6c2b0eee5f0834` ≡ 真机 `work/l2-camera/nflasha15.bin` 前 256 KiB（a2 前 64 KiB = `810baf7da8d739fa7c4315c95e049e31`）。⇒ **真机数据 → 镜像 → QEMU eMMC → 闭源 `emmc.ko` → dd** 整条链一致（E1）。
- 新失败点：`backup.ko backup_init() error (file_load)`（文件层，不是 eMMC）→ Backup_* 符号缺失 → `Power IC type 255` → 继续到 `[VERSION] 100.101.014 / MODE=0` → **`sauu` page fault，PC=0xffffffff → kernel exception monitor**。
**对"a1 patch 路线"的新约束（重要）**
- 该 initrd 的 cramfs 是 **压缩版（Compressed ROMFS / deflate）** ⇒ **原地按字节 patch `sauu` 不可行**；必须重建 cramfs。Round 9 已验证可行路径：**7z 解包 → mknod 补 /dev 节点 → `mkfs.cramfs` 重建**，内核能挂（但 7z 解包有 2 个 sub-item 错误、个别 dev 节点丢失）。⇒ 真机若走这条路，"重建保真度"是一项要单独评估的风险。
- 表在 **USER LBA 0**，不属于任何 nflashaN 分区 ⇒ **改表/改 EXBL 区不是"写某个分区"能做到的**；要读它得用**裸节点 `/dev/nflasha`**（252:0，=整块 USER 区）。

## 17. Round 10：离线链收窄成**单点阻塞**（`backup.ko` 的 Data_check/Data_init），而且它和缺 dump 是同一件事
- **P0 `backup.ko file_load` 没修好，但失败域钉死了**：7 次对照（真机原样 `Backup.bin`+`.bak`、tmpfs 复制、pri/sec 同文件、magic 变异；两版模块：initrd 版 md5 `0a38eec6…`、a15 版 vermagic-patch 后 `638881c5…` 能 insmod）**全部**在 `backupfile_load()` 内失败 ⇒ 与 vfat/权限/簇链/文件差异无关，卡在 **`Data_check`/`Data_init`**：调用链 `backup_init → select_path → load_file(vfs_stat/vmalloc/filp_open/vfs_read) → Data_check → Data_init(hdr@0x0c 与模块内版本串比较，records = hdr@0x10 × 6)`。镜像 a2 区里的 `Backup.bin` md5 与真机一致，读路径无误。
- **P1 `sauu` 崩溃根因（E1）**：干净配置（r10i：loop-mount 原 initrd `cp -a` 保住全部真 /dev 节点 + MODE=0）里 sauu 过了 `Begin main()` 才崩，内核解码器指到 **`mcmn_log_init @ libInfraMediaCommon.so:0x1d00a`**（由 `mcmn_list_get_node_count:0x1c9da` 调），page fault at **0xffffffff**（r4/fp=0xffffffff, r10=0xaa55）。与 Round 9 的 `PC=0xffffffff`、r10f 的 **`FixedAreaTop/Size: FFFFFFFF`** 同源：**Backup/FixedArea 没拿到 ⇒ 0xffffffff 哨兵被当指针/跳转目标**。⇒ 修好 backup 数据层就放行 sauu 状态机。
- **★与真机 dump 的闭环**：镜像里 `boot0/boot1` 与 **USER 0x0–0x10000（真分区表 + 可能的 FixedArea）**全是零，因为**还没 dump**。所以"离线 R1 演练"的上限 = "真机只读补 dump"的下限，同一件事 ⇒ 真机那步（`tools/bootarea_run.sh`：`nflashaB0/B1` + 整块 USER 区取头 64 KiB）现在是关键路径。
- **P5 逐分区来源表**（pt4）：FULLMATCH=真机 dump `a2/a4/a6/a7/a10/a13/a23`；官方包 `a3/a5`；合成空 vfat `a11/a12/a17/a18`；全零 `a16`；**`a1` 区是旧的不完整 dump，`0x3F0000` 起有洞 ⇒ 可用 `work/l1-camera/nflasha1.bin` 回填**；`boot0/1` 与 `USER 0–0x10000` 未 dump（全零）。
- **cramfs 重建保真度（更正 §16 的手法）**：`7z` 解 cramfs 会把 `/dev/*` **降成普通文件** ⇒ 之前 r10b/c/f 的部分报错是假象。干净手法 = **loop-mount 原 initrd → `cp -a` → 改 → `mkfs.cramfs` 重建**（`initrd_r10i.img` md5 `0fbf9bb6…`）。⇒ 真机 a1-patch 路线要用这个手法，别用 7z。
- 基线完好：`bionz.c 87febf2b…`、`sd.c e13776d0…`、QEMU `d4103e35…`、`pt4 85876746…`、Round 9 日志未动。产物 `work/qemu-a7c/results/round10/`（`FINDINGS.md`、`run_r10.sh`、`r10_r10a…i.ser`、`initrd_r10i.img`、`backup_15p.ko`、`bk_dis.txt`/`text_ann.txt`、`p5.py`）。
- 下一轮（Round 11）输入清单：①真机 `nflashaB0/B1` + `USER 0–0x10000`（拿到就能填 FixedArea/真表）②回填 a1 区③重试 `backup.ko` → sauu → 真写一次低价值分区（P2/P3 未做，被 P0 吃掉时间盒）。

## 18. Round 11：★离线**写路径已证到 R1**（闭源驱动写分区 + 冷重启后仍在）
**做成了什么（r11f → r11g）**
- 往 `/dev/nflasha23`（Sony AL_EMMC 驱动，major 252/minor 23）写 64 KiB 随机图案：`R11-DD-RC=0`，立即读回 md5 `5c5a00ec…` == 图案；**QEMU 冷重启后新开机的校验读仍是同一 md5** ⇒ 写持久化。宿主侧确认图案落在镜像文件偏移 **`0x50C00000`**（= `0x400000` boot 前缀 + `0x50800000` a23 起点）。
- ⇒ **"真机数据 → 镜像 → QEMU eMMC → 闭源驱动 → 写 → 重启后读回"闭环成立**（E1/R1）。这是恢复故事里最硬的一块离线证据。
**根因结论（把 Round 10 的单点再往前推了一层）**
- H3 证实：`BK4` 串匹配，不是失败原因；`ud_im.elf` 确实起来了，且 `file_load` 路径里没有 OSAL 调用 ⇒ **Round 11 否掉了我上一轮的 H1 假设**（诚实记录）。
- ★**cookie 不同**：rescue/updater 侧 `backup.ko`（`0a38eec6…`）期望 cookie **`0x9000e1a0`**，而真机文件里是 **`0xaaaaaaaa`**；**a15 产品侧模块**才期望 `0xaaaaaaaa`。把原生 ko 里 **5 个 cookie 比较点**全改掉 ⇒ **仍然失败** ⇒ `Data_init` 还有别的门（表/校验和）。
- **`backup.ko` 没有软失败**：把 `bl backupfile_load` / `bl backup_senser_init` 直接 `mov r0,#0` 绕过（`.init.text+0x148/0x1d0`）⇒ 立刻 NULL 表崩溃（r11d）。
- ★**`sauu` 崩溃的链条是硬的**：`mcmn_log_init`（`libInfraMediaCommon.so:0x1d00a`）解引用 `0xffffffff` = `MAP_FAILED` 的链表基址；**USER 模式不会 insmod `mcmn_drv.ko`**，而 `mcmn_drv.ko` 需要 **7 个 `Backup_*` 符号** ⇒ `sauu` ↔ `backup.file_load` 绑死。另：`sauu` 出错后内核 Exception monitor 会**冻住控制台** ⇒ 诊断脚本要把"写"放在 `sauu` 之前做。
- `ud_reboot.elf` 在 QEMU 里 RC=255；busybox `reboot` 打 `Restarting system.` 但 cxd90045 机器不自复位（靠外部重启 QEMU = 遗留缺口）。busybox 有 `md5sum/cut/kill/sleep`，**没有 `cksum/cmp/timeout`**（坑过一次 r11e）。
**仍未定（下轮）**：`Data_init` 过 cookie 之后的门（表/校验和）没吃透 ⇒ "正经链"`backup → mcmn_drv → sauu 状态机` 还通不过；**真机 USER 更新时 backup 是不是也这样"死着"跑完（H2）仍未证**。
**顺带（真机侧）**：a6 里有 `CDiAdjCtl::ReadBackup/WriteBackup/ReadBackupSize` 与 `libbackup.so` 引的 `Backup_read/Backup_write/Backup_get_datasize` ⇒ Backup 区读写在 senser 服务里有**结构化原语**（DIAC 字典里可见 `FACTORYDEFAULT_BACKUP_CONFIG`、`AFADJ_FORMAT` 等 ADJ 族命令），但它不在我们已知的 19 个 Jiritsu opcode 里 —— 别当成可直接调的命令。

## 19. Round 12：正经链通了；但**上一轮（R11）的 cookie 结论被推翻**（诚实记录）
- ★真因是**参数语义**：`backup_init` 把模块参数 **`Backup_load` 的值**传进 `backupfile_init`。`Backup_load != 1` 时 `Data_init` 取 **`arch_phys_to_cache(hdr+0x00)`** 的 **RAM**（**不重读文件**）⇒ R11 那些"改 cookie / 换文件 / 换 FS / tmpfs"实验全都打在无关路径上。
- 我本地复核并补上一等证据：真机 `Backup.bin`（1,210,408 B，md5 前缀 `7a549d06`）的 **`hdr+0x00 = 0x02e80000`** ⇒ **第一个 u32 就是 RAM 物理地址**，与 `arch_phys_to_cache(hdr+0x00)` 完全对上；`hdr+0x04=0xaaaaaaaa`、`+0x08=1`、`+0x0c="BK4"`、`+0x10=750`。⇒ **真机 updater 正常分支是从 RAM 里的这份 blob 取 Backup**（主系统/EXBL 预置），`Backup_load=1` 才是"从文件读"的救援分支（`insmod.sh` 里 `IAMLDUDWRT` 分支正是 `Backup_load=1 Backup_save=0`）。
- 用 `Backup_load=1 Backup_save=0` + **未改一字**的真文件 ⇒ `insmod` RC=0、**38 个 `Backup_*` 进 kallsyms**、不再打 `file_load` 错。`mcmn_drv.ko` insmod **RC=0**、major **249** 与真节点 `/dev/mcmn (c 249,1)` 匹配、open OK、`mmap` = **ENOSYS**。
- `sauu` **不再崩**，走到 **`BeginningState → WaitingConnectionState`** ⇒ 卡在"需要 PC 侧 USB"（QEMU 无 gadget 模型，`connection.val=0`）。
- `mmc_drv.ko` 需要 `pcie_slot_ctrl/root_ctrl` ⇒ 内核得开 **`CONFIG_CXD900X0_PCIE2_DME`**；注意 **别用 gcc-9**（3.0.27 在 `BUILD_BUG` 挂），沿用 gcc-6.4 Bootlin 配方。
- QEMU 侧新增 **reset hook**：`bionz.c` **md5 变为 `139a86cb…`**（旧源码备份 `…r11.bak`；`87febf2ba7fc4f19aa05ed1829edf804` 是 hook 前的版本），新二进制 `35b2e30c…`；用基线源码重编的二进制与旧 `d4103e35…` 逐字节一致 ⇒ 可还原。guest 侧 `arch_reset()` patch 已写好（`kernel-reboot-hook.patch`，写 `0xf240f004`）但还没编进内核。
- 另：模块里 `0x9000e1a0` 出现 **5 次**、`0xaaaaaaaa` **4 次**（我本地字节扫描）⇒ R11"期望 0x9000e1a0"与 R12"全是 0xaaaaaaaa"**都不完整**；别再从 cookie 字面量推语义，以**行为实验**为准。

## 20. Round 13：离线已到"只能靠真机补数据"的边界
- **A 保真成功**：bionz 新增 `A7C_RAM_BLOB` 把**未改一字**的真机 `Backup.bin` 预填 **PA `0x02e80000`**（注册成 rom，复位自动重灌）⇒ **原生 `insmod backup.ko Backup_save=0` 一字未改：RC=0、38 个 `Backup_*` 进 kallsyms、无 `file_load` 错**；不预填的对照 RC=5/0。
- ★**出厂 a1 命令行的 `memrsv=0x75e000@0x02E68000` 已覆盖该区**（`EJ_CLEAR_MEMORY` 只清空闲页）⇒ 不用加参数；这也**反向证实**真机就是"主系统把 serial-cfg blob 预置到 `0x02e80000`，updater 正常分支从 RAM 读"。
- 注意：QEMU 里 `/dev/mem` 读出的 RAM 头 64 KiB md5 ≠ 文件头 64 KiB（E2）⇒ 真机 RAM 是**活副本**（运行期被改），要真机 RAM dump 才能定。
- **B**：`ksrc-r13`（gcc-6.4 配方）把 Kconfig 里 `PCIE2_DME` 的 `!CXD900X0_QEMU` 依赖去掉重编（config diff 仅 +1 行），`System.map` 出现 `pcie_root_ctrl/pcie_slot_ctrl` ⇒ **`insmod mmc_drv.ko` RC=0**，但 **QEMU 没有 Sony SD host（PCIe-DME 通道）** ⇒ mmc_drv 装载了但**没有后端**。
- **C 闭环**：R12 的 hook 在这棵 QEMU 树触发 `qapi_enum_lookup` assert（本树枚举无 host-reset）⇒ 改成 `shutdown_request(GUEST_SHUTDOWN)` → exit 0 → wrapper 同镜像重拉；guest 里 `reboot` 的 writel 要挪到 `arch_reset_core` **之前**（`pm_machine_reset` 不回返）。结果：**boot1 写 a23 → guest 自己重启 → boot2 读回同一 md5 `ef59d910…` 打 `REREAD-OK-AFTER-GUEST-REBOOT`**（两组复现；boot2 里 backup 正常分支仍 RC=0/38）。⇒ **R1 更强了：写 + guest 内重启 + 重启后重读，全程离线**。
- **D（mode5）**：`/setting/updater/mode5` → `[DETAIL] MODE=5` → `insmodMediaDriver` 两模块 RC=0 → `exec sdfileinput.elf` → 内核 `MMC:Failed mcmnd_api_getbkupinfo_bus_connect_type` ⇒ **`[FIRMUP NG] Error 77`**（**77 不在 `common.src` 错误表里**，来自 mcmn/sdfileinput 层；a15 里该串旁边是 `Force Local bus` ⇒ **卡槽总线类型来自 Backup/serial-cfg 信息**）。合成 vfat 卡（`BODYDATA.DAT` = 猜壳 FDAT + 官方包 `udtrbody.bin`）放在 a10。**验签没到**，但机制钉死（E1）：`VerifySignature = SHA256(body−0x100)` + `RSA_verify(NID_sha256)`，公钥 = initrd `/etc/VerificationKey.pem`(RSA-2048)，卡上头带 256 B 签名。
- md5 记录：`bionz.c 32dbbd76…`（R12 源码备份 `.r12.bak`；R12 版是 `139a86cb…`）、QEMU 二进制 `e3ae292c…`、新内核 `vmlinux.bin 5ad80118…`、initrd r13a/c/d/g = `72494113/6ac3d395/d3c67bb8/22ddef6b`、卡 `ce716b69`、`BODYDATA.DAT 4e6f45fa`、实验盘 `a7c_emmc_r13{,_m5}.img = c84208c9/d526e5f0`；**基线 pt4 `85876746…` 未动**。

---
## Round 15 结果：mode5 现在真的在流读官方 `.dat`（桩的两个真 bug 修掉了）
产物：`work/qemu-a7c/results/round15/{FINDINGS.md,R15_POSTMORTEM.md,r15_p5_boot1.ser}`；远端 `~/qemu-a7c/results_round15/`、`results_round16/R15_POSTMORTEM.md`。
新 md5：`r15fshim.c 6276f75f…`、`r15fshim_r15e.so b95ba49e…`、`initrd_r15e.img 34a654e2…`、卡镜像 `a7c_emmc_r15v203.img c95b9ac0…`、负样 `a7c_emmc_r15neg.img a0696f90…`；基线 `a7c_emmc_pt4.img 85876746…` ✓ 未动；本轮 QEMU/`bionz.c`/`sd.c` 一字未改。

**桩的三个坑（都已实测修正，写下来免得再踩）**
1. `r14fshim_*.so` 是**宿主 gcc 编的、带 `GLIBC_2.34`** ⇒ guest（3.0.27 glibc）拒载。要交叉编到相机那套 glibc/ABI。
2. **`Fsys_FindFirst` 真签名是 3 参**，且**必须把找到的路径写回第 1 个参数的缓冲区**；按 2 参写会 page fault（`@0x80`）。
3. **`Fsys_Seek` 第三参不是 `SEEK_CUR/END`**：实测传参 `(1,20,20)` ⇒ 按**绝对 SET** 实现才对。改对之后：`42 → 86 → found FDAT`。

**Error 42 / 86 的出处（不在 shell 错误表里，是 `LEDErrorConverter::Convert(ApiException 0x3000x)` 映射出来的用户码；打印点 `common.src:74`）**
- **42** = `SDUUDConditionChecker.cpp:130` **"Firm size is larger than buffer size"**（chunk 长度是垃圾）
- **86** = `SDFileInputUpdaterManager.cpp:178` **"not meet UUD conditions"**
⇒ 两者都属**条件检查阶段**，与读文件/摘要/签名/写分区无关。

**mode5 的写表（512 B/条，去重后只有 11 条）**：全部落在 **index1=`a2 /setting`**（`rel 0x800200/0x800a00/0xc10a00`，宿主 `+0x400000`）= vfat 引导/FAT/目录（我们注入 `mode5` 旗标 + `comp` 触发 `rm -rf mode*`），其余 8 条在 **index10（`rel 0xb800000` → `/dev/nflasha11`，宿主 `0xbc00000`，注意不是 `0xc000000`）** 的卡切片里（`0x2e000` = vfat 根目录项，`open()` 的副作用）。
⇒ **mode5 至今没写过任何固件分区**（a1/a3/a10/a15/a23·PMBP 全 0 写）；**出厂 `comp` 会删 `mode*` ⇒ 旗标每轮必须重注入**。

**p6 = 卡上换成官方 2.03 `.dat`（未改一字）后**：UUD 门**通过**（`Old 2.0 / New 2.3 / Model 0x91030019 / Region 0x0000`），第二次走链后 **`ZZSDREAD` 涨到 639,925 条 ≈ 327 MB = 整个 `FDAT` 正在流进来**（写仍只有 3 条 a2）。⇒ **读卡+解容器+条件检查这半条链已经真跑通**；验签与写分区是下一问。

**负样准备**：卡切片只有 2 个扇区与正样不同（`0xbc2e000` 目录项=跑脏，须排除；`0x1bc00000`），挂载后逐字节对文件 ⇒ 首个不同**文件偏移 `0xffcc0dc`（268,222,684）**，`de→c3`，落在 **FDAT payload 的签名消息区（密文体）内**、不在签名区（签名 `0x14a2b0ec..0x14a2b1ec`）✓ ⇒ 运行时应当 **FAIL**，这是 L3 的关键判据。
