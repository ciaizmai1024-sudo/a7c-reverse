# A7C(一代) 「能不能不刷任何东西就在相机上执行命令」— `/bin/sh -c` 注入面全量审计

分析对象（全部只读）：
* `firmware.tar_unpacked/0700_part_image/dev/nflasha15_unpacked/lib/libJiritsu.so`（注释反汇编 `work/text.asm`，9365 行）
* `.../nflasha15_unpacked/lib/libsencore.so`（本次新转储 `work/sencore.asm`，15848 行，`.text 0xf394-0x18f4c`）
* `.../nflasha7_unpacked/lib/libSTMcmdexecute.so`（本次新转储 `work/stm.asm`，`.text/.init/.fini 0x664-0xa36`，全库只有 4.6 KB）
* 旁证：`libWlanAdjust.so`（`work/wlanadj.asm`）、`lib/libExternalCommand.so`、`libObj.so`、`bin/im.elf`、`bin/Wltestcmd`、`nflasha7` 原始 ext2 镜像的 inode 表

工具（新建，只读别人）：`work/cflow.py`（按 `.dynsym` 边界汇总每个函数的 PLT 调用 / 引用字符串 / 报文偏移）、`work/jiritsu_syms.txt`（`adjtbl.py sym` 输出）、`work/sencore.asm`、`work/stm.asm`、`work/wlanadj.asm`。
复现：
```bash
python3 tools/jdis.py <so> <lo> <hi> > work/<name>.asm          # 同一套 PLT/GOT/字面量注释
python3 tools/adjtbl.py sym <so> > work/jiritsu_syms.txt
python3 work/cflow.py work/text.asm work/jiritsu_syms.txt 0x4754 0x48f8 ...
```

标记：【已验（指令级）】/【推断】/【未定】。

---

## 1. 所有把字符串送进执行的汇聚点（sink）

### 1.1 libJiritsu.so —— 只有 2 处构造命令串 + 1 处真正 exec【已验（指令级）】

| # | sink（构造命令串的函数） | 格式串（rodata） | 构造点 | 交给 exec 的点 | 参数来源 |
|---|---|---|---|---|---|
| S1 | `sys_tar_process @0x45e0` (size 0x90) | `0x94b3 = '/bin/tar xpf %s ./ -C %s'`<br>`0x94cc = '/bin/tar cf %s ./ -C %s'` | `0x4608-0x4622 snprintf(buf=sp+8, 0x200, fmt, r5=r2, [sp]=r1)`（mode≠0 走 cf：`0x4614-0x4622`） | `0x4628 blx 0x30e8 → PLT _ZN13CShellExecute12ExecShellNewEPc` | **函数入参**：`sys_tar_process(mode=r0, dir=r1, archive=r2)`；`r1`→push 到 `[sp]`（第二个 `%s`=`-C` 后的目录），`r2`→`r3`（第一个 `%s`=tar 包）。入参实际全是调用方的 .rodata 常量，见 §2 |
| S2 | `sys_set_timeofday @0x4694` (size 0x78) | `0x9503 = '/bin/date -s %02d%02d%02d%02d%04d.%02d'` | `0x46b6-0x46d4 snprintf(buf=sp+0x18, 0x200, fmt, r4, [sp]=r6, [sp+4]=r8, [sp+8]=stk1, [sp+0xc]=r5, [sp+0x10]=stk2)` | `0x46da blx 0x30e8 → PLT ExecShellNew` | **6 个整数**（无 `%s`、无引号）。唯一调用者 `cmd_debug @0x4da8` 传的全是立即数：`0x4dbe movw r0,#0x7e1`(2017)、`0x4db8 movs r1,#7`、`0x4dba movs r2,#4`、`0x4dbc subs r3,#5`(=21)、`0x4dae str #0x2a`(42)、`0x4db0 subs r3,#0x10`→`str` =26 ⇒ 日期被写死成 `07 04 21 42 2017 .26` |

exec 原语：
```
0x3b78 CShellExecute::ExecShellNew(char* cmd)            [已验]
 0x3b86 memset(sp,0,0x10)                                ; argv 数组 4 个指针
 0x3b90 add r0,pc ==> 0x91b4 '/bin/sh'   ; 0x3b94 add r3,pc ==> 0x91bc '-c'
 0x3b9a str r0,[r7]      ; argv[0]='/bin/sh'
 0x3b96 str r3,[r7,#4]   ; argv[1]='-c'
 0x3b9c str r4,[r7,#8]   ; argv[2]=cmd（原样，无引号/转义）
 0x3b98 str 0,[后续]     ; argv[3]=NULL
 0x3b8e movs r2,#4       ; argc_limit=4      0x3b7e/… r3=0（不双 fork）
 0x3b9e blx 0x36d4  ==> PLT stm_system       ← 本库唯一 exec 导入
 返回：0 = OK；<0 → 0x10000000；被信号终止 → 0x10000004；退出码非 0 → 0x10000003
```
* `ExecShellNew` 的调用点只有 **0x4628 / 0x46da** 两处；`stm_system` 的 `blx` 只有 **0x3b9e** 一处。全库扫描（`grep -E "ExecShellNew|stm_system" work/text.asm`）没有第三处。【已验（指令级）】
* `rabin2 -i libJiritsu.so | grep -E 'system|popen|exec|fork'` → **只有 `stm_system` 一个**。库里没有 `system()/popen()/execve()/fork()` 的直接调用。【已验】
* **纠正旧笔记**：`notes/senser_shell.md` §1.2 说 `sys_set_timeofday @0x3a34`、格式 `'/bin/date -s "%s" %s %s'`（0x3aee），`FIRMWARE_MOD.md:272` 同 —— 两处都不对：真地址 **0x4694**（`.dynsym` 权威），格式串在 **0x9503**，**没有 `%s`、没有引号**；`stm_system` 调用点是 0x3b9e 不是 0x3a84。同理 `senser_shell.md` 说 `stm_pipe` 在 0x6b96/0x6f40 被调用 —— 实际 `grep stm_pipe work/text.asm` **零命中**（那是 `cmd_high_capacity_*` 里的本地地址，不是 stm_pipe）。【已验】
* `sys_mount @0x40fc` = `mount(2)`（`0x4112 '/dev/…'`, `0x9317 'vfat'`, `blx 0x364c → PLT mount`）；`sys_dir_create/create2 @0x4480/0x44c8` = `mkdir(2)`；`sys_rm_tree @0x3ec4` = `opendir/readdir/unlink/rmdir` 递归；`sys_file_remove2 @0x43e0` = **`glob(path)` + `unlink`**（见 §6-B，通配符会被解释）。**这些都不是 shell 版本**，所以路径里的 `;|&$()*` 对它们无意义。【已验（指令级）】

### 1.2 libsencore.so（ProductInfo/AdjustControl/FileControl/MemoryDump 的库）—— 2 处 exec，**不经 shell**【已验（指令级）】

```
唯一 exec 导入：stm_system（PLT stub 0xe644）。全 .text 只有 2 个 blx 0xe644：0x1634a、0x16378
（都在 AdjustControl block 0x601 / code 0x1f「终端使能」里）
0x1632c add r5,pc ==> 0x38715 '/usr/bin/ulogio.elf'
0x16346 str r5,[r7,#0xc4]      ; argv[0] = 常量路径
0x16338 str r3,[r7,#0xc8]      ; argv[1] = 0x56cf4 'it'   （第二处 0x53729? 实为 0x38729 'ot'）
0x16340 str r3,[r7,#0xcc]      ; argv[2] = &(r7+0x14) —— 见下
0x16344 movs r3,#0 ; (r2=4 argc_limit, r3=0) ; blx 0xe644 stm_system
喂 argv[2] 的那 1 个字符来自报文：0x16306 ldrb r3,[r4,#0x1c]; 0x1630e adds r3,#0x30; 0x16310 strb r3,[r7,#0x14]
（`0x16308/0x16318 strh 0` 把它后面清零 ⇒ argv[2] 就是「pkt[0x1c]+0x30」这 1 字节，NUL 结尾）
```
* 这是 `execve("/usr/bin/ulogio.elf", ["/usr/bin/ulogio.elf","it","<char>",NULL], envp)` —— **没有 `/bin/sh -c`**，所以 `;`、`|`、`$()` 等元字符完全不被解释。PC 能改的只是那个字符（且 pkt 字节 ≥0xd0 时 `(b+0x30)&0xff` 可为 0 ⇒ 空串 argv）。【已验（指令级）】
* `rabin2 -i libsencore.so` 里 `system/popen/execve/fork` 只有 `stm_system` 一个导入；`grep -E "PLT (system|popen|execve|fork)" work/sencore.asm` 零命中。libsencore 里**没有其它 sh 注入面**。【已验】

### 1.3 libSTMcmdexecute.so 与「谁在用 exec 原语」（全固件枚举）

`find firmware.tar_unpacked -name 'libSTMcmdexecute*'` → **在包里**：`0700_part_image/dev/nflasha7_unpacked/lib/libSTMcmdexecute.so`（4640 B，DT 导出只有 `stm_system @0x828`、`stm_popen @0x8cc`、`stm_pclose @0x9c4`）。【已验】

`grep -rl stm_system firmware.tar_unpacked` 的完整名单（去掉 raw 镜像与自身）：
`libJiritsu.so`（§1.1）、`libsencore.so`（§1.2）、`bin/im.elf`、`bin/Wltestcmd`、`lib/libObj.so`、`lib/libupdaterufp.so`。
另有 `lib/libExternalCommand.so`（`ExternalCommand::exec` 用 `stm_popen`+`system/popen`）与 `lib/libNetService.so`：
* `libExternalCommand` 只被 `libWlanAdjust.so` 使用，且 `libWlanAdjust` 里唯一的 `ExternalCommand::exec` 调用点在 **0x7462**，命令串是**常量** `0xc31e = '/usr/bin/Wltestcmd TX stop'`（`0x7442`）。【已验（指令级）】
* `libNetService` 属网络栈（WiFi/UPnP），不在 USB senser/Jiritsu 通道上。【推断】
* `im.elf` 里的命令串：`'/usr/bin/e2fsck -y %s'`、`'/usr/bin/sen.elf &'`；`libObj.so` 里是工厂 BT/WLAN 测试串（`/usr/bin/btRFTest.elf …`、`/usr/bin/Wltestcmd …`）；`Wltestcmd` 自己拼 `/usr/bin/wl -i wlan0 %s`（`band %s`、`%s_rate -r %.1f`）。这些都不在 Jiritsu/senser 报文可达的路径上。【推断（未逐一追调用者）】

---

## 2. `sys_tar_process` 两条路径参数的来源：**全部是 .rodata 常量**【已验（指令级）】

包装层（尾调用 PLT stub 0x3310 → `sys_tar_process`）：
```
0x4670 sys_tar_compress(dir=r0, archive=r1) : 0x4670 mov r3,r0; 0x4672 mov r2,r1; 0x4676 movs r0,#1; 0x467a mov r1,r3; b 0x3310
        ⇒ sys_tar_process(1, dir, archive) ⇒ '/bin/tar cf <archive> ./ -C <dir>'
0x4684 sys_tar_extract(archive=r0, dir=r1)  : 0x4686 mov r2,r0; 0x468a movs r0,#0; b 0x3310
        ⇒ sys_tar_process(0, dir, archive) ⇒ '/bin/tar xpf <archive> ./ -C <dir>'
```
`grep "PLT sys_tar_compress|sys_tar_extract|sys_tar_process" work/text.asm` → 只有 3 个外部调用点，逐条看参数：

| 调用点 | 所在函数 | 由哪条命令到 | 参数（指令证据） | 最终命令行 |
|---|---|---|---|---|
| **0x6874** `PLT sys_tar_compress` | `adj_cmd_set_firm @0x67ec`（cmd **6** FIRMUP，`mode&2` 分支） | `0x4006` | `0x6834 add r5,pc ==> 0x953e '/tmp/jiritsu'`；`0x686e ldr r8,[..]; 0x6870 add r8,pc ==> 0x9e0d '/tmp/jiritsu.bak.tar'`；`0x686e mov r0,r5; 0x6872 mov r1,r8` | `tar cf /tmp/jiritsu.bak.tar ./ -C /tmp/jiritsu` |
| **0x69d2** `PLT sys_tar_extract` | `adj_cmd_set_firm @0x67ec`（cmd **6**，第 9 步） | `0x4006` | `0x69ca-0x69ce add r0,pc ==> 0x9efd '/tmp/jiritsu/ramdsk/jiritsu.dat'`；`add r1,pc ==> 0x953e '/tmp/jiritsu'`（注意：`jiritsu.dat` 的**内容**是 PC 给的 tar 包，路径本身是常量） | `tar xpf /tmp/jiritsu/ramdsk/jiritsu.dat ./ -C /tmp/jiritsu` |
| **0x7604** `PLT sys_tar_extract` | `CImJiritsu::jit_thread @0x74b0`（开机/jinit 残留时自动回滚） | 无（内部线程） | `0x75ce add r6,pc ==> 0x9e0d '/tmp/jiritsu.bak.tar'`；`0x7602 add r1,pc ==> 0x953e '/tmp/jiritsu'` | `tar xpf /tmp/jiritsu.bak.tar ./ -C /tmp/jiritsu` |

⇒ **没有任何命令号能把 PC 给的路径喂进 tar 命令行。** 三个调用点的两个路径都是 `ldr/add pc` 立即数取 .rodata 常量。【已验（指令级）】

### 2.1 逐个命令的「有没有 shell 版 tar/mkdir/rm/mount」

`work/cflow.py` 汇总（`CALL` 去重后；STR 只列路径类）。凡下表没有出现 `ExecShellNew`/`stm_system`，即该命令**完全不碰 shell**：【已验（指令级）】

| cmd（本仓库记法 `block=0x1001, code=0x4000\|n`） | 处理函数 | 用到的 exec/文件系统原语 | 路径参数来源 |
|---|---|---|---|
| 1 MODE `0x4001` | `cmd_mode @0x4754` | `sys_file_chk_exist`/`mode_file_read`/`mode_file_write`/`sys_file_remove`/`snprintf('%s',…)` | 常量 `/tmp/jmode`(0x91d3)；mode 字节 = `msg[0x1c]` |
| 2 MOUNT `0x4002` | `cmd_mount @0x64d0` | `sys_mount`(mount(2))/`sys_umount`/`sys_dir_create`(mkdir(2))/`sys_file_remove`/`sys_media_mount` | 常量 `/tmp/jiritsu`、`/dev/nflasha6` |
| 3 FORMAT `0x4003` | `cmd_format @0x48f8` | `sys_mount`/`sys_rm_tree`(**递归 unlink/rmdir**)/`unlink`/`opendir`/`readdir` | 常量 `/tmp/jiritsu`、`/tmp`、`/dev/nflasha6`、`/tmp/jbusy`、`/tmp/jmode` |
| 4 START `0x4004` | `cmd_start @0x4b60` | `mode_file_read` + `CImJiritsu::init/run/get_status`（dlopen 线） | 常量 `/tmp/jmode`；要求内容 `Manual`(0x96b4) |
| 5 DEBUG `0x4005` | `cmd_debug @0x4da8` | **只调 `sys_set_timeofday`（S2）** | **全常量日期**（§1.1） |
| 6 FIRMUP `0x4006` | `adj_cmd_set_firm @0x67ec` | **shell：S1×2**（cf 备份 / xpf 主机 tar）+ `ramdisk_mount`/`open/write`/`sys_file_md5hash`/`sys_file_remove2`(glob+unlink)/`remove` | tar 路径常量；**tar 内容 = PC 数据**（写到 `/tmp/jiritsu/ramdsk/jiritsu.dat`） |
| 7 SET_FILE `0x4007` | `adj_cmd_set_file @0x56c0` | `sys_mount`/`open/write/fsync/close`/`dlopen+dlclose`/`glob('/tmp/jiritsu/*')`(配额) | 路径来自 **area id 表**（`get_jiritsu_area_filename(msg[0x1d])`），不是 PC 串 |
| 8 GET_FILE `0x4008` | `adj_cmd_get_file @0x5468` | `open/read`/`strncat`（把内联路径拼到 `/mnt`） | `mode=msg[0x1c]`、`id=msg[0x1d]`、`flag=msg[0x1e]`；**mode1 ⇒ 内联路径在 `msg+0x1f`**（缓冲 0x1000B） |
| 9 FILE_DELETE `0x4009` | `cmd_file_delete @0x58f8` | `sys_mount` + `sys_file_remove`（unlink(2)） | area id（`msg[0x1d]`） |
| 10 GET_FILELIST `0x400a` | `adj_cmd_get_file_list @0x641c` | `search_dir`(`opendir/readdir`) | 常量 `/mnt` |
| 11 GET_FILE_HASH `0x400b` | `adj_cmd_get_file_hash @0x6c54` | `open/read` + `libCommuMD5`（**不是 md5sum**） | area id / `/mnt` |
| 12 COMPARE_MEDIA `0x400c` | `adj_cmd_compare_media @0x625c` | `sys_media_mount`/`open/write/read/memcmp` | 常量 **`/mnt/.compare`**(0x9cb5) —— 不调 tar/shell |
| 13 GET_VERSION `0x400d` | `adj_cmd_get_version @0x5028` | `open/read`/`sys_split` | 常量 `/tmp/jiritsu/ver.txt` |
| 14 FACTORY `0x400e` | `cmd_factory @0x519c` | 只有 `osal_wai_sem_tmo`/`osal_sig_sem`/`memcpy`（信号量+拷贝） | `msg[0x1c..0x24]`；**无任何文件系统/shell 调用** |
| **15 SET_FILE_PATH `0x400f`** | `adj_cmd_set_file_path @0x52a8` | `calloc/memcpy` + 清洗循环（§3）；**不 exec** | **PC 串**：DMM/包 payload，`unit+1`（= `msg+0x1d`），长 `L-1`（`L=msg[0x14]`，`L-2 < 0x200`）→ 存全局 `g_customPath @0x32590` |
| **16 SET_FILE2 `0x4010`** | `adj_cmd_set_file2 @0x5b00` | `sys_mount`/`sys_dir_create2`(mkdir)/`open(O_CREAT\|O_TRUNC,0600)/write/fsync/close`/`dlopen+dlclose`/`sys_get_dir_size`(`glob('/tmp/jiritsu/*')` 配额) | `mode=msg[0x1c]`,`id=msg[0x1d]`,`flag=msg[0x1e]`；`mode1` 时 `0x5b5c strb 0xff,[msg,#0x1d]` ⇒ 走 `g_customPath`；路径由 `get_access_filename @0x5948` 合成 |
| **17 GET_FILE2 `0x4011`** | `adj_cmd_get_file2 @0x5fe8` | `sys_mount`/`sys_media_mount`/`open/read` | 同上；`mode∉{0,1,0xff}` → `0x10000201`（`0x60c0`），基目录常量 `""`(0x997d) 用不上 |
| **18 FILE_DELETE2 `0x4012`** | `cmd_file_delete2 @0x5f18` | `sys_rm_tree` + `sys_dir_remove`(rmdir) 或 **`sys_file_remove2` = `glob(path)`+`unlink`** | 同上；**`mode=msg[0x1c] ∉ {0,1}` ⇒ 基目录 = 空串 0x997d ⇒ 最终路径 = `g_customPath` 原样**（`0x5f66 add r1,pc ==> 0x997d`，且无错误码分支） |
| 19 TEST_UI_VIEW `code=0x1001/0x0013…`（pfunc=0） | `cmd_test_ui_view @0x4dd2` | 空（12 字节） | — |

⇒ `cmd_compare_media(12)`、`adj_cmd_set_file_path(15)`、`adj_cmd_set_file(7)`、`cmd_format(3)`、`cmd_factory(14)`、`cmd_start(4)` 里**都没有 shell 版 tar/mkdir/rm/mount**：要么系统调用，要么路径是常量。【已验（指令级）】

### 2.2 PC 路径的最终落点（`get_access_filename @0x5948`）【已验（指令级）】
```
0x59c6 ldr r5,[GOT] ==> 0x32590 g_customPath      ; id==0xff 时取 PC 给的串
0x59d0 strlen ; 0x59da strncmp(基目录, g_customPath, …)   ; 若已以基目录开头 → 原样
0x59ec ldrb r3,[g_customPath] ; cmp r3,#0x2f('/')
0x59f8 add r2,pc ==> 0x929c '%s/%s'   （不以 / 开头）
0x5a06 add r2,pc ==> 0x9bab '%s%s'    （以 / 开头 → 直接 dir+path，dir 可为空串 0x997d）
0x5a0a blx 0x380c snprintf
```
* PC 串永远是 snprintf 的**参数**而不是格式串 ⇒ 没有格式串漏洞；**没有任何 `..`、前缀、引号检查**。【已验】
* area id 分支（id 0..4 与 ≥0x10 的 34 条表）也是 `snprintf('%s', 常量)`。【已验】

---

## 3. 过滤器（逐条指令）：只有 1 个，在 `adj_cmd_set_file_path @0x52a8` 里【已验（指令级）】

```
0x52ae ldr r6,[msg,#0x14]            ; L
0x52b4 subs r4,r6,#1 ; 0x52b6 subs r3,r4,#1 ; 0x52b8 cmp r3,#0x200 ; 0x52bc blo ok
       ⇒ 长度门：L-2 < 0x200 ⇒ 路径字节数 ≤ 0x200(512)，calloc(L,1) 尾页给 NUL
0x52e6 ldrb r3,[msg,#0x1c] ; 0x52ea cmp r3,#0 ; bne → 只登记 DMM 缓冲、不存路径（状态 0）
0x5310 memcpy(g_customPath, unit+1, n=L-1)
0x5318 ldrb r1,[r3],#1                ; ← 逐字节清洗循环
0x531c cmp r1,#0x5c ; 0x5320 subs r1,#0x2d ; 0x5322 strb r1,[r3,#-1]   ; '\' → '/'（0x5c-0x2d=0x2f）
0x5326 ldrb r1,[r3,#-1]
0x532a cmp r1,#0x0a ; beq reject        ; \n 拒绝
0x532e cmp r1,#0x0d ; beq reject        ; \r 拒绝
0x5332 cmp r1,#0x2c ; bne next          ; ',' 拒绝（0x5336: free + g_customPath=NULL + 状态 0x10000201）
0x5346 adds r2,#1 ; 0x5348 cmp r2,r4 ; blo 0x5318
```
**没有第三处过滤**（`grep -E "cmp r[0-9]+, #(0xa|0xd|0x2c|0x5c)" work/text.asm` 只命中这一段）。

字符判定表（回答"哪些能通过"）：

| 字符 | 能否通过 cmd 15 过滤 | 备注 |
|---|---|---|
| 空格 `0x20` | ✅ 通过 | |
| `;` `0x3b` | ✅ | |
| `\|` `0x7c` | ✅ | |
| `&` `0x26` | ✅ | |
| `$` `0x24` / `$(` | ✅ | |
| 反引号 `` ` `` `0x60` | ✅ | |
| `"` `0x22` / `'` `0x27` | ✅ | |
| `(` `0x28` `)` `0x29` | ✅ | |
| `*` `0x2a` | ✅ | 会被 **glob()** 解释（`sys_file_remove2`、配额 glob）→ 有通配符能力，非 shell 执行 |
| `>` `0x3e` `<` `0x3c` | ✅ | |
| `?`、`[]`、`~`、`#`、`{}`、Tab | ✅ | |
| `..` | ✅（完全不检查） | 挂载点归一化在 kernel，`/tmp/jiritsu/../../etc` 逃出 nflasha6 |
| `/` | ✅ | |
| `\` `0x5c` | 被**改写**成 `/` | |
| `\n 0x0a`、`\r 0x0d`、`, 0x2c` | ❌ 拒绝（状态码 `0x10000201`，`g_customPath` 置 NULL） | 唯一被拒的三个 |

⇒ **过滤本身绝不构成 shell 防线**：所有元字符都能进 `g_customPath`。挡住的不是过滤器，而是"没有任何 PC 串能到达 shell"（§1.1/§2）。

---

## 4. `/bin/date` 那条

* 走到它的唯一路径：**Jiritsu cmd 5 = `DEBUG`（`code=0x4005`, `block=0x1001`）→ `cmd_debug @0x4da8` → 0x4dc2 `PLT sys_set_timeofday` → S2 → `/bin/sh -c '/bin/date -s %02d…'`**。【已验（指令级）】
* **`%s` 不存在**：格式串是 `0x9503 = '/bin/date -s %02d%02d%02d%02d%04d.%02d'`，6 个整数（busybox/ash 的 `date -s MMDDhhmmYYYY.ss`）。【已验】
* 6 个参数全部是 `cmd_debug` 里的立即数（`2017/7/4/21` + 栈上 `42/26`）⇒ **PC 不可控任何字节**，注入需要闭合 `"` 这件事根本不适用（命令行里根本没有引号）。【已验】
* 副作用/可观测：发一条 `0x4005` 会把相机时钟设成 **2017-07-04 21:42:26**（之后读 `/tmp/jiritsu/jit.log`、备份块里的时间戳、或 GET_VERSION/日志时间都能看到跳变）。除此之外没有别的命令改时间：`grep sys_set_timeofday work/text.asm` 只有 0x4dc2 一个调用点；全固件只有 `libJiritsu.so` 含该符号（`grep -rl sys_set_timeofday firmware.tar_unpacked`）。【已验】
* ⇒ 结论：**date 面不可注入**。【已验（指令级）】

---

## 5. `libSTMcmdexecute.so` 的护栏（0x828 附近逐条）【已验（指令级）】

导出：`stm_system @0x828`(164B)、`stm_popen @0x8cc`(248B)、`stm_pclose @0x9c4`(106B)。

```
0x0828 stm_system(path r0, argv r1, argc_limit r2, flag r3):
 0x083a bl 0x7b8                     ; ★唯一的校验器（见下）  <0 → 返回 -1（0x8b6）
 0x0842 fork ; <0 → -1 ; !=0 → 父进程 0x884
 子进程： 0x084c cmp r8(flag),#0 ; bne 0x860 → 再 fork 一次（守护化；ExecShellNew 传 flag=0 ⇒ 不双 fork）
 0x0852 bl 0x7f6                     ; 关 fd：getrlimit(RLIMIT_NOFILE=7)，失败则上限 0x100；close(fd) for fd=3..max
 0x0856-0x085c r0=path, r1=argv, r2 = ==> 0x8cd4（固定 envp 数组）
 0x0876 blx PLT execve ; 失败 → 0x087a movs r0,#1 ; 0x0880 blx PLT _exit
 父进程： 0x088a blx PLT waitpid(pid, &status(sp+4), 0)
 0x0894 __errno_location; errno==10(ECHILD) → 收；errno==4(EINTR) → 0x884 再 wait；
 0x08a4 ands r3,status,#0x7f ; ==0 → 返回 status；否则 (r3+1)>>1 > 0 → 再 waitpid（信号终止会重试）
 返回值 = 原始 wait status（ExecShellNew 再解成 0x10000003/0x10000004）
```
校验器 `0x7b8`（`stm_popen` 也调它，0x8f0）：
```
0x07c2 cbz r0 → -1                        ; path != NULL
0x07c4 blx PLT strlen ; 0x07c8 cmp #0x1000 ; bhi → -1     ; path 长度 ≤ 4096
0x07ce ldrb r3,[r0] ; 0x07d0 cmp #0x2f ; bne → -1          ; ★path 必须以 '/' 开头（绝对路径）
0x07d4 cmp r5(argc_limit),#0x14 ; bgt → -1                 ; argc_limit ≤ 20
0x07d8 cbz r4(argv) → -1
0x07de loop: ldr r0,[r4],#4 ; cbz r0 → 返回 0 ; r3++ ; cmp r3,r5 ; blt 继续  → 超限 -1
       ★ 只数 argv 条目数，**不检查任何条目里的字符**
```
固定环境（execve 的 envp = `&0x8cd4`，`.data`，由 `.rel.dyn` 的 R_ARM_ABS32 重定位到 `.rodata`）：
```
0x8cd4 → 0xa3a 'HOME=/'
0x8cd8 → 0xa41 'PATH=/sbin:/bin:/usr/sbin:/usr/bin'
0x8cdc → 0xa64 'TOPRC=/etc/toprc'
0x8ce0 → 0xa75 'MALLOC_OPTIONS=gfffffffff'
0x8ce4 → 0xa8f 'MALLOC_MMAP_THRESHOLD_=32768'
0x8ce8 → 0xaac 'MALLOC_TRIM_THRESHOLD_=32768'
0x8cec → 0xac9 'LT_ABORTREASON=0'      ; 末尾 0x8cf0 = 0 → NULL 结尾
```
护栏清单：
* 有：path 非空 / 绝对路径 / ≤4096；argv 非空且条目数 ≤ argc_limit(≤20)；子进程关掉 fd≥3；失败 `_exit(1)`；`stm_popen` 的 mode 只允许 `'r'`/`'w'`(0x8fc-0x904)。
* **没有**：可执行文件白名单、参数引用/转义、`chroot`、`setuid/setgid/drop groups`、`alarm`/超时/看门狗（`waitpid` 无 WNOHANG ⇒ **会无限期阻塞命令处理线程**）、`rlimit` 收紧（只是读出来关 fd）、`ptrace` 限制（只有 `getrlimit`，无 PR_SET_PTRACER）、任何字符过滤。
  （纠正 `notes/senser_shell.md` §1.2 说的「`__libc_stack_end` 读取 + `prctl(PR_SET_PTRACER)`」：`work/stm.asm` 里 0x7f6 只做 `getrlimit`+`close` 循环，**没有 prctl**，且导入表里也没有 `prctl`。）【已验】
* `execve` 的 argv **就是** `{"/bin/sh","-c",cmd,NULL}`（libJiritsu 侧 `0x3b9a/0x3b96/0x3b9c`），path = `"/bin/sh"` ⇒ **cmd 里的 shell 元字符会被 `/bin/sh` 完整解释**。【已验（指令级）】
* `/bin/sh`、`/bin/tar`、`/bin/date` 在真机上存在：解包目录里 `nflasha7_unpacked/bin/` 只有 `busybox`+9 个真文件（解包丢了 symlink：整个解包树 `find -type l` = 0 个），但 `nflasha7` 原始 ext2 镜像的 inode 表里有**每 128 B 一条、i_mode 低位 `0xa1ff`(symlink 0777)、i_size=7、fast-symlink 目标 `"busybox"`** 的成串 inode（如 file off 26024/26152/26280…）⇒ rootfs 的 `/bin/{sh,tar,date,…}` 是 busybox applet 软链。【已验（镜像 inode）】具体名字（`sh`/`tar`/`date`）为【推断（强）】—— Sony 产线 FIRMUP 命令依赖 `/bin/tar`，A7C II 同代码线在生产上使用。

---

## 6. 判定 + PoC

### 6.1 判定：**经由 `/bin/sh` 不可注入**【已验（指令级）】

堵点（按证据强度）：
1. **tar 的两个 `%s` 永远是常量**：`sys_tar_process` 只有 3 个调用者（0x6874 / 0x69d2 / 0x7604），两参数都是 `add rX,pc ==> .rodata` 常量（`/tmp/jiritsu`、`/tmp/jiritsu.bak.tar`、`/tmp/jiritsu/ramdsk/jiritsu.dat`）。没有任何命令号能把 PC 串放进这两格。→ 「把路径写成 `x; id > /tmp/jiritsu/INJ.txt;`」在**一代根本不适用**：没有哪个命令的路径参数来自报文。【已验】
2. **date 的命令行没有 `%s`**，只有 `%02d/%04d`，参数是 `cmd_debug` 的立即数。【已验】
3. **libsencore 的 2 处 exec 不经 shell**（`execve("/usr/bin/ulogio.elf", …)`），PC 只能改 argv 里的一个 ASCII 字符。【已验】
4. `ExecShellNew`/`sys_tar_process`/`sys_set_timeofday` 都是 libJiritsu 自己的符号，全固件没有别的模块引用它们（`grep -rl "ExecShellNew" / "sys_tar_process" / "sys_set_timeofday" firmware.tar_unpacked` 只命中 libJiritsu.so + raw 镜像），也没有 dlsym 动态取名的迹象（Jiritsu 的 dlsym 只取 `CreateScriptI/LoadScriptI/RunScriptI/DestroyScriptI`）。【已验（符号级）】

即：**没有一条 USB 报文能让相机执行 `/bin/sh -c '<我们拼的串>'` 里我们控制的字节。** 想执行命令，只能走「写文件 + 让相机自己去 load」的路线（下一节）。

### 6.2 最接近可利用的位置（按价值排序）

**A. `FILE_DELETE2`(0x4012) 的 glob 语义 + 空基目录**（本次新发现）【已验（指令级）】
* `cmd_file_delete2 @0x5f18`：`mode=msg[0x1c] ∉ {0,1}` ⇒ 基目录 = **空串 0x997d**，最终路径 = `g_customPath` **原样**（`get_access_filename` 走 `'%s%s'`）；路径最后一个字符 `'/'`(0x5f82-0x5f88) ⇒ `sys_rm_tree(path)`(递归 unlink+rmdir) + `sys_dir_remove`；否则 `sys_file_remove2(path)` = **`glob(path, 0, NULL, &g)` 然后对每个 regular 文件 `unlink`**（0x43f0-0x442c，`S_IFREG` 判定 `and r3,[globbuf+0x10],#0xf000; cmp #0x8000`）。
* 含义：`*`/`?`/`[…]` 会被 **glob 展开**（这是"通配符"能力：一条命令删一批文件），且路径可以 `..` 逃出 `/tmp/jiritsu`。**不是** shell，`;`/`|`/`>` 无意义。
* 风险：删错就是删错，无回收。

**B. `SET_FILE_PATH`(0x400f) + `SET_FILE2`(0x4010) 的 `..` 越界写 = 真正的"不刷机拿执行"**【已验（路径合成与 syscall 级）】
* 合成：`snprintf('%s%s', '/tmp/jiritsu', g_customPath)`，`g_customPath` 以 `/` 开头时直接拼接；`..` 不检查；`sys_dir_create2` 会 `mkdir` 缺失的父目录；`open(path, 0x241(O_RDWR?O_CREAT|O_TRUNC), 0600)` + `write` + `fsync`。
* 落点：`/tmp/jiritsu` 是 nflasha6 的挂载点，`/tmp/jiritsu/..` = `/tmp`；`/tmp` 与 `/etc` 同一分区（`TEST_LADDER.md`：nflasha10 12 MB，`/tmp=/etc`）。所以
 `../../etc/ld.so.preload` → `/etc/ld.so.preload`（真 flash、开机生效）
 `../..` 一路到 `/` 还能碰到 `/setting`(备份区)、`/var`、`/tmp`（tmpfs，重启即清）。
* 配额只统计 `glob('/tmp/jiritsu/*')` 的已用量（`sys_get_dir_size`），所以写到 `/etc` **不受 5 MiB 限制**，但也因此**没人保护 flash**。【已验】

**C. cmd 6 FIRMUP(0x4006)：命令行固定，但 tar 包的**内容**是 PC 给的**【已验调用；成员名 `..` 行为未定】
* 命令行固定：`/bin/tar xpf /tmp/jiritsu/ramdsk/jiritsu.dat ./ -C /tmp/jiritsu`。若 busybox tar 允许成员名里的 `../..`（busybox 只剥开头 `/`），一条 FIRMUP 就能把带自选 mode/owner 的文件写到 `/tmp/jiritsu` 之外；`p` 位保留权限、可含 symlink 成员 ⇒ 后续写可穿过软链。**busybox 版本的 `..` 处理未实机验证【未定】**；`tools/jiritsu_pack.py` 里刻意全用 `./` 开头条目（`TEST_LADDER.md` §30 也说要比对条目/权限/软链行为【未做】）。

**D. `libJit.so` dlopen 线（最强、已知）**：`SET_FILE2` 写 `/tmp/jiritsu/libJit.so`（要求 `/tmp/jbusy` 不存在，写前 dlopen+dlclose 校验 ELF）→ `jit_thread @0x74b0` 把它复制到 `/tmp/jiritsu/ramdsk_libJit`(ramdisk 1M) → `dlopen` → `dlsym CreateScriptI/LoadScriptI/RunScriptI/DestroyScriptI` 并调用 ⇒ **任意 ARM 原生代码执行**（worker 里自己 `system()` 就有完整 shell）。【已验调用点；触发时机推断】

### 6.3 PoC（按现在的固件，用「写 + 让相机 load」而不是 shell）

> 若你原来设想的 PoC 是 `PFUNC=0x40 + block=0x1001 + code=0x400X` + 路径 `x; id > /tmp/jiritsu/INJ.txt;`：**一代不适用**（该路径参数不存在；见 6.1）。下面是**等价可行**的四要素。

**PoC-1（低风险、只碰 tmpfs，先验证「PC 串真的被当路径用」）**【已验语义（指令级），实机未做】
* (a) 命令号/块码：`block=0x1001, code=0x400f`（cmd 15 SET_FILE_PATH）载荷 `[0x00] + b'../../tmp/inj_probe.txt\0'`；然后 `code=0x4010`（cmd 16 SET_FILE2）小头 `mode=0x00, id=0x00, flag=0x00` + 数据 = 任意内容（≤5 MiB）。
* (b) 前置条件：**必须先发 0x400f（mode 字节 msg[0x1c] 必须为 0，否则 0x52ec 分支只登记 DMM、不存路径）**；不需要 `MOUNT(0x4002)`（SET_FILE2 mode0 自己 `sys_mount('/dev/nflasha6','/tmp/jiritsu')` @0x5b48）；不需要 `/tmp/jbusy` 不存在（那个检查只在写 `libJit.so` 时做，0x5c7c）；不需要 `/tmp/jmode` = Manual（那是 `cmd_start` 的要求）。注意路径里**不能含 `\n \r ,`**，长度 ≤512。
* (c) 可观测副作用：`code=0x4011`（GET_FILE2，mode0/id0xff/flag0）把 `/tmp/inj_probe.txt` 读回；或 GET_FILE2 用 id0xff 读到 → 状态码 0 + 内容匹配。`/tmp` 是 tmpfs ⇒ **重启自动清干净**。
* (d) 风险：极低（只写 tmpfs）。若忘了带 `mode=0`，会得到状态 `0x10000201`（无副作用）。

**PoC-2（真执行，写 flash）**【路径合成已验；实机风险按 TEST_LADDER 的评级】
* (a) `0x400f` 存路径 `../../etc/poc/hello.txt`（或直接 `../../etc/ld.so.preload`，但**别第一次就写 preload**），`0x4010` 写内容。
* (b) 前置：同 PoC-1；写 `ld.so.preload`/任何 flash 文件前先按 `TEST_LADDER.md` L1 拉回原厂 `/tmp/jiritsu` 全套 + `df`（`/tmp=/etc` 写满会让所有写报 `0x10000009`）。
* (c) 观测：`0x4011`(GET_FILE2 id0xff) 读回；重启后仍在（flash）。若要"执行"：写 `/etc/ld.so.preload` 指到一个我们也用 SET_FILE2 写进去的 `.so`（busybox 是动态链接 ⇒ preload 写错会全灭，`FIRMWARE_MOD.md:361`）。或者更稳：走 D（`libJit.so` worker，4 个导出符号见 `tools/jiritsu_pack.py`）。
* (d) 风险：**`..` 越界写没有回滚机制**（`.bak.tar` 只覆盖 `/tmp/jiritsu`）；`sys_dir_create2` 会在 flash 上 `mkdir` 目录（残留）；文件被建成 **0600 root**；写坏 `/etc` 需要靠更新器重建（`us_mkfs.sh -m app`）。

**PoC-3（glob 通配符演示，用 A 的发现）**【已验（指令级）】
* (a) `0x400f` 存 `'/tmp/jiritsu/ramdsk*'`（或 `…/*.dat`），`0x4012`(FILE_DELETE2) 小头 `mode=0x02`（∉{0,1} ⇒ 原样路径、且**不挂 nflasha6**）、`id=0x00`。
* (b) 前置：先 FIRMUP 或在 nflasha6 上有一个可删的测试文件；用 `mode=0x00` 时会先挂 nflasha6 并把路径拼到 `/tmp/jiritsu`（此时 glob 字符同样生效）。
* (c) 观测：`0x400a`(GET_FILELIST) 或 `0x4011` 确认目标消失。
* (d) 风险：glob 一次删多个；路径末尾带 `/` 会触发 `sys_rm_tree` **递归删**。删错无救（尤其别用 `../../etc/*`）。

---

## 7. 与旧笔记的勘误清单（便于以后引用）

| 位置 | 旧说法 | 实际（本次逐指令） |
|---|---|---|
| `notes/senser_shell.md` §1.2 / `FIRMWARE_MOD.md:272` | `sys_set_timeofday @0x3a34`，串 `'/bin/date -s "%s" %s %s'`(0x3aee)，`stm_system` 调用点 0x3a84 | `sys_set_timeofday @**0x4694**`（`.dynsym`，size 0x78），串 `0x9503 = '/bin/date -s %02d%02d%02d%02d%04d.%02d'`（**无 %s、无引号**），snprintf 0x46d4 / ExecShellNew 0x46da；唯一调用者 `cmd_debug @0x4da8`（0x4dc2），参数全常量 |
| `notes/senser_shell.md` §1.2 | 「文件名来自包内（是否过滤未验证）⇒ 推断存在文件名注入面」 | **不成立**：tar 的路径参数 3 个调用点全是 .rodata 常量；报文里的路径从不进 tar 命令行 |
| `notes/senser_shell.md` §1.2 | `stm_pipe` 在 0x6b96/0x6f40 被 libJiritsu 调用 | `grep stm_pipe work/text.asm` = 0 命中；libJiritsu 只用 `stm_system`（0x3b9e） |
| `notes/senser_shell.md` §1.2 | `stm_system` 里有 `prctl(PR_SET_PTRACER)`/`__libc_stack_end` | `libSTMcmdexecute.so` 导入表无 `prctl`；0x7f6 = `getrlimit`+`close(3..max)` |
| `notes/jiritsu.md` §4 | `sys_tar_process` 的 `mode 1/0` 与参数序 | 补充精确化：`sys_tar_compress(dir, archive)` / `sys_tar_extract(archive, dir)`（0x4670/0x4684 的尾调用参数交换），两个 `%s` 顺序 = (archive, dir) |
| `notes/jiritsu.md` §1 | `cmd_format @0x48f8`、`cmd_debug @0x4da8` 等 | 与 `.dynsym` 一致（`work/jiritsu_syms.txt` 可重放） |
