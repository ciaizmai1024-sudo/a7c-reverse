# Sony A7C（v2.00 / chassis CXD90045）更新机制分析

分析对象：本目录已解出的 `updater.img`（CRAMFS，41 个普通文件）与 `firmware.tar`（ustar，20 个带序号的顶层目录）。
方法：全部为静态分析（r2 / capstone / strings / python），**未对相机做任何写入**。

---

## 0. 先回答"下一步该分析哪里"

你提的方向（`libupdaterbody.so` ↔ `config.xml`，再看如何校验、识别机型、选组件）是对的，我按这个方向已经走完了一轮，结论如下（证据见后文）：

1. **`config.xml` 与 `libupdaterbody.so` 的关系已经证实**：`config.xml` 是数据，`libupdaterbody.so` 是解释器；但**组件类型是硬编码在 .so 里的 9 项表**，XML 只提供"某个 key 到了就跑哪些脚本"。
2. **更新器内部没有任何签名/公钥校验**，只有 CRC32 + size（本包 123 条记录全部可用普通 CRC32 重算，见 §4）。
3. **"识别机型"不在更新器里，而在主固件侧**：`libupdaterufp.so`（`firm_model/firm_region/firm_version/verskip`）+ `libupdatertalk.so`（`Dec_Scramble` = AES）+ `crypter.elf`，本机侧的 model/region/version 存在 `dat2/dat3/dat4`（需 `ud_datcnv.elf` 经 IPC 服务解密）。这才是真正的门禁。
4. 所以**"能不能绕过签名"这个问题在更新器侧不成立**（本来就没有签名）；真正决定成败的是 §5 的加密/机型门禁，以及 §7 里那些会擦分区的动作。

> **修订（后续实测，详见 `FIRMWARE_MOD.md`）**："没有签名"只对更新器 ramdisk 工件成立。
> **FDAT 尾部 272 B = 16 B IV + 256 B**（256 B 疑为 RSA-2048 签名；同 SoC 的 ZV-E10 侧已给出四条证据并实测 `checkGuard` 报 Invalid version），
> 而验签者很可能是 nflasha1 里的 `mf`——**本包不刷 nflasha1，所以手里没有这个文件**。另：FDAT 本身已可完整解密（密钥公开：`key_aes`=SHA256("")前16B、`key_cxd90045`），
> 338,092 个块校验全部通过；重打包只差那个签名。

**建议的下一步（优先级）**：见 §8。最值钱的两条是：把主固件侧的 model 比较点（`set_model/firm_model` 的调用者）钉死；把 `Dec_Scramble` 的 16 字节密钥来源钉死。

---

## 1. 三个镜像的角色与关系（实测）

| 文件 | 类型 | 角色 |
|---|---|---|
| `updater.img` | CRAMFS（magic `0x28CD3E45`，size 0x23000，**无 Sony 头、无签名**） | 更新器运行体 bodyfs：`config/config.xml`、`bin/*.sh`、`bin/*.elf`、`bodylib/libupdaterbody.so`、`usr/lib/libupdatercommon.so` |
| `firmware.tar` | ustar（目录名带 `NNNN_` 序号，序号决定解包/执行顺序） | 数据载荷：配置、分区镜像、app、lens 参数等 |
| （上游 `.dat`） | 加密包 | `firmware.tar` 与 `updater.img` 都是它解密后的产物；解密密钥见 §5.3 |

**关键实测**：`updater.img` 与固件里已经存在的 `/usr/bin/udtrbody.bin` **逐字节相同**（`cmp` 通过；CRAMFS "47 files / size 143360" 一致），说明本更新包里的更新器运行体就是 usr 分区自带的那一份，v2.00 并没有换更新器。

```
cmp updater.img \
  firmware.tar_unpacked/0700_part_image/dev/nflasha15_unpacked/bin/udtrbody.bin  # IDENTICAL
```

`part_image.sum` 只写 4 个分区：`nflasha3`(Main 48MB)、`nflasha5`(Warm Boot 60MB)、`nflasha7`(rootfs 8MB)、`nflasha15`(usr 300MB)。
`nflasha1`（Updater 分区）不在其中 —— **这个包不更新更新器 ramdisk**，只换它写进去的固件。

---

## 2. `config.xml` ↔ `libupdaterbody.so`：实际解释关系

地址都是 `bodylib/libupdaterbody.so`（ARM Thumb，`vaddr == paddr`）内的函数入口，符号名来自 `.dynsym`（该 .so 未 strip 导出符号）。

```
UpdaterBody::Execute(RingBuffer*, CallbackInterface*)          @ 0xf4f4   ← 唯一入口（外部经 GetBody/ReleaseBody 取实例）
  ├─ 日志 "Start unpacking"
  ├─ 建 /tmp_updater/updater/update  (EXTRACT_ROOT)
  ├─ mount -t vfat /dev/nflasha2 /setting (posix_attr)  → 读 /setting/Backup.bin 备份
  ├─ XmlConfigHandler::LoadConfig("/tmp_updater/updater/bodyfs/config/config.xml")  @ 0x1320e
  │     └─ XmlConfigHandler::LoadUserConfig(...)  @ 0x131ca     ← 还会读包里的 config/uconfig.xml（本包没有）
  ├─ KeyTagFactory::GetKeyTag(index, key)  @ 0x11338            ← 组件类型判定（硬编码表，§3）
  ├─ 每个 key：BaseKeyTag::PreExecute → Extract → PostExecute   @ 0xfac0 / 0x10934 / 0x606e
  │     ├─ PackedFileHeader::Parse @ 0xf150（校验 "ustar" magic、八进制 size；GNU longname 'L' 走 extractLongName @ 0xec90）
  │     ├─ NewFirmwareFile::extractDirectory @ 0x12318 / extractNormalFile @ 0x12488
  │     └─ XmlConfigHandler::isKey @ 0x133a4 → executeGuard @ 0x13450 → Plugin::Execute @ 0x14308
  └─ "End unpacking(process time = ...)"
```

XML 语法支持的元素/属性（`XmlConfigHandler.cpp` 的 rodata 里就是这些字面量）：
`programs` / `proc(key=)` / `shell(module=,param=,thread=)` / `run(module=,function=,param=,thread=)` / `guard` / `param` / `thread` / `execute`。

三类插件：
- `ShellPlugin::Execute` @ 0x13de8 —— 拼 shell 命令，**先 export 环境**（见 §6 的 PATH 注入），失败会 `getledval.elf` 报 LED 错误码。
- `DllPlugin::Execute` @ 0x140c4 —— `dlopen(module)+dlsym(function)`，对应 `<run>`；本包只有 `ul_crc32sumprfile.so / ul_crc32sumprfile`（注意 `bin/us_crc32sumprfile.sh` 存在但 config.xml 并未引用它，属遗留）。
- `ThreadPlugin` @ 0x13d14 + `ThreadIdQueue` —— `thread="yes"` 的分支并行，`Join(bool)` @ 0x13c54 / `HasError()` @ 0x13b0e 收口。

**guard 机制（本包没用）**：`executeGuard(key, node)` 读 `guard` 元素的 `module` + `function` 属性，先跑一个 `.so` 函数；`CheckGuardResult(key)` @ 0x13758 / `checkGuardResult` @ 0x132e8（遍历 `programs→proc`，比对 `key` 属性）决定该 proc 是否放行。A7C 的 `config.xml` 里**没有任何 `<guard>`**，也就是说更新器本身在这一层没有做任何"条件检查"。

---

## 3. 组件是怎么被选中的（两级：目录 → KeyTag；key → proc）

### 3.1 第一级：硬编码表（`KeyTagFactory::GetKeyTag` @ 0x11338）

先用 `StringHandler::GetPosition(...,'/')` 取 `'/'` 位置作为**目录分量的右边界**，再与 rodata 里的字面量逐个比较（顺序即代码里的比较顺序）：

| 比较字面量（0x16651…） | 构造的类 |
|---|---|
| `appli` | ApplicationKeyTag |
| `config` | ConfigKeyTag |
| `partconf_sum` | PartitionConfigChksumKeyTag |
| `part_image` | PartitionImageKeyTag |
| `appli_sum` | ApplicationChksumKeyTag |
| `updater` | UpdaterKeyTag |
| `updater_sum` | UpdaterChksumKeyTag |
| `prfile` | PrFILEKeyTag |
| `backup` | BackupKeyTag |
| 其它 | **NoKeyTag（普通解包，不特殊处理）** |

表里同时存在 `appli`/`appli_sum`、`updater`/`updater_sum`，说明比较是**整段目录名比较**（`'/'` 位置正好给出边界），不是前缀匹配。
tar 里的目录名带 4 位序号（`0100_config`），而相机侧脚本引用的是 `$EXTRACT_ROOT/config`（`/tmp_updater/updater/update/config`），所以解包时序号前缀会被剥掉；序号的真实用途是 `PackedFileHeader::getIndex @ 0xecf0 / removeIndex @ 0xed28` 维护"同一序号一组"的分组顺序（0100=数据，0101=该组件的 CRC 门禁）。

### 3.2 第二级：XML 的 `proc key` —— 包里有这个文件，这个 proc 才跑

本包（v2.00 全量包）实际触发的 proc：

| tar 目录（序号） | proc key | 触发时执行 | 作用 |
|---|---|---|---|
| `0101_config_sum` | `config_sum/config.sum` | `us_crc32sum.sh "config file"` → `chkfirm.sh` → `edit_mount.sh` → `keep_big_backup.sh` | 校验 config 目录；判定 主/子 LSI（`ud_get_power_ic_type.elf` + 包里是否有 `config/sub.conf`）；把 `mount1.conf` 追加进 `mount.conf`；把 `big_backup.conf` 列出的文件（`/setting/psd.bin`）先搬进 tmpfs |
| `0111_backup_sum` | `backup_sum/backup.sum` | `us_crc32sum_backup.sh` | 要求包里恰好 1 个 `backup/*/*/*.bin`，只挑该文件那一行做 CRC（机型相关的 Backup.bin 模板：CX88600/CX88601 各语言版本） |
| `0300_partconf` | `partconf/partinf.conf` | `chknandcapa.elf partconf/partinf.conf` | 包内分区表 vs 实际 NAND（fopen/fgets 解析 + ioctl 查容量） |
| `0301_partconf_sum` | `partconf_sum/partconf.sum` | `us_crc32sum.sh` → **`us_mkfs.sh`** | 重建分区（`edisx.elf /dev/nflasha partinf.conf`）+ 逻辑格式化（`uc_mkfs.elf -m full|app`）+ `ud_keep_backup.elf -s` 还原 Backup.bin + `ud_wbi_drop.elf` + `dosfsck -Y /dev/nflasha2` + 写 `/setting/sen/smode = "UU"` |
| `0641_darwin_sum` | `darwin_sum/darwin.sum` | `us_crc32sum.sh` → `us_darwin_firm.sh`（thread） | `darwin_core.bin`（226KB）升级。**注意：bodyfs 里没有 `us_darwin_firm.sh`**（见 §8 未解项） |
| `0651_prfile_sum` | `prfile_sum/prfile.sum` | `<run module="ul_crc32sumprfile.so" function="ul_crc32sumprfile" thread="yes">` | PMBP(prfile 分区) 校验，走 `.so` 且并行 |
| `0701_part_image_sum` | `part_image_sum/part_image.sum` | `us_crc32sum.sh "part_image image"`（`-s -c`，**不查 size**） | 校验刚写进分区的 4 个镜像 |
| `0801_appli_sum` | `appli_sum/appli.sum` | `us_crc32sum_appli.sh appli` | 先把 `/ramdsk/dat2,dat3` 还原到 `/mnt`(=nflasha1)、`dat4` 还原到 `/setting/updater/` 并 `touch mode`+`mode6`（版本跳过模式），再对 68 个 app/lens 文件做 CRC |

包里**没有数据、因而不会触发**的 proc：`updater_sum/updater.sum`、`front_sum`、`ca_sum`、`gps`、`accsy_sum`、`loader_sum/loader.sum`（`loader_writer.sh` → `pformat.elf /dev/nflashaB0`）、`genlock_sum`、`furud_sum`（`us_spi_firmup.sh`）。其中 `0600_gps / 0630_ca / 1030_genlock` 只是空目录占位。
→ 这就是"选择更新组件"的真实含义：**包内目录集合 + 序号顺序**驱动，XML 只是把这些 key 映射到脚本。

---

## 4. 校验到底是什么（不是签名）

`bin/uc_crc32sum.elf`（strings）：

```
[CRC32SUM] uc_crc32sum [-s] -c file
[CRC32SUM] -c file : sum file
[CRC32SUM] -s : not check size mode
[CRC32SUM] check sum OK / check sum NG
[CRC32SUM]error %s size mismatch (stat size = %ld, list size = %ld)
[CRC32SUM]error %s crc mismatch (stat crc = %ld, list crc = %ld)
```

`.sum` 记录格式（逗号分隔，实测）：`flag,crc32,size(hex),mode,?,gid/uid,user,group,-1,-1,path,`（`flag` = 文件类型：`0` 普通文件（有真实 crc/size）、`5` 目录（`crc=ffffffff,size=0`）、`2` 符号链接（第 11 字段存目标，例 `tmp/mtab,../proc/mounts`））。

`tools/verify_sums.py`（本次新增）实测：

```
0101_config_sum/config.sum  -> 0100_config     : OK=2  NG=0
0111_backup_sum/backup.sum  -> 0110_backup     : OK=27 NG=0
0301_partconf_sum/...       -> 0300_partconf   : OK=1  NG=0
0641_darwin_sum/darwin.sum  -> 0640_darwin     : OK=1  NG=0
0651_prfile_sum/prfile.sum  -> 0650_prfile     : OK=20 NG=0
0701_part_image_sum/...     -> 0700_part_image : OK=4  NG=0
0801_appli_sum/appli.sum    -> 0800_appli      : OK=68 NG=0
合计 124 条：123 个普通文件全部 CRC32 + size 相符，NG=0（剩 1 条是符号链接 tmp/mtab -> ../proc/mounts，无 CRC）
```

→ **`.sum` 只是"包内容自洽"的完整性校验**：任何人重新打包都能自己重算 CRC。它不能证明"这是 Sony 签过的包"。
另外 `PackedFileHeader::Parse` 只验 ustar magic（`dlsym("ustar")` 取全局魔数比对）和八进制 size 字段。

在整个 `libupdaterbody.so` / `libupdatercommon.so` / `uc_crc32sum.elf` 里检索 `sign|rsa|ecdsa|sha|hmac|cert|pubkey|verify` **没有任何验签实现**；唯一的密码学原语在主固件侧（§5.3 的 AES）。
`/cert` 分区（nflasha12，40MB）是相机网络/证书用途，与固件更新无关。

---

## 5. 机型识别与真正的门禁（在主固件 `nflasha15`/usr 里，不在更新器里）

### 5.1 更新模式（`UPDATER_ACTION_MODE`）由旗标文件决定
`/setting/updater/` 下（nflasha2）：`mode`、`mode1`、`mode3`、`mode5`、`mode6`。
`/usr/bin/up.sh`（usr 分区，服务/维护用）：

```
up.sh            → touch mode mode1        → 进 Updater（UFP）模式，再 ud_send_lsi.elf 4
up.sh serv       → mode + mode3            → SERVICE
up.sh user       → mode                    → USER（普通用户更新）
up.sh ms         → mode + mode5            → MSCRYPT
up.sh ver        → mode + mode6            → VERSKIP（版本跳过：允许不降/不升版本刷）
up.sh modmod  <8位hex>  / modreg <8位hex> / modver <4位>
```

对应 `config/common.src` 的 `MODE_USER=0 / PROD=1 / SERVICE=2 / MINOR=3 / VERSKIP=6`，`us_mkfs.sh` 也按这些模式决定 `edisx`+`uc_mkfs -m full` 还是 `-m app`（USER/MINOR/MSCRYPT 连分区重建都不做）。
`libupdaterbody.so` 里对应 `Mode1/2/3/5/6FlagFile`、`CompleteFlagFile`、`/root/IAMUPDATER`、`/root/IAMLDUDWRT`（串刷）等旗标类。

### 5.2 本机 model / region / version 的存在形式
`up.sh` 的 `func_com_mod_modreg`：`dat2`(model)、`dat3`(region) 在 **`/dev/nflasha1`（Updater 分区）**，`dat4`(version) 在 **`/setting/updater/`**；读写必须经
`ud_datcnv.elf -d/-e -i <in> -o <out> -a`，而 `ud_datcnv.elf` 只链接 `libosal_uipc.so`（**把加解密交给另一个进程/服务**，密钥不在文件系统里；相机里有 `mpr_monio.elf`/`mpr_viewLog.elf` 与 MPR 分区 nflasha4）。
这解释了 `us_crc32sum_appli.sh` 为什么要先把 `dat2/dat3/dat4` 备份到 `/ramdsk` 再写回 —— app 刷新会重建分区，这三个文件是"机型/区域/版本身份"。

`config.yaml` 里 `fdat: model 0x91030019 / region 0 / version 2.00` 就是**包头**里的机型/区域/版本（`libupdaterufp.so` 的导入符号：`firm_model / firm_region / firm_version / set_model / set_region / set_version / verskip / ac_flag / acsy_flag / udtr_get_firm_info_inmedia`），更新器把这些与相机侧 `dat2/3/4` 对照后决定要不要刷、能不能降。

### 5.3 唯一的密码学操作：AES 描述乱（scramble）
`usr/lib/libupdatertalk.so`（小库，导出符号明确）：

```
Dec_ScrambleInit @0x620 → AES_set_decrypt_key(keyptr, 0x80 /*128bit*/, &decx)
Dec_Scramble     @0x648 → AES_decrypt(block→栈) 后原地拷回 16 字节  （ECB，16B 分组）
KeyArray : GLOBAL OBJ 32 字节 @0x8830
```

实测本构建里 `KeyArray = e3b0c44298fc1c149afbf4c8996fb924 27ae41e4649b934ca495991b7852b855`
= **SHA-256 空串的摘要**（占位/派生痕迹，真实密钥很可能按 chassis 在构建期注入 —— 与 `config.yaml: dat.crypterName: CXD90045` 对应）。
`libupdaterufp.so` 调 `Dec_ScrambleInit/Dec_Scramble`，并使用 `/usr/bin/crypter.elf`（`Updater::CryptFileInputUpdaterManager / MsCryptBufferManager / MsDecryptorModule / DecryptorModule`，同样走 `libosal_uipc` 服务路径）。

**结论**：门禁 = "包头的 model/region/version 与本机 dat2/3/4 匹配" + "包体是用 chassis 对应的 AES 密钥加密的（没有密钥就连结构都看不到）"，**不是数字签名**。这个判断只适用于更新器与上述库；不排除 loader/boot 侧还有别的校验（§8）。

---

## 6. 更新器自带的"跳过某组件"开关（官方留的口子，值得优先利用）

`libupdaterbody.so` 与脚本里这些是**运行时旗标**，不是校验：

| 旗标 / 机制 | 位置 | 效果 |
|---|---|---|
| `nwu` | `/tmp_updater/not_write_file/nwu` | `BaseKeyTag::isUpdaterSkip @ 0xfe10` → "UpdaterExtract Skip"，**不写更新器自身** |
| `nwl` | `/tmp_updater/not_write_file/nwl` | `us_mkfs.sh` 里 `NOT_WRITE_LOADER` → `fmode="app"` + `uc_pclear -f mount.conf`，**不刷 loader** |
| `uincomp` | `/tmp_updater/updater/current/updater/uincomp`（`UpdaterKeyTag::PreExecute @ 0xfe94` 里 open 创建） | 标记更新器不兼容（配合 `ERROR_UINCOMP=54`） |
| PATH 注入 | `ShellPlugin`：`export EXTRACT_ROOT=/tmp_updater/updater/update; export PATH=/tmp_updater/updater/update/program:/tmp_updater/updater/bodyfs/bin:/usr/bin:$PATH` | **包内 `program/` 目录里的同名脚本会优先于 bodyfs 脚本被执行**（这是不重编 CRAMFS 就能换脚本的官方通道） |
| `config/uconfig.xml` | `XmlConfigHandler::LoadUserConfig @ 0x131ca` | 包可以额外注入一份 XML 配置（本包没有该文件） |
| `mount1.conf` | `edit_mount.sh`（`config/mount1.conf` 追加进 `config/mount.conf`） | 包可以扩展挂载表 |

LED 错误码约定（`getledval.elf 0xNN`，闪光灯闪 N 下报障）：`0x41` 固件无效、`0x42` 机型/LSI 不符、`0x46` Backup.bin 保不住、`0x51/0x52` loader/坏块、`0x61` 分区、`0x62` 逻辑格式化、`0x68/0x69` SPI/genlock、`0x81/0x82` CRC 失败。

---

## 7. 会真正破坏数据的动作（改包前必读）

按 `config.xml` 顺序，一次全量更新实际会做：

1. `keep_big_backup.sh`：`/setting/psd.bin` → tmpfs（`RAMDISK_SIZE=5242880`）
2. `chknandcapa.elf`：读包内 `partinf.conf` 比对真实 NAND
3. `us_mkfs.sh`：`edisx.elf /dev/nflasha partinf.conf`（**重写分区表**）→ `uc_mkfs.elf -m full`（**格式化 nflasha2/3/…**）→ `ud_wbi_drop.elf` → `dosfsck -Y /dev/nflasha2`
4. `part_image`：`PartitionImageKeyTag::Extract @ 0x10b8c` 直接把 `0700_part_image/dev/nflasha{3,5,7,15}` 写进分区（300MB 的 usr、rootfs、WBI、Main）
5. `endupdate.sh`：`ud_lerase.elf /dev/nflasha 4`（**擦 MPR 分区**）、`PRODUCT/VERSKIP` 模式还会 `ud_fsys_format.elf /dev/nflasha24`
6. `loader_writer.sh`（本包未触发）：`pformat.elf /dev/nflashaB0`（**刷 loader + DDR training 数据**）—— 这一步坏了基本等于变砖

所以：**改过的包不要拿去真刷**。当前阶段的一切结论都应从静态分析 + `mode` 旗标（USER/SERVICE/VERSKIP 会跳过大部分破坏性步骤）来推断。

---

## 8. 未解项与建议的下一步（按优先级）

1. **钉死主固件侧的机型比较点**（最高价值）
   `libupdaterufp.so` 的 `set_model/set_region/set_version/firm_*/verskip` 是导入符号，提供方是主 app；已知引用 `libupdaterufp.so` 的是 `lib/libIMDB.so`。
   要回答的是：比较发生在哪个进程、失败时返回哪个错误、`VERSKIP(mode6)`/`SERVICE(mode3)` 分别放宽了哪一项。
   ```bash
   cd firmware.tar_unpacked/0700_part_image/dev/nflasha15_unpacked
   r2 -q -a arm -b 4 -e bin.demangle=true -c "aaa; axt sym.imp.set_model; afl~ufp" lib/libIMDB.so
   r2 -q -a arm -b 4 -c "aaa; axt sym.imp.Dec_ScrambleInit; axt sym.imp.Dec_Scramble" lib/libupdaterufp.so
   ```
2. **钉死 AES 密钥来源**：`KeyArray(32B)` = `SHA256("")` 是占位还是最终值；`Dec_ScrambleInit` 里 key 指针来自 GOT 的哪一个；`crypter.elf` 经 `libosal_uipc` 请求的是哪个服务进程（怀疑与 MPR/nflasha4 有关）。
   ```bash
   r2 -q -a arm -b 4 -c "aa; pdf @ sym.Dec_ScrambleInit; px 32 @ 0x8830" lib/libupdatertalk.so
   ```
3. **解释 `us_darwin_firm.sh` 缺失**：`config.xml` 引用它，但 bodyfs（41 文件）里没有；包内也没有 `program/` 目录。三种可能：(a) 走 §6 的 PATH 注入、由包内 `program/` 提供；(b) 该 proc 因包内 `0640_darwin` 有数据但脚本缺失而真会失败；(c) `darwin_core.bin` 由 `usb_darwin.ko`/其它路径处理。这是验证"key→proc 是否严格按 XML 执行"的最好用例。
4. **`chknandcapa.elf` / `edisx.elf` 的分区表约束**：确认改 `partinf.conf`（分区大小/顺序）是否可行、坏块与 OOB 怎么处理（`ioctl` 语义），这决定"自定义分区"路线是否可行。
5. **`ud_keep_backup.elf` 的 `-p/-s/-r/-u/-w/-n` 语义**：Backup.bin 是唯一承载校准数据的东西，任何实验失败后要能恢复它（`bksb.elf` 从 `/setting/Backup.bin` + `LdrBkupList.txt` 生成 `LdrBkup.bin`）。
6. **确认 KeyTag 表匹配的精确语义**（整段 vs 前缀）：`GetKeyTag @ 0x11338` 里用 `'/'` 位置做边界，倾向"整段目录名比较"；若要 100% 确认，反汇编 `StringHandler` vtable+0x1c 的实现（在 `libupdatercommon.so` 里，通过 `.rel.dyn` 定位 vtable 槽位）。

**一句话结论**：更新器侧确实是 `config.xml → shell/run 脚本 → ELF 工具 → 分区/固件组件` 这条链，而且**没有签名**（只有 CRC32+size）；但它外面有一层"机型/区域/版本 + chassis 专属 AES 加密"的门禁，而且链路上多处是擦写分区的破坏性操作。所以现在这轮静态分析的正确用法是：先把 §8 第 1、2 项查清楚，再谈"能不能改包"，改的时候优先用 §6 的官方旗标（`nwu / nwl / mode6 / program/ / uconfig.xml`），别动 `part_image` 和 loader。

---

## 附录：本次用到的复现命令

```bash
# 1. 校验 .sum（证明只有 CRC32+size）
python3 tools/verify_sums.py

# 2. updater.img 与固件自带更新器是否相同
cmp updater.img firmware.tar_unpacked/0700_part_image/dev/nflasha15_unpacked/bin/udtrbody.bin

# 3. 反汇编 libupdaterbody.so（Thumb-2；vaddr==paddr）
r2 -q -a arm -b 4 -e bin.demangle=true -e scr.color=0 -c "aa; afl" updater.img_unpacked/bodylib/libupdaterbody.so
r2 -q -a arm -b 4 -e bin.demangle=true -e scr.color=0 -c "aa; pdf @ 0x11338" updater.img_unpacked/bodylib/libupdaterbody.so
# pc 相对字面量池注释不可靠时，用本目录 /tmp 下的 annot.py 风格脚本手工算 val + (addr_of_add + 4)

# 4. CRC 校验器行为
strings -a updater.img_unpacked/bin/uc_crc32sum.elf | grep CRC32SUM

# 5. 主固件侧门禁
strings -a firmware.tar_unpacked/0700_part_image/dev/nflasha15_unpacked/lib/libupdatertalk.so | grep -E "Scramble|AES|Key"
grep -nE "mode[0-9]?|modmod|modreg|modver" firmware.tar_unpacked/0700_part_image/dev/nflasha15_unpacked/bin/up.sh
```
