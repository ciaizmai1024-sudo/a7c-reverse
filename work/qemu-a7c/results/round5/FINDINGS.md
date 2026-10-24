# Round 5 FINDINGS — M4 卡点定性完成：**不是缺外设，是「空向量页 + 内核 paging_init 尾部一次 NULL DataAbort」的 prefetch-abort 递归**；M10 前进最多

时限内完成 A（定性）+ B（M6/M7/M8a/M8b/M9）+ 追加 M10。bionz.c 本轮**未改动**（md5 仍
`11abc8c7d5a3c0ec0a50bfe4262e3c70`）。新 kemco：远端 `parts/kemco_m{6,7,8a,8b,9,10}.txt`
（本机 `work/cmdlines/` 同名），run 脚本远端 `~/qemu-a7c/run_r5.sh`、`run_m10.sh`、`qmp_forensics5.py`。

## A. 卡点定性（INT 档 = M4 + `-d int,unimp`，60s，`int5_int.log` 4.1GB 留在远端）
本 QEMU 构建 `-d` 列表**没有 `unassigned`**（`-d help` 里没有；基线比 5.1 旧），有 `int/unimp/exec`。

- **不是 DataAbort 级联**，是**纯 prefetch-abort 死循环**：全 log 35,848,113 次
  `Taking exception 3 [Prefetch Abort] ... IFSR 0x7 IFAR 0xffff1000`，**只有 1 次**真 DataAbort：
  ```
  AArch32 mode switch from svc to irq PC 0x6013fd50   ← cpu_init 的 IRQ/ABT/UND/SVC 栈设置(msr)，正常
  AArch32 mode switch from irq to abt PC 0x6013fd54
  AArch32 mode switch from abt to und PC 0x6013fd60
  AArch32 mode switch from und to svc PC 0x6013fd6c
  Taking exception 4 [Data Abort]
  ...with ESR 0x25/0x9600003f
  ...with DFSR 0x5 DFAR 0x0            ← 唯一真错：读地址 0
  Taking exception 3 [Prefetch Abort]  ← 之后全部是它，IFAR 恒 0xffff1000（×35848113）
  ```
  4 行 mode switch 是 `cpu_init+0x44..0x60`（setup_arch→setup_processor→cpu_init，早期）的
  `msr CPSR_c` 序列，QEMU 把它们记成 mode switch —— **异常 log 里没有其它任何异常**（无 IRQ、无 undef）。
- **`-d int,exec` 二次跑（25s，`exectrace.log` 已删，上下文存 `da_ctx.txt`）**抓到 DA 前后的 TB：
  ```
  Trace 0: [00000000/60443204/...]      bootmem_init+0x88c
  Trace 0: [00000000/60444884/...]      paging_init+0x534（紧随 bl bootmem_init）
  Taking exception 4 [Data Abort] DFSR 0x5 DFAR 0x0
  Trace 0: [00000000/ffff0010/...]      ← 数据abort向量(0xffff0010)被取指执行
  Trace 0: [00000000/ffff0400/...]
  Trace 0: [00000000/ffff0800/...]
  ```
  即：**VA 0xffff0000 向量页被成功取指但内容全 0**（0x00000000=`andeq r0,r0,r0`≡NOP），CPU 在
  向量页里滑 NOP（ffff0010→…→ffff0fff），到 **0xffff1000 取指翻译失败**（该页 PTE=0）→
  PrefetchAbort → 又进 0xffff0010 的空页 → 无限循环，PC/LR 冻结在 `0xffff1000/0xffff1004, abt32`。
- **没有任何 unassigned 访问参与死因**：`info mtree -f`（`mtree.txt`/`mtree_f.txt`）显示
  PA `0x132c00`（页表/blob）、`0x133000`（vector_page）、`0xdf7fe000`（线性窗尾）全部落在
  **`ddr0` (0–0x7fffffff RAM)**；`0xffff0000-0xffff5fff` = `bootrom`(RAM,可写)。**缺外设模型不是本卡点的原因**。

## B. 0xffff1000 / 0x132c00 / 0xdf7fe000 的归属
- Sony 内核把静态页表区放死在 PA（`System.map`: `pgtbl_area_begin=top_pmd_page=0x132000`，
  `vector_page=0x133000`，`swapper_pg_dir=0x134000`，`pgtbl_area_end=0x138000`；6016KB）。
- swapper_pg_dir[VA 0xffff0000 的 L1 项]（PA `0x137ffc`）= **0x132c01** ⇒ L2(coarse)表 PA=0x132c00；
  **R05=0x132c01 就是这个 L1 描述符值**。L2 表（PA 0x132c00..）实测全 0：`0xffff0000` 页的 PTE
  在 devicemaps 之后又被清/或不在该表；`0xffff1000` 的 PTE（0x132c10）恒 0 ⇒ PF。
- 向量页内容（PA 0x133000，`vectors.asm` 前半）= **4KB 全零**。原因链（源码 ksrc 只读证实）：
  `early_trap_init()` 在 **setup_arch 末尾**（`arch/arm/kernel/setup.c:1094`）把 vectors/kuser 拷进
  `vectors_page=vector_page`(PA 0x133000，**CONFIG_EJ_STATIC_VECTOR_PAGE=y**)；随后 `paging_init→
  devicemaps_init`（mmu.c:1571-1583,1636）`memset(vector_page,0)`+`memset(top_pmd_page,0)`+重建 PTE
  ——把刚拷的向量又抹零。真机上大概率没有「第一次 abort」所以无人踩这条；我们的配置触发了 DA，就永远出不来。
- `0xdf7fe000 = high_memory(0xdf800000) - 0x2000`（线性窗末端）；`0x132c00` = top_pmd_page+0xc00（页表区内部，见上）。
- 0xffff1000 本身：**不是 kuser helper**（3.0 helper 在向量页内 +0xfc0），就是空向量页的下一页首地址。

## C. 第一次真错（根因#1）：paging_init 尾部例程越界查 mem_section
`-d exec` 定位 DA 在 TB `0x60444884`=`paging_init+0x534`（`bl bootmem_init` 之后）的例程：
反汇编（`da_ctx.txt`+objdump）：`cmn r4,#0x60000001; addls r0=r4+0xa0000000 / addhi r0=r4+0xe0000000;
pfn=r0>>12; section=pfn>>16; r3=mem_section[section](表@0x604c3580); uxtb/addne; ldr r1,[r3]`
（604448b0，**无判空**）→ `uxtb r2=r0>>8`、`addne r3+= (r2&0xff)*16`。
死亡现场寄存器自洽：R04=0xdf7fe000(循环 r4=窗尾) → r0=0xbf7fe000>>12=**pfn 0xbf7fe**，R01=**0xb**=section，
R02=0xbf7=pfn>>8 ⇒ `mem_section[11]=0`（实测 mem_section[0..7]=0x60100000/…/0x6010f000 有效，[8..]=0）
⇒ `ldr r1,[0]` → DFAR=0。**该例程假定「尾部线性窗 VA 0xa0000000–0xdf7fe000 ↔ PA 0x20000000–0x7f7fe000」
（pfn=VA−0x20000000）**——正是真机 updater 的窗（0x20000000 起 :uc 窗 + bank1）；M4 的平坦窗
(0x60000000↔PA 0) 让它算出 pfn 0xbf7fe 越界。round3/4 那个「memset 写平坦窗末端」也是这个例程。

## D. 四档（+M10）结果（每档 `A7C_MAP=f`+对应 kemco，60s(9=120s)，SNAPEVERY=15）
| 档 | kemco 改动 | 结局 |
|---|---|---|
| M6 | 总 RAM 1.5G（`mem=512M@0`+`memrsv 0x1C000000@0x20000000:uc`+`mem=512M@0x40000000@1`） | **同一卡点**（R15=0xffff1000,ab t32；t=60 快照寄存器同形）⇒ 总 RAM/窗上限不是问题 |
| M7 | `cxd90014.bam=N` | **同一卡点** ⇒ BAM/memchk 使能不是 abort 来源 |
| M8a | 删 `exception.*`+`stack_usage=y`+`tmonitor.*` | 同一卡点 |
| M8b | 只删 `tmonitor.*` | 同一卡点 |
| M9 | `init=/bin/sh` | 同一卡点（死得比 initrd 识别早；`RAM disk`/`Freeing initrd` 未出现，ATAG_INITRD2 仍待验） |
| **M10** | **`mem=512M@0` + 删 `memrsv=0x20000000@0x20000000:uc` + `mem=1016M@0x20000000@1`**（bank1 挪到真机 :uc 窗基点） | **★前进最多**：无 0xffff1000 风暴；内核活到 t≥100s，**abort handler 真工作**：ring 见 `Internal error: Oops: 805 [#14] PREEMPT SMP`、`Unable to handle kernel paging request at virtual address 0000ffff / e59f312c / 20202044`（嵌套 oops 级联，[#14]=第14次进 handler）；t=100s 最终停在 `_raw_spin_lock_irqsave+0x90`（R13=0x60441fe0、R11=0x60441ff4 = **paging_init 栈里自旋**）。ring 里最后时间戳 0.470884。**未到 /init**（VFS/Run /init 未出现；M10 的 log_buf 不在 0x400000–0x600000 快照窗内，早期内容缺失） |
**未到达 /init**。前进最多 = **M10**（越过 prefetch 风暴，进入内核自身 oops/调度路径，最后在 paging_init 里自旋）。

## E. 下一步（优先级）
1. M10 系列继续调 mem 声明（bank1 基点/uc 窗 memrsv 保留但范围对齐），并取 M10 的**完整 ring**
   （先定位新 log_buf 地址：扫 `Linux version` 字符串跨 0–0x400000 与 >0x600000）看第一个 Oops 的 PC；
   paging_init 内自旋 ⇒ 查 nl/bootmem 锁死锁点（`nl_sem`?）。
2. 空向量页（真 config 也如此）使**任何** abort 变 PF 风暴 ⇒ 可给 QEMU 加个「0xffff1000 页 RAM alias」
   或改 bionz 预填向量，把 oops 变成可读 panic（或直接补 `0x132c10` PTE）。
3. 到 initcalls 之后再验 ATAG_INITRD2/`init=/bin/sh`。

## F. 产物
- 本机 `results/round5/`：`FINDINGS.md`、`int5_head.txt`/`int5_tail.txt`（异常 log 头尾）、
  `da_ctx.txt`（DA±exec TB）、`vectors.asm`（PA 0x133000 向量页=全0 + PA 0xffff0000 bootrom 跳板反汇编）、
  `mtree.txt`/`mtree_f.txt`、`ring_m{6,7,8a,8b,9}.txt`（合并质量差，卡点同形为准）。
- 远端 `~/qemu-a7c/`：`int5_int.log`(4.1GB，-d int 全量)、`fwdump5_{int,m6,m7,m8a,m8b,m9,m10}/`、
  `run5_*.log`(串口全 0 字节)、`run_r5.sh`、`run_m10.sh`、`qmp_forensics5.py`、`parts/kemco_m*.txt`。
- kemco M10（可用基线候选，md5 65c6d09b…）：见 `work/cmdlines/kemco_m10.txt`。
- 本机 bionz.c 无改动：md5 `11abc8c7d5a3c0ec0a50bfe4262e3c70`（远端同）。
