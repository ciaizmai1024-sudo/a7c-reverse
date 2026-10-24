# GitHub 调研：CXD90045 同代次（A7M3 / A7C / A7C II / ZV-E10 / ZV-1F）固件破解与改造

调研时间：2026-10-23（UTC）。未登录 API：`search` 约 37 次、`core` 14 次、`code_search` 4 次（全部 401，未登录不可用）、
`raw.githubusercontent.com` 约 12 次、`git clone --depth 1` 12 个仓库。本地已有 `refs/`（CXD90045-FPSU、Sony-PMCA-RE、fwtool.py、zve10-qemu、a7c2-fl23-research）不计入。

---

## 1. 一览表

| 仓库 / 链接 | star·最近推送 | 与 CXD90045 一代的关系 | 能直接拿到的东西 | 缺口 / 风险 |
|---|---|---|---|---|
| [ma1co/fwtool.py PR #52](https://github.com/ma1co/fwtool.py/pull/52)（DavidBuchanan314） | open，2026-10-22 仍在评论 | **直接命中**：`ILCE-7M3`(CXD90045, model `0x71030014`)、`ZV-1F`(CXD90045)；评论给出 **CXD90045 k0–k6, k8–k12** 与 CXD90057 13 把 FDAT AES-CBC 密钥 | `pull/52.diff`（devices.yml 条目 + `constants.py` 密钥 + `fdat.py` 多密钥 crypter 注册）；评论里 3ricj 的「机型×固件版本→密钥」矩阵 | **未合并进 master**（master 只有 `CXD90045` = k0）；无加密（打包）方向实现；A7R VI 密钥未知 |
| [ma1co/fwtool.py PR #53](https://github.com/ma1co/fwtool.py/pull/53) | open，2 commits | 作者自述 "Tested against `Update_ILCE7CV203.exe`" —— **正是我们机型的 2.03 更新器 EXE** | 纯 Python **LZX 解压**器 + 新版混淆 LZX CAB 解包路径 | 慢（~15 s）；未合并；不含打包/重签 |
| [ma1co/fwtool.py#51](https://github.com/ma1co/fwtool.py/issues/51) / [#54](https://github.com/ma1co/fwtool.py/issues/54) | open，2026-09 | 同厂（CXD90057，A7 IV）代次 | 根 shell、解密后的 eMMC 分区 dump 方法、SDM2 分区表、AXProtector 解包 | A7 IV（arm64）不是 A7C（armv7）；SDM2 ≠ 我们的私有分区表 |
| [DavidBuchanan314/ILCE-7M4-RE](https://github.com/DavidBuchanan314/ILCE-7M4-RE) | 2026-09～10 活跃 | 相邻代次（BIONZ XR），**方法论直接可用** | **真实二进制**：`bootrom/CXD90057_Mira_0xFFFF0000.bin`、`CXD90058_Cetus`、`emmc_boot/emmc_boot0.bin`、`esram_0xfe040000.bin`；bootROM 串口隐藏启动模式（`tools/uart_boot`）、裸机 `payloads/fastboot`（USB 备份/还原分区）、AES-XTS 密钥推导脚本 | 是 CXD90057 eMMC，非 CXD90045 NAND；「无验签」结论只对 A7 IV 成立 |
| [Gimmer268/lzpt-tools](https://github.com/Gimmer268/lzpt-tools) + [fwtool.py PR #55](https://github.com/ma1co/fwtool.py/pull/55) | 0★ / open，2026-09-26 | 我们 `firmware.tar` 里的 `TPZL` 成员就是同一容器 | **LZPT 编码器 + 原地 patcher**（`lzpt.py`、`lzpt_inplace.py`）、512 对齐不变量、WBI 不变量、砖机 UART 日志与 `nand.ko`(`mumin_lzp.c`) 反汇编位置、调试串口引脚表（`SERIAL.md`） | 只在 CXD90014（ILCE-7RM2/6300）上验证；作者明说「produce a container, not a flashable update package」 |
| [nolan2628/Sony-ZVE-10-Camtool](https://github.com/nolan2628/Sony-ZVE-10-Camtool) | 10★，2026-10-18 | **同芯片**：fwtool `devices.yml` 里 `ZV-E10: arch CXD90045`；armv7l、Linux 3.0.27_nl-rt106+（与 A7C 同内核） | 完整真机工具链：`cam.py`(40+ 子命令)、`jiritsu_lib.py`（Senser 双阶段认证）、`dump_flash.py`/`restore_flash.py`/`verify_dump.py`（**整分区读回写**）、**ARM32 `libJit.so` 载荷二进制 + `.s` 源**、分区表与容量、操作红线（`FIRMUP(0x4006)`/`FORMAT(0x4003)` 会挂死服务） | 1.5 GB 分区 dump 未发布（数据在 `../senser_probe/`）；未报告「改过的分区写回去并成功开机」 |
| [chocotan/a7c2-re](https://github.com/chocotan/a7c2-re) | 14★，2026-10-21 | 相邻代（A7C II，arm64）；**签名问题定位最深** | 整机 19 分区 / 1.80 GiB 转储方法（`pnflasha*` 密文视图 / `cnflasha*` 明文视图）；libJit root 执行（ILCE-7CM2 2.01 + ILME-FX30 实测 `Uid: 0 0 0 0`）；`2026-10-21-developer-modes/REPORT.md`（up.sh 各模式语义、preload 白名单、**验签函数地址**）；arm64 载荷 .so + 脚本 | 明确「不刷写固件、不改只读分区」；结论只针对 7CM2 2.01；A7C 是 armv7，载荷要重编 |
| [chocotan/a7c2-qemu](https://github.com/chocotan/a7c2-qemu) | 4★，2026-10-21 | 同代（A7C II）QEMU 路线，与 zve10-qemu 互补 | **公开的 QEMU 补丁**：`source/qemu-sony-native.patch`、`source/qemu-sony-usb.patch`（QEMU 11.1.2 基线）、`overwrite/` 覆盖固件文件的机制、`docs/tech/01..12` 排障笔记 | 用 `-machine virt -cpu cortex-a35`，不是 `bionz.c` 板级模型；只吃 7CM2 2.01 ALLLANG |
| [ma1co/qemu](https://github.com/ma1co/qemu)（fork，20★，最后推送 2021-06-19） | 公开 | **就是那个「qemu-sony」**：`hw/arm/bionz.c` 里有 `DEFINE_MACHINE("cxd90045", cxd90045_machine_init)`，`VERSION` = 5.1.0 | 一次 `raw.githubusercontent` 即可取 `hw/arm/bionz.c`（47 KB，含 CXD90045 全部寄存器/外设定义） | 2021 年快照，`boot_size=0x40000`、DDR 尺寸与真机不符 → 必须叠 zve10-qemu 的 `patches/qemu/bionz.patch`(259 行)/`sd-cid.patch`(133 行)/`qemu-cxd90045-vip-display.patch`(301 行)（本地已有） |
| [QAQLeonard/a7c2-fl23-research issue #23](https://github.com/QAQLeonard/a7c2-fl23-research/issues/23) | 350★ 仓库，issue 2026-10-22 | **正中 ILCE-7C 2.03**（作者 hnws） | 长文实测：`054c:0d29`→`054c:0336`、Senser 三轮认证、`dlopen("/tmp/jiritsu/libJit.so")` root、`/tmp/jiritsu` 不存在的绕法（`set_file2` mode 1 + `sys_dir_create2`）、A7C 分区挂载表、av-cam 物理加载（`libOnDemandLoader.so` + `/dev/mem` mmap）与对象偏移 | **代码没放出来**（本地 `a7c1-port/`）；卡在 av-cam 物理基址；0 回复 |
| [YuuLuo/a7c2-service-preload](https://github.com/YuuLuo/a7c2-service-preload) | 79★，2026-10-15 | 相邻代（7CM2 2.01） | 从 USB 服务会话到 root 一次性代码执行的完整链路文档（含 `PROTOCOL.md`：控制请求、帧结构、摘要输入、两种模式序列） | 只有文档 + 结论，无完整工具；preload 入口有砖机风险（作者已踩） |
| [YuuLuo/a7c2-camera-tools](https://github.com/YuuLuo/a7c2-camera-tools) | 31★，2026-10-19 | 相邻代 | 跨平台（mac/win）A7C II 2.00/2.01 只读服务工具、`p1_gate_*`、feature/sound/fl23 包 | 只针对 7CM2；不含固件写路径 |
| [Himpq/FireHydrant](https://github.com/Himpq/FireHydrant)（A6700）+ [其 issue #1](https://github.com/Himpq/FireHydrant/issues/1) | 新，2026-10 | 相邻代（A6700 / FX30 对比） | `DEVICE_CHANNEL.md`：`libJit.so` 加载入口、`/proc/self/maps` 基址定位与偏移换算；issue #1 记录 **FX30 上 FileControl/MemoryDump 返回 128** | 纯文字，「不包含固件二进制、补丁数据与可执行脚本」 |
| [t2r05/fx30-senser-map](https://github.com/t2r05/fx30-senser-map) | 0★，2026-10-21 | 相邻代（ILME-FX30 6.00） | 服务模式通道边界：只有 2 个 pFunc 可达（`0x10` ProductInfo / `0x40` AdjustControl），文件/内存通道不响应 | 与 A6700 差异说明**通道能力按机型裁剪**，不能假定 A7C 与 7CM2 一致 |
| [ma1co/Sony-PMCA-RE](https://github.com/ma1co/Sony-PMCA-RE)（master, 2022-08-18） + issues #745/#748/#294 | 高 | 我们已 clone；issue 侧新证据 | `updatershell/` 有**载荷源码**（`updaterbody.cpp`、`pack.py`、`Makefile`）与 `fdat/*.dat` 载荷：CXD4105/4115/4120/4132/**CXD90014**（含 ILCE-7M2/7RM2/7SM2/6300/6500） | **载荷不含 CXD90045** → 更新器 ramdisk 载荷这一代没人做过；master 停更，`updatershell`/`tweak` 靠 service mode |
| [masterflai/pmca-re-reloaded](https://github.com/masterflai/pmca-re-reloaded) | 7★，2026-10-21（活跃） | 通用（含新代次 service shell） | Rust 重写版 PMCA-RE（桌面 app、备份/usage log/固件校验与安装、updater shell）；在 PMCA-RE [#747](https://github.com/ma1co/Sony-PMCA-RE/issues/747) 自荐 | 自述「Flashing official firmware is ported but has not yet been tried on a camera」 |
| [ma1co/OpenMemories-Tweak](https://github.com/ma1co/OpenMemories-Tweak) / [OpenMemories-Framework `docs/Cameras.md`](https://github.com/ma1co/OpenMemories-Framework/blob/master/docs/Cameras.md) | — | 「第三条路」问题 | app 方式（telnet/adb/去 30 分钟限制/语言） | **PMCA 应用列表最晚只到 A7M2/A7RM2/A7SM2（2015）**，没有 A7M3 / A7C / A7C II → app 路线在这一代**不存在** |
| [BI2QFA/a6300_updater_emu](https://github.com/BI2QFA/a6300_updater_emu) | 1★，2026-08 | CXD90014 的「更新器固件 QEMU」 | 仓库里直接放**从 α6300 转储并改过的内核 + 文件系统镜像**（`firmware/`，5.7 MB）+ Windows 版 `qemu-system-arm.exe`（用 ma1co/qemu 编的）+ `run.py` | 只有 CXD90014；是别人转储的镜像，不是 CXD90045 |
| [oxunjonuz/aiodam-sony-a7siii-firmware-audit](https://github.com/oxunjonuz/aiodam-sony-a7siii-firmware-audit) | 新，2026-10-04 | 相邻代（A7S III，用 PR#52 的密钥解密） | 一个 `BODYDATA.DAT` 的静态审计（含 Zenodo DOI）、SSH 私钥发现 | 作者自认静态only：「Signature enforcement … remain outside what the file alone proves」 |
| 同代 FL2/FL3 生态：[MDHan/a7c2-fl23-macos](https://github.com/MDHan/a7c2-fl23-macos) 40★、[lzh2016zzz/a7cr-fl23-research](https://github.com/lzh2016zzz/a7cr-fl23-research) 18★、[nimrc/sony-a7c2-fl23-linux](https://github.com/nimrc/sony-a7c2-fl23-linux) 3★、[ChambersXDU/sony-a7c2-research](https://github.com/ChambersXDU/sony-a7c2-research) 10★、[jpaulrez/sony-a7c2-hacks](https://github.com/jpaulrez/sony-a7c2-hacks) 4★ | — | 只做 A7C II/7CR 功能解锁（写设置/Backup，不刷分区） | 7CM2 写偏移、LiME/Volatility3 内存取证、`fwtool/sony/{fdat,dat,flash}.py` 副本 | 与「刷分区」无关；`fdat.py` 里 FDAT 头只有 32-bit `checksum`，**没有尾部签名建模** |

---

## 2. 四个问题的回答

### Q1 — 有没有人已经改过同代次固件并成功上机？

**答：代码执行（root）已经在 ILCE-7C 2.03 上打通，但「改固件 + 写回 + 正常开机」在任何 2018+ 机型上都没有公开的成功案例。** 最接近的成功是 ZV-E10（同为 CXD90045）的整分区读回写，以及 A7 IV（CXD90057）的 fastboot 分区刷写。

1. **ILCE-7C 一代本体已有 root 代码执行** —— https://github.com/QAQLeonard/a7c2-fl23-research/issues/23（hnws，2026-10-22）
   > "On the first-generation A7C (ILCE-7C, firmware 2.03) the Senser authentication, `054c:0336` service session and the Jiritsu `dlopen("/tmp/jiritsu/libJit.so")` root primitive all work."
   > 中文：A7C 2.03 上认证、服务会话、Jiritsu `dlopen` root 原语全部实测可用；载荷必须是 **ARM32 EABI**（`e_flags` 改成 `0x5000002`）。
   **【已证】**（作者报告 `euid : 0`、pid 162 = `im.elf`），但代码在其本地 `a7c1-port/`，未发布，且明确「只读固件、只写 `/tmp/jiritsu`」。
2. **同芯片 ZV-E10 的整分区写回工具已存在，但没人写过改过的分区** —— https://github.com/nolan2628/Sony-ZVE-10-Camtool
   > "this writes raw block bytes; the wrong partition means a brick." / "Until you have a working bootROM recovery, do not touch `nflasha3` (/system, contains av-cam.bin)."
   > 中文：raw block 写回可用（`restore_flash.py --confirm`），但作者红线是别碰 `/system`，且 **`FIRMUP(0x4006)` / `FORMAT(0x4003)` 会让服务挂死** —— 服务模式里的「 updater 刷写」通道在这一代不可用。
   **【已证】**（读写路径与分区表已验证；「改过的分区」未上机）。
3. **相邻代 A7C II / FX30 用 libJit 拿到 root，但刻意不刷固件** —— https://github.com/chocotan/a7c2-re
   > "改用固件自身对 `/tmp/jiritsu/libJit.so` 的 `dlopen` 取得 root 命令执行…已在 **ILCE-7CM2 2.01** 与 **ILME-FX30** 上验证 `Uid: 0 0 0 0`"；README 顶部："真机工具不修改只读分区、不刷写固件"。
   **【已证】**（两台真机）。
4. **A7 IV（CXD90057）已经做到「刷分区」级别** —— https://github.com/DavidBuchanan314/ILCE-7M4-RE
   > "You can reach the serial bootloader by blasting the right bits down the RX pin of the accessory connector… a bare-metal fastboot-compatible boot payload, which can be used to back up and restore eMMC partitions over USB."
   > 中文：bootROM 有隐藏串口启动模式，裸机 fastboot 载荷可透传加解密地备份/还原分区。
   **【已证】**（有 `images/pwned.jpg`、发布的 bootrom/emmc_boot 二进制），但机型不是 CXD90045。
5. **改过 `.dat`/容器并重打包 → 砖** —— https://github.com/ma1co/fwtool.py/pull/55（Gimmer268）
   > "I repacked an ILCE-7RM2 image, the updater reported `Done`, and the camera never booted again… `/system` (`nflasha3`) becomes unreadable before `init` gets anywhere, so the camera does not enumerate over USB at all - flashing is not enough to recover it, the flash chip has to be read/written directly."（UART 日志 + `kmod/nand.ko`/`mumin_lzp.c` 的 `0x1FF` 位测试）
   > 中文：重打包 LZPT 容器时块偏移/长度必须 512 对齐，否则刷进去报 Done 但起不来，只能夹 flash 救。
   **【已证】**（CXD90014 一代；容器格式与我们 `firmware.tar` 里的 `TPZL` 相同）。
6. **A7C 上用官方更新通道塞自制包会直接被拒** —— https://github.com/ma1co/Sony-PMCA-RE/issues/745（danilomozer，ILCE-7C 2.03）
   > "Updater mode fails with 'Firmware update error: Invalid model' (expected, signed firmware)."
   **【已证】**（用户实测；只说明机型/区域校验先报错）。
7. **「不刷分区也能拿到代码执行」的第三条路 = service mode（Backup 区 tweak），不是 app**：
   - PMCA-RE ma1co 本人：https://github.com/ma1co/Sony-PMCA-RE/issues/294 → "In the latest development build, tweaks should now be supported for this camera, too. You can use `pmca-console serviceshell`"（ILCE-7C）。**【已证】**
   - 2026-10 复现：https://github.com/ma1co/Sony-PMCA-RE/issues/748 → "Successfully unlocked the language options on a mainland China Sony A7C (ILCE-7C), firmware 2.03… After the tweak, it showed 35/35 languages"（Apple Silicon macOS，`-d libusb`）。**【已证】**
   - **app 路线（OpenMemories: Tweak）在这一代没有**：`OpenMemories-Framework/docs/Cameras.md` 的 PMCA 支持列表里最后的全画幅机型是 A7M2(2014) / A7RM2 / A7SM2(2015)，**没有 A7M3、A7C、A7C II**（`grep '| A7'` 命中里无 7M3/7C）。**【已证（缺失）】**

### Q2 — FDAT 尾部 256 B（疑似 RSA-2048）有没有人给出绕过 / 定位结论？

**答：没有 CXD90045 的正面结论；但相邻代（A7C II / A7 IV）已把「验签发生在哪里、以及刷分区层面根本不验签」讲清楚。**

1. **验签在更新器内部，函数已定位（A7C II 2.01，代码证实）** —— https://github.com/chocotan/a7c2-re/blob/main/report/2026-10-21-developer-modes/REPORT.md
   > "三种模式共用写入路径 `UFPDecryptorModule::exec_write_firm@0x12f50`，解密前先 `VerifySignature`，`RSA_verify()==1` 失败抛 `0x30002`。**没有任何 updater 模式接受自制包。**"
   > 证据锚点：`libupdaterufp.so`/`sauu`/`libupdaterapi.so`：模式选择、签名验证 `exec_write_firm@0x12f50`/`0x1361c`；**"与 nflasha1 `boot/initrd.img` 内 updater 比对一致"**。
   > 中文：验签在 nflasha1 的 updater ramdisk 里（RSA_verify），up.sh 的 user/serv/ver 三种模式都不绕过。
   **【已证（代码级，7CM2 2.01）】**
2. **flash 层面「没有验签」的正面说法（A7 IV）** —— ILCE-7M4-RE README Fun Facts
   > "The eMMC partitions are encrypted with AES-XTS, but **there is no signature verification**."
   > 中文：分区只有加密、没有签名校验 → 走 bootROM/裸机载荷直接写分区就不需要过 FDAT 尾签名。
   **【已证（A7 IV / CXD90057）】**，对 CXD90045 是**类比推测**。
3. **preload 路线作者的措辞暗示更新流程存在可临时打开的「门」** —— https://github.com/YuuLuo/a7c2-service-preload
   > "Installing a modified firmware image also needs an update acceptance path; preload execution does not permanently disable signature checks. **The investigated update workflow restored its temporary gate afterward.**"
   > 中文：更新工作流里确实存在一个「临时门」，只是他们用完就还原了，没写门在哪。
   **【仅声称】**（没给地址/字段）。
4. **公开工具都没有建模尾部签名**：fwtool `fwtool/sony/fdat.py` 的 `FdatHeader` 只有 `('checksum', Struct.INT32)`（ChambersXDU 的 `fwtool/sony/fdat.py` 副本同样），`AesCbcCrypter.encrypt()` 直接 `raise Exception('Encryption not supported')`（fwtool master 第 211 行）。**【已证】**
5. **「改 initrd 再改 p1chksum 的 md5 换进 nflasha1」这个问题在公开渠道无人回答** —— https://github.com/ma1co/fwtool.py/issues/50（2025-06-11，**0 comments**）
   > "Now that I have modified and repackaged initrd, I would like to directly replace it into /dev/nflasha1. Is this method feasible?"
   **【仅提问，无结论】**

### Q3 — `qemu-sony`（含 `bionz.c` / `-M cxd90045`）源码有没有公开可得的地方？

**答：有。它就是 `ma1co/qemu`（公开 fork），QEMU 5.1.0，含完整 CXD90045 机器模型；我们只需要叠上已在本地 `refs/zve10-qemu/patches/qemu/` 的补丁。**

- https://github.com/ma1co/qemu —— "QEMU for Sony BIONZ image processors"，fork、**20 star**、最后推送 **2021-06-19**、`VERSION` = `5.1.0`。
  直接可取：`https://raw.githubusercontent.com/ma1co/qemu/master/hw/arm/bionz.c`（47 408 B），内含
  `DEFINE_MACHINE("cxd90045", cxd90045_machine_init)`（`mc->desc = "Sony BIONZ CXD90045"`，`cortex-a5`）、`cxd90045_init`、`CXD90045_DDR0_SIZE 0x40000000`、`CXD90045_SRAM_BASE 0xfe000000`、`CXD90045_BOOTCON_BASE 0xfe005030`、`CXD90045_SDHCI_BASE 0xf0304000`。 **【已证】**
- 差异（公开快照 vs 真机）：公开版 `qdev_prop_set_uint32(dev, "boot_size", 0x40000)`（256 KB）、DDR0/DDR1 = 1G/1G；zve10-qemu 记录真机应为 `0x200000`（2 MB）与 `1G + 256M` + WBI 段装载 → 见本地 `refs/zve10-qemu/docs/QEMU_BOOT_PROGRESS.md` §176「`cxd90045` 机器模型的 4 处修补」与 `patches/qemu/bionz.patch`(259 行)、`patches/qemu/sd-cid.patch`(133 行)、`patches/qemu-cxd90045-vip-display.patch`(301 行)。
- 另一条**完全公开、更新的 QEMU 路线**：chocotan/a7c2-qemu（QEMU 11.1.2 + 自带 `source/qemu-sony-native.patch`、`source/qemu-sony-usb.patch`、`source/manifest.json` 逐文件 before/after），用 `-machine virt -cpu cortex-a35`（A7C II 是 arm64）。它的 `docs/tech/README.md` 第 111 行："**机器**：`-machine virt,secure=off -cpu cortex-a35 -smp 1`"。 **【已证】**
- 附带：`BI2QFA/a6300_updater_emu` 里带着 **ma1co/qemu 编出来的 Windows `qemu-system-arm.exe`**（62 MB）+ 转储的内核/文件系统，可作为「拿不到编译环境时」的参照。

### Q4 — 有没有人分享过这一代的 `nflasha1`（更新器 ramdisk，含 `mf`/`UdtrMain.sh`）或 `libJit.so` / `tmmc.jit` 的 dump？

**答：没有公开的 CXD90045 一代 `nflasha1` / updater ramdisk dump。公开的只有：载荷侧（我们写进去的 `libJit.so`）二进制、以及 CXD90014 一代的更新器镜像。**

空结果证据（见 §4 表格）：`search/repositories?q=nflasha` → **0**；`nflasha1` → **0**（issues 7 条，全是索取）；`UdtrMain` → **0**；`tmmc.jit` → **0**；`udtrbody` → **0**（repos）；`p1chksum` → **0**。
命中的 7 条 `nflasha1` issue 里只有索取/提问：fwtool #44（"Looking for Sony A7RII capera with original firmware version 1.00 to dump for the community"）、#50（改 initrd 换进 nflasha1，无人回复）、PMCA-RE #488/#683/#255（砖机求助）。

**能拿到的替代品（已证，都在仓库里）：**

| 想要 | 公开最近似物 | 出处 |
|---|---|---|
| `libJit.so` 载荷（ARM32，可直接给 A7C 用） | `payload/libJit_exec.so`、`libJit_arm_ok.so`、`libJit_boot_hook.so` + `jit_*.s` 源 + `build_payload_v2.py`（「★ the only correct payload builder」），规则「Write `libJit.so` with `write(16)`；其它用 `0xff01`」 | https://github.com/nolan2628/Sony-ZVE-10-Camtool/tree/main/payload |
| `libJit.so` 载荷（arm64，7CM2/FX30 用） | `report/2026-10-18-libjit-exec/` 的 `payload/*.arm64.so` + 源码 + SHA-256 | chocotan/a7c2-re |
| 更新器 ramdisk 镜像（老一代） | `firmware/`（5.7 MB，「从 α6300 转储并经过修改的内核、文件系统镜像」）+ `run.py` | https://github.com/BI2QFA/a6300_updater_emu |
| 更新器侧载荷的源码与打包脚本（老一代） | `updatershell/{updaterbody.cpp,process.c,mount.c,pack.py,Makefile}` + `updatershell/fdat/*.dat`（CXD4105/4115/4120/4132/**CXD90014**，无 CXD90045） | 本地 `refs/Sony-PMCA-RE/updatershell`（628 KB） |
| nflasha1 的身份记录（没给镜像但给 SHA） | chocotan dev report：「nflasha1/nflasha2 以 `ro,loop,nosuid,nodev,noexec` 挂载读取后卸载，前后 SHA-256 一致：nflasha1 `0937e8cc…948d7c`，nflasha2 `5f73837a…739a7254`」 | chocotan/a7c2-re |
| ZV-E10（CXD90045）分区表实测 | nflasha1 7.9 MB FAT12 unmounted / nflasha2 20 MB /setting / nflasha3 48 MB **/system(含 av-cam.bin)** / nflasha6 16 MB /tmp/jiritsu / nflasha15 300 MB /usr / nflasha16 140 MB 全零可当 scratch | Sony-ZVE-10-Camtool README §7 |
| 真机 dump 分享 | **各家一致不放二进制**：Sony-ZVE-10-Camtool「contains no firmware and no device data」；FireHydrant「不包含固件二进制」；a7c2-re 只放载荷 .so | — |

---

## 3. 值得 clone / 下载的具体目标（按价值排序）

1. **`https://github.com/ma1co/fwtool.py/pull/52.diff`**（已存 `/tmp/pr52.diff`）—— 取 `fwtool/sony/constants.py`（`key_cxd90045_k0 = C1AA8F7C…`、`key_cxd90045_k8 = 782FD979…`）+ `devices.yml` 的 `ILCE-7M3: CXD90045 / 0x71030014`、`ZV-1F`。为什么：我们 `config.yaml` 的 `crypterName: CXD90045` 只有 k0；若 A7C 2.03 换密钥索引，PR 评论（2026-10-09）给的 CXD90045 `k0–k6, k8–k12` 全表 + 3ricj 的「机型×版本→密钥」矩阵可直接暴力试。取法：`curl -L https://github.com/ma1co/fwtool.py/pull/52.diff`；全密钥见 issue 评论 `.../issues/52#issuecomment-*`。
2. **`git clone --depth 1 https://github.com/DavidBuchanan314/ILCE-7M4-RE`** —— 取 `bootrom/CXD90057_Mira_0xFFFF0000.bin`、`bootrom/CXD90058_Cetus_0xFFFF0000.bin`、`emmc_boot/{emmc_boot0.bin,esram_0xfe040000.bin}`、`scripts/parse_emmc_partitions.py`（从 bootrom 的 `0xb800:0xbc00` scramble pad + loader `0x239b0` offset table 推导 AES-XTS 密钥）、`tools/uart_boot*`、`payloads/fastboot/`。为什么：这是唯一公开「写分区不需要验签 + bootROM 启动模式」的完整证据链，方法可移植到 A7C（NAND/私有分区表要重做，但验签结论方向一致）。
3. **`git clone --depth 1 https://github.com/Gimmer268/lzpt-tools`** —— 取 `lzpt.py`（**LZPT/TPZL 编码器**，`pack --ref` 保留 header `0x10..0x17`、每块 pad 到 512）、`lzpt_inplace.py`（`scan/probe/patch`：只挑 ≥N 字节、纯 literal、且不被后续 match 引用的位置做原地改）、`INVARIANTS.md`、`SERIAL.md`（砖机那台 7RM2 的调试串口引脚表）。为什么：我们改 `firmware.tar` 里的 `nflasha3/7/15` 时，公开工具只会解码；这是第一个能编回去并且带 512 对齐断言的实现。
4. **`git clone --depth 1 https://github.com/nolan2628/Sony-ZVE-10-Camtool`** —— 取 `jiritsu_lib.py`（0x0E8A→0x0D95→0x0336 两阶段认证 + SHA1/512B key table）、`dump_flash.py`/`restore_flash.py`/`verify_dump.py`、`build_payload_v2.py`、`payload/*.so` + `payload/*.s`、README §5「Non-negotiable rules」+ §7 分区表。为什么：ZV-E10 在 fwtool `devices.yml` 里就是 `arch: CXD90045`，与 A7C 同内核 `3.0.27_nl-rt106+`/armv7l；这套是我们「整分区备份→本地改→整分区写回」的现成骨架，还带着 `FIRMUP/FORMAT` 会挂死的实测红线。
5. **`chocotan/a7c2-re`** —— 取 `report/2026-10-21-developer-modes/REPORT.md`（up.sh user/serv/ver/ms/file/modver/modmod/modreg 语义表、preload 4 路径白名单 `bootin.elf@0x403f08`、`/setting/mode/dmode`、gdbserver 死路径 `0x401ae0`、验签地址）、`report/2026-10-16-system-dump/`（`pnflasha`/`cnflasha` 双视图 dump 方法 + `scripts/jiritsu_*.py`）、`report/2026-10-18-libjit-exec/`（arm64 载荷）。为什么：签名/工程模式/preload 语义是公开材料里最系统的，虽然机型是 7CM2。
6. **`https://raw.githubusercontent.com/ma1co/qemu/master/hw/arm/bionz.c`** —— 一次 raw 取 47 KB；与本地 `refs/zve10-qemu/patches/qemu/*.patch` 对照即可重建 `cxd90045` 模型。别整仓 clone（280 MB）。
7. **`git clone --depth 1 https://github.com/chocotan/a7c2-qemu`** —— 取 `source/qemu-sony-native.patch`、`source/qemu-sony-usb.patch`、`docs/tech/{01-firmware-assets,02-qemu-boot,03-guest-environment,07-storage,08-settings}.md`、`start.sh` 的 `overwrite/`（换 `usr/lib/appFw.so` 的现成机制）。为什么：这是**公开的新版 QEMU 补丁**，若放弃 `bionz.c` 走 generic virt + 覆盖文件，可省掉大量模型工作（代价：arm64 假设要改成 armv7）。
8. **`git clone --depth 1 https://github.com/BI2QFA/a6300_updater_emu`** —— 取 `firmware/`（α6300 转储并改过的更新器内核 + fs）与 `run.py`。为什么：「更新器 ramdisk 在 QEMU 里跑」这件事在老一代已经跑通，可作对照实现（CXD90014，非 CXD90045）。
9. **`git clone --depth 1 https://github.com/ma1co/qemu`** 只在需要编译期上下文时做（20 star、2021 快照）。
10. **跟踪/去问的两处**（无二进制可下载）：QAQLeonard/a7c2-fl23-research **issue #23**（请作者发布 `a7c1-port/`，含 A7C 2.03 的 `probe/ps/cat/sh/memscan/addr` 载荷）；PMCA-RE **issue #747** → `masterflai/pmca-re-reloaded`（Rust 重写版，`clone --depth 1` 取 service shell / updater shell 实现）。

---

## 4. 搜索范围与空结果证据（避免假阴性）

`search/repositories`（`q=` 未加 `in:` 修饰，即默认 name/description/readme）：

| query | total_count | 与 CXD90045 相关的命中 |
|---|---|---|
| `CXD90045` | 1 | 只有 Lost-week-1025/CXD90045-FPSU（本地已有） |
| `CXD90046` | 0（repos）；3（issues，全是 PS4/PS5 无关） | 无 |
| `nflasha` | **0** | 无 |
| `nflasha1` | **0**（repos）；7（issues，全为索取/提问） | 无 |
| `libJit.so` | **0**（repos）；7（issues） | issue #23（A7C 1st gen）、FireHydrant#1 |
| `udtrbody` | **0**（repos 与 issues） | 无 |
| `UdtrMain` | **0** | 无 |
| `p1chksum` | **0**（repos）；1（issue = fwtool#50，无人回答） | 无 |
| `tmmc.jit` | **0** | 无 |
| `FDAT` + `signature` | 140（issues，噪音极大） | 无相关命中 |
| `UDTRFIRM` | **0** | 无 |
| `av-cam.bin` | **0**（repos） | 无 |
| `jiritsu` | 45 | a7c2-service-preload、Sony-ZVE-10-Camtool 有效 |
| `updatershell` | 1 | CliffVale/sony-a6000-firmware-research（A6000，CXD4132/90014 代） |
| `SystemSoftwareUpdater` | **0** | 无 |
| `ILCE-7C` | **0**（repos） | 只有 PMCA-RE issues 命中 |
| `ILCE-7M3` | 2 | 全是配件（GPS/SDK），无固件破解 |
| `ILCE-7CM2` | 7 | 全部是 A7C II FL2/FL3 与逆向 |
| `A7C firmware` | 7 | 同上代生态 |
| `A7C hack` | 4 | jpaulrez/sony-a7c2-hacks（只是 CAMSET*.DAT 设置文件） |
| `Sony firmware patch` | 13 | cokeenet/zve10-qemu 有效，其余是 SE 手机/Walkman |
| `qemu-sony` | 2 | ma1co/OpenMemories-CI、cokeenet/zve10-qemu |
| `bionz` | 7 | BI2QFA/a6300_updater_emu 有效 |
| `fl23` | 61 | A7C II 生态（QAQLeonard 350★ 等） |
| `sony camera qemu` | 1 | OpenMemories-CI |
| `sony firmware dump` | 7 | CliffVale/sony-a6000-firmware-research |
| `a7iii firmware` | 1 | 无关（SDK） |
| `user:ma1co` / `user:DavidBuchanan314` / `user:Gimmer268` | 1411 / 125 / 1 | Gimmer268 只有 lzpt-tools |

`search/issues`（同一 search 配额）：`repo:ma1co/Sony-PMCA-RE updatershell`(68)、`repo:ma1co/Sony-PMCA-RE a7c`(27)、`repo:ma1co/Sony-PMCA-RE "a7 iii"`(8)、`repo:ma1co/Sony-PMCA-RE serviceshell ILCE-7C`(6)、`FDAT signature`(140)、`libJit.so`(7)、`nflasha1`(7)、`tmmc.jit`(0)、`CXD90046`(3)。
**`search/code` 未登录返回 401（4 次尝试：`nflasha`、`udtrbody`、`p1chksum`、`appFw.so`）→ 代码级全文检索没跑成**，改用「clone 候选仓库 + 本地 grep」代替（12 个仓库，grep 关键词 `nflasha|udtrbody|libJit|p1chksum|appFw|FDAT|bionz.c|cxd90045|jiritsu|tmmc.jit`）。

**配额**：`core` 用 14 / 60（剩 46），`search` 约 37 次（每分钟 10 上限，分批 sleep 8）。

## 5. 对本项目最有用的三条可执行结论

1. **先做「不改 FDAT 尾」的路径**：service-mode 整分区读回写（ZV-E10 已有骨架）+ in-place LZPT patch（lzpt-tools），保持块表与总大小不变 → 不触发 fwtool#55 那类砖，也不需要自制签名包。
2. **验签在 nflasha1 的 updater ramdisk 里**（`UFPDecryptorModule::exec_write_firm` → `VerifySignature`/`RSA_verify`，失败 `0x30002`）→ 我们缺的 `nflasha1`/`initrd` 是**验签研究的关键缺口**，比拿 `av-cam.bin` 更优先；拿法是 A7C 上 root 后直接 `dd /dev/nflasha1`（`/dev/nflasha*` 在这一代可读写，见 chocotan 的密文/明文双视图与 camtool 的 dump）。
3. **A7C 一代已有公开可达的 root 原语**（issue #23），把 `Sony-ZVE-10-Camtool/payload` 的 ARM32 载荷 + `jiritsu_lib.py` 移植过来即可复现，不必等 a7c1-port 发布。
