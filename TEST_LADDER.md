# 安全测试阶梯（降低变砖风险）

> 前提结论都来自本仓库的逐指令/包内分析（见 `FIRMWARE_MOD.md`、`UPDATES_ANALYSIS` 勘误在 `FIRMWARE_MOD.md` §1、`notes/jiritsu.md`）。
> 标注：【已验】= 有指令级/包内证据；【未验】= 只能上机回答。

## 0. 什么叫"砖"，谁能救

| 分区（A7C `mount.conf`） | 内容 | 写坏后果 | 可否救 |
|---|---|---|---|
| `boot0/boot1`（eMMC 硬件区） | SPL/引导 | 真砖 | eMMC 是焊死 BGA，需编程器/拆机【成本高】 |
| `nflasha1` (8 MB vfat，开机不自动挂；`partinf` 叫 “SYSTEM (Updater)”) | **确定有的**：`dat2`/`dat3`（`common.src: MS_MOUNT_POINT=/mnt` + `us_crc32sum_appli.sh` 挂到 `/mnt` 写这两个）；**同芯片强证据推断还有**：`boot/{vmlinux.bin, initrd.img(CRAMFS), kemco.txt, loadaddr.txt}` + **`p1chksum`（逐文件 MD5 清单）**【待 dump 定】。<br>★注意：`up.sh`/`us_mkfs.sh`/`crypter.elf`/`udtrbody.bin` **不在这里**，它们在 `nflasha15` 的 `/usr/bin/`（本轮实测） | 若真是 boot 分区：写坏 = 启动链坏（不只能刷） | **难**：包里根本不带它的镜像（`tar tf firmware.tar` 只有 a3/5/7/15）⇒ 唯一保险是自己双读的两份 dump。★但 **A7C 2.03 包里有 `0400_updater/dev/nflasha1`（8,323,072 B）**（本机 `/Volumes/Update_ILCE7CV203`）⇒ 出厂参照可用（见 `notes/updater_flow.md` §20） | 
| `nflasha2` `/setting` (20 MB) | **逐机校准**（`Backup.bin` 1,235,836 B 等） | 校准丢失=功能损伤（不是砖，但贵） | 只能靠事先备份 |
| `nflasha3/5/7/15` | /system、/wbi、/rootfs、/usr（app 本体） | im.elf 起不来 → UI 没画面、**Jiritsu 通道也随之消失** | **可救**：更新器 `us_mkfs.sh -m app` 会重建并写回 part_image 里的 a3/5/7/15【已验脚本内容】 |
| `nflasha6` (16 MB, 开机不挂) | Jiritsu 工作区（`/tmp/jiritsu`，原厂 `libJit.so`/`tmmc.jit`/`DIAC.csv`） | 不影响启动；worker 崩了也只是 `jinit` 残留 → 不加载 worker | 可救（覆盖式刷回原厂副本，前提是我们已把它拉回 PC） |
| `nflasha10` `/tmp=/etc` (12 MB) | `ld.so.preload`、`/etc` 配置；**`/tmp/jiritsu.bak.tar` 也落在这** | 写满 → **所有写操作报 0x10000009（含救援写）**【已验】 | 需重启清 tmp；`/etc` 写坏较麻烦 |
| `nflasha4` (12 MB raw，"MPR Flash Backup") | 包里没有它的镜像 | **每次官方更新的收尾都会擦它**（`endupdate.sh:94 ud_lerase.elf /dev/nflasha 4`）【已验脚本】 | 靠 `/setting/Backup.bin` 重建（同一脚本链） |
| `/setting/updater/{mode*,dat4}` + `/setting/mode/{dmode,preload}` | 更新模式旗标、更新器认定的版本号、启动子系统/preload 开关 | 写错 → 下次启动行为不对（不砖） | 用固件自带的 `us_remove_modes.sh`、`change_mode.sh`、`up.sh modver` 改回来【已验脚本内容】 |
| `nflasha11` `/log` (500 MB) | 日志/暂存 | 写满影响拍照日志，不致命 | 安全 |

**永不碰清单**：`boot0/boot1`（=`/dev/nflashaB0/B1`，只有 `pformat.elf` 会写）、`nflasha1`、`nflasha2`（校准，但见下：旗标文件也在这）、分区表。
**永不做**：`edisx.elf`（重写分区表）、`FORMAT`(0x4003) 命令、`uc_mkfs -m full`、往 `/etc`(nflasha10) 塞满东西。

**修正（本轮，见 `notes/updater_flow.md` §3–§5）**：`modeType='O'`/VERSKIP 不再是"同版本重刷的唯一出路"，
它只是**破坏最大的那条**（edisx + full + 还会 `ud_fsys_format /dev/nflasha24`）。
同版本重刷还有三条破坏更小的候选（机制【已验脚本】、效果【未验】）：
`up.sh modver <4位>`（改 `/setting/updater/dat4`，把"当前版本"改小 → 普通 `'U'` 包即可通过 `0x142`）、
`up.sh serv`（旗标 `mode3`）、`up.sh ms`（旗标 `mode5`）—— `us_mkfs.sh:39-47` 里
`USER/SERVICE/MINOR/MSCRYPT` 都**不跑 edisx**、`fmode=app`。

> 关键不对称：app 分区（a3/5/7/15）写坏 **不等于砖**——更新器能重建它【已验脚本逻辑】。
> 真正砖的只有 boot 链与分区表，而这正是我们**没有任何本地副本**的部分（包里只有 a3/5/7/15）。

**本轮的两条修正（详见 `notes/updater_flow.md` §16–§17）**：
- 一代自己的刷入枚度：`us_mkfs.sh` 里 `USER/SERVICE/MINOR/MSCRYPT` ⇒ **不跑 `edisx`** + `uc_mkfs.elf -m app`；
  `VERSKIP` ⇒ `edisx` + **`-m full`**（还加格卡）；`PRODUCT/LOADER_UPDATER` ⇒ `edisx` + `-m full`（除非有 `/tmp_updater/not_write_file/nwl`）。
  还欠：`-m app` 到底格 mount.conf 里哪几块（待反解 `uc_mkfs.elf`，已在手）。
- **★★ 272 B 尾到底谁验：`sauu` 是死代码；2.00 上 PC 可达的路径全都不验签**（详见 `work/sauu/SIG_VERIFY_200.md`、`notes/updater_flow.md` §25；**取代 §19/§21 的旧结论**）：
  - `sauu`(84,428 B，两版同) 对 `RSA_verify@plt(0xb60c)`/`PEM_read@plt(0xbb84)`/`RSA_free@plt(0xbae4)`/`SHA256@0xb940` 的**调用点 = 0**；`/etc/VerificationKey.pem` 字面量只是 `__FILE__`+`printf` 参数 ⇒ 验签代码被编进去但从没被调。
  - 2.00 的 `mf`（PROD/工厂路径，`execute_prod.sh` 里 `mf &`）**不链 libcrypto、无任何验签符号**；**2.03 才给 `mf` 加上**：`0xbd1c→0xc178` `PEM@0xc1d4`→`SHA256@0xc1ec`→**`RSA_verify(NID_sha256)@0xc200`**，失败 `ApiException 0x30002`（pem 打不开 `0x30005`）。
  - 2.00 上唯一真验签的是 **MSCRYPT(mode5) 的 SD 卡路径**：`sdfileinput.elf`（唯一 `DT_NEEDED` 该库，2.00/2.03 逐字节相同）→ `SDDecryptorModule::execWriteFirm@0xcba4` → `0xcc32 blx VerifySignature` → **`RSA_verify@0xde0c`**（都在 `libsdfileinputupdaterapi.so`）；`UFPDecryptorModule::exec_write_firm@0xc600`(bl@0xc69a) 全库 0 callers = 死代码。**PC 通道进不到 MSCRYPT**。该库 2.00/2.03 只差 5 字节/3 处（`BufferManager::Initialize@0xd040` 把 mmap 缓冲 `0x20000000`→`0x40000000` 即 512 MiB→1 GiB、栈帧 `0x830`→`0xc30`、`.ARM.extab` LSDA）⇒ **与验签无关，两版验签等价**。
  - `IAMSIGN` 是 **2.03 构建期烧进 a1 CRAMFS 的标记**（`/root/IAMSIGNENABLED` 0 B，无人写只被读）：2.03 `libupdater0604.so` 的 `udtr_adjcmd_get_verifysign` stat `/tmp_updater/root/IAMSIGN{ENABLED,DISABLED}` = **能力查询，不是运行时开关**；2.00 无此概念。
  ⇒ **结论：在 2.00，USER/SERVICE/MINOR/VERSKIP/PROD 全都不验 272 B 签名**；相机侧真正会验的是 `crypter.elf` 的 **DEND CRC32**（四份 `crypter.elf` 都有 `CrcChecker@0xb408`，poly `0xEDB88320`，读尾 12 B `memcmp(buf+8,"DEND")`+比对，失败打印 `calc_crc`/`getHd_crc`@`CrcChecker.cpp:89`）⇒ **重算 CRC 就能过**。
  ⇒ **路线 A（改包重刷）从“默认不可行”升为“很可能可行”**；代价是**刷到 2.03 之后 PROD 路径会被 `mf` 拦**（要留后路就别在 2.03 上做篡改刷）。
  ⇒ 引擎也钉死了：PC 侧（a15 `libIMDB→libupdaterufp` 门禁 + `crypter.elf`）**只写旗标**（`mode/mode1/mode3/mode6`）→ 重启 → a1 `UdtrMain.sh→execute_ufp.sh` 才真正写分区。
- **`/dev/nflasha1` 现在有出厂参照了**：A7C 2.03 包内 `0400_updater/dev/nflasha1`（8,323,072 B，`work/v203/nflasha1_203.bin`），**且与 ZV-E10 2.03 的 a1 逐字节相同**（同一 sha256 `c9040270…`；`boot/initrd.img` 的 MD5 `bb50bfb5…` 也与另一项目文档记的一致）⇒ 升级器分区跨机型共享。
  ⇒ **L1 的 dump 清单里必须含 nflasha1**，拉回来第一件事就是与 `work/v203/nflasha1_203.bin` 做 diff（看哪些字节是逐机的）。

---

## 0.5 判定语言：证据分级与恢复分级（本文件唯一允许的风险说法）
**旧的“风险≈0”一律作废。**每条结论/风险都要带级别标签；能不能进入下一级真机写入，由级别决定。

**证据分级（这条结论从哪来）**
- `E0 静态分析`：从 ELF/脚本/配置/反汇编读出来的。
- `E1 离线模拟`：mock、arm32 容器、QEMU 里跑出来的。
- `E2 同芯片他机实测`：别的项目在同型芯片（ZV-E10 等）上验过的 ⇒ **只能当参考，不能当本机判据**。
- `E3 本机实测`：这台 ILCE-7C / FW2.00 / `bcdDevice=0x200` 上直接观测到的（含双读一致这类）。

**恢复分级（“写坏了能救回来”这句话的可信度）**
- `R0 推断`：从脚本/代码逻辑推出“应该能重建”。
- `R1 离线演练过`：在 QEMU/mock 里把“损坏 → 用某条路径重建 → 验证”整条走过。
- `R2 本机验证过`：在这台相机上真的写坏过又救回来过（或至少把“写→读回一致→重启行为正常”走通过）。

**硬规则（取代“有恢复机制所以可以继续”）**
1. 任何真机**写入**，其依赖的恢复路径必须 **≥R1**；只有 R0 的恢复路径**不得**作为进入下一级的理由。
2. 写入通道本身必须 **≥E3**：先在一个**低价值分区**上把“写 → 读回逐字节一致 → 重启后行为正常”走通（= 把写机制从 R0 抬到 R2），才允许对 app 分区写。选哪个分区见新增的 **L4.5**。
3. **写不自动重试**；重试只允许“先读回定状态、再决定”的手动流程。读命令的自动重试可保留。
4. 每级都要填 §0.7 的验收表；任一格不确定 = 本级不通过，不得顺延。
5. 版本边界：结论只在 `(机型, FW 版本, 工具版本, 包哈希)` 四元组内有效；任一变了 → 前一级判据**不沿用**，重跑 preflight。

> **死结与解法**：要证明“恢复”必须先能“写”。所以顺序不是“先找到最强的写入入口”，而是：**先拿最低价值分区把写通道实测**（规则 2），再谈 app 分区。

## 0.6 不可逆边界（没副本、也没软件恢复路径的东西）
先把“没了就真没了”钉住，不用“还有救援方法”含糊带过：

| 区域 | 副本现状 | 没了会怎样 |
|---|---|---|
| eMMC boot 区（设备偏移 `0x0–0x10000`，EXBL/boot0；`boot0/boot1`） | **无副本**（`partinf.conf` 从 `0x10000` 起，包内也没有） | 引导链没了＝砖，只能外部编程器/拆机 |
| `nflasha1`（boot 分区，2.00 官方更新**从不重写**它） | 只有自己的 dump（**双读一致**，`sha 82e1b199…`） | 同上：只能自己写回，而写回能力尚未实测（R0） |
| 机身独有、**尚未 dump** 的分区：`a3(机身)/a11/a12/a16/a17/a18/a24` | **无副本** | 若含逐机校准/标识（`DIAC.csv` 校准、`/lens`）⇒ 不可逆损失（不是砖但补不回来） |
| `nflasha6`（Jiritsu 载荷区） | 有机身 dump（16 MB 双读一致） | 载荷可重建；逐机 hash 表/日志丢了不可逆（次要） |

⇒ 新增 **L1.5「备份完备性」**（只读、便宜）：上表第 3 行全部补 dump，并建 `work/BACKUP_MANIFEST.tsv`（`路径 | 期望字节数 | sha256 | 两份离机副本位置`）。**清单不全 ⇒ 之后一切真机写入不获授权。**

## 0.7 每一级的验收表（格式固定，缺格即不通过）
| 项 | 必须写什么 |
|---|---|
| 进入条件 | preflight 六项（§0.8）+ 上一级判据逐项复核记录 |
| 操作边界 | 本级允许的路径/opcode/设备，逐条列出（黑名单不靠记性） |
| 通过判据 | 期望状态码 + **字节数** + sha256 + 文件系统结构变化（新增目录项偏移）+ 重启后状态 |
| 停止条件 | 任何未知返回值、字节数不符、`cmp` 不一致、出现 `mode*` ⇒ **立即停**，不进入下一步 |
| 失败处置 | 保留日志与快照；**不得自动重试写**；先读回定状态 |
| 退出核对 | 与进入前 diff（`/setting/updater/` 目录清单、`comp`/`dat4` 字节、无新旗标） |

## 0.8 preflight（每次真机会话的第一条命令，不过就不许做任何事）
`jiritsu_send.py preflight` 要打印并核对以下六项（任一不符→退出）：
1. 设备身份：`054c:0d29` + `bcdDevice=0x200` + product 串 `ILCE-7C`（**不是** `054c:0d2a`/MTP，也不是另一台机身）。
2. 固件版本：`/setting/updater/dat4` 与 a7 里的 `/version.txt`（sha 已知）都等于预期的 **2.00**。
3. 工具版本：`tools/jiritsu_send.py` 的 sha256 与 `work/TOOL_HASH` 记录一致（含 padding 修复）。
4. 备份清单：`work/BACKUP_MANIFEST.tsv` 存在，且本级要动的分区在清单里（含两份离机副本）。
5. 旗标状态：`/setting/updater/` 下**无** `mode*`（有就先处理，别在带旗标的状态下做其它实验）。
6. 只读/写入模式：默认**只读**；写必须 `--allow-write` + 白名单同时命中（§0.9）。

## 0.9 执行边界落在代码里，不落在纪律里
- `jiritsu_send.py` 默认 **RO**：写类子命令（`fput/put/del/fdel/写回`）没 `--allow-write` 就直接拒绕并解释。
- 写路径**白名单**按级写死在工具里（例：L2.5 只允许 `/tmp/zzprobe`、`/setting/updater/zzprobe`、`/tmp/jiritsu/zzprobe`）；白名单外 → 拒绕 + 非 0 退出。
- **写不重试**：现在 `wrap2.sh` 对任何 `rc≠0` 重试 5 次 ⇒ **对写就是“同一文件可能被写 1–5 次”**（真实缺陷，已发现）。重试循环只对读命令生效；写命令要重发必须先 `fget` 定状态。
- 失败即停：脚本序列用 `set -euo pipefail` + 每步显式判据（`cmp` 不一致就 `exit 1`），不允许“打印警告继续”。

---

## 1. 阶梯（每级：目的 / 动作 / 通过判据 / 失败后果 / 回滚）
> **执行顺序**（标题位置≠顺序；本轮新增的级别排在后面只为不动原文）：
> `L-1 → preflight → L1 → L1.5（备份完备性）→ L2.5（文件级写，单独授权）→ L4（备份分区）→ L4.5（写通道实测）→ L0/L0.5 → L3 → L5 → L6 → L7`；
> **L2（代码执行）与 L0'（改载荷重刷）不在常规序列里**，需各自单独审批（L2 要恢复能力 ≥R1；L0' 先做 QEMU/离线专项）。

### L-1 主机侧预演（**E1 离线模拟通过**；已完成）
> 边界（按审查要求写清）：mock 验的是**帧封装 / 读写逻辑 / tar 行为 / 护栏**；**不覆盖**真机 USB 服务状态、挂载态、异常恢复、超时、部分写。所以这一级的说法不是“风险 0”，而是“软件测试通过”。
- arm32 容器（OrbStack，M 芯片原生 armv7）里 dlopen 我们的 `libJit.so` 并按 `jit_thread` 的调用序列跑 `Create→Load→Run→Destroy`【已验 PASS】。
- **已做**：用**相机自己的 busybox v1.29.3（+ glibc 2.11.2）在 arm32 容器里离线跑**，按相机一模一样的命令 `tar xpf /w/jiritsu_firm.dat ./ -C /tmp/jiritsu` 解我们的载荷 → **rc=0**，三个文件落点对、mode 对（libJit.so 755）【实测】。方法见 `notes/toolchain.md`（`work/cambb.sh`）。
  - 发现并修了一个真 bug：载荷里**必须有 `./` 目录项**，否则相机自家 busybox 会“解出来但返回 rc=1”（`tar: .: not found in archive`）→ 可能被 `set_firm` 当解包失败（`0x10000010`）。`tools/jiritsu_pack.py` 已修（新载荷 MD5 `1abcd4fa9b98df8a0eb90eaa28bd577d`）。
  - 另外证实：busybox 会把成员名里的 `../` 剔掉 ⇒ **靠 tar 成员越出解包目录不可行**【实测】；越界写要靠 `SET_FILE2` 的路径穿越，而不是 tar。方法固定成工具：`tools/camuser.sh` + `tools/camprefix.sh`。
- **已做**：`tools/jiritsu_send.py --mock`（假 Senser 服务，`/dev/*` 回退到固件包里的**真分区镜像**）跑通 L1/L2 的全部非-USB 逻辑：`dump nflasha7` 与包内镜像**逐字节一致**、`put→get` 回读一致、Jiritsu framing 与同芯片实证的 camtool **逐字节一致**；护栏（不发 0x4003/0x4006/0x4005、`del` 遇 `/` 或 `*?[` 需 `--allow-danger`）都测过。

### L0 只改 header 的官方刷 —— 只能验证“改包能被接受 + 门禁按预期中止”（**E0/E1；本机的“写盘前一定停”尚未实测**）
- 刷 `/tmp/ILCE7CV200.region1.dat`（只把 `region 0→1`，与原包差 36 字节，尾部 272 B 原样保留）。
- 预期：`0x141` 区域不匹配，**在写盘之前安全中止**（门禁在 `/usr/lib/libupdaterufp.so`、跑在正常模式的 `im.elf` 里，`0x127c`）【已验】。
- **重要修正**：`model/region` 永远要过（`verskip` 只跳过版本比较）⇒ **这个包测不出签名**（它在验签之前就停了）。它只能证明：改过的 .dat 能被 PC 应用接受、更新链路能进能退、相机无损。
- **测签名的正确探针**（同样零风险，因为会在写盘前失败）：只**翻 CBC 区 1 个字节**（尾部 272 B 不动、不重算 CRC）。
  **【新判定】预期只会报 CRC 类失败**（`calc_crc`/`getHd_crc`），因为 2.00 根本没有签名校验层，只有 `crypter.elf` 的 DEND CRC32（见上条）。若反而报别的硬失败 ⇒ 说明还有我们没建模的校验层（`ldec` 硬件级），那才是需要追的信号。
  真正能证明“改过的载荷会被写进去”的探针是 **L0'**：**翻尾部 272 B 里 1 bit + 重算 DEND CRC32**（预期 2.00 不拦）。
- **不要用** `…modeO.dat`：`modeType='O'` ⇒ `up.sh ver` ⇒ 旗标 `mode mode6` ⇒ VERSKIP ⇒ `edisx` + `-m full` + 擦 nflasha24（`us_mkfs.sh:39-77`、`endupdate.sh:94-101`）【已验脚本内容】。
- 顺带一条安全垫：`/usr/bin/up.sh`（无参数时）会 `touch /setting/updater/mode mode1`＝下次进更新模式；
  要撤销用 `/usr/bin/us_remove_modes.sh`（`rm -f /setting/updater/mode*`）【已验脚本内容】。

### L0.5 兜底链路演练（目标不变，但同版本重刷会被拦）
- **新发现**：`0x127c` 里 `firm_version <= set_version → 0x142`，`verskip` 只跳过版本比较 ⇒ **同版本 2.00→2.00 重刷会直接报 `0x142`**，除非用 `'O'`（VERSKIP，会 `edisx` + `-m full` 全盘重建）【已验】。
- 所以“温和版演练”只能做到：刷 `region1` 包 → 确认能进更新流程、PC 应用接受改过的包、相机无损伤（不重建任何分区）。
- “写坏了能用官方更新器重建 app 分区”要想真验证只两条路：①用 `…modeO.dat`（接受全盘重建，先取走 `/setting`+`/log` 里自己的东西）；②先走路线 B 拿到代码执行，那时靠自己的 `dd` 备份 + 读回校验，**不必再依赖官方链路兜底**（这是选路线 B 的一个重要理由）。
- **新增的低风险做法（代替 ①）**：拿代码执行后先 `up.sh modver 0000`（改小 dat4 里更新器认为的当前版本），
  再用**原包原样的 `'U'` 头**做一次 USER 模式重刷 —— USER 模式 `fmode=app`、不动分区表、`ud_keep_backup -s` 会恢复 `Backup.bin`
  【机制已验，效果未验】。要付的代价：`nflasha4` 被 `ud_lerase` 擦、`uc_mkfs -m app` 重建 a3/5/7/15。
- ⚠ **旗标地雷（本轮发现；每次刷完都要检查）**：本包**有** `appli` 段（`0800_appli`，4 MB 镜头文件），其后处理脚本
  `us_crc32sum_appli.sh` 跑完会 **`touch /setting/updater/mode` + `mode6`**（Version Skip 旗标）。
  ⇒ 一次“温和的 USER 更新”可能让**下次启动又进更新模式、且以 VERSKIP 跑 `edisx` + `-m full`**【已验脚本内容；下次启动到底怎么读旗标【未验】】。
  刷完先用只读看一眼 `/setting/updater/`（旗标、`dat4` 现值），需要时用固件自带的 `us_remove_modes.sh`（`rm -f /setting/updater/mode*`）清掉。
- **救援阶梯（低于 Jiritsu 层，全部是固件自带机制）**：`/setting/mode/dmode`（`change_mode.sh` 0–6：可以只起 kernel、不起 appFw）、
  `/setting/mode/preload`（`change_mode.sh p <lib>`；Sony 自家就用 `/usr/tool/{libkmcsup,libsonyefence,libduma}.so`）、
  `nflasha3` initrd 的 `sbin/init` 里可见 `launch_shell()`/`/bin/ash --login` 与 `/usr/bin/launch_shell.elf`（在 `/dev/console`/`/dev/ttycons` 上给 shell）
  【已验字符串/符号；串口是否被 `/setting/kemco.txt` 的 `console=ttynull0` 静音，一代的 kemco.txt 在 nflasha1 里，未 dump ⇒ 未定】。
- 若决定真跑一次官方刷（不管哪个包）：电池 ≥3 格、更新中不拔 USB/不关相机、先取走 `/setting`与`/log` 里自放的文件，完成后核对版本号与校准（对焦/防抖表现）。

### L1 服务模式，纯只读（**E3：只读本机已实测跑通**；“读不会触发副作用”仍是静态推断）
- 进服务模式（USB `054c:0336`）→ 用文件读命令（`GET_FILE2 0x4011`）把 `/tmp/jiritsu` **全部**拉回 PC：`libJit.so`、`tmmc.jit`、`DIAC.csv`、`ver.txt`、`jcount`、`Cam_AdjustGuide_Files/*`，逐个 SHA-256 记录。
- 只读能力可以**用现成工具**：`pmca-console serviceshell` 用的命令在一代全实现（`libsencore.so`）：文件读 `PFUNC=0xff01 FileControl`、备份读 `AdjustControl(0x603,1)`（`CUsbSvc::ReadDataFromBackup@libInfraUsbCmn 0xd0f0`）、内存读 `PFUNC=0xff03 MemoryDump`。
  **但两个期望要降维**：①这一代的"终端"`(0x601,0x1f)` 执行的是 `/usr/bin/ulogio.elf it|ot`（日志控制台），**不是 `/bin/sh`**；②一代 Jiritsu 的 `cmd_debug` 是空桩（`0x4da8`，42 字节）→ 命令 5 不给代码执行【已验指令级】。
  **写类命令先不用**：`writeBackup(0x603,2)`/`saveBackup(0x603,3)`/`setBackupProtection(0x603,15)` 会写校准区，未备份前不得调用。
- 顺带只读探测：`df`（/tmp 剩余空间，备份 tar 要落在那）、`ls /dev/nflasha*`、是否存在 `/tmp/jbusy`、`/tmp/jiritsu/jinit`、`/tmp/jiritsu.bak.tar`，以及 `/setting/updater/` 里的 `mode*`/`dat4` 与 `/setting/mode/{dmode,preload}` 现值（改之前必须先记下原值）。
  **分区表已不用猜**：包里 `0300_partconf/partinf.conf` + `0100_config/mount.conf` 给全了 —— A7C 一代确实有
  `nflasha16` `/android/system` 140 MB(raw)、`nflasha17` `/android/data` 100 MB(vfat)、`nflasha13` 4 MB UpdaterWork、
  `nflasha12` 40 MB /cert、`nflasha18` 20 MB /lens、`nflasha23` 2 MB PMBP（`mount.conf` 全文见 `notes/updater_flow.md` §4）。
  但**别照抄 camtool 把 a16 当"全零 scratch"**：一代 partinf 标的是 "Android(system)"，内容是否有用未知 ⇒ 只读优先。
- **分区整段备份不需要代码执行**：同芯片的 `dump_flash.py` 是用 **`FileControl(0xff01)` 直接读块设备**（`jiritsu_lib.py:152-169`：hdr=`<HH cmd,len>` + 4 字节对齐的 latin1 文件名）⇒ 在拿到代码执行**之前**就能把 nflasha3/7/15/6 整段拉回 PC（`camtool` 称可“整段读写块设备”）。【同芯片实测】
  **一代已实测走通**：`FileControl READ /dev/nflasha1` 返回 **8,323,072 B = partinf 里 a1 的长度**（0x007F0000）【真机一次，待第二次读交叉确认】。
- **读到的长度必须等于 partinf 给的分区长度**（工具已自动校）：a1=8,323,072；a6=16,777,216；a7=8,388,608；
  a3=50,331,648；a5=62,914,560；a15=314,572,800；a2=20,971,520【已验：包内 `0300_partconf/partinf.conf`】。
  注意**包内镜像比分区短**（a3 30,290,944 / a5 32,577,024 / a7 4,992,000 / a15 239,982,592），所以 `--mock` 演练里会报“长度不符”——那是演练而非错误；**真机读短了就是读坏了**。
- **一切实操先过 `--mock` 预演**（现在 mock 会用包里的真东西当机身配置：`partinf.conf`/`mount.conf`/`kemco.txt`/`version.txt`，
  并按已验编码合成 `dat4=00 02`、`dat2=19 00 03 91`、`dat3=0000`），`nflasha1/nflasha6` 在 mock 里必然读失败（包里根就没了这两块）。
- **判据（硬性门槛）**：拿到原厂 `libJit.so` 的完整副本。**没拿到就不许进 L2**（否则刷上去就再也回不去）。
- **两次独立读已内置**（`--twice`，默认 2）：同一路径读两份、比 sha256，不一致就报“不能当备份”；想快（/usr 300 MB）可 `--twice 1`，但写前至少补一次对读。
- 具体命令（一条包干拉完，全只读）：
  ```sh
  python3 tools/jiritsu_send.py --mock l1 --dir work/l1_mock          # 先离线演练
  .venv-jir/bin/python tools/jiritsu_send.py scan                    # 看 PID：A7C 应先 0E8A，鉴权后 0336
  .venv-jir/bin/python tools/jiritsu_send.py l1 --dir work/l1 \
      --dump nflasha1,nflasha6,nflasha7                              # nflasha1 包里没得，必须从机身拉
  # 要加 /usr（300MB，慢）就 --dump nflasha1,nflasha6,nflasha7,nflasha15 --twice 1
  ```
  `l1` 现在还会自动拉回 `/setting/{partinf.conf,mount.conf,kemco.txt}`、`/setting/updater/dat4`、`/mnt/dat2`、`/mnt/dat3`、`/version.txt`，
  全部可与包内出厂版直接 diff（已验：包内同路径文件存在）——这能回答两件事：**机身分区表与包里的 partinf 是否一致**（不一致 ⇒ VERSKIP 会重划盘）、
  **机身 kemco.txt 与出厂版是否一致**（否则改串口开关前先存原值）。
  工具会自己：鉴权（MSC→0336→服务）、默认不发 3/6/5 等危险命令、状态码翻译成可读文字、dump 完就地扫 vfat 目录项（dat2/dat3/chassis/udtrbody…）。

### L2 ★重新分级：这不是“写文件”，是**代码执行**测试（`SET_FILE2` → dlopen → 跑构造函数）
> 审查结论（对）：“worker 只写一个测试文件”是**预期行为**，不是系统强制的权限限制。dlopen 一旦执行构造函数，跑的就是任意代码；`jinit` 熌是**哨兵（熌断标记）不是自动回滚**。本级改为**高风险代码执行**，进入条件：
> - 原厂 `libJit.so` 副本已在手（从 a6 空闲簇恢复出 409,551 B，`work/l1-camera/a6_extracted/a6_libJit_recovered.so`）【E3】，且**把它写回去的路径**先经 **L4.5** 实测（≥R2）；
> - 独立记录的恢复方法（写回原厂库的具体命令序列）+ 停止条件（崩过就不往同一个会话里堆，先重启相机）；
> - 恢复能力未达 **≥R1** 之前，**不进入本级**。

（以下为原 L2 正文）
- ★**编号写法备忘**（本轮纠正）：上线时 Jiritsu 帧里 `code` 字段发的是 **`struct.pack('<HH', 0x1001, N)`，N = 2/4/15/16/17/18（十进制）**，
  与同芯片实证的 camtool 完全一致（`jiritsu_lib.py:136-149`：`select(15)`→`read(17)`/`write(16)`/`delete(18)`，载荷小头 `00 ff 00`）。
  本文里 `0x400f/0x4010/0x4011/0x4012` 只是命令名别名；**往真机发 `0x4011` 那种写法会因表外命令被拒（上一轮就是因此报错）**。
- **主路径改为写文件，不是刷 tar**：同芯片实测红线“**`FORMAT(0x4003)` / `FIRMUP(0x4006)` 会卡死服务模式，不要发**”（`Sony-ZVE-10-Camtool/README.md:358`）【同芯片实测】→ 发 `set_firm`（0x4006）降为备选（工具与 `work/jiritsu_firm.dat` 已备好）。
- 做法：**`SET_FILE2(0x4010)` 把我们的 `libJit.so` 写到 `/tmp/jiritsu/libJit.so`**（同芯片实测：只有走 `write(16)` 才会触发 dlopen；用 `0xff01` 写同一路径**不会触发加载**，`cam.py:434-436`）。`MOUNT(0x4002)` 可发可不发——SET_FILE2 在 `mode=0` 时会自己挂 nflasha6（@`0x5b48`）【已验（指令级）】；但**写 `libJit.so` 要求 `/tmp/jbusy` 不存在**。载荷里同时带**原厂 `libJit.so` 的备份副本**（存 PC + 存 /log）。
- worker 行为最简：只写 `/tmp/jiritsu/WORKER.VER`（**不要** `system()`、不要 dd）。**干活要同时挂在 `.init` 构造函数里**：同芯片证实 ctor 在 dlopen 时就跑，而 `RunScriptI` 需要引擎发脚本请求（上机前无法预知它会不会被调）。
- 通过判据：读回 `WORKER.VER` 是我们写的 ⇒ 代码真的在相机进程里跑起来了。
- 失败与恢复（【同芯片实测】的错误码，见 `notes/camtool.md` §5）：
  - `write(16)` 返回 `0x10000000` ⇒ 空/非法 ELF，dlopen **干净失败**（没崩，可直接重试）。
  - `write(16)` 抛 USB 异常 ⇒ 载荷在 dlopen 阶段崩，**`im.elf` 死后相机会自己重启（30–40 s）**，等 60 s 再连；不必拔电池（A7C 不靠 USB 供电，但同样先拔线再断电）。
  - 同一会话里再写都不生效 ⇒ **dlopen 按名字缓存** ⇒ 改文件大小（pad）或重启相机。
  - 误删 `/tmp/jiritsu/libJit.so` ⇒ Jiritsu 会**卸载 nflasha6**（读返回 130），用 `0x4002` 重挂，数据不丢。
  - 一代自己的崩溃哨兵：`/tmp/jiritsu/jinit` 残留 → jit_thread 不加载 worker（不循环崩、也不自动恢复）→ 要把**原厂 libJit.so 刷回去**。
- 备选（才用 `set_firm`/FIRMUP 时）的回滚事实：报错（`0x10000009`/`0x10000010`）时备份留在 `/tmp` ⇒ 下次开机自动 `sys_tar_extract` 自愈【已验 0x75ce-0x7604】；刷成功则 `bak.tar/bak.hash` 被删（`0x6a36/0x6a40`）⇒ **没有自动回滚**。
- 具体命令（先离线演练再上机）：
  ```sh
  # 0) 离线：帧长/字节先看对（不需要相机、不需要 pyusb）
  python3 tools/jiritsu_send.py frames 'sel=/tmp/jiritsu/libJit.so' \
      'w16=/tmp/jiritsu/libJit.so:tools/jit_worker/libJit_padded.so'
  python3 tools/jiritsu_send.py --mock put /tmp/jiritsu/libJit.so tools/jit_worker/libJit_padded.so
  python3 tools/jiritsu_send.py --mock get /tmp/jiritsu/libJit.so - | cmp - tools/jit_worker/libJit_padded.so
  # 1) 真机（相机进服务模式、线直接接 PC；venv 已有：.venv-jir）
  .venv-jir/bin/python tools/jiritsu_send.py scan
  .venv-jir/bin/python tools/jiritsu_send.py put /tmp/jiritsu/libJit.so tools/jit_worker/libJit_padded.so
  .venv-jir/bin/python tools/jiritsu_send.py get /tmp/jiritsu/WORKER.VER work/l1/WORKER.VER.got
  .venv-jir/bin/python tools/jiritsu_send.py get /tmp/jiritsu/cmd.log -      # 带 cmd.txt 后读回输出
  ```

### L1.5 备份完备性（新增，必做；只读）
- 目的：把 §0.6 表里“无副本”的**机身独有分区**（`a3 机身/a11/a12/a16/a17/a18/a24`）全部 dump，戒掉“拿包内镜像当真机备份”的错觉。
- 动作：`dump <dev> --twice 2`（双读一致才算）→ 建 `work/BACKUP_MANIFEST.tsv`（路径/期望字节数/sha256/两份离机副本位置）→ 镜像 `rsync` 到相机外的第二台机器。
- 判据：每分区字节数 == `partinf.conf` 期望值（**长度不符 = 直接失败**，hash 相等也不能免责）；关键分区再抽一个已知文件做结构校验（如 a15 里 `crypter.elf` 的 sha）。
- 回滚：无（只读）。失败：换线/重插再来，无副作用。

### L4.5 写通道实测（新增，关键：把“写”从 R0 抬到 R2）
- 选**最低价值**分区做第一次真写（候选：`nflasha13` = 4 MB 更新日志；或 `nflasha10` = /tmp 12 MB）：整段 dump → 写回**同一内容** → 双读比对 → 重启 → 重读 → 确认相机行为无变化。
- 目的：只回答一个问题——“我们的写通道能不能把字节原样写进 eMMC 并读回”。成功 ⇒ 写入机制变 **E3/R2**，L5/L6 才有资格；失败 ⇒ **所有真机写入计划暂停**。
- 风险：选 a13/a10 写坏几乎无损（日志/临时盘）；写错分区（比如误写 a2）则直接按 L5 处理。
- 前置：L1.5 清单全绿；写前 preflight；写后按 §0.7 退出核对。

### L2.5 FileControl 的**文件级写**能力（新增，最便宜的一档，风险低）
- 背景：修了 padding bug（`4-len%4` 在已对齐时多补 4 个 NUL ⇒ 之前一律假报 `130`）之后，FileControl(0xff01) 对运行系统**全线可读**（`/usr/bin/{crypter.elf,udtrbody.bin,up.sh,sen.elf,change_mode.sh,us_remove_modes.sh}`、`/usr/lib/{libupdater*,libJiritsu,libsencore}.so`）。**写（cmd=1）还没试。**
- 三档递进（每档都：写哑文件 → 读回 → **拔电重启再读回** → 不行就 `fdel`）：
  1. `/tmp/zzprobe`（= nflasha10，vfat）→ 预期可写；顺便验证“a10 上的写跨重启持久”。
  2. `/setting/updater/zzprobe`（= nflasha2，vfat）→ **这一档最重要**：能写就等于我们可以自己下旗标（`mode1`=PROD 工厂路径 / `mode2`=SERVICE），而 2.00 的 PROD 路径 `mf` **不验签**；回滚只要 `us_remove_modes.sh`（`rm -f /setting/updater/mode*`）或 `fdel`。
  3. `/usr/lib/zzprobe`（= nflasha15，**ext2 ro 挂载**）→ 预期 `EROFS`；若竟然可写且跨重启持久，才有资格谈“换单文件”（否则遵守 L5 的整盘写回红线）。
- 通过判据：读回字节一致 + 重启后仍在（或按预期消失）+ 相机行为不变（无旗标残留、正常开机）。
- 失败后果：哑文件，`fdel` 即可；**旗标写错**才是风险 → 必须紧跟 `us_remove_modes.sh` 复核。
- ★**落点不是“临时目录”那么直觉**（`firmware.tar_unpacked/0100_config/mount.conf`：`/dev/nflasha6 none vfat 16777216`——**挂载点是 `none`，不自动挂**；`/dev/nflasha10 /tmp vfat 12582912`）⇒ **写 `/tmp/jiritsu/*` 落在 a10 还是 a6，取决于这一刻 a6 有没有被 `MOUNT(0x4002)`/`MountMediaI` 挂上**。判定法：写前 `dump nflasha6` → 写 → 再 `dump nflasha6` → `cmp -l` 看新目录项。**未判定前不要把 a6 当目标。**
- ★**持久化写入需单独授权**（不因叫 `zzprobe` 就默认无害）：a2 含逐机设置/校准备份与更新器状态；a6 是逐机载荷区。每档写入前要写明：目标分区、已有几份副本、写失败时的处置。
- ★**写命令禁自动重试**（`wrap2.sh` 重试 5 次 = 对写可能写了 1–5 次）：`fput` 非 0 或超时 → **先 `fget` 定状态**再决定重发；每次写后记录实际字节数（回答“截断还是追加”）。

### L3 worker 只做只读探测（**前提是 L2 已过 = 已在跑任意代码；“命令只读”不等于无副作用**）
- worker 里 `system("id; mount; df; ls -l /dev/nflasha*; cat /proc/mounts")` → 输出 `cmd.log` 用 `GET_FILE2` 读回。
- 判据：确认 uid（是否 root）、`/dev/nflasha15` 等设备是否可打开、当前挂载状态。
- 这一步回答"能不能 dd"这个问题本身；不做任何写。

### L4 备份分区（首选：`0xff01` 直接读块设备；worker 内 `dd` 是备选）
- 首选（不需代码执行）：`FileControl(0xff01)` 整段读 `/dev/nflasha15/3/7/6/2` → 存 PC；写回用同一条通道（`restore_flash.py`）。
- 备选（worker 内）：`dd if=/dev/nflasha15 of=/log/jitbak/nflasha15.img bs=65536` + `sha256sum` 清单（/log 500 MB 装得下 300 MB）。若一代有 `nflasha16`（ZV-E10：140 MB 全零空白）则优先用它当暂存。
- worker：`dd if=/dev/nflasha15 of=/log/jitbak/nflasha15.img bs=65536`（/log 500 MB 装得下 300 MB）+ `nflasha6/3/7/10`；写完 `sha256sum` 落到 `/log/jitbak/SHA.txt`。
- 判据：读回 SHA 与 PC 侧比对；重启后 `/log` 仍在（flash 上，不会掉）【已验 /log 是 nflasha11】。
- **这是唯一可接受的"大改前的备份"**：因为通道自带的 `.bak.tar` 只覆盖 `/tmp/jiritsu`，成功后还会被删。

### L5 写 app 分区的正确粒度：**整分区写回**，不是运行中改文件
- 同芯片红线（`README.md:356-357`）：**改 `/usr` 或 `/` 必须“整盘 dump → 本地改 → restore 整盘写回”；禁止运行中局部写**（页缓存不一致 → ext2 错误）；`nflasha15=/usr` 是 **ext2 ro** 挂载。【同芯片实测】
- ⇒ 我原先建议的“`remount,rw` + `touch /usr/JITTEST`”做法**作废**；改成：先 L4 整段 dump → PC 上改镜像 → 整段写回 → 重启验证。
- 风险提升一级：整盘写回万一写错就是整个 `/usr` 没（仍在“可重建”范围内，但需先确认能重建）。

### L6 在镜像里改一个文件（本地改，不是相机上改）
- 在 PC 上对已 dump 的 ext2 镜像挂载（或 `e2tools`/`debugfs`）改一个**不在启动路径上**的小文件 → 写回 → 重启验证 UI/功能；失败就把原镜像原样写回。
- 不关键文件的候选：`/usr/bin/crypter.elf`（先备份！它是更新链的解密/校验体，里面有 DEND CRC `0xae60`、头 CRC `0xbf1c`、chassis `0xbde4`）、非启动路径的脚本/资源。

### L7 才轮到真正的目标改动（gen1 的 "appFw 等价物"）
- 一代没有 `/usr/lib/appFw.so` 与 `/cp`；候选目标（`im.elf`/`libObj.so`/kmod/codec）都**更大更关键**，一次只动一个，且要有 L0.5/L4/L6 打底。

---

## 2. 每级通用纪律（照抄执行即可）
1. **一次一个动作**，动作后立刻：重启 → 看 UI → 按快门拍照 → （若相关）WIFI/USB → 再进服务模式读状态。不要连续堆改动。
2. **写前先备份**（通道备份不可靠：只在本次刷写窗口内有效，成功即删）。
3. **写后读回校验**：`GET_FILE2` 或 `dd … | sha256sum`，与 PC 侧比对；不要相信"返回 0 就是写对了"。
4. 写分区时避免"边用边写"：先 `remount,ro`，或写完**立即重启**。
5. 电源：电池 ≥3 格；写过程中不拔 USB、不关相机、不拔电池（尤其 `dd` 期间）。
6. `nflasha6` 区总量 ≤5 MiB（配额），且备份 tar 落在 `/tmp`(=nflasha10, 12 MB) → **每次刷前先看 `df`**，写满会让所有写操作（含救援）报 `0x10000009`【已验】。
7. 载荷里不要放 `DIAC.csv`（会被 `sens_list_update()` 重写，可能弄坏校准）、不要放 `jiritsu.hash`（`set_firm` 自己写）。
8. 每次上电后先看 `/tmp/jiritsu/jinit` 与 `/tmp/jiritsu.bak.tar` 的状态，再决定下一步（它们分别是"上次 worker 崩了"和"上次刷写没走完"的标记）。
9. **不要发 `FIRMUP(0x4006)` / `FORMAT(0x4003)`**（同芯片实测会卡死服务模式）；破坏性命令如需发，重试次数要设 0。
10. 载荷**大小要变**（pad 几十字节）以躲开 dlopen 缓存；同一个会话里崩过一次就先重启相机再继续，不要原地重试。
11. worker 里跑命令时 busybox 没有 `tail/wc/head/tr/awk/find/id/vi` 的 `/bin` 软链 → 要写 `busybox tail` 这类全名；读 `/proc/*` 不能用文件读（`st_size=0`），要 `cat`。
12. **不要发 `SET/DEBUG(0x4005)`**：它不执行代码，但会把相机**时钟设成 2017-07-04 21:42:26**（`sys_set_timeofday @0x4694`，参数是立即数）→ 污染 EXIF/日志时间【已验】。
13. **`FILE_DELETE2(0x4012)` 当心**：mode 字节不是 0/1 时基目录=空串（路径原样用），结尾带 `/` 会 `sys_rm_tree` **递归删**；否则走 **`glob()`+unlink ⇒ `*`/`?`/`[…]` 会展开** ⇒ 一次能删掉整个目录（含越界到 `/etc`=nflasha10）【已验（指令级）】。未备份前不得用它做“清理”。

14. **写不自动重试**（§0.9）：读可重试；写必须先 `fget`/`get` 定状态再决定重发，并记录“实际发生了几次写”。
15. **preflight 先行**（§0.8）：六项任一不符 → 不开会话；每级开干前先填 §0.7 验收表。
16. **未验证的恢复路径不得作为下一级的理由**（§0.5 规则 1）：“官方更新器能重建 app 分区”目前只是 **R0（静态推断）**；实测先在 L4.5（低价值分区）上做。

## 3. 各动作的砖风险评级
| 动作 | 砖风险 | 理由 |
|---|---|---|
| 只改 header 的官方刷（region1） | **无** | 门禁（`0x127c`）在写盘前中止；`model/region` 永远要过 |
| 官方原版同版本重刷 | **会被拦** | `0x142`（版本不升），除非 `'O'` → 反而全盘重建 |
| 用 `SET_FILE2(0x4010)` 写 `libJit.so` | **高（代码执行，不是“写文件”）** | 同芯片实测：只有走 `write(16)` 才会触发 dlopen；跑起来后是任意代码。`jinit` 熌是哨兵**不是自动回滚**；`im.elf` 会自己重启（30–40 s） | nflasha6 不参与启动；崩了 `im.elf` 会自己重启（30–40 s）且有 `jinit` 熔断 |
| L0' 改载荷 + 重算 DEND CRC 重刷（2.00 无验签） | **中高（等价 L5）→ 移出真机阶梯，先做 QEMU/离线专项** | “只改几字节”≠低风险：成功判据就是“真的走写盘” |
| FileControl 文件级写（`zzprobe`） | 低–中 | 落点是持久化分区（a10/a2）；`/tmp/jiritsu` 落点取决于 a6 是否已挂载；跨重启持久性与覆盖语义**未验** |
| 发 `FIRMUP(0x4006)` / `FORMAT(0x4003)` | **高（同芯片实测卡死服务）** | 默认不发；见 `notes/camtool.md` §2 |
| worker `touch /usr/JITTEST` | 极低 | 新增文件 |
| worker 改已有 app 文件（相机上局部写） | 中高 | **同芯片禁止运行中局部写 `/usr`**（页缓存/ext2）→ 应改用整盘写回 |
| 整分区 dump→本地改→整盘写回 | 中高 | 一次改整个分区，但在“可重建”范围内；写前必须有原镜像 |
| worker `dd` 整个 nflasha15 | 中高 | 一次改整个分区；但仍在"可重建"范围内 |
| `modeType='O'` / VERSKIP 刷 | **高** | `edisx` 重写分区表 + `-m full` 全盘重建（还会 `ud_fsys_format /dev/nflasha24`，`endupdate.sh:97-101`） |
| `up.sh modver <ver>` + 普通 `'U'` 包重刷 | **中** | 不跑 edisx、`fmode=app`；但仍会擦 `nflasha4`、重写 a3/5/7/15；dat4 本身可再写回【机制已验/效果未验】 |
| 写 `/setting/updater/mode*`、`/setting/mode/{dmode,preload}` | 低–中 | 只改下次启动行为；有 `us_remove_modes.sh`/`change_mode.sh` 可改回；但若把 dmode 写成“不起 appFw”且没串口，会暂时进不去系统【未验】 |
| `FORMAT`(0x4003) 命令、跑 `edisx.elf` | **很高/禁止** | 分区表与文件系统级破坏，无本地副本 |
| 升级到官方 **2.03**（本机 `/Volumes/Update_ILCE7CV203`） | **中** | 版本天然过 `0x142`（严格大于）、USER 不跑 `edisx`、`-m app`；**但 2.03 会重写 `nflasha1`（2.00 不会）**，并擦 a4 + 重写 a3/5/7/15 ⇒ **升之前必须先 dump 机身 a1**【已验：包内有 `0400_updater/dev/nflasha1` + `updater.sum`】 |
| `dd`/写回 `/dev/nflasha1` | **很高（建议当禁区）** | 同芯片证据表明它是 **boot 分区**（kernel+initrd+kemco+loadaddr+p1chksum），而 2.00 官方更新从不重写它⇒ 我们只有自己的 dump；`p1chksum` 可能还会按 MD5 校验【未验】 |
| 碰 `nflasha1` / `boot0/boot1`（`/dev/nflashaB0`，只有 `pformat.elf` 写它） / `nflasha2` | **禁止** | 无副本；校准与引导唯一 |

## 3.9 新增两阶（2025-10-24：来自 `sauu` 验签重查 + `nflashaB0/B1` 节点发现）

### L1.6（只读·零风险）：用 `/dev/nflashaB0` / `/dev/nflashaB1` 取 eMMC boot 区
- 依据：主 rootfs(`a7`) 与 updater initrd(`a1`) 的 `/dev` 里都有 **`nflashaB0` + `nflashaB1`** 静态节点（另有 `mmca`/`mmcaa1`/`mmcab1`/`mmcac1`/`mmcad1`/`mcmn`）。⇒ 几乎肯定就是 eMMC BOOT1/BOOT2 硬件区（EXBL 所在）。
- 手法：与 a1..a23 完全相同的只读 dump 通道；长度未知 ⇒ 先 64 KiB 试探再放大，两次读比 sha。
- 要回答：EXBL 到底怎么校验 `boot/vmlinux.bin`/`boot/initrd.img`——`p1chksum` 是**纯文本 MD5 清单**（`a6d9d769…`/`0f00bf40…`）且在 initrd 与 a15(/usr) 里 **0 处引用** ⇒ 读它的只有 EXBL；它有没有被签名固定、a1 有没有被整体签名校验。
- 意义：决定"改 a1 里的 initrd"是 **R1**（可整分区回写且能启动）还是 **R0**（改了可能起不来、恢复手段未证）。证据：dump 本身 E3，由 EXBL 推出的结论 E0/E1。

### L4.7（写 a1：验签短路 patch）—— L1.6 + QEMU R1 演练完成前**不得**实机执行
- 已确证（E0，`work/sauu/SIG_RECHECK_200.md`）：2.00 的 `sauu` 在 **USER(0)/SERVICE(2)** 下**无条件** `RSA_verify`（调用点 `0x10b0e` → `fcn.000104e0`；stub `0xb60c`）。签名覆盖**整块 body**：`verify_info = {data=缓冲基址, len=total_data_size-0x100, sig=+(total-0x100), siglen=0x100, key="/etc/VerificationKey.pem"}`，SHA256 → RSA-2048；失败 = `printf "Signature Verification Error"` + `ApiException 0x30002` + `__cxa_throw`。⇒ **没有 Sony 私钥就刷不了改过的 payload**（改一字节必失败；只改 CRC 不会触发 RSA 失败，但另有 CRC 关）。
- 2.00 vs 2.03 `sauu`：验签相关函数（`0x10368`/`0x104e0`/`0x10a88`/ctor）**逐字节相同**、调用点地址两版一致 ⇒ 2.03 没新增验签也没加 gate（唯一语义差异是 mmap 上限 `0x20000000→0x40000000`）。`IAMSIGNENABLED` 是 **2.03 独有**的空旗标文件 + `libupdater0604.so: udtr_adjcmd_get_verifysign`（stat `/tmp_updater/root/IAMSIGN{ENABLED,DISABLED}`），2.00 无此函数/字串。
- 候选短路点：调用点 `0x10b0e`（`bl fcn.000104e0`）或判定点 `0x1056c-0x1056e`（`cmp r0,1 / beq`）。patch 对象在 **a1 的 initrd**（cramfs 不压缩 ⇒ 可原地按字节改），改完必须**同步重算 `p1chksum` 的 MD5**。
- 换/删 PEM 不够：PEM 全文还被 `fcn.00010368` 用 SHA1 与安全服务(MWF IPC)应答比对（`0x10474`），且失败是抛异常不是跳过 ⇒ 自签 PEM 不可行。
- 未证（弱 E0）：`sauu -m`/`-s`（MINOR/VERSKIP）是否走同一路径（`sauu` 里没有 `-m`/`-s` 字串，argc 只 1 处 cmp）；PROD 侧；失败时的用户可见码。
- ⇒ **顺序上先试"不改 a1"的模式实验（PROD/MINOR/VERSKIP 旗标）**，但必须先在 QEMU 里 R1 演练"只有旗标、没有 payload"会发生什么（会不会半刷）。

## 4. 变砖前的三件"救命东西"（必须已在手）
1. 原厂 `/tmp/jiritsu` 全套副本（L1）+ SHA-256 清单。
2. `/setting`(`nflasha2`) 的完整镜像（校准！含 `Backup.bin`、`updater/dat4`、`updater/mode*`、`sen/`）——**只读一次就永久存好**；再加一份 `nflasha4`（MPR，每次官方更新都会被 `ud_lerase` 擦）。
3. 已验证过的救回路径：L0.5 的"官方更新器能重建 app 分区"至少成功演练过一次。
