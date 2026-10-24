# A7C V2.03 全解 + 与 V2.00 逐项对比（2026-03 会话产物）

产物根目录：`work/v203/`。输入 `FirmwareData_ILCE7CV203.dat`（363,197,944 B）。

## 0. 解密与对象表（产物哈希）

| 产物 | 大小 | SHA-256 |
|---|---|---|
| `work/v203/full_dec.bin` | 361,778,688 | `3ca201291b9566126bad038716d466036898fdb564ed6ff35d8ea54adefe5659` |
| `work/v203/updater_203.img`（object0, cramfs, @512, 147,456 B） | 147,456 | `be375522808e37a47701976727a66f14bc39f95060c12ef33e1b9c32b984556f` |
| `work/v203/firmware_203.tar`（object1, @147,968, 361,630,720 B） | 361,630,720 | `be44cd8216ad059cd6fc92379f1f06dab73342fd08132476aee4fe0a757517b6` |
| `work/v203/full_dec_200.bin`（2.00 对照明文） | 344,853,504 | — |
| `work/v203/nflasha1_203.bin`（tar 成员 `0400_updater/dev/nflasha1`） | 8,323,072 | `c9040270ad886214c5656894b90fb1e839a3ab942cb65726633d8f1f1221c093` |

- FDAT 帧层：354,685 块 ×1024 B，块头 u16 校验和 354,685/354,685 全过；IV=`65813b8bd0d327fc282ea8265432f0d7`。
- `firmware_203.tar` == `full_dec.bin[147968:147968+361630720]`（流式 sha256 逐字节验证一致）。
- 头 CRC 存储=crc32(hdr[12:512])=`0xff8ccf1d` ✓（2.00 为 `0xcdf83cd7`）。

## A. 2.03 有没有 a1（最重要的问题）—— **有**

2.03 tar 成员 171 条（2.00 = 163），新增成员仅 5 条：

```
0400_updater/
0400_updater/dev/
0400_updater/dev/nflasha1      ← 8,323,072 B（=分区全长，FAT12 mkfs 后镜像）
0401_updater_sum/
0401_updater_sum/updater.sum   ← 145 B
```

- **没有任何 `0200_updater` 成员**；2.00 里 `dev/nflasha1` 完全不出现（`dev/nflasha15`/`nflasha10` 不算）。
- `0401_updater_sum/updater.sum` 全文（格式=`标志,CRC32,大小,模式,uid,gid,user,group,--,路径,`）：
  ```
  5,ffffffff,00000000,000001ed,00000000,000003e8,root,root,-1,-1,dev,
  0,3a26ae82,007f0000,000001a4,00000000,000003e8,root,root,-1,-1,dev/nflasha1,
  ```
  实测 `zlib.crc32(nflasha1_203.bin)=0x3a26ae82` ✓（第二列就是镜像 CRC32，与 part_image.sum 同一族）。

## B. 包内 a1（vfat/FAT12, 8 MiB）的内容

```
== 根目录 ==
drwxr-xr-x  boot/                 (16 KB 目录项)
-rwxr-xr-x  p1chksum              105 B   sha256 4feddcced0448f5a86d6421f7e90a2bb39c562f88dbc2ef2f7260603256e5003
== boot/ ==
-rwxr-xr-x  initrd.img   4,943,872  sha256 040a7d7666aa93f6abeade2caf153fd346c42dd90931de37bd656ae63d615d8d  (CRAMFS magic 45 3d cd 28)
-rwxr-xr-x  kemco.txt      1,062    sha256 79d71ee7182306b06fdbe093a553df0fbcfc195efa8dc1e2231413ce3c4737f3
-rwxr-xr-x  loadaddr.txt     33    sha256 a55bb7c1ef670cad21301679f75412bf2f81bfe713c3a83acd4b2b457523200d
-rwxr-xr-x  vmlinux.bin  1,701,156  sha256 49a2c6f83cfed9f963e1c82c4ea382a10614777a83173f52579406c63a11d1c5
```

- **没有 `dat2`/`dat3`**（整个卷只有上面 5 个文件）⇒ 包内 a1 是"出厂引导镜像"，机身 `dat2/dat3`（本机 model/region）是运行时才写的；正因如此 2.03 脚本在重写 a1 前备份、之后恢复（见 D）。
- `p1chksum` 原文（105 B，MD5 清单，只覆盖两个 boot 文件；实测两行都与解出的文件 MD5 吻合）：
  ```
  0dcd3b9177c38b610dcd0afdfba57def  ./boot/vmlinux.bin
  bb50bfb5261f161a9f49bd351e5fddfb  ./boot/initrd.img
  ```
- `loadaddr.txt` 全文：`0x00108000,0x00700000,0x00103000`
- `kemco.txt` 全文（bootargs，1,062 B）：见本报告被存文件 `work/v203/n15/a1_boot/boot/kemco.txt`；首行 `kemco`，含 `ip=off initrd=0x00700000,0x01000000 root=/dev/ram0 rw … init=/sbin/init … console=ttyAM0,115200n8 … mem=1G@0 … *`。
- 解出的 a1 全部 5 个文件已存 `work/v203/n15/a1_boot/`。

## C. a1 的 initrd（CRAMFS, 4,943,872 B）—— 完整清单在 `work/v203/a1_initrd/`（625 条目，manifest=`work/v203/a1_initrd_manifest.tsv`）

**"缺失六件套"全部都在 a1 initrd 里**（此前只在 a15/脚本里看到引用）：

| 文件 | 大小 | SHA-256 |
|---|---|---|
| `/usr/bin/crypter.elf` | 43,280 | `28c56467ee4038aad46713e014ab2bd538f5cd59645637abac58c75e720b2639` |
| `/usr/bin/up.sh` | 5,008 | `03a70fd0d0ef269c0de9530398d1e4d7cd8fcb089286cff682ee32d097ad16bd` |
| `/usr/bin/updater_log.sh` | 137 | `c5d4fa9c062b8794f92b551f5a70aa0335cf838ea2a6ecab3def2f5be836809a` |
| `/usr/bin/updater_storage_backup.sh` | 488 | `eb835d9ea1b270c6e9cccf6c0f7a01333874bee10986963c44a1ad044f07a0af` |
| `/usr/bin/updater_storage_restore.sh` | 619 | `7cc2f2d475c8954e35a5466a2501301b80a376be4dca6edf49118f654ff48949` |
| `/usr/bin/mf` | 39,960 | `8d99f909b0915d98e3b89c23f3e7627d009d4b10472efdb831bc2a1a94bb302c` |
| `/usr/bin/sauu` | 84,428 | `d79af0e6958e47c9b50622b1bedb4afe86b7384e3513ffd62ce09f9e2c18a322` |
| `/usr/bin/sen.elf` | 22,604 | `c257e5fc9a7f5738af8f4c5125527a9a0e7c0325a86ba51fc6413d5853706aaa` |
| `/usr/bin/is_valid_boot.sh` | 483 | `51a9aec51413eead0debd856afa60ad06ad4726bab2502a11415fe5c3a3a1b8a` |
| `/usr/bin/UdtrMain.sh` | 2,174 | `001220e5fa3b5242a48a107223dcf99d505225ef59d88872c7829135494418d9` |
| `/etc/VerificationKey.pem` | 451 | `79be4fb50a652540428f10ff55bb900b4523a20235737643809420d5ac4c3b04` |
| 另有 `updater_log_rotate.sh`(732)、`updater_storage_mount.sh`(589) | | |

**没有** `us_mkfs.sh`、`ud_mpr*`（us_mkfs.sh 属于 a15 的 bodyfs，不在 a1 initrd）。
注意：a1 initrd 里的 `crypter.elf`（43,280 B）**不是** a15/usr/bin 那个 crypter.elf（39,036 B）——两个不同构建。

三个脚本全文已在会话回报中贴出，文件本体都在 `work/v203/a1_initrd/usr/bin/`。
要点：`UdtrMain.sh` = 开机 updater 主入口（读 `/setting/updater/mode*` 旗标 → PROD/MINOR/SERVICE/VERSKIP/MSCRYPT/USER，再 `execute_prod.sh` 或 `execute_ufp.sh`）；`updater_storage_backup/restore.sh` = 把 updater 本地存储(vfat)备份到 RAM 再 `mkdosfs -f 1 -s 32` 重格式化后回写（`/root/IAMLDUDWRT` 串行烧录模式才强格式）。

## D. config.xml（body cramfs 内）diff：2.00 vs 2.03

整个文件唯一差异（1 行）：

```diff
12c12
<                       <shell module="us_crc32sum.sh" param="updater image"/>
>                       <shell module="us_crc32sum_updater.sh" param="updater image"/>
```

即 `updater_sum/updater.sum` 这个作业槽（`proc key="updater_sum/updater.sum"`）**2.00 的 config.xml 里已经有**，只是 2.00 的 tar 里没有 `0400_updater`/`0401_updater_sum` 段所以空转；2.03 补上了 a1 镜像段，并把校验脚本换成新的 `us_crc32sum_updater.sh`——它在 `uc_crc32sum.elf -s -c`（image 模式逐段 CRC+写设备）之后**挂回 /dev/nflasha1 并把 /ramdsk/dat2、/ramdsk/dat3 拷回去**。
配套 body 脚本变化（其余条目全部未变）：

- 新增 `/bin/us_crc32sum_updater.sh`（1,509 B）。
- `startupdate.sh`：新增"Accessory update 早退"分支；新增 **挂载 /dev/nflasha1 备份 dat2/dat3 到 /ramdsk**；新增 **kikilog w/a**（挂 /dev/nflasha10，1,957,888 B 的有效 `kikilog.dat` 备份到 /tmp_updater 并删除）。
- `endupdate.sh`：新增 accessory 早退；新增 把 `/tmp_updater/kikilog.dat` 写回 /dev/nflasha10。
- `body_common.sh`：新增 `MSCRYPT=6`。
- `config/body_version`：`100.101.014` → `100.111.035`。

⇒ **结论：2.03 会重写 /dev/nflasha1（整分区，8,323,072 B 镜像 + CRC32 清单），并在写前/写后保护机身 dat2/dat3。**

## E. body（updater cramfs）逐文件 diff（2.00=`body200/` 与 `body203/`，manifest `work/v203/manifest_20[03].tsv`）

- 新增：`/bin/us_crc32sum_updater.sh`（1,509 B）；删除：无。
- 改了（5 个）：`bin/body_common.sh` 125→135、`bin/endupdate.sh` 3,113→3,918、`bin/startupdate.sh` 1,296→2,434、`bodylib/libupdaterbody.so` 106,156→106,448、`config/config.xml` 2,213→2,221、`config/body_version`（同大小，内容变）。
- 未变：41 项，含全部 `*.elf`、`us_mkfs.sh`、`libupdatercommon.so`、`common.src`、`chassis`(=`CXD90045`) 等。

## E2. nflasha15 里的两个 gate 文件（2.03 从 ext2 镜像 `mount -o loop,ro` 取；存 `work/v203/n15/`）

| 文件 | 2.00 | 2.03 | 结论 |
|---|---|---|---|
| `bin/crypter.elf` | 39,036 `5721d6f3…3fa1` | 39,084 `e5fe58a7…43b0` | **代码逐字节相同**：`.text`/`.rodata`/`.plt`/`.rel.*`/`.data` 全部 SAME；唯一差异是 `.comment`（GCC 2018.12.05→2022.03.10/2022.06.14, Sony CE Linux 8.2.6.0→8.2.7.4/8.2.7.6，+44 B+padding=48）与 .dynsym/.dynstr 条目顺序。**校验逻辑没有任何变化**（UFU 链/DEND CRC/帧和/ECB/头CRC32[12,512)/chassis/取体 全同）。|
| `lib/libupdaterufp.so` | 12,936 `881c9a54…2206` | 13,152 `bf2c0ad9…f348` | 变了，但**门禁原封不动**：门禁函数仍在 **0x127c**（model/region/verskip 比较，0x12ca cmp model→bne 0x1306 `mov #0x140`；0x12da cmp region→`0x141`；0x12e4 verskip==1 跳过版本；0x12f8 `0x142`），modeType 检查仍在 **0x1b8c**（`ldrb [r6,#0x14]; cmp #0x4f/#0x55`，错误 0x1031），verskip 置位仍在 **0x1c00/0x1c08**；`udtr_conv_stat2err` 映射同（0x140→7,0x141→6,0x142→5）。`.rodata` 里 `/mnt/dat2`(0x291a)、`/mnt/dat3`、`/setting/updater/dat4`(0x2850)、`/dev/nflasha1`+`/mnt`+`vfat`+`posix_attr` mount(0x21f6..0x2206) 全部还在。变化：`.text` 0x16de→0x177a（+0x15c），插入 ~2 个新 IPC 辅助函数（≈0x1f48/0x1f52/0x1fd8：组 type=7 消息、`orr r3,#0x80000000` 后 `osal_snd_msg`；snprintf+valloc），并被 2 处调用（0x207a/0x2142）；一处 `stm_system` 调用新增；一个函数栈帧 +0x2B0；GOT/bss 整体右移 +0xac；导入符号集合完全相同。|

2.03 nflasha15 镜像本体：`work/v203/n15/nflasha15_203`（243,140,608 B，sha256 `d105d9e95f8d5a2ffa7df76a3da2fc894c2e33946b3ff3cfed66110794e72fbc`）。

## E3. 头字段对比（2.00 vs 2.03，全部实测）

| 偏移 | 字段 | 2.00 | 2.03 |
|---|---|---|---|
| +0 | magic | `UDTRFIRM` | 同 |
| +8 | 头 CRC32（覆盖 hdr[12,512)） | `0xcdf83cd7` ✓ | `0xff8ccf1d` ✓ |
| +12 | 格式串 | `0100` | `0100` |
| +16 | modeType | `U`(0x55) | `U`(0x55) |
| +20 | luw | `0x4e`(78) | `0x4e`(78) |
| +32 | **版本** | 字节 `00 02 00 00` | 字节 `03 02 00 00` |
| +36 | model | `0x91030019` | `0x91030019` |
| +40 | region | 0 | 0 |
| +44 | (0) | 0 | 0 |
| +48 | obj2(tar) 偏移 | 143,872 (0x23200) | 147,968 (0x24200) |
| +52 | obj2 长度 | 344,709,632 | 361,630,720 |
| +56 | 对象个数 | 2 | 2 |
| +64/+68/+72 | obj1 modeType/头长/长度 | `U`/0x200/143,360 | `U`/0x200/147,456 |

**+32 版本语义**：字节 `03 02 00 00`（2.00 `00 02 00 00`）。作为 **单个 u16 LE 存储的 BCD 打包值**：低半字(2 B)= `0x0203`（主版本在高字节：02.03），+34..35 = `0000` 两版皆零。即"一个 BCD-u16 + 2 字节零"与"两个 u16(0x0203,0)"在现有两版数据上不可区分，但没有任何字段间接受过非零值 ⇒ 采信 BCD-u16（主版本高字节）模型 ✓（`fdat_layout.py` 把它误标成 hdrlen=0x200；真实头长仍恒 512，由 +68 给出）。

**FDAT 尾 272 B（前 32 B hex）**：
- 2.00：`13 ef b6 a3 9e 3f 0c f8 34 59 33 67 9c 7e d2 22 | 08 b7 3f 29 b1 cd d4 be 39 73 b5 17 98 6d ea eb`（IV=前 16B）
- 2.03：`65 81 3b 8b d0 d3 27 fc 28 2e a8 26 54 32 f0 d7 | b4 f4 ad e4 78 4d 92 96 2c ad 21 7c 31 69 41 6c`

## 其余 tar 段逐项 diff（2.03 vs 2.00）

| 段/文件 | 结果 |
|---|---|
| `0300_partconf/partinf.conf` (4,017 B) | **逐字节相同**（sha `fc23dc2edb8e…`）⇒ 分区表/大小/名字不变 |
| `0100_config/mount.conf` (1,253 B) | **逐字节相同**（sha `0ef2d463b13c…`）；`big_backup.conf`、`0101_config_sum/config.sum`、`0301_partconf_sum/partconf.sum` 也全同 |
| `0701_part_image_sum/part_image.sum` | 同一批 4 块（a3/a5/a7/a15，无 a1），大小/CRC 全变：a5 32,577,024→**35,709,920**(+3,132,896)；a15 239,982,592→**243,140,608**(+3,158,016)；a7 4,992,000→**5,132,288**(+140,288)；a3 30,290,944→**30,292,992**(+2,048) |
| `0111_backup_sum/backup.sum` + `0110_backup/` | 文件清单完全相同（NB 13 + NB_HIBIKI2 13，共 26 区域 blob）；**每个 blob 1,210,408→1,211,928 B（+1,520）**，26 个 CRC 全变；`MainDest.txt` 全同：`SYSASTRA-DSLR / NB / CX88600_UC2.bin` |
| `0801_appli_sum/appli.sum` | 新增 2 条目：`setting/ulogio.bin`(3,796 B)、`tmp/kikilog.dat`(1,957,888 B)；字体 2 个变：`Sony_DI_Icons.ttf` 566,836→619,664、`MYingHeiC-GB18030-SJ_wIcon.ltt` 1,958,944→2,053,204（Big5 ltt 大小不变但 CRC 变）；**其余（含全部 57 个 lens 文件、DmmConfig、facedmy、config.spec…）逐字节未变** |
| `0640_darwin/darwin_core.bin` | 226,424→**226,444**(+20) 变了 |
| `0650_prfile/` | LICENSE 清单变化：+`jsoncpp.txt`、+`opus.txt`、-`IW.txt`；`libcurl.txt`/`openssl.txt`/`libssh2.txt` 内容更新 |
| `0600_gps`、`0630_ca`、`1030_genlock`（及各自 `_sum`） | 两版都是**空目录**（无任何成员）⇒ 无变化 |
| tar 成员名 diff 全部 | 见上文 A 的 5 条新增 + `IW.txt` 删 + `jsoncpp/opus/ulogio.bin/kikilog.dat` 增，别无其它 |

## 卡住/未做

- 无卡死项。brew 无 e2fsprogs/cramfsprogs；cramfs 解包改用 vendored `refs/fwtool.py/fwtool/archive/cramfs.py`（重写零依赖版 `work/v203/cramfs_unpack.py` 未用上，实际用 `work/v203/dump_body.py` 调 fwtool，成功）；ext2 用 OrbStack `--privileged` + `mount -o loop,ro` 成功。
- 2.03 的 `libupdaterufp.so` 新增 IPC helper（type=7 + 0x80000000 flag 的消息）语义未深挖；只确认门禁/错误映射/字符串不变。

## 工具脚本（新写）
- `work/v203/cramfs_unpack.py`（独立 cramfs 解析，未最终采用）
- `work/v203/dump_body.py`（fwtool cramfs → 目录 + manifest(path/size/sha256)）
- 反汇编/对比中间产物：`work/v203/ufp_text_20[03].asm`、`ufpsyms_20[03].txt`、`crypt_syms_20[03].txt`、`tar_list_20[03].txt`、`manifest_20[03].tsv`、`a1_initrd_manifest.tsv`
