# a3 = 机身 /system（FAT12，簇 16 KiB）摊开的清单

> 由 100.122.234.78 上 `qoderclicn -m DeepSeek-Flash` 子代理产出（脚本 `tools/fat12_walk.py` 可复跑）。
> **主会话独立复核**：`sabin/ssboot.bin` 偏移 `0x139C200`/11,280 B/md5 `0fb03e48…` ✓、`sabin/ssboot_any.bin` `0x13A0200`/9,648 B/md5 `f8ec8bb1…` ✓、
> 两者 `+0x04` 处 ASCII **`B4`** 魔数 ✓、`initrd.img` 在 `0x438` 处 magic `ef53` ⇒ **ext2（不是 cramfs）** ✓、`vmlinux.bin` 开头是裸 ARM32 指令 ⇒ 未压缩内核 ✓。
> FAT 参数：512 B/扇区、32 扇区/簇（16 KiB）、保留 1 扇区、FAT×2 各 32 扇区、根目录 512 项、数据区 `0xC200`，簇 N 偏移 = `0xC200+(N-2)*0x4000`；
> FAT1==FAT2、每条簇链长度与文件大小精确吻合、20 条 LFN 校验和全对、无交叉链接/无已删项。

| 文件 | 字节偏移 | 大小 | md5 | mtime |
|---|---|---:|---|---|
| `/dfe_app.bin` | `0x0x10e4200` | 1956 | `4d6d250734e0ad2e…` | 2021-11-14 19:41:56 |
| `/lif_app.bin` | `0x0x1340200` | 6716 | `7f4be40e8dc6afe2…` | 2021-11-14 19:41:56 |
| `/ldr_drv.bin` | `0x0x1310200` | 7012 | `7c8c16cd10909785…` | 2021-11-14 19:41:56 |
| `/sabin/ssboot_any.bin` | `0x0x13a0200` | 9648 | `f8ec8bb13e1efa7d…` | 2021-11-14 19:41:56 |
| `/wole_app.bin` | `0x0x1794200` | 10768 | `265bd0fd0646e86b…` | 2021-11-14 19:41:56 |
| `/sabin/ssboot.bin` | `0x0x139c200` | 11280 | `0fb03e483e4e4371…` | 2021-11-14 19:41:56 |
| `/bt_firm.hcd` | `0x0x10d4200` | 61787 | `be8ac9166791929f…` | 2021-11-14 19:41:56 |
| `/dfe_dat.bin` | `0x0x10e8200` | 65536 | `8c5f3b191dd124cf…` | 2021-11-14 19:41:56 |
| `/sabin/sa_dfdet.bin` | `0x0x1374200` | 156292 | `553238d64f4abd1c…` | 2021-11-14 19:41:56 |
| `/lensbin_lensproperty/LensAberrationData.bin` | `0x0x1318200` | 161766 | `84e7f61b0e60184f…` | 2021-11-14 19:41:56 |
| `/bonobo.bin` | `0x0x10a8200` | 172144 | `37d65ffefb84423d…` | 2021-11-14 19:41:56 |
| `/sabin/idt_cam.bin` | `0x0x1348200` | 176528 | `c8785e6d48eaeb65…` | 2021-11-14 19:41:56 |
| `/initrd.img` | `0x0x10f8200` | 2186240 | `ca8ae5d1ce551ed9…` | 2021-11-14 19:41:56 |
| `/vmlinux.bin` | `0x0x13a4200` | 4117632 | `a73bf8a79adc7174…` | 2021-11-14 19:41:56 |
| `/av-cam.bin` | `0x0x10200` | 17394576 | `8a3822728974abd4…` | 2021-11-14 19:41:56 |

## SSBOOT / B4 家族

- 两个 ssboot 去头后 **94.88% 相同**（最长连续 1,444 B）；与 `sabin/idt_cam.bin` 同一 **B4 家族**（共享 48 字节序列、同常量、同指针表）。
- 头部 `+0x2C` 恒为 `0x682`；`+0x54` 起指针全落在 `0x48000–0x49E00` ⇒ 按基址 **`0x48000`** 装载（SABIN 子系统侧的小地址空间，不在 ARM `mem=` 窗里）。
- **无版本串**（ASCII/UTF-16 都扫不到 ≥8 字符的正常串，没有 Linux/Sony/version/copyright）；**无压缩也无加密**（熵 6.32/6.35，压缩流通常 >7.9；0x00 占 19%/18.6%，内部有 1,504 B 重复块、相似度 92–95%）；无 gzip/xz/lz4/zstd/cramfs/squashfs/ELF/uImage/FIT 魔数。
- 按 ARM/Thumb/MIPS/SH/M68K/Xtensa 反汇编都不成代码 ⇒ 判断是 SABIN 子系统的**启动配置/寄存器表/系数数据**，由驱动按 B4 协议下发（子代理推断，我未独立证）。
- 名称撞车提醒：内核里的 `kernel/power/ssboot` 是 suspend/resume 快照，跟这两个 blob 无关。

## 为什么值得记

- a3 是**官方更新会写的分区**（包内 tar 的 `0700_part_image/dev/nflasha3`），也正是 `kemco.txt` 里 `cmpr.path=/system/sabin/ssboot.bin` 指向的地方 ⇒ 改 SABIN/DSP 侧加载数据只动 a3，不用碰 a1。
- `initrd.img` 是 **ext2** ⇒ 改主系统 initramfs 比 a1 的 cramfs 好办（ext2 可以 loop-mount 直接改）。
- 这批 DSP/协处理器固件（`av-cam.bin`、`dfe_app.bin`、`idt_cam.bin`、`bonobo.bin`、`bt_firm.hcd`、镜头校正数据）第一次有了完整偏移/md5 清单 ⇒ 以后要做"只换某个 DSP 固件"的实验，改 a3 里对应文件即可（风险仍在 a3 半刷面里，见 `CHECKPOINT.md` §4d）。
