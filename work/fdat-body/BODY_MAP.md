# FDAT 明文流内部结构地图（R18b，离线）

输入：`/tmp/dec200.bin`（2.00，344,853,504 B）、`/tmp/dec203.bin`（2.03，361,778,688 B）
容器：`/tmp/ilce7c200/…/FirmwareData_ILCE7CV200.dat`（346,206,712 B）、`/tmp/ilce7c203/…/…V203.dat`（363,197,944 B）
脚本：`work/fdat-body/p1_ufu_head.py`、`p2_align.py`、`p3_xcheck.py`、`p4_avcam.py`
（报告原文：`p1_report.txt`、`p2_report.txt`、`p3_report.txt`、`p4_report.txt`；成员表：`tarmembers_200.tsv` / `tarmembers_203.tsv`，列 = 数据偏移(明文绝对) / size / tar类型 / 名字）

结论一句话：**明文流 = 512 B `UDTRFIRM` 头 + object 表(2 项) + [obj0 = updater body cramfs] + [obj1 = 一个 ustar tar，tar 里放 4 个（2.03 为 5 个）整分区镜像 `0700_part_image/dev/nflashaX` + 一堆按段编号的文件]**。
真机 dump 与包内镜像**逐字节对齐成功**（2.00 的 a3/a5?/a7/a15 与机身 dump 前缀完全相同；2.03 的 a1 也在包内）。

---

## ① UDTRFIRM 头（明文 0x000..0x1FF，512 B）两版对照

| 偏移 | 字段 | 2.00 | 2.03 |
|---|---|---|---|
| +0 | magic | `UDTRFIRM` | 同 |
| +8 | u32 LE = crc32(hdr[12:512]) | `0xcdf83cd7` ✓实测 | `0xff8ccf1d` ✓实测 |
| +12 | ASCII 版本串 | `0100` | `0100` |
| +16 | modeType | `'U\0\0\0'` | 同 |
| +20 | u32（"luw"=78） | 78 | 78 |
| +24..+31 | 全 0 | — | — |
| +32 | **版本(BCD-u16+2B0)** | `00 02 00 00` = 2.00 | `03 02 00 00` = 2.03 ← **UUD 的 Old/New 版本字段就在这里**（低字节=次版本 BCD：0x0200/0x0203；高字节=主版本 0） |
| +36 | model LE u32 | `0x91030019`（字节 `19 00 03 91`） | 同 |
| +40 | region | 0 | 0 |
| +44 | u32 | 0 | 0 |
| +48 | obj2(tar) 明文偏移 | 143,872 = 0x23200 | 147,968 = 0x24200 |
| +52 | obj2 长度 | 344,709,632 | 361,630,720 |
| +56 | 对象个数 = 2 | 2 | 2 |
| +64 | obj0: `'U'`,头512,长度 | 143,360 | 147,456（cramfs @0x200）|
| +80 | obj1: `'P'`,512,0（占位） | 同左 | 同左 |
| +96..+127 | obj2/obj3 槽全 0 | — | — |
| +128..+511 | 未用（0x1C0 起实测全 0；0x200 起就是 cramfs magic `45 3d cd 28`+"Compressed ROMFS"） | | |

随版本变化的字段只有：**+8 头 CRC、+32 版本、+48/+52 tar 偏移长度、+68/+72 obj0 长度**（其余全部逐字节相同）。

## ② `6157 / 664`（DecryptorModule.cpp:112 打印 `6157:664`）

搜索范围与模式（两版各自）：UFU 的 DATV/PROV/UDID/DEND 全部 payload、明文头 0..0x2000、**整个明文流**；
模式：0x180D/0x0298 的 LE/BE u16 与 LE/BE u32、相邻对 `<HH (6157,664)`、`(664,6157)`、ASCII `"6157"` `"664"` `"6157:664"` `"6157:"` `":664"` `"\"6157\""` `"\"664\""`；另扫全部真机分区 dump 的前 4 KiB（boot sector / ext2 superblock / 组描述符）内任意偏移的 u16/u32 LE+BE。

**结果：没有任何结构化命中。**
- 头 0..0x2000：仅 1 处噪声（BE16 0x180D @0x161b/0x163f，落在 updater cramfs 压缩数据里）。
- FDAT 密文里 0x180D/0x0298 命中若干 = 随机噪声（密文）。
- 明文全流里 LE32/BE32 各自若干命中全部落在分区镜像/语言 blob 内部（如 2.03 `<HH(6157,664)` @0x13a0f1c5 在 a15 ext2 镜像里）——都是巧合，无成对结构。
- 分区引导头/ext2 超级块里也没有这两个数。
⇒ 离线侧看不到 `6157/664` 作为长度或计数出现在任何头/表字段。**含义未证实**；最像的猜测：相机侧某两个"条目数"（例如某 fs 的文件数）或运行期计数器，需相机侧再取证（本机搜过：文件名计数、tar 成员数 163/171、UDID 21 条、sum 条目数都对不上）。

## ③ UFU 外层容器（两版逐字段实测）

```
0x000 89 55 46 55 0d 0a 1a 0a
0x008 rec len=4   DATV  payload 01 00 00 00            （u32 LE =1，格式版本）
0x014 rec len=4   PROV  payload 01 00 00 00            （u32 LE =1）
0x020 rec len=172 UDID  = [be32 count=21] + 21×{ [u32 flag(LE)=1..2][u16 pid BE][u16 vid BE=054c] }
                          首条 0448/054c，末条 flag=2（03e2:054c）；两版逐字节相同
0x0d4 rec len=346,206,480 FDAT  (2.03: 363,197,712)    data 起点 0xdc
<len(B)-12> rec len=4 DEND  payload=BE crc32
```
- **DEND 修正**（旧文档口径不准）：`stored = zlib.crc32(B[0:len(B)-12])`，即覆盖到 DEND 记录 12 字节（len+type+crc）**之前**的全部字节。实测 2.00 `0xaaaa81b8` ✓、2.03 `0x53cabfbb` ✓（含 DEND 头则算不出来）。
- FDAT 尾 272 B = [16 B CBC IV][256 B 签名]；签名消息 = FDAT payload[0, size−0x100] = **整个帧流 346,206,208 B(2.00) + 那 16 B IV**。⇒ 明文流任何一字节都同时被"帧校验和 + DEND CRC + FDAT 签名"三重覆盖（改后必须重签名，见 tools/fdat_r14pack.py）。

## ④ 明文流内部布局（两版对照，绝对明文偏移）

```
[0x000,0x200)        UDTRFIRM 头（含对象表）
[0x200,0x200+len0)   obj0 = updater body（cramfs，magic 45 3d cd 28 "Compressed ROMFS"，未压缩存储 deflate 文件体）
[len2off,len2off+len2) obj1 = ustar tar（GNU，含长名字 'L' 条目）→ 11 个编号段
```

| 段（tar 顶层目录） | 2.00 plain 范围 | 2.03 plain 范围 | 内容 / 去向 |
|---|---|---|---|
| 0100_config + _sum | 0x23600..0x23ee5 | 0x24600..0x24ee5 | mount.conf、big_backup.conf（→ /setting 用） |
| 0110_backup + _sum | 0x24a00..0x1e2e828 | 0x25a00..0x1e39418 | 26 个语言/区域 blob（1,210,408 / 2.03 1,211,928 B） |
| 0300_partconf + _sum | 0x1e2fe00..0x1e30db1 | 0x1e3aa00..0x1e3b9b1 | **partinf.conf 两版逐字节相同**（分区表来源） |
| 0400_updater + _sum | —（2.00 无） | 0x1e3c600..0x262c600 | **dev/nflasha1 整分区镜像 8,323,072 B + updater.sum** |
| 0640_darwin + _sum | 0x1e32000..0x1e69478 | 0x262d800..0x2664c8c | darwin_core.bin（226,424→226,444） |
| 0650_prfile + _sum | 0x1e6a600..0x1f52dfb | 0x2665e00..0x27507fb | LICENSE 文本 |
| 0700_part_image + _sum | 0x1f54000..0x144e9400 | 0x2751c00..0x15309a00 | **4 个分区镜像 dev/nflasha15,a3,a5,a7 + part_image.sum** |
| 0800_appli + _sum | 0x144ea000..0x148de469 | 0x1530a600..0x15902469 | lens/字体/config.spec/…（2.03 增 setting/ulogio.bin、tmp/kikilog.dat）——按文件放样到 **a10** 的证据见 §⑤ |

tar 成员全部有对应 `NNNN_xxx_sum/*.sum` 条目，格式 `flag,crc32(BE hex),size(hex),mode,?,uid,gid,user,group,-1,-1,路径,`；
**实测：所有 .sum（config/partconf/backup/darwin/prfile/part_image/appli/updater）的 crc32+size 与成员字节内容全部吻合**（2.00 与 2.03 各自全量核对 ✓，见 p3_report）。
tar 内部成员顺序 ≠ 名字序（数据段按大小倒序摆放），表在 `tarmembers_*.tsv`。

## ⑤ 偏移对齐表（明文 ↔ 分区；两版）

真机 dump 对齐结果（2.00 = 机身 2.00 态）：

| 包内成员 | 2.00 明文偏移 | 与真机 dump 的关系 | 2.03 明文偏移 |
|---|---|---|---|
| 0700_part_image/dev/nflasha15 (239,982,592) | **0x1f54000** | `work/l2-camera/nflasha15.bin`(314,572,800) **前 239,982,592 B 逐字节全同**（分区尾部 74.6 MB 不在包内=用户数据区） | 0x2751c00（与 2.00 机身差 @0x400 起） |
| 0700_part_image/dev/nflasha3 (30,290,944) | **0x10431a00** | `work/l1_v/nflasha3.bin` **全长逐字节全同**（FAT12：bs512,簇32扇区,resv1,root@+0x8200，vol 180c4168） | 0x10f32600（FAT 结构变了：resv=32，vol 1f165c0f） |
| 0700_part_image/dev/nflasha5 (32,577,024→35,709,920) | 0x12115000 | 无机身 a5 dump | 0x12c16400 |
| 0700_part_image/dev/nflasha7 (4,992,000→5,132,288) | **0x14026800** | `work/l1-camera/nflasha7.bin`(8 MiB) **前 4,992,000 B 全同**（ext2 /；镜像是分区前缀截断） | 0x14e24a00 |
| 0400_updater/dev/nflasha1 (8,323,072) | — | — | **0x1e3c600**：`work/v203/nflasha1_203.bin` **全长全同**；与机身 `work/l1-camera/nflasha1.bin` 差在 @0x27（BPB 序列号区，机身运行时改过） |
| AV-CAM.BIN（在 a3 镜像内） | 数据 @**0x10441c00**（a3 成员+0x10200，目录项 @0x10439c20 起始簇3） | 与 `work/a3-avcam/AV-CAM.BIN`（17,394,576 B）头 512/1MiB/8MiB/中段窗口全部同偏移命中 ⇒ **就是同文件** | 数据 @**0x10f46600**（a3 成员+0x14000），文件大小 **17,398,676 = 2.00+0x1004** ✓（与"LUT 基址 +0x1004"一致；表体数值大面积重排，无法用整体窗口对齐） |
| 0800_appli/tmp/kikilog.dat (1,957,888) | —（2.00 无此成员） | a10 dump `work/l2-camera/nflasha10.bin` +0x47fe40 处内容 = 该成员头 512 B ⇒ **0800_appli 的文件按 a10 文件系统放样**（a10 不是整分区镜像） | 0x1571dc00 |
| 不在包内的分区 | — | a2(/setting)、a4、a6、a10 本体、a13、a23：明文里搜 boot sector 无命中（a2/a23 的 +1MiB 同窗假命中来自 vfat 空簇重复） | 同 |

分区大小核对（P3）：partinf.conf 两版相同（crc 23edf4ed）；part_image.sum 里 size 字段(BE hex) `01f11600`=a5、`0e4dd800`=a15、`004c2c00`=a7、`01ce3400`=a3 与 tar 成员长度一致 ✓；updater.sum `007f0000`=8,323,072=a1 分区全长 ✓；a1 分区尺寸与 partinf `0x7F0000` 一致 ✓。
（存疑：partinf 口径 a3 size 0x3000000=48 MiB，但 FAT 与成员只有 30,290,944=0x1CE3400 —— 分区尾未用或口径不同，标**未定**。）

## ⑥ 明文偏移 → FDAT 帧 → 密文偏移 换算（已往返验证）

帧流：**所有帧负载恒 1020 B，除末帧**（2.00: 338,092 帧、末帧 684 B；2.03: 354,685 帧、末帧 1008 B）。帧结构 `[u16 校验和][u16 len|bit15][1020 B 负载][0xFF 填充到 1020]`，帧 k 占 FDAT payload `[k*1024, k*1024+1024)`。

对任意明文偏移 p（0 ≤ p < 明文总长）：
```
k   = p // 1020            （帧号）
f   = 4 + (p % 1020)       （帧内偏移，FDAT payload 内）
FDATpayload = k*1024 + f
.dat 文件偏移 = 0xdc + FDATpayload           （FDAT data 起点 .dat@0xdc，rec@0xd4）
```
密文性质：FDAT payload[0,512)（= 帧0 头 + 明文 p∈[0,508)）走 **AES-128-ECB**；其余全部 **AES-256-CBC**（链从尾区 IV 起）。改明文的任何字节 ⇒ 需重算该帧校验和、重排帧（保持 1020/帧即可原帧数重排）、重加密该帧及其后全部 CBC 链、重算头 crc32(hdr[12:512))、重算 DEND crc32(B[:len-12])、**重新 RSA 签名 FDAT[0, size-0x100]**。
验证：p = {0,0x1ff,0x200,0x400,0x1234,0x186a0,文件尾-64} 各取 64 B（截到帧内），按上式回 FDAT 解密流取字节 **两版 7/7 全 ✓**（p3_report 头部 14 行）。
关键锚点的 .dat 偏移（示例）：2.00 a15 镜像头 = .dat@0x1f73814；a3 = 0x10536e4c；AV-CAM 数据 = 0x10547150；a7 = 0x14167f5c；2.03 a1 = .dat@0x1e5ac88（全表可跑 `p3_xcheck.py`）。

## ⑦ 压缩/杂项痕迹

- 明文 0x200 = updater body cramfs（`$Cram`/`$Crom` magic 串全流 **0 命中**；cramfs 用超级块 magic `45 3d cd 28`+"Compressed ROMFS"，非 `$Crom` 方向标记）。a1 的 initrd cramfs 在 2.03 a1 镜像内部（a1 镜像里再套 vfat→cramfs，`45 3d cd 28` 两版各出现 7~8 次，多在 tar 数据里的随机命中，真身只在 a1 镜像 +0x?? 处）。
- 2.00 明文里出现 xz 头 `\xfd7zXZ`（0x14217DF6 附近，a7 ext2 镜像内部一个 xz 文件），2.03 在 a7 镜像内 0x152A8A21 处也有 —— 是分区镜像自带的 /usr 压缩残留，不是 FDAT 层压缩。
- **FDAT 明文整体不压缩**（分区镜像原样存放，所以真机能逐字节对上）。

## 复现

```bash
python3 work/fdat-body/p1_ufu_head.py > work/fdat-body/p1_report.txt   # UFU 记录/头对照/6157 搜索
python3 work/fdat-body/p2_align.py    > work/fdat-body/p2_report.txt   # tar 成员表 + dump 窗口对齐（慢，~3min）
python3 work/fdat-body/p3_xcheck.py   > work/fdat-body/p3_report.txt   # 帧换算往返 + .sum CRC 全核对 + 精确对齐
python3 work/fdat-body/p4_avcam.py    > work/fdat-body/p4_report.txt   # FAT 解析 AV-CAM、段区间表、a10 证据、FS 头 6157 扫描
```
已知坑：`p2_align.py::build_frame_index` 的 FDAT 边界差 8 字节（IV 错位），帧映射以 `p3_xcheck.py` 版本为准。
