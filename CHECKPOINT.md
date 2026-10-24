# CHECKPOINT —— 暂停时的可续跑状态（2025-10-24）

## 0. 一分钟恢复上下文
读这四样就够续跑：`TEST_LADDER.md`（阶梯 + R 等级）、`notes/qemu.md`（§13–20 = 离线进展 + md5 基线）、
`notes/updater_verify.md`（FDAT 容器 / CRC / 验签结构）、`work/BACKUP_MANIFEST.tsv`（真机只读目标清单）。

> 文档落点提醒：`FIRMWARE_MOD.md`（522 行）里**没有** §9/§10；官方刷写流程叙述在 `notes/updater_flow.md`、
> 真机风险叙述在 `A7C_REAL_DEVICE_FEASIBILITY.md`。别再去 `FIRMWARE_MOD.md` 找 "10.1"。

## 1b. ★签名门最终判定（本轮 E1，最重要的新事实）
- **2.00 官方包来源：俄罗斯官网仍可下载** `https://www.sony.ru/electronics/support/e-mount-camera-ilce-series/ilce-7c/downloads`（curl 直连 403，用浏览器；下载后核对 `notes/updater_verify.md` 的 md5/sha256：dmg `9b4cff23…` / `.dat` `05862805…`）。官方 `.dat` 就在本机：`~/Downloads/Update_ILCE7CV200.dmg` → `.../Resources/FirmwareData_ILCE7CV200.dat`（346,206,712 B）；2.03 同构（363,197,944 B）。挂载：`hdiutil attach -readonly -nobrowse -mountpoint /tmp/ilce7c200 <dmg>`（macOS 没有 `timeout`，别用）。
- 容器 = **UFU**：`89 'UFU' 0d0a1a0a` + `[BE u32 size][TYPE]` 记录链（`DATV/PROV/UDID/FDAT/DEND`）；`DEND.payload` = BE `zlib.crc32(stream[0:n-12))` ⇒ 外层 CRC 可重算。
- ★`FDAT` 记录 payload 的**尾 256 B** = RSA-2048/PKCS#1v1.5+SHA256 签名，消息 = `FDAT payload[0:size-0x100]`（**密文体本身**，含 512 B 头 + 16 B IV）。用相机 a1 的 `/etc/VerificationKey.pem`：**2.00 OK★、2.03 OK★（同一把 key）**；翻 1 位必 FAIL。工具 `tools/sig_probe_fdat.py`。
- ⇒ **2.00 也有签名门**；`sauu` 与 mode5 的 `verify_info` 就是这个 FDAT 记录。**改 body（含相机侧门禁字段 `modeType/version/model/region`）需要 Sony 私钥**，或走 **Route A′（换 a1 里的 `sauu`）**。
- 签名外可改：`DATV/PROV/UDID` + 记录头（重算 CRC 即可）。`UDID` = USB **VID:PID 白名单**（21 条，含 `054c:0d29`=A7C；a15/a1 里 0 引用 ⇒ PC 侧更新器消费）。
- Round 14 的"正对照必须自签"**作废**：正对照直接用真 `.dat`。

## 1. 现在成立的关键事实（含出处）
- **分区表在 USER LBA 0**（USER 字节 0，共 512 B：magic ASCII `"8246"`、版本 `"1.00"`、`part_max≤30`、
  条目 @`+0x20` 每条 16 B `{start,size,type,flag(bit0=active)}`），与 `partinf.conf` 完全一致；
  **不在任何 `nflashaN` 分区里** ⇒ 必须用裸 `/dev/nflasha`（252:0）读。出处 `notes/qemu.md` §14–16。
- **`sauu`（USER/SERVICE 模式）无条件调用 RSA 验签**，覆盖**整个 body（减去尾 `0x100`）**，公钥 = initrd
  `/etc/VerificationKey.pem`（RSA-2048），失败 = `Signature Verification Error` + `ApiException 0x30002`。
  补丁点 = a1 initrd 里的 `sauu`：调用点 **`0x10b0e`**（`bl fcn.000104e0`）或判定点 **`0x1056c–0x1056e`**。
  出处 `work/sauu/SIG_RECHECK_200.md`、`notes/updater_verify.md`。
- **Backup 语义（两轮实验定死的）**：真机 `Backup.bin`（1,210,408 B，md5 前缀 `7a549d06`）的 **`hdr+0x00 = 0x02e80000`
  = RAM 物理地址**；updater **正常分支从 RAM 读**（`insmod backup.ko Backup_save=0`，不带 `Backup_load`），
  `Backup_load=1` 是"从文件读"的救援分支。出厂 a1 命令行 **`memrsv=0x75e000@0x02E68000` 已覆盖该区**。
  RAM 预填未改一字的真文件 ⇒ 原生命令行 `insmod` **RC=0、38 个 `Backup_*` 进 kallsyms、无 `file_load` 错**。
  出处 `notes/qemu.md` §19–20。
- **离线 R1 已成立**：QEMU 内经**闭源 AL_EMMC 驱动**写 `/dev/nflasha23` → guest 内 `reboot`（QEMU `shutdown_request`
  → wrapper 同镜像重拉）→ 重启后读回**同一 md5**；宿主侧确认落在镜像文件偏移 **`0x50C00000`**（= `0x400000` boot 前缀 + a23 起点）。
- **mode5（卡线）离线到头**：`mcmn_drv.ko`/`mmc_drv.ko` 都能 insmod（内核把 Kconfig `CXD900X0_PCIE2_DME` 的
  `!CXD900X0_QEMU` 依赖去掉重编），但 **QEMU 没有 CXD900x0 PCIe-DME + mcmn SD host 模型** ⇒
  `MMC:Failed mcmnd_api_getbkupinfo_bus_connect_type` ⇒ **`[FIRMUP NG] Error 77`**（**77 不在 `common.src` 错误表**；
  该串旁边是 `Force Local bus` ⇒ 卡槽总线类型来自 Backup/serial-cfg 信息）。
- **手里有官方未改的解密流**：`work/v203/full_dec_200.bin`（**344,853,504 B**，头 `UDTRFIRM`）= 2.00；`full_dec.bin`（361,778,688 B）= 2.03；`work/v203_head.bin`（4,180,980 B）。

## 2. 被中断的 Round 14（未完成，可直接重发）
- 盘上只有 `work/qemu-a7c/results/round14/loattach.c`（798 B），**没有 FINDINGS.md**；远端可能有 `~/qemu-a7c/results_round14/` 残留。
- 未做的目标（下次原样重发）：①用 `-d unimp` 抓 `mcmn_drv`/`mmc_drv` 访问的 MMIO 寄存器块 → 做**最小 host 桩**；
  ②让卡被枚举、能按块读；③卡上放**未改一字**的 `full_dec_200.bin`（按 `notes/updater_verify.md` 的 FDAT/`DEND`/尾 272 B 语义摆）→
  **正向：验签应通过**；④**负向：body 中段改 1 字节 ⇒ 必须 `Signature Verification Error` + `0x30002`**（这对对照是 Route A′ 门槛的决定性证据）；
  ⑤过了之后再让 updater 真写一个低价值分区 + guest 重启重读。
- 基线复验过未动：`a7c_emmc_pt4.img` md5 `85876746…`。

## 3. 相机一通就跑（只读批次，按序；无需新决策）
```
ssh wubin@172.22.22.131 'bash ~/a7c-jiritsu/bootarea_run.sh'    # = 本地 tools/bootarea_run.sh
```
1) `--preflight`（可取消）→ 2) **`nflashaB0/B1`**（= boot0/boot1，**EXBL 在这**；回答"ROM 是否验 a1"⇒ 决定 a1 补丁是 **R1 还是 R0**）
→ 3) 整块 `/dev/nflasha`（USER 区）的**头 64 KiB** + 当场解析真分区表 → 4) RAM `0x02e80000`（camtool `mem` 读，先 4 KiB 试探）
→ 5) `padtest`（写探针）→ 6) 一次 `zzprobe1` 写（只在明确 GO 后、`tools/wrapw.sh` 一次一发、不重试）。
注意事项：**相机默认 MassStorage 枚举 ⇒ `054c:0336` 不出现** ⇒ 跑任何 Jiritsu 前先 `--mode-poll`；每条命令前先 `mount`；
`camuser.sh` 在相机停 MSC 时会挂起（已加 `( exec 6<&- ) 2>/dev/null || true` 让远端命令能返回）。

## 4. 离线资产与 md5 基线（远端 `wubin@172.22.22.131`，sudo `zzz888ZZZ`）
- QEMU 二进制 `e3ae292c…`；`hw/arm/bionz.c` `32dbbd76…`（备份 `.r12.bak` = `139a86cb…`、`.r11.bak` = `87febf2b…`）；`hw/sd/sd.c` `e13776d0…`。
- 内核 `~/qemu-a7c/ksrc-r13/arch/arm/boot/vmlinux.bin` **`5ad80118…`**（gcc-6.4 Bootlin 2018.02 + `KCFLAGS=-fno-builtin-memset`；**别用 gcc-9**）。
- 镜像：基线 pt4 `85876746…`；Round 13 实验盘 `a7c_emmc_r13{,_m5}.img` = `c84208c9/d526e5f0`。
- 结果目录：远端 `~/qemu-a7c/results_round{10,11,12,13}/`；本地 `work/qemu-a7c/results/round{2..13}/`。

## 5. 只能靠真机补的东西（当前所有硬缺口的共同答案）
`nflashaB0/B1`（EXBL 是否验 a1）、USER `0x0–0x10000`（真分区表 / FixedArea）、RAM `0x02e80000` 活副本、
官方更新卡 `BODYDATA.DAT`（真 FDAT 头 + 尾 256 B 签名）、以及 **L2.6 真机 raw 节点写**验证（见 `TEST_LADDER.md`）。
