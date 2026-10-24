# A7C 旗标文件机制梳理（/setting + /usr）

结论基于两份材料：

- 更新器 initrd：`a7c-shared/a1_initrd_200/`、`a7c-shared/a1_initrd_203/`（以 2.03 为准，差异单列）
- 机身 `/usr`：`a7c-shared/nflasha15.bin`（解包在 `modes/a15/`）
- `/setting` 整块镜像：`a7c-shared/nflasha2.bin`（FAT12）

---

## 0. 先给结论

1. **更新器不是只有 `mode5` 一个旗标。** 路由旗标是 `mode`、`mode1`、`mode2`、`mode3`、`mode5`、`mode6`，全部按“文件存在/不存在”生效，内容无所谓（空文件即可）。
2. **`comp` 不是脚本，是一个空文件**（`/setting/updater/comp`）。`execute_ufp.sh` 看到它才执行 `rm -rf /setting/updater/mode*`。出厂镜像自带 `comp`，所以你自己塞的 `mode5` 在每次非产线更新开始时都会被删掉——它是**一次性开关**。
3. **2.03 的 `UdtrMain.sh` 在 `mode`（不带数字）不存在时直接强制 PROD**，根本走不到 `mode5`。所以 2.03 上只放 `mode5` 不生效，必须同时放 `mode`。2.00 没有这条强制判定，单独 `mode5` 可用。
4. **优先级：`mode3 > mode2 > mode6 > mode1 > mode5`。** 任何残留的高优先级旗标都会把 `mode5` 截胡；`mode1` 还会把更新器带进产线链（`execute_prod.sh`），而产线链**不执行** `comp` 清理，所以 `mode1` 会留存——每次进入更新器都会走产线链。
5. **“刷固件不写 /setting”这个前提不成立。** a1 更新器会 `mount -t vfat /dev/nflasha2 /setting` 然后删除/创建旗标、`touch MediaUpdateCompleteFlag`；机身 `libObj.so` 还会 `mkdir /setting/mode`、写 `cmode`。它不会整块重刷/格式化，但确实会改写这个分区的目录项和文件。
6. **真正会影响“正常启动”的旗标不在 `updater/` 下，而在 `/setting/mode/` 和 `/setting/sen/`：** `dmode`、`preload` 由 `bootin.elf` 在每次正常启动时读取；`cmode`、`smode` 由机身库读取。`/setting/updater/*` 只在进入更新器时被读，改错最坏是更新会话失败/循环，不会影响正常开机。
7. `mode4` 没有任何读取者（`libupdatercommon.so` 里连 `Mode4FlagFile` 类都没有），`up.sh` 的 keepbackup 分支也被注释掉了——是死键。
8. `mode2` 有读取者（`UdtrMain.sh`），但**没有找到任何写入者**；手工放进去后的下游效果也没有找到读取 `/ramdsk/mode2` 的代码，实际约等于 USER 路径。

---

## 1. 两个关键更正

### 1.1 `nflasha15.bin` 不是 FAT，是 ext2

- 文件偏移 `0x400` 处是 ext2 superblock，magic `0xEF53`（偏移 `0x438`）。
- 1 KiB block，234356 blocks，58696 inodes。
- 用 `modes/ext2_walk.py` 解包，得到 `modes/a15/`（967 个文件）和 `modes/manifest.tsv`。

### 1.2 `/setting` 更新时会被写

`execute_ufp.sh` 的实际动作：

```sh
prepare-usb.sh
ud_timeout_poweroff.elf &
mount -t vfat /dev/nflasha2 /setting ...
if [ -e /setting/updater/comp ] ; then
        rm -rf /setting/updater/mode*
fi
umount /setting
```

此外还有：

- MSCRYPT 分支：`touch /setting/updater/MediaUpdateCompleteFlag`
- 机身 `libObj.so`：`mkdir /setting/mode` + 写 `/setting/mode/cmode`
- `change_mode.sh`：写 `/setting/mode/dmode`、`/setting/mode/preload`
- `up.sh func_modver`：写 `/setting/updater/dat4`

`nflasha2.bin` 是 FAT12（512 B/sector，32 sectors/cluster，1 reserved，1 FAT，512 root entries，40960 sectors，FAT 大小 4）。用 `modes/fat12_ls.py` 可直接列出：

```
$ python3 fat12_ls.py ls UPDATER
FILE comp    cl=0   size=0
FILE dat4    cl=438 size=2        # 内容 00 02
$ python3 fat12_ls.py ls MODE --deleted
FILE cmode   cl=441 size=3  [deleted]   # 3 字节（推测为 CC\n，簇已被复用）
```

也就是说出厂镜像里 `comp` 存在、`mode` 不存在、`cmode` 是被删除状态。

---

## 2. 更新模式决策链（a1 initrd）

`UdtrMain.sh` 的 `getCurrentMode()`（2.03 第 7-37 行）：

```text
/setting/updater/mode 不存在
        -> 强制 PROD（2.03 新增），touch /ramdsk/mode1，return 1
/setting/updater/mode3 存在 -> MINOR   (3)  touch ramdsk/mode3,UFP,UFP_PRFILE
/setting/updater/mode2 存在 -> SERVICE (2)  touch ramdsk/mode2,UFP,UFP_PRFILE
/setting/updater/mode6 存在 -> VERSKIP (6)  touch ramdsk/mode6,UFP
/setting/updater/mode1 存在 -> PROD    (1)  touch ramdsk/mode1
/setting/updater/mode5 存在 -> MSCRYPT (5)  touch ramdsk/mode5,UFP,UFP_PRFILE
否则                        -> USER    (0)  touch UFP,UFP_PRFILE
```

然后：

- `/setting/updater/uincomp` 存在 → `blink_error_exit ERROR_UINCOMP`（更新直接终止）
- `PROD` → `execute_prod.sh`（`mf` + `sen.elf` + `prepare-usb.sh`，产线链，**不做 comp 清理**）
- 其它 → `execute_ufp.sh`：
  - `comp` 存在 → `rm -rf /setting/updater/mode*`
  - MINOR → `sauu -m`
  - VERSKIP → 复制 `dat2/dat3/dat4` 到 `/ramdsk`，`sauu -s`
  - MSCRYPT → `insmod mcmn_drv/mmc_drv/ms_drv` + `sdfileinput.elf` + `touch MediaUpdateCompleteFlag`
  - 其它（USER/SERVICE）→ `sauu`

2.00 与 2.03 的差异（`diff` 实测）：

- 2.03 新增“`mode` 不存在 → 强制 PROD”这一段（2.00 没有）。
- 2.03 的 MSCRYPT 分支多 `insmod ms_drv.ko`。

---

## 3. 主表

说明：

- “存在性旗标”指只看文件是否存在，内容无关（空文件即可）。
- 地址均为该二进制内的 VA；同一功能在多个更新器二进制里各有一份拷贝。
- `a1` 指 2.03 initrd，`a15` 指机身 `/usr`。

| 旗标 | 类型 | 读取者（模块 / 函数 / 地址） | 读到后做什么 | 改错/残留的后果（安全性） |
|---|---|---|---|---|
| `/setting/updater/mode` | 更新路由（存在性） | `a1: UdtrMain.sh:15`（缺失强制 PROD，仅 2.03）；`execute_ufp.sh:33`（comp 存在时删除）；RVchk 只删不读 | 存在→继续按 `mode3>mode2>mode6>mode1>mode5` 选路；不存在→(2.03+) PROD | 缺它不是危险，但会让 `mode5` 失效；被 comp 删掉属正常一次性行为 |
| `/setting/updater/mode1` | 更新路由（存在性） | `a1: UdtrMain.sh:27`；RVchk（`sauu sub_1517c`、`mf sub_e2d0`、`crypter sub_ede8`、`sdfileinput.elf 0x11924`、`libsdfileinputupdaterapi.so 0x108d8`）在降级判定成立时删 `mode`+`mode1` | PROD → `execute_prod.sh`（产线更新）；不走 comp 清理 | **高**。残留后每次进更新器都走产线链；优先级高于 `mode5`，会让 SD 链失效 |
| `/setting/updater/mode2` | 更新路由（存在性） | `a1: UdtrMain.sh:21` | SERVICE；touch `/ramdsk/mode2`、`/ramdsk/UFP`、`/ramdsk/UFP_PRFILE`；后续与 USER 一样走 `sauu` | 中。**没找到写入者**；残留会压过 `mode6/mode1/mode5`。下游没有发现读 `/ramdsk/mode2` 的代码 |
| `/setting/updater/mode3` | 更新路由（存在性） | `a1: UdtrMain.sh:18`；`execute_ufp.sh:38-40` | MINOR → `sauu -m`；comp 存在时启动即被删 | 中低，一次性。写入者：`libObj sub_896204/896008`、`libupdater0604 sub_1424/sub_15a0`、`up.sh func_servicemode` |
| `/setting/updater/mode4` | 更新路由（存在性） | **无读取者**（a1/a15 均未找到；`libupdatercommon.so` 无 Mode4 类） | 无 | 无作用（死键）。`up.sh func_keepbackup` 会写 `mode+mode1+mode4`，但分发处被注释 |
| `/setting/updater/mode5` | 更新路由（存在性） | `a1: UdtrMain.sh:30`（→`/ramdsk/mode5`）；RVchk 读 `/ramdsk/mode5`（同上地址）；`execute_ufp.sh:45-50` | MSCRYPT：insmod mcmn/mmc/ms + `sdfileinput.elf` + `touch MediaUpdateCompleteFlag`；`/ramdsk/mode5` 使 RVchk 末段版本检查直接返回 0（放过） | 低-中。前提：`mode` 存在、无更高优先级旗标；comp 会让它一次性；版本检查旁路意味着可降级刷写 |
| `/setting/updater/mode6` | 更新路由（存在性） | `a1: UdtrMain.sh:24`；`execute_ufp.sh:41-44`；StartUpdaterMode 删除 | VERSKIP：复制 `dat2/3/4` 到 `/ramdsk` → `sauu -s` | 中低，一次性。优先级高于 `mode1/mode5`，会截走你的 `mode5` |
| `/setting/updater/comp` | 更新控制（存在性） | `execute_ufp.sh:33`；`sauu sub_141dc`、`sauu sub_e078`；`mf sub_ddfc`；`crypter sub_de48`(a1)/`sub_d83c`(a15)；`sdfileinput.elf 0x10974`；`libsdfileinputupdaterapi.so 0xf938`；StartUpdaterMode（`sauu 0x14638`、`mf 0xe258`、`crypter a1 0xe2a4`/`a15 0xdc98`、`sdfileinput 0x10dd0`、`lib 0xfd94`）；`ud_timeout_poweroff.elf sub_86f4` | ① `execute_ufp.sh` 开头 `rm -rf mode*`；② StartUpdaterMode 删 `mode6/mode3/mode`；③ `ud_timeout_poweroff` 少等 1.8 s；④ `sauu sub_e078` 在 comp 存在时选 `UsbBusPower_Init_IgnoreSuspend`，否则 `UsbBusPower_Init` | **关键，别删。** 删了以后 `mode5`/`mode1` 等会永久驻留，形成每次更新都跑同一链的循环。它本身是“更新完成”标记，内容无关 |
| `/setting/updater/dat4` | 版本（内容） | `execute_ufp.sh:14`（复制）；RVchk（同上五个地址）；`libupdaterufp.so` 有引用（未展开） | 读前 2 字节，与当前固件版本比较，做降级拦截；异常时删 `mode`+`mode1` 并返回 -1 | 中。内容型，出厂 `00 02`。乱改会导致更新被拒/误判降级；不影响正常启动 |
| `/setting/updater/uincomp` | 更新控制（存在性） | `a1: UdtrMain.sh:66` | 在 dispatch 之前 `blink_error_exit ERROR_UINCOMP`，更新终止 | 高（更新被卡死），但只影响更新器；未找到写入者。删掉即可恢复 |
| `/setting/updater/debug` | 调试（存在性） | `a1: UdtrMain.sh:54`；`sauu sub_fbe4`（DebugExBase::IsCommand） | `ud_cons.elf on` 开串口控制台；允许 DebugEx 命令（DEBUG_RESET / DEBUG_EXTRACT_LOG / DebugExLog） | 低，只增加调试能力，不影响选路 |
| `/setting/updater/MediaUpdateCompleteFlag` | 更新标记（存在性） | **未找到读取者**（a1/a15 都没有） | 未知 | 未知（见“分不清”） |
| `/ramdsk/mode`、`mode1/2/3/5/6`、`UFP`、`UFP_PRFILE` | 进程间标记（tmpfs） | 写入：`UdtrMain.sh`；读取：RVchk 只读 `/ramdsk/mode5`、`/ramdsk/UFP`（以及 `/ramdsk/dev/mode`） | `mode5` 触发版本检查旁路；`UFP` 是 RVchk 清理分支的前提 | 重启即消失，**不能当持久开关用** |
| `/ramdsk/dev/mode` | tmpfs 标记 | 写入：`libsencore.so NinThread`（a15 约 `0x10e9a`；a1 initrd 里也有同一字符串/逻辑）；读取：RVchk（仅判存在） | 作为 RVchk “版本异常清理”分支的联合前提 | 含义分不清 |
| `/setting/mode/dmode` | 启动调试（内容） | `a15 bootin.elf sub_9448`（`+0x26` 取路径；读最多 30 字节） | 逐字符解析调试开关：`0-3` 基础模式、`p/P`=0x40（启用 preload）、`l/L`=0x42、`w/W`=8、`g/G`=0x10（target gdb）、`s/S`=0x20（gdbserver）等 | 内容型，正常启动会读。无效字符被忽略；`g/s` 类选项可能让 `im.elf` 等待调试器导致启动停滞（未逐一实测） |
| `/setting/mode/preload` | 启动 preload（内容） | `a15 bootin.elf sub_991c`（仅当 dmode 含 `p`）；白名单表在 `bootin.elf 0xa8dc` | 给 `/usr/bin/im.elf` 设 `LD_PRELOAD`；只接受 4 个路径：`/usr/tool/LeakTracer.so`、`libefence.so`、`libjemalloc_tsh.so`、`libmcheckb.so` | 名单外被忽略；名单内文件损坏/不兼容可能让 UI 进程起不来，**会影响正常启动**（中） |
| `/setting/mode/cmode` | 机身工厂模式（内容） | 读取：`a15 libObj.so sub_a3fc14`（`GetFactoryMode`，`strncmp("CC")`→1）；写入：`libObj.so sub_16679c`（`mkdir /setting/mode` + `fopen` 写 `"CC\n"`；参数为空则 `unlink`） | 内容以 `CC` 开头 → 工厂模式=1；缺失/其它 → 0 | 内容型。只影响功能/命令，不影响启动。出厂镜像里是“已删除的 3 字节文件” |
| `/setting/sen/smode`（及 `/boot/sen/smode`） | 传感器模式（内容） | `a15 libsencore.so LoadSenserMode 0x176ac`；`a15 sen.elf sub_a0b8/sub_9f3c` | 若 `/setting/A_ZIT_BLINK` 存在读 `/setting/sen/smode`，否则读 `/boot/sen/smode`；前 4 字节 `"UU\n"`→1，其它→0；缓存到 `/var/.sen/.smode` | 内容型；错值退化为 0，不阻断启动。值 1 会改传感器模式（具体影响未验证） |
| `/tmp/jmode` | 机身 Jiritsu（tmpfs） | `a15 libJiritsu.so cmd_mode`（`+0x20`）、`CImJiritsu::jit_thread`（`+0x4da`） | Jiritsu 模式/调试 | tmpfs，不持久，重启消失 |

### 3.1 谁写“下一个更新模式”（补充表）

| 写入路径 | 写什么 | 地址 |
|---|---|---|
| 机身 UDTR0604 命令（`libObj.so`） | 先跑 `/usr/bin/us_remove_modes.sh`（`rm -f mode*`），再建 `mode` + `mode1`/`mode3`/`mode6` 之一；命令 0/2 = 只清空 | `sub_896204`、`sub_896008`；helper `sub_895f88`（跑脚本）、`sub_895fd8`（`open(path,O_RDWR|O_CREAT,0444)` 建空文件） |
| 更新器 UDTR0604 命令（`libupdater0604.so`） | 同上（`mode` + `mode1/mode3/mode6`） | `sub_1424`、`sub_15a0`；helper `sub_13bc`（跑脚本）、`sub_1250`（建空文件） |
| `up.sh` | `user`→`mode`；`serv`→`mode+mode3`；`ver`→`mode+mode6`；`ms`→`mode+mode5`；`keep`→`mode+mode1+mode4`（分发被注释） | `a15/bin/up.sh:15-102`，与 a1 2.03 完全相同（md5 一致） |
| `CurrentFirmware` 导出方法 | `SwitchModeToUpdater`→`mode`；`SwitchModeToVersionSkipUpdater`→`mode+mode6`；`SwitchModeToMsCryptUpdater`→`mode+mode5`；`StartUpdaterMode`→comp 存在时删 `mode6/mode3/mode`。**注意：这些方法没有找到直接调用者，见第 6 节第 5 条** | `sdfileinput.elf 0x10bb8/0x10aa8/0x10ca8/0x10dd0`；`libsdfileinputupdaterapi.so 0xfb7c/0xfa6c/0xfc6c/0xfd94`；`mf sub_e040/df30/e130/e258`；`sauu sub_14420/14310/14510/14638`；`crypter a1 sub_e08c/df7c/e17c/e2a4`、`a15 sub_da80/d970/db70/dc98` |
| `libupdatercommon.so` 基类 | `Create` 建空文件、`Delete` unlink、`IsValid` stat | `a15/lib/libupdatercommon.so`：`0x6a28` / `0x69bc` / `0x6998`；文件名常量 `0x7ada-0x7b35` |

注意：所有已验证的 `CompleteFlagFile` 调用都是 `IsValid`，**没有任何代码创建 `comp`**。出厂镜像自带它；谁在产线/PC 工具侧创建未证实。

`up.sh` 不带参数时还有两种切换语义（机身侧手动工具）：

- 已有 `mode` → `rm -f $UPDIR/mode*`（下次正常启动，不进更新器）
- 没有 `mode` → `touch $UPDIR/mode $UPDIR/mode1`（下次强制进更新器/产线链）

---

## 4. 你的 `mode5` 方案怎么用

### 4.1 生效条件

1. `mode`（不带数字）必须同时存在（2.03+）；2.00 可只放 `mode5`。
2. 不能有 `mode3`、`mode2`、`mode6`、`mode1` 残留，否则按优先级截胡。
3. `comp` 必须存在（出厂即有），否则 `mode5` 不会被自动清除，更新链会反复触发。

### 4.2 为什么它是“一次性”的

`UdtrMain.sh` 先读 `mode5` 决定走 MSCRYPT，然后 `execute_ufp.sh` 在挂载 `/setting` 后立刻 `rm -rf /setting/updater/mode*`（因为 `comp` 在）。所以本次更新能走 SD 链，但更新结束后旗标已消失；下次要再走需重新放入。

**不要为了让它常驻而删 `comp`**：那样 `mode5` 会一直留着，每次进更新器都跑 SD 链；同时 `/ramdsk/mode5` 会让 RVchk 的末段版本检查直接放过（允许降级）。

### 4.3 风险排序（只列能影响更新的）

1. `uincomp` 残留：更新直接报错退出。
2. `mode1` 残留：反复进产线链，且不清除。
3. `mode3/mode2/mode6` 残留：覆盖 `mode5`。
4. `dat4` 被改：更新被拒/降级误判。
5. 更新中断（掉电）时正在写 FAT：目录项/簇链可能损坏（通用风险，不是旗标本身）。

---

## 5. 安全性总评：哪些能影响启动

- **`/setting/updater/*`：只在 a1 更新器里读。** 在 a15 里没有任何正常启动代码读它们（`bootin.elf`、`im.elf`、`sen.elf` 都不读）；机身 app 只是通过 UDTR0604 去**写**。所以在用户态范围内，更新旗标改错最坏是更新会话失败/循环。**但 bootloader/Jiritsu 是否会用这些旗标决定进 a1 还是 a7，未验证**（见第 6 节第 13 条）。
- **`/setting/mode/dmode`、`preload`：正常启动由 `bootin.elf` 读。** 这是唯一一组“改错可能影响开机/UI”的旗标。`preload` 还要求 `dmode` 含 `p` 才生效，且只接受 4 个白名单路径。
- **`/setting/mode/cmode`：只影响工厂模式开关**，内容必须是 `CC` 才有效；错值等于关闭。
- **`/setting/sen/smode`：错值退化为 0**；不会阻断启动。
- **内容型 vs 存在型：** 更新路由旗标都是存在型（空文件即可）；`dat4`、`cmode`、`smode`、`dmode`、`preload` 是内容型。把存在型旗标写成乱码不影响其意义；把内容型写成乱码会有上述后果。
- **出厂镜像状态：** `comp` 存在、`mode` 不存在、`cmode` 已删除。这意味着每次非产线更新都会先清 `mode*`（与你观察到的现象一致）。

---

## 6. 分不清（不要当结论用）

1. **`mode2` 的写入者**：`libupdatercommon.so` 里有 `Mode2FlagFile` 类，但 a1/a15 的所有二进制都没有构造它；`up.sh` 也没有 mode2 分支。下游读 `/ramdsk/mode2` 的代码没找到，实际效果约等于 USER，但未证实。
2. **`mode4` 的读取者**：完全没找到。`up.sh` 的 keepbackup 会写 `mode4`，但分发处被注释，且库中没有 Mode4 类。认定为死键。
3. **`comp` 的创建者**：a1/a15 所有相关调用都是 `IsValid`/`open`，没有 `Create`。出厂镜像自带；可能是产线/PC 工具直接写入 FAT，未证实。
4. **`MediaUpdateCompleteFlag` 的读取者**：a1/a15 都没有字符串引用；可能是 PC 端或后续启动阶段读取，未证实。
5. **`CurrentFirmware` 四个切换方法的真实调用者**：vtable 在 `mf/sauu/crypter/sdfileinput` 里都存在，但直接 `bl` 调用找不到；`sdfileinput.elf` 里连构造函数都没有调用者。可能是给外部 USB/PC 接口用的，或死代码。不能据此断定“更新器会自己写 mode5”。
6. **`im.elf` 对 `/setting/sen/smode` 的引用**（`sub_9612`，literal `0x96a0`）：只确认了字符串，具体用途未展开。
7. **`libInfraMediaCommon` / `libInfraMediaDetect` / `MPR_SCN_INSTALL_MAP_DEMOMOVIE` 对 `/setting/mode`、`cmode`、`smode` 的间接引用**：受 `md.skipdata` 和间接寻址影响，未解析。
8. **`libupdaterufp.so` 的 `dat4` 读取**：字符串在 `0x27ba`，调用链未展开。
9. **`libsencore NinThread` 写 `/ramdsk/dev/mode` 的 3 字节内容/含义**：只确认写了 3 字节；RVchk 只判存在。
10. **`dat4` 版本编码与比较方向**：确认读 2 字节、与 `information` 结构 `+4/+8` 打包值比较，但具体哪个方向算“降级”未逐位确认。
11. **RVchk 返回 -1 在上层的确切处理**：各调用点是否都中止更新未逐一确认。
12. **2.00/2.03 之外的其他固件版本**：以上地址/差异只对这两份 initrd 和 a15 有效。
13. **bootloader / Jiritsu 是否读 `/setting/updater/*` 来决定“下次进 a1 更新器还是 a7 正常系统”**：a1/a15 用户态代码里没有发现，但 bootloader 不在本次分析范围内，不能排除。

---

## 7. 复现与脚本清单（都在 `modes/`）

```sh
# 1) 解 a15（ext2）
python3 ext2_walk.py /Users/wubin/a7c-tasks/a7c-shared/nflasha15.bin extract a15
python3 ext2_walk.py /Users/wubin/a7c-tasks/a7c-shared/nflasha15.bin list --grep 'bootin|libObj|libupdater'

# 2) 列 /setting FAT12（本目录新增脚本）
python3 fat12_ls.py ls
python3 fat12_ls.py ls UPDATER
python3 fat12_ls.py ls MODE --deleted
python3 fat12_ls.py dump UPDATER/DAT4 /tmp/dat4.bin

# 3) 反汇编 / 字符串交叉引用
python3 elfxref.py refs   a15/lib/libObj.so '/setting/mode/cmode'
python3 elfxref.py dis    a15/lib/libObj.so 0x16679c 80
python3 elfxref.py pltcalls a15/lib/libupdatercommon.so 'BaseFlagFile'
python3 elfxref.py refs   /Users/wubin/a7c-tasks/a7c-shared/a1_initrd_203/usr/bin/sauu updater/debug

# 4) 全树扫字符串（已有输出）
python3 scan_mode_refs.py /Users/wubin/a7c-tasks/a7c-shared/a1_initrd_203/usr > scan_a1.tsv
```

| 文件 | 用途 |
|---|---|
| `elfxref.py` | ARM32 ELF 字符串/函数/PLT 交叉引用；`dis` 会标注 PC 相对字符串 |
| `elfutil.py` | ELF 解析/辅助 |
| `ext2_walk.py` | ext2 只读遍历/解包 `nflasha15.bin` |
| `fat12_ls.py` | FAT12 遍历/解包 `nflasha2.bin`（本目录新增，支持显示已删除项） |
| `scan_mode_refs.py` | 树内旗标字符串扫描 |
| `scan_a1.tsv` / `scan_a15.tsv` | 两份树的字符串扫描结果 |
| `a15_tree.txt` / `manifest.tsv` | a15 解包清单（路径/大小/md5） |
| `a15/` | a15 解包树（967 个文件） |

---

## 8. 工厂镜像里的直接证据

- `/UPDATER/COMP`：0 字节，簇 0（空文件）。
- `/UPDATER/DAT4`：2 字节 `00 02`（小端 0x0200）。
- `/MODE/cmode`：目录项已被删除（首字节 `0xE5`），但 LFN 仍是 `cmode`，簇 441，长度 3 字节——与 `libObj.so sub_16679c` 写入的 `"CC\n"` 长度一致。该簇已被释放并被其它数据复用，无法直接读回内容；结合 `GetFactoryMode` 的 2 字节 `strncmp`，可以推断出厂时 cmode 被写过又被删除（即出厂为正常模式，不是工厂模式）。
- `/setting/mode` 目录在镜像里存在，但除已删除的 `cmode` 外没有其它条目；`/setting/updater` 里只有 `comp` 和 `dat4`，所以“只放一个 mode5”的行为完全取决于 `UdtrMain.sh` 的版本（2.00 vs 2.03）。
