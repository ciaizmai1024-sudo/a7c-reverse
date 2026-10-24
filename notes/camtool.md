# camtool（同芯片 ZV-E10 = CXD90045）实测结论对照

来源：`/tmp/gh/Sony-ZVE-10-Camtool`（`github.com/nolan2628/Sony-ZVE-10-Camtool`，10★，2026-10-18）。
ZV-E10 在 fwtool `devices.yml` 里就是 `arch: CXD90045`，与 A7C 同 SoC/同内核（`3.0.27_nl-rt106+`、armv7l）→ **它的"实测红线"对我们是硬约束级别的信息**（标【同芯片实测】）。
两个前子代理（01a16694 / 01a166b3）跑空，本文是我自己用 read/grep 直接读该仓库得到的；引用都给文件+行号。

## 1. 写 `libJit.so` 的正确通道 = Jiritsu `write(16)`（= 我们的 `SET_FILE2 0x4010`）
- `cam.py:434-436`：「必须走 Jiritsu `write(16)`（`adj_cmd_set_file2`），它会 open+write 并在路径等于 `/tmp/jiritsu/libJit.so` 时 dlopen。**用 `0xff01` FileControl 写同一路径不会触发加载**」【同芯片实测】
- `README.md §4.3`（中文 `README.zh-CN.md §4.3:337`）同上；`jiritsu_lib.py:149-150` 给出 `select(path)` + `jiritsu(18)`（=DELETE2）等成对命令。
- 调用样例（`verify_ctor.py:39-42`）：`j.select('/tmp/jiritsu/libJit.so'); j.jiritsu(16, b'\0\xff\0' + blob)` → 返回码 `0x0` 为成功。
  ⇒ **载荷前缀 `\0\xff\0`**：与我们反汇编的 `msg+0x1c` 的 mode 字节一致（bit1=备份请求，bit0=数据在半包）——他们传 `mode=0xff`?? 需要上机核对（见 §7）。

## 2. ★红线：`FORMAT(0x4003)` / `FIRMUP(0x4006)` 会卡死服务模式
- `README.md:358`（中文 `:350`）：**"`FORMAT(0x4003)` / `FIRMUP(0x4006)` will hang the service. **Do not send them.**"**【同芯片实测】
- `jiritsu_lib.py:115`：「破坏性命令（FORMAT/FIRMUP）请传 `retries=0`」；`README.md:311` 同。
⇒ **我们路线 B 里"用 `set_firm`(0x4006) 刷 tar 载荷"要降级为备选**；主路径应是 **`write(16)` 直写 `/tmp/jiritsu/libJit.so`**（同芯片已验证可用，且不经过 tar 解包语义）。
  已生成的 `work/jiritsu_firm.dat`（tar 载荷）保留给"确实要走 FIRMUP"的情形。

## 3. 代码执行的触发：载荷的**构造函数**（ctor/`DT_INIT`）在 dlopen 时跑
- `verify_ctor.py:9-11`：判定 = `write(16)` 返回 0 且 marker 文件出现；抛 `GenericUsbException` = **dlopen 阶段崩**（im.elf 死）。
- `README.md:242-246`：**im.elf 死后相机会自己重启（约 30–40 s）**，等 60 s 再 `cam.py wait`；真要断电只在 3 分钟不回来时需要，且**必须先拔 USB 线**（ZV-E10 可由 USB 供电）。
- `README.md:346-348`：**dlopen 按名字缓存**——ctor 崩过一次后，同一会话里再写任何库都命中缓存、ctor 不再执行；只有 im.elf 真重启才清。→ `cam.py:431-432 deploy_payload(pad=…)` 用**改文件大小**来避免缓存（仓库里就有 `jit_exec_v10.bin` 与 `jit_exec_v10_pad.bin` 两份）。
- 他们的载荷**不实现 `CreateScriptI/LoadScriptI/RunScriptI/DestroyScriptI`**（`payload/jit_exec_v1*.s` 里没有这些符号），纯靠 ctor 一次性执行 ⇒ **一代也应把"干活"放在 ctor（`.init`）里**，`ScriptI` 四函数作为次要路径（我们已实现的 cmd.txt 机制可以两边都挂）。【建议】

## 4. 手工 ELF 的三个坑（`build_payload_v2.py` 文件头注释 + 代码）
1. **`.dynamic` 必须在可写段**：glibc 在 dlopen 时会往 dynamic 段写指针（`l_info`、`DT_DEBUG`）；落在 R+X 只读映射 → 直接 SIGSEGV，表现就是"写 libJit.so 后服务整个消失"。
   （我们 gcc 产的 .so 天然满足：标准布局 + RELRO，见相机自家库也是 gcc 产的 → 无需处理。）
2. 构造函数用 **`DT_INIT`（不是 `INIT_ARRAY`）**，入口地址**要带 Thumb 位（`|1`）**，否则 Thumb/ARM 解码错→立刻 SIGSEGV。
3. `e_flags = 0x05000200`（注释：`EF_ARM_EABI_VER5 | soft-float`）**正是我们产物的值**（`make docker` 实测 `0x5000200`）；
   ⇒ issue #23 里"要把 `e_flags` 改成 `0x5000002`"的说法**与这份同芯片实测矛盾**（相机自家库是 `0x5000002`，但 `0x5000200` 实测可用）。【他证，可用】

## 5. 错误码 / 状态码对照（可直接用于我们的工具）
| 现象 | 含义 | 出处 |
|---|---|---|
| `write(16)` → `0x10000000` | 空文件/非法 ELF，dlopen **干净失败**（不是崩溃） | `README.md:378` |
| `write(16)` 抛 `GenericUsbException` | 载荷在 dlopen 阶段崩，im.elf 死 → 相机 30–40 s 自动重启 | `README.md:379` |
| `sh` 超时、`out.txt` 不出现 | dlopen 命中缓存（本会话已崩过）→ 重启相机，别原地重试 | `README.md:380` |
| `/tmp/jiritsu` 读返回 `130` | **nflasha6 被卸载**（`rm /tmp/jiritsu/libJit.so` 会触发卸载）→ `jir 0x4002` 重挂，数据不丢 | `README.md:98,381` |
| 认证后设备变 `0x0994/0x0D96` | 相机 USB 模式不是"大容量存储"（ZV-E10 的 id，与 A7C 的 `0E8A→0336` 是同一类问题） | `README.md:376` |
| 认证报 `NoneType` 无 cmd | 上次读大文件被打断，握手错位 → `usb_recover.py` | `README.md:377` |

## 6. ★分区读写：不需要代码执行也能 dump/restore 整分区
- `dump_flash.py:3`：**通过 `FileControl(0xff01)` 整段 dump 块设备**（`jiritsu_lib.py:152-169` 给出 `file_read/file_write/file_delete`，hdr=`<HH cmd,len>` + 补齐到 4 的 latin1 文件名）；`cam.py:1404`：「`0xff01` FileControl：按文件名读/写/删，任意路径，**可整段读写块设备**」。
- `README.md §5.2`（中文 `:348`）红线：**改 `/usr` 或 `/` 必须"整盘 dump → 本地改 → restore 整盘写回"，禁止运行中局部写**（页缓存不一致 → ext2 错误）。`nflasha15=/usr` 挂载是 **ext2 ro**（`README.md:415` 区表）。
  ⇒ **修正我 `TEST_LADDER.md` 里 L5/L6 的做法**：不要在运行中的相机上 `remount,rw` 改 `/usr` 里的文件，而是"整分区读回 → PC 上改 → 整分区写回"。
- 红线 §5.1：**打通 bootROM 救砖前不要碰 `nflasha3`**（`/system`，含 `av-cam.bin`）。

## 7. 分区表（ZV-E10 实测）与 A7C 对照
`README.md §7`（中文 `:398-408`）+ `cam.py:120-126`：
| 分区 | ZV-E10 | 我们 A7C（`mount.conf` / 已知） | 备注 |
|---|---|---|---|
| nflasha12 | 40 MB `/cert` | 未见行（推测存在） | 上机 `ls -l /dev/nflasha*` + `partinf.conf` 核对 |
| nflasha13 | 4 MB 更新历史（未挂载） | 同上 | |
| **nflasha16** | **140 MB 全零空白（可当试验田/scratch）** | 推测存在 | **备份暂存首选**（比 /log 500MB 更安全：不是日志区） |
| nflasha17 | 100 MB 空 FAT16 | 推测存在 | |
| nflasha18 | 20 MB `/lens` | — | |
| nflasha23 | 67 MB 未挂载、内容非空、用途待查 | — | |
| nflasha15 | 300 MB `/usr` **ext2 ro** | 300 MB（我们记 240MB 已用） | 改动只能"整盘写回" |
⇒ 上机第一步就该把 A7C 的 `partinf.conf` 与 `/dev/nflasha*` 列表 dump 出来对齐（我们的 `mount.conf` 只列了挂载项，未挂载的空白分区也能读）。

## 8. 其它可直接复用的细节
- 认证直接复用 PMCA-RE 的 `SonySenserAuthDevice`/`SonySenserDevice`/`GenericUsbDriver`（`README.md:479`）→ 我们写 `jiritsu_send.py` 时不必自己实现鉴权。
- `pkt(pfunc, data, retries=2)`：默认重试 2 次；**破坏性命令传 `retries=0`**（`jiritsu_lib.py:112-118`）；超时 `CAM_USB_TIMEOUT`（默认 15000 ms）。
- 读 `/proc/*` 不能用 `get`（`st_size=0` 读回 0 字节）→ 用 `sh "cat ..."`（`README.md:363`）。
- busybox 里 `tail/wc/head/tr/awk/find/id/vi` **没有 `/bin` 软链**，要写 `busybox tail`（`README.md:364`）→ 我们 worker 的 `cmd.txt` 里也别用裸 `id`/`tail`。
- 他们的 `cam.py sh "<cmd>"` 就是"shell over USB"：先 `0xff01` 写命令/输出文件，再 `write(16)` 换载荷（大小 pad 过）让 ctor 执行 → 与我们 `cmd.txt` 思路一致，但**触发点是 ctor**。

## 9. 待核对（下机时）
1. `verify_ctor.py` 里 `write(16)` 的前缀 `b'\0\xff\0'` 与我们反汇编的 `msg+0x1c` mode 位语义（bit1=备份/bit0=数据在半包）到底怎么对应——**先按我们的逐指令版本来**。
2. A7C 是否同样"发 `FIRMUP(0x4006)` 会卡死服务"：一代 `adj_cmd_set_firm` 我们逐指令看过、没看出卡死点（它返回状态码），但同芯片的实测优先，**默认不发**。
3. A7C 一代是否也有 nflasha16/17/23 这类空白分区（暂存用）。
