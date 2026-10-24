# ulogio TELN 开关：能不能用、开起来是什么

调查对象：机身 2.00（a2 `/setting/ulogio.bin`，3772 B）与手头的 2.03 更新包。
方法：纯静态（ext2/FAT 解析、ELF 反汇编、字符串），未上机。所有地址都可按下文命令复现。

## 0. 结论速览

- **能用**。2.00 上把 `/setting/ulogio.bin` 偏移 **0x9c 的字节从 0x00 改成 0x01**，重启即生效
  （前提：`/setting/filter.bin` 不存在——出厂 a2 就没有）；不需要用户名密码。
- **开起来不是"只看日志"，是一个 root shell**：ulogio 在 **TCP 23** 上监听（`0.0.0.0`，无认证），每个连接 fork 一个 pty，子进程直接
  `execl("/bin/ash", "ash", "--login", NULL)`。以正常启动时的 root 身份运行。
- **同一时刻只接受一个 telnet 会话**；已有会话时新连接会收到一行 `maximum number of ethernet terminal reached.` 然后被关闭。
- telnet 服务端在 **`/lib/libosal_ulogio.so`** 里（不是 busybox，也不是内核模块）。
- **2.03 是另一套实现**：更新包 initrd 里的 `libosal_ulogio.so`（27664 B）没有 `socket/bind/listen`、没有 `vfork/execl/pty`，也没有 `/bin/ash`，
  telnet 通道改成"以太网终端"接到 ulogio 的终端/日志通道。2.03 上**不能**按 2.00 的证据断言会得到 shell（详见 §6）。
- busybox 确实**没有 telnetd**（也没有 nc），所以 TELN 是这台机器上唯一的 telnet 服务端。

| 版本 | 文件 | 大小 | 行为 |
|---|---|---|---|
| 2.00 a15（`nflasha15.bin`） | `libosal_ulogio.so` | 31132 | socket 23 + pty + `/bin/ash --login`（root shell） |
| 2.00 a7 initrd | `libosal_ulogio.so` | 31132 | 同上（另一构建，md5 不同） |
| 2.03 a7 initrd | `libosal_ulogio.so` | 27664 | 无 socket 创建、无 pty/execl，终端复用（见 §6） |

---

## 1. 镜像与二进制位置（先更正一个前提）

### 1.1 `nflasha15.bin` 是 ext2，不是 FAT

- 超级块在 0x400：偏移 0x438 的 `53 EF`（magic 0xEF53），1024 B block，234356 blocks，58696 inodes，`incompat=0x2`（无 ext4 extent）。
- 相机上它作为 **/usr** 挂载（`netstack.md` 的结论），所以镜像里的 `/bin/ulogio.elf` 运行时就是 `/usr/bin/ulogio.elf`。
- 因此 `fat12_walk.py` 用不上；本次换成了只读的 `ext2_walk.py`。

### 1.2 `nflasha2.bin` 是 FAT12

- BPB：512 B/扇区、32 扇区/簇、每 FAT 4 扇区、根目录 512 项。
- 数据区 `40960 - 1 - 2*4 - 32 = 40919` 扇区，`40919/32 = 1278` 簇（<4085）⇒ **FAT12**。
- 启动脚本 `insmod.sh` 里：`mount -t vfat /dev/nflasha2 /setting`，之后
  `insmod .../osal_ulogio.ko ulogio_initfile=/setting/ulogio.bin`。所以改的正是启动时读的那个文件。

### 1.3 ulogio 的三个部件

| 路径（a15 镜像内） | 大小 | 作用 |
|---|---|---|
| `/bin/ulogio.elf`（`/bin/ulogio` 是指向它的符号链接） | 19152 | 命令行工具（UIPC 客户端） |
| `/lib/libosal_ulogio.so` | 31132 | 用户态主体：过滤设置、终端、**telnet 服务端** |
| `/kmod/osal_ulogio.ko` | 38988 | 内核模块：解析 `/setting/ulogio.bin`、维护 TERM/TELN 旗标、UIPC 服务 |

a15 根分区本身**没有 `/bin/ash`、也没有 busybox**；busybox 来自 a7 initrd（`a1_initrd_200/203` 的 `/bin/ash -> busybox`）。
运行时 `/bin` 是 initrd 的，`/usr` 是 a15 的，所以 telnet 里 `execl("/bin/ash")` 能找到。若把 a15 单独 chroot 出来是没有 shell 的。

`a2` 的 `/setting` 里只有 `ulogio.bin`（3772 B，md5 `ceb0e7f1fa66acdbabefd68008eaae08`，与 `a7c-shared/setting/ULOGIO_BIN` 相同），
**没有 `filter.bin`**。这一点对"改配置能不能生效"很关键（见 §4.3）。

---

## 2. telnet 服务端实证（2.00 的 `libosal_ulogio.so`）

以下地址是 `extracted/libosal_ulogio.so`（31132 B，来自 a15）的 Thumb 地址。

### 2.1 入口与开关

`ulogio_telnetd_init` @ **0x4398**：

```text
43c4: ldr r6, [r4, #0x10]        ; 结构体 +0x10 = telnet 旗标（来自驱动 init-info+0x30）
43de: cmp r6, #0
43e0: bne.w 0x4506               ; 非 0 -> 建 socket
43e4: ... str.w r5, [lr]         ; 0xf500 = -1
43f2: ldr r0, ... ; -> 0x6770    ; puts(...)
      "... socket ignore because telnet flag is down"
      "command 'ulogio telnet up' can up the socket "
```

旗标为 0 时**不会**创建监听，只打印上面两句；为 1 时走 0x4506：

```text
4506: movs r0,#2                 ; AF_INET
4508: movs r1,#1                 ; SOCK_STREAM
450a: mov r2,r5                  ; 0
450c: blx socket
451a: ... setsockopt(SO_REUSEADDR=2, 1, 4)
4536: adds r1,r7,#4              ; sockaddr_in
453c: movs r3,#2 ; strh r3,[r7,#4]   ; sin_family = AF_INET
4544: str r5,[r7,#8]                 ; sin_addr = 0 (INADDR_ANY)
453e: mov.w ip,#0x1700
4546: strh.w ip,[r7,#6]              ; sin_port = 0x1700 -> 网络字节序 00 17 -> 端口 23
454a: blx bind
4552: movs r1,#2 ; blx listen        ; backlog = 2
```

错误串：`[ulogio] failed to create socket`、`[ulogio] failed to bind telnetd port`、
`[ulogio] failed to enable listen on listenerfd`。端口和地址都是写死的，无参数、无配置项。

### 2.2 会话处理：accept -> pty -> `/bin/ash --login`

`ulogio_telnetd_mainloop` @ **0x37bd**，`select()` 等监听 fd；accept 在 **0x3c72**：

```text
3c6e: movs r1,#0 ; mov r2,r1
3c72: blx accept
3c76: subs r4,r0,#0 ; blt ...        ; accept 失败
3c84: ldr r6,[0xf4d8] ; cmp r6,#0
3c86: ble.w 0x4078                   ; 没有会话 -> 0x4078: bl 0x3028 (pty helper)
3c8a: ... write(accepted_fd, "maximum number of ethernet terminal reached. \n", 0x2f)
3c98: blx close
```

- 从代码看只维护一个 telnet 会话：已有会话时，新连接只会收到
  `maximum number of ethernet terminal reached. \n`（0x2f = 47 字节，来自 0xf36c）然后关闭。
- 没有会话时调用 pty helper **0x3028**：
  - 打开 `/dev/ptmx`，`grantpt` / `unlockpt` / `ptsname`；
  - `vfork`；子进程 `close(0..255)`，打开 slave，`dup2` 到 0/1/2，`setsid`，`tcsetpgrp`，继承 termios；
  - 子进程执行 **0x31fa 附近的 `execl`**：
    - 0x661c `"/bin/ash"`
    - 0x6628 `"ash"`
    - 0x662c `"--login"`
  - 失败则 printf 后 `exit(1)`。代码里**没有** login/passwd/用户名提示，也没有降权。
- 会话断开时 `kill(pid, 9)`，关闭并释放 fds/缓冲区（0x3ca2 起）。

### 2.3 telnet 协议处理

主循环里的 IAC 解析：

- **0x3ec4** `cmp r3, #0xff`（IAC），**0x3f1c** `cmp r3, #0xfa`（IAC SB），**0x3fda** `cmp r2, #0x1f`（NAWS），
  **0x3fec** `movw r1, #0x5414`（`TIOCSWINSZ`，把客户端窗口大小下发给 pty）。
- 会剥掉 0xF1–0xFE 和转义的 0xFF；处理 CR/LF。
- **不发 WILL/DO 协商回应**，所以是"raw telnet"：Linux `telnet`、`nc`、PuTTY 的 Telnet 模式都能连；
  客户端不要期待选项协商。

### 2.4 安全含义

- 监听 `0.0.0.0:23`，无认证，直接 root shell（宿主进程在正常启动时是 root）。
- 只在隔离的局域网/直连网段打开；不要放在有不可信主机的网络上。要关掉就改回 TELN=0 并重启。

---

## 3. 连上之后是什么

- **不要用户名密码。** 连接后直接是 busybox ash（`--login` 会读 `/etc/profile`，但不会做认证）。
- **不是"只吐日志"。** 日志终端是 ulogio 的另一套东西（`term on/off`、`tlist/ot/it`、`alog/lsnap`）；
  telnet 这条路径是 pty + shell。
- 同一时刻一个 telnet 会话；第二个连接会被拒绝（见 2.2）。
- 因为 `/bin/ash` 来自 a7 initrd，telnet 进程的文件系统视图是相机的运行根，能直接跑 `/usr/bin` 下的工具。

---

## 4. TELN / TERM 在代码里怎么被读

### 4.1 启动链（内核模块）

启动脚本（initrd `/usr/bin/insmod.sh`）：

```sh
mount -t vfat /dev/nflasha2 /setting
insmod /usr/kmod/osal_ulogio.ko ulogio_initfile=/setting/ulogio.bin
```

`osal_ulogio.ko` 的 `module_init`（`.init.text`，objdump 地址 0x0 起）流程：

1. 若 `ulogio_initfile` 非空：`ulogio_file_open` -> `ulogio_file_size` -> `kmalloc` -> `ulogio_file_read` -> `ulogio_init(buf, size)`。
2. 否则若 `ulogio_initdata` 非空：`ulogio_init(data, size)`。
3. 两者都没有：printk `"setting data not specified!"` 并失败。

`ulogio_init` 的顶层 TLV 解析（.text 0x64 起）用一张标签字面量表：

```
0x74c TERM   0x758 TELN   0x73c FLTF   0x76c FBOX   0x724 DBGL ...
```

- `TERM` 值 -> `[r11-76]`
- `TELN` 值 -> `r4`
- `FLTF`（`/setting/filter.bin`）-> `[r11-68]`
- `FBOX` 记录指针 -> `[r11-64]`

调用（0x6d8）：

```c
ulogio_filter_driver_init(fbox_ptr, ..., TERM,
                          /* [sp]   */ TELN,
                          /* [sp+4] */ filterfile);
```

`ulogio_filter_driver_init` @ **0x4460**：

- `TERM` -> 驱动全局 `[0x124+1]`（字节）
- `TELN` -> 驱动全局 `[0x2b0+0x16]`（字节）
- `filterfile` 路径拷到 `[0x2b0+0x18]`
- 路径非空则打开并调用 `ulogio_filter_load_setting_f`；
  **打不开就回退到 `ulogio_filter_load_setting(FBOX)`**（先校验 FBOX tag）。

之后 0x6ec `bl ulogio_filter_get_telnet`，0x6f4 `strh r0, [r6, #0x30]` 把旗标写进与用户态共享的 init-info 结构 **+0x30**。

读/写函数：

| 函数 | 地址 | 动作 |
|---|---|---|
| `ulogio_filter_get_term` | 0x4a20 | `ldrsb [0x124+1]` |
| `ulogio_filter_get_telnet` | 0x4a74 | `ldrsb [0x2b0+0x16]` |
| `ulogio_filter_set_term` | 0x4ad4 | 写 `[0x124+1]` |
| `ulogio_filter_set_telnet` | 0x4b50 | 写 0/1 到 `[0x2b0+0x16]` |
| `ulogio_filter_set` | 0x4b78 | 按 msg[0xa] 分派：2=term，3=efree，1=abort，4=timetag，**5=telnet**，6=trace |

`ulogio_filter_set` 尾部（0x4c34–0x4c80）在 filterfile 路径非空时：

```c
fd = ulogio_file_open(path, 0x241 /* O_WRONLY|O_CREAT|O_TRUNC */, 0x1a4 /* 0644 */);
ulogio_filter_save_setting_f(fd);
close(fd);
```

失败时 printk `"cannot save filter setting to %s"`。

**`filter.bin` 覆盖规则：** 如果 `/setting/filter.bin` 存在，驱动启动时优先加载它，里面的 TELN 会覆盖 `ulogio.bin` 的 TELN。
出厂 a2 没有这个文件，所以改 `ulogio.bin` 直接有效；一旦跑过 `ulogio telnet up/down`，它就会被创建并从此优先。

### 4.2 标签解析的一个坑

驱动 `ulogio_filter_load_setting` @ 0x3bb0 里，`TELN` 不是直接的字面量：

```text
3c??: ldr r0, =0x4d524554   ; "TERM"
...
      add r0, r0, #0xfa0000 ; 0x4d524554 + 0x00fa0000 = 0x4e4c4554 = "TELN"
```

所以只在 ko 里 grep `TELN` 字符串是找不到的，别据此判断"驱动不支持 TELN"。TELN 分支把字节写到 `[0x2b0+0x16]`（0x3ff4–0x3ff8）。
同一个函数还处理 `TERM/DBGL/EFRE/FLTA/TTAG/FCHK/FVER/CFLT/SFLT`；`FCHK/FVER` 是 `filter.bin` 自己的头部/校验，`ulogio.bin` 没有文件级校验。

### 4.3 用户态库

`libosal_ulogio.so`：

| 函数 | 地址 | 动作 |
|---|---|---|
| `ulogio_filter_load_setting` | 0x51f4 | 解析 TLV；`TELN` -> `0xf924`，`TERM` -> `0xf46c` |
| `ulogio_filter_load_setting_f` | 0x582c | 解析 `filter.bin`（FVER/FCHK + 记录） |
| `ulogio_filter_save_setting_f` | 0x5ab4 | 写 `filter.bin` |
| `ulogio_filter_userspace_init` | 0x5ef8 | 尾跳 0x1dd4 调 `load_setting` |
| `ulogio_filter_get_term` | 0x6060 | 读 `0xf46c` |
| `ulogio_filter_get_telnet` | 0x60a8 | 读 `0xf924` |
| `ulogio_filter_set_term` | 0x60fc | 写 `0xf46c` |
| `ulogio_filter_set_telnet` | 0x616c | 写 `0xf924` |
| `ulogio_filter_set` | 0x6190 | 同上分派 type 5；写 `filter.bin`（0x241/0x1a4） |

但**决定是否监听的不是这两个用户态全局**：守护线程（0x21bc）先做 `unsetenv("LD_PRELOAD")`、
注册 UIPC 0x8001、用 0x8012 同步取 0x48 字节 init-info，然后构造：

```text
+0x00 log ring, +0x04 print ring, +0x08 pipe fd,
+0x0c init-info[0x32] (mode), +0x10 init-info[0x30] (telnet flag)
```

再把 +0x10 传给 `ulogio_telnetd_init`。所以**开机时的 TELN 由驱动从磁盘读到的值决定**。

### 4.4 除改配置之外的开关途径

1. **改 `/setting/ulogio.bin` 的 0x9c = 0x01**（推荐；无校验、大小不变、只改一个字节）。
2. **`ulogio telnet up`**（CLI，`/usr/bin/ulogio.elf`）：
   - CLI 只链 `libosal_uipc/libosal_utm`，用 `osal_snd_msg` 发 UIPC set 消息（有串 `[ulogio] failed to send message to ulogio userspace!`）。
   - 接收端两侧都有 type=5 分支：驱动的 `ulogio_filter_set` 置 `[0x2b0+0x16]` 并按 FLTF 保存；用户态库的 `ulogio_filter_set` 置 `0xf924` 并保存同一文件。
   - 结果：创建/重写 `/setting/filter.bin`，**监听 socket 只在守护线程初始化时创建，所以必须重启**。
     帮助串原文：`telnet up -- enable telnet output, must be reboot system`。
3. **模块参数**：`insmod osal_ulogio.ko ulogio_initfile=<file>` 或 `ulogio_initdata=<...> ulogio_initdata_size=<n>`（需要 insmod 权限；启动脚本默认用 1）。
4. **recovery/工厂路径**：存在 `/root/IAMLDUDWRT` 时，initrd 把 tmpfs 挂到 `/setting`，用
   `ud_get_serial_cfg_file.elf 7 /setting/ulogio.bin` 取配置，并 `backup.ko Backup_load=1 Backup_save=0`。这条路可以不碰 `/dev/nflasha2` 注入配置。
5. **环境变量/命令行参数：没有。** CLI 没有任何配置参数；代码里唯一的 unsetenv 是 `LD_PRELOAD`。busybox 也没有 telnetd 可用。

---

## 5. ulogio 子命令全表（从 `ulogio.elf` 字符串原样整理）

提示符：`[ulogio]>`（0x2e90）、`[%s]>`（0x3304）、`[%3x]>`（0x330c）；子系统菜单用 `uquit` 退出。

| 组 | 子命令 | 说明（帮助原文摘要） |
|---|---|---|
| 读内存 | `db` | `db <base_addr> <size>` 按字节 |
| | `dw` | 按字（word） |
| | `dl` | 按双字 |
| | `dk` | `dk <base_addr> <size> <file_path>` 导出到文件（**没有叫 `dump` 的子命令**，`dump` 只出现在这条帮助里） |
| | `logaddr` | `logaddr [SubSystemID][SubArea]` 取日志内存物理地址 |
| 写内存 | `mb` / `mw` / `ml` | 按字节/字/双字写 |
| | `mf` | `mf <base_addr> <size> <data>` 填充 |
| | `mu` | `mu <base_addr> <size> <filename>` 用文件内容写内存 |
| 终端/子系统 | `switch` | `switch [SubSystemID]` 进子系统菜单；不带参数进最近一个 |
| | `ilist` | 列出带菜单的子系统 |
| | `tlist` | 列出终端 |
| | `ot` / `it` | 按索引设输出/输入终端 |
| 日志抓取 | `alog` | `alog [-p] [PATH] [-b|-d|-k|-t] [filename]` 保存所有日志区 |
| | `lsnap` | `lsnap <SubSystemID> <filename>` 单次快照 |
| | `lstart` / `lstop` | 连续抓取开始/停止 |
| | `rewind` | 重绕终端输出 |
| 过滤 | `filter` | `on <SID> [CID] <ERROR\|WARNING\|DEBUG\|INFO>`、`off <SID>`、`abort [clear]`、`info`、`clear` |
| | `trace_filter` | `on/off <SID>`、`clear`、`info` |
| 终端/逃生日志 | `term` | `term on` / `term off`（终端输出开关，对应 TERM） |
| | `efree` | `efree on/off`（释放逃生日志区） |
| UIPC | `uipc` | `uipc <OSAL_ID> <msgdata> x 6` |
| | `uipctxt` | `uipctxt <sndfilename>` 从文件发 UIPC 消息 |
| 其他 | `help` / `exit` / `crash` / `timetag` / `telnet` | `timetag normal\|limit\|both\|off`；`telnet up\|down` |
| 子菜单 | `uquit` | 退出子系统菜单 |

用户提到的 `filter`、`set`、`dump`：`filter` 是子命令；**没有独立的 `set` 或 `dump`**——
`set` 只作为 `filter on/off`、`term on/off`、`telnet up/down` 的语义出现，`dump` 只出现在 `dk` 的帮助文字里。

---

## 6. 2.03 的重要差异（不要直接套用 2.00 的结论）

2.03 更新包 initrd 的 `libosal_ulogio.so`（27664 B，md5 `74a69a1b7429accf2fa75448eb93f1b3`）与 2.00 的 31132 B 版本不是同一份实现：

- 网络/pty 相关的动态导入只有 **`accept/ioctl/kill/select`**，**没有** `socket/bind/listen/setsockopt`，也**没有** `vfork/execl/dup2/ptsname/grantpt/setsid`。
- 字符串里**没有** `/bin/ash`、`--login`、`socket ignore because telnet flag is down`、`failed to bind telnetd port`。
- `ulogio_telnetd_init`（0x3a88）改为建立"以太网终端"节点（两次 `calloc(1, 0x20)`），按 init 结构里的 mode 配置；
  相关串是 `maximum number of ethernet terminal reached.`、`failed to open UART terminal`、`failed to created telnet sessions`。
- 全 initrd 里带 `socket/bind/listen` 的 ELF 只有 busybox/libc/libcrypto，**找不到创建 23 端口监听的组件**。
  因此从这份库的代码看，telnet 会话是被当作 ulogio 的终端通道来复用，**不 fork shell**；监听 fd 由谁创建，
  仅凭现有镜像无法确定（2.03 的 a15 侧库我们没有，只有 a7 initrd 的这份）。

因此：

- 对 **2.00 机身**（本机 a2 + `nflasha15.bin`，含 `iw/top`、无 `curl`）：按 §0/§2 的结论，TELN=1 得到 root shell。
- 对 **2.03**：同样的 TELN 打开后预期是 ulogio 的远程终端/日志通道，不是本地 shell；23 端口是否真的被监听需要在 2.03 上实测
  （或在拿到 2.03 的 a15 镜像后复核 a15 侧 `libosal_ulogio.so`）。

---

## 7. busybox 复核

- a7 initrd 与 a1 initrd 的 busybox 都是 **v1.29.3**，静态提取的 applet 表 **191 个**（见 `a7c-shared/net-tools/busybox_applets_a7.txt` / `..._a1initrd.txt`）。
- **没有 `telnetd`、没有 `nc`、没有 `httpd`**：`strings busybox | grep -i telnet` 为空；applet 清单也没有。
- a15 根分区没有 busybox 可执行文件（`/bin/mkfifo -> ../../bin/busybox` 只是符号链接，借 a7 那颗）。
- 结论：机器上没有任何现成的 telnetd，TELN 打开的是 ulogio 自带的服务端。

---

## 8. 对 `a7c-shared/notes/netstack.md` 的更正

| netstack.md 原文 | 实测/反汇编结论 |
|---|---|
| "a2(/setting) 里没有 ulogio 配置" | 错。a2 有 `ulogio.bin`（3772 B，md5 `ceb0e7f1…`，与 2.00 包内一致）；2.03 包里是 3796 B。 |
| "ulogio = 日志/内存终端，不是 shell" | 只对了一半。2.00 的 telnet 会话是 pty + `/bin/ash --login`，是 shell；日志/内存终端是 `term`、`tlist/ot/it` 那一套。 |
| "`ulogio telnet up` 只是置内核 ko 的旗标" | 不完整。它还会把设置写回 `FLTF=/setting/filter.bin`（驱动/库两侧都有保存路径），且 socket 只在启动时建，**必须重启**；之后 `filter.bin` 的 TELN 会覆盖 `ulogio.bin`。 |
| "端口 23，写死" | 正确。`sin_port = 0x1700`（0x4546），`INADDR_ANY`，`listen(2)`。 |
| "a15 里没有 busybox" | 正确；但补一句：a15 也没有 `/bin/ash`，shell 来自 a7 initrd。 |

---

## 9. 复现与工具（都在本目录）

### 9.1 解析 a15（ext2）

```sh
cd /Users/wubin/a7c-tasks/telnet-console
python3 ext2_walk.py ../a7c-shared/nflasha15.bin ls /
python3 ext2_walk.py ../a7c-shared/nflasha15.bin ls /bin
python3 ext2_walk.py ../a7c-shared/nflasha15.bin find ulogio
python3 ext2_walk.py ../a7c-shared/nflasha15.bin dump /lib/libosal_ulogio.so extracted/libosal_ulogio.so
```

`extracted/` 里已有：`ulogio.elf`、`libosal_ulogio.so`、`osal_ulogio.ko`、`libIMDB.so`。

### 9.2 反汇编

```sh
python3 dis_arm.py extracted/libosal_ulogio.so ulogio_telnetd_init --len 800
python3 dis_arm.py extracted/libosal_ulogio.so ulogio_telnetd_mainloop
python3 dis_arm.py extracted/libosal_ulogio.so ulogio_filter_set --len 400
python3 dis_arm.py extracted/libosal_ulogio.so ulogio_filter_load_setting --len 400
```

默认按 Thumb 解码；`.ko` 是 ARM 模式且各段 VMA 都是 0，`dis_arm.py` 无法自动选段，
需要 `llvm-objdump -d -r`/`objdump -d -r` 的输出配合（本次用 `/tmp/ko_dis.txt` 的那份）。

### 9.3 看/改配置

```sh
cd /Users/wubin/a7c-tasks/a7c-shared
python3 tools/ulogio_cfg.py setting/ULOGIO_BIN get TELN
python3 tools/ulogio_cfg.py setting/ULOGIO_BIN get TERM
python3 tools/ulogio_cfg.py setting/ULOGIO_BIN set TELN on -o /tmp/telnet-on.bin
cmp -l setting/ULOGIO_BIN /tmp/telnet-on.bin      # 只应看到 1 个字节：0x9c 从 0 变 1
```

等价的手工 patch：文件偏移 `0x9c` 的 `00` 改 `01`（TELN 记录：长度 dword@0x94、tag `TELN`@0x98、payload@0x9c；
TERM 记录：@0x88/0x8c/0x90，现值 1）。文件没有校验，大小不变。

### 9.4 上机步骤（自行承担风险）

1. **先备份** a2 的 `ulogio.bin`（以及 `Backup.bin`/`Backup.bak` 原样保留）。
2. 用你现有的 a2 写入方式把改好的 `ulogio.bin` 写回 `/setting/`（或走 recovery 的 `ud_get_serial_cfg_file.elf 7` 路径）。
3. **确认 `/setting/filter.bin` 不存在**；若存在，先删掉或把它的 TELN 也设为 1。
4. 重启。检查：`cat /proc/net/tcp` 里应有本地 `:0017` 的 LISTEN；或从 PC `nc -vz <相机IP> 23`。
5. 连接：`nc <相机IP> 23` 或 `telnet <相机IP>`，回车后应看到 shell 提示符。
6. 回滚：恢复备份的 `ulogio.bin`（或 `set TELN off`），重启；若曾生成 `filter.bin`，删掉它或把 TELN 设 0。

---

## 10. 局限与风险

- 全部结论来自静态分析，未在硬件上跑过；"root 身份"是按正常启动时 ulogio 进程由 initrd 以 root 启动推断的。
- 守护线程由哪个进程加载 `libosal_ulogio.so` 没有完全追死：`libIMDB.so` 的模块表里有 `libosal_ulogio.so` 和
  `ulogio_so_suspend/resume`，`libsencore.so` 里有 `/usr/bin/ulogio.elf`；不影响"库里有 telnet 服务端"和"由 init-info+0x30 门控"这两点。
- 2.03 的 telnet 实现不同（§6），不要拿 2.00 的地址和行为直接套。
- 无认证的 root shell 暴露在 0.0.0.0:23，风险很高；只在可控网络短时开启。
- 一旦运行过 `ulogio telnet up/down`，`/setting/filter.bin` 会长期覆盖 `ulogio.bin`，排查"改了没生效"时先看这个文件。
