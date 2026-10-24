# Round 3 FINDINGS — Sony GPL 源码到手后的方向变更与结果

时间：2026-10-24（UTC+8）。本轮前 25 分钟按「alias/镜像窗」路线跑了 T1/T2（结果已被新证据推翻），
收到方向变更后改跑 **Sony 自带 QEMU 配置** 路线。

## 0. 结论速览（内存图之争的答案）

**「内存图不对」假设部分成立，但不是 alias：**
- 真机/源码模型：`PAGE_OFFSET=0x60000000`，`VA−PA=0x60000000` 恒定（`mach/memory.h`），
  DDR0 物理基址 0。内核是**未压缩 `vmlinux.bin`**（`CONFIG_SNSC_BOOT_BIN=y`），
  装载 PA = `CONFIG_CXD900X0_TEXT_OFFSET`（出厂 0x108000；Sony QEMU defconfig 0x138000），
  链接 0x60108000/0x60138000。**不需要任何 alias**；我们 Round1/2 把 DDR0 扩到 2GB
  让 zImage 解压到 PA 0x60000000 才是 slab DataAbort 的直接原因（等于把内核放到真机的
  bank1 空洞/镜像区）。
- 真机 bank（权威 = nflasha1 kemco，V2 日志确证内核按它建 bank）：
  `arm_add_memory: 0 0x0 0x40000000` + `arm_add_memory: 1 0x80000000 0x3f800000`
  （即 mem=1G@0 + mem=1016M@0x80000000@1）+ 4 条 memrsv。
  ⇒ QEMU 应建模 **DDR0=1GB@0 + DDR1=1016MB@0x80000000**（不再是 2GB flat + 256MB）。

## 1. 新做的可观测手段
- `qmp_forensics.py` 升级：周期性小快照（log_buf 窗口）+ 终点全 dump + 寄存器/反汇编；
  `post` 模式可离线重放。log_buf 位置这次直接从 `ksrc/System.map` 读
  （QEMU-defconfig 内核：`log_buf 0x60484384`→ring PA 0x49fe88，`log_buf_len=0x20000`）。
- 坑：oops 级联在 **内核时间 20ms 内刷满 128KB 环**，t=5s 的首个快照已经没有 `[#0]` 头；
  但**最深帧（根因帧）在 t=5s 快照里完整保留**（见 §3）。
- Sony klog（`kernel/klog.c`，`klog.addr=0x02120000`）在 V1/V2 里为空：klog 在 initcalls
  阶段才初始化，而崩溃发生在 start_kernel 更早处。

## 2. 工具链/内核构建（可复现）
- `~/sony-src/...` 只读 → **拷贝到 `~/qemu-a7c/ksrc` 再 `make mrproper`+构建**（O= 会被
  「tree not clean」拒绝）。
- `make ARCH=arm CROSS_COMPILE=$HOME/sony-src/armv7-eabihf--glibc--stable-2018.02-1/bin/arm-linux-
  cxd90045_qemu_nfs_defconfig && make -j6 vmlinux.bin`（gcc 6.4，`LD_LIBRARY_PATH=~/sony-src/mpfr4/...`）
- 产物 `ksrc/arch/arm/boot/vmlinux.bin`（3,521,920 B，未压缩）。

## 3. V1（defconfig 内核 + 内置 cmdline，无 -append，无 initrd）
- 内核活着跑进 `start_kernel+0x10c → nodeorder_init → memset`，**过了 slab**（内存图基本对了）。
- 最早根因帧（t=5s 快照，环里已无 `[#0]` 头）：
  `DataAbort, do_bad_area, fault VA≈0x8000003c（r6=0x8000003c, r0=0x8000003c, r2=4, 填充 -1）`
  `PC=0x60298f8c（memset+0x2c） from nodeorder_init+0x...（mm/nodeorder.c） from start_kernel+0x10c`
  → V1 的 `mem=512M@0`：VA 0x8000003c ↔ PA 0x2000003c 超出 512MB bank ⇒ nl/nodeorder 的
  某张静态表/按 bank 末址放置的结构越过 bank 尾。真机 bank 是 1GB，所以不炸。
- 之后 `panic.c:106` BUG + oops 级联到 `Kernel panic - not syncing: Attempted to kill the idle task!`
  （与 Round2 同一形状，只是位置更靠前）。
- 串口 0 字节：崩溃发生在 initcalls 之前，amba2 控制台（driver initcall 注册）与 klog 都没起来。
  **console 是否通仍未验证**（amba2 最小模型已写入 bionz.c，未被消费）。

## 4. V2（同一内核；-append = a1 kemco + QEMU-defconfig 内存项合并）
- kemco blob 被接受：`cmdline override at 60133005`（CONFIG_CMDLINE_PHYS_OFFSET=0x133000）。
- 日志给出**权威内存图三行**：
  ```
  Machine: ARM-CXD900X0
  arm_add_memory: 0 0x0 0x40000000 / arm_add_memory: 1 0x80000000 0x3f800000 / arm_add_memory: 2 0x0 0x20000000
  reserve area 0..4: 100000@0, 75E000@2E68000, 500000@9B00000, 20000000@20000000, 128000@0
  ```
- 死因是我方合并失误：kemco 自带 `mem=1G@0 + mem=1016M@0x80000000` 又叠了
  defconfig 的 `mem=512M@0` ⇒ 第三 bank 与 bank0 重叠 ⇒ **kernel BUG at mm/bootmem.c:334!**（add_memory 重叠断言）。
  这同时**确证内核自己解析 cmdline mem=/memrsv=**（不靠 ATAG_MEM；ATAG 路径 ej_head_init 传 -1）。

## 5. V2b（修正版：纯 kemco bank + `A7C_MAP=a`：DDR0=1G, DDR1=1016M, 附 0x60000000 alias 窗）
（结果见文末追加；跑在 fwdump_v2b，日志 run3_v2b.log。）

**追加 V2b 结果**：bootmem 重叠 BUG 消失（bank 被完整接受），但同一处崩溃仍在：
`start_kernel+0x10c → nodeorder_init → memset(→PC=memset+0x2c)`，DataAbort（do_bad_area），
这次写 **VA 0xdf7ffffc**（=lowmem 顶 0xdf800000 前一个 word；V1 是 0x8000003c=512MB bank 顶后一 word）
⇒ memset 的目标地址紧贴「已映射低内存末端」，像是 nl 内存管理器把某个结构放在
(bank 末端 + 偏移)（日志有 `clear all memory region / add memory region: %8lX(@%08lX),%8lX(%ldK)`）。
随后 oops 级联（时间戳到 7.36s，`Oops … [#…]` 一路）直到 `Kernel panic - not syncing: Fatal exception in interrupt`。
两张 config（ksrc defconfig vs 出厂 .config）的 `SNSC_MAX_NODEORDER=8 / NODES_SHIFT=4` 相同，
排除 nodeorder 表尺寸差异 ⇒ 下一步查 nl 的 memory-region/max_low_pfn 计算（V3 出厂 .config + CXD900X0_QEMU=y
是唯一还没排除的构建面；本轮时限内未跑）。

## 6. bionz.c 最终 diff 概要（本机=远端 `~/qemu-a7c/qemu-sony/hw/arm/bionz.c`）
1. `CXD90045_TEXT_OFFSET=0x00138000`（可 env `A7C_TEXT_OFFSET` 覆盖，出厂 config 用 0x108000）；
   kernel 用 `load_image_targphys` 按 raw binary 装载（不再走 zImage 解压语义）。
2. kemco blob 恢复写入：地址 env `A7C_CMDLINE_OFFSET`（默认 0x133000；出厂 0x103000），
   `-append` 为空则完全不写 ⇒ 内核用内置 CONFIG_CMDLINE。
3. **amba2 UART 最小模型**（4 个口，0xf2000000+i*0x1000）替换 pl011：
   FR(0x18) 读回 RXFE|CTS（内核位：RXFE=0x010/TXFF=0x020/BUSY=0x008，QEMU 内置 pl011 位分配
   不同且 0xfe0/0xff0 ID 读 0 ⇒ amba2 probe 根本 bind 不上）；PIDR/CIDR 回
   PID=0x00041011（amba2.c pl011_ids）/CID=0xb105f00d（AMBA_CID）；DR 写 → chardev。
4. env `A7C_MAP`（orig/a/b/c/d）内存图变体（Round2 遗留，a 仍有用：DDR0 1GB+**DDR1 1016MB**
   真机 bank；b/c/d 的 alias 实验已判为不需要，保留但不默认）。
5. `ATAG_MEM`（env A7C_ATAGMEM，仅 c 档）；DDRC 尺寸常量寄存器随 map 更新。

## 7. 下一步（优先级）
1. 看 V2b：若 bootmem 断言过了，**下一道坎预计仍是 nodeorder/memtable 或 tmonitor**；
   再用纯 kemco cmdline 过 initcalls（amba2 console + klog 起来才算「console 通」）。
2. V3：出厂 `.config` 副本 + `CONFIG_CXD900X0_QEMU=y`（注意 Kconfig 可能把 TEXT_OFFSET
   默认改成 0x138000，装载地址跟 env 走）——与真机内核几乎一致。
3. console 通了之后才轮到：initrd 是否被 `initrd=` 解析接受（3.0 arm 主线只从 ATAG 拿 initrd，
   nl 是否扩了 `initrd=` cmdline 需要在 setup.c 里查）、nflasha 走 udif/emmc。

## 产物
- 远端：`~/qemu-a7c/{ksrc(内核源+构建), kb-qemu(废), fwdump_t1,fwdump_v1,fwdump_v1b,fwdump_v2,fwdump_v2b,
  run3_*.log, round3_*.out, kbuild.log, build_r3*.log, run_sony.sh, qmp_forensics.py}`
- 本机：`work/qemu-a7c/results/round3/`（日志/环文本/FINDINGS；.bin 大文件不回传，留远端）
