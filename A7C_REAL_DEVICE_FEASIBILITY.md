# Sony A7C 真机连接与修改固件写入可行性、变砖风险评估

> 范围：本仓库针对 **ILCE-7C 一代／CXD90045／v2.00 固件包**的静态分析及现有工具。只审计，不连接相机、不发送 USB 命令、不修改程序或固件。本文所谓“可行”不是在这台 A7C 上验证成功；不提供变砖概率数字，因为没有本机实测样本和经验证的救援链。

## 一、结论先行

| 想做的事 | 当前判断 | 风险结论 |
|---|---|---|
| USB 枚举、识别相机 | 工具和 libusb 环境已备好；**这台 A7C 的实际 PID/接口尚未实测** | 低，但不能先假定 `054C:0E8A → 0336` 一定成立 |
| 进服务模式并读取文件/分区 | PMCA-RE Senser 栈、Jiritsu 文件通道及同芯片 ZV-E10 的先例支持；**这台 A7C 尚未验证** | 比写入低，非“零风险”；大文件读取可超时、截断或导致会话失步 |
| 用 `SET_FILE2(0x4010)` 覆盖 `libJit.so` 运行代码 | 一代加载路径有静态证据，另有 A7C 一代 **v2.03 的第三方 root 报告**；当前 v2.00 机身与现有二进制**未实测** | **中至高**：这是持久写入 `nflasha6`，并会立即加载不受信任代码；不能称为“安全探针” |
| 通过官方更新器刷修改后的 `.dat` | 目前**未证明可行**。可重算 CRC/帧校验，不等于能通过尾部 256 B 未知校验；版本、机型、区域也有门禁 | **高／不可量化**：不能假定失败必然发生在写盘之前 |
| 用 `'O'`/VERSKIP 同版本重刷，或改镜像后整分区写回 | 存在写入路径，但没有本机成功恢复案例；VERSKIP 涉及分区表和 full mkfs | **很高**，现在不建议上机实施 |
| 不刷包，直接改门禁库 `/usr/lib/libupdaterufp.so`（整分区 dump→改→写回） | 门禁全在这个 12 KB 库里，`libIMDB.so` 按名 dlopen；库在“更新器会重建”的 nflasha15 上【本轮已验】 | **中**：比刷修改包轻（不依赖验签），但仍需先拿到写块设备的通道，且同版本 `0x142` 会限制“刷回原版”兜底（`up.sh modver` 可解） |

**整体建议：可以考虑在人工核对 USB 设备后开展“枚举与经核验的只读取证”；目前不满足修改固件刷入的放行条件。**“服务通道可运行代码”和“官方修改包能刷入”是两件不同的事，不能互相替代。

## 二、可行性证据及边界

### 1. 连接和服务通道

- `tools/jiritsu_send.py` 调用 `refs/Sony-PMCA-RE/pmca/usb/sony.py` 的 `SonySenserAuthDevice`／`SonySenserDevice`；离线 framing 与同芯片 `refs/Sony-ZVE-10-Camtool/jiritsu_lib.py` 对齐，`--mock` 及虚拟环境导入已通过。**这些只证明主机侧封包及模拟读写，不证明相机实际认证或权限**。
- 默认 MSC PID 候选不止 A7C：`tools/jiritsu_send.py:40-41,283-327` 含 `0x0E8A/0x0D95/0x0D96/0x0994`，服务 PID 含 `0x0336/0x02A9`，`find_one()` 只按 PID 选第一个设备，不核对机型或序列号；`0x0D96/0x0994` 在同芯片工具说明里还可能意味着**错误 USB 模式**。仓库早期的 `notes/a7c2-tools.md` 亦将一代 PID 留待核验。**先枚举、人工确认目标机和实际模式，不能把工具默认值当成 A7C 实测值。**
- `libJiritsu.so::adj_cmd_set_file2 @0x5b00` 与加载线程 `0x7684/0x769c` 支持“写 `libJit.so` 后复制至 ramdisk 并 dlopen”的路径；ZV-E10 同芯片的 `refs/Sony-ZVE-10-Camtool/README.md` §4.3 确认要用 Jiritsu `write(16)`，而非普通 FileControl 写文件。`notes/github-survey.md` 引用 A7C 一代 **2.03** 的外部实机 root 报告。上述证据对 **v2.00、当前机身、当前 worker** 的实际效果仍只是强线索。
- 同芯片 README §5 报告 `FIRMUP(0x4006)`／`FORMAT(0x4003)` 会卡住服务；不应因一代 `adj_cmd_set_firm @0x67ec` 可反汇编就尝试发送。该 `FIRMUP` 操作的是 Jiritsu 区，**不是把整套修改固件刷入 app 分区的捷径**。

### 2. 官方 `.dat` 改包路线

- 在现有 A7C 一代工件中，`notes/updater_verify.md` §2–§3 定位了 `crypter.elf` 的 DEND CRC `0xae60`、帧校验 `0xe0ec`、头 CRC `0xbf1c`、chassis 比较 `0xbde4`；未在这些可用模块发现 RSA/EVP 验签。**这不等于整条启动/更新链没有验签**：包内没有 `nflasha1` 更新器分区，FDAT 尾部 16 B IV＋256 B blob 的真实作用仍未定。`KeyArray=SHA256("")` 只说明已定位的 ECB 初始化，不能据此推定硬件 CBC 密钥或签名可伪造。DEND CRC 可覆盖尾部数据，并不意味着 `crypter.elf` 会解释尾部 256 B。
- `libupdaterufp.so` 首块头处理 `0x1b5a–0x1c1e` 后，`0x127c` 依次检查 model/region/version，失败码分别 `0x140/0x141/0x142`；之后才走 tmpfs `Firm.dat` 写入 `0x26dc–0x2706` 和 `crypter.elf`。**只在这条已分析 UFP 路径内**，匹配失败发生在这些写入之前；主机更新器是否预先拒绝、实际采用何种入口，尚未在本机验证。
- 已装 v2.00 的机身按此门禁，同版本普通 `'U'` 更新会先遇 `0x142`。`region1.dat` 即使报 `0x141`，也**不能测试签名**；“CBC 区翻一字节”若保持同版本 `'U'`，同样先被 `0x142` 拦住。即使观察到 CRC 报错，也**不能排除后面还有认证**。`TEST_LADDER.md` L0 所称“风险≈0／正确签名探针”应视作未经上机证实的设想，而非无损承诺。
- `'O'` 会跳过**版本**比较，但不跳 model/region；脚本侧 VERSKIP 会调用 `edisx.elf` 和 `uc_mkfs -m full`（`FIRMWARE_MOD.md` §2.1）。普通 USER 更新也会改写 app 镜像。`tools/fdat_hdr_edit.py` 只重算已知校验并保持尾部原样，**不能证明尾部对新密文仍有效**。

## 三、为什么当前会比 `TEST_LADDER.md` 的风险评级更危险

1. **“备份完成”可能是假的。** `tools/jiritsu_send.py:86-112` 的 `jir()` 遇非零 response/status 只打印、仍返回；`read2/write2` 没检查 `sel()` 成功。`cmd_get/cmd_l1` (`:425-445,540-558`) 会把失败读出的空数据当正式文件保存并显示空串 SHA-256。`cmd_l1` 默认只读七个文件，不包括文档要求的 `Cam_AdjustGuide_Files/*`，默认也不 dump **逐机校准的 `nflasha2`**。所以出现 `work/l1/libJit.so` 不等于原厂库已可靠备份。
2. **分区 dump 没有证明“完整”。** `cmd_dump/cmd_l1` (`tools/jiritsu_send.py:506-582`) 未核对本机 `partinf` 给出的预期分区长度、未二次独立读取比对；L1 没有为各分区生成完整哈希清单。成功计算 SHA-256 只能证明**实际收到的字节**没变，不能证明未截尾。尤其包内的原始 `nflasha15` 镜像约 **239,982,592 B**，而文档给出的该分区容量约 **314,572,800 B**；其他镜像同样可能短于分区容量，不能把更新包镜像直接当“整盘备份”或不经核对就整盘写回。
3. **超时会重发有副作用的命令。** `Jiritsu.pkt()` (`tools/jiritsu_send.py:73-92`) 默认任意异常后重试两次，仅 `FORMAT/FIRMUP` 关重试；`SET_FILE2`、`DELETE2`、`START` 及 `raw` 均可能超时后被重复发送。USB 超时不等于相机未执行第一包。工具的 `raw/fput/fdel` 也可绕过“永不碰”文档禁令。
4. **L2 载荷不是“只写心跳”。** `tools/jit_worker/libJit.c:107-136` 在 dlopen **构造函数**和 `RunScriptI` 内读取持久的 `/tmp/jiritsu/cmd.txt`，若与 `.last` 不同即 `system()` 执行；`/tmp/jiritsu` 是 flash-backed `nflasha6`，旧 `cmd.txt` 可能重启后仍在。命令/拼接会截断，失败仍写 `.last`，`cmd.rc` 不记录真实退出码。`TEST_LADDER.md` L2 的“不要 `system()`、只写 `WORKER.VER`”与**实际准备部署的二进制矛盾**；不能直接照 L2 的 `put` 命令操作。
5. **模拟与他机故障恢复不可外推。** Mock 把 MOUNT/START 固定报成功、缺失 Jiritsu 文件甚至回“成功＋空内容”，不运行 ctor、不模拟 `jbusy/jinit` 或 flash 容量；只验证一部分 framing 与文件流程（`tools/jiritsu_send.py:164-264`）。ZV-E10 的“崩后 30–40 秒自动重启”、`e_flags=0x5000200` 可用，只是**同芯片他机**经验。当前 worker 是 `DT_INIT_ARRAY`、带待动态解析的 libc 符号；musl 容器自测不等于在 A7C 的 glibc 2.11.2/实际 `im.elf` 上通过。
6. **回滚未落实。** `set_firm` 成功路径会删 `bak.tar/bak.hash`（`FIRMWARE_MOD.md` §3.1.1 `0x6a36/0x6a40`）；`jinit` 是拒绝再次加载的哨兵，**不是自动回滚**。直接 `SET_FILE2` 覆盖 `libJit.so` 更不能指望 tar 备份。文档建议的 `/log` 原厂副本，当前 `put` 命令不会替用户创建。
7. **“app 写坏更新器能救”仅是脚本分析。** 包内 `nflasha3/5/7/15` 镜像和 `us_mkfs.sh` 的更新路径存在，不等于 A7C 本机可在 UI/Jiritsu 死掉后、同版 `0x142` 门禁限制下可靠恢复。`nflasha1` 包内无镜像；`nflasha2` 逐机校准不可由通用包重建；boot 区/分区表出错可能需拆机或经单独验证的 BootROM 恢复。`TEST_LADDER.md` 里“只有 boot 才是真砖”“`touch /usr/JITTEST` 极低风险”“`crypter.elf` 可当不关键试写文件”均**过于乐观或与其后文自相矛盾**。
8. **改 `/usr` 的两种错误做法都危险。** 同芯片 README §5 禁止运行中局部改挂载的 ext2 `/usr`（页缓存/元数据不一致）；改成整分区写回也不是低风险——期间断电、长度/布局不符或覆盖错目标都可能令 `im.elf` 与服务通道同时失效。`/usr/bin/crypter.elf` 是官方更新链关键程序，不应当作无关紧要的首次试写文件。
9. **`nflasha10` 是 flash-backed vfat。** `/tmp`、`/etc` 共用约 12 MB；写满会影响后续写入和恢复。不要假定“重启会自动清空 /tmp”。ZV-E10 的 `nflasha16` 空白试验分区**不等于 A7C 也有同用途分区**。

## 四、风险分层与停止条件

| 阶段 | 相对风险 | 本次评估的行动边界 |
|---|---|---|
| 离线核对镜像、工具 framing、已有文档 | 最低 | 可继续；mock 只算模拟，不算真机通过 |
| USB `scan` 与人工核对机型/实际 PID | 低 | 只枚举，确认唯一目标；不以默认 PID 推断连接成功 |
| 服务鉴权、只读读取（包括分区 dump） | 低至中 | USB 会话可能挂起；L1 的 MOUNT 会改变运行时挂载状态；所有读取必须验证返回状态、长度、重复读取与哈希，空文件不算备份 |
| 修改头的更新包／故意失败的探针 | **未知且不宜称零风险** | 同版门禁让它们通常得不到签名信息；不能将报错当成已验证恢复演练 |
| `SET_FILE2` 写并加载 `libJit.so` | 中至高 | 当前 worker 含自动 `system()`、读失败未硬中止、无可信原厂副本门槛；**当前状态停止** |
| 官方更新器刷修改 `.dat`／普通 app 镜像整区写回 | 高 | 签名与可恢复性未决；**当前状态停止** |
| `'O'`/VERSKIP、`FIRMUP/FORMAT`、写 `nflasha1/2/3` 或引导／分区表 | 很高至灾难性 | 前者重分区/格式化、同芯片后两命令卡死服务；**不建议尝试** |

**放行任何写入之前的最低门槛（须逐项有人核验）：**

1. 明确这台相机的**型号、固件实际版本、区域、USB PID/接口及分区表**；确认读取的是目标机。不要把 2.03 外部报告替换成 2.00 结论。
2. 把 `nflasha1`、`nflasha2`、`nflasha6`、所有可能改到的分区和原厂 `libJit.so`／Jiritsu 工作区取得**非空、预期长度、至少两次独立读取一致**的原始副本；保存不覆盖的 PC 副本和哈希清单。失败/缺一项即停。
3. **若走官方 `.dat` 改包路线**，先核清 FDAT 尾部 256 B 与 `nflasha1` 更新器的校验职责、同版本门禁；**不得将“改包失败”视作恢复能力已证明**。若只研究服务写入，此项不决定 `SET_FILE2` 能否工作，但未知签名与版本门禁意味着**不能把官方改包当作服务写坏后的兜底**。
4. 若考虑服务路线，需先解决工具的失败状态传播、写命令重试、备份门槛，且首次载荷不得从 flash 读旧命令并执行；在实际 A7C 软件 ABI 上做离线核对。即便如此，仍须有**独立、已验证**的断电/服务不可用时恢复方式，不能只依赖同芯片经验。
5. 对 `/usr`、`/system` 等启动相关分区，先建立完整、可校验、能在失去 Jiritsu 服务后使用的恢复链；否则**不进入刷写阶段**。

## 五、本轮继续分析得到的新证据（详见 `notes/updater_flow.md`）

只读静态（未碰相机）把**更新包自带的更新器代码与脚本**读全后，三件事直接改变风险图：

1. **同版本重刷不再只能靠 VERSKIP。** `nflasha15_unpacked/bin/up.sh`（相机自带、在可写的 /usr 内）提供
   `modver`（用 `ud_datcnv.elf` 改写 `/setting/updater/dat4` 里「更新器认为的当前版本」）、
   `modmod/modreg`（挂 `/dev/nflasha1` 改 `dat2/dat3` 机型/区域）、以及 `user/serv(mode3)/ms(mode5)/ver(mode6)` 旗标。
   `us_mkfs.sh:39-47,55-77` 证实 `USER/SERVICE/MINOR/MSCRYPT` 都**不跑 edisx、fmode=app**，只有 `VERSKIP/PRODUCT` 才 edisx+full。
   ⇒ 「先 `up.sh modver` 把版本改小，再用原样 `'U'` 包做一次 app 模式重建」比 `'O'` 低一个量级【机制已验，效果未验】。
2. **每次官方更新都会擦 `nflasha4`（12 MB raw「MPR Flash Backup」）**（`endupdate.sh:94` `ud_lerase.elf /dev/nflasha 4`）；
   备份链是 `/setting/Backup.bin` + `ud_keep_backup.elf -s/-p/-r/-u`，写 loader 前还会 `bksb.elf` 生成 `LdrBkup.bin`。
   ⇒ 备份清单必须含 **nflasha2（`Backup.bin`/`updater/dat4`/`updater/mode*`）+ nflasha4**；「USER 模式很温和」要减去这一条。
3. **存在低于 Jiritsu 层的救援旋钮（固件自带）**：`/setting/mode/dmode`（`change_mode.sh`：0=只起 kernel … 3=起 appFw，`3g/3b`=gdb/gdbserver，`p <lib>`=任意 preload）、`/setting/mode/preload`；
   `nflasha3` initrd 的 `sbin/init` 有 `launch_shell()` 与 `/bin/ash --login`，`/usr/bin/launch_shell.elf` 在 `/dev/console` 上给 shell；`us_remove_modes.sh` 撤销「下次进更新模式」。
   ⇒ 比 `TEST_LADDER.md` 担心的 `/etc/ld.so.preload` 安全（Sony 自家调试机制、文件在 /setting，USER 更新不重建 /setting）。

同时收窄 §2.2 的签名问题：FDAT 记录尾的 **272 B 被容器 `DEND` 的 CRC32 覆盖**（`crc32(文件[0:size-12]) = aaaa81b8` 已核）；
上游 fwtool `fdat.py:AesCbcCrypter.decrypt()` **只取尾 16 B 当 IV、直接丢弃其余 256 B 仍能解出 `UDTRFIRM`** ⇒ 该 256 B 不是解密载荷所需；
一代包内所有可用模块（`libupdater{ufp,ufunc,talk,common,media}.so`、`crypter.elf`、`libupdaterbody.so`）里
**没有任何 `Updater::*Signature*` 修饰名或 RSA 比较**（`bsa_server` 的 `VerifySignature` 属蓝牙 GATT）。
⇒ 更像「给 LDEC 硬件/更新器的认证块或密钥块」（`nflasha7/kmod/ldec.ko` 的 dump 变量无密钥参数 ⇒ 密钥在 SoC 内）【推断】；
**是否被验仍只能等 nflasha1 dump**【未定】。另：`nflasha7_unpacked/root/chassis` 内容就是 `CXD90045`（crypter.elf `0xbde4` 比对的文件），改 rootfs 时别动它。

## 六、此次审计范围及证据索引

- 本机未连接相机；未验证任何 USB 握手、服务写入、官方更新或救砖；**变砖概率无法计算**。
- A7C 一代静态证据：`notes/updater_verify.md` §2–§6，`notes/updater_flow.md`（本轮新增：`up.sh`/模式旗标/`us_mkfs.sh`/`config.xml`/`mount.conf`/init 启动面），`notes/jiritsu.md`，`FIRMWARE_MOD.md` §1–§3；更新模式 `UPDATER_ANALYSIS.md` 与 `updater.img_unpacked/bin/us_mkfs.sh`；FDAT 尾 272 B 见 `tools/fdat_tail.py`。
- 同芯片他机行为：`refs/Sony-ZVE-10-Camtool/README.md` §4.3、§5；A7C 一代 v2.03 外部报告：`notes/github-survey.md`（issue #23）。
- 当前工具与载荷：`tools/jiritsu_send.py`、`tools/jit_worker/libJit.c`；与旧风险表冲突之处见 `TEST_LADDER.md` L0–L2、L5–L6、§3。
- 本文是**风险评估而非上机操作许可**；如果本机恢复路径始终无法验证，“不刷修改固件”是合理结论。
