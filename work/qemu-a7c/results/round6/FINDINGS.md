# Round 6 FINDINGS — 权威地址布局查清 + 观测面修好（崩溃已变成可读 panic/oops）

bionz.c 本轮改动（`vectors_fix.patch`，基线 md5 `11abc8c7…` → 新 md5 **`df3a4c3b51e15da2f6a7e2fa0c3cddc8`**，本地/远端一致）：
新增 `A7C_MAP=g`（Sony 权威布局）+ `A7C_PTEFIX`（预填 0xffff1000/0xffff2000 PTE，实测被内核 boot 期清掉，无害保留）。

## A. 源码里的权威规则（全部 file:line 实证，树只读）

### A1. `arch/arm/mach-cxd900x0/include/mach/memory.h`（全文已读，33-71 行）
- `PAGE_OFFSET = CONFIG_PAGE_OFFSET`（两份 config 都是 `0x60000000`）；`PLAT_PHYS_OFFSET = DDR0_BASE`。
- `memory.h:47-69`（`CONFIG_SPARSEMEM` 分支，**Sony 自定义覆盖**）：
  - `SECTION_SIZE_BITS = CONFIG_SNSC_SPARSE_SECTION_SHIFT`（两份 config 都 `=20` ⇒ 1MB section；这就是 DA 反汇编里 `pfn>>8/=16` 的来由）。`MAX_PHYSADDR_BITS/MAX_PHYSMEM_BITS=32`。
  - `DDR0_END = DDR0_BASE + CONFIG_CXD900X0_SIZE_DDR0`（config 默认 `0x40000000`），`DDR1_BASE=0x80000000`（`mach/platform.h:31,34`），`CONFIG_CXD900X0_SIZE_DDR1=0x10000000`（出厰 config 与 kb-qemu 同）。
  - `VA_DDR0 = PAGE_OFFSET(0x60000000)`，`VA_DDR1 = VA_DDR0 + SIZE_DDR0 = 0xa0000000`；注释（memory.h:59-63）明写映射：`DDR0 0x00000000-0x3fffffff ↔ 0x60000000-0x9fffffff；DDR1 0x80000000-… ↔ 0xa0000000-…`
  - **`__phys_to_virt/__virt_to_phys`（memory.h:65-69）没有 bus_offset**：
    `x < DDR1_BASE ? x+0x60000000 : x-0x80000000+0xa0000000`，反向 `VA<0xa0000000 ? VA-0x60000000 : VA-0xa0000000+0x80000000` = **`VA − 0x20000000`**。
    **⇒ 死亡公式里的 `0x20000000 = VA_DDR1 − DDR1_BASE = 0xa0000000 − 0x80000000`**，是 DDR1 线性窗的固定 VA−PA 差，不是外设、不是 bus_offset。
- 含义：PA `0x40000000–0x7fffffff` 在真机是**洞**；线性窗是 `[0x60000000, 0x60000000+SIZE_DDR0] ∪ [0xa0000000, …]` 且 `__virt_to_phys` 只对「PA<0x40000000 或 PA≥0x80000000」自洽。**任何把 RAM 塞进 PA 0x40000000-0x7fffffff 的 QEMU 布局都会让宏不对称反算出野 pfn**（round5 M4 flat 2G 的死因正是 `__virt_to_phys(0xdf7fe000)=0xbf7fe000` → `mem_section[0xb]=NULL`）。

### A2. `adrs_conv` 是什么
`arch/arm/mach-cxd900x0/adrs_conv.c`（整机树唯一命中文件）：它是 **VA↔PA↔uncached 别名转换器 + `memrsv=` cmdline 钩子**，不是总线桥：
- `parse_memrsv_hook(start,size,type)`（:53）：`memrsv=…:uc/device` 类保留区把 `pa_uc[]/va_uc[]`（uncached 起点，默认 `DDR0_END/DDR1_END`，:50）往下拉——这正是 a1 `memrsv=0x20000000@0x20000000:uc` 的消费方（把 PA 0x20000000 起标 uncached）。
- `arch_va_to_phys/arch_va_to_noncache`（:100+）：`va<VA_DDR1 → va-VA_DDR0`；`va<VA_DDR1_END → va-0x20000000`；ESRAM 直通；失败打印 `ERROR:...` + `adrs_conv.debug=1` 时 `__backtrace()`、`=2` 时 `BUG`；`adrs_conv.null=Y` = `pass_through(0)`（把 NULL 直通不报错）。
- 调用时机：**运行期**驱动接口（DMA 描述等），不在 paging 之前；a1 不带、a2 带 `adrs_conv.debug=1 adrs_conv.null=Y`，两者都不影响 boot 成败（round5 M8b 已证 tmonitor 无关）。

### A3. `paging_init` 尾部那个「查 mem_section 不判空」的函数是谁
不是 Sony 私有函数——就是 **`paging_init()` 内联的 `empty_zero_page = virt_to_page(zero_page)`（`arch/arm/mm/mmu.c:1704-1705`，紧随 `bootmem_init()`(:1702)）**：
- 反汇编 `paging_init+0x534..0x538`（`objdump -d ksrc/vmlinux`）：`addls/addhi`（宏的两分支）→ `lsr r0,#12`(pfn) → `lsr r1,#16`（EXTREME 两级 mem_section 的 root 索引）→ `ldr r3,[r3,r1,lsl2]` → `cmp r3,#0` 只保护 `uxtbne/addne`（L2 子表内 `+ (pfn>>8 &0xff)*16`）→ **`ldr r1,[r3]` 无条件执行**（r3=NULL→DFAR=0）→ `bic r1,#3; mla r1,r3(#36),pfn,r1`（= `section->mem_map + pfn*sizeof(page)`，正是 `pfn_to_page`）→ `str r1,[r6,#28]`(empty_zero_page) → `bl __flush_dcache_page`（mmu.c:1706）。
- 即：Sony 定制 `__virt_to_phys` + SPARSEMEM_EXTREME 查表**无判空**；布局对（RAM 都在 PA<0x40000000 或 ≥0x80000000）就自洽，布局错就空指针。
- `bootmem_init` 本体在 `arch/arm/mm/init.c:736`（`high_memory=__va(...)` :875、`remap_node` :881、Sony 的 `bootmem_clear` :721/849 = round3/4「memset 窗尾」元凶）。

### A4. `CONFIG_EJ_STATIC_VECTOR_PAGE` 机制与缺口
- Kconfig：`arch/arm/Kconfig.ej:79`（`default y if ARCH_EJ`）。head.S:42-65：`PGTBL_AREA_SIZE=4K+4K+16K`；`top_pmd_page=PGTBL_AREA_BEGIN(0x132000)`、`vector_page=+0x1000(0x133000)`、`swapper_pg_dir=0x134000`——**向量页和页表都在内核镜像低端的固定 PA**（真机由 EXBL/bootloader 直载到 PA0，所以 PA=VA−0x60000000 定死）。
- `mmu.c devicemaps_init`（:1571-1583）：`vectors_page=vector_page; memset(vector_page); memset(top_pmd_page); __pmd_populate(pmd_off_k(0xffff0000), …)`；随后 :1618-1626 `create_mapping` 给 **VA 0xffff0000 建 PTE → PA 0x133000**，但**只有 4KB**；`0xffff1000` 的 PTE（L2 槽实测在 PA `0x132fc4`）恒 0。
- `early_trap_init`（traps.c:813-832，由 setup.c:1094 在 setup_arch **末尾**调用）才把 `__vectors_start/__kuser_helper` 拷进 vector_page。⇒ **`paging_init/bootmem_init` 之内发生的任何 abort 都在「PTE 有、内容全 0」的向量页上执行**：CPU NOP 滑过 `0xffff0fff` 到 `0xffff1000`（PTE=0）→ PrefetchAbort → 回 0xffff0010 全零页 → 35,848,113 次风暴（round5 实测）。
- QEMU 侧两条腿：(1) 别在 bootmem_init 里触发首个 DA（布局 g，见下）；(2) 预填 `0x132fc4/fc8` PTE（本轮 PTEFIX）——实测内核 boot 期把该 L2 槽清掉（`0x132fc4→0`，`0x132fc0` 内核自己重写 `0x13367e`），**预填会被抹**，所以布局修正才是根治。

### A5. 两份 config 差别（要点）
出厰 `config-shipped-2.00` 与 `cxd90045_qemu_nfs_defconfig`/kb-qemu 实测：两者 `PAGE_OFFSET=0x60000000`、`SPARSEMEM=y/FLATMEM 关`、`SNSC_SPARSE_SECTION_SHIFT=20`、`EJ_STATIC_VECTOR_PAGE=y`、`EJ_CLEAR_MEMORY=y`、`SNSC_MAX_NODEORDER=8`、`MAX_LOWPMEM/max_low_pfn` 无固定值（由 cmdline bank 决定）。差异只在 `CXD900X0_TEXT_OFFSET`：出厰 `0x00108000` vs QEMU-defconfig/kb-qemu/我们运行的 vmlinux = `0x138000`（bionz 默认已对齐），以及 shipped 无 `SNSC_SSBOOT` 段差异。**没有** HIGHMEM/MAX_LOWPMEM 类差异。
**真机 updater 阶段物理布局（唯一结论）**：kernel+页表+向量直载 PA0 窗内（TEXT PA 0x138000，pgtbl 0x132000-0x138000，向量页 PA=0x133000）；DDR0 1GB@PA0、DDR1@PA0x80000000（a1 用 1016MB=到 0xBF800000），线性窗 VA 0x60000000–0xDF800000 连续拼接，中间 PA 0x40000000-0x7FFFFFFF 是物理洞；`0x20000000` = DDR1 窗的 VA−PA 差 = 真机 bank1 `:uc` 保留窗基点。
**QEMU 应用的 RAM 布局（明确一条）**：`ddr0 = 1GB @0x00000000`，`ddr1 = 1016MB @0x80000000`，`0x40000000–0x7fffffff` 留洞，无 mirror/无 sram2 桩 = 本轮 `A7C_MAP=g`。

## B. 观测面修复 + 验证
bionz.c（patch 见 `vectors_fix.patch`）：
1. `A7C_MAP=g`：按 A5 布局（`case 'g': return 7` → ddr0=0x40000000、ddr1=0x3F800000、无 mirror、无 sram2、DDRC 寄存器自动对齐）。
2. `A7C_PTEFIX`（默认开，可 `=0` 关）：装载后向 `0x132fc4/0x132fc8` 写 `0x13367e`（把 0xffff1000/0xffff2000 指回 vector_page）。实测内核 devicemaps 会清这两个槽（保留代码无副作用）；根治靠 g 布局让 early_trap_init 得以执行、把真向量填进 PA 0x133000。
**验证（必须项，已做）**：C1(a1 逐字,map g) 到 start_kernel 的 `nodeorder_init`（kernel t=2.8s），崩溃全部以**带符号的 oops/backtrace** 落进 log_buf 环（PA `0x49fe88`，`log_buf_len=0x20000`）；C2(a2 逐字) 直接给出可读 panic：
```
<1>[0.576886] Unable to handle kernel NULL pointer dereference at virtual address 00000000
<1>[0.576892] pgd = 60134000
<0>[0.576903] Internal error: Oops: 805 [#14] PREEMPT SMP
<4>[0.577018] pc : [<60140d3c>]    lr : [<6015fb70>]    psr: 00000153
        pc = __bug+0x20   lr = vprintk+0x1dc        （System.map 符号化）
<0>[0.581526] Kernel panic - not syncing: Fatal exception in interrupt
<0>[0.574383] Kernel panic - not syncing: Attempted to kill the idle task!
```
无一次 PrefetchAbort-0xffff1000 风暴（C1/C2 全 log 无 `IFAR 0xffff1000`）。串口仍 0 字节（ttyAM 控制台未绑/早期 null），日志以 log_buf 环读取——这就是本轮的可读崩溃面。

## C. 三档实测（`A7C_MAP=g`，60s，三路：log_buf 环 / klog@0x034A0000 / -d int,exec）
| 档 | cmdline | 结果 |
|---|---|---|
| C1 | **a1 逐字**（`mem=1G@0`+`memrsv=0x20000000@0x20000000:uc`+`mem=1016M@0x80000000@1`，md5 `614f102b…`） | **最远**：越过 paging_init/bootmem_init，跑到 `start_kernel→nodeorder_init`（init/main.c:542）。首个真错（`-d int,exec` 抓取，log `int6_c1x.log` 2.6GB）：`Taking exception 4 [Data Abort] DFSR 0x805 DFAR 0xdf800000`（= `high_memory`，即线性窗最顶那一页之外）；最后 TB = `nodeorder_init+0x18/0x2c ↔ memset`（mm/nodeorder.c:60-85 的 memset 循环，寄存器显示 memset 的 dst 以 +76B/次扫过 0x7f85→0xaa45→0xd1ff→0xdd00…——`r3=memset返回+76` 与 Sony memset 返回值的漂移让这个循环不终止，一路踩到窗尾出界）→ `die→panic("Fatal exception in interrupt")` 级联可读。**未到 /init**。 |
| C2 | **a2 逐字**（含 `adrs_conv.*`、`mmu.dac=Y`、`cxd900x0.bam=N`、`mem=256M@0x80000000@1`、`initrd=0x700000,8M`，md5 `ef072ece…`） | 同样越过 paging_init；**可读 Oops/panic 全文**（见 B 引用）：vprintk 里 `BUG()`(@`__bug+0x20`，vprintk+0x1dc) → `Oops:805[#14]` → `Attempted to kill the idle task!` panic。环里先出现 `Unable to handle kernel NULL pointer dereference at 00000000`（嵌套 oops 级联）。**未到 /init**。 |
| C3 | M10 按 A 修正（`mem=512M@0` + bank1 挪回 `mem=1016M@0x80000000@1` = `kemco_m10g.txt`） | 退步：**回到 0xffff1000 PrefetchAbort 风暴**（终态 R15=0xffff1000/R14=0xffff1004）。环里最后日志停在 `bootmem_init: max_low=0x784384, max_high=0x784384`（init.c:797 之后），即 512M-bank0 + 1016M-bank1 时 paging_init 内部（sparse mem_map/node 放置）又触发了「窗尾/NULL」类首错（此时 early_trap_init 还没跑→风暴）。对比 C1 仅差 bank0=512M 与删 `:uc` 两处——下一步的判别变量。 |
C3 首个 Oops 的符号化 PC/LR：本轮快照拿不到（风暴早于第一个可读 oops 落环；环里最后有效行见上）。C2 的首个 Oops PC/LR 已符号化（`__bug+0x20` ← `vprintk+0x1dc`）。

## 结论与下一步缺口
1. **RAM 布局定论**：`A7C_MAP=g`（1GB@0 + 1016MB@0x80000000 + 中间洞）就是 Sony 宏/mem= 声明的自洽布局，已被 a1/a2 逐字验证能穿过 paging_init/bootmem_init。kemco 用 **a1 逐字** 为最优基线（跑得最远）。
2. 新缺口（按优先级）：
   - `nodeorder_init` 的 memset 漂移死循环（C1 死因）：怀疑 `memset` 返回值约定（`r3=r0+76`）——查 Sony `memset` 的返回语义 / `MAX_NODE_ORDER_NU` 循环在真机为何不漂；下一步用 `-d exec` 数 loop 迭代和 r0 返回值即可定位。
   - C3 里 512M-bank0 让 mem_map/node 放置撞窗尾 → 与 C1 的 0xdf800000 同族：Sony sparse/bootmem 把 mem_map 放**线性窗顶端**（实测 `~0xde5ee000`，`SPARSEMEM_ALLOC_MEM_MAP_TOGETHER`），窗顶由 max_low 决定——研究 `:uc` memrsv 是否存在与否如何改变 max_low/window 顶。
   - C2 在 vprintk `BUG()`：a2 早期 printk 路径（可能 `SNSC_NULL_CONSOLE`/loglevel 断言），需要取 a2 更靠前的环内容（加大 `log_buf_len=` 或读 boottime/klog@0x035A5000——本轮快照窗已含 0x03585000+0x48000）。
3. `/init` 未到达；缺口定性仍是内核早期（非 initramfs/dev 节点）。

## 产物
- 本机 `results/round6/`：`FINDINGS.md`、`vectors_fix.patch`、`rings6.txt`（C1/C1e2/C2/C3 环头尾）、`kemco_m10g.txt`、`kemco_a1_ni.txt`、`kemco_a1/a2.txt` 副本。
- 本机 `work/qemu-a7c/qemu-sony/hw/arm/bionz.c` md5 **`df3a4c3b51e15da2f6a7e2fa0c3cddc8`**（远端同，已重编 `arm-softmmu/qemu-system-arm`）。
- 远端 `~/qemu-a7c/`：`run_r6.sh`、`fwdump6_{c1,c1e2,c1x,c2,c3}/`、`int6_c1x.log`(2.6GB, -d int,exec)、`parts/kemco_m10g.txt`、`parts/kemco_a1_ni.txt`、`rings6.txt`。
