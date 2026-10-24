# GitHub issue #23（QAQLeonard/a7c2-fl23-research）—— hnws 在 ILCE-7C **2.03** 上打通 Jiritsu root
记录日期：2025-10-24。用途：交叉验证我们的通道结论 + 列出可借/可赠/存疑。

## 他打通的东西（与我们一致 ⇒ 置信度↑）
- `054c:0d29`(MSC) → `StartSenser` → **`054c:0336`** 服务会话 + PMCA SHA-256 静态密钥（`libsencore.so` 三把 key 与 PMCA 仓库字节一致）⇒ 与我们 `notes/jiritsu.md` 一致。
- `adj_cmd_set_file2` 写 `/tmp/jiritsu/libJit.so` → `dlopen(path,1)` → `_init()` 以 **root（euid=0, pid=im.elf 162）**跑；载荷必须 **ARM32 EABI**，`e_flags` 后处理成 `0x5000002`。
- 挂载表与他一致（= 我们 `mount.conf` 实测）：`a7=/`、`a15=/usr`、`a10=/tmp`、`a3=/system`、`a2=/setting`、`a11=/log`、**`a6=/tmp/jiritsu`**（挂上后）。
- **新信息（记下）**：退出 `0336` 会短暂出现 **`054c:0994`** 中间态，期间新的 `StartSenser` 无效；等 ~30 s 回 `0d29`。与 a7c2 的 `0D68 -> 096F -> MSC` 同类。
- **可直接抄的技巧**：A7C 出厂**没有** `/tmp/jiritsu`，第一次 Jiritsu 文件命令在 `mount("/dev/nflasha6","/tmp/jiritsu","vfat")` 返 **`0x10000004`**（`sys_mount` 只把 EBUSY 当"已挂载"）。他的绕法：`select("/mnt/../tmp/jiritsu/.keep")` + `set_file2(mode=1, data="x")` ⇒ 内部 `sys_dir_create2()` 逐级 stat/mkdir `/mnt`、`/mnt/..`、`/mnt/../tmp`、`/mnt/../tmp/jiritsu` ⇒ 目录建出来（在 `/tmp`=a10 vfat，持久），之后 mode 0 的 a6 挂载就成功。**我们的 `tools/jiritsu_send.py` 应当内置这个前置**。

## 他给我们的新内容面（我们此前没做过这条线）
- `/system`=**a3 vfat rw**，里面 8.3 文件名（我们 2.00 的 a3 dump `work/l1_v/nflasha3.bin`，md5 前缀 `79f0190091d0`，目录项在 `0x8220`）：**`AV-CAM`、`BONOBO`、`DFE_APP`、`DFE_DAT`、`LDR_DRV`、`LIF_APP`、`VMLINUX`、`WOLE_APP`** ⇒ 一批 DSP/协处理器平铺镜像，**都是可改的内容面**。
- `av-cam.bin`（他 2.03 = **17,398,676 B，md5 `440c2a3e77a43c16c2bae5af2f3845c9`**）由 **`/usr/kmod/liro.ko`** 加载到 **DSP 平铺地址 `0x635c6000`，入口 `0x635c6044`**；`/usr` 里有 `liro`(62)、`/system/av-cam.bin`(1)、`ft_backup`(1)、`OnDemandLoader`(21) 字符串 ⇒ **2.00 也是同一机制**（我们 a15 里就有这些串）。
- 3D LUT：文件偏移 **`0x108c9c4`**（VA `0x646529c4`）是指针表，`case0..3` 偏移 `+0x2c88/+0x7e34/+0x4bd0/+0x70d0` → `0xF7EF9A/0xF7F4CE/0xF7FB6E/0xF802D6`，各 **405×3=1215 B**，**当前全 0**。
- a15 里有 **`openssh`、`wpa_supplicant`、`hostapd`、`telnetd`** 串（我们实测计数：openssh 5 / wpa_supplicant 61 / hostapd 23 / telnetd 7）⇒ issue 里"开 ssh server 走 Wi-Fi"的建议**有硬件/软件底子**，但服务端是否真在 `/usr/bin` 里、服务模式下 Wi-Fi 是否可起，仍需验证。

## 我们能反向赠他的（含一条可能直接解他卡点）
1. **地址空间判断（可能直接解释他的失败）**：出厂命令行给出的 ARM 内存图 = `mem=1G@0` + 第二 bank `mem=1016M@0x80000000@1`（升级）/`mem=256M@0x80000000@1`（主系统），外加 `memrsv=680M@0x15800000:uc`、`memrsv=0xAEEB000@0x0A915000`、`memrsv=0x1A5E000@0x02E68000` 等。**`0x635c6000`（1.55 GB）不在任何 ARM `mem=` 窗口里** ⇒ 它是 **DSP 侧地址**，所以 `open("/dev/mem")` 读 `0x635c6000` 打到非 RAM 窗口（挂死 USB 完全合理）。⇒ 别再从 ARM 侧找 DSP 地址。
2. **平铺镜像 ⇒ 不需要运行时物理基址就能改**：他自己的数据就证明 `VA − 0x635c6000 == 文件偏移`（`0x646529c4 − 0x635c6000 = 0x108c9c4`）。所以**改文件让 liro 重载**就是正门；运行时基址只在"热改内存"时才需要。
3. **备份/恢复原语（他"不敢改"的解药）**：我们有 FileControl `fget` 整分区 dump 通道（a3 已在手）+ **QEMU 离线已证的写回 R1**（闭源 AL_EMMC 驱动写 `/dev/nflashaX` → guest 内 `reboot` → 重启后读回同一 md5）。⇒ 先把 a3 整分区备份 + 演练过回写，才谈改 `/system/av-cam.bin`。
4. **3.0.27 内核的可编译配方**（Bootlin 2018.02 gcc 6.4 + `KCFLAGS=-fno-builtin-memset` + Sony `memset.S` 返回 `dst+len` 的坑）+ 同 SoC（CXD90045）全系统 QEMU（`cxd90045` 机器，真 eMMC 镜像 + 真 initrd）⇒ 可离线跑 `liro.ko` 的加载路径、看 `adr/fn/load` 参数与 `ft_backup`，比扫 `/dev/mem` 稳。

## 存疑 / 别照抄
- 他的 LUT **只做了 Unicorn 单元级**（`fn_63b14a48` 的 `Create3DLUT` 分支 405/405 变化）⇒ 证明"源表被读"，**没有运行时调用证据**；而 A7C 菜单里**没有 Creative Look/Custom Look** ⇒ 这条 LUT 通路在 A7C 上是否被调用仍未证（E0）。要打进去之前先找调用点/开关。
- `udrt_dic` 在 `0x22d63000` 推不出 av-cam 也在 `0x20xxxxxx`（QAQLeonard 已指出，我同意）。
- `CAMPRxxN/P.DAT` 与 look 的关系是推测（E0）。
- 他的固件是 **2.03**，我们的相机是 **2.00** ⇒ 任何偏移/哈希都要**跨版本重新对**（我们两边 a1 都有：`work/l1-camera/a1_initrd` 与 `a1_extracted_203`）。

---
# ★我们这边的跨版本对照（ILCE-7C **2.00**，本地解包，E3）
产物：`work/a3-avcam/{AV-CAM.BIN,README.md}`。输入 = `work/l1_v/nflasha3.bin`（2.00 的 `/system` 整卷 dump，**30,290,944 B**）。

**卷结构（FAT12，不是 FAT16）**：真 BPB **就在 offset 0**（之前 `FATs=512` 是把 root entries 读串了）：`bps=512, spc=32（簇 16 KiB）, reserved=1, FATs=2×32 扇区, root 512 项 @0x8200, 数据区(簇2)=0xC200, 总扇区 59162`，**FAT1==FAT2 逐字节一致**，共 1845 数据簇。
**dump 不截断**：BPB 声明的卷大小 `59162×512 = 30,290,944` **正好等于 dump**；48 MiB 分区的尾部 ~19 MiB 在 FAT 卷之外 ⇒ 之前"可能截断"的担心作废，**md5 可信**。AV-CAM 簇链 `3→…→1064` 正常终止、末簇完整。

## `AV-CAM.BIN`：2.00 vs 2.03
| | 2.00（我们） | 2.03（hnws） | 差 |
|---|---|---|---|
| size | **17,394,576** | 17,398,676 | **−4,100 B** |
| md5 | **`8a3822728974abd4f7704e7f57339d4f`** | `440c2a3e77a43c16c2bae5af2f3845c9` | 不同文件 |
| sha256 | `0113bf72…7524d0f9`（全值见 `work/a3-avcam/README.md`） | — | — |
| ORIL 头 | 文件偏移 **0x4**（全文件仅一处）：`0a0000ea|ORIL|v4|entry 0x635c6044` | 同样字段 | **头完全相同** ⇒ **2.00 的 DSP 平铺基址也是 `0x635c6000`**，`VA − base == 文件偏移` 成立 |

## ★LUT 指针表：2.00 里存在且同构，但**偏移整体平移**（打补丁必须按版本重算！）
锚点：THUMB2 字面量池 `0x550dfc` 含同一组 profile 常量 `0x2c88/0x4bd0/0x70d0/0x7e34`（说明**选择逻辑相同**，只是表基址移动）。
| 项 | 2.00 | 2.03 | Δ |
|---|---|---|---|
| 表基址 | VA `0x646519c0` / 文件 **`0x108b9c0`** | VA `0x646529c4` / 文件 `0x108c9c4` | **−0x1004** |
| `+0x2c88` | `0x64543f9e` / 文件 `0xF7DF9E` | `0x64544f9a` / `0xF7EF9A` | −0xFFC |
| `+0x7e34` | `0x645444d2` / 文件 `0xF7E4D2` | `0x645454ce` / `0xF7F4CE` | −0xFFC |
| `+0x4bd0` | `0x64544b72` / 文件 `0xF7EB72` | `0x64545b6e` / `0xF7FB6E` | −0xFFC |
| `+0x70d0` | `0x645452da` / 文件 `0xF7F2DA` | `0x645462d6` / `0xF802D6` | −0xFFC |
四段 `405×3=1215 B` 在 2.00 里**同样全 0**（前 16 B 全零、非零字节计数 0）⇒ 与 2.03 一致，"表存在但没被填"是一代两版共同的现状。

## a3(/system) 全清单（2.00，size/md5）
`AV-CAM.BIN 17,394,576/8a382272…`、**`VMLINUX 4,117,632/a73bf8a7…`**、**`INITRD.IMG 2,186,240/ca8ae5d1…`**、`BONOBO 172,144/37d65ffe…`、`BT_FIRM.HCD 61,787/be8ac916…`、`DFE_DAT 65,536/8c5f3b19…`、`DFE_APP 1,956/4d6d2507…`、`LDR_DRV 7,012/7c8c16cd…`、`LIF_APP 6,716/7f4be40e…`、`WOLE_APP 10,768/265bd0fd…`；另有空子目录 `LENSBI~1`、`SABIN`。
**★对我们的含义**：**主系统的内核与 initrd 就是 `/system` 里的普通 vfat 文件**（`VMLINUX` + `INITRD.IMG`，2.18 MB —— 注意它不是 a1 里那个 8 MB 的升级 initrd）。⇒ ①**a3 在启动链上**，改它等于改启动件；②若 EXBL 不校验它们（仍未证，靠 `nflashaB0/B1` dump 才能定），那"**改 `/system/VMLINUX` 或 `INITRD.IMG`**"可能比改 a1 的 cramfs initrd **容易得多**（vfat 文件、不涉及 updater 的 RSA 签名门）；③我们的 QEMU 未来可以直接用这份真 `VMLINUX`/`INITRD.IMG` 起主系统（离线跑 `/usr` 侧）。
