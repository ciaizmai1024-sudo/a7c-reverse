# Round 4 FINDINGS — updater 阶段：M4 越过 nodeorder_init，内存图结论 = 平坦连续（bank1 在 PA 0x40000000）

时间：2026-10-24（UTC+8）。远端 `~/qemu-a7c/`，QEMU bionz.c 最终 md5 **11abc8c7d5a3c0ec0a50bfe4262e3c70**
（上一版 8c19082b…）。所有 run 用**已编好的 Sony QEMU-defconfig 内核** `ksrc/arch/arm/boot/vmlinux.bin`
（raw，装载 `A7C_TEXT_OFFSET=0x138000`），initrd=真机 a1 `parts/initrd.img`@PA 0x700000，
`-drive if=mtd,a7c_emmc.img`，kemco 经 **新增 env `A7C_CMDLINE_FILE`** 逐字节写入 blob 区
`0x133000`（内核 `setup.c:setup_machine_tags()` 自己把 `\n`→空格并在 `\n*` 截断 ⇒ 真机文件可原样喂入；
日志确认 `cmdline override at 60133005`，4 条 memrsv + 两 bank 全部被内核接受）。

## 1. 各档结果（每档：内存图 + 结局）

| 档 | A7C_MAP (QEMU RAM) | kemco | 结局 |
|---|---|---|---|
| E0 | a：1GB@0 + 1016MB@0x80000000 + 0x60000000 alias | a1 逐字 | **不过 nodeorder**：与 round3 V2b 完全同形（`memset+0x2c` DataAbort → `do_translation_fault` 级联 → panic）。t=120s 环已被级联刷满 |
| M3 | **e（新）**：2040MB 平坦@0 + 1016MB@0x80000000（无 alias/sram2） | a1 逐字 | **不过**：同一级联（4.49s 刷满）→ **RAM 兜底不解决问题，缺的是内核页表（PMD）** |
| M1 | **f（新）**：仅 2GB 平坦@0（0x80000000 无 RAM） | a1 逐字 | **不过**：同一级联（7.3s 刷满）→ 内核不做 @0x80000000→0x40000000 的自我转换；按声明建映射 |
| M2 | b：1GB@0 + alias 0x40000000=PA0 镜像 + 1016MB@0x80000000 | a1 逐字 | round3 V1b/V2b 已判不过（本轮未重跑）——alias 窗假说排除 |
| **M4** | **f：2GB 平坦@0** | a1 逐字，仅改 **`mem=1016M@0x40000000@1`**（`parts/kemco_a1_m4.txt`） | **★越过 nodeorder_init**：完整早期日志干净（见 §2），跑到 zone 初始化/`free_area_init_node` 之后（`high_memory: df800000`，`Normal 0x0→0x7f800`，node0 127650 / node1 260096 pages）|
| M4b | 同 M4 + bootrom 0xffff0000 去掉 readonly | 同 M4 | 卡点不变（排除「写只读向量页」这一个假说） |

M4 卡点（t=10s 起死循环，到 t=100s 不前进）：`PC=0xffff1000, LR=0xffff1004, PSR=600001d7 (abt32)`，
R04=`df7fe000`（lowmem 尾）, R05=`00132c01`（≈PA 0x132c00|T，恰在 blob 0x133000 前 0x400）。
环形缓冲停在 `Normal zone: 257810 pages` 之后（`Memory:`/`Bootmem` 行未出，console 未注册所以串口全黑）。
下一步应查：内核 ssboot/warm/vector-stub 往 0xffff1000 放/跳桩，以及 `nodeorder/nl` 之后那次
「memset 到 lowmem 尾」例程（R04/R05 都指向它）——不是本轮已排除的内存图问题。

## 2. ★真机内存图结论（E0/M1/M3/M4 四档判别）
1. 内核**按 mem= 声明地址**建立线性映射与页表（M1 有 2GB 兜底但声明 @0x80000000 ⇒ VA 0xdf7ffffc 无 PMD，
   nl 的 memset（PC=memset+0x2c，向前 STMIAE，dst=平坦窗末端）即炸）。
2. **RAM 兜底/alias 都无效**（M3：PA 0x40000000–0x7F800000 与 0x80000000+ 都有 RAM，照炸；M2 镜像窗同理已排除）
   ——问题在内核页表覆盖，不在 QEMU 地址空间覆盖。
3. **唯一过法：把 node1 声明到 PA 0x40000000（M4）**，此时 lowmem 窗 `0x60000000–0xdf800000`（2040MB）
   与 RAM 完全一致。⇒ **updater 阶段真机上 DDR bank1 在“boot/平坦地址窗”里就在 PA 0x40000000**，
   kemco 的 `mem=1016M@0x80000000@1` 是 raw/EXBL 视角（EXBL 的 DDRC/地址映射把它搬到 0x40000000；
   `cxd90014.bam=Y` 经查是 bam=Bus-Activity-Monitor(memchk) 使能开关（`cxd900x0.c:319 module_param_named(bam…)`、
   `mach-cxd900x0/bam.c`），**不是**地址转换开关；主系统的 `adrs_conv.*` 才是另一套转换驱动）。
   注意 `memrsv=0x20000000@0x20000000:uc` 正好在 node0 的 1G 内抠出 0x20000000–0x40000000 ⇒ 真机平坦图
   = 0–0x20000000 DRAM + 0x20000000–0x40000000 :uc 窗 + 0x40000000–0x7F800000 = 恰好 1016MB（=bank1 大小）。
4. 可用 QEMU 配置（写死建议）：**M4 = 2GB 平坦 DDR@0（map f）+ kemco `mem=1016M@0x40000000@1`**；
   内核装载 0x138000、blob 0x133000、initrd 0x700000 全部不变。

## 3. 观测面结论
- **log_buf 环（PA 0x49fe88，ring 128KB）= 唯一可用路**；崩溃级联 ~20ms 内刷满环 ⇒ 必须
  `SNAPEVERY≤5` 或短 WAIT（M4 无级联，t=15 的快照就干净）。取环文本：
  `dd if=fwdump_<tag>/snap_XXXX_400000.bin bs=1 skip=654984 count=131072 | strings -a`。
- **klog@0x034A0000 全空**（klog 在 initcalls 才初始化；本轮全部死得更早）——updater 想用 klog 必须先过 initcalls。
- **em_console（mailbox 0x200210ec）未确认**：0x20020000 窗快照全 `0xFFFFFFFF`/零，内核死得早没写到
  `0x20021xxx`；串口全程 0 字节（console 注册在 initcalls，死前未到）。
- 串口 stdio：0 字节（同 round3，非回归）。

## 4. 第一手根因（E0b 早快照 t=5s，深帧）
`nodeorder_init ← start_kernel+0x10c` 帧**是真的**（ring_e0b.txt 尾帧可见），PC=`memset+0x2c`；
`nodeorder_init` 里只有对 `.bss` 小表的 memset ⇒ 真正越界写发生在其调用的 memset(dst=平坦窗末端)
（V2b dst=0xdf7ffffc；V1 mem=512M 时 dst=0x8000003c）⇒ 该 dst 是「按 mem= 声明算出的 lowmem 末端」
的某个 word 表（nl/bootmem 类），与结论 §2-1/2 一致。E0b 环里还见
`do_page_fault ← do_translation_fault+0x24`（handler 自身递归缺映射 ⇒ 无限级联）。

## 5. bionz.c diff（8c19082b → 11abc8c7）
1. `A7C_MAP` 新增 **e**（2040MB 平坦@0 + 1016MB@0x80000000，无 mirror/无 sram2 孪口）与
   **f**（仅 2GB 平坦@0；ddr1 size=0 时不创建）。
2. 新增 env **`A7C_CMDLINE_FILE`**：把真机 kemco.txt **逐字节** `load_image_targphys` 到
   `A7C_CMDLINE_OFFSET`（0x133000；16KB 含 NUL 填充，止于 0x137000 不撞 kernel@0x138000）。
   优先级高于 `-append`。
3. `bootrom@0xffff0000` 去掉 `memory_region_set_readonly`（允许内核 early_trap_init 写向量页；
   M4b 验证卡点不在这里，但该改动方向正确、保留）。
4. 未动：amba2 UART 模型、A7C_TEXT_OFFSET/A7C_CMDLINE_OFFSET、atags、eMMC tbl、DDRC 尺寸常量
   （map e/f 自动等于新 DDR 尺寸）。

## 6. 复现命令（远端 ~/qemu-a7c）
```
./run_r4.sh <tag> <wait> <E0|M3|M1|M2|M4>      # SNAPEVERY=<n> 可覆盖(默认15)
SNAPEVERY=5 ./run_r4.sh e0b 45 E0
./run_r4.sh m4b 100 M4                          # 目前最远档
```
产物（远端，txt 已回传本机本目录）：`ring_{e0,e0b,m3,m1,m4,m4b}.txt`、`klog_*.txt`(空)、
`run4_*.log.start`（ZZMAP/ZCMDLINE_FILE 行）。远端另有 `fwdump_{e0,e0b,m3,m4,m4b,m1}/`、
`parts/kemco_a1.txt`(逐字节=本机 work/cmdlines/kemco_a1.txt)、`parts/kemco_a1_m4.txt`。

## 7. 下一步（优先级）
1. **M4 卡点**：跑 `nm System.map` 对 PC/帧（0xffff1000、R05=00132c01、R04=df7fe000）；查
   `kernel/power/ssboot`、`ssboot_init`（start_kernel+0xf4 已执行过？）与 vector/kuser 页在
   0xffff0000+0x1000 的桩；也查那次 memset 例程在 M4 图下写 df7fe000 的意图（也许正是
   `clear all memory region`（warm.c:324）——`warm.boot_drop/ignore_drop` 参数路径）。
2. 卡点过后才谈 `/init`、UdtrMain；`initrd=` cmdline 是否被接受（V 系列从未打到 `Freeing initrd`，
   3.0 主线 initrd 只认 ATAG——bionz 已写 ATAGS(INITRD2)@0x600000，待验）。
3. 观测升级：SNAPEVERY=3；把 klog 快照改到 initcalls 之后再取；em_console 需要内核活到 mailbox 写。
