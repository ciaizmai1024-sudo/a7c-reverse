# zve10-qemu 仓库精读 → 对 A7C 改固件/写回的可迁移做法

阅读对象：`refs/zve10-qemu`（Sony ZV-E10 一代，CXD90045 "ASTRA"，与我们 A7C **同一颗 SoC**）
阅读方式：**纯静态阅读**（未运行任何需要真机的东西）+ 本机 python 只读交叉核对 A7C 解包件。
本文所有 zve10 侧结论都给了仓库内路径与原文片段；A7C 侧结论标注了我实际跑过的核对命令。

术语对齐（重要，仓库内部自身不一致）：
- `docs/FIRMWARE_REPORT.md` / `docs/JIRITSU_CHANNEL.md` 按 **fwtool.py 的代际**称 CXD90045 为"第四代"（`AesCbcCrypter` = 4th gen）。
- `zve10-uart-boot/docs/GEN_COMPARISON.md` 按 **BootROM/payload 架构**称 CXD90045 为"三代机"、CXD90057 为"四代机"。
- **两者指同一台机器**（A7C / ZV-E10 / A6400 / ZV-1F 都是 CXD90045）。引用时一律写 SoC 名，不写"几代"。

---

## 0. 仓库地图（读了哪些，哪些是核心）

| 线 | 关键文件 | 价值 |
|---|---|---|
| 真机救援 | `rescue/README.md`、`rescue/docs/{PROTOCOL.md,ARMv7_方案_定稿.md,README_抢救包.md,STATUS.md}`、`rescue/payloads/minimal_fix/{main.c,Makefile,VALIDATION*.txt}`、`hardware/README_盲操作容错版.md`、`hardware/OPERATOR_CARD.md` | ★★★★★ 1 字节修复法 + BootROM 串行启动 |
| 启动桥硬件 | `zve10-uart-boot/{README.md,CAPABILITY.md,PROTOCOL_FIXED.md,VERIFY_TODAY.md}`、`zve10-uart-boot/docs/{ROM_VERIFY.md,GEN_COMPARISON.md,ANALYSIS.md,ROM_EMMC_INIT.md,STATUS_EOD_20261022.md,FASTBOOT_PLAN.md,payload_*.c}`、`zve10-uart-boot/{rp2040/*.pio,rpi2040/uart_boot_led.ino,scripts*/inject_*.py}`、`hardware/{BOOTROM_RESEARCH.md,UART_PIN_RESEARCH.md,LED_RESEARCH.md}` | ★★★★★ 对 A7C 直接可用（同 BootROM） |
| QEMU | `docs/{HANDOFF.md,HANDOFF_2026.md,QEMU_BOOT_PROGRESS.md(≈20k 行),GEN1_SYSTEM_STRUCTURE.md,EXCLUDED_HYPOTHESES.md,A7C2_QEMU_REFERENCE.md,ZVE10_PORT_ROADMAP.md}`、`scripts/*`、`patches/{kernel,qemu}/*`、`display/*` | ★★★★ 仿真能力与坑 |
| 校验/门禁 | `docs/{FIRMWARE_REPORT.md 三·补,JIRITSU_CHANNEL.md §5-6}`、`guard/*.c` | ★★★★★ "改包能否通过校验"的答案在这里 |
| 分区/工具 | `data/{partition_map.tsv,machine_comparison.tsv}`、`scripts/build_patched_emmc_safe.sh`、`tools/port/*` | ★★★★ 写回与偏移换算规则 |

---

## 1. 真机救援 / 写入手法

### 1.1 故障模型：为什么"软件层无解"

`rescue/README.md`：

> `/etc/ld.so.preload` 指向一个**无法加载**的动态库后：
> `/bin/busybox` 是**动态链接**的，`/bin/sh` 只是它的符号链接
> ⇒ busybox 起不来 ⇒ `/sbin/init` 起不来 ⇒ **开机循环、无数据模式、无 shell**

**A7C 实测复核**（我跑了）：`firmware.tar_unpacked/0700_part_image/dev/nflasha7_unpacked/bin/busybox`
= `ELF 32-bit LSB executable, ARM, EABI5, dynamically linked, interpreter //lib/ld-linux.so.3`
⇒ **同样的失效模式在 A7C 成立**。任何 `/etc/ld.so.preload` / preload 库实验都必须先过
"`LD_PRELOAD=<so> /bin/true` 单进程验证"这条纪律（`rescue/docs/README_抢救包.md` 的"血泪教训"）。

### 1.2 ★ `/etc` 到底在哪块分区上（决定一切写入手法）

`docs/QEMU_BOOT_PROGRESS.md` §161.2（Round 188，QEMU 实测）：

```
| 注入方式 | 结果 |
| /setting/mode/preload（bootin 会设 LD_PRELOAD） | ❌ 未生效（有条件判断） |
| rootfs /etc/ld.so.preload | ❌ 未生效（rootfs 的 /etc 被覆盖） |
| nflasha10 根目录放 ld.so.preload | ✅ 生效（5 个进程加载） |
⇒ 真机的 /etc 实际来自 nflasha10（vfat），不是 rootfs
```

**A7C 实测复核**：
- `0700_part_image/dev/nflasha7_unpacked/etc/` = **空目录**（rootfs 的 /etc 只是挂载点）；
- `0100_config/mount.conf`：`/dev/nflasha10 /tmp vfat 12582912 16384`（与 ZV-E10 **一字节不差**）；
- `0800_appli/tmp/` 内容 = `toprc / nsswitch.conf / services / protocols / config.spec / images` —— 典型的 /etc 内容；
- `nflasha3_unpacked/initrd.img_unpacked/sbin/init` 的字符串里有
  `/dev/nflasha10`、`/tmp`、`/etc`、`TOPRC=/etc/toprc`、`move_partition failed`。

⇒ **A7C 的 `/etc` 与 `/tmp`（+`/var`）同属 nflasha10 这块 12 MiB FAT 分区**，与 zve10 结论一致。

### 1.3 ★★ "1 字节修复法"的具体做法（用什么通道）

通道选择（`rescue/README.md` + `docs/ANTIBRICK_SYSTEM.md`）：

| 场景 | 通道 | 做法 |
|---|---|---|
| 相机还能起 shell（半修坏） | **网络（WiFi）或 USB 上的 root 通道** | `rm -f /etc/ld.so.preload` 或写空白 |
| 相机进海量存储（MSC） | **USB MSC + PC 端更新器流程（PMCA）** | 走 L4（见 §1.5） |
| **boot-loop、无任何软件通道** | **BootROM 串行启动（UART 电平、48000 baud）→ SRAM 裸机 payload → 直接操作 SDHCI/eMMC** | 改 FAT 目录项 1~2 字节 |
| 一切真机写入前 | **QEMU 演练**（`scripts/run_armv7_payload.sh`） | 同一 payload 先在镜像上跑通 |

修复语义（`rescue/payloads/minimal_fix/main.c`，注释即原文）：

```c
/* 6) ★ 档2：清 size 字段（+28..+31）= 0 ⇒ 文件存在但 0 字节 ⇒ preload 列表为空 */
u8 *se = buf + hit*32;
se[28]=0; se[29]=0; se[30]=0; se[31]=0;
```

- 第一版思路是"把目录项首字节写 0xE5（删除）"（`VALIDATION.txt` 里 `first=0xe5 ✓✓ 已删除`）；
- **定稿改成"清 size"**（`VALIDATION_size_clear.txt`：`原 size=0x10000004? 实际 0x104 → 读回 0x0 ✓✓`）。
  理由见 §1.4（LFN 项仍在，删除短名项会让 LFN 变孤儿，风险更高；清 size 只改 1 字节且幂等）。
- 目标块：`#define ROOT_SCAN_BLK 0x56008u`（= 分区起始块 `0x56000` + 根目录第 4 扇区），
  `0x56000 × 512 = 0x0AC00000` = nflasha10 在 **eMMC 用户区**的偏移。

payload 的三条安全保证（`hardware/README_盲操作容错版.md`，QEMU 实测）：

```
★ 任何一步验证不通过 ⇒ 一个字节都不写 ⇒ 相机状态不变
★ 扫全部 32 个根目录块（FAT12 根目录 512 项 = 16KB）；size>1MB / attr 异常 ⇒ 拒绝写
★ 写后读回校验；幂等（size 已为 0 ⇒ 不写）
实测：正常路径 1 字节变化；幂等路径新增改动 0 字节；找不到 ⇒ 零写入
```

结果反馈 = **机身 LED 闪码**（BootROM 串行启动协议是**只写**的，没有回读命令）：
`hardware/LED_RESEARCH.md`：LED = GPIO port0/bit0，
`设输出 0xF2910004`、`点亮 0xF2910048`、`熄灭 0xF2910044`；
码表 `1 成功 / 2 没找到 / 3 MMC / 4 读 / 5 写 / 6 校验`（`0xA5/0xE1..0xE5` 写在 SRAM `0xFE02F000`）。

**诚实边界**：这条真机路线在 ZV-E10 上**没有最终完成**（`rescue/docs/STATUS.md`：软件侧 100% 就绪，
卡在找不到物理 RX；`zve10-uart-boot/docs/STATUS_EOD_20261022.md`：命令链已通、数据阶段未通）。
**已 100% 完成的是 QEMU 端到端验证**（`docs/QEMU_BOOT_PROGRESS.md` §135：12 MB 全分区写回，
主机侧 md5 `3a75a7c0…` 一致；前后 64 KB 未被误写；`mdir` 列目录正常）。

### 1.4 ★ A2 "分区写满的连锁失败" —— 容量约束与写满后果

原文（`docs/HANDOFF_2026.md`，转引社区 a7C II 的 `RECOVERY-AND-LESSONS.md`，并声明与本项目独立结论一致）：

```
相机的 /tmp、/etc、/var 是同一块 12 MiB vfat 分区（nflasha10）。
往里写大文件会把它填满 → 之后任何写入都失败 0x10000009
→ 连"把 /etc/ld.so.preload 置为中性"的清理写入也失败
```

两条推论（同一处原文）：
```
⇒ 我们的"1-2 字节修复"是最优方案（不写大文件）
⇒ 若必须写 12MB，要一次性写完整个分区（不是追加）
```
另：`docs/JIRITSU_CHANNEL.md`/§157.4 记录 a7C2 的中和技巧：`jiritsu_preload_clear.py`
写 **512 个换行**（glibc 按空白分割 ⇒ 空 preload 列表），并给出经验
"覆盖写只在**已有文件大小内**可行（对 0 字节文件写失败 `0x10000009`）"。

分区尺寸与"写满/写坏后果"（`data/partition_map.tsv`，与我实测的 A7C `partinf.conf`/`mount.conf` 对照）：

| 分区 | 大小（A7C 实测 partinf.conf） | fs / 挂载 | 写满或写坏的后果（zve10 侧证据） |
|---|---|---|---|
| nflasha1 | 7.9 MB | vfat（更新器 ramdisk，含 `boot/{vmlinux.bin,initrd.img,kemco.txt,loadaddr.txt}` + `p1chksum` + `dat2/dat3`） | 动它 = L0 铁律区（`ANTIBRICK_SYSTEM.md` L0），无软件救路；`p1chksum` 会核对 md5（§134/§112.1） |
| nflasha2 | 20 MB | vfat `/setting` | 模式旗标 + `Backup.bin` + `kemco.txt`；更新流程要挂它读 Backup，满/坏 → 更新链断 |
| nflasha3 | 48 MB | FAT12 `/system` | 内核+initrd+av-cam；`p1chksum` 校验 |
| nflasha5 | 60 MB | `wbi`（`WBI1`）`/wbi` | 热恢复镜像；`ud_wbi_drop.elf` 会丢它 |
| nflasha7 | 8 MB | ext2 `/rootfs` | 只有 136 文件；busybox/glibc/6 个引导 .ko |
| **nflasha10** | **12 MB** | vfat `/tmp`（**实际 = /etc + /var + /tmp**） | **写满 ⇒ 所有写入失败 0x10000009，含"自救"写入；救援必须 1~2 字节** |
| nflasha11 | 500 MB | vfat `/log` | 备份/转储目的地（`dd if=/dev/nflasha15 of=/log/…`）；必须**是合法 vfat**，全零会让 `/log` 挂不上（QEMU 里 52.5s→70.6s 的差别） |
| nflasha12 /13 /15 /18 /23 | 40 / 4 / 300 / 20 / **2 MB(A7C) vs 64 MB(ZV-E10)** | cert / updaterwork / usr(ext2) / lens / PMBP | nflasha15 是唯一"可改的大分区" |

A7C `nflasha15` 空闲量实测（我读 ext2 superblock）：
`blocks_count=234356`（229 MB FS，块 1 KiB）、`free_blocks=57682` → **打包好的 /usr 里还有 ≈56 MiB 空闲**，
inodes 58696；分区本身 300 MB ⇒ 若换镜像还能再扩 ~70 MB，但**不建议改 FS 几何**（见 §7 风险）。

### 1.5 服务/工厂通道全景（能不能“读写文件/读内存”）

`docs/FIRMWARE_REPORT.md` “三·补二 / 工厂服务路径全景”：
```
PC 端工厂工具（★ 未随固件分发）
   │ USB
   ▼
相机（更新模式）：usb_extcmd.ko ("USB Extension Command function driver")
                 usbg_storage.ko (海量存储)   usbg_sen.ko (SEN)
相机内：sauu（更新核心：-m Minor / -s VersionSkip）  mf（工厂工具）  sen.elf（Senser 工具）
```
相关能力已在固件里定位到（同一文档）：

| 能力 | 实现 | A7C 是否存在 |
|---|---|---|
| 读内存到文件 | `ud_get_mem2file.elf <filename> <address> <size>`（在 nflasha1 initrd 里；`execute_prod.sh` 用它 dump DDR training data） | 待确认（在 nflasha1，需 dump） |
| 从 SD 卡升级 | `sdfileinput.elf`/`sauu` + `libsdfileinputupdaterapi.so`（含 `VersionSkip`） | 待确认 |
| 引导来源判定 | `is_valid_boot.sh`：1=OneNAND / 2=MS(记忆棒) / **3=USB Boot** | 待确认 |
| 升级必要性判定 | `hash_check.sh` 用 **`md5sum -c`** | 待确认 |
| ff01/ff03 “读文件/读内存” | 固件里只命中 BLE 特征（`libInfraBluetoothLowEnergy.so`，服务 UUID `8000FF00FF00…`） ⇒ `ff01/ff03` 是**工厂 EXTCMD 命令码**，不是固件内部符号 | 同样只能当假设 |
| `sen.elf` | 路径 `/setting/.hasp`、`/boot/sen/smode`、`/setting/sen/smode`、`/var/.sen/.smode`，符号 `Read_Hasp`/`Hasp Read Failed` ⇒ **需要 HASP 加密狗** | **A7C 有 `/usr/bin/sen.elf`**（我已在 `nflasha15_unpacked/bin/sen.elf` 看到） |

⇒ 对 A7C：“有存储写权限就能切模式/进服务”这条完全成立（旗标在 vfat 明文的 nflasha2），
但“PC 端工厂客户端”不存在公开发行版 ⇒ 要自己实现 PC 端 + 逆向 `mf` 的 FIFO/EXTCMD 协议（ARM32，可反汇编）。

### 1.6 对 A7C 改 `usr / rootfs / nflasha15` 的可迁移注意事项

来自 zve10 的分层兜底（`docs/ANTIBRICK_SYSTEM.md` §三），逐层对应到 A7C：

```
L0  永不触碰：nflashaB0/B1（eMMC boot0/boot1，= EXBL+Loader2）、nflasha1（更新器 ramdisk）、
    vmlinux.bin/initrd.img、/sbin/init、libc/ld.so
L1  旁路安装：新东西放 /log（nflasha11，500MB），用 mount --bind 覆盖 /usr/… 目标文件
    ⇒ /usr 一个字节都不改，原版永远在盘上
L2  看门狗自动回滚 agent：开机 N 秒内没检测到 UI 进程 ⇒ 自动 umount + 删开关 + 重启回原版
L3  dd 还原：先做全盘/分区备份 + SHA-256（他们对 17 分区 + nflashaB0/B1 + 1.85 GiB 全盘都做了）
L4  官方更新器强制重刷（纯软件、最硬）：把 /setting/updater/dat4 写低（2 字节 BCD）或建 mode6
    ⇒ 任何官方包都能灌进去 ⇒ 相机回到出厂态
```
（上面这段就是 zve10 原文结构；我在 §1.5 补充了工厂通道。）

L4 的实测记录（`ANTIBRICK_SYSTEM.md` §二，**真机跑过**）：

```
/setting/updater/dat4  2 字节，权限 -r--------（root 可写）
原始 "03 02"（=2.03） → 写 "00 00" → 相机报 0.00 ⇒ 版本杠杆可用 → 已还原
```
恢复操作卡（同一文件 §四）：
```bash
python3 zve10_net.py <IP> run "dd if=/dev/nflasha15 of=/log/nflasha15.bak bs=1M"
python3 zve10_net.py <IP> run "cp -a /setting/updater/dat4 /log/dat4.bak; printf '\000\000' > /setting/updater/dat4; sync"
python3 zve10_official_update.py <build>/fw/FirmwareData_ZVE10V203.dat   # PC 端 PMCA 流程
python3 zve10_net.py <IP> run "cp -f /log/dat4.bak /setting/updater/dat4; sync"
```
⇒ **注意**：`dat4` 在这里是"裸 2 字节 BCD 直接写"就生效，与我们 A7C 分析里
"`ud_datcnv.elf -e` 加密写 dat4"并不矛盾 —— `up.sh ver/modver` 是**加密写**（写的是 `dat4` 的正式格式），
直接 `printf` 覆盖低 2 字节也能撬动版本判断。A7C 上**先备份 `/setting/updater/dat4` 再试**，且只写 0x0000。

---

## 2. A3 启动桥硬件 / `zve10-uart-boot`：UART 到底能拿到什么

### 2.1 已验证的物理层（实测接线，`zve10-uart-boot/README.md`）

```
BOOT_SERIAL_IN  ← 相机 USB-C 的 D− (A7)，经 470Ω
XRESET_REQ      ← 相机 USB-C 的 D+ (A6)，经 470Ω
CC1 / CC2       ← 各 5.1kΩ 下拉到 GND（分开，不短接、不上拉）
VBUS            ← 外部稳定 5V；GND 共地
发送端          ← RP2040（Pico），PIO 位翻转 + DMA，open-drain 输出
```
ZV-E10（无 Multi 口）实测"CC 下拉 + D− 注入"就能进 BootROM 串口启动；A6700（CXD90057）则要 CC 56k 上拉 —— **不可照搬**（`GEN_COMPARISON.md`）。

普通调试串口（控制台）另一回事（`hardware/UART_PIN_RESEARCH.md`）：

```
SoC 映射：DEBUG_UART0_TXD = GPIO2[9]，DEBUG_UART0_RXD = GPIO2[8]，GPIO2 bank = 0xF2910200
OCTRL2.OEN_SET=0xF2912204 / IEN_SET=0xF2912214 / PUD1_SET=0xF2912244
UART0 = 0xF2000000（PL011），控制台 115200 8N1
```
`docs/QEMU_BOOT_PROGRESS.md` §231 补充了一个**很实用的开关**：
```
真机 /setting/kemco.txt 里 amba2.console=0 ⇒ loader/内核无输出；改成 1 ⇒ 有输出
（真机 cmdline 里还有 error.led=0,0、wdt.timeout=500 等参数）
```
⇒ A7C 若能在 /setting 写文件（有 root 通道时），**把 `amba2.console` 置 1 就有 UART0 输出**，
不需要拆机就能拿到日志（前提：物理 TX 测试点能测到；见 `BOOTROM_RESEARCH.md` 的 a6400 维修手册 MULTI pin8=UART_TX / pin9=UART_RX / pin10=BOOT_SERIAL_IN）。

### 2.2 BootROM 串行启动 = "下载模式"（有，且已实测能执行任意代码）

**串口参数（两段不同！）**

| 阶段 | 参数 | 出处 |
|---|---|---|
| BootROM 记录流 | **48000 baud, 8O1（奇校验）**，11 bit/字节；ROM 用 GPIO 位采样，步长 84 tick ≈ 20.83 µs | `zve10-uart-boot/README.md` |
| 之后 payload/控制台 | UART0 @0xF2000000 **115200 8N1** | `ARMv7_方案_定稿.md` |

**记录格式**（`PROTOCOL_FIXED.md` + `scripts2/inject_a7c_exact.py`）：
```python
body   = struct.pack("<IHI", 10 + len(p), rtype, value) + p
record = body + struct.pack("<I", zlib.crc32(body) & 0xffffffff)
recs = [rec(0x0000, V)]                     # 组首 SET_UNLOCK（V = 解锁 token）
     + [rec(0x0001, LOAD+off, chunk) ...]   # 每块 ≤ 4086 B
     + [rec(0xffff, ENTRY)]                 # SET_ENTRY：写 [0xFE00500C]
     + [rec(0x0000, V)]                     # 组末必须【同 type】才关组
```
**致命细节（他们踩过的错，两次纠正）**：
- 组首/组末**必须同 type（都用 SET_UNLOCK）**，**不能**用 a7M4 的 `END_MARKER(0x0123)`；否则 ROM 报 `0x2004`（1 长 4 短闪）。
- 记录之间 `RECORD_GAP = 14.4 ms`；**组内不允许 >293.6 µs 静默**（载波必须持续翻转 ≈4 kHz）；
  整组必须 **< 1.45 s**（ROM timer A）。
- "载波开启后等 0.5 s"这条**在 ZV-E10 实测有害**（`VERIFY_TODAY.md` §2.3：加了 0.5 s 必失败，去掉才正常）。
- 慢块宽度必须落在 **225.4–293.6 µs**：`slow=11(229µs) 失败 / slow=12(250µs) 成功`
  （`rp2040/serialboot_slow12.pio` 就是给这个的）。
- 每次上机前**必须彻底断电**（拔电池 + 断 VBUS 等 10 s）：payload 会关看门狗（`0xF2402000/0xF2402004`）并死循环。

**解锁 token（对 A7C 最要紧的一条）**（`docs/ROM_VERIFY.md` ⑦）：
```
0x8CB102DC / 0xA86DA25E / 0x2CF25621 都不是 ROM 里的常量
⇒ ROM 运行时从 boot0 偏移 0x200 读取 (V, C)，并校验 crc32(V||C)==0xFFFFFFFF
⇒ 每台机器的 token 由 boot0 决定；我们是 V=0x8CB102DC, C=0xA86DA25E（已从本机 boot0 提取）
```
⇒ **A7C 必须先把自己 eMMC boot0 的 0x200 处 8 字节读出来**（全盘 dump 里偏移 0x200 即可）。
`zve10-uart-boot/scripts/inject_a7cfull.py` 还示范了"把 (V,C) 埋进 payload 镜像偏移 0x200"的写法。

**能拿到什么 / 拿不到什么**

| 能力 | 状态 | 证据 |
|---|---|---|
| 执行任意 ARM32 代码（SRAM `0xFE020000`/`0xFE021000`） | ✅ 实测（1 秒长闪 + 3 快闪证实） | `CAPABILITY.md`、`PROTOCOL_FIXED.md` |
| ROM 错误码 | ✅ 靠机身 LED 闪码读（长闪 = ((code>>12)&0xF)-1，短闪 = code&0xFFF；`0x100D` 奇偶错、`0x2002` token 错、`0x2003` CRC 错、`0x2004` 组不完整、`0x2005` 入口返回、`0x3001` 超时、`0x1002` 退回正常启动失败） | `README.md` |
| **回读通道** | ❌ BootROM 串行启动协议**只有写**（SerCmd 只有 4 种，无 peek/read）⇒ 只能靠 LED | `rescue/docs/PROTOCOL.md` |
| 单次载荷 | ZV-E10 实测上限 ≈1.2 KB（1212 B 可、1264 B 不可）；**同族 A7C 实测可发 5,149 B（2 条 MEM_WRITE: 4086+1063）** ⇒ 认为是注入侧问题不是 ROM 限制 | `README.md` "关于载荷大小（重要更正）"、`FASTBOOT_PLAN.md` |
| 突破载荷上限 | ✅ 二级加载器（接收器 v6 + CRC32 + 进度闪），任意大小数据流式写 SRAM | `PROTOCOL_FIXED.md`、`CAPABILITY.md` |
| eMMC **命令**链 | ✅ CMD0/1/2/3/7/13 全通（`CMD2=0x0201` 是关键修正，`CMD3=0x031A`、`CMD7=0x071A`、`CMD13=0x0D1A`，实测灯码 1,1,1,1） | `docs/STATUS_EOD_20261022.md` |
| eMMC **数据**阶段（CMD17/18） | ❌ **未完成**：自己的描述符路径超时；调 ROM 多块读 `0xFFFF25A3` 静默卡死 | 同上 |
| USB fastboot（peek/poke/flash/dumpbrom） | ❌ 未做，但给了 S1–S6 计划（DWC3 @0xF0200000 + PHY + gadget），**S1（发得下 5 KB）是 go/no-go** | `docs/FASTBOOT_PLAN.md` |

**硬约束（对 A7C 直接可用）**（`docs/STATUS_EOD_20261022.md` 🔑）：
```
1. eMMC = PEF1G4，1.98GB，按【非高容量】访问
   ⇒ CMD17/24/25 的 ARG 必须是【字节地址】不是块号
   ⇒ nflasha10 分区起点 = 0x0AC00000（字节）
   ⇒ ld.so.preload 的 size 字段 = 0x0AC0107C（布局 A）/ 0x0AC010BC（布局 B）
2. 看门狗 ~500ms（cmdline wdt.timeout=500）⇒ 整分区 12MB 写会被复位；单字节/单块写安全
3. R1 状态在 RESP0(0x10)，掩码 0xE0F82000；完成判据 PRESENT_STATE(0x24)&3==0（不是 INT_STATUS 位）
4. ROM 的 eMMC 初始化函数在 0xFFFF2278（只返回 0 或 0x80000004）；调它比自己做初始化更省事
```
⚠️ 注意这里与 `rescue/payloads/minimal_fix/main.c` 的 `ROOT_SCAN_BLK 0x56008`+CMD17(arg=块号) 存在**寻址风格冲突**：
`0x56008` 是"块号×512 = 字节地址"巧合等价（`0x56000×512 = 0x0AC00000`），
但真机 PEF1G4 按非高容量寻址 ⇒ **ARG 要写 `0x0AC01000` 这种字节地址**。A7C 上机前必须先确认自己 eMMC 是否 <2GB（非 HC）。

**Sony 私有寄存器/初始化序列**（两处，互相印证）：
- 从设备明文 loader（EXBL/Loader2，加载 `0xFE040000`、入口 `0xFE047000`）里提取的 12 步初始化：
  `README.md` "eMMC 初始化序列" + `docs/ANALYSIS.md` 04:40 节（字面量表 `0xfe04fa64`：
  `0xF03044FC / 0xF030403E(bit7=1.8V) / 0xF0304204(bit1、bit18=0x40000) / 0xF030402C CLKCTL ×17 / 0xF0304028 |=4(4-bit 总线) / 0xF0304124 &=~0x01000100`，且 `0x4204` **必须读-改-写、顺序不能乱**）。
- 从 **BootROM 反汇编**提取的序列与数据阶段参数：`docs/ROM_EMMC_INIT.md`
  （PHY 块 `0xF0304200/0xF0304208`、`POWER_CONTROL=0x0A`（不是 0x0F）、`[0x158]=0x40`、`[0x124]=0x200`、
  每条命令前后 `0x124 |= /&= ~0x20000`；
  `CMD17: TM=0x31, COMMAND=0x111A, [0x58]=缓冲区地址, [0x5C]=0`；`CMD18: TM=0x37, CMD=0x123A`；
  ROM 把状态存到 SRAM `0xFE030000..0x14`（RESP0..3），payload 可读到最后一次卡状态）。
  `docs/ON_RETURN_CHECKLIST.md` 给写盘参数：`CMD24=0x181A/TM=0x21`、`CMD25=0x193A/TM=0x27`、
  描述符 `desc[0]=(len+511)&0xFE00<<16 | 0x21 |(last?2), desc[1]=addr`。

### 2.3 BootROM 与 A7C 同芯片 ⇒ 逐条已验证

`docs/ROM_VERIFY.md` 标题就是"**对照 A7C 笔记**"，结论原文：

> **A7C 笔记的所有关键地址/规则在 ZV-E10 的 BootROM 中逐条吻合（同为 CXD90045 代）。**

已逐条对上的地址/规则（⇒ A7C 可直接采用）：
```
入口跳转        0xFFFF013C: ldr r1,[pc,#4]=0xFE005000; ldr r0,[r1,#12]; bx r0
记录解析入口     0xFFFF0802；无有效记录时返回 0x3001 并继续正常开机
组关闭规则       0xFFFF0B2E（type 相同才关组）
关组前 flag 检查 0xFFFF0B34：flag0=[0xFE010004]（SET_UNLOCK 置）、flag1=[0xFE010008]（SET_ENTRY 置），全 0 ⇒ 0x2004
串口采样        MISC_MODEREG = 0xF2915000，读 +0x10 的 bit1 = BOOT_SERIAL_IN
串口启动使能     [0xFE010010] bit4（bit2 = eMMC 正常启动）
采样时序窗口     慢块 225.4–293.6 µs；字节间窗口 206–447 µs
```
`GEN_COMPARISON.md` 还把"能借/不能借"讲得很清楚（可以借：cold/sense 同步、记录编码、Pico 命令；
不能借：A6700 的 unlock `0x2CF25621`、END_MARKER 组帧、ARM64 payload、CC 上拉接线）。
**A7C 侧的入口地址细节**：`ENTRY = 0xFE020000`（ARM 代码偶数地址已实测可行；
"Thumb 须 addr|1，A7C 例 `0xFE020041`"）。

**对 A7C 的物理入口**：本仓库没给 A7C 的测试点（ZV-E10 也没最终找到，只有 BGA 球位：
`G18/L19 = BOOT_SERIAL_IN`、`N8 = BOOT_EXT`、`P4 = BOOT_SIMPLE`、`AL24 = BOOT MODE`、
`AH23/AH24 = BOOT_NVM/SA_TDI、BOOT_SBB/SA_TDO（= JTAG 存在）`，出自 a6400（同 SoC）维修手册电路图，
`hardware/BOOTROM_RESEARCH.md`）。**但仓库里多处引用"本机 A7C 实测 5,149 B payload"**，
说明有人已在真 A7C 上打进过 BootROM —— 值得向笔记作者/社区追问具体接线点。

---

## 3. QEMU 仿真：现状、复现、补丁、坑，以及"能不能搬到 A7C 离线验证改包"

### 3.1 现在跑到什么程度（有日志证据）

| # | 目标 | 状态 |
|---|---|---|
| 1 | 内核 → `/sbin/init` → 挂载 chroot → **33 个平台模块**全加载 | ✅ |
| 2 | 机身 App `im.elf` 持续运行；`libObj.so` 于 **16.85 s** 加载 | ✅ |
| 3 | `liro`（MUSASHI 图像核）完整运行，派生 280 内核线程 | ✅ |
| 4 | `udm_hdmi`/`udm_cec` 初始化成功 | ✅ |
| 5 | 无堆损坏/abort（连续多轮零崩溃） | ✅ |
| 6 | 显示链路 App→`/dev/dmpgles2`→`grm_gles.ko`→Mali | ❌ 未完成 |
| 最佳记录 | guest 时间 **70.6 s**、68–70 次模块加载、UIPC 处理器 40+ 种、**零 page fault** | — |

显示侧的**决定性结论**（`display/probe/README.md`、`docs/QEMU_BOOT_PROGRESS.md` §161）：
```
探针注入 5 个进程；GRM_* 调用 0；GraphicsEngine 初始化 0；屏幕/序列创建 0；
viewUnified* 加载 0；dlopen 失败项 0（库全部加载成功）
⇒「没有画面」的根因不是缺 GPU 模型，而是【UI 从未被创建】
```
并且显示**通道**本身已经打通（§Round 355-357）：
```
用户态 mmap /dev/mem @phys 0x20312000（32bpp）填蓝/红条纹 → QMP screendump 可见
⇒ VDF/streamfb 显示通道可用，软件 GPE 直写 VDF 路线成立（不需要 ramfb）
```
最新一轮（§三百二十四~三百二十七）在追 `viewUnified2` 的 `init_array`（1768 个 ctor）与
"2 节点环形链表"竞态：`pViewManager` 全程为 0（gdb 硬件 watchpoint 310 s 无写入命中）。
`artifacts/cxd90045-vip-static-frame.png` + `patches/qemu-cxd90045-vip-display.patch` 说明另有一条 VIP/streamfb 静态帧实验。

### 3.2 复现命令与需要的固件文件

```sh
# 一条命令（需自备固件）
QEMU=... ZIMAGE=... EMMC=... INITRD=... BACKUP=... CMDLINE_FILE=... ./scripts/run_qemu_zve10.sh
# 实际展开（docs/HANDOFF_2026.md）
qemu-system-arm -M cxd90045 -display none -serial file:/tmp/run.log -monitor none \
  -kernel $Z -initrd handoff_p0/initrd.img \
  -drive if=mtd,file=ab_v3b.img,format=raw \
  -device loader,file=BACKUP.BIN.fixed,addr=0x02E80000,force-raw=on \
  -append "earlyprintk $(cat real_cmdline.txt)"
```
需要的固件件（全部要从自己机器导出）：
1. **整盘 eMMC 镜像**（`ZVE10_EMMC_FULL.img`，1,983,905,792 B；偏移 0 = EXBL+Loader2）；
2. **真机 cmdline**（`/setting/kemco.txt` 里取，含 `mem=1G@0 memrsv=680M@0x15800000:uc mem=256M@0x80000000@1 ramdisk_size=… console=ttyAM0,115200n8 error.led=0,0 wdt.timeout=500`）；
3. **`BACKUP.BIN.fixed`**（把 `BACKUP.BAK` 的运行态 key `0x00fa0028=0x20098000`、`0x00fa005d=0x0007C000` 补进 `BACKUP.BIN`，文件偏移 `0x0bda40/0x0bdb14`）—— **`MonDrv::Init` 成功的前提**；
4. 自编内核 zImage（打过 3 个补丁）+ 真机 initrd（两条链：nflasha3 的 ext2 initrd，或 nflasha1 的 CRAMFS 更新器 initrd）。

最强调试手段（两个 shell 脚本）：
```sh
./scripts/shell_zve10.sh "cmd"     # 用 nflasha1 的 CRAMFS initrd：/sbin/init 是脚本，
                                   # 结尾 while true: 若无 /root/IAMLDUDWRT ⇒ /bin/ash --login ⇒ 现成 root shell
./scripts/shell_camera.sh "cmd"    # 再 mount nflasha7/15/2 到 /mnt 后 busybox chroot /mnt 进相机 rootfs
```
⇒ 这条"用更新器 ramdisk 白嫖 root shell"的技巧（§112）对 A7C **同样可用**（A7C 也有 nflasha1 ramdisk；但 A7C 包里不带 `0400_updater`，见 §7）。

### 3.3 补丁清单（做了什么）

内核侧（`patches/kernel/`）：
- `adrs_conv_qemu.c`（**直接覆盖** `arch/arm/mach-cxd900x0/adrs_conv.c`）：Sony 地址换算失败时返回 0 ⇒ 一堆 NULL 解引用；改成 `pass_through()` 命中返回 `VA_DDR0`、兜底做**正确换算** `pa + VA_DDR0`。README 特别警告："早期为消错一律返回 `VA_DDR0` 害得后面多追好几轮"。
- `kconfig-pcie-qemu.patch`：`CXD900X0_PCIE2_DME` 依赖 `PCI` + 打开 `CONFIG_PCI` ⇒ 修好 `mmc_drv` 的 `Unknown symbol pci_*`。
- `tty-visible-qemu.patch`（`drivers/tty/serial/amba2.c`）：QEMU 下强制 `txrx_enable=1` ⇒ **App 的用户态输出可见**（真机 `amba2.console=0` 是故意的）。
- 各类 trace：`mmap-trace.c`、`fs_ioctl_trace.c`、`fs-open-misso-trace.c`。

QEMU 侧（`patches/qemu/`）：
- `bionz.patch`：`hw/arm/bionz.c` 的 `cxd90045` 机器：DDR 改成 `1G@0 + 256M@0x80000000`（对齐真机 cmdline）、
  `TEXT_OFFSET` 对齐内核 defconfig、**补 ATAGS（CORE/INITRD2/CMDLINE/NONE）+ 带寄存器的跳板**（`r1=MACH_TYPE_CXD900X0=3497`、`r2=atags@0x10000`，否则内核拿不到 initrd）、`boot_size=0x200000` + WBI 7 段装载（`cxd90045_load_wbi()` 硬编码 `2×0x200000 + 0x5800000`）。
- `sd-cid.patch`：`hw/sd/sd.c` 的 eMMC **CID 布局**（PNM 6 字节、整体后移一字节），给 Samsung `KLM8G1WEPD` 的 CID（`MID=0x15 OID=0x0001 → cid_id=0x0115`，PNM `"R3DPW8"` 命中 `emmc.ko` 型号表[0]）；外加 **CMD23 块数掩码 `& 0xFFFF`**（修 eMMC 写）、CMD8/CMD6/EXT_CSD。
  ⇒ **注意**：索尼 `emmc.ko` 会按 CID 查型号表，不匹配就无法识别分区（`fixup_part_conf` panic、WBI 不匹配那一串，见 §19~§28）。

镜像侧：`scripts/build_patched_emmc_safe.sh`（见 §5）。
App/模块侧 9 项修法（`docs/HANDOFF_2026.md` 表）：liro `b 2e0`、`backup.ko` 惰性初始化 trampoline（含 **`R_ARM_ABS32` 重定位手术**）、`libosal_uipc.so@0x26c0=7a68`、`im.elf@0x2f46=00bf`、`/dev/tty→/dev/null` 符号链接、`libc __assert_fail 80b5→7047`、**68 个 `/lib/X → /usr/lib/X` 符号链接**、`libc abort 684d→fee7`（**只能自旋，不能返回**）。

### 3.4 还有哪些坑（他们已经付过学费的）

```
✗ debugfs 原地 rm/write 替换文件不可靠 ⇒ 必须整树 rdump + 宿主改字节 + mke2fs -d + 逐项校验
   （曾因此静默丢掉 /lib/libMWF.so ⇒ dlerror 文本溢出 0x30 字节堆块 ⇒ 追十几轮）
✗ 没有内部约定信息时不要做字节级补丁（libMWF.so 补丁 A/B 后回退）
✗ 每处改动必须 A/B 对照，包括内核"为消错加的兜底"
✗ 大文件不要写 /tmp（tmpfs/12MB 分区满会静默失败）
✗ QEMU eMMC 模型 CMD6(SWITCH) 后卡 programming 态（模型 bug，真机是 R1b 会自己回 transfer）
✗ QEMU monitor HMP 回显会打乱管道输入 ⇒ 脚本化用 -qmp；pmemsave 文件名不能用绝对路径
✗ mcheck() 在这份 libc-2.11.2 上不可用（必须在任何 malloc 前调用；ld.so 早已 malloc；
  且该 libc 没编 MALLOC_CHECK_ 支持）⇒ 用自写 interposition 哨兵（guard/）
✗ LD_PRELOAD 是全局的 ⇒ 探针会污染被观测对象（sen.elf 也加载了 libguard.so，
  导致 ab_guard/ab_sen 两轮的观测数据全部作废，必须做 ab_sen_clean.img 干净基线）
✗ /log(nflasha11) 若在全盘镜像里是全零 ⇒ FAT-fs bogus ⇒ /log 挂不上（补合法 vfat 后 52.5s→70.6s、page fault 1→0）
✗ 真机 Loader2 路线要 `-icount shift=2` 与 boot 分区 @0x87c4 清零（patchInitPower，跳过电源 IC 初始化）
✗ 固件自带 is_qemu 分支（init 的 check_qemu、libIMDB 的 IMDB:qemu profile、/proc/version 含 "qemu"）
```

### 3.5 ★ 评估：这套方法搬到 A7C，能不能离线跑 `libupdaterufp.so / crypter.elf / 更新器`？

**结论：可行度高，而且他们其实已经"半个身子"跑通了更新器链。**

证据（`docs/QEMU_BOOT_PROGRESS.md` §165 / §166.4）：
```
官方 initrd（nflasha1/boot/initrd.img，CramFS 4,943,872 B）+ rootfstype=cramfs ⇒
EXECVE /usr/bin//UdtrMain.sh
[W] Forced Prod Mode.  [DETAIL] MODE=1
EXECVE /usr/bin//ud_im.elf
EXECVE /usr/bin//execute_prod.sh
EXECVE /usr/bin//mf
EXECVE /usr/bin/sen.elf
```
也就是说：**QEMU 里已经真实执行了"更新器 ramdisk + 模式判定 + `mf`（签名验证类所在）+ `sen.elf`"这条链**；
只是 `ud_im.elf` 依赖 `libupdater0604.so / udtr_senser_init / sens_adjCmd_init`（Senser/UIPC 服务），
Forced Prod 链不会自己创建 UI。

为什么 A7C 也能做到：
- QEMU 机器 `cxd90045` 就是 A7C 的 SoC；内核源码树本身就叫 `<build>/src/a7c-kernel/linux`（**ZV-E10 项目一直在用 A7C 内核树**）。
- A7C 与 ZV-E10 的分区表/大小/fs 类型完全一致（我实测 `mount.conf`/`partinf.conf` 一致，只有 nflasha23 PMBP 是 2 MB vs 64 MB），
  cmdline/内存图/保留区同类；`libIMDB.so` 结构一致（`data/machine_comparison.tsv` 里 A6400/ZV-E10 同为 CXD90045，217/198 条记录）。
- QEMU 已加载 `osal_uipc/utm/backup/grm_gles` 等模块并有 40+ UIPC 处理器 ⇒ 跑更新器所需的 IPC 底座已经在。

要跑 `libupdaterufp.so / crypter.elf` 还缺什么（诚实清单）：
1. **A7C 的 nflasha1 ramdisk 镜像**：A7C 的 v2.00 更新包里**没有** `0400_updater`
   （我核对过：`firmware.tar_unpacked` 里没有 0400 目录；`part_image.sum` 只有 a3/a5/a7/a15）
   ⇒ `UdtrMain.sh`、`mf`、`ud_im.elf`、`execute_prod.sh`、`dat2/dat3`、`p1chksum` 都在相机 nflasha1 上，**必须先从 A7C 导出**。
   （`updater.img` 只是 bodyfs：`config/config.xml` + `bin/*.sh` + `bodylib/libupdaterbody.so`，没有 `mf`/`UdtrMain.sh`。）
2. **USB 更新模式通道或 SD 升级通道**：相机端更新流程要 `054c:03e2` 更新模式（`usbg_*`/`usb_extcmd.ko`）
   或 `sauu`/`sdfileinput.elf`（SD 卡升级，`libsdfileinputupdaterapi.so` 里有 `VersionSkip`）。
   QEMU 里跑 USB gadget 需要 DWC3 建模（未做）⇒ **更现实的做法是走 SD/文件输入路径或直接调 bodyfs 的 API**。
3. **Senser/UIPC 服务**：`udtr_senser_init`、`sens_adjCmd_init` 需要 `sen.elf`/`libsencore.so` 起得来，
   而 `sen.elf` 需要 **HASP 加密狗**（`Read_Hasp`/`Hasp Read Failed`）⇒ 在 QEMU 里要么 stub 掉 HASP 检查，
   要么用 `mode` 旗标绕开 senser 分支。
4. `crypter.elf` 的解密走 `libosal_uipc` 的**另一个进程/服务**（我们 A7C 分析已确认它只链接 `libosal_uipc`）
   ⇒ 要在 QEMU 里把那个服务进程（疑似与 MPR/nflasha4 相关）也起来，否则只能 hook 到"调用发出"这一步。

**"验证改过的固件包能否通过校验"的现实做法**（不需要真机）：
1. 用 QEMU 起 nflasha1 ramdisk（A7C dump）→ 真实跑 `UdtrMain.sh` 的模式判定与 `mf`；
2. 在 `mf` 上用 LD_PRELOAD / GOT hook 把 `N7Updater21::SignatureVerification`、
   `RSA_verify`、`PEM_read_RSA_PUBKEY` 分支"打印参数 + 返回成功"（`mf` 未 strip，符号可见）；
3. 把改过的 `firmware.tar`/分区镜像喂进去，观察**哪一层先报错**（CRC32 sum → 机型/版本 → 分区容量 `chknandcapa.elf` → 写分区 → `endupdate.sh`）；
4. 全程用 QEMU 的 eMMC 镜像做写回演练（他们已验证 QEMU 里 12 MB 写回 md5 一致），
   然后主机侧 `cmp` 差异 ⇒ **得到"改了哪些字节、写到哪个分区"的确切证据**，再决定上真机。
⇒ 这套方法在 A7C 上的成本主要是"导 nflasha1 + 补 USB/SD 通道 + stub HASP"，
  而不是重新做一遍 zve10 的 220 小时（模块链、backup.ko、MonDrv 那部分可直接复用镜像与补丁）。

---

## 4. `guard/` 目录：**不是**固件校验/门禁，是 QEMU 里的堆/IO 探针

四个文件（`guard/lib{guard,quar,clamp,redir}.c`，共 439 行）全部是 **LD_PRELOAD interposition 诊断库**：

| 文件 | 是什么 | 关键片段 |
|---|---|---|
| `libguard.c` | 哨兵字节分配器：`HDR 16 / GUARD 32 / MAGIC 'WARD' / CANARY 0xDEADBEEF`，malloc 时加头尾哨兵，free/realloc 校验 | `enabled = name_match(__progname, "im.elf")`（只对目标进程启用）；注释明确"不要在 malloc 里调 dlsym（会递归）⇒ 直接用 `__libc_malloc/__libc_free/...`" |
| `libquar.c` | use-after-free：free 的块留在隔离区 + 毒化 `0xDD`，分配前抽查（DUMA `PROTECT_FREE` 原理），`MAGIC 'QUAR'` | 与尾哨兵互补 |
| `libclamp.c` | **语义探针**：把 `ioctl` 的 `snd_sync_direct(0x80000006)` 长度夹到 4 KB（`CLAMP_MAX`），用于确认"内核 `copy_to_user(len-16)`，App 传 0x910042(≈9.5 MB) 写穿自己内存"是不是根因 |
| `libredir.c` | **判别性探针**：长度不变，把 ioctl 第三参数换成"16 字节头 + 24 MB 安全 mmap"，`SAFE_SZ = 24MB`；判据原文："崩溃消失 ⇒ 该写入确实在碾 App 内存（这就是根因）；崩溃仍在 ⇒ 与本路径无关" |

⇒ **`guard/` 与"固件校验/门禁"无关**（名字是"内存 guard page/哨兵"的 guard）。
`docs/QEMU_BOOT_PROGRESS.md` §116/§117/§104 记录了它们的战果与局限：
`libguard` 预加载后**没抓到**越界（因为损坏发生在 libguard 构造器之前的早期分配，`0x2b000~0x2e000`）；
`libredir` 才是破案工具。

**真正的"校验/门禁实验"在别处**（对我们最关键）：
- `docs/JIRITSU_CHANNEL.md` §5 表里：`updater_mode.py / updater_checkguard.py / updater_state.py`
  → **结论原文**："更新模式路线（**第 4 代 RSA 签名，自定义 body 不可行**）"，
  §6 补充实测现象："**`checkGuard` 报 Invalid version**、`TEST` 一直 Invalid Command"。
  （这个 `checkGuard` 正是我们 A7C `libupdaterbody.so` 里 `executeGuard / CheckGuardResult @0x13758` 那套机制在 PC 端 PMCA 流程里的对应物。）
- `docs/FIRMWARE_REPORT.md` "三·补"（2026-10-15 晚的重大订正）：见 §7。

---

## 5. 分区表与镜像读写工具（有没有 Sony 私有分区表解析器 / edisx、uc_mkfs 的等价物）

### 5.1 他们用的"工具"清单与用法

| 工具 | 用法 | 说明 |
|---|---|---|
| `data/partition_map.tsv` | 直接查表 | **分区表 + 偏移换算**：列含 `start_hex / size_bytes / mount / fs / flag / package_image / package_image_bytes / sha256`；表头注释即规则 `镜像偏移 = 表内偏移 + 0x400000（boot0 2MB + boot1 2MB）` |
| `docs/HANDOFF_2026.md` §追加 1 | `nflasha2 表 0x00800000 → 镜像 0x00C00000 ✓ 实测 FAT 在此` | 同一规则的第二次确认 |
| `docs/QEMU_BOOT_PROGRESS.md` §134.3 | **反例**：`nflasha10 在 .img 文件里 = 0x0B000000，但真机 eMMC 用户区 = 0x0AC00000（块 0x56000）` | 用 md5 交叉验证纠正过（`3a75a7c0…` 对上 0x0B000000） |
| `scripts/build_patched_emmc_safe.sh` | `debugfs -R "rdump / tree" nflasha15.img` → 宿主 Python 改字节 → `mkfs.ext2 -b 1024 -I 128 -O ^resize_inode` + `mke2fs -d tree` → `e2fsck -fy` → `dd` 回整盘镜像偏移 | **这就是"重新打包分区镜像"的等价物**（不是 edisx，不改分区表） |
| `display/probe/README.md` | `debugfs -w -R "write libgrmlog.so /lib/libgrmlog.so" nflasha7.img`；`printf '/lib/libgrmlog.so\n' > ld.so.preload && mcopy -i nflasha10.img ld.so.preload ::/` | **host 侧写 ext2/vfat 分区镜像的两种手法**（ext2 用 debugfs，FAT 用 mtools） |
| `scripts/run_armv7_payload.sh` | `qemu -M cxd90045 -device loader,file=payload.bin,addr=0xFE020000 -S -gdb tcp::1235` + `gdb -ex "set $pc=…" -ex "set $sp=0xFE100000" -ex continue` | **在 QEMU 里跑救援 payload**（纯软件演练，零真机风险） |
| `tools/port/{parse_imdb.py,parse2.py,freespace.py,abi_closure.py,check_reverse_closure.py,xrefs*.py,resolve.py,parse_uxac.py,scan_pngs.py}` | `python3 abi_closure.py <解包目录>` 等 | 不是分区工具，是**二进制兼容性/补丁空间**分析：`freespace.py` 找 `.rodata` 里未被重定位引用的字符串（可覆写腾出补丁空间），`parse2.py` 按 44 字节记录解 `libIMDB` 条目 |
| `scripts/gen_all_stubs.py` | `gen_all_stubs.py <libIMDB.so> <已有lib目录> <输出源码目录>` | 从 IMDB 表生成缺失库的桩（跑 App 用） |
| `tools/abtest/{run_ab.sh,ab_wrapper.sh,bsa_server_wrapper.sh}` | 成对跑改前/改后 | A/B 对照包装器 |

### 5.2 有没有 Sony 私有分区表写入器的 host 等价物？

**没有。** 他们的做法是"**不重建分区表，只重写分区内容**"：
- 分区表本身由相机自己的 `edisx.elf /dev/nflasha partinf.conf` + `uc_mkfs.elf -m full|app` 负责
  （这两个 ELF 就在 **A7C 的 `updater.img_unpacked/bin/`** 里，我们已有）；
- `chknandcapa.elf partinf.conf` 会拿包内分区表去 `ioctl` 查真实 NAND 容量 ⇒ **改分区表必须过这道关**；
- host 侧只有 `partinf.conf`/`mount.conf` 的**文本解析 + dd 偏移规则**（`data/partition_map.tsv`）。
- 另有一条硬事实：`nflasha` 块设备是 `emmc.ko` 自己按 MTD 接口注册的
  （`docs/QEMU_BOOT_PROGRESS.md` §160：`cat /proc/partitions` 看不全），
  所以 host 侧 dd 只能按"整盘镜像 + 表内偏移 + 0x400000"来写，不能用 parted/losetup 那套。

Sony 自己那套的语义（`rescue/docs/ARMv7_方案_定稿.md` + `docs/QEMU_BOOT_PROGRESS.md` §19-§28）值得记住：
`WBI`（nflasha5，`WBI1` 魔数）里带 eMMC 型号/分区表信息，`emmc.ko` 会做 `tbl_valid` 校验，
**型号不匹配 ⇒ 分区表校验失败**；QEMU 里是靠"补 CID + 造 eMMC 信息表 + `fixup_part_conf`"才过的。
⇒ A7C 上**绝不要用 host 工具重写分区表**；要改就改内容，且保住 nflasha5/WBI 一致性。

---

## 6. 可直接迁移到 A7C 的做法（6 条，含风险与失效模式）

**M1. 用"dat4 版本杠杆 + 官方包重刷"当作实证过的兜底（最高性价比）**
zve10 真机已验证：`printf '\000\000' > /setting/updater/dat4` → 相机报 0.00 → 官方包能灌进去 → 回到出厂。
A7C 对应物：`/setting/updater/dat4`（vfat 明文分区 nflasha2，写它不需要任何解锁）。
风险：更新器会重写系统分区（等于恢复出厂），我们自己的改造会被抹掉（可接受）；
失效模式：若 A7C 的 `dat4` 格式与 ZV-E10 不同（我们是 `ud_datcnv.elf -e` 加密写），直接改 2 字节可能被 `verskip/ac_flag` 逻辑忽略 ⇒ **必须先备份 `/setting/updater/dat4`，在 QEMU 里先验一遍再上真机**。

**M2. 所有 /usr 改动改成"旁路 + 看门狗回滚"，不要原地写 nflasha15**
照抄 `ANTIBRICK_SYSTEM.md` L1/L2：新文件放 `/log`（nflasha11，500 MB），`mount --bind` 覆盖目标；
开机 agent 在 N 秒内没在 `/proc/*/maps` 里看到 `viewUnified*/appFw.so` 就自动 umount + 删旗标 + 重启。
失效模式：agent 自己是通过 `ld.so.preload` 注入的 ⇒ 它一旦坏，机器就进 boot-loop（这正是 zve10 的事故），
所以 agent 必须过 `LD_PRELOAD=<so> /bin/true` 单进程纪律，并且**preload 条目写在 nflasha10 根目录**（= 真机 `/etc`），
出事时能用"1 字节清 size"救回。

**M3. 任何写入前：全盘 dump + SHA-256 + 偏移三重校验**
zve10 的纪律是"17 个分区 + nflashaB0/B1 + 整盘 1.85 GiB 全备份，写后完整读回 SHA-256"。
A7C 必须同样记住两个偏移口径：
`partinf.conf 表内偏移 + 0x400000 = .img 文件偏移`，而**真机用户区偏移 = 表内偏移本身**。
失效模式：把 12 MB 分区写到 `0x0B000000`（文件口径）而不是 `0x0AC00000`（用户区口径）⇒ 写进错误区域（他们差点就做了）。

**M4. 把救援 payload 做成"零写入优先 + 幂等 + LED 结果码"**
`hardware/README_盲操作容错版.md` 的 5 步（扫 32 个根目录块 → 校验 attr/size 合理性 → 清 `+28..31` → 写 1 扇区 → 读回校验 → 失败恢复原值）
+ 结果码 `[0xA5/0xE1..0xE5]` 写 SRAM `0xFE02F000` + LED 播报。
A7C 直接可用（同 FAT 布局、同 12 MB nflasha10、同 LED 机制：`error.led=0,0` → port0/bit0）。
风险：真机 eMMC 若非高容量（<2 GB）⇒ **CMD17/24/25 的 ARG 要用字节地址**；
`wdt.timeout=500` ⇒ 只能单块写，不能 12 MB 连续写（除非 payload 先关看门狗 `0xF2402000/0xF2402004`）。

**M5. 用 BootROM 串行启动做"离线写 eMMC"，token 从自己 boot0 取**
接线（D−→470Ω→RP2040 GP28，D+→470Ω→RESET，CC 各 5.1 k 下拉，外部 5 V，open-drain，48000 8O1）
+ 组帧（SET_UNLOCK→MEM_WRITE(≤4086)→SET_ENTRY→SET_UNLOCK，间隔 14.4 ms，组 <1.45 s，慢块 250 µs）
+ **解锁 V/C 从本机 boot0 @0x200 读**（不是任何公开常量）。
A7C 的可信度很高（`ROM_VERIFY.md` 逐条吻合，且仓库多处引 A7C 实测数据）。
失效模式：①找不到物理测试点（ZV-E10 就是卡在这）；②信号质量 ⇒ 0x2004/0x1002 交替出现（用 <10 cm 短线 + 可靠共地）；
③数据阶段（CMD17）在 ZV-E10 尚未打通 ⇒ 先按 `ROM_EMMC_INIT.md` 调 ROM 的 `0xFFFF2278` 初始化 + `0xFFFF25A3` 多块读，而不是自己写描述符。

**M6. 改包验证顺序：先在 QEMU 里跑 `mf`/`UdtrMain.sh`，别先上真机**
`FIRMWARE_REPORT.md` 三·补的四条证据链（见 §7）已经把"能不能自造升级包"钉死为
**"解得开、造不出"**（RSA-2048 签名 + `AesCbcCrypter.encrypt()` 抛异常 + `crypter.elf` 只有解密类）。
所以 A7C 的现实路线是：**改相机里的东西（分区内容 / preload / 旗标 / bind 覆盖），不改升级包**；
若一定要走升级包，就把"绕验签"做在**相机侧**（patch `mf` 的 `SignatureVerification` 分支），
而不是试图造签名。风险：改 `mf`/更新器 ramdisk = 触碰 L0 铁律区（`nflasha1`），无软件救路。

---

## 7. 与现有 `UPDATER_ANALYSIS.md` 的衔接点 / 需要复核的地方

| 我们的结论（A7C） | zve10 侧的对应/补充 | 要做什么 |
|---|---|---|
| "更新器侧没有签名，只有 CRC32+size" | **成立但范围不完整**。`FIRMWARE_REPORT.md` 三·补证据 2/3：FDAT 尾部 `272 字节 = 256B RSA-2048 签名 + 16B IV`；公钥在 `0400_updater/.../initrd.img_unpacked/etc/VerificationKey.pem`、`nflasha15_unpacked/share/data/pub.key`、`kikilog_pub.pem`；验签类在 **`mf`**（`N7Updater21SignatureVerification`、`PEM_read_RSA_PUBKEY`、`RSA_verify`、`"Signature Verification Error"`） | A7C 包里**没有** 0400_updater，我也**没在 A7C 解包件里找到** `VerificationKey.pem`/`pub.key`（只有 `share/network/cert/certification.pem`）⇒ **必须 dump A7C 的 nflasha1 才能确认公钥与 `mf` 是否存在**；`mf`/`sauu` 也不在 A7C 的 nflasha15/bin 里 |
| "`KeyArray = SHA256("")` 32 B，真实密钥可能按 chassis 注入" | **已解出**：fwtool `constants.py` 的 `key_aes = E3B0C442 98FC1C14 9AFBF4C8 996FB924`（正是我们看到的 KeyArray 前 16B）+ **`key_cxd90045_k0` / `key_cxd90045_k8`（各 32 B）**；映射 `AesCbcCrypter(key_aes, key_cxd90045_k0)`；`config.yaml` 里 ZV-E10 用 `CXD90045_k0`、ZV-1F 用 `CXD90045_k8`（`data/machine_comparison.tsv`） | A7C `config.yaml: dat.crypterName: CXD90045`（无 `_k0/_k8` 后缀）⇒ **要核对 fwtool `devices.yml` 里 ILCE-7C 条目用哪把 key**（A6400 同 chassis 用 `_k0`）。这把 key 是公开的，"解得开"没问题 |
| "`Dec_Scramble` 是唯一的密码学操作（AES-128 ECB 16B）" | zve10 侧确认 FDAT 是 **AES-CBC**（不是 ECB）；ECB 那套（`Dec_Scramble`）在相机侧的 dat/通信路径 | 两者不冲突：一个是包解密（fwtool/AES-CBC，密钥公开），一个是相机内 scramble。别混用 |
| "mode6 / mode2 / `program/` PATH 注入 / `uconfig.xml` 是官方留的口子" | zve10 完全一致，并补了 `getCurrentMode()` 的**完整分派代码**（`/root/IAMLDUDWRT` → PROD(串口 boot 工厂下载写入)；mode3=MINOR、mode2=SERVICE、mode6=VERSKIP、mode1=PROD、mode5=MSCRYPT），以及 `up.sh` 的 `func_verskip(){ rm -f $UPDIR/mode*; touch $UPDIR/mode $UPDIR/mode6; sync; }` | A7C 上优先用这些旗标；注意 `/root/IAMLDUDWRT` 同时是 QEMU 里"开 root shell"的开关（§112），两者语义别搞混 |
| "`part_image.sum` 只 4 个分区，本包不换 nflasha1" | 与 ZV-E10（包内**带** nflasha1）不同 ⇒ A7C v2.00 确实不换更新器 ramdisk | 想改更新器必须自己 dump nflasha1 |
| "`us_mkfs.sh`/`edisx.elf` 重写分区表 = 破坏性" | 一致，另加：`chknandcapa.elf` 会 `ioctl` 查真实 NAND；`emmc.ko` 按 CID 查型号表；WBI(nflasha5) 承载 eMMC 型号/分区表 ⇒ 改分区表路线要过三道 | 我们若只改 nflasha15 内容，就不要碰 partconf/partition 表 |

**待补的一条 A7C 实测（本 worktree 里没有 .dat 原件）**：git index 里 staged 了
`FirmwareData_ILCE7CV200.dat` / `firmware.fdat` / `fdat_dec.bin`，但当前工作区没有这些文件。
补齐后按 zve10 的方法验签名（`FIRMWARE_REPORT.md` 三·补证据 2）：
```bash
python3 -c "import os,sys;n=os.path.getsize(sys.argv[1]);print(n,n%1024,hex(n))" firmware.fdat
# 期望：n % 1024 == 272  (= 256 字节 RSA-2048 签名 + 16 字节 IV)，且密文块数 = n//1024
tail -c 272 firmware.fdat | xxd | head   # 前 256B 签名，最后 16B 是 CBC IV
# 对照：A7C 已解出的 firmware.tar 是标准 ustar ⇒ 解密这步公开密钥就够（不需要 Sony 私钥）
```
若这条成立 ⇒ **A7C 与 ZV-E10 一样"解得开、造不出"**，改包必须绕相机侧验签而不是自签。

A7C 侧我实跑过的核对命令（可复现）：
```bash
# 分区表与 ZV-E10 是否一致
diff <(sed -n 's/\r//g;p' config.yaml) /dev/null; cat firmware.tar_unpacked/0100_config/mount.conf
grep -E "^0x" firmware.tar_unpacked/0300_partconf/partinf.conf
# /usr（nflasha15）空闲量
python3 - <<'PY'
import struct
d=open('firmware.tar_unpacked/0700_part_image/dev/nflasha15','rb').read(0x500)
sb=d[0x400:0x500]
u32=lambda o: struct.unpack_from('<I',sb,o)[0]; u16=lambda o: struct.unpack_from('<H',sb,o)[0]
print(u32(0), u32(4), u32(16), 1024*(1+u16(24)))   # inodes blocks free bsize
PY
# busybox 是否动态链接（= 变砖失效模式成立）
file firmware.tar_unpacked/0700_part_image/dev/nflasha7_unpacked/bin/busybox
# /etc 是不是空挂载点（= /etc 来自 nflasha10）
ls -la firmware.tar_unpacked/0700_part_image/dev/nflasha7_unpacked/etc
strings -a firmware.tar_unpacked/0700_part_image/dev/nflasha3_unpacked/initrd.img_unpacked/sbin/init | grep -nE "/etc|nflasha10|TOPRC|move_partition"
```

---

## 8. 给下一步的最少动作清单（按优先级）

1. **dump A7C 全盘 eMMC**（含 boot0/boot1）：拿到 ①`nflasha1`（更新器 ramdisk、`mf`、`dat2/dat3`、`p1chksum`）②`/setting`（`kemco.txt` 的 cmdline、`updater/dat4`、`mode*`）③boot0@0x200 的解锁 (V,C)。**没有它，后面全堵。**
2. 在 QEMU 里用 `scripts/run_qemu_zve10.sh` + `shell_*.sh` 的骨架（同 SoC，机器模型 `cxd90045` 直接可用）跑 A7C 镜像，先复现"更新器 ramdisk root shell"与 `UdtrMain.sh` 模式判定。
3. 在 QEMU 里对 A7C 演练三件事，再谈真机：(a) `dat4=0000` 的版本杠杆；(b) 一个改过的 `firmware.tar` 走到哪一步失败；(c) 1 字节清 `ld.so.preload` size 的 payload。
4. 若要做真机救援硬件：先按 `hardware/BOOTROM_RESEARCH.md` 的 BGA 球位 + a6400 MULTI pin 定义（pin8 TX / pin9 RX / pin10 BOOT_SERIAL_IN）向维修圈问 A7C 的点位；ZV-E10 的"USB-C D−(A7)+470Ω"经验不能直接假设 A7C 相同。
