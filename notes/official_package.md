# 官方 `.dat` 明文侧的权威"可写清单"（决定刷入枚度与自签路线）
离线，只读；来源 = 官方 `FirmwareData_ILCE7CV20{0,3}.dat` 解密体（配方见 `notes/updater_verify.md` 末节 / `tools/fdat_aescbc.py`），
明细产物在 `work/fdat-body/`（`BODY_MAP.md`、`tarmembers_20{0,3}.tsv`、`p1..p4_*.py`）。
真机 dump 比对用的是我们自己的只读 dump（`work/l1-camera/`、`work/l2-camera/`、`work/l1_v/`）。证据级 **E3（离线可复跑）**。

## 1. 明文体的组成：512 B 头 + obj0 + obj1(tar)
- 头（明文 `0..0x200`）：`UDTRFIRM` + `+8 = crc32(hdr[12:512]) LE` + **`+32 = 版本 BCD-u16`（2.00 `00 02` / 2.03 `03 02` ⇒ **UUD 门读的 Old/New 版本字段就在这里**）** + `+48/+52 = tar 偏移/长度` + `+68 = obj0 长度`；`model 0x91030019`、`region 0`、`modeType 'U'`、`+20=78` 两版相同。
- `obj0` = updater body cramfs（magic `45 3d cd 28`，2.00 @plain `0x200` / 143,360 B）；`obj1` = **ustar tar**（2.00 @`0x23200`、2.03 @`0x24200`）。
- tar 成员数：**2.00 = 163 / 2.03 = 171**；所有 `*_sum` 的 `crc32+size` 与成员**全量核对通过**。

## 2. tar 的 11 个编号段 = **官方一次更新会写的东西**
| 段 | 内容 | 2.00 | 2.03 |
|---|---|---|---|
| `0100_config` | 3 个文件 + **`big_backup.conf` = `/setting/psd.bin`**（17 B，"big backup"目标路径） | 1,270 B | 同 |
| `0110_backup` | **26 个 BK4 标准 Backup blob** + `MainDest.txt` | 31 成员 31,470,641 B | 31,510,161 B |
| `0300_partconf` | **`partinf.conf`**（4,017 B，2016-07-07 生成） | ✓ | ✓ |
| `0400_updater` | **`dev/nflasha1` = 8,323,072 B（= `0x7F0000` 整个 a1）** | **不存在** | **✓（仅 2.03）** |
| `0600_gps` / `0630_ca` | 0 B 占位 | ✓ | ✓ |
| `0640_darwin` | `darwin_core.bin` | 226,424 B | 226,444 B |
| `0650_prfile` | 24/25 个文件 | 937,960 B | 945,883 B |
| `0700_part_image` | **`dev/nflasha15`（usr）、`dev/nflasha3`（Main）、`dev/nflasha5`（Warm Boot Image）、`dev/nflasha7`（Rootfs）** | 239,982,592 / 30,290,944 / 32,577,024 / 4,992,000 | 243,140,608 / 30,292,992 / 35,709,920 / 5,132,288 |
| `0800_appli` | `lens/VX*_lensfile.bin`（~55 个）、`setting/{DmmConfig.bin, facedmy.bin, kemco.txt, appfw_infra/, `**`ulogio.bin` 仅 2.03**`}`、`tmp/{mtab,nsswitch.conf,protocols,services,toprc,config.spec,images}` | ✓ | ✓（多 `ulogio.bin`） |
- ⇒ **官方更新的写对象 = `a15 + a3 + a5 + a7`（2.03 还加 `a1`）+ Backup 里被选中的那一份 blob + `0800_appli` 若干文件 + `partinf.conf/darwin/prfile/config`**。
- ⇒ **不写**：`a2(Setting)`、`a4`、`a6(Jiritsu)`、`a10` 本体（只以文件放样）、`a13`、`a23`。
- 注意 **`a5 = Warm Boot Image` 也在写列**：只写 `a3/a15` 而 `a5` 没跟上（半刷）会让 warm-boot 恢复成旧状态——这是我们之前没想到的半刷风险面。

## 3. `0110_backup`：26 个"标准 Backup"（BK4）与机身那份的关系
- 每份都是 `BK4` 头：**`+0x00 = RAM PA 0x02e80000`**、`+0x04 = 0xaaaaaaaa`、`+0x0c = "BK4"`、**`+0x10 = 条目数 750`(2.00) / `819`(2.03)**（**条目 +69**），size `1,210,408`(2.00) / `1,211,928`(2.03)。
- 命名：`SYSASTRA-DSLR/{NB, NB_HIBIKI2}/{CX88600, CX88601, CH88600, CH88601}_{ALLLANG,E38,J1,KR2,UC2,AF1,AP2,CEC,CN1,CN2,IN5,JE3}.bin`
  ⇒ **两个机型系列（NB / NB_HIBIKI2）× 12 个区域/语言档**。
- **`MainDest.txt` = 选择器**（两版都是 `SYSASTRA-DSLR / NB / CX88600_UC2.bin`）⇒ 官方流程按它挑一份写进 Backup。
- **机身 `/setting/Backup.bin`（md5 `7a549d06…`，也正是 QEMU 里预填 RAM 的那份）与 26 份标准件都差很多**：最近的一份仍差 **93,617 B / 2,203 个 run**（首处 `+0x08`，机身 `01` vs 包 `00`）；机身那份在 `0x02fb94`、`0x02fd3c`、`0x031f69…`（ASCII `haZZTSMNJHGFE…`）等处**有值**而标准件是 `00` ⇒ **机身 Backup 是装配/运行时累积的设备专属内容**。
- **26 份标准件里都搜不到 `SHA1(我们的 VerificationKey.pem)`**（raw / hex 大小写都没有）⇒ **`verifyKey` 要的指纹不是官方包 Backup 段给的** ⇒ 更支持"**真机 RAM blob 由 BodyLoader/主系统运行时组装**"这一假设 ⇒ **真机 `0x02e80000` 与 `a2:/Backup.bin` 的逐字节比对仍是决定性实验**（`CHECKPOINT.md` §4c）。

## 4. 包里那份 `partinf.conf` 与机身分区表**不一致**（别再搞错）
- 包里（2016-07-07 生成）：`a1` Updater 7.94MB、`a2` Setting 20MB、`a3` Main 48MB、**`a4` MPR Flash Backup 12MB**、**`a5` Warm Boot Image 60MB**、**`a6` Jiritsu 16MB**、`a7` Rootfs 8MB、`a10` Work 12MB、**`a11` Log 500MB@`0x0B800000`**、`a12` Network 40MB、`a13` UpdaterWork 4MB、**`a15` usr 300MB@`0x2D800000`**、`a16/a17` Android(system/data)…
- 机身表（USER byte 0）里 `a15` 在 `0xB800000`（= 包里的 a11 Log 地址）。
⇒ **名字与大小对得上（`a15`=usr 300MB、`a3`=Main 48MB、`a7`=Rootfs 8MB、`a5`=Warm Boot 60MB），起始地址不同**；tar 成员名 `dev/nflashaXX` 与机身节点名一致（对齐已证：`dev/nflasha15` 逐字节 == 机身 a15 前 239,982,592 B）。
⇒ **用法：包内的"名字/大小"可信，包内的"地址"不可信**（机身 USER 表为准）。`type` 字段：`a5=2`、`a15=0`、其余多为 `1`（含义待定，可能与"是否校验/是否可更新"有关）。
⇒ 首次拿到权威分区语义命名：**`a4=MPR Flash Backup`、`a5=Warm Boot Image`、`a6=Jiritsu`、`a12=Network`、`a13=UpdaterWork`**（`a6=Jiritsu` 与我们的 `/tmp/jiritsu` mount(nflasha6) 完全对上）。

## 5. 两条风险线索（本机 dump 实测）
- 机身 `a4`（`work/l2-camera/nflasha4.bin`，12,582,912 B）开头是 **`CMMeX`** 结构（`43 4d 4d 65 58 00 58 00` + 一串 `{…ff}` 记录）⇒ **a4 不是 a1 的镜像副本** ⇒ "**刷坏 a1 有 a4 兜底**"这个假设**不成立**（bricking 风险回到 R0，除非另有证据）。
- 机身 `a3` 里有 **`SABIN`(`0x8480`) 与 `SSBOOT`(`0x13442e0`)** ⇒ `kemco.txt` 的 **`cmpr.path=/system/sabin/ssboot.bin`（+ `ssboot_any.bin`）** 在 2.00 上确实存在（比较/warm-boot 镜像）。

## 6. `kemco.txt`（2.00/2.03 都有，1,905 B）= 主系统启动配置（QEMU 直接可用）
`ramdisk_size=8192`；`rootfstype=ext2 root=/dev/ram0 init=/sbin/init initrd=0x700000,8M`；
**`console=ttynull`**（⇒ 主系统本来就没控制台，与我们 QEMU 上 amba2"只出不进"的观察一致）；
`xrstreq=1 wdt.mode=1`、`exception.reboot=1`、`wdt.timeout=500`；
**`warm.mode=2 warm.tmo=100000 warm.resume_drop=0 warm.boot_drop=0 warm.ignore_drop=1`**；
`cmpr.path=/system/sabin/ssboot.bin cmpr.path2=/system/sabin/ssboot_any.bin`；
`pcie.ch0/ch1_enable=Y pcie_ports=native pci=ecrc=on pciehp.pciehp_force=Y pcie_aspm.policy=performance`；
`cxd900x0.bam=N mmu.dac=Y exec.coremode=1 adrs_conv.debug=1 adrs_conv.null=Y`；
`page_alloc.minkb=128 lokb=1024 hikb=1280`、`lpj=1757184`、`pgd.n=15`、`cache_l2x0.wait=3 prio=130`；
`tmonitor.addr=0xF00000 tmonitor.size=0x8000 tmonitor.mask=0`；`pm.resume=0x20021054 pm.sus_error=0x20021060 pm.ddr_ctrl=sref pm.pasr1=0xff`；
`snsc_workqueue.kipid=130 manage.irqd=129 softirq.sirqd=123`、`snsc_boot_time.us=Y`、`basic.prof_path=/log/ssbi_prof.bin`、`ip=off`、`cgroup_disable=memory`。

## 7. `ulogio.bin`（**仅 2.03 包里有**，3,796 B，md5 `a401b16a…`）= ulogio 配置
段标记 `RECO LOGB PRTB CHAN ISYS DBGL DBCL FLTA TERM **TELN** FBOX SFLT CFLT` + 路径
`FLTF→/setting/filter.bin`、`RCVF→/log/escapelog.bin`、`ALGP/ALGB/ALGD/ALGK/ALGT→/log/ulogio_{blog,dlog,klog,tlog}(.txt)`；
头串 `LGNM191H_Dslr_Astra-Diadem`（codename，与 Backup 路径里的 `SYSASTRA-DSLR` 同源）。
⇒ **2.03 的 telnet/日志通道是这份配置驱动的**（2.00 不带这份 ⇒ 走内置默认；端口仍是 lib 里写死的 23）。
⇒ 给 gh#23（2.03）：这份文件在 `/setting`(a2) 里，改 `TELN` 段就是改 telnet 通道配置。

## 8. ★对"自签"路线的判定（重要修正）
运行时的顺序是 **`verifyKey`（已装 PEM 的 SHA1 vs Backup 指纹）→ `RSA_verify`（就用这把已装 PEM）**。
⇒ **没有 Sony 私钥就签不出能过 `RSA_verify` 的签名**；而"换 PEM"这件事本身要靠刷 **a1**（官方 2.03 包正是刷 a1）——可第一次刷又是旧 a1 的验签器把关 ⇒ **鸡生蛋**。
⇒ **结论：把"改过的 a1"用 raw 节点写灌进去（L2.6，`/dev/nflasha1` 整 8 MB 图 = 包里 `0400_updater/dev/nflasha1` 那份）绕过签名门，之后再让自制签名包接管 `a15/a3/a5/a7`。** 这把 **L2.6 从"自救工具"提升为"信任根 bootstrap"**。
（备选：若真机 RAM blob 里那 20 B 指纹条目可被我们写入（Route A″），也同样需要先能 raw 写 Backup。）

## 复现
```bash
# 解密 + 帧校验（两把 key 都是公开的，见 notes/updater_verify.md）
python3 tools/fdat_aescbc.py /tmp/ilce7c203/.../FirmwareData_ILCE7CV203.dat /tmp/dec203.bin
# tar 段清单与成员
python3 work/fdat-body/p3_xcheck.py          # 对齐/交叉验证（帧映射以此为准）
python3 tools/verify_sums.py                 # 包内 *.sum 的 crc32+size
# 机身 Backup vs 包内标准件
md5 work/l2-camera/probe2/_setting_Backup.bin.bin   # 7a549d06…
```

---
## 9. ★机身 `/setting`(a2) 的根目录 = 三个现成恢复点（FAT12 手工解出，判据已校）
`work/l2-camera/nflasha2.bin` 是 FAT12：`bps=512, SecPerClus=32(簇 16 KiB), RsvdSecCnt=1, NumFATs=1, FATSz16=4, RootEntCnt=512`
⇒ `fatstart=0x200`、`rootdir=0xa00`、`data=0x4a00`；**取文件：`offset = data + (cluster−2)×16384`**（我先前把它按扇区算错过一次，判据是"解出的 `BACKUP.BIN` md5 必须等于 `7a549d0600ae452a7c8ca3b2a56b58f4`"✓）。

| 目录项（root dir 偏移） | 名字 | 大小 | 内容/判定 |
|---|---|---|---|
| `0x0ae0` | `BACKUP.BIN` (cl 91) | 1,210,408 | BK4（`+0x0c`）；md5 **`7a549d06…`** = 我们一路用的那份 Backup ✓ |
| `0x0ca0` | `BACKUP.BAK` (cl 514) | 1,210,408 | **另一份 BK4 Backup**，与 `.BIN` 只差 **265 B / 85 run**（运行期计数差异）⇒ **第二恢复点** |
| `0x0c20` | `PSD.BIN` (cl 92) | 4,427,776 | 高熵（非零比 0.968）、无 `BK4`；头 `50 46 90 00 50 01 00 00 00 90 43 00 …` ⇒ 就是 `big_backup.conf` 指的 **`/setting/psd.bin`**（"big backup"，比 Backup 大一档，疑压缩/加密） |
| `0x0ba0` | `KEMCO.TXT` (cl 90) | 1,905 | **与官方包里的 `kemco.txt` 逐字节相同**（md5 `ef072ece…` ✓）⇒ 证明 `0800_appli/setting/kemco.txt` 就落在这里 |
| `0x0c60` | `ULOGIO.BIN` (cl 363) | 3,772 | **2.00 上也有 ulogio 配置**（2.03 包里是 3,796 B）；**前 3,772 B 与 2.03 版完全相同（差异 0 字节）**，2.03 只是尾部多 24 B |
| `0x0ce0` | `MODE`（目录, cl 440） | 0 | mode 旗标目录（`comp` 会清 `mode*` 的那个） |

要点：
- **`BACKUP.BIN` 与 `BACKUP.BAK` 与包内 `MainDest` 选中的 `CX88600_UC2.bin` 都差 99,401 B** ⇒ 机身 Backup 里 **约 10 万字节是设备专属**（序列号/校准/锁/计次）⇒ **任何"整份覆盖 Backup"的写之前，必须先把机身 `BACKUP.BIN`（和 `.BAK`、`PSD.BIN`）备份下来**；顺带：`BACKUP.BIN`/`BAK`/`PSD.BIN` 里都**没有** `SHA1(VerificationKey.pem)`（raw 与 hex 都没有）。
- **`ulogio.bin` 的段表在 2.00/2.03 上同一布局**：`RECO LOGB PRTB CHAN ISYS DBGL DBCL FLTA TERM **TELN** FBOX SFLT CFLT` + `FLTF→/setting/filter.bin`、`RCVF→/log/escapelog.bin`、`ALGP/ALGB/ALGD/ALGK/ALGT→/log/ulogio_{blog,dlog,klog,tlog}`；
  **`TELN` 记录在偏移 `152`，其值 = `00000000`（关闭）**，后面紧跟 `FBOX=0x20`、`SFLT=0x0c`、`CFLT=0x0c` 一类记录。
  ⇒ **"telnet 通道在 2.00 与 2.03 都存在，只是默认关闭"**（与 `ulogio telnet up` 需要置位+重启完全吻合）；给 gh#23（2.03）：配置就在 `/setting/ulogio.bin`，`TELN` 在 `+152`。
- 提取件存 `work/a2-setting/`（Sony 原件，已 gitignore，不重分发）。
