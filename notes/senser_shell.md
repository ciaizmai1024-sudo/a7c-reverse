# A7C (Gen1) senser / 服务模式：命令通道、终端、代码执行 — 证据笔记

分析对象：`firmware.tar_unpacked/0700_part_image/dev/nflasha15`（ext4，解包到 `nflasha15_unpacked/`），
以及 `nflasha7_unpacked/`（早期启动 rootfs）、`nflasha3_unpacked/initrd.img_unpacked`。

方法/工具（全部只读）：
- `rabin2 -E <lib>`（导出表：名字/`vaddr`/size）、`rabin2 -i`（导入表）、`rabin2 -ld`（DT_NEEDED / RUNPATH）。
- capstone(THUMB) 自建脚本：解析 `.plt`/`.got` 得到 **PLT stub → 符号名** 全映射
  （`libsencore.so`: 604 stubs, **0 未解析**；`libJiritsu.so`: 202 stubs, 0 未解析；`libSTMcmdexecute.so`: 16, 0），
  再对目标函数反汇编，自动注释 `bl/blx → 符号`、字面量池 → 字符串 vaddr。
- 全镜像 `movw #imm / cmp` 扫描（用于找 PFUNC/backup block 常量比较）。

标记：【已验】= 有文件+符号+地址+指令/字符串直接证据；【推断】= 由已验事实推出、未逐字节验证。

---

## 0. 谁在实现 senser（USB 服务模式）

| 文件 | 角色 | 关键证据 |
|---|---|---|
| `nflasha15_unpacked/bin/sen.elf` (259,392 B) | senser 服务进程（USB 协议服务端） | 内含字符串 `SenserThread`、`senser_start`、`senser_end`、`/setting/sen/smode` |
| `nflasha15_unpacked/lib/libsencore.so` (369,804 B, `SENSER_LIBRARY_VERSION = "6.02  15-May-2020 12:07"`) | 协议实现库（sen.elf 加载） | 导出 `_Z20senser_usb_mode_startv`、`_Z22senser_normal_mode_startv`、`_Z11FileControlPK12SenserPacket` 等；`SystemControlStart("/usr/local/bin/sen.elf")` 字符串 @rodata 0x389a8 |
| `nflasha15_unpacked/lib/libJiritsu.so` (174,816 B) | 校准（JIRITSU）19 条命令服务 | 导出 `cmd_*`、`adj_cmd_*`、`sys_*`、`IM_JIRITSU::CImJiritsu` |
| `nflasha7_unpacked/lib/libSTMcmdexecute.so` (4,640 B) | **exec 原语**（`stm_system`/`stm_popen`） | libJiritsu、libsencore 的 DT_NEEDED 都含它 |
| `nflasha15_unpacked/lib/libInfraUsbCmn.so` | USB gadget / senser 接口 + 备份读 | 导出 `usb_senif_init/destroy`、`usb_senif_pub`(obj)、`_ZN7CUsbSvc24check_forced_senser_modeEv` @0xad1c、`_ZN7CUsbSvc18ReadDataFromBackupEiiPv` @0xd0f0、`_ZN7CUsbSvc26read_port_desc_from_backupEP27usb_otgcore_port_descriptor` @0xb844 |
| `nflasha15_unpacked/bin/ulogio.elf` | 终端通道里跑的程序 | 字符串 `[ulogio]>`、`======== ULOGIO %s ========`、`/dev/mem`、`log address: 0x%04x`、`failed to do snap capture(%d)` |
| `nflasha15_unpacked/bin/adjstctl.elf` | 校准服务客户端工具（引用全部 19 条 JIRITSU 命令） | `grep -c JIRITSU` = 19 |

服务模式持久化标志文件【已验】：`libsencore.so` 的 `LoadSenserMode` @vaddr **0x176ac**（104 B）：
`/boot/sen/smode`（若 /boot 挂载）否则 **`/setting/sen/smode`**（字符串 0x56c34/0x56c44），
镜像到 `/var/.sen/.smode`（0x56c23），日志格式 `SENSER_MODE = %d`（默认值 2）；
`StoreSenserMode` @**0x17714** 写回同一文件。initrd 的 `init` 里另有 `check_forced_senser` / `is_forced_senser` / `/setting/sen/smode` / `/setting/mode/dmode` 字符串。

---

## Q1. A7C Gen1 原生就有「执行代码 / 执行命令」通道吗？

**结论：有，三条不同性质的通道；且 `cmd_debug` 本身不是 shell。**

### 1.1 `cmd_debug` = 空桩（不是缺失的导入，也不是命令注入点）【已验】
- `libJiritsu.so` 导出 **`cmd_debug` @ vaddr 0x4da8, size 42**（`rabin2 -E`）。它是在本库**定义**的（不是 UND）。
- 反汇编（Thumb，PLT 已解析）：只有 `movw r2,#0x12c0; ldr r3,[pc,..]; ldr r3,[r3+off]; cmp r3,#0; movs r3,#0; movs r0,#0; str r3,[r0]; ite; mov r0,r3; pop…; bl __stack_chk_fail` → 立即数 0 赋返回值，**无 system/popen/fork/execve/open/socket，无字符串引用**。
- 调用点只有一个：**0x711e**，位于 JIRITSU 命令序列块（同一块里 0x70d6 `cmd_mode`、0x70ee `cmd_format`、0x7106 `cmd_start`、0x711e `cmd_debug`，均通过 libJiritsu 自身 PLT stub 调用）。该块看起来是「mode→format→start→debug」的启动序列，而不是每条 USB 报文一个 handler（见 §1.5）。
- 19 条命令的导出地址（`rabin2 -E libJiritsu.so`）：
  `cmd_mode` 0x4754、`cmd_format` 0x48d8、`cmd_backup` 0x498c、`cmd_restore` 0x4d58、`cmd_start` 0x4b60、
  `cmd_high_capacity_set_file` 0x6b20、`cmd_high_capacity_set_file_path` 0x6d08、`cmd_high_capacity_get_file` 0x6f14、
  `cmd_get_version` 0x5c80、`cmd_get_mem_free` 0x5c94、`cmd_get_mem_used` 0x5cd4、`cmd_clear_dmm` 0x4de2、
  `cmd_download_image` 0x54f4、`cmd_download_data` 0x5118、`cmd_upload_image` 0x6294、`cmd_get_image_size` 0x5388、
  `cmd_debug` 0x4da8、`cmd_get_dmm_info` 0x4e9c、`cmd_get_dmm_free` 0x4f94、`cmd_get_dmm_used` 0x4fac、`adj_cmd_set_file` 0x679c、`adj_cmd_get_file_hash` 0x6c54。

### 1.2 shell 执行通道：`CShellExecute::ExecShellNew` → `stm_system`（fork+execve）【已验】
- `libJiritsu.so` DT_NEEDED 含 **`libSTMcmdexecute.so`**；PLT stub **0x36d4 → `stm_system`**；PLT **0x30e8 → `_Z12CShellExecute12ExecShellNewEPc`**，而该符号在 libJiritsu 自己里面定义（**0x3b78**；它在 libJiritsu 的 UND 列表里出现是因为它同时被本库其它 TU 引用 —— 全固件里没有任何其它库导出它，故解析只能落在 libJiritsu 自身/或运行时 dlopen 的插件）。
- `CShellExecute::ExecShellNew` @**0x3b78**：
  `0x3ba0/0x3ba6/0x3bae` 依次压入字符串 **`/bin/sh`(0x3bb4)**、**`-c`(0x3bbc)**、参数 `cmd`(r4) → 构造 `argv={"/bin/sh","-c",cmd,NULL}`；`0x3b9e blx 0x36d4 → stm_system`。
- `stm_system` @**libSTMcmdexecute.so vaddr 0x828**：`fork`(0x842/0x860) → 子进程 `execve`(0x876，argv/envp 来自参数) → `__libc_stack_end` 读取 + `prctl(PR_SET_PTRACER)`(@0x7f6 小函数) → 父进程 `waitpid`(0x88a) 并对 EINTR(4)/ECHILD(10) 重试。**即真正的 POSIX exec，不是 libc system()**。
- libJiritsu 里 `stm_system` 只有 **1 个调用点 0x3b9e**（即 ExecShellNew 内）。`ExecShellNew` 的调用点：**0x4628、0x46da**，两者都在导出函数 **`sys_tar_process` @0x45e0 (size 144)** 内；它格式化的命令串是
  `/bin/tar cf %s ./ -C %s`(rodata 0x4650) 与 `/bin/tar xpf %s ./ -C %s`(rodata 0x4676)。→ 备份/恢复走 shell，模板固定，文件名来自包内（是否过滤未验证）→【推断：存在文件名注入面】。
- 另一处直接 shell：`sys_set_timeofday` @**0x3a34**（PLT `stm_system` 调用点 0x3a84），命令串 **`/bin/date -s \"%s\" %s %s`**（rodata 0x3aee 区）。时间串来自上位机 →【推断：注入面】。
- `system/popen/execve/fork/waitpid/execveat/system` 在 libJiritsu.so 中**只作为 PLT 导入存在**（`rabin2 -i`）；本库内没有直接 `bl` 到这些导入（除 `stm_system` 路径）。`stm_popen`/`stm_pipe` 由 libSTMcmdexecute.so 提供，libJiritsu 引用了它们（`cmd_high_capacity_*` 里用 `stm_pipe` @0x6b96/0x6f40，用于 pipe 分块传大文件，不是执行）。

### 1.3 原生插件执行（最强的一条）：`libJit.so` dlopen/dlsym【已验调用；推断触发方式】
- `IM_JIRITSU::CImJiritsu::jit_thread(void*)` @**libJiritsu.so 0x74b0 (size 1696)**：
  - `0x7654 bl ramdisk_mount`，参数串 `"/tmp/jiritsu/ramdsk_libJit"`(0x7660) + `"size=1M"`(0x766c)
  - `0x7672 bl sys_file_copy` → 目标 **`/tmp/jiritsu/ramdsk_libJit/libJit.so`**
  - `0x769c bl dlopen("/tmp/jiritsu/ramdsk_libJit/libJit.so", RTLD_NOW)`
  - `0x76ae bl dlsym("CreateScriptI")`、`0x76da bl dlsym("LoadScriptI")`（另有 `RunScriptI`、`DestroyScriptI` 字符串），随后 `blx` 调用取到的函数指针
  - 错误串：`libJit.so copy error.`、**`libJit.so crashed.`**、`jit_thread: load error: %s`、`jit_thread: load emergency error: %s`、`jit_exit`
  - 上传落点字符串 **`/tmp/jiritsu/libJit.so`**（同 `tmmc.jit`、`jit.log`、`/tmp/jiritsu/`）→ 由 `adj_cmd_set_file` @0x679c / `cmd_high_capacity_set_file*` 写入。
  → **只要用校准通道的 set_file 把 `libJit.so` 放进去，相机就会 dlopen 并调用其中的导出函数 = 任意 ARM 原生代码执行，不需要重新刷机。**（触发时机：加载后 `dlsym`+调用已验；「上传即触发」为推断）
- 相关：`_ZN10IM_JIRITSU10CImJiritsu3runEPKc` @0x7b64、`init` @0x7394、`jit_thread` 由 `pthread_create`(PLT 0x34f8) 创建。

### 1.4 `/tmp/jmode` 与 `cmd_debug` 无关【已验】
- `cmd_start` @**0x4b60**：`0x4bd0 mov r1,#0` + `"/tmp/jmode"`(0x4bd2) → `bl 0x3054`（fopen/stat 类，PLT 解析出的本地包装），失败串 `JMODE_OPEN_FAIL`(0x4bd8)；日志 `not jmode`(0x4c5e)/`have jmode`(0x4c67)/`jmode err not Manual`(0x4c9a)，并比较字符串 **`Manual`**(0x4c34)；成功则设置全局 `jiritsuDebug`(0x61608 区) + `jmode_flag`(0x6161c)。
- `cmd_format` @0x48d8：`0x48f8`/`0x4920` 有 `"/tmp/jiritsu"`、**`/tmp/jmode`** → 删除模式文件。
- 校准（JIRITSU）另有 `jiritsuDebug`、`jiritsuDebugMode`、`/dev/gpio_drv`(`JIRITSU_CHANGE_USB_FAIL`)、DMM 物理/逻辑映射（`DmmMgr::PhysToLogi` @0x7ffc、`sync_alloc_dmm_buffer` @0x80ac）→ 校准命令可直接读写设备内存区（DMM），这也是「非 shell 的原生数据/代码执行面」。【已验符号与调用；语义推断】
- 早期启动的 shell（非 USB）：`nflasha7_unpacked/bin/launch_shell.elf` 在 0x3b54 处 `execve("/bin/ash","--login")`；`init` 有 `launch_shell.elf`、`/bin/ash --login` 字符串；libsencore.so rodata 0x31050 也有 `/bin/ash --login` → 本地控制台 shell 存在，是否被接到 USB 终端**未验证**（A7C 的 senser 终端实际接的是 ulogio，见 Q2/§2.5）。

### 1.5 命令是怎么被调进来的（补充证据）【已验】
- 在 `libJiritsu.so` 里对 `cmd_*`、`sys_tar_process`、`ExecShellNew`、`cmd_debug` 做全段 `bl/blx` 扫描：**没有任何直接调用**；这些导出函数只通过本库自身 `.plt` stub 被引用（PIC 自调用，stub 例：`sys_tar_process` 0x3310/0x3314、`ExecShellNew` 0x30e8、`cmd_debug` 0x35c8、`cmd_mode` 0x37d0、`cmd_start` 0x3474、`cmd_format` 0x34d4、`stm_system` 0x36d4、`dlopen` 0x3320、`sys_file_copy` 0x35e0、`ramdisk_mount` 0x3544）。
- 第一个 RX 段（vaddr 0xf34 起）里有形如 `{0x000a0012, N, fnaddr, fnsize}` 的表项，例如 `0x102c: 000a0012 / 0x058e / 0x000045e1(sys_tar_process) / 0x00000090`、`0x146c: 000a0012 / 0x0675 / 0x00004da9(cmd_debug) / 0x0000002a`。**最后的 size 与 `rabin2 -E` 导出的 size 完全一致（0x90=144、0x2a=42）** → 这是函数元数据表（行号/大小），不是消息派发表。
- 全固件中只有 `libJiritsu.so` 自身含 `sys_tar_process` 符号名（`grep -rl`），`bin/adjstctl.elf`、`bin/sen.elf`、`bin/scenario.elf` 都不导入它；`adjstctl.elf` 只有 `testcmd_sndmsg`（发 OSAL 消息），`scenario.elf` 有 `testcmd_run_scenario`。→ JIRITSU 的 19 条命令是**消息码驱动**（由运行中的 app/MPR 侧派发），shell/tar 执行发生在 jiritsu 服务进程内部，参数（文件名、日期串）来自上位机消息。
- 因此 §1.2 的「命令串」是否可被上位机直接控制，取决于消息字段（`cmd_backup/cmd_restore` 的路径参数）→ 仍需真机验证。

### 1.6 传感器/场景框架（补充）
libsencore.so 里的 senser 命令是通过 Sony **scenario 表**注册的（数据段/文本常量表，条目形如 `{0x000a0022, fnA, fnB, size}`）：
`0x27c0 → FileControl(0x14d55)`、`0x33a0 → MemoryDump(0x14af9)`、`0x46c0 → AdjustControlFunc(0x14bed)`、`0x45a0 → ProductInfoFunc(0x13835)`、`0x3840 → TestMode(0x137dd)`。
固件里确有 `lib/libInfraMakeScenario.so`、`bin/scenario.elf`、`scenario/*.so`（616 KB）→【推断：场景可被触发执行，属另一条潜在执行/脚本面】

---

## Q2. PMCA-RE 用到的服务命令在 A7C Gen1 存在吗？

**结论：全部存在，实现都在 `libsencore.so`。**（下列 handler 的日志标签字符串是身份的直接证据：每个 handler 开头都会 `cppdump_logrec(level, TAG, packet, len)`。）

| PMCA-RE 功能 | A7C 设备侧实现【已验】 | 关键指令/字符串 |
|---|---|---|
| ProductInfo (PFUNC **0x0000**) | `_Z15ProductInfoFuncPK12SenserPacket` @**0x13834** (152 B) | 标签 `INQ_ID`(0x1384c)/`INQ_TITLE`(0x1385e)/`INQ_MODEL`(0x13872)/`INQ_ROM`(0x138a6)；子命令 switch @0x138c6–0x138d8：`0x4, 0x10, 0x12, 0x13, 0xf1, 0xff` → **0x00f1 存在**（PMCA 用它探测「终端切换功能」是否支持） |
| AdjustControl (PFUNC **0xff00**) | `_Z17AdjustControlFuncPK12SenserPacket` @**0x14bec** (64 B)，标签 `ADJ_CTRL`(0x16114/0x16124)；真正派发在 0x15f60/0x16000 区 | block 常量比较（全库 `movw/cmp` 扫描）：**0x601** @0x16280（`movw r2,#0x601; cmp r3,r2`，码 0x11/0x12/0x13/**0x1f**/0x21/0x23/0x2f/0x31/0x51/0x52/0x53/0x61/0x62）、**0x603** @0x12ce2/0x12d04（码 0x1..0x15）、**0x6b3** @0x16238/0x1446c、0x687 @0x12d80 |
| 终端使能 (0x601, **0x1f**) | 同一函数 @**0x162bc → 0x16306** | `0x16318 ldr r0,[pc]; add r0,pc ;; => "/usr/bin/ulogio.elf it"`(0x16324) → `blx 0xff58 (stm_system)`；`0x16354` 第二处 **`"/usr/bin/ulogio.elf ot"`**(0x16336) → 再次 `stm_system`；并从包 offset **0x1c/0x1d** 取参数字节（0x162e8、0x16348：`add r0,r6,#0x1c; ldrb r3,[r0]`）。另有全局 **`terminal_change_function_is_disabled`**(0x61eec)，(0x603,0xf) 分支 @0x14326 读取它 |
| FileControl (PFUNC **0xff01**) | `_Z11FileControlPK12SenserPacket` @**0x14d54** (376 B)，标签 `FILE_CTRL`(0x14d72) | `Serialize<FileControlType>` @0x14d68；`0x14d80 ldrh r3,[r7,#0x40]; cmp 2 / cmp 3 / cmp 1` → 1=写：`new WriteDeviceData(path, 0x1241, 0x8000)` @0x14e4c（路径由包 offset 0x42/0x44 取，`std::vector<char>` 复制，@0x14e3c/0x14dbe）；2→0x14e74、3→0x14e82（读/删，函数指针构造）；还会写 trace 文件 `tlog_update_file(4,…)` |
| MemoryDump (PFUNC **0xff03**) | `_Z10MemoryDumpPK12SenserPacket` @**0x14af8** (244 B)，标签 `MEM_DUMP`(0x14b24) | `Serialize<MemoryDumpType>` + `GetPacketRemains` 长度校验 @0x14ad4/0x14af8；`DeviceIo::open` + `mmap` + 字符串 **`/proc`**(0x14b4c) → 通过 mmap /proc/… 读内存；注册处常量 `movw r3,#0xff03` @**0xffac**；`DeviceIo::setRequest(…,&MemoryDumpType,4)` @0xf93e（`MemoryDumpType{base,size}` 见 PMCA `struct.pack('<II')`） |
| readBackup (0x603, 1) | 设备侧真正读备份：`_ZN7CUsbSvc18ReadDataFromBackupEiiPv` @**libInfraUsbCmn.so 0xd0f0** (46 B) → 调 **`Backup_nread` / `Backup_read` / `Backup_get_datasize`**（该库 UND 列表）；libsencore.so 只用 `Backup_read_4Byte`（调用点 0x163f8/0x16400/0x164ac/0x164b4，块号 0x61b @0x163cc）；app 层还有 `UFW::AdjBase::BackupWrapper_Read/Write`、`_ZN10UsbControl16ReadBackupForAdcEv`（libUsbControl.so）、`libbackup.so` 的 `Backup_get_datasize` | → **读备份不需要任何代码执行**；0x603 具体块内容/大小映射未逐块验证（`/setting` 备份 1,235,836 B 是否就是 0x603 单块）→【推断/未验】 |
| backup 写/保存 | 同上（`Backup_write` 在 libbackup.so / libUsbControl.so；libsensordpp.so 有 `SdppCmdIf::ExecCmd(SensDppSdPrm*)`、`MC_UPDATE_BACKUP_START` 字符串） | A7C II 项目已在真机使用 `readBackup/writeBackup/saveBackup` 与自定义 `(0x603,0x40/0x41)` 4 字节键值码：`refs/a7c2-fl23-research/src/camera_runtime/transport.py:344-350`、`app.py:139,178,190,196` |
| 其它 senser 命令 | `_Z8TestModePK12SenserPacket` @0x137dc；`_Z12PfuncCommandPK12SenserPacket` @0x18018；`_Z22HostCommunicationCommandPK12SenserPacket` @0x18174；`_Z13PluginCommandPK12SenserPacket` @0x18288（= PMCA 的 PFUNC **0xff07**，用于加载 `libseckeypatch.so` 插件）；`_Z25SubsystemCommunicationCommandPK12SenserPacket` @0x182c4；`_Z15TerminalReceivePK12SenserPacket` @0x18bc4 / `_Z13TerminalSendPK12SenserPacket` @0x18c7c；主循环 `_Z11SenserThreadPv` @0xfed8；`SetPacketReceiveCallback` @0x173a8 注册 6 个 handler | 字符串 `TERM_MODE`(0x28f34/0x475e0)、`FILE_CTRL`、`MEM_DUMP`、`ADJ_CTRL`、`G_SAVE_BACKUP`(0x3569c)、`DEBUG_READ`(0x2a0a4)、`DEBUG_WRITE`(0x2490)、`FACTORYDEFAULT_BACKUP_CONFIG`、`/setting/mode/dmode`、`MODE_DMODE_%08X`、`LoadPluginFile`(导入) |
| MSC 侧的 PFunc 分发 | `nflasha15_unpacked/bin/msc.elf` 里有 `PfuncCommandHandler`、`PSPFDISK`、`Sony Storage MC Ext Cmd`、`_ZN7PFuncCmdC2Ev` | 即 PMCA-RE `MscExtCmdDevice`（054C:0E8A）的对端 |

### 2.5 「终端」在 A7C 上到底是什么【已验】
`AdjustControl(0x601, 0x1f)` 在设备端执行 `/usr/bin/ulogio.elf it` 与 `/usr/bin/ulogio.elf ot`（两次 `stm_system`），
`ulogio.elf` 是**日志/内存抓取工具**（`fgets` 读 stdin、提示符 `[ulogio]>`、`/dev/mem` + `mmap`、`log address/ log size`、`snap capture`、`osal_snd_msg` IPC），
所以 senser 终端字节流（endpoint 1，0x40 字节）**喂给的是 ulogio 控制台，不是 `/bin/sh`**。→ 想做真正的 shell 必须靠 §1.3（libJit.so）或 §1.2 的 exec 面。

---

## Q3. PMCA-RE 的 `serviceshell` 能在 A7C Gen1 上用吗？

### 3.1 上位机流程（`refs/Sony-PMCA-RE/pmca/commands/usb.py`）
`senserShellCommand()`（**usb.py:658**）：
1. `SonyMscExtCmdDevice`（MSC `054C:0E8A`）→ `SonySenserAuthDevice(device.driver)` → `start()` + `authenticate()`；
2. `time.sleep(1)` 等设备重新枚举成 `SonySenserDevice`，再 `start()+authenticate()`；
3. `complete()`（打印 model/version）或 `CameraShell(ShellPlatformBackend(dev)).run()`。
`senserFileCommand()`(735)、`senserPicCommand()`(757)、`senserMemCommand()`(783)、`propertiesCommand()`、`memoryCommand()`(801) 同一套路。

认证与 A7C 特例【已验代码】：
- `SONY_ID_PRODUCT_SENSER = [0x02a9, 0x0336]`（`pmca/usb/sony.py:31`）→ **A7C 的 0336 已在支持列表**。
- `SONY_VendorRequest_StartSenser = (1, 0x37ff, 0xd7aa)`、`StopSenser = (1, 0xc800, 0x2855)`（sony.py:891-892）。
- `minSize = 0 if self.driver.getId()[1] == 0x0336 else SenserMinSize`（sony.py:854）→ **A7C 无 0x1000 填充**。
- 认证 key：`keys = constants.senserKeysSha1 if ret == 2 else constants.senserKeysSha256`，并且 **`data = data + keys[i] if getId()[1] == 0x0336 else data[:4]`**（sony.py:924-925）→ 0336 走「拼 key」分支（Sony SHA1 变体在 `pmca/usb/crypto.py`）。
- 终端：`setTerminalEnable(b)` = `_sendAdjustControlPacket(0x601, 0x1f, struct.pack("<HH", 2 if b else 0, 0xFFFF))`；`readTerminal()` = `dev.read(ep=1, size=0x40)`；`writeTerminal(d)` = `dev.write(ep=1)`（sony.py:939-952）。
- 交互 shell：`pmca/platform/backend/senser.py:12 interactiveShell()` 先 `setTerminalEnable(False/True)`，再 `transferSenserTerminal()` 用 `select` 在 socket ↔ `readTerminal/writeTerminal` 之间搬运 0x40 字节。

### 3.2 `CameraShell` 命令表（`pmca/platform/__init__.py:15-48`）+ 风险
`senser` 后端同时实现 Shell/File/Memory/Backup 四类后端（`backend/senser.py:5`），因此可用命令：
- **只读、低风险**：`info`、`pull <REMOTE>`（FileControl code 2）、`bk r <ID>`（AdjustControl 0x603 code 1）、`bootrom`（唯一直接暴露的 MemoryDump 用例：`readMemory(0xffff0000,0x6000)`）、`servicemem`（Python API 的任意 MemoryDump 读）。
- **写入、有风险**：`push <LOCAL> <REMOTE>`（FileControl code 1 → `WriteDeviceData(path,0x1241,0x8000)`，可覆盖 `/setting/*`、`/usr/local/*`；删除是 code 3）、`bk w <ID> <hex>`、`bk patch`、`bk s`（`saveBackup(0)`）、`bk lock|unlock`、以及 `AdjustControl(0x601,0x1f)` 开终端（会启动 ulogio 占日志通道）。
- 注意 PMCA 没有把「任意内存读」和「execute」暴露成 shell 子命令（`Shell` 只有 info/shell/push/pull/bootrom/bk）；任意地址读要走 `servicepics`/Python API。

### 3.3 A7C Gen1 可用性判定
- **协议层：可用**。Q2 已证明 0x0000(+0xf1)/0xff00(0x601,0x1f + 0x603 code 1..)/0xff01/0xff03/0xff07 全部在 A7C 的 `libsencore.so` 里实现；0336 的 padding/key 拼接特例已在 PMCA-RE 中。
- **驱动层（macOS）：可行**。`refs/Sony-PMCA-RE/requirements.txt` 里 `comtypes`/`pywin32` 都带 `sys_platform == 'win32'` 标记，核心只依赖 `pyusb`+`pycryptodomex`+`pyyaml`+`tlslite-ng`+`asn1crypto`（走 `pmca/usb/driver/generic/libusb.py`）→ `serviceshell / servicefiles / servicepics / serviceprops / servicemem / servicetweak` 在 macOS 上应可用（**【推断】，未在本环境实机运行**）。macOS 需先卸载/绕过 MSC 占用（`diskutil unmountDisk`），libusb 直接 claim interface 0。
- **交叉证据（同族已跑通）**：`refs/a7c2-fl23-research` 把同一份 PMCA senser 代码 vendored 到 `src/camera_runtime/vendor/pmca/usb/sony.py`（同样的 0x37ff/0xd7aa、0x0336 特判），生产流程为：`054C:0E8A` → 认证 → 相机变 **`054C:0336`**（README:121,177-178,196-201；development.md:91-95 提到 0336 未出现要冷却 30 s 重试 ≤3 次），并在真机上用 `readBackup/writeBackup/saveBackup`+`(0x603,0x40/0x41)` 写数据。该项目明确标注**原始 A7C（一代）不在其支持列表**（docs/en/changelog.md:30），所以一代仍需自行验证。

---

## 3.4 待验证 / 风险清单（下一步）
1. 【未验】`sys_tar_process` / `sys_set_timeofday` 的调用者（是否由 USB 包参数直接驱动）→ 决定 §1.2 的注入是否可达 USB。
2. 【未验】`libJit.so` 的触发时机与搜索路径（`/tmp/jiritsu/libJit.so` → ramdisk copy → dlopen），以及 `CreateScriptI/LoadScriptI/RunScriptI` 的调用约定（可从 `tools/jit_worker`、`tools/pmcctrl-receiver` 与 A7C2 项目对照）。
3. 【未验】A7C 一代上 0x603 的块号 ↔ `/setting` 备份 1,235,836 B 的对应关系；建议只做 `bk r 603` + `servicepics`/MemoryDump 只读探测。
4. 【未验】FileControl code 2/3 的读/删语义（0x14e74/0x14e82 的函数指针构造）。
5. 安全试验顺序建议：`info` → `bk r` → `pull` → MemoryDump 只读 → 才考虑 `push`/`bk w`/`bk s`（后者会改 `/setting`，失败可能导致需要重新刷机）。

## 附：本次分析产生的可复现命令
```bash
rabin2 -E firmware.tar_unpacked/0700_part_image/dev/nflasha15_unpacked/lib/libsencore.so | grep -E 'FileControl|MemoryDump|AdjustControl|ProductInfo|TestMode'
rabin2 -i .../libJiritsu.so | grep -E 'system|popen|fork|execve|stm_'
rabin2 -ld .../libJiritsu.so | grep -E 'NEEDED|RUNPATH'      # RUNPATH=/usr/local/lib, NEEDED libSTMcmdexecute.so
python3 plt.py <elf> <plt.json>       # 解析 .plt/.got -> 符号名（本机 capstone 5.0.7）
python3 jd.py  <elf> <lo> <hi> <plt.json>   # Thumb 反汇编 + PLT/字符串注释
```
