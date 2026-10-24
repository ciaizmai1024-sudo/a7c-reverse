# Round 7 FINDINGS — 用出厂 .config 编内核（V3）+ **破案：nodeorder_init 死循环是 gcc builtin-memset 与 Sony memset 返回约定的冲突** ⇒ 到达 `VFS: Mounted root (cramfs)`

## 0. 一句话结论
出厂 `.config`（`work/sony-src/config-shipped-2.00`，md5 `18a3664120dabd38e41f042168589136`）+ 只开 `CONFIG_CXD900X0_QEMU=y`，
用 gcc 6.4 编出的 **V3**（`_text=0x60108000`，真机装载地址 `0x108000`）在 **`A7C_MAP=g` + a1 kemco 逐字** 下
先复现 round6 的 `nodeorder_init` 踩穿窗顶（首错 DA `DFAR 0xdf800008`），**根因查明**（见 §3），
加一个编译开关 `-fno-builtin-memset`（**不改一行源码**）后一路跑到：
```
RAMDISK: cramfs filesystem found at block 0
RAMDISK: Loading 4700KiB [1 disk] into ram disk...
VFS: Mounted root (cramfs filesystem) readonly on device 1:0.
Freeing init memory: 176K
```
且 rootfs 里的 **`UdtrMain.sh` / `mkramdsk.sh` / `init` / `freeramdisk` / `ud_darwin_init.elf`** 全部在环里可见（= a1 updater 根文件系统真的挂上了）。

## A. 编译期 DDR 常量（原文 + 判定）
文件：`arch/arm/mach-cxd900x0/include/mach/memory.h`（本机树只有这一个 A7C memory.h；`mach-cxd90014/` 只有 Kconfig，没有 `include/mach`；`mach-emxx`/`mach-ne1` 是别的 SoC 的）。
```
33  #define PAGE_OFFSET		UL(CONFIG_PAGE_OFFSET)
42/44  #define PLAT_PHYS_OFFSET	UL(DDR0_BASE)
47  #if defined(CONFIG_SPARSEMEM)
49  #define SECTION_SIZE_BITS	CONFIG_SNSC_SPARSE_SECTION_SHIFT
52  #define MAX_HOTPLUG_MEM	(CONFIG_CXD900X0_SIZE_DDR0+CONFIG_CXD900X0_SIZE_DDR1)
54  #define DDR0_END	(DDR0_BASE + CONFIG_CXD900X0_SIZE_DDR0)
55  #define DDR1_END	(DDR1_BASE + CONFIG_CXD900X0_SIZE_DDR1)
56  #define VA_DDR0		PAGE_OFFSET
57  #define VA_DDR1		(VA_DDR0 + CONFIG_CXD900X0_SIZE_DDR0)
58  #define VA_DDR1_END	(VA_DDR1 + CONFIG_CXD900X0_SIZE_DDR1)
65  #define __phys_to_virt(x)	((ulong)(x) < DDR1_BASE ? (x)+VA_DDR0 : (x)-DDR1_BASE+VA_DDR1)
68  #define __virt_to_phys(x)	((ulong)(x) < VA_DDR1 ? (x)-VA_DDR0 : (x)-VA_DDR1+DDR1_BASE)
```
`arch/arm/mach-cxd900x0/include/mach/platform.h:31,33,34,35`：`DDR0_BASE 0x00000000`、`DDR0_SIZE 0x80000000`、`DDR1_BASE 0x80000000`、`DDR1_SIZE 0x7e000000`（硬编码，仅 bam.c 用）。
`arch/arm/mach-cxd900x0/Kconfig:38-49`：
```
config CXD900X0_SIZE_DDR0  hex "Size of DDR0"  default 0x40000000
config CXD900X0_SIZE_DDR1  hex "Size of DDR1"  default 0x10000000
config CXD900X0_TEXT_OFFSET hex default 0x008000
```
⇒ **DDR 大小是 CONFIG 常量**（不是硬编码），`mach/vmalloc.h:47`：
`VMALLOC_START = PAGE_OFFSET + SIZE_DDR0 + SIZE_DDR1 + 8M`。

两份 config 对比（出厂 `config-shipped-2.00` vs 我们的 V3/kb-qemu）：
| 符号 | 出厂 | V3（出厂+QEMU） |
|---|---|---|
| `CONFIG_PAGE_OFFSET` | 0x60000000 | 同 |
| `CONFIG_CXD900X0_SIZE_DDR0` | **0x40000000 (1 GB)** | 同 |
| `CONFIG_CXD900X0_SIZE_DDR1` | **0x10000000 (256 MB)** | 同 |
| `CONFIG_CXD900X0_TEXT_OFFSET` | 0x00108000 | 同（V3 `_text=0x60108000`）|
| `CONFIG_CMDLINE_PHYS_OFFSET` | 0x00103000 (`_ENABLE=y`) | 同 |
| `CONFIG_CXD900X0_QEMU` | not set | **=y**（select `SIMPLE_LOADER/SIMPLE_SUSPEND`，关 `HWBP`/`PCIE2_DME`/`ARM_DAP`）|
| `SPARSEMEM/EXTREME/ALLOC_MEM_MAP_TOGETHER` | y | 同 |
| `SNSC_SPARSE_SECTION_SHIFT` | 20 | 同 |
| `SNSC_MAX_NODEORDER / NODES_SHIFT` | 8 / 4 | 同 |
| `HIGHMEM` | 无 | 无 |
| `BLK_DEV_INITRD / BLK_DEV_RAM / CRAMFS` | y / y(`RAM_SIZE=4096`) / y | 同（V3h 改成 8192，见 §5）|
| `EJ_STATIC_VECTOR_PAGE` | y | 同 |
| `CONFIG_LOG_BUF_SHIFT` | **13（8 KB 环！）** | 13（诊断档 17/21）|

**A.3 结论（自洽性）**：编译期 DDR1 窗口 = 256 MB ⇒ `VMALLOC_START=0xB1000000`、`VA_DDR1_END=0xB0000000`。
- **a2 主系统** cmdline 的 `mem=256M@0x80000000@1` **与出厂 config 严格自洽**（`high_memory=0xB0000000 < VMALLOC_START`）。
- **a1 updater** 的 `mem=1016M@0x80000000@1` 与出厂 config **不自洽**（`high_memory=0xDF800000` 越过 vmalloc 区）⇒ **真机 updater 阶段跑的是另一个 .config 编出来的内核**（`SIZE_DDR1=0x3F800000` 量级），GPL 给的这份是主系统那份。
- **但本轮实测：这个不自洽并不是崩溃原因** —— C1(bank1=1016M) 首错 `DFAR 0xdf800008 = high_memory+8`，C2(bank1=256M，QEMU DDR1 也只给 256 MB) 首错 `DFAR 0xb0000018 = 同一个 high_memory 的等价位置`；两者死法一模一样，都是"越过线性窗顶"。真正的根因见 §3。

## B. V3 构建（out-of-tree 拷贝，源码树只读）
`~/qemu-a7c/ksrc-v3` = `cp -a ~/sony-src/linux-7c-200/linux` 后 `make mrproper`（`make O=` 在 3.0.27 被 `prepare3` 拒绝：源码树里有 `.config/include/config`，"is not clean"）。
`.config` = 出厂原文 + `scripts/config -e CXD900X0_QEMU` + `yes "" | make oldconfig`（无 olddefconfig）。
工具链：`~/sony-src/armv7-eabihf--glibc--stable-2018.02-1/bin/arm-linux-`（gcc 6.4.0）+ `LD_LIBRARY_PATH=~/sony-src/mpfr4/usr/lib/x86_64-linux-gnu`（否则 `libmpfr.so.4` 找不到）。
产物：`arch/arm/boot/vmlinux.bin` = **3,993,984 B 未压缩**（`CONFIG_SNSC_BOOT_BIN=y`）。

V3（严格出厂 + QEMU，无其它改动）关键符号（`V3-System.map`）：
```
_text = 60108000 (PA 0x108000)   pgtbl_area_begin/top_pmd_page = 60102000 (PA 0x102000)
vector_page = 60103000 (PA 0x103000)  ← 与 CONFIG_CMDLINE_PHYS_OFFSET 同一页（loadaddr.txt 第三值 0x103000 由此确证）
swapper_pg_dir = 60104000 (PA 0x104000)
__log_buf = 604e32a8 (PA 0x4e32a8, 长 1<<13)  log_buf_len = 604c5b80  high_memory = 604e8074 (运行时写)
```
`BLK_DEV_INITRD=y / BLK_DEV_RAM=y / BLK_DEV_RAM_SIZE=4096 / CRAMFS=y` 全开。
构建必须的最小补丁：`pcie_link_fix.patch`（见 §6）。

## C. 各档实测（bionz.c `A7C_TEXT_OFFSET=0x108000 A7C_CMDLINE_OFFSET=0x103000 A7C_CMDLINE_FILE=<blob> A7C_PTEFIX=1`，initrd 仍在 PA 0x700000；三路：log_buf 环 / klog@0x034A0000 / `-d int`）
| 档 | MAP | cmdline | 内核 | 结果 |
|---|---|---|---|---|
| C1 | g(1 GB + 1016 MB) | a1 逐字 md5 `614f102b` | V3 出厂原样(环 8 KB) | 越过 paging_init/bootmem_init，**t≈2.0 s `nodeorder_init` 里 memset 游标失控**，首错 `DFSR 0x805 DFAR 0xdf800008`，之后 `do_page_fault↔do_translation_fault` 递归风暴（4 s 内 622 次 DA），最后 CPU 卡在 `__raw_spin_lock+0x88` 抢 `logbuf_lock`（R00=604e2e10）|
| C2 | **h**(1 GB + 256 MB = `CONFIG_CXD900X0_SIZE_DDR1`) | a1 逐字但 `mem=1016M@0x80000000@1`→**`mem=256M@0x80000000@1`**（`parts/kemco_a1_256.txt` md5 `cea0afa4`）| V3 | **完全相同的死法**：首错 `DFAR 0xb0000018`（= 该布局的 `high_memory+0x18`）。⇒ 256 MB 假说被否 |
| C3 | – | – | – | 见 §3（`nodeorder_init` 反汇编 + 边界）|
| C1f/C2f | g / h | a1 / a1-256 | V3 + `-fno-builtin-memset` + `LOG_BUF_SHIFT=21` | **完整启动到 VFS**：`Memory: 1024MB 1016MB = 2040MB total` / `console [ttyAM0] enabled` / `klog: initialize logging buffer: 0x00020000@0x034a0000` / `rootfs image is not initramfs …; looks like an initrd`，但 `INITRD: 0x00700000+0x00800000 overlaps in-use memory region - disabling initrd`（**是我把环改成 2 MB 把 bss 顶到 0x700000 造成的副作用**），`VFS: Unable to mount root fs on unknown-block(1,0)` |
| C1g/C2g | g / h | 同上 | V3 + `-fno-builtin-memset` + `LOG_BUF_SHIFT=17` | `rootfs image is not initramfs; looks like an initrd` → `Freeing initrd memory: 8192K` → **`RAMDISK: cramfs filesystem found at block 0`** → **`RAMDISK: image too big! (4700KiB/4096KiB)`** → `No filesystem could mount root, tried: ext2 cramfs vfat fuseblk` → panic。⇒ 差在 `CONFIG_BLK_DEV_RAM_SIZE=4096` |
| **C1h** | **g** | **a1 逐字** | V3h = V3 + `-fno-builtin-memset` + `LOG_BUF_SHIFT=17` + **`BLK_DEV_RAM_SIZE=8192`** | **到达 /init 阶段**：见 §5 |
| C2h | h | a1-256 | V3h | 同样到 `VFS: Mounted root (cramfs filesystem) readonly on device 1:0.`（`RAMDISK: Loading 4700KiB [1 disk]`），说明两种 bank 布局都能跑 |

`-d int` 抓取（各 4 s，4 千行级别，无 PrefetchAbort-`0xffff1000` 风暴；本轮 PTEFIX 已按 TEXT_OFFSET 推导到正确槽位 `0x102fc4/0x102fc8`，pte=`0x10367e`）：
```
C1: 0x9600007f DFSR 0x805 DFAR 0xdf800008   (第一个 DA，之后全是 DFAR 0 的递归)
C2: 0x9600007f DFSR 0x805 DFAR 0xb0000018
```

## C3. `nodeorder_init` 那个循环的边界（V3 反汇编，破案）
`mm/nodeorder.c:73-77`：
```c
for (i = 0; i < MAX_NODE_ORDER_NU; i++) {
        memset(nodeorder[i].node_num, -1, sizeof(nodeorder[i].node_num));
        nodeorder[i].ro_exclude_zl = NULL;
        nodeorder[i].rw_exclude_zl = NULL;
}
```
gcc 6.4 编出来的 `nodeorder_init+0xc..0x3c`（V3）：
```
ldr  r3, =nodeorder+8        ; r3 = 游标（node_num 在元素内 +8）
add  r5, r3, #684            ; r5 = 结束地址（9 个元素 × 76B）
loop: mov r0, r3 ; mov r2,#68 ; mvn r1,#0 ; bl memset
      add r3, r0, #76        ; ★游标 = memset 的返回值 + 76（gcc 用 builtin 语义：memset 返回 dst）
      str r4, [r0,#-8] / [r0,#-4]   ; 两个 zonelist 指针（在元素尾，故 -8/-4）
      cmp r3, r5 ; bne loop
```
内核里被调用的 `memset`（`arch/arm/lib/memset.S`，`0x6024f0a0`）**Sony 版把 r0 当游标推进、返回 `dst+len`**（`0x6024f0d0/0x6024f0d4: stmiage r0!,…`；结尾 `mov pc,lr` 时 r0 已 = dst+68）。
⇒ 每轮游标前进 `68+76 = 144` 而非 76，`cmp r3,r5` **永远不相等 ⇒ 无限循环**，游标从 `0x606e7ab8` 一路涨到线性窗顶之外 → `DFSR 0x805, DFAR = high_memory(+8/+0x18)`。round6 看到的"`nodeorder_init+0x18 ↔ memset` 每 +76 B 漂移"就是这里。
**真机不会这样死**：Sony 的交叉编译器（gcc 4.x）不会用 `memset` 返回值当游标。**要让它在我们的 RAM 布局里不越界，不用改 `mem=`、不用改 RAM 布局**：
`make KCFLAGS=-fno-builtin-memset` 后循环变成
```
add r5, r5, #76 ; str r4,[r5,#-84] ; str r4,[r5,#-80] ; cmp r5,r6 ; bne
```
（游标纯指针算术，与 memset 返回约定无关）⇒ 9 轮干净结束，boot 一路通过。
副作用范围：所有依赖 `memset` 返回值的代码都受影响（Sony 树里这类写法不少），所以这个开关是**全局修正**而不仅是绕过。

## D. 补丁 / 开关对照（纪律：unpatched 与 patched 都留了运行结果）
- **没有任何源码补丁**参与关键结论。`drivers/pci/probe.c` 的 4 个桩函数（`pcie_root_port_max_busnr/_pdc/_prsnt`、`pcie_port_perst`）是**纯链接修复**：
  `CXD900X0_PCIE2_DME` 因 `depends on PCI && !CXD900X0_QEMU` 在开 QEMU 后被关闭 ⇒ `arch/arm/mach-cxd900x0/Makefile:23` 不再编 `pcie.o`，而 Sony 改过的 `drivers/pci/probe.c:772`、`hotplug/pciehp_hpc.c:592,425`、`pciehp_ctrl.c:209` 仍引用。补丁文件 `pcie_link_fix.patch`（未加 Q 头，是手工贴的最小 diff）。
- **诊断性偏离（都在 config/命令行层面，非源码）**，代价是"不再与真机逐字节等价"：
  1. `KCFLAGS=-fno-builtin-memset`（关键；见 §3。这是编译开关，等价于换回 Sony 老 gcc 的代码生成）；
  2. `CONFIG_LOG_BUF_SHIFT=13→17`（可观测性；**注意 13 只有 8 KB 环**，递归风暴一冲就没了；21 会把 bss 顶到 0x700000 把 initrd 判成"overlap"）；
  3. `CONFIG_BLK_DEV_RAM_SIZE=4096→8192`（a1 的 initrd cramfs 实测 **4700 KiB**，出厂值 4 MB 装不下 ⇒ **出厂 .config 不是 updater 阶段那份**，又一佐证）。
- 对照结果：unpatched(V3，出厂原样) = C1/C2 死在 `nodeorder_init`；flag-patched(V3f/V3g/V3h) = 到 `VFS: Mounted root (cramfs)`。

## E. `em_console=0x200210ec` 的真身（结论：不是输出 mailbox，别再等它出字）
- `arch/arm/mach-cxd900x0/error.c:249`：`early_param("em_console", parse_adc_param)`（同一个 param 也吃 ADC/errind 参数），`error.c:400`：`em_console_enable_triggered = errind_console_enable_triggered`。
- `kernel/exception.c:881-882,1031`：`em_console_enable()/…_triggered()` 是函数指针，异常监控（EM）用它"要不要把 console 打开"。
- `drivers/tty/serial/amba2.c:987-988,1265`：`if (em_console_enable_triggered && em_console_enable_triggered()) …` —— **内核是"读"这个标志**（EXBL/monitor 在 `0x200210ec` 置位表示"错误监控要求开控制台"），不是往里写 FIFO。
⇒ bionz.c 里 ma1co 的 em_console 实现（写区域/握手位）与内核方向相反，**改 bionz 也不会让 stdio 出字**，本轮不动 bionz（除 §G 的两处必要修正）。串口 0 字节的真实原因另查：a1 cmdline 里是 **`amba2.console=0`**（a2 更用 `console=ttynull`），而本轮环里已出现 `console [ttyAM0] enabled` ⇒ 后续想拿真串口，只要把 `amba2.console=1` 塞进 blob（或看 `cfg.uart=15` 的门控），不必再刮 log_buf 环。

## G. bionz.c 改动（本地/远端 md5 一致 **`87febf2ba7fc4f19aa05ed1829edf804`**，已重编）
1. 新增 **`A7C_MAP=h`**（map 8）：DDR0 1 GB@0 + DDR1 **256 MB**@0x80000000（= `CONFIG_CXD900X0_SIZE_DDR1`），中间仍留洞。
2. **`A7C_PTEFIX` 按 `A7C_TEXT_OFFSET` 推导**（旧版写死 `0x132fc4/0x132fc8`，对出厂 `TEXT_OFFSET=0x108000` 是错的）：
   `L2 表 = text_off-0x6000+0xc00`，槽 `+0x3c0/+4/+8`（0xffff0000/1000/2000），pte = `(text_off-0x5000)|0x67e` ⇒ 本轮打印 `ZZPTEFIX: 0x102fc4/0x102fc8 = 0x10367e`。
3. 修一个 abort：出厂 `CMDLINE_PHYS_OFFSET=0x103000` 时，多余的 `cxd_init_cmdline("","" ,0x103000)` 占位会和 blob 的 rom 重叠 ⇒ `rom: requested regions overlap … qemu-system-arm: rom check and register reset failed`（直接起不来）。现在只在 `cmd_off != 0x103000` 时才补。
运行参数（本轮最优档 C1h）：`A7C_MAP=g A7C_TEXT_OFFSET=0x108000 A7C_CMDLINE_OFFSET=0x103000 A7C_CMDLINE_FILE=parts/kemco_a1.txt A7C_PTEFIX=1 -kernel ksrc-v3/arch/arm/boot/vmlinux.bin -initrd parts/initrd.img -drive if=mtd,file=a7c_emmc.img`。

## 关键日志（C1h，`ring7_c1h_full.txt`，log_buf 环 PA 0x4e32a8 / VA 0x604e32a8）
```
<5>[0.000000] Linux version 3.0.27_nl-rt106 (wubin@ubuntu) (gcc 6.4.0 Buildroot 2018.02) #7 SMP PREEMPT RT
<4>[0.000000] arm_add_memory: 0 0x0 0x40000000
<4>[0.000000] arm_add_memory: 1 0x80000000 0x3f800000
<4>[0.000000] bootmem_init: max_low=0x784384, max_high=0x784384
<5>[0.078583] Kernel command line:  ip=off initrd=0x00700000,0x00800000 root=/dev/ram0 rw noatime noalign init=/sbin/init … mem=1G@0 memrsv=1M@0 …
<6>[0.102932] Memory: 1024MB 1016MB = 2040MB total
<6>[0.323314] Brought up 1 CPUs      <6>[0.362673] Switching to clocksource cxd4105-freerun-timer
<6>[0.400217] uart0: ttyAM0 at MMIO 0xf2000000 (irq = 150) is a AMBA/PL011
<6>[0.401169] console [ttyAM0] enabled
<6>[0.383708] klog: initialize logging buffer: 0x00020000@0x034a0000, magic wrong nbit: 20(0x00000000)
<6>[0.377353] Trying to unpack rootfs image as initramfs...
<6>[0.381021] rootfs image is not initramfs (junk in compressed archive); looks like an initrd
<6>[0.405788] Freeing initrd memory: 8192K
<5>[0.487706] RAMDISK: cramfs filesystem found at block 0
<5>[0.488078] RAMDISK: Loading 4700KiB [1 disk] into ram disk...
<6>[0.560914] VFS: Mounted root (cramfs filesystem) readonly on device 1:0.
<6>[0.569073] Freeing init memory: 176K
<4>[0.569201] default_nodeorder is not valid. Force it to 0.
<6>[0.896346] ALFReD (v161102p2)   <6>[0.898134] eMMC: SDR mode
<6>[0.903378] eMMC: 1286MiB, Unknown PEF1G4 (rev 0x4d, date 0x15, serial 0x4c4b0001)
<6>[0.910368]  nflasha: unknown partition table
<6>[0.913261] partition table invalid
（环里同一页还能看到 rootfs 文件名：init / freeramdisk / UdtrMain.sh / mkramdsk.sh / ud_darwin_init.elf / ud_init_sio_port_setting.elf / us_darwin_init.sh）
```
再往后的日志停在 0.913 s 的 `partition table invalid`（t=30 s 快照）⇒ **下一个缺口 = eMMC 里的 nflasha 分区表格式**（`a7c_emmc.img` 里没有 Sony 的分区表；`nflasha` 驱动不读 DOS 分区表），不是内核内存管理。

## 下一步（优先级）
1. **nflasha 分区表**：给 `a7c_emmc.img` 造 Sony 的分区表（对照 mount.conf 的 a1..a23 尺寸），让 `/dev/nflasha*` 出现；ALFReD 已经在读我们给的 eMMC（"eMMC: 1286MiB"），只需喂对布局。
2. **回到出厂 `LOG_BUF_SHIFT=13` 的忠实档**再跑一次 C1h（环只有 8 KB ⇒ 必须 `SNAPEVERY=1`、并在 ~0.5 s 内抓）；`BLK_DEV_RAM_SIZE=8192` 建议保留（真 updater 内核几乎肯定是 8192 或 cmdline `ramdisk_size=8192`）。
3. 想要串口真出字：blob 里把 `amba2.console=0` 换 1（a1 原文是 0！）或查 `cfg.uart=15` 门控；现在 log_buf 环已经够用。
4. `default_nodeorder is not valid. Force it to 0.` ⇒ nodero/noderw/nodeorder 参数（真机可能在 a2/更后面的 blob 里）——若 updater 要按 node 分配内存，需要补 `nodeorder=` 参数（源码 `mm/nodeorder.c`）。

## 产物（本机 `work/qemu-a7c/results/round7/`）
- `FINDINGS.md`（本文件）、`pcie_link_fix.patch`
- `v3.config`（**严格出厂+QEMU=y**，md5 同远端 `parts/v3.config` `552da2e3…`）、`v3-config-logbuf21-nobuiltin.txt`、`v3h-config.txt`（+`LOG_BUF_SHIFT=17`+`BLK_DEV_RAM_SIZE=8192`）
- `V3-System.map`（md5 `bbc642eaa9a696cda381b12e54f9a681`）、`V3f-System.map`、`V3h-System.map`
- `vmlinux.bin.v3`（出厂原样，md5 `1c3f9486f2ca83daae8469d29476e12c`）、`vmlinux.bin.v3f`（`-fno-builtin-memset`+ring21）、`vmlinux.bin.v3h`（md5 `84c21ba31a640c30a42fb2e1ea3ce340`，**到达 cramfs root 的那份**）
- 环文本：`ring7_c1.txt` `ring7_c2.txt`（V3 原样，DA 风暴）、`ring7_c1c/c2c.txt`（ring17）、`ring7_c1d*.txt`（ring21，含 nodeorder 帧）、`ring7_c1f_full.txt` `ring7_c2f_full.txt`（ring21+nobuiltin，INITRD overlap）、`ring7_c1h_full.txt` `ring7_c2h_full.txt`（**Mounted root (cramfs)**）
- `kemco_a1_256.txt`（a1 逐字、仅 `mem=256M@0x80000000@1`，md5 `cea0afa4a035c2f86ba05e4c805242ce`）、`run_r7.sh`
远端 `~/qemu-a7c/`：`ksrc-v3/`（V3 树，含全部 .config 演化）、`parts/{vmlinux.bin.v3,v3f,v3h,V3-System.map,…}`、`fwdump7_{c1,c2,c1c,c2c,c1d,c1f,c2f,c1g,c2g,c1h,c2h}`、`ring7_*.txt`、`int7_{c1,c2}.log`、`ex7_c2.log`(8.2 M 行 `-d int,exec`)、`build_v3{b,c,c2,d,e,f,g,h}.log`。
bionz.c：本地 `work/qemu-a7c/qemu-sony/hw/arm/bionz.c` md5 **`87febf2ba7fc4f19aa05ed1829edf804`**（远端同，已重编 `arm-softmmu/qemu-system-arm`）。
