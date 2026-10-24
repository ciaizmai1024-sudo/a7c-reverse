# ★低风险入口 1：`/setting/ulogio.bin` 的 TELN ⇒ 2.00 上是无认证 root shell（TCP 23）

> 调查由 100.122.234.78 上 `qoderclicn -m DeepSeek-Flash` 子代理完成（全文见 `work/mac-mini-agents/telnet-console/README.md`，工具已入库 `tools/ext2_walk.py`、`tools/dis_arm.py`）。
> **主会话独立复核通过**（都是我自己在这台机器上跑的）：
>
> - `nflasha15.bin` **是 ext2**（`0x438` 处 magic `53ef`、block 1024、234,356 blocks）——**不是 FAT**；a2 才是 FAT12（512 B/扇区、32 扇区/簇、每 FAT 4 扇区、根目录 512 项）。
> - `ext2_walk.py` 在 a15 里找到 `/bin/ulogio.elf` 19,152 B、`/bin/ulogio`→符号链接 10 B、`/kmod/osal_ulogio.ko` 38,988 B、`/lib/libosal_ulogio.so` 31,132 B（与子代理报的尺寸一致）。
> - 2.00 的 `libosal_ulogio.so` 导入：`socket/bind/listen/accept/select/ioctl/kill` + `grantpt/unlockpt/ptsname/dup2/setsid/vfork/execl` **全在**；字符串有 `/bin/ash`、`--login`、`[ulogio] socket ignore because telnet flag is down`、`[ulogio] failed to bind telnetd port`、`must be reboot system`、`maximum number of ethernet terminal reached.`。
> - 端口：`0x453e: mov.w r12,#0x1700` ⇒ **23**，`INADDR_ANY`，`listen(2)`。
> - 2.03 那份 `libosal_ulogio.so`（27,664 B）里上述导入与字符串 **0 命中** ⇒ 2.03 不是同一实现，**别按 2.00 断言有 shell**。
> - 机身 a2 解出来只有 `BACKUP.BIN/BACKUP.BAK/KEMCO.TXT/PSD.BIN/ULOGIO.BIN`（+MODE 目录），**没有 `filter.bin`** ⇒ 改 `ulogio.bin` 的 TELN 直接生效。

## 一句话
**改 a2（FAT12，更新不写它）里 3,772 字节文件的第 `0x9c` 字节 `00`→`01`，重启 ⇒ `0.0.0.0:23` 无认证 root shell（pty + `/bin/ash --login`）。** 这是目前找到的性价比最高、最不容易变砖的入口（R1：文件可备份可还原，还另有 Jiritsu/服务模式兜底）。

## 拿到 shell 之后立刻值钱的地方（ulogio 自带子命令，来自 `ulogio.elf` 字符串全表）
- 读物理内存：`db/dw/dl <base> <size>`、**`dk <base> <size> <file>`＝把物理内存导出成文件**、`logaddr [SID][SA]`＝取日志区物理地址。
- 写物理内存：`mb/mw/ml`、`mf <base> <size> <data>` 填充、`mu <base> <size> <file>` 用文件灌进去。
- 日志/终端：`term on/off`、`tlist`、`ot/it`、`alog`、`lsnap`、`lstart/lstop`、`rewind`；过滤：`filter on/off/info/clear/abort`、`trace_filter`；UIPC：`uipc <OSAL_ID> <msgdata> x 6`、`uipctxt <file>`；还有 `crash`、`timetag`、`telnet up/down`、子系统菜单 `switch [SID]` / `uquit`。
- **没有** 独立 `set`/`dump` 子命令（`dump` 只出现在 `dk` 帮助文字里）。

## 与本轮其他结论的接点（一开 shell 就能一并解决）
- 读 **OTP/SKD 窗**：物理 `0xF340F000`(32 B，AES-256 key) 与 `0xFFFF5000`(1 KiB，大概率 `__GetPublicKeyHash`) ⇒ `dk 0xF340F000 32 /tmp/skd.bin`（见 `notes/skd-key-source.md`）。
- 读 **保留 RAM**：`0x02E80000`(Backup RAM，§4c 要比对的那块)、`0x03085000`/`0x478000`(LOGB 日志环形缓冲)、`0x034FD000`/`0x8000`(PRTB) ⇒ **完整启动日志免费拿**。
- `uipc` 子命令可以直接发 uIPC 消息 ⇒ 与 R19 在 QEMU 里排的 Backup 条目表互相印证（`Backup_read(0xe7002e)` 那个 ID 也能试）。
- 之后才考虑 `mw/mu`（写内存不动 flash，风险低于写分区，但要一样小心）。

## 注意与风险
- **要重启**（监听 socket 只在 ulogio 守护线程初始化时创建）；串里就写着 `telnet up -- enable telnet output, must be reboot system`。
- 一旦跑过 `ulogio telnet up/down`，会生成 **`/setting/filter.bin`**，此后它的 TELN **覆盖** `ulogio.bin`（排查"改了没生效"先看它）。出厂 a2 没有这个文件。
- 只接受**一个**会话，第二个连接收到 `maximum number of ethernet terminal reached.` 后被关掉。
- 不做 telnet 选项协商（raw），`nc` 也能连；无认证 ⇒ 只在可控网络短时开。
- 前提是有网络地址（Wi-Fi 连上/AP）；`0x9c` 一字节改完大小不变、无校验（`FCHK/FVER` 是 `filter.bin` 自己的头，`ulogio.bin` 没有文件级校验）。
- **2.03 上预期不是 shell**（改成"以太网终端"复用日志/终端通道；23 是否监听未证，需实测或拿到 2.03 的 a15 侧库）。机身是 2.00 ⇒ 按本节做。
