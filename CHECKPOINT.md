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

## 4b. 网络/调试通道实况（E3，见 `notes/netstack.md`）
- Wi-Fi 真脚本在 **`/usr/wifi-scripts/`**（`network.sh` 等只是 `libIMDB.so` 的串）；只有一个 `bcmdhd.ko`（OOB 由 `dhd_irq=144` 决定）；固件 `/usr/wlan/bcm/`、nvram `/usr/share/network/nvram/*/bcm4339_*.txt`；`bss.conf` 是 **`ap_scan=0`**。
- busybox v1.29.3（191 applet，a15 没有 busybox，借 a7 的）：**`nc/telnetd/httpd/crond/ip` ✗**；**`udhcpc/tc/logger/switch_root/ftpd/ftpget/ntpd/ssl_client` ✓** ⇒ 传大文件走 FTP。
- **无 ssh 服务端**；客户端只有库 `libssh2.so.1.0.1`（无 CLI）；OpenSSL 2.00=1.1.1a、2.03=3.0.2；**2.03 有 `curl 4.8.0`，2.00 没有**（2.00 有 `iw/top`）。
- **`ulogio` = 自带内核级控制台**：`telnet up|down`（**端口 23 写死**，需重启）；子命令含 `db/dw/dl`、`mb/mw/ml/mf/mu`、`lsnap/lstart/lstop`、`crash/timetag/uipc`。
- 要做交互 shell：我们的 ARM32 worker 里 `socket()+connect()+dup2` ⇒ 笔记本 `nc -l` 反向 shell（零新二进制），或带一个静态 ARM32 dropbear。

## 4c. ★真机现在最该读的一处 RAM（Round 17 新增，优先级最高）
读真机 **`0x02e80000` 的 Backup RAM blob**（长度取 `Backup.bin` 的 1,210,408 B），与我们手上 `a2:/Backup.bin`（md5 `7a549d06…`）逐字节比对。
Round 17 抓到 `verifyKey` 的比对是 `SHA1(整只 /etc/VerificationKey.pem 含尾换行)` vs **Backup 里按 BackupID 取的 20 字节指纹**，而我们镜像里那个条目是**全零（出厂未写）**。
⇒ 若真机 RAM blob 也是零 ⇒ 真机走 mode5 也会卡 `verifyKey`（那官方 SD 更新必有别的入口写这个条目）；
⇒ 若真机 blob ≠ a2 文件（BodyLoader 运行时补写）⇒ 我们的 Route A″ 要改的是**运行时 blob**（或让 BodyLoader 那份对上）。
顺带把 `nflashaB0/B1`（EXBL）与 USER 头/分区表一起读。

## 4d. 官方包侧的"可写清单"与风险判定（E3，见 `notes/official_package.md`）
- **一次官方更新会写：`a15 + a3 + a5 + a7`（2.03 还写 `a1`）+ Backup 里被 `MainDest.txt` 选中的那一份 blob + `0800_appli` 若干文件 + `partinf.conf/darwin/prfile/config`**；**不写** `a2/a4/a6/a10 本体/a13/a23`。⇒ 半刷风险面里多了一个之前没想到的：**`a5 = Warm Boot Image` 不同步**（warm-boot 会恢复旧状态）。
- **`a4` 开头是 `CMMeX` 结构 ⇒ a4 不是 a1 的镜像副本** ⇒ "刷坏 a1 有 a4 兜底"**不成立** ⇒ **刷 a1 仍是 R0**；先拿 `a10`（/tmp，可弃）做 L2.6。
- ⇒ **L2.6 的定位升级：从"自救工具"变成"信任根 bootstrap"**——先 raw 写改过的 a1（绕过签名门），之后自制签名包才能接管 a15/a3/a5/a7（因为 `RSA_verify` 用的就是已装的那把 PEM，换 PEM 又需要刷 a1 ⇒ 鸡生蛋只能靠 raw 写破）。
- **包内 `partinf.conf`：名字/大小可信（`a15`=usr 300MB、`a3`=Main 48MB、`a5`=Warm Boot 60MB、`a6`=Jiritsu、`a4`=MPR Flash Backup），地址不可信**（它给 `a15@0x2D800000`、`a11=Log@0x0B800000`；机身 USER 表为准）。
- **机身 `/setting/Backup.bin` 与包内 26 份标准 Backup 都差 9 万多字节（2203 个 run）** ⇒ Backup 里有大量设备专属内容（序列号/校准/锁）⇒ **任何"整份覆盖 Backup"的写都要先把机身那份备份下来**（`a2` 里 `psd.bin` 命中情况：0xca210）。`0100_config/big_backup.conf` 的内容正是 `/setting/psd.bin` ⇒ **官方流程会在更新前把旧 Backup 存到那里**（是个恢复点）。
- 26 份标准 Backup（BK4，条目数 2.00=750 / 2.03=819）里**都没有 `SHA1(VerificationKey.pem)`** ⇒ `verifyKey` 的指纹不是包内提供 ⇒ §4c 的真机 RAM 比对仍是决定性的。

## 4e. 机身 `/setting`(a2) 里已有三个恢复点（已实测解出，判据 md5 对得上）
`BACKUP.BIN`(1,210,408, BK4, md5 `7a549d06…`)、**`BACKUP.BAK`(同尺寸 BK4，与 .BIN 只差 265 B/85 run)**、**`PSD.BIN`(4,427,776, 高熵 = `big_backup.conf` 指的 `/setting/psd.bin`)**；另有 `KEMCO.TXT`(与包内 kemco.txt 逐字节相同)、`ULOGIO.BIN`(2.00 也有，2.03 版仅尾部多 24 B；**`TELN` 记录起于 `0x94`（长度字段）、标签串在 `+152`、值 dword 在 `0x9c`=0 ⇒ 改成 1 就开 telnet**)、`MODE/` 目录。
   - ★ulogio 段表已被 2015 MacBook 上的子代理解出（`notes/ulogio-format.md`、`tools/ulogio_cfg.py`，主会话复核通过）：
     **`LOGB` = 物理 `0x03085000` 长 `0x478000`（4.7 MB 日志环形缓冲）、`PRTB` = `0x034FD000` 长 `0x8000`**，两者首尾相接，
     **都落在出厂 `memrsv=0x75e000@0x02E68000` 保留窗里**（紧邻 Backup RAM `0x02E80000`）⇒ **日志文本一直在保留 RAM 里**：
     QEMU 侧别再在 `0x6000c000` 找 ulogio 环形缓冲（Round 18 找错了），直接读 guest RAM 的 `0x03085000`；真机侧拿到内存快照后这两个窗口就是免费的启动日志。
⇒ 机身 Backup 与包内标准件差 **99,401 B** ⇒ 覆盖 Backup 前必须先备份这三份；三份里都没有 `SHA1(VerificationKey.pem)`。
⇒ 半刷/写坏的恢复素材 = `/setting/{BACKUP.BIN,BACKUP.BAK,psd.bin}` + 我们已有的 a1/a2/a3/a7/a10/a13/a15/a23 dump（写回靠 L2.6 的 raw 节点写）。

## 5. 只能靠真机补的东西（当前所有硬缺口的共同答案）
`nflashaB0/B1`（EXBL 是否验 a1）、USER `0x0–0x10000`（真分区表 / FixedArea）、RAM `0x02e80000` 活副本、
官方更新卡 `BODYDATA.DAT`（真 FDAT 头 + 尾 256 B 签名）、以及 **L2.6 真机 raw 节点写**验证（见 `TEST_LADDER.md`）。

- ★低风险入口 1（TELN→root shell）：**改 a2 里 `/setting/ulogio.bin` 偏移 `0x9c` 一个字节 `00`→`01` + 重启 ⇒ `0.0.0.0:23` 无认证 root shell（2.00）**；a2 是 FAT12、更新不写它、文件可备份还原 ⇒ **R1**。拿到 shell 后 `dk/mu/mb/mw` 可直接读写物理内存 ⇒ 顺手解决 OTP 窗（`0xF340F000`/`0xFFFF5000`）、Backup RAM（`0x02E80000`）、LOGB 日志（`0x03085000`）。详见 `notes/ulogio-telnet-shell.md`。注意 2.03 的实现不同（不是 shell）；跑过 `ulogio telnet up` 会生成 `filter.bin` 覆盖该开关。

- ★低风险入口 2（/setting 旗标 + env.txt）：主系统 initrd(a3 的 `initrd.img`，**ext2**) 的 `/sbin/init`(28,524 B) 里确认存在 `/setting/mode/dmode`、`/setting/sen/smode`、`/setting/env.txt`(有 `parse_and_set_env`/`putenv`)、`/proc/udm/upm_bootmode`，且 init 自带 `LD_PRELOAD=/usr/tool/{libkmcsup.so.2.0.0,libsonyefence.so,libduma.so}`；那颗 initrd 里还有 `dosfsck` ⇒ a2 的 FAT 能自愈。⇒ **建文件即可试，默认都不存在，R0–R1**；各旗标触发什么正在追（`notes/injection-points.md`）。另：**官方更新会重写 /setting/ulogio.bin 与 kemco.txt**（补丁会被覆盖，也是改坏时的兜底）。

- ★更正（modes 轮，逐行验过）：**不能说"刷固件不写 /setting"**——`execute_ufp.sh:32-33` 有 `if [ -e /setting/updater/comp ]; then rm -rf /setting/updater/mode*`（`comp` 是空文件不是脚本）⇒ **旗标是一次性的**（这就是 QEMU 里 mode5 每轮要重注入的原因）；更新器还 touch `MediaUpdateCompleteFlag`、`libObj.so` 写 `/setting/mode/cmode`、`change_mode.sh` 写 `dmode/preload`、`up.sh` 写 `dat4`（不格式化、但目录项会变）。**旗标梯 = `mode3(MINOR) > mode2(SERVICE) > mode6(VERSKIP) > mode1(PROD) > mode5(MSCRYPT=SD 卡链)`**（2.03 `UdtrMain.sh` 18/21/24/27/30 行），**2.03 缺裸 `mode` 会 Forced Prod Mode**（第 15 行，+`touch /ramdsk/mode1`；2.00 无此判定）；`mode1` 走产线链且不清 comp ⇒ 会残留；`mode4` 死键。**影响正常开机的旗标在 `/setting/mode/`（dmode、preload←bootin.elf）与 `/setting/sen/`（smode），不在 `updater/` 下** ⇒ `/setting/updater/*` 是安全游乐场。a2 完整清单已解（`UPDATER/{COMP, DAT4=00 02}`、DmmConfig.bin、.hasp、.etools、facedmy.bin、facerec0..7、Backup.bin/.bak、psd.bin、kemco.txt、ulogio.bin、MODE/、GPS/、appfw_infra/）。

- ulogio 内存读写安全边界（`notes/ulogio-memory-access.md`）：`db/dw/dl/dk/mb/mw/ml/mf/mu` 走 CLI 自己的 /dev/mem mmap、**offset 就是物理地址**、**无白名单/无范围检查/不需先 switch**，只有对齐掩码；**打无效 PA 会整机挂死而非报错**。内核线性映射 `PAGE_OFFSET=0x60000000`(DDR0 1GB)、`DDR1 PA 0x80000000 ↔ VA 0xA0000000`；**`0x635C6000` 不是 ARM PA**（物理空洞；作 VA 才＝PA `0x035C6000`）⇒ 想读那片要写 `0x035C6000`。`logaddr` 表 = **109 SID / 417 区域，全在 PA `0x030850d8`–`0x034bd190`**，与我算的 LOGB/PRTB 互证。`dk` 落盘路径任意、大小无上限、命令行缓冲 0x80。**推论：读 `0xF340F000`/`0xFFFF5000` 等价于出厂 `SKData_Init` 每次更新都做的 mmap ⇒ 真机上可映射可读，风险 R1**。

- ★入口优先级改写（`notes/jiritsu-capabilities.md`）：**Jiritsu/SensTALK（USB 服务模式 PID 054c:0336）成为最低风险主入口** —— E-J1 `pFunc 0xff03 MemoryDump` 任意**物理读**（`/dev/mem`+`MappedMemory(prot=3,flags=1)`，`0x8000` 分片）；E-J2 `pFunc 0xff01 FileControl type=1`(`O_WRONLY|O_CREAT|O_TRUNC|O_DSYNC`)+`Jiritsu SET_FILE_PATH/SET_FILE2` **任意路径写文件、无清洗、无 `..` 过滤、自动建目录** ⇒ **往 /setting 写的通道就是它**；E-J3 **写 `/tmp/jiritsu/libJit.so` 立即 `dlopen`**（`0x5d76–0x5db8`）⇒ **无签名代码执行**，且它还会复制到 `/tmp/jiritsu/ramdsk_libJit/` 再加载。落盘区是 **a6 调试分区**，`cmd_format/FIRMUP` 只作用 a6，**没有任何原始写 a1/a15/a3 的命令** ⇒ 变砖面小。不要发：`NOR_WRITE/NVM_*/UNINSTALL_*/CLEAR_DEVICE_UNIQUE_KEY/*_FORMAT/DD_*_SET/EEPROM*/WRITE_CUSTOMER_REGIST_HASH256`。**唯一前置空白＝怎么进服务模式(0336)**。修正：`cmd_debug` 只设 RTC 不是提权；`0x601 RAM_READ/WRITE` 只是 ≤256 B LSI 缓冲不是物理内存；FileControl 问题是无白名单不是填充 bug。命令表 `notes/jiritsu-commands.tsv` 1,746 条。

- ★`libInfraSKD.so` 静态实读（我本人，2.00 那份 10,160 B）：**它自己就是 AES-256-CBC 解密者**（导入 `EVP_aes_256_cbc/CipherInit/CipherUpdate/CTX_new/free/set_padding` + **`SHA256`** + `snprintf`），源文件 **`astra_data.c`**，getter 叫 **`__GetCommonKeyData`/`__GetPublicKeyHash`**，init 在 `0xc04`（`open /dev/mem` → `mmap 0x400@0xFFFF5000` → `mmap 0x20@0xF340F000` → `osal_reg_sync_msg_queue_cb`），反 init `0xd28`（munmap 0x400/0x20），**`0x9ec` 是按类型 `0x00–0x13` 查 `{表指针,条数}` 的序列化器，两个取数全局分别限幅 `0x400`(=1KiB 窗) 与 `0x1f`**，分派器 `0xa7c`（type 1..4，含 0x20 字节入/出缓冲的一次调用）。工具：`tools/elf_imports.py`（PLT↔符号）、`tools/skd_dis2.py`（节头解析+字面量引用）。**排除**：key 不是那 32 字节原值；也不是对其做任何常见 hash/hex-文本 hash/EVP_BytesToKey/AES 包裹/HMAC；也不是 `sha256('0'*n)`(n≤8192) 或带分隔符的零 hex 文本 ⇒ **输入不止那两个窗**（下一步：QEMU 里 hook 它的 `SHA256`/`EVP_CipherInit` GOT 槽，把 key 的原始输入直接打出来）。
