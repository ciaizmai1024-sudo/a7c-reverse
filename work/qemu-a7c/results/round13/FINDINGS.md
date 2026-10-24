# Round 13 — 正常分支靠 RAM 预填打通（保真）；guest 自发 reboot 闭环；mode5 链走到 sdfileinput 卡访问层

## ① A：`insmod backup.ko Backup_save=0`（不带 Backup_load）——**通**
- QEMU bionz.c 新增 env **`A7C_RAM_BLOB=path[@addr]`**（默认 addr 0x02e80000）：`load_image_targphys` 把**未改一字的真机 `Backup.bin`**（md5 `7a549d06…`，1,210,408 B）预填进 guest RAM `PA 0x02e80000`；注册成 rom ⇒ **每次复位自动重灌**（≈"EXBL 每次冷启把 backup blob 装进 RAM"）。
- 判据（`r13_blob4_boot1/2.ser`，initrd 里只有 insmod.sh 的 RC/kallsyms 打印，**insmod 命令行一字未改**）：
  - `R13-INS-NORMAL-RC=0`、`R13-KSYMS=38`、`R13-BAK-LOADED-NORMAL`，串口**没有** `backup_init() error (file_load)`。
  - 对照（`r13_ctl_boot1.ser`，同一 initrd/内核，不预填）：`RC=5`、`KSYMS=0` ⇒ 正常分支吃的确实**只有 RAM**，与 Round 12 的 `arch_phys_to_cache(hdr+0x00)` 结论闭环。
- **RAM 保留结论**：a1 命令行里出厂就带 **`memrsv=0x75e000@0x02E68000`**（覆盖 0x02e80000..blob 尾 0x02fa7828），无需加参。源码级：`arch/arm/mm/init.c:parse_memrsv` 把区域登记进 `reserved_mem[]` 并在 bootmem 里置"已用"，而 `CONFIG_EJ_CLEAR_MEMORY` 的 `bootmem_clear()` 只 memset **空闲**页（打 `memclr:`）⇒ 预填内容活到 insmod。`/dev/mem` 探针（`bs=1024 skip=189440 count=64`）读出 `R13-RAMBLOB-MD5(head64K)=fcd6bcb56c1689fcef28b57c22475bad`，而文件头 64K=`556727a6…` —— **RAM 头 64K ≠ 文件头 64K**（E2 推断：真机 RAM 里是"活的/带脏记录"的 backup 副本；文件是落盘态。对判定无碍：hdr+0x00..0x10 与 BK4/cookie 校验都过、38 符号在）。
- boot2（guest 自己重启后的第二轮）同样 `RC=0/38`（rom 重灌生效）⇒ 重启后正常分支仍可复现。

## ② B：内核开 `CONFIG_CXD900X0_PCIE2_DME` → **`insmod mmc_drv.ko` RC=0**
- `ksrc-v3` 复制为 **`ksrc-r13`**，沿用 gcc-6.4 Bootlin 配方（`CROSS_COMPILE=~/sony-src/armv7-eabihf--glibc--stable-2018.02-1/bin/arm-linux-`、`LD_LIBRARY_PATH=~/sony-src/mpfr4/usr/lib/x86_64-linux-gnu`、`KCFLAGS=-fno-builtin-memset`），改动：
  1. `arch/arm/mach-cxd900x0/Kconfig`：`CXD900X0_PCIE2_DME` 的 `depends on PCI && !CXD900X0_QEMU` → **`depends on PCI`**（QEMU config 下强开，偏离）；
  2. `arch/arm/mach-cxd900x0/include/mach/system.h`：`arch_reset` 里 `writel(0x52E57001, 0xf240f004)` **放在 `arch_reset_core()` 之前**（r11/r13a 证实 `pm_machine_reset(1)` 在 QEMU 里不回返）+ `#include <linux/io.h>`。
- 增量重编 ~1 分钟：`CONFIG_CXD900X0_PCIE2_DME=y`、`pcie.o/pcie_ctl.o/pcie_setup.o` 编入、System.map 含 `pcie_root_ctrl/pcie_slot_ctrl`；probe.c 里的 r7 链接桩因 `#if !defined(CONFIG_CXD900X0_PCIE2_DME)` 自动退场。新 `vmlinux.bin` md5 **`5ad80118…`**（基线 v3h 未动）。
- 结果：`R13-INSMOD-MCMN-RC=0`、**`R13-INSMOD-MMC-RC=0`**、`/proc/modules` 6 项匹配；无 Unknown symbol。a1 命令行的 `pcie.ch0_enable=Y` 等参数现在真被 pcie.o 吃掉，开机不死（QEMU 未建模 PCIe host，寄存器读 0 → root-mode 扫到 0 设备，良性）。
- QEMU cxd90045 **没有** Sony "MMC-on-PCIe-DME" host：mmc_drv 装载≠有卡；`/dev/mmca*` 无后端。最小 host 桩要造 Sony SD3.0 host 寄存器组 + DME 通道枚举，非本轮体量。

## ③ C：**guest 内 reboot 闭环**（QEMU 复位 hook 的 assert 也修了）
- Round 12 hook 在这个 QEMU 树里会炸：`qemu_system_reset_request()` 0 参（reason=NONE）→ `qapi_enum_lookup` assert → core dump（`R13-RESET-HOOK … Assertion 'val >= 0 && val < lookup->size' failed`，本树 run-state.json 的 ShutdownCause 枚举**没有 host-reset**）。r13 改为 **`qemu_system_shutdown_request(SHUTDOWN_CAUSE_GUEST_SHUTDOWN)`**（枚举安全）→ QEMU **exit 0**，wrapper（`run_r13.sh`，`-no-reboot`）见 RC∈{0,17} 就**同一持久 eMMC 镜像重拉**。
- guest 侧协议（insmod.sh 内，busybox 无 `od/head/conv=`，两轮踩坑后改净）：boot1 读 `/dev/nflasha23` md5≠P1 → 写确定图案 P1（`R13A23BOOT1`+零，64KiB，md5=`ef59d9108dca7e0105df50674ffce0b1`）→ `reboot`；boot2 读到 P1 → **`R13-A23-REREAD-OK-AFTER-GUEST-REBOOT`**（`r13_blob4_boot1/2`、`r13_m5_boot1/2` 两组都复现）。
- 即：**Round 11 的 a23 图案演练这次是 guest 自己重启后读回的**（写→guest reboot→QEMU 退出重拉→读回一致）。

## ④ D：mode5（存储卡）线 —— 走到 **sdfileinput.elf 被 exec、卡访问层失败**
- 静态（原生 a1 initrd + Bootlin objdump，`/tmp/sdpa.asm`=`libsdfileinputupdaterapi.so` 反汇编，随存）：
  - `UdtrMain.sh getCurrentMode`：`test -f /setting/updater/mode5` → `MODE_MSCRYPT`；`execute_ufp.sh`：`insmodMediaDriver`（mcmn_drv+mmc_drv）→ `sdfileinput.elf` → 成功后 `touch /setting/updater/MediaUpdateCompleteFlag` → `User Update OK` → `ud_reboot.elf`。
  - 卡布局关键字面：`BODYDATA.DAT`（sdfileinput.elf）、`"FDAT"`/`"found FDAT"`、`"%c:\%s"`（FAT 根目录名拼路径）、`SDUUDConditionChecker::searchFDAT`、`SDDecryptorModule::execWriteFirm`。
  - **验签语义（E1）**：`SignatureVerification::VerifySignature` = `SHA256(data=body_ptr−0x100, len)` → **`RSA_verify(NID_sha256=672, sha, 32, siglen=[hdr相关], sig, RSA 公钥)`**，公钥 **fopen `/etc/VerificationKey.pem`**（initrd 内，RSA-2048，模数见 `work/l1-camera/a1_initrd/etc/VerificationKey.pem`）⇒ 卡上 BODYDATA.DAT 头部带 **256 B RSA-2048 签名**，签名对象=其后 body。
- 实验：`a7c_emmc_r13_m5.img`（pt4 拷贝）里 a2 加 **`/setting/updater/mode5`**（a2 里出厂已有 `updater/comp`、`dat4`，无 `uincomp`）；卡 stand-in：12 MiB vfat（`r13_card.img`，含我们合成的 `BODYDATA.DAT`=FDAT 头+官方包 `udtrbody.bin`）**写进 a10**（host 偏移 176 MiB）；initrd `r13g`（mcmn/mmc insmod 交还给 execute_ufp；us_darwin_init 后台化 20s kill，偏离同 r12）。
- 串口（`r13_m5_boot2.ser`）：`[DETAIL] MODE=5` → `[DETAIL] : exec sdfileinput.elf` →（内核）`MMC:Failed mcmnd_api_getbkupinfo_bus_connect_type` → **`[FIRMUP NG] : Error 77`** → `[Error] : error sdfileinput`。
- **结论**：mode5 的 updater 层链在离线侧全活（旗标→模式判定→两个媒体驱动 insmod RC=0→sdfileinput 起），**停在卡 host**：mcmn 查 backup-info 总线连接失败→Fsys 挂不上 `/dev/mmca*`（QEMU 无 Sony SD host/PCIe-DME 通道模型）。**验签没到**：需要（a）真卡/真 payload（官方 BODYDATA.DAT 是加密+签名的，GPL 包里没有；我们只能合成未签名卡）或（b）QEMU 里造 SD host。离线"正向验签"因此**未证**，机制已钉死（上面 E1）。
- 顺带：busybox 无 `losetup`（RC=127），loop 兜底也没成；`up.sh`（a1 里的产线脚本）会 `touch $UPDIR/mode $UPDIR/mode5` —— mode5 就是"存储卡更新"旗的出处。

## ⑤ 偏离清单（不代表真机行为）
1. **QEMU 改动**：`bionz.c` r13 两处（RAM blob 预填 env `A7C_RAM_BLOB`；reset-hook 改 `qemu_system_shutdown_request(GUEST_SHUTDOWN)`）→ **bionz.c md5 `32dbbd76…`**（r12 版备份 `hw/arm/bionz.c.r12.bak`=139a86cb；基线 `.r11.bak`=87febf2b），**qemu-system-arm md5 `e3ae292c…`**（r12 版在 `arm-softmmu/qemu-system-arm.r12`）。
2. **RAM 预填**是我从文件灌的（真机由 EXBL 从 eMMC backup 区装填，且 RAM 副本头 64K 与文件不同≠脏读，见①）；`0x02e80000` 的 memrsv 是出厂参数，未改。
3. **内核差异**（`ksrc-r13` vs v3h）：Kconfig 去掉 `!CXD900X0_QEMU` 依赖强开 PCIE2_DME（config diff 仅 `+CONFIG_CXD900X0_PCIE2_DME=y`）+ system.h reboot hook；`vmlinux.bin` md5 `5ad80118…`。真机 updater 内核本就带 pcie（a1 命令行 `pcie.ch0_enable=Y` 佐证），但真机 pcie 是真硬件。
4. **合成卡**：`r13_card.img`/`BODYDATA.DAT` 的 FDAT 头是**猜的壳**（magic/偏移/尺寸字段自洽、签名区 256 B 全零）；写进 a10 是 loop-less stand-in（真机是 mmc_drv 的 SD host）。
5. initrd r13* 均在原生 initrd 上只加 echo/探针行（insmod 命令未改；mode5 版把 darwin 初始化后台化 20s kill）；`reboot`/探针都跑在 `/ramdsk`、`/dev/nflasha23`。
6. 基线**未动**：`a7c_emmc_pt4.img` md5 `8587674613…` 复验一致；实验写盘都在 `a7c_emmc_r13*.img` 拷贝上；Round 10–12 initrd/日志未改。

## ⑥ 产物与日志
- 本地 `work/qemu-a7c/results/round13/`（本文件 + 下表远端副本）；远端 `~/qemu-a7c/results_round13/`：
  `initrd_r13a/b/c/d/g.img`（72494113/203f6be6/6ac3d395/d3c67bb8/22ddef6b）、`r13_card.img` `ce716b69`、`BODYDATA.DAT` `4e6f45fa`、`r13_setup{1,2,3,4,6}.py`、`run_r13.sh`、`config_diff.txt`、`build_r13{,b}.log`、串口/退出日志：`r13_ctl_boot1`(对照 RC=5)、`r13_blob_boot1`(首证 RC=0/38)、`r13_blob4_boot1/2`(**C 闭环 + boot2 再 RC=0/38**)、`r13_m5_boot1/2`(**MODE=5 链**)。
- 实验镜像：`a7c_emmc_r13.img` `c84208c9…`（含 P1=a23 图案）、`a7c_emmc_r13_m5.img` `d526e5f0…`（mode5 旗+卡@176MiB）。
- 反汇编：远端 `/tmp/sdpa.asm`（libsdfileinputupdaterapi 全量）、`/tmp/sdelf.asm`、`/tmp/upc.asm`。

## ⑦ 仍需真机/真卡才能定
1. 真机 PA `0x02e80000` RAM blob 现场（camtool mem 读 ~64K 头 + `hdr+0x00`）：确认"RAM 副本 ≠ 文件、头 64K 是活的"这条 E2；以及真机 USER 模式不带 Backup_load 是否也吃 RAM（Round 12 的 H2）。
2. `nflashaB0/B1` + `USER 0x0–0x10000`（part 表/FixedArea 源头）。
3. **官方 SD 更新卡（或相机跑一次更新后的 BODYDATA.DAT）dump**：拿到真 FDAT 头 + 256 B 签名 ⇒ 才能做"官方 payload 验签通过"的正向离线验证；我们的私钥不在手（签名只能由 Sony 出）。
4. mode5 后半程（FDAT 扫描→SDDecryptor 解扰→execWriteFirm→写分区→MediaUpdateCompleteFlag→reboot）要 SD host 建模或真卡；QEMU 侧下一步是"最小 Sony SD host + DME 通道"或给 mmc_drv 造带后端的 /dev/mmca*。
5. a1 区回填（Round 10 P5）本轮未动。
