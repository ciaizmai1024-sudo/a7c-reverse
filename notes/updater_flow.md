# A7C 一代（CXD90045, v2.00）更新链与模式系统 —— 包内可静态证实的部分

本轮把**更新包自带的 updater 代码/脚本**全部读完（`updater.img` = `/usr/bin/udtrbody.bin`，与
`0700_part_image/dev/nflasha15_unpacked/bin/udtrbody.bin_unpacked/` 同一内容的两次解包）。
下面每条都给**文件+行号**，标【代码证实】= 直接读到的；【推断】= 由这些事实推的；【未定】= 仍然缺证据。

> 与旧文档的关系：`TEST_LADDER.md` 把 `modeType='O'`/VERSKIP 当成"同版本重刷的唯一出路"，
> 本文推翻了这个前提（见 §3、§4）。

## 1. 谁是执行体（一代的实际分工）

| 分区 | 内容（本包实测） | 在更新链里的角色 |
|---|---|---|
| nflasha1（vfat 8,323,072 B） | **包里没有镜像**；`up.sh` 用 `mount -t vfat /dev/nflasha1` 读写它 | 放 `dat2`(机型码)/`dat3`(区域码) + boot 文件（kernel/initrd，待 dump）【未定】 |
| nflasha3（/system, vfat，包内 30,290,944 B） | `vmlinux.bin`、`initrd.img`（已解包）、`av-cam.bin`、`dfe_app.bin`… | 正常启动的 kernel+initrd；**initrd 里的 `sbin/init` 是启动总调度**（§6） |
| nflasha5（/wbi，32,577,024 B）、nflasha7（/rootfs raw，4,992,000 B） | nflasha7 里有 `bin/busybox`、`sbin/init`(ELF)、`kmod/{ldec,emmc,nand,lld,dmac,devno}.ko`、**`/root/chassis` = `CXD90045`**、`/root/common.src` | **更新环境的 rootfs**（`chassis` 就是 crypter.elf `0xbde4` 比对的来源）【代码证实】 |
| nflasha15（/usr raw，239,982,592 B） | `bin/{im.elf,sen.elf,bootin.elf,crypter.elf,up.sh,change_mode.sh,launch_shell.elf,ud_datcnv.elf,ud_send_lsi.elf,udtrbody.bin,…}`、`lib/libupdater{ufp,common,ufunc,talk,media}.so` | 更新体本体 + 更新脚本 + 正常模式服务通道 |
| nflasha4（raw 12 MB，"MPR Flash Backup"） | 包内无镜像 | **每次更新的 endupdate 都会擦它**（§5）【代码证实】 |
| nflasha13（4 MB UpdaterWork）/ nflasha23（2 MB PMBP）/ nflasha24 | 未挂载 / 有挂载点 | `endupdate.sh:21-22` 把 a23 当 `FSYS_WORK`、a24 当 `USER_STORAGE`（仅 PRODUCT/VERSKIP 格式化）【代码证实】 |

`libupdaterufp.so` 只有 **12,936 B**（`.text` 5.8 KB、`.bss` 64 KB）——它只是**门面/门禁**；
真正的解析在 `crypter.elf`（39 KB），干活在 `udtrbody.bin → bodylib/libupdaterbody.so`（106 KB）+ 脚本。

**已核**：Mac 应用自带的 `updater.img`（143,360 B）与相机自己的 `/usr/bin/udtrbody.bin` **逐字节相同**（`cmp` 通过），
两份解包目录也完全一致 ⇒ PC 端带着与相机一样的更新体（serial/LDUDWRT 路径下由 PC 供给）【已验】。

## 2. 包内 `config.xml` = 更新作业表（一代，逐行）

`updater.img_unpacked/config/config.xml`（60 行）里每个 `<proc key="…">` 对应包内一个段：
`us_crc32sum.sh` 先按 `*_sum/<name>.sum` 验 **CRC32+size**，然后跑对应脚本：

| key | 脚本 | 本包是否有该段 |
|---|---|---|
| `config_sum/config.sum` | `us_crc32sum.sh` + **`chkfirm.sh`** + `edit_mount.sh` + `keep_big_backup.sh` | ✔ 0100_config |
| `partconf_sum/partconf.sum` | `us_crc32sum.sh` + **`us_mkfs.sh`**（分区/格式化，§4） | ✔ 0300_partconf |
| `part_image_sum/part_image.sum` | `us_crc32sum.sh`（image 模式） | ✔ 0700_part_image（**只有 nflasha3/5/7/15**） |
| `backup_sum/backup.sum` | `us_crc32sum_backup.sh` | ✔ 0110_backup（30 MB，`SYSASTRA-DSLR/NB_HIBIKI2/CH8860{0,1}_*.bin`） |
| `appli_sum/appli.sum` | `us_crc32sum_appli.sh`（顺带恢复 dat2/dat3/dat4 + `touch mode mode6`，见 §3） | ✔ 0800_appli（4 MB 镜头文件） |
| `darwin_sum/darwin.sum`, `prfile_sum/prfile.sum`, `ca_sum/ca.sum`, `genlock_sum/genlock.sum`, `gps` | `us_darwin_firm.sh` / `ul_crc32sumprfile.so` / `us_ca_firm.sh` / `us_genlock_firmup.sh` | darwin 224KB、prfile 960KB(PMBP)、ca/genlock/gps 为**空段** |
| `loader_sum/loader.sum` | `us_crc32sum.sh` + **`loader_writer.sh`** → `pformat.elf /dev/nflashaB0` | **✘ 本包没有 loader 段 ⇒ 不动 loader**【代码证实】 |
| `front_sum`, `furud_sum`, `accsy_sum` | `us_front_firmup.sh` / `us_spi_firmup.sh` | ✘ 没有（前板/SPI 侧不碰） |

⇒ **一代包里能看到的完整性检查只有 CRC32+size（`uc_crc32sum.elf -c`）与 DEND/帧/头 CRC。**
在 `nflasha3/5/7/15` + `updater.img` 全量字符串搜索里，**没有任何** `N7Updater*Signature*` 修饰名、
`VerifySignature`（只有蓝牙 GATT 的 `BTM_BleVerifySignature`／`"Signature Verification Failed, data ignored"`，
在 `bin/bsa_server`，属 BT 栈）、`VerificationKey`、`pub.key`。【代码证实：搜索范围与命中列表见 §7】

**仍然未知**：nflasha1 里的 boot/initrd 侧（`mf`/`sauu`/`UdtrMain.sh` 一代是否同名存在）——
`pformat.elf /dev/nflashaB0`（loader=eMMC boot 分区）与 `p1chksum` 类自检只能从 dump 得到。

## 3. ★更新模式不是"只能靠包头字母" —— 模式由 `/setting/updater/mode*` 旗标文件决定

`nflasha15_unpacked/bin/up.sh`（一代自有，路径就在可写的 /usr 里）：

| `up.sh` 参数 | 旗标动作（行号） | 打印的下一步模式 | `ud_send_lsi.elf` 的 mode_num |
|---|---|---|---|
| 无参数 | 有 `mode` 就 `rm -f $UPDIR/mode*`，否则 `touch mode mode1`（`:240,246`） | Updater mode | 4（`:250`） |
| `user` | `rm mode*; touch mode`（`:18,21`） | UFP mode | 2（`:266`） |
| `serv` | `touch mode mode3`（`:81`） | Service mode | 3（`:270`） |
| `ver` | `touch mode mode6`（`:41`） | **Version Skip** | 6（`:286`） |
| `ms` | `touch mode mode5`（`:61`） | **MS Crypt（SD 卡）** | — |
| `keep`（注释掉） | `touch mode mode1 mode4`（`:102`） | Keepbackup | — |
| `modver <4位>` | `ud_datcnv.elf -d/-e` 读改 **`/setting/updater/dat4`**（`:128,139`） | 改"更新器认为的当前版本" | — |
| `modmod/modreg <8位>` | `mount -t vfat /dev/nflasha1` + `ud_datcnv.elf` 改 **`/mnt/dat2`/`/mnt/dat3`**（`:188,194,207`） | 改更新包匹配用的机型/区域码 | — |

**★`dat2/dat3/dat4` 到底是什么格式：已用相机自己的 `ud_datcnv.elf` 在 arm/v7 容器里实跑讁实**（详见 `work/DATCNV_RESULTS.md`）：
- `-a` 模式（`up.sh` 用的就是这个）：每个字符取**低半字节**（'0'-'9'→0-9，'.'→0xE），两字符一组打包成字节，**再小端存放**；输出长 = `⌊len/2⌋` 字节。
  实测：`"0200"`→`00 02`；`"91030019"`→`19 00 03 91`（**与 FDAT 头 `+36 model=0x91030019` 的小端字节完全一致**）；`"00000000"`→`00 00 00 00`。
- **无 magic、无头、无长度字段、无任何校验**（改成 `ff 02` 也能解，只是解出乱码）⇒ 手写的 dat 与工具产物逐字节相同。
- 硬限制（唯一的坑）：输入 **>8 字节 / >16 字符 → rc=0 但输出 0 字节（静默写空）**；dat4=2 B、dat2/dat3=4 B 均在限内（`up.sh` 也强制 modver 4 字符、modmod/modreg 8 字符）。
- 注意：版本文本存的是 **`"0200"` 而不是 `"2.00"`**（后者会被编成 `00 2e`，且 `-d -a` 解回 `2>00` 不往返）；
  ⇒ **ZV-E10 的“dat4 裸写 `00 00` → 相机报 0.00”对 A7C 同样成立**（= 文本 `"0000"`）。
| `us_remove_modes.sh` | `rm -f /setting/updater/mode*` | **撤销"下次进更新模式"** | — |

`us_crc32sum_appli.sh`（`appli` 段的后处理，`updater.img_unpacked/bin/`）额外做了两件重要的事【已验逐行】：
- `if [ -e /ramdsk/dat4 ]` → **挂 `/dev/nflasha1` 到 `/mnt` 后 `cp /ramdsk/dat2 /mnt/`、`cp /ramdsk/dat3 /mnt/`、`cp /ramdsk/dat4 /setting/updater/`**
  ⇒ **更新器 ramdisk 里带着 `dat2/dat3/dat4` 的原始副本**，机型/区域/版本身份能被官方链路自己恢复（`modmod/modreg/modver` 写错不是不可逆）；
- 紧接着 **`touch /setting/updater/mode` + `mode6`** ⇒ 跑过 `appli` 段后下次会**以 Version Skip 模式进更新模式**（这就是“改镜头文件也会触发一次 verskip 重建”的原因，`TEST_LADDER.md` 里要防这条）。

SD 卡更新路径在一代代码里存在【已验字符串/类名，能否用未验】：`nflasha7/root/common.src` 有
`MS_MOUNT_POINT=/mnt`、`DATSRC_SENSER=0 DATSRC_MS=1`；`crypter.elf` 里有 `Updater::MsDecryptorModule`、
`Updater::MsCryptBufferManager`、`/dev/mmca`、`/dev/ms`、字符串 `"fdat"`/`"chunk="`；
`up.sh ms` 置 `mode mode5`（MSCRYPT=6），`us_mkfs.sh` 对 MSCRYPT 与 USER 同走 `fmode=app`、不跑 edisx。

`crypter.elf` 侧对应类：`ModeFlagFile`/`Mode1/2/3/5/6FlagFile`（`CurrentFirmware.cpp`，挂载
`/dev/nflasha1`@0xd750、`/dev/nflasha2`@0xd6dc 读 `dat2/dat3/dat4` 与旗标）【代码证实：符号+字符串】。
两套编号并存，别混：
- `nflasha7/root/common.src`：`MODE_USER=0 MODE_PROD=1 MODE_SERVICE=2 MODE_MINOR=3 MODE_VERSKIP=6`
- `updater.img_unpacked/bin/us_mkfs.sh:12-19`：`PRODUCT=1 LOADER_UPDATER=2 USER=3 SERVICE=4 MINOR=5 MSCRYPT=6 VERSKIP=7`
旗标文件编号（mode1/3/4/5/6）与脚本里的 `UPDATER_ACTION_MODE` 编号不是一回事。【已证实两套存在；精确映射仍需上机或反汇编 `CurrentFirmware`】

**UFP（USB）路径只允许 `modeType` = 'U'/'O'**（`libupdaterufp.so` 0x1b8c/0x1c00，`notes/updater_verify.md` §已验），
所以"'M'(MINOR)/'P'(PROD) 包"在 USB 路线上会被拒【已验】；但**模式旗标文件是另一条腿**，
写在 `/setting`（nflasha2 vfat，正常模式下可写）。

## 4. `us_mkfs.sh`：谁重写分区表、谁只重建 app

`updater.img_unpacked/bin/us_mkfs.sh`：
- `:39-47`：`SERVICE|USER|MINOR|MSCRYPT` → **不跑 edisx**；其它（含 VERSKIP、PRODUCT）→ `updater_storage_backup.sh` →
  **`edisx.elf /dev/nflasha partinf.conf`（重写分区表）** → `updater_storage_restore.sh`。
- `:55-77`：`fmode`：`PRODUCT/LOADER_UPDATER` → `full`（有 `/tmp_updater/not_write_file/nwl` 则 app）；
  `SERVICE/USER/MINOR/MSCRYPT` → **`app`**；`VERSKIP` → **`full`**；
  然后 `uc_mkfs.elf -m $fmode -f mount.conf`（失败 `getledval 0x62`）。
- `:78-88`：挂 `/setting` → **`ud_keep_backup.elf -s` 恢复 `Backup.bin`**；`:90` `ud_wbi_drop.elf partinf.conf`；
  `:110/113` 写 `/setting/sen/smode = "UU"`；非 app 路径还会 `dosfsck -Y /dev/nflasha2`。
⇒ 结论：**MSCRYPT(6)/MINOR(5)/SERVICE(4)/USER(3) 都不动分区表**；只有 `VERSKIP/PRODUCT` 才 edisx+full。
之前把"同版本重刷"只能绑到 VERSKIP 是错的 —— **`up.sh serv`(mode3) 或 `ms`(mode5) 也是候选**。【代码证实】

`0100_config/mount.conf`（一代实测，含类型与大小）给出精确爆炸半径：
`a1 vfat 8323072 / a2 /setting vfat 20971520 / a3 /system vfat 50331648 / a4 raw / a5 /wbi wbi /
a6 vfat 16777216 / a7 /rootfs raw / a10 /tmp vfat / a11 /log vfat / a12 /cert vfat / a13 vfat /
a15 /usr raw 314572800 / a16 /android/system raw 146800640 / a17 /android/data vfat /
a18 /lens vfat / a23 /PMBP prfile 2097152 / a24…a30 size 0`
（`partinf.conf` 里 a16=140MB "Android(system)"、a17=100MB "Android(data)"、a23=2MB "PMBP" ——
与 ZV-E10 的 140MB 空白试验田**编号一致但用途标注不同**，别照抄 camtool 的"全零 scratch"结论）【代码证实】

## 5. USER 模式并不"温和"到什么都有：`endupdate.sh` 的实际动作

`updater.img_unpacked/bin/endupdate.sh`：
- `:62-70`：USER/SERVICE/MINOR/MSCRYPT → `ud_get_uudtype.elf` 决定是否 `-r`(不重置 userdata) 或 `-u`(重置)，其它模式 `-w`；
- `:77-79`：包内 `backup/*/*/*.bin` 存在则 **覆盖 `/setting/Backup.bin`**（本包有 30 MB 这类文件）；
- `:81` `ud_keep_backup.elf $BACKUP_OPT` 回写备份；
- `:94` **`ud_lerase.elf /dev/nflasha 4`：每次更新（除 serial 下载模式）都擦 nflasha4（MPR）**，失败 `ERROR_MPR_ERASE=45`；
- `:97-101`：只有 `PRODUCT/VERSKIP` 才 `ud_fsys_format.elf /dev/nflasha24`（用户存储）。
`startupdate.sh` 则 `updater_storage_mount.sh` + `ud_keep_backup.elf -p /ramdsk`（先保 `Backup.bin`）。
⇒ **`/setting/Backup.bin`（nflasha2）+ nflasha4(MPR) 是这套更新的可回退基础**；`loader_writer.sh` 更明确：
写 loader 前用 `bksb.elf /setting/Backup.bin LdrBkupList.txt LdrBkup.bin` 先做 loader 备份。【代码证实】

## 6. 反砖/调试面（一代也在包里，不依赖 Jiritsu）

`nflasha3` 的 `initrd.img_unpacked/sbin/init`（未 strip，带 debug_info）里可见：
- 挂载序列 `/dev/nflasha2→/setting`、`/usr` **依次试 ext2 → ext2 no-compress → cramfs → vfat**，
  `/system` 试压缩 → vfat；还会试 `dnflasha3/dnflasha15/dnflasha7`（双读设备）、`/dev/nflasha9→/usr/upgrade`。【代码证实】
- 读 **`/setting/mode/dmode`**、`/setting/env.txt`、`/setting/sen/smode`、`/proc/udm/upm_bootmode`，
  并 `putenv("LD_PRELOAD=…")`（`/usr/tool/libkmcsup.so.2.0.0`、`libsonyefence.so`、`libduma.so`），
  起 `/usr/bin/bootin.elf`、`/usr/bin/sen.elf`、`/usr/bin/net_cmdd.elf`，失败则 `launch_shell() failed` + `/bin/ash --login`。【代码证实】
- `nflasha15_unpacked/bin/change_mode.sh`：**写 `/setting/mode/dmode` + `/setting/mode/preload`**，
  支持 0–6（只到 kernel / 只起 infra / 起 LIRO / 起 appFw=默认 3）、`3g/3s`(target gdb/gdbserver)、`7/8/9/d/e/f/10`（LeakTracer/eFence/jemalloc/mcheckb）、
  以及 **`p <lib>` = 任意 preload 路径**；结尾"Please reboot your system."。【代码证实】
- `/usr/bin/launch_shell.elf`：在 **`/dev/ttycons`/`/dev/console`** 上 `setsid`+`execv /bin/ash --login` 的 shell 循环（含 `do_freeramdisk`）。【代码证实】
- 与 A7C II 的差别：一代 `change_mode.sh` **没有** `development.txt`→串口打开那段；`console=` 由 `/setting/kemco.txt` 决定（A7C II 实测是 `ttynull0`），一代的 `kemco.txt` 位置在未 dump 的 nflasha1 里【未定】。

⇒ 建议把「`/setting/mode/dmode`（起多少东西）+ `/setting/mode/preload`（Sony 自家机制的 preload）+ `us_remove_modes.sh`（撤销进更新模式）」
当作**低于 Jiritsu 层的救援阶梯**；比 `TEST_LADDER.md` 里担心的 `/etc/ld.so.preload` 安全得多（是固件自带机制、且文件在 /setting，USER 模式更新也不会重建 /setting）。【推断】

## 7. FDAT 尾 272 B 的本轮离线结论

`tools/fdat_tail.py`（本轮新写）实测：
- FDAT 记录 = `0x14a2b110` B = **338,092 × 1024 块 + 272 B**；这 272 B **在 FDAT 记录内部**，
  因此被容器尾 `DEND` 的 CRC32 覆盖：`crc32(文件[0:size-12]) = aaaa81b8` = 存的值 ✔【已验】（旧脚本 `fdat_unwrap.py` 的范围差 8 字节，已澄清）。
- 尾 = 16 B IV(`13efb6a3…`) + 256 B blob（熵 7.18/8、无 `00 01 FF…00` 明文结构、无 0xFF 填充）⇒
  外观符合"密文/签名值"，不符合明文。【已验（统计）】
- `fwtool` 上游源码（`/tmp/gh/sony-a7c2-research/fwtool/sony/fdat.py`）里 `AesCbcCrypter.decrypt()`
  取最后 0x110 B 的**前 16 B 当 IV**，`FilePart(file, 0, size)` **直接丢掉其余 256 B**，
  且照样解出 `UDTRFIRM` 魔数 ⇒ **这 256 B 不是解密载荷所必需的**；同一文件还给出 `CXD90045_k0/_k8` **两把** CBC 密钥（我们用的是 k0）【已验（上游代码）】
- 一代包内所有可用模块（`libupdater{ufp,ufunc,talk,common,media}.so`、`crypter.elf`、`libupdaterbody.so`）
  反汇编扫 `'U'/'O'/'M'/'P'/'N'` 立即数：只有 `libupdaterbody.so:0xe349 adds r0,#0x4e`('N') 一处相关命中，
  **没有任何 modeType/签名字节比较**；`0x110` 也没被引用（`notes/updater_verify.md` §已验一致）。【本轮已验】
⇒ 合理解释：256 B 是**给 LDEC 硬件/更新器用的认证或密钥块**（nflasha7 有 `kmod/ldec.ko`：
`boss_hw_ldec_set/process/wait`，dump 变量只有 `srclen/dst_phys/dstlen/records/ch/…`，没有密钥参数 ⇒ 密钥在 SoC 内/OTP）【推断】；
是否被验、被谁验，仍只能等 nflasha1（或其 `mf`/initrd）dump。【未定】
另注：`nflasha7_unpacked/root/chassis` = `CXD90045`（9 B）就是 crypter.elf `0xbde4` chassis 比对读的文件【已验】，
改包/改 rootfs 时别动它。

## 9. ★门禁代码就在可写的 /usr 里 —— 不刷包也能改它（本轮新发现）

`nflasha15_unpacked/lib/libIMDB.so` 里有成名的插件表：`("libupdaterufp.so", "udtr_ufp_init", "udtr_ufp_exit")`
（同表里还有 `libupdatertalk.so`/`libupdatermedia.so`/`libInfraUpdaterDPro.so` 等）。`libIMDB.so` 的 `DT_NEEDED` 里**没有** `libupdaterufp.so`（只有 libc/libstdc++/libdl…）
⇒ 它是**按名字 dlopen** 的【已验】。而那个 dlopen 的库就是包住全部身份门禁的库：
`model/region/version` 比较（`0x127c`）、`modeType` 只允 'U'/'O'（`0x1b8c`）、verskip（`0x1c00`），
然后才 `stm_system("/usr/bin/crypter.elf", …)` 与 `up.sh user|ver|ms`。

推论（【推断】，未上机）：`libupdaterufp.so` 在 **nflasha15（本次更新会重写的 app 分区）**上，所以下面两个能力同时成立：
1. 把它“整分区 dump → 本地改 → 整分区写回”就能改掉门禁（版本/区域/modeType 限制），**不需碰 boot、也不需刷 .dat**；
   写坏它只会让 `im.elf` 起不来（更新器仍可重建 a15）。
2. 改完可以用**原包原版**（不改任何头字段）做一次 USER 刷来恢复 → 与二代的 `appFw.so` 战术同构。
   风脸的是“im.elf 一直 crash ⇒ 只能靠更新器重建”，而更新器重建要过 `0x142` 同版本拦拦——先 `up.sh modver` 可解。

附：`libIMDB.so` 共引用 177 个 `.so`，其中 **105 个不在本包 /usr/lib**（包括 `appFw.so`、`gui.so`、`subapp.so`、`AppConfig.so`、
`libJiritsuUIView.so`、`libInfraUpdaterDPro.so`、`libTestDriver.so`）——这张表是**跨机型共用表**，缺项只会 dlopen 失败（日志可见）【已验：文件存在性 + 表内容】。
⇒ 一代确实没有 `appFw.so`（不是解包丢了），但 `libupdaterufp.so`/`libupdatertalk.so`/`libupdaterufunc.so`/`libupdatermedia.so` 四个更新相关库**都在包内**。

## 11. ★包内容 ↔ 写入目标（A7C 2.00 实测，全部是包里的实物）

注：`config.xml` 不是固件包里的，而是 **PC 自带更新体（`updater.img` → `config/config.xml`）**里的作业表；
固件包只提供它引用的**编号目录**（数字前缀 = 执行顺序）【已验：两处文件对比】。

| 包内目录 | 内容 | 作业（config.xml） | 写到哪 |
|---|---|---|---|
| `0100_config/` | `mount.conf`、`big_backup.conf`（**只有一行：`/setting/psd.bin`**） | `us_crc32sum.sh "config file"` + `chkfirm.sh` + `edit_mount.sh` + `keep_big_backup.sh` | mount.conf → `/setting/mount.conf`；big_backup 只在 PRODUCT/VERSKIP 时把 `psd.bin` 拷进 5 MB tmpfs |
| `0110_backup/` | `MainDest.txt`（`SYSASTRA-DSLR`/`NB`/`CX88600_UC2.bin`）+ `SYSASTRA-DSLR/…` | `us_crc32sum_backup.sh "backup file"` | `/setting/Backup.bin` 一路（会先校 `ls $UPDATE_BACKUPBIN` 必须恰好 1 个） |
| `0300_partconf/` | **`partinf.conf`（4,017 B，就是分区表）** | `chknandcapa.elf partconf/partinf.conf` → `us_crc32sum.sh` → **`us_mkfs.sh`** | 只在 VERSKIP/PRODUCT 才真改盘（§4） |
| `0600_gps/`、`0630_ca/`、`1030_genlock/` | **空目录** | `us_ca_firm.sh`/`us_genlock_firmup.sh` 等 | 本包无内容 ⇒ 不动 /cert、genlock |
| `0640_darwin/` | `darwin_core.bin` | `us_darwin_firm.sh darwin`（thread） | darwin 引擎区（`/dev/nflasha?`）【目标未定】 |
| `0650_prfile/` | `PMBP/LICENSE/…` | `ul_crc32sumprfile.so`（run，非 shell） | PMBP（`nflasha23` 2 MB） |
| `0700_part_image/` | 只有 **`dev/nflasha{3,5,7,15}`** 四张镜像 | `us_crc32sum.sh "part_image image"` | `uc_mkfs -m app` + 写回 a3/5/7/15 |
| `0800_appli/` | **57 个 `lens/VX*_lensfile.bin`（共 360 KB）**、`setting/{DmmConfig.bin 78 KB, facedmy.bin 50 KB, kemco.txt 1.9 KB}`、`tmp/{images/*.ltt,*.ttf、toprc、nsswitch.conf、protocols、services、config.spec}` | `us_crc32sum_appli.sh appli`（顺带恢复 dat2/3/4 + `touch mode mode6`） | `lens/` → `/lens`(a18)；`setting/` → `/setting`(a2)；`tmp/` → **`/tmp`≡`/etc`(a10)**（那些 nsswitch/protocols/services 就是网路栈的 /etc 文件） |

**机制细节（本轮读完整 `us_crc32sum_appli.sh`）**：它开头 `umount /ramdsk/updater/update/appli_sum/setting`，
再 `mount -t vfat /dev/nflasha2 /ramdsk/updater/update/appli_sum/setting` ⇒ **把机身的 /setting 挂进解包目录里**，
然后 `cd appli_sum && uc_crc32sum.elf -c appli.sum`【已验脚本】。`appli.sum` 共 74 条：**57 条 `lens/` + 4 条 `setting/` + 10 条 `tmp/`**【已验】。
⇒ 同一个相对路径既能读到包里那份、也能写到机身那份；但“只校包内 / 还是连机身现有文件一起校”【未定】。两种后果先记：
- 若校机身：我们改了 `/setting/kemco.txt` 之类后，官方更新 `appli` 段可能 CRC 不过（LED `0x82`）⇒ 刷前要把出厂版放回去；
- 若只校包内：改 /setting 文件不影响下次官方刷 ⇒ 风险小得多。
要定这个只需读 `uc_crc32sum.elf`（在更新体里，已在手）【待做】。
好消息是**包里自带出厂版原件**（`kemco.txt`/`DmmConfig.bin`/`facedmy.bin` + 5 个 /etc 文件 + 57 个 lens 文件）
⇒ 天然有一套字节正确的出厂参考：既能 diff 机身内容，也能 byte-exact 还原【已验】。

**本包没有的段**（与 config.xml 对比）：`updater`、`loader`、`front`、`accsy`、`furud`、`gps`、`ca`、`genlock` 均无内容/无镜像
⇒ **官方更新不会写 nflasha1（更新器区）、不会写 loader（`loader_writer.sh`）、不会碰外扩 SPI**【已验：目录实物】。

### 权威分区表（`0300_partconf/partinf.conf`，格式 `start,size,type,flag`）

```
a1  0x00010000 0x007F0000  7.9375MB System(Updater)      ← = 8,323,072 B（真机 dump 长度与此完全对上）
a2  0x00800000 0x01400000      20MB System(Setting)
a3  0x01C00000 0x03000000      48MB System(Main)
a4  0x04C00000 0x00C00000      12MB MPR Flash Backup
a5  0x05800000 0x03C00000      60MB Warm Boot Image
a6  0x09400000 0x01000000      16MB Jiritsu
a7  0x0A400000 0x00800000       8MB Rootfs
a10 0x0AC00000 0x00C00000      12MB Work
a11 0x0B800000 0x1F400000     500MB Log
a12 0x2AC00000 0x02800000      40MB Network  (mount.conf: /cert vfat)
a13 0x2D400000 0x00400000       4MB UpdaterWork (vfat, 默认不挂)
a15 0x2D800000 0x12C00000     300MB usr (raw → /usr)
a16 0x40400000 0x08C00000     140MB Android(system)
a17 0x49000000 0x06400000     100MB Android(data)
a18 0x4F400000 0x01400000      20MB LensData (/lens)
a23 0x50800000 0x00200000       2MB PMBP
```
a8/a9/a14/a19-a22/a24-a30 size=0（保留）。整个映射到 `0x50A00000` ≈ **1.29 GB**。

**包内镜像长度 ≠ 分区长度**（写回时要的是分区长度，不是镜像长度）：

| 设备 | 分区（mount.conf/partinf） | 包内镜像 | 差 |
|---|---|---|---|
| nflasha3 | 50,331,648 | 30,290,944 | -20 MB |
| nflasha5 | 62,914,560 | 32,577,024 | -30 MB |
| nflasha7 | 8,388,608 | 4,992,000 | -3.2 MB |
| nflasha15 | 314,572,800 | 239,982,592 | -71 MB |
| nflasha1 | 8,323,072 | **包里没得** | 只能从机身 dump |
| nflasha6 | 16,777,216 | **包里没得** | 同上 |

另：`chknandcapa.elf partconf/partinf.conf`（在更新体里，非根文件系统）会用包里的 partinf 去校 NAND 容量；
而 `mount.conf` 里的 `PartitionSize` 列就是相机自己的分区尺寸 ⇒ **L1 拉回 `/setting/partinf.conf` 与包内这份 diff，能直接看出机身表与包表是否一致**（不一致 ⇒ VERSKIP 会重划盘）。

### ⇒ 一次普通 USER 更新实际碰到的分区（八个）

整段重建：`nflasha3`(/system)、`nflasha5`(/wbi)、`nflasha7`(/rootfs)、`nflasha15`(/usr)（`uc_mkfs -m app` + 写 part_image）；
**文件级**写入：`nflasha2`（`DmmConfig.bin`/`facedmy.bin`/`kemco.txt` + `mount.conf` + `partinf.conf` + `updater/dat4` 恢复）、
`nflasha10`（`/tmp≡/etc`：`nsswitch.conf`/`protocols`/`services`/`toprc`/UI 字体）、`nflasha18`（`/lens` 里 57 个 `VX*_lensfile.bin`）、
以及每轮收尾必擦的 `nflasha4`（MPR）【已验脚本】。
⇒ **L4 备份不能只备整分区**：上面这些**文件**也要拉一份（尤其 `/setting/kemco.txt`——串口控制台开关就在那，
`TEST_LADDER` 里“一代 kemco.txt 未 dump”这一项现在可以从包里读到样值，但机身上的实际值仍要从相机拉）。
⇒ 包里没有 `updater`/`loader` 段 ⇒ 官方刷不会碰 `nflasha1` 与 boot loader【已验】。

### ★`/setting/kemco.txt` = 内核 cmdline（串口开关就在这个文件里，而它是官方更新会写的文件）

包里出厂版（`0800_appli/setting/kemco.txt`，1,905 B）实测包食：
`ramdisk_size=8192`、`rootfstype=ext2 root=/dev/ram0 init=/sbin/init initrd=0x700000,8M`、
`mem=1G@0` + `mem=256M@0x80000000@1` + 一串 `memrsv=`、`cmpr.path=/system/sabin/ssboot.bin`/`cmpr.path2=/system/sabin/ssboot_any.bin`、
`wdt.timeout=500 xrstreq=1 wdt.mode=1`、`klog.addr=0x035A5000 klog.size=0x20000`、`alog.addr=0x03524FC0`、
`cfg.uart=9`、`exception.console_option=115200n8`、**`console=ttynull`**、`em_console=0x200210ec`、`error.led=0,0`。
【已验：文件内容】

- ⇒ **一级引导的二级阶局在 `/system/sabin/ssboot.bin`（= nflasha3，官方 USER 刷会重写它）**，不在只有 `pformat.elf` 能碰的 boot0/boot1 里【已验：路径字串在包里】。
- ⇒ **串口无输出不是硬件问题而是 cmdline 问题**：同芯片同代的 ZV-E10 实测过“kemco 里 `amba2.console=0` → 无输出，改 1 → 有输出”
  （`refs/zve10-qemu/docs/QEMU_BOOT_PROGRESS.md:17673`、`:224`）；A7C 出厂版里没有 `amba2.console`，而是 `console=ttynull` + `cfg.uart=9`
  ⇒ **候选开关应当是 `console=` 的写法（或 `cfg.uart`），具体名字【未验】**。
- 诱人的地方：`/setting` 是 vfat，而 `FileControl(0xff01)` 能按**文件**写（不需整分区写、不需代码执行）
  ⇒ “改一个文本文件换来串口日志/控制台”理论上可达；但风险不对称：
  kemco 写坏 ⇒ 内核起不来 ⇒ 相机自己的 FileControl/更新链也没了（只能回到 L7 的 BootROM 串行），
  所以它是“比 `dd nflasha15` 轻、但比改 `dat4` 重”的一级，**呰前必须先 dump 原文件并确认能写回**【推断】。

## 12. 两层密码的 key 到底在哪（本轮实测）

- **ECB 层（512 B 头）的 key 就在软件里**：`e3b0c442 98fc1c14 9afbf4c8 996fb924`（= `SHA256("")[:16]`）
  以**裸字节**存在 `nflasha15_unpacked/lib/libupdatertalk.so` 文件偏移 **0x830**（全包只这一处）【已验】。
  ⇒ 该库在 **可重建的 nflasha15** 上，换/patch 它就等于换 ECB key。
- **CBC 层（载荷）的 key+IV 全包内 0 命中**：`key_cxd90045`（`c1aa8f7c…d303e06b`，含拆成 k0/k8 两半）与 IV `13efb6a3…` 在
  `nflasha15`（239,982,592 B）、`nflasha3`、`nflasha5`、`nflasha7`、`updater.img` 里全部找不到【已验：全镜像字节搜索】
  ⇒ **CBC 不是软件实现的**（与 `crypter.elf` 不链 crypto、`ldec.ko` 里也没有 key 字串相吻合）：
  它是 **BOSS 芯片里的 LDEC 硬件 DMA 解密器**，key 在芯片/OTP 里；我们手里的 `key_cxd90045` 是前人 dump 出来的公开值。
- `ldec.ko`（initrd 里，15,840 B，proprietary，vermagic 3.0.27_nl-rt106+ ARMv7）的导出面：
  `boss_hw_ldec_{set,process,wait,lock,stop,get_state,resource_init}`、`ldec_ioctl`、`ldec_get_user_pages`、`ldec_dma_set`；
  dump 字段只有 `srclen / dst_phys / dstlen / records / ch / xsrcflush / xdstflush` ⇒ **描述符只带地址/长度/记录表，不带 key**。
  报错链：`ldec_dma_start err. status` / `boss_hw_ldec_wait err. status = %d`（+ `lld_ldec_int_cond` 寄存器转储）。
  ⇒ **推论【未验】**：如果尾 272 B 是硬件认证/密钥包装，失败会以 `boss_hw_ldec_wait err status=…` 的形式出现在日志里，
  而不是 `crypter.elf` 的 CRC 报错 ⇒ 正好就是 §7 那个“翻 CBC 区 1 字节”探针要区分的两种结果。
- 实用推论【推断】：拿到代码执行后，用户态可以自己 `ioctl` 这个 `/dev/ldec*` 设备用**片内 key** 加/解任意数据
  ⇒ 那是路线 A（自制 .dat 重加密）最现实的执行手段，比逆向出 key 更可行。

## 14. ★★解密后的 FDAT 内部结构（本轮实测，路线 A 真正要重造的东西）

把 `/tmp/fdat_dec.bin`（344,853,504 B，CBC 解完全文）按字节读，里面就是**两个对象 + 一张表**：

```
0x00000000  主头 512 B（"UDTRFIRM"）
       +8  u32 = 0xcdf83cd7            头 CRC32（覆盖 hdr[12,512)，已验）
      +12  ASCII "0100"              格式版本串
      +16  0x55 'U'                modeType（UFP/用户）
      +20  0x4e (78)              ？
      +32  0x200 (512)            头长
      +36  0x91030019           机型码（小端字）   +40 region=0   +44 0
      +48  0x00023200 (143,872)  ← 第二个对象的**偏移**
      +52  0x148bda00 (344,709,632) ← 第二个对象的**长度**（= 总长 − 143,872，整对）
      +56  0x00000002               ← **对象个数 = 2**
      +64  0x55 'U'   +68 0x200   +72 0x00023000 (143,360)  ← 第一个对象的元信息（modeType/头长/长度）
0x00000200  对象 1 = **Compressed ROMFS（cramfs）**，143,360 B
      开头 `45 3d cd 28` = cramfs 超级块 magic(0x28CD3D45)，`00 30 02 00`=fs 大小 143,360，
      `09 19 92 e8`=cramfs 自己的 crc，`name="Compressed ROMFS"` ⇒ 与 PC 自带的 `updater.img` 同一物，
      也与相机 `/usr/bin/udtrbody.bin` **逐字节相同**（之前 `cmp` 过）⇒ **相机里的“更新体”就是一个 cramfs 镜像**，
      脚本里 `$EXTRACT_ROOT`/`/ramdsk/updater/bodyfs/bin/…` 就是它被取出/挂上的根【已验】。
0x00023200  对象 2 = **`firmware.tar`**，344,709,632 B（开头就是 `0100_config/` 目录项，末尾整块零 ⇒ 标内 tar）
```
⇒ **之前把它当成“一个 UDTRFIRM + 一堆帧”是不准确的**：它是 `主头(512) → cramfs(更新体) → tar(内容段)`，
  而且 `0xa2fcf14` 那个“第二个 UDTRFIRM”只是 tar 里的一个**模块描述串**（`UDTRFIRM` + `N7Updater20BaseBodyLoaderMode` + `/tmp_updater/updater/body…`），
  不是头 ⇒ 搜索 magic 次数不能用来判对象个数，得读 `+56`。
⇒ **路线 A 要重造的是这五样**：主头（含对象表 +56/+48/+52/+72 + 头 CRC@+8）、cramfs（自带 crc `0xe8921909`）、tar、
  外层帧校验（每 1024 B）、DEND 记录 CRC。尾 272 B 在帧层，与这个内部结构是两个不同的层。

## 15. 本轮对可行性结论的影响（写进 `A7C_REAL_DEVICE_FEASIBILITY.md`）

1. **同版本重刷不必上 VERSKIP**：`up.sh modver` 改 `/setting/updater/dat4`（或 `serv`/`ms` 旗标模式）都可能是
   绕过 `0x142` 的低破坏路径；`'O'`/mode6（edisx + full + 擦 nflasha24）降级为"最后手段"。【代码证实机制，效果【未验】】
2. **`0110_backup`/`/setting/Backup.bin`/nflasha4(MPR)** 是这套链的备份面；每次 USER 更新都会 `ud_lerase … 4`。
   做 L4 备份时要含 **nflasha2（含 Backup.bin、upter/dat4、mode*、sen/）+ nflasha4**。【代码证实】
3. **loader 可写但本包不写**（`pformat.elf /dev/nflashaB0`），而且写 loader 前会先做 `LdrBkup.bin`。
   ⇒ 真砖风险在"自己发 loader 段/自己 pformat"，不在这次更新。【代码证实】
4. 仍缺的只有 nflasha1 的 boot 侧（`dat2/dat3`、kernel/initrd、可能的 `mf`/p1chksum）与 LDEC 语义；
   其余更新链已可在 PC 上离线读全。

## 16. ★`endupdate.sh` 读完：模式常量表、MPR/`Backup.bin` 收尾、还有"VERSKIP/PRODUCT 会格存储卡"

【已验：`endupdate.sh:9-22` 变量区 + `:55-110` 主流程】更新体自己定义的模式常量：
```
PRODUCT=1  LOADER_UPDATER=2  USER=3  SERVICE=4  MINOR=5  MSCRYPT=6  VERSKIP=7
KEEP_BACKUP=ud_keep_backup.elf     GET_LED=getledval.elf   LED 错误码 KEEPBACKUP=0x46
FSYS_WORK=/dev/nflasha23    # PMBP 2 MB
USER_STORAGE=/dev/nflasha24  # 存储卡也以 nflash 设备形式存在
```
⇒ 这是**一代自己的数字含义**（比引用 ZV-E10 的 `UPDATER_ACTION_MODE={2,4,6,8,9,10,11}` 强）；
而 `/setting/updater/mode*` 里存的是 **ASCII 字符**（`'3'`=51 … `'7'`=55，另有 `'M'`=0x4d）⇒ 字符→数字的转换点仍待定位。

收尾固定动作【已验】：
1. `ud_get_uudtype.elf` 返回 2 ⇒ `ud_keep_backup.elf -r`（保留 userdata），否则 `-u`（重置）；其它模式 `-w`；条件不满足 `-n`。
2. `cp /tmp_updater/updater/update/backup/*/*/*.bin /setting/Backup.bin`（"Backup.bin overwrite OK"）⇒ **包里那 1.2 MB 区域固件写进 a2 上的一个文件**。
3. `ud_keep_backup.elf $BACKUP_OPT` 非 0 ⇒ LED `0x46` + 退出（在 erase 之前）。
4. `ud_lerase.elf /dev/nflasha 4`（擦 MPR）——每次刷都做；失败 ⇒ `blink_error_exit $ERROR_MPR_ERASE`。
5. **只有 PRODUCT/VERSKIP**：若 `busybox sfdisk -s /dev/nflasha24` 成功 ⇒ **`ud_fsys_format.elf /dev/nflasha24` 直接格卡**（真机行为待验）。
6. 最后重新挂 `/setting`。

直接价值：
- `/setting/Backup.bin`（a2、文件级）是 MPR/MPC 区域固件的源件；**包里自带 26 个区域版本**（`CX88600/CX88601/CH88600/CH88601_{E38,CEC,AP2,JE3,CN1,CN2,AF1,IN5,KR2,UC2,J1,ALLLANG}.bin`，各 1,210,408 B）
  ⇒ 即使 a4 被擦坏，源件仍在包里（还缺的只是"写 a4"的手段）。
- **做 VERSKIP 前先把卡拔了/备份**：一旦进 VERSKIP，格卡会一并发生。
- L3 枚举设备时记得还有 `nflasha23`(PMBP) 与 `nflasha24`(卡)。

## 17. ★本轮：nflasha1 到底是什么 / 破坏半径（`us_mkfs.sh` 全读）/ 一代软件路径里根本没有 RSA

### 17.1 `us_mkfs.sh` 才是"刷机会格哪些盘"的权威（一代自己的脚本）
【已验：`us_mkfs.sh:12-24,39-77`】它自己也定义了同一套 1-based 常量（与 `endupdate.sh` 一致）：
`PRODUCT=1 LOADER_UPDATER=2 USER=3 SERVICE=4 MINOR=5 MSCRYPT=6 VERSKIP=7`
- `case $UPDATER_ACTION_MODE`：`SERVICE|USER|MINOR|MSCRYPT` ⇒ **不跑 `edisx.elf`**（不重划分区表）；
  其余（PRODUCT/LOADER_UPDATER/VERSKIP）⇒ `updater_storage_backup.sh` → **`edisx.elf /dev/nflasha partinf.conf`** → `updater_storage_restore.sh`。
- `fmode`：`PRODUCT|LOADER_UPDATER` → `full`（若存在 `/tmp_updater/not_write_file/nwl` 则改 `app` + `uc_pclear -f mount.conf`）；
  `SERVICE|USER|MINOR|MSCRYPT` → **`app`**；`VERSKIP` → **`full`**。最后 `uc_mkfs.elf -m $fmode -f $FILE_MOUNTCONF`。
- 之后（非 LDUDWRT 时）：挂 `/setting` → **`ud_keep_backup.elf -s`（从 `/setting/Backup.bin` 还原芯片区）** → 卸载；再 `ud_wbi_drop.elf partinf.conf`。
⇒ **USER 模式 = 不重划表 + `-m app`**；**VERSKIP = 重划表 + `-m full` + 还会格卡**（见 §16.5）。
⇒ 还欠一环：**`-m app` 到底格 mount.conf 里哪几块**（`uc_mkfs.elf` 里的分类规则）——下一步反解 `uc_mkfs.elf`（已在手：`updater.img_unpacked/bin/uc_mkfs.elf`）。

### 17.2 两套模式常量并存（别再混）
- `config/common.src:31-35`：**0-based** `MODE_USER=0 MODE_PROD=1 MODE_SERVICE=2 MODE_MINOR=3 MODE_VERSKIP=6`
- `endupdate.sh` / `us_mkfs.sh`：**1-based** `PRODUCT=1 … USER=3 … VERSKIP=7`
⇒ 前者是"调用方/参数"侧的含义，后者是 `UPDATER_ACTION_MODE` 的取值；`/setting/updater/mode*` 里存的仍是 ASCII 字符（`'3'`…`'7'`、`'M'`）。
**字符→数字的转换点**（`up.sh`？`crypter.elf`？`udtrbody` 入口？）仍待定位。

### 17.3 `loader_writer.sh`：loader 区叫 `/dev/nflashaB0`，而且**有官方备份路径**
【已验：脚本全文】`LOADER_UPDATER` 路径：解 `loader/loader_mpt.tar` → `md5sum -c loader_mpt.md5` →
挂 `/setting` 后 **`bksb.elf /setting/Backup.bin <LOADER>/LdrBkupList.txt <LOADER>/LdrBkup.bin`**（把 loader 区先备份进 Backup.bin）→
**`pformat.elf /dev/nflashaB0`**（擦/重写 loader 区，坏块返回 246 → LED 0x52）→
`dd if=/ramdsk/mis_ddrtraining_data.bin of=/dev/nflashaB0 bs=512 count=1 seek=24`（DDR training 在第 24 扇区）。
⇒ 本包**没有 loader 段** ⇒ USER 更新不碰 `nflashaB0`；而 `Backup.bin` + `bksb.elf` 说明 **loader 区的原件会被存进 `/setting/Backup.bin`**（一条现成的还原腿）。
⇒ 也说明 `partinf.conf` 里没有 `B0`：boot/loader 区是 nflash 驱动的独立区（`/dev/nflashaB0`），不是 nflasha1。

### 17.4 `chkfirm.sh`：主/副 LSI 的门（顺带解释 `0640_darwin` 是什么）
`ud_get_power_ic_type.elf` 返回电源 IC 型号来判定 LSI：`CHARON_CAM=1 CHARON_DSC=6 CA=4 PIROSHIKI=5 DARWIN=7`；
和包内 `config/sub.conf` 的存在与否交叉判断（错配 → LED `0x42`）。⇒ **`0640_darwin/darwin_core.bin` = DARWIN 电源 IC 的固件**（不是 macOS Darwin，也不是主系统）。
`/root/IAMLDUDWRT` 存在时跳过该检查（= 串列下载启动场景）。

### 17.5 ★一代软件更新路径里**没有任何 RSA/签名验证**（本轮实测的否定证据）
- `up.sh` + 更新体全部脚本：`openssl`/`dgst`/`.pem`/`signature` **0 次命中**；
- `crypter.elf`：无 `RSA`/`public`/`pubkey`/`pem` 字串，只有 `DEND`（CRC 逻辑）；
- `libupdaterufp.so` / `libupdatertalk.so`：`rsa|sign|verify|cert|pubkey` **0 命中**（`libIMDB.so` 只有 `libInfraCertificate.so`，那是网路/TLS 基础设施）。
- 但相机里**有** `/usr/bin/openssl` 与 `/lib/libcrypto.so.1.1` ⇒ 拿到代码执行后想算什么都能算。
⇒ 结论收紧：**"272B 尾" 不是由 senser/服务路径（crypter+up.sh）验的**。剩下的候选只有两个：
  (a) nflasha1 里 boot 时那套 updater（ZV-E10 同芯片证据：`boot/{vmlinux.bin,initrd.img(CRAMFS,4.94MB),kemco.txt,loadaddr.txt}` + `p1chksum` + `dat2/dat3`，`initrd` 里 `/sbin/init` 判 `/root/IAMLDUDWRT`/`/root/IAMUPDATER`）；
  (b) 片内 LDEC 硬件（CBC key 只在芯片里；尾里就有 IV）——若尾是硬件侧的 MAC/签名，1-byte-flip 探针会以 `boss_hw_ldec_wait err. status=…` 而不是 `0x41`/LED 形式暴露 ⇒ **L0 探针正好能区分**。

### 17.6 别再混：`updater.img`/`udtrbody.bin` 住在 **nflasha15**，不是 nflasha1
【已验】`crypter.elf`、`up.sh`、`ud_datcnv.elf`、`udtrbody.bin` 都在 `0700_part_image/dev/nflasha15_unpacked/bin/`（= 相机 `/usr/bin/`；`loader_writer.sh` 里 `source /usr/bin/common.src` 也对得上）。
FDAT 的第一个对象（cramfs `updater.img`）与 `/usr/bin/udtrbody.bin` 逐字节相同 ⇒ **同一个更新体在包里再带一份**（刷时解到 `/tmp_updater/updater/bodyfs`），它不是 nflasha1 的内容。

### 17.7 nflasha1 = **boot 分区**（同芯片强证据），因此比之前估计的更关键
- 包里 `mount.conf:13` `/dev/nflasha1 none vfat 8323072 16384`（不自动挂）；`partinf.conf` 名字 `SYSTEM (Updater)`；`common.src` 里 `MS_MOUNT_POINT=/mnt` + `us_crc32sum_appli.sh` 把它挂到 `/mnt` 写 `dat2/dat3` ⇒ **`/mnt` ≡ nflasha1**（与 Jiritsu 读 `/mnt/dat2` 一致）。
- ZV-E10（同芯片）实测该分区含 `boot/{vmlinux.bin,initrd.img,kemco.txt,loadaddr.txt}` + **`p1chksum`（逐文件 MD5 清单）** + `dat2/dat3`，且其 initrd 才是"真机启动链用的 initrd"。
⇒ 对 A7C 的含义（**推断，待 dump 证实**）：a1 = 8 MB vfat 的启动分区，**官方更新从不重写它**（包里根本没有它的镜像）⇒ **我们对它唯一的保险就是自己 dump 的那两份**；写坏 a1 = 启动链坏（只剩 BootROM/串列路径）。
⇒ 另外 `p1chksum` 是 MD5 清单 ⇒ 若 boot 阶段真按它校验，改 a1 里的 `initrd.img` 还得同步改 MD5 行（一代包里没有任何代码引用 `p1chksum`，校验者应在 a1 自己的 boot 代码里）。

## 18. ★模式旗标 ↔ 数字模式（子代理反解 `libupdaterbody.so`/`crypter.elf`；我抽查复核了关键证据）
完整报告：**`work/modes/MODE_MAP.md`**（286 行，另有 `work/modes/{body,crypter,ufp,common}_text.asm`、`plt_*.json`）。

唯一的"数字 ↔ 旗标文件"翻译器 = `libupdaterbody.so` 的 `Updater::FlagFirmwareInformationHandler::StartUpdate()` @**0x14e48**：
```
14e82 ldr r3,[this,#4]        ; UPDATER_ACTION_MODE
14e84 subs r2,r3,#1 / cmp r2,#1 / bls   -> 模式 1,2 完全不写旗标
14e8c cmp r3,#4 / beq                  -> 模式 4(SERVICE) 不写任何旗标
14ee8 subs r3,#3 / cmp r3,#4 / bhi     -> 只有 3..7 进 tbb
14ef0 tbb [pc,r3]   表 @0x14ef4 = 63 71 03 1c 35
        3->0x14fba   4->0x14fd6   5->0x14efa   6->0x14f2c   7->0x14f5e
```
| 数字模式 | 语义 | 写的旗标（写在 **`/tmp_updater/updater/current/updater/…`** = nflasha2 挂载点，rodata@0x16575） | 谁触发 |
|---|---|---|---|
| 1 / 2 | PRODUCT / LOADER_UPDATER | `mode1`(+`mode4`) | `up.sh` 无参 / `keep` |
| 3 | USER | `mode` | `up.sh user`、FDAT 头 modeType `'U'` |
| 4 | SERVICE | （无） | – |
| 5 | MINOR | `mode` + `mode3` | `up.sh serv` |
| 6 | MSCRYPT | `mode` + `mode5` | `up.sh ms` |
| 7 | VERSKIP | `mode` + `mode6`（另在 0x14f9a/0x14fa4 rw 挂 `/setting` 并碰 dat4） | `up.sh ver`、头 modeType `'O'` |

- 旗标名用的是 `common.src` 那套**旧编号**（USER=0→裸 `mode`、SERVICE=2、MINOR=3、MSCRYPT=5、VERSKIP=6；rodata 0x7ada-0x7b2d 里有 `updater/mode,mode1..mode6,comp`，**没有 mode4**）；运行时枚举是 1..7 ⇒ 这就是"两套编号并存"的原因（§17.2）。
- **数字是内存里传的，不是从旗标文件读的**：`crypter.elf` @0xc55a `DllHandler::Open("/tmp_updater/updater/bodyfs/bodylib/libupdaterbody.so",2)` → `GetSymbol("GetBody")` → vtable+0x58 取值：`0xc00c` 若 `[this+0x58]==1` ⇒ **FDAT 头 `[+0x14]=='L'` → 2，否则 → 1**（即 modeType 还能是 `'L'`=loader/product）；`verskip` 只在 `[+0x14]=='O'`（@0x1c02）或 IPC `0x4b0233` 回复时为 1，`'U'`→0，其它字符直接异常 `0x1031`。
- 脚本侧拿模式的方式：rodata@0x16575/../0x16b48 实测整条命令 =
  `export EXTRACT_ROOT=/tmp_updater/updater/update; export PATH=/tmp_updater/updater/update/program:/tmp_updater/updater/bodyfs/bin:/usr/bin:$PATH; export UPDATER_ACTION_MODE=<一位数字>` 交给 `system()`（`ShellPlugin::Execute@0x13de8`，数字>9 → `ApiException 0x3001a`）【本轮亲验字串存在】
  ⇒ **包里 `update/program/` 排在 PATH 最前**（PATH 劫持面确实存在，只是没有可控字符串可注入）。
- 版本门（`libupdaterufp.so`，GOT 名 `set_version`/`set_model`/`set_region`/`verskip`）@0x127a-0x1336：
  model 不符→`0x140`；region 不符→`0x141`；**`verskip==1` 直接跳过版本比较**；否则 `cmp firm_version,set_version` ⇒ **包版本必须严格大于**（否则 `0x142`）。
  `set_version` = `/setting/updater/dat4` 的 2 字节 LE（读函数 @0x14fe-0x1546）；`set_model`/`set_region` = 先 `mount("/dev/nflasha1","/mnt")` 再读 **`/mnt/dat2`、`/mnt/dat3`**（@0x2150-0x21ec）【本轮亲验：`/dev/nflasha1`、`/mnt`、`/mnt/dat2`、`/mnt/dat3`、`/setting/updater/dat4` 都是它的 .rodata 字串】
  ⇒ **再次钉死 `/mnt` ≡ nflasha1**（§17.7），且身份三件套的读取点就是这里。
- 收尾清旗标：`CompleteUpdate@0x1516c` 删 `mode1/mode2/mode3/mode5/mode6`、建 `comp`、删 `mode`；`crypter.elf @0xdc99` 见到有效 `comp` 就删 `mode6/mode3/mode`。
- 每条作业的接受/跳过/拒绝由 `<guard>` 决定：`XmlConfigHandler::executeGuard@0x13450`，**子进程退出码 0=通过、`0xff`=跳过、其它=异常**（`XmlConfigHandler.cpp:0x59`）。

## 19. ★272 B 尾的验证者是谁：同芯片资料里其实已经有了 —— 就是 `mf`
证据来自我们自己仓库里的 ZV-E10（同芯片 CXD90045）文档 `refs/zve10-qemu/docs/FIRMWARE_REPORT.md`：
- `:160` FDAT = `363,725 × 1024` 密文块 **+ 272 = 256 B 签名 + 16 B IV**；
- `:171` **`0400_updater/dev/nflasha1 → boot/initrd.img_unpacked/etc/VerificationKey.pem` = RSA-2048 公钥**（位数与 256 字节吻合）；
- `:285/:299` **`mf`（39,960 B，ARM EABI5 ELF）里有 `Updater::SignatureVerification`、`PEM_read_RSA_PUBKEY`、`RSA_verify`、`SHA1_*`/`SHA256`、字串 `"Signature Verification Error"`** ⇒ **验签发生在 `mf`**；`crypter.elf` 只有解密器（无 Encryptor）。
- `mf` 里同时有 `Updater::ModeFlagFile / Mode3FlagFile / Mode5FlagFile / **Mode6FlagFile** / CompleteFlagFile` + `/setting/updater/mode1`、`/ramdsk/mode5`、`/tmp_updater/fifo1|2` ⇒ 与 §18 一代 `libupdatercommon.so` 里的旗标名**完全同源**（跨机型同一条链）。
- 工厂/服务路径全景（`:270-277`）：PC 工厂工具（不随固件分发）→ 相机侧 `usb_extcmd.ko`("USB Extension Command function driver") + `usbg_storage.ko` + `usbg_sen.ko` → 相机内 **`sauu`（更新核心，`-m` Minor / `-s` VersionSkip）、`mf`（工厂工具）、`sen.elf`（Senser 工具，需要 HASP 加密狗）**。
- 相邻代 7CM2 侧：`UFPDecryptorModule::exec_write_firm@0x12f50 → VerifySignature/RSA_verify`（`chocotan/a7c2-re`，且说与 nflasha1 `boot/initrd.img` 内的 updater 代码一致）。
⇒ 对本机的结论（收紧）：**A7C 一代 senser/服务路径的软件（`crypter.elf`/`libupdaterufp.so`/`libupdatertalk.so`/更新体脚本）里没有任何 RSA**；
  验签者在 **nflasha1 里那套 updater（`mf`/`sauu`）**，而 a1 恰恰是包里不带、我们也没有副本的那块。⇒ "272 B 到底在 A7C 的哪条路径上被验"只能靠 (a) dump a1 反汇编 `mf`，或 (b) 下面的真机探针。

### 19.1 由此设计的**决定性探针**（比 L0 的"CBC 翻一字节"更对题）
L0 那个"CBC 区翻一字节"其实只能触发**帧内 u16 校验和**（`crypter@0xe0ec`），碰不到尾签名。真正对题的做法：
1. **只翻尾 256 B 签名里的 1 bit**（不碰 16 B IV、不碰任何帧、不碰帧头校验和）；
2. **重算 `DEND` 的 CRC32**（它覆盖 `[0, filesize-12)`，含尾；规则已实测 `crc32(dat[:-12])`）；
3. 顺带把 FDAT 头版本号 `2.00 → 2.01`（过 `0x142`"必须严格大于"）+ 重算头 CRC（`crc32(明文[12:512])`）+ 头是 ECB，要重新加密（`tools/fdat_hdr_edit.py` 已做这三层）。
判读：
- **刷成功（写盘、点亮 FIRMUP OK）⇒ A7C 服务路径不验尾签名 ⇒ 路线 A（改包重刷）对服务路径打开**（只需 CRC，不需索尼私钥）；
- 报 `0x41`/LED 类错误 ⇒ 尾签名被验（那就维持"路线 A 默认不可行"）。
顺序要求：**先拿到代码执行（L2/L3）再做这个探针** —— 因为一旦版本号被抬到 2.01，退回官方 2.00 需要 `up.sh modver`（要代码执行）或 VERSKIP（edisx + `-m full` + 格卡，代价大）。

### 19.2 另一个可下载的同芯片参照（正在跑）
`cokeenet/zve10-qemu/data/partition_map.tsv:2`：**ZV-E10 V2.03 的官方包里有 `0400_updater/dev/nflasha1`，8,323,072 B（与 A7C 的 a1 一字节不差），SHA-256 `c9040270ad886214…`**。
⇒ 公开可得（下载 Sony ZV-E10 2.03 升级器 + 我们自己的 FDAT 工具就能解出），能拿到：a1 的 FAT 根清单、**`p1chksum` 原文格式**（公开渠道至今没有）、`VerificationKey.pem`、`mf`/`sauu`/`is_valid_boot.sh` 本体 ⇒ 可离线反汇编 `mf` 把"272 B 谁验、怎么验"钉死。
注意：`qn06142/zv-e10-re` 实测"包里的 a1 与相机自己的 a1 有 79.5% 字节不同" ⇒ **参照只能用来读结构与代码，不能当 A7C 的备份**。
另：`is_valid_boot.sh` 在 a1 的 boot initrd 里，`ud_get_boot_device.elf` 返回 1=OneNAND/2=MS Boot/3=USB Boot，**USB Boot 分支会 `ud_cons.elf on` 开串口控制台**（`refs/zve10-qemu/docs/GEN1_BOOT_HARDWARE_TYPEC.md:84,157,313`）⇒ 比改 kemco 更靠谱的串口抓手，且暗示存在 USB boot 救援路径。

## 20. ★A7C **2.03** 包里有自己的 `nflasha1`（8,323,072 B）—— 本机就有这个包；顺带 ZV-E10 2.00 对照
本机 `/Users/wubin/Downloads/Update_ILCE7CV203.dmg`（已挂到 `/Volumes/Update_ILCE7CV203`）里的
`FirmwareData_ILCE7CV203.dat`（363,197,944 B）实测（解了前 48 MB 明文 + 顺序解析 tar 成员，帧校验 0 失败）：
```
tar 起点 = 明文 147,968；object0(cramfs body) = 512..147,968 = 147,456 B（2.00 是 143,360）
0100_config 0101_config_sum 0110_backup 0111_backup_sum 0300_partconf 0301_partconf_sum
0400_updater/  dev/nflasha1 = 8,323,072 B     ← A7C 自己的升级器/boot 分区镜像！
0401_updater_sum/ updater.sum (145 B)
0600_gps ...
```
- ⇒ **2.03 的官方刷会写 `nflasha1`（2.00 的包里根本没有这一段）**。这既说明 a1 官方可重写（可恢复性比之前估计好），也意味着：若"272 B 尾签名不被验"成立，**改过的 a1 可以塞进自制 .dat 走官方路径刷进去**。
- ⇒ **A7C 的 a1 出厂镜像现在不用碰相机就能拿到**（结构、`p1chksum`、`boot/kemco.txt`、initrd 里的 `mf`/`sauu`/`VerificationKey.pem`/`is_valid_boot.sh`/`UdtrMain.sh`/`updater_log.sh`/`updater_storage_*.sh`）。
  但它是 **2.03 版**，且 ZV-E10 实测"包内 a1 vs 机身 a1 有 79.5% 字节不同" ⇒ **机身 a1 仍必须自己 dump**（尤其 dat2/dat3 与可能被改过的区域）。
- 2.03 头字段：`+32 版本 = 0x0203`（2.00 是 `0x0200`）⇒ **版本是 BCD 打包的 u16，主版本在高字节**，与 `dat4` 的 2 字节编码同源；`+8` 头 CRC ✓；model `0x91030019`/region 0/modeType `'U'` 不变；IV 每包不同（2.03 = `65813b8b…`）。
- 2.03 的 `0110_backup` 区域 blob = **1,211,928 B**（2.00 是 1,210,408）⇒ MPR/区域固件也更新过；`0100_config/mount.conf` 仍是 1,253 B（待确认字节一致）。

### 20.1 ZV-E10 **2.00**（本机 `ZVE10/`，已解包）对照 A7C 2.00
- `partinf.conf` / `mount.conf` **只有一处实质差异**：`nflasha23` PMBP = **ZV-E10 64 MB vs A7C 2 MB**（连带尾部偏移 `0x54800000` vs `0x50A00000`）；其余分区完全一致。A7C 的 partinf 生成日期 2016-07-07（ZV-E10 2020-11-13）⇒ A7C 沿用很旧的分区表模板。
- **两个 updater body 其实是同一套代码**：42 个文件全部共有，只有两处不同 —— `config/body_version`（ZV-E10 `100.101.016` / A7C `100.101.014`）与 `bin/body_common.sh`（**A7C 少一行 `MSCRYPT=6`**）。⇒ 更新体是跨机型通用的；今天在一代 body 里读到的脚本逻辑对 ZV-E10 同样成立。
- `0800_appli/setting/kemco.txt` 两机型几乎一致（都有 `console=ttynull`、`cfg.uart=9`、`exception.console_option=115200n8`、`em_console=0x200210ec`；只差 `cache_l2x0.prio=130` 与 `wbimem` 大小）。
  ⇒ **ZV-E10 qemu 项目里被改成 1 的那个 console 开关不在这份 kemco 里** ⇒ 真正的启动 cmdline 应该在 **a1 的 `boot/kemco.txt`**（等 2.03 的 a1 解开就能看到 A7C 的真实 cmdline）。
- ZV-E10 2.00 的 `part_image.sum` 同样是 4 块（a3/5/7/15，大小不同），也没有 `0400_updater` ⇒ **"包里没有 a1" 是 2.00 时代的共性，不是 A7C 特有**。

## 21. ★★刷入到底发生在哪、272 B 尾到底谁验：**`sauu`**（全部来自 2.03 包里 A7C 自己的 a1）
`work/v203/nflasha1_203.bin`（8,323,072 B，sha256 `c9040270…21c093`；**与 ZV-E10 2.03 包里的 a1 完全同一个 sha** ⇒ a1 是跨机型共享镜像）
解开后：FAT12 8 MiB，内容只有 `boot/{vmlinux.bin 1,701,156、initrd.img 4,943,872(CRAMFS)、kemco.txt 1,062、loadaddr.txt 33}` + `p1chksum` 105 B；**没有 dat2/dat3**。
产物：`work/v203/a1_initrd/`（625 条，manifest `a1_initrd_manifest.tsv`）、`work/v203/REPORT.md`。

### 21.1 真正的刷入流程（一代，指令/脚本级）
```
运行中的系统:  libIMDB → libupdaterufp(门禁 0x127c/0x1b8c/0x1c00) → crypter.elf → body(libupdaterbody.so)
               └ FlagFirmwareInformationHandler@0x14e48 只是把 /setting/updater/mode* 旗标写好（不写分区！）
                     ↓ 重启进"更新模式"（boot 链加载 nflasha1 的 vmlinux+initrd）
更新模式 ramdisk（就在 a1 里）:  /usr/bin/UdtrMain.sh  ← 旗标→模式数字的读取者（之前在包里找不到的那一半）
               ├ getCurrentMode(): IAMLDUDWRT→PROD；无 mode→强制 PROD(touch /ramdsk/mode1)；
               │     mode3→MINOR、mode2→SERVICE、mode6→VERSKIP、mode1→PROD、mode5→MSCRYPT、默认 USER
               │     （并 touch /ramdsk/modeN + /ramdsk/UFP + /ramdsk/UFP_PRFILE；/setting/updater/uincomp → ERROR_UINCOMP=54）
               ├ 串口：test -f /root/IAMLDUDWRT || test -f /setting/updater/debug → ud_cons.elf on
               └ execute_ufp.sh $mode:  MINOR→`sauu -m`；VERSKIP→copyCurrentFirmwareInfo + `sauu -s`；
                     MSCRYPT→insmod mcmn/mmc/ms_drv + `sdfileinput.elf`(+MediaUpdateCompleteFlag)；否则→`sauu`
                     （都带 LD_PRELOAD=/usr/lib/libSysDef.so）
```
- a1 自己的 `/usr/bin/common.src`：`MODE_USER=0 MODE_PROD=1 MODE_SERVICE=2 MODE_MINOR=3 MODE_MSCRYPT=5 MODE_VERSKIP=6`
  ⇒ **旗标文件名后缀就是 a1 侧编号**（USER=0 用裸 `mode`）；body 的 1..7 是另一套运行时枚举（a1→body 的翻译在 a1 的 crypter/sauu 里，43,280 B 版，已可离线反解）。
- `execute_ufp.sh:copyCurrentFirmwareInfo()`：**把 `/mnt/dat2`、`/mnt/dat3`（= a1 上！）和 `/setting/updater/dat4` 拷进 `/ramdsk/`**
  ⇒ 完美解释 `us_crc32sum_appli.sh` 事后从 `/ramdsk/` 恢复三件套；**dat2/dat3 在 a1、dat4 在 a2** 彻底钉死。
- `if [ -e /setting/updater/comp ] ; then rm -rf /setting/updater/mode*`（上次成功过就清旗标）。

### 21.2 ★272 B 尾 = RSA-2048，验证者是 **`sauu`**（不是 crypter，不是 body）
| 对象 | `RSA_verify/PEM_read/SignatureVerification` |
|---|---|
| `a1:/usr/bin/sauu`（84,428 B） | **有**：`N7Updater21SignatureVerificationE`、`RSA_free`、`RSA_verify`、`PEM_read_RSA_PUBKEY`、源文件名 `SignatureVerification.cpp`、日志格式含 `"signature"` |
| `a1:/usr/bin/mf`（39,960 B，工厂工具） | **有**，并且有字串 **`/etc/VerificationKey.pem`**（该文件 451 B，就在 a1 initrd 的 `/etc/`）+ `"Signature Verification Error"` |
| `a1:/usr/bin/crypter.elf`（43,280 B）与 `a15:/usr/bin/crypter.elf`（39,036 B） | 无 |
| `a15` 的 `libupdaterufp / libupdatertalk / libupdaterufunc / libupdatermedia` | 全 **0 命中**（本轮补测） |
⇒ **路线 A（自制 .dat 走官方刷）基本判死**：服务/运行系统侧只验 model/region/version 并写旗标，**真正写分区是在更新模式里由 `sauu` 驱动，而 `sauu` 验 RSA**。
⇒ "只翻尾签名 1 bit + 重算 DEND"探针现在的预测是**会失败**（仍值得做一次，成本极低、失败即在写盘前中止）。

### 21.3 `p1chksum` 格式已破；校验者仍不在 userspace
```
0dcd3b9177c38b610dcd0afdfba57def  ./boot/vmlinux.bin
bb50bfb5261f161a9f49bd351e5fddfb  ./boot/initrd.img
```
= **标准 `md5sum` 文本**，只覆盖 boot 下两个文件，**不含 p1chksum 自身**；我复核两行 MD5 与实际文件完全吻合 ✓（`bb50bfb5…` 也和 ZV-E10 文档记载一致 ⇒ 同镜像）。
⇒ 但 **a1 initrd 全树 0 处引用 `p1chksum`** ⇒ 读它的是更早的阶段（loader/EXBL/`/dev/nflashaB0` 里的代码，我们还没有）。
⇒ 顺带：a1 里另有 `hash_check.sh / hash_update.sh / hash_drop.sh`，用 `md5sum -c ${HASH_DIR}/<firm名>.md5` —— 那是"包哈希缓存/断点"机制（LDUDWRT 路径会 `rm ${…}/hash/*`），与 p1chksum 无关。

### 21.4 新的官方抓手（比改 kemco 安全）
- **`/setting/updater/debug` 存在 ⇒ `ud_cons.elf on`（更新模式下开串口控制台）**【已验脚本】——一个空文件而已，写在 a2 上，随时可删。
- `is_valid_boot.sh`：`ud_get_boot_device.elf` → 1=OneNAND / **2=MS Boot（`ud_cons.elf on` + `ud_msmnt.elf` + `ms_security.elf`）** / **3=USB Boot（`ud_cons.elf on`）** ⇒ **USB boot 是自带串口日志的一条入口**（配合 BootROM/串列启动 = 真正的救援路径候选）。
- a1 的 `boot/kemco.txt` 里有 **`console=ttyAM0,115200n8 amba2.console=0`**（Sony 自己的写法；另有 `cfg.uart=15`、`initrd=0x00700000,0x01000000`、`cxd90014.bam=Y`）
  ⇒ 若要给**主系统**开串口，改 `/setting/kemco.txt` 里的 `console=ttynull` 时有官方拼写可照抄（`/setting/kemco.txt` 是 `console=ttynull`+`cfg.uart=9`）。
- `loadaddr.txt` = `0x00108000,0x00700000,0x00103000`（kernel/initrd/… 加载地址）。

### 21.5 a1 的可恢复性因此变好（风险从"无副本"降级）
1. 我们手里有 **2.03 包的出厂 a1**（跨机型共享）；2. **官方 2.03 更新本身就会整分区重写 a1**（`config.xml` 只改 1 行：`us_crc32sum.sh updater image` → `us_crc32sum_updater.sh …`，并新增该脚本；`startupdate.sh` 新增 dat2/dat3 备份 + kikilog(nflasha10) 规避，`endupdate.sh` 回写 kikilog）；3. **dat2/dat3 可再生**（`ud_datcnv.elf`，model=0x91030019/region=0 已知）。
⇒ 结论：写 a1 不再是"没有任何退路"，但**前提仍是先 dump 机身 a1**（机身那份是 2.00 时代 + 被运行期写过，ZV-E10 实测与包内 a1 差 79.5%）。

### 21.6 两台"刷入引擎"并存 —— 最后一格还没钉死（但已经能离线钉）
| 引擎 | 在哪 | 门禁 | RSA 验签 | 能写分区 |
|---|---|---|---|---|
| **UFP / 运行系统侧**：`libIMDB → libupdaterufp → crypter.elf(a15,39,036) → body(libupdaterbody.so)` | nflasha15（`/usr/bin`、`/usr/lib`） | 有：`0x127c/0x1b8c/0x1c00`、`0x140/141/142` | **无**（ufp/talk/ufunc/media/crypter 全 0 命中，本轮补测） | 有：body 里就是 `us_crc32sum*.sh` + `uc_crc32sum.elf`（`ShellPlugin::Execute → system()`） |
| **更新模式侧（a1 的 ramdisk）**：`UdtrMain.sh → execute_ufp.sh → sauu`(84,428)（MSCRYPT 走 `sdfileinput.elf`） | nflasha1 的 `boot/initrd.img` | 走同一套 body | **有**（`Updater::SignatureVerification`/`RSA_verify`/`PEM_read_RSA_PUBKEY`；`/etc/VerificationKey.pem` 451 B 就在同一 initrd） | 有（同一个 body；`/ramdsk` 就是这边造的） |
- 关联证据：`uincomp` 同时出现在 **`libupdaterbody.so`**（两侧都加载它）与 `UdtrMain.sh`（见到就 `blink_error_exit 54`）；`libupdaterufp.so` 里引用 `up.sh`；a1 侧 `execute_ufp.sh` 会 `if [ -e /setting/updater/comp ] ; then rm -rf /setting/updater/mode*`。
⇒ 两种可能：(a) PC app 走 UFP 侧，**就地写完**（那 272 B 在这条路上根本不验）；(b) UFP 只写旗标 + `uincomp`，**重启后由 `sauu` 完成**（那 272 B 必验）。
⇒ 离线钉死办法（都已在本机，可直接反汇编）：`work/v203/a1_initrd/usr/bin/{sauu,crypter.elf,up.sh}` vs `…/nflasha15_unpacked/bin/{crypter.elf,udtrbody.bin}` —— 看谁调用 `uc_crc32sum.elf`/写块设备、谁在什么时机调 `SignatureVerification`。
⇒ 实测钉死办法：L0' 探针（**只翻尾 256 B 里 1 bit + 重算 DEND CRC**，用 2.03 原包，版本号不用动）：过 = (a)；报 54/LED = (b)。
- 顺带：**Mac 端 `SystemSoftwareUpdater.app`（2.03 与 2.00 两份）里没有任何 RSA/签名/FDAT 相关字串**（`MacOS/SystemSoftwareUpdater` 只有 ObjC 类名 + `/SystemSoftwareUpdaterTool` + `.dat`；52,992 B 的 Tool 里 grep `rsa|signatur|verif|pem|dend|UDTRFIRM|FDAT` 全 0）⇒ **PC 端不做验签**，只管把 .dat 送过去。

## 23. ★★★ 机身 a1（2.00）离线钉死：p1chksum 吻合、验签者不是 sauu、2.00 没有签名门禁（详见 `work/l1-camera/A1_COMPARE.md`）
1. 手写 FAT12 解析（`work/l1-camera/fat12.py`）：512 B/扇区、32 扇区/簇(1024 B)、保留 1、FAT×2 各 32 扇区、根目录 512 项、总 16256 扇区、隐藏 0 ⇒ 505 簇 < 4085 = **FAT12**；FAT@0x200/0x4200、根目录@0x8200、数据@0xc200。两份 FAT 副本逐字节相同（卷干净）。
2. 机身目录：根 `boot`(cl3) `p1chksum`(105 B,cl404) `dat2`(4 B,cl405) `dat3`(4 B,cl406)；`boot/` = initrd.img(cl4,294 簇,4,812,800) vmlinux.bin(cl298,104 簇,1,697,076) kemco.txt(402,1062) loadaddr.txt(403,33)。dat2/dat3 无 LFN、时间戳 2011-01-01（相机驱动写的），其余 = 出厂 2020-05-14 16:30:10（与卷序列号 `0x4e382154` 一致）。
3. ★**p1chksum 两条 MD5 与机身自己提取的文件实算逐字节吻合**：vmlinux `a6d9d7695e66a1301ca8f2a29eb42aea`、initrd `0f00bf40c7d13f84cf9abf8c068c5f7a` ⇒ 机身 boot 未被改过；格式与 2.03 的 105 B 完全同构（203 值 `0dcd3b91…`/`bb50bfb5…`）。a1 initrd 全树仍 0 处引用 p1chksum。
4. dat2 = `19 00 03 91` ⇒ **LE 0x91030019**（model id，确认小端）/ BE 0x19000391；dat3 = `00 00 00 00` ⇒ LE=BE=**0**（旧笔记"dat2/dat3 sha 相同"是错的）。
5. 机身 initrd CRAMFS 解出 621 条目/217 文件（`work/l1-camera/a1_initrd{,_manifest.tsv}`）。与 2.03 manifest：608 同名，**157 文件字节相同**、**47 不同**、只 2.00 的 13 条其实是同一批库从 `/lib` 挪到 `/usr/lib`（除 libgcc_s），只 2.03 的新增含 **`/root/IAMSIGNENABLED`(0 B)** + libuuid。`/etc/VerificationKey.pem` 451 B `79be4fb50a65` **两版相同**（RSA-2048）。
6. ★验签者判定（指令级，`tscan.py`/`armdis.py`）：`sauu` 84,428 B **两版 .plt/.dynsym/.rodata 逐字节相同**、`/etc/VerificationKey.pem` 字面量在两版同一 vaddr 0x10cb4、引用点 0x10c66-0x10c6c 是 `printf("%s:%d")` 的 `__FILE__`+行号 0x97 ⇒ **sauu 里没有任何 bl 指向 RSA_verify/PEM_read/RSA_free 的 @plt（两版都 0 命中）⇒ 修正 §21.2：sauu 不验签**。真正执行的是 **`/usr/lib/libsdfileinputupdaterapi.so`**（机身 2.00 就在，与 2.03 只差 **4 字节**立即数，`VerifySignature` 0xdd6c 里 `bl PEM_read_RSA_PUBKEY`0xdddc→`SHA256`0xddf8→**`bl RSA_verify@plt` 0xde0c**→`RSA_free`0xde32），调用者只有 `SDDecryptorModule::execWriteFirm`(0xcc32, = `sdfileinput.elf`/MSCRYPT) 与 `UFPDecryptorModule::execWriteFirm`(0xc69a)。
7. 2.00 与 2.03 的真差：`mf` 2.00 **不链 libcrypto/libssl、0 验签字串**（2.03 才加）；`libupdater0604.so` 2.00 **没有** `UD_GET_VERIFY_SIGN`+`/tmp_updater/root/IAMSIGN{ENABLED,DISABLED}`（2.03 有），2.00 官方包解密体 `full_dec_200.bin` 对 IAMSIGN/VERIFY_SIGN **0 命中** ⇒ **签名开关是 2.03 引入的，这台 2.00 机身没有**。
8. 机身 2.00 `UdtrMain.sh`：`test $MODE_PROD -eq $cur_mode && ud_cons.elf on`（PROD 必开串口控制台，2.03 改成只在 `/root/IAMLDUDWRT`）；`execute_ufp.sh` 只差 2.03 多一行 `insmod ms_drv.ko`。
9. 全零区解释：机身最后已用簇=406（末字节 0x65FFFF），簇 407-506 在 FAT1+FAT2 里都是 0x000（**101 个空簇**）⇒ `0x660000` 之后全零 = **没用到的空簇**，不是被清零的已用区。12,999/16,256 差异块 = 引导扇区 1（只 4 字节=卷序列号）+ FAT 4（链形状）+ 根目录 1 + boot/ 目录 1 + **空闲簇 946** + **超出簇范围尾部 12,046**；203 在 0x66c200/400/600、0x670200、0x674200 的 5 个非零块其簇也是空闲 ⇒ 打包残留。
10. 可行性：改 a1 的 initrd + 同步改 p1chksum **可做**（p1chksum 就是 md5sum 两行、单簇文件可原地覆盖，不碰 FAT）；硬约束是机身 `boot/kemco.txt` 的 `initrd=0x00700000,**0x00800000**`（2.03 才是 `0x01000000`；两版 kemco.txt 只差偏移 0x22/0x23 两字节）⇒ 新 initrd ≤8 MiB（现 4,812,800 B，余 3.36 MB），且 **2.03 的 4,943,872 B initrd 已超 8 MiB**；空闲空间仅 101 簇=103,424 B，改大 initrd 必须重排簇。p1chksum 不覆盖 kemco.txt/loadaddr.txt。

## 25. ★★★ 取代 §19/§21：272 B 尾在 A7C **2.00** 上根本没人验（`work/sauu/SIG_VERIFY_200.md`）
1. **`sauu` 不是验签者**（两版 sauu 一致）：对 `RSA_verify@plt(0xb60c)`/`PEM_read@plt(0xbb84)`/`RSA_free@plt(0xbae4)`/`SHA256@0xb940` 的调用点 **0**；`/etc/VerificationKey.pem`(vaddr 0x10cb4) 只是 `__FILE__`+`printf` 参数 ⇒ 死代码。
2. 2.00 的 `mf`（MODE_PROD 路径）不链 libcrypto、无验签符号；**2.03 才加**：`0xbd1c→0xc178`，`PEM@0xc1d4`→`SHA256@0xc1ec`→**`RSA_verify(NID_sha256,0x2a0)@0xc200`**，失败 `ApiException 0x30002`（pem 打不开 `0x30005`，`SenserInputUpdaterManager.cpp:162`）。
3. 2.00 唯一真验签点 = **MSCRYPT(mode5) SD 卡路径**：`sdfileinput.elf`（全固件唯一 `DT_NEEDED libsdfileinputupdaterapi.so`，2.00/2.03 逐字节相同）→ `SDDecryptorModule::execWriteFirm@0xcba4` → `0xcc32 blx VerifySignature(stub 0xab7c)` → **`RSA_verify@0xde0c`**。`UFPDecryptorModule::exec_write_firm@0xc600`(bl@0xc69a) 全库 **0 callers** = 死代码。a15/更新体对 `sdfileinput|updaterapi|UFPDecryptorModule|execWriteFirm|SignatureVerification` **0 命中** ⇒ **PC 通道够不到验签**。
4. 该库 2.00↔2.03 实际差 **5 字节/3 处**（不是 4）：`BufferManager::Initialize@0xd040` 里 `and r5,r5,#0x20000000 → #0x40000000`（指令 @0xD064，改 0xD066-67；`sysconf(30)`→neg→mask→`mmap` 缓冲 512 MiB→1 GiB）；`SDFileManager::getFirmwarePath@0xda58` `sub.w sp,sp,#0x830→#0xc30`(0xDA5E)+字面量池位移 0xDA9E；`.ARM.extab@0x1243E` 3→5（LSDA 连带）⇒ **与验签无关**。
5. `IAMSIGN` 只在 2.03：`/root/IAMSIGNENABLED`(0 B) 由构建期烧进 a1 CRAMFS（无人写），唯一读者是 2.03 `libupdater0604.so` 的 `udtr_adjcmd_get_verifysign`（stat `/tmp_updater/root/IAMSIGN{ENABLED,DISABLED}`）= **能力查询不是开关**。
6. 链路（钉死）：PC `.dat` → a15 `libIMDB → libupdaterufp`（门禁 `0x127c`/`0x140-0x142`）**+ `crypter.elf`（只写旗标 `mode/mode1/mode3/mode6`）** → 重启 → a1 `UdtrMain.sh → execute_ufp.sh` 才写分区。
7. **DEND CRC32 确实被验**：四份 `crypter.elf` 都有 `CrcChecker@0xb408`（poly `0xEDB88320`，读尾 12 B `memcmp(buf+8,"DEND")` + 比对，失败打印 `calc_crc`/`getHd_crc`@`CrcChecker.cpp:89`）⇒ 改包必须重算 CRC。
8. **LED/错误码表**（`common.src` + body）：41/45/47/48/**54=UINCOMP**/67/72/73/87；body 侧 `0x41/0x61/0x62/0x68`；验签失败不走 shell 码，走 `ApiException 0x30002`。
9. **判定**：A7C **2.00** 上 USER/SERVICE/MINOR/VERSKIP/PROD **都不会**撞 RSA，只有 MSCRYPT 会（PC 进不去）⇒ **L0' 探针（翻 272 B 里 1 bit + 重算 DEND CRC）在 2.00 预计不会被拦**；2.03 的 PROD(`mf`) 会被拦。缺环：帧 u16 校验和/头 CRC 的实际强度、门禁 `0x140/0x141/0x142` 与 `modeType 'U'/'O'` 的组合（静态不可达，非实测）。
