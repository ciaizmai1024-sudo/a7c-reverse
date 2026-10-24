# A7C(一代) `libJiritsu.so` 静态分析 — 命令分发 / 文件通道 / libJit / 调参文件

目标：`firmware.tar_unpacked/0700_part_image/dev/nflasha15_unpacked/lib/libJiritsu.so`
（一代 A7C v2.00 `nflasha15` 里的 Jiritsu / AdjustGuide 插件，ARM32 Thumb-2，DT_INIT = `jiritsu_init`）

## 0. 工具与可复查性（本文每个地址都能重放）

| 文件 | 作用 |
|---|---|
| `tools/jdis.py` | 自写 Thumb(-2) 反汇编器（capstone5 + 手写 ARM PLT stub），带 ELF 语义注释：`blx 0x3320 ;; -> PLT dlopen`、`ldr r3,[r4,#0x31c] ;; GOT _Z11sens_searchPKvS0_`、字面量池 `==> 0x953e = '/tmp/jiritsu'`；GOT/数据槽 → `.rel.dyn/.rel.plt` 符号名 |
| `tools/tbl.py` | 找 TBB/TBH 跳转表（字节特征 `df e8 ?? f0`）并解出 case→target |
| `work/text.asm` | 整段 `.text`(0x3944–0x91ac，9365 行) 带注释反汇编 |
| `tools/adjtbl.py` | `sym`（libJiritsu 的 .dynsym 定义符号+大小，权威函数边界）/ `adj`（adjstctl.elf 的 19 条命令描述符表）/ `areas`（34 条调参文件 id→路径表） |

用法：`python3 tools/jdis.py <so> <start> [end]`。
坑：该 ELF 的 `.dynsym` 用非标准字段排布（`nm,val,sz,[info,other,shndx]`）；`.rel.plt` 的 addend 用 ROT 编码（`0xe28f0000` 形式）；
PLT 里混有 `bx pc`+2 word 的 Thumb→ARM veneer（`jdis.py` 已处理）。**函数地址以 `.dynsym` 为准**（下表）。

## 1. 事实：ELF 布局与符号（全部权威）

```
.text   0x3944 size 0x5868      .plt 0x3010 size 0x934
.rodata 0x91b4 size 0x20455     .rel.dyn off 0x2a0c(190 项)  .rel.plt off 0x2704(154 项)
.init_array 0x32000(=0x3959)    .fini_array 0x32004(=0x3979)
.data.rel.ro 0x3200c size 0x110 = 34 条 {u32 id, char* path}   ← §6.1
.got 0x3224c   .data 0x32578   .bss 0x3257c
```
`.dynsym` 里**同时带定义符号（shndx≠0）与 size**，所以函数边界是确定的（下表；符号值含 Thumb 位，代码地址 = 值&~1）：

| 代码地址 | size | 符号 |
|---|---|---|
| 0x39c0 / 0x39da | 0x1a | `sens_sort` / `sens_search`（qsort/bsearch 比较器，§6.4） |
| 0x3a6e…0x3acc | | `DmmMgr::GetLastErrCode/GetUnitHandle/GetUnitType/CheckUnitType/isOK` |
| 0x3ad8 / 0x3b0c / 0x3b3e | | `jiritsu_cppdump_logrech` / `jiritsu_cpp_logrech(const char*)` / `(const char*,u32)` |
| 0x3b78 | 0x6c | `CShellExecute::ExecShellNew(char*)` |
| **0x3be4** | 0x104 | **`jiritsu_init`** |
| 0x3ce8/0x3d38/0x3d7c/0x3e18/0x3e1e/0x3e24 | | `jiritsu_exit` / `_sus` / `_res` / `_inact`(空) / `_act`(空) / `_thread` |
| 0x3e40 / 0x3e4c | | `sys_binary_md5hash` / `sys_file_md5hash` |
| 0x3fe8/0x4030/0x40b8 | | `sys_file_create` / `_create2` / `_create3` |
| 0x40fc / 0x41b4 | | `sys_mount` / `sys_umount` |
| 0x426c / 0x42e0 | | `mode_file_write` / `mode_file_read` |
| 0x434c / 0x439c / 0x43e0 | 0x50/0x44/0x5a | `sys_file_chk_exist` / `sys_file_remove` / `sys_file_remove2` |
| 0x4480 / 0x44c8 | | `sys_dir_create` / `sys_dir_create2`（建多级父目录） |
| 0x4528 / **0x45e0** / 0x4670 / 0x4684 | | `sys_file_copy` / **`sys_tar_process`** / `sys_tar_compress` / `sys_tar_extract` |
| 0x470c / 0x4734 / 0x5e74 | | `sys_media_status` / `sys_media_power` / `sys_media_mount` |
| **0x4754 / 0x48f8 / 0x4b60 / 0x4da8 / 0x4dd2** | 0x1a4/0x268/0x248/0x2a/0xc | `cmd_mode` / `cmd_format` / `cmd_start` / `cmd_debug` / `cmd_test_ui_view` |
| 0x4dde/0x4df8/0x4e14/0x4e5c/0x4e94 | | `packet_set_error` / `_process_end` / `_res_raw_data` / `_req_raw_data` / `_fin_del_data` |
| 0x4eb0 / 0x5028 / 0x519c | 0x178/0x174/0x10c | `search_dir` / `adj_cmd_get_version` / `cmd_factory` |
| **0x52a8** | 0xcc | **`adj_cmd_set_file_path`**（cmd 15） |
| 0x5374 / 0x53c4 / 0x53f8 / 0x5948 | | `ramdisk_mount` / `ramdisk_umount` / `get_jiritsu_area_filename` / `get_access_filename` |
| 0x5468 / 0x56c0 / 0x58f8 | 0x258/0x238/0x50 | `adj_cmd_get_file`(cmd 8) / `adj_cmd_set_file`(cmd 7) / `cmd_file_delete`(cmd 9) |
| **0x5b00 / 0x5fe8 / 0x5f18** | 0x374/0x274/0xd0 | **`adj_cmd_set_file2`(16) / `adj_cmd_get_file2`(17) / `cmd_file_delete2`(18)** |
| 0x625c / 0x641c / 0x6c54 | 0x1c0/0xb4/0x2c0 | `adj_cmd_compare_media`(12) / `adj_cmd_get_file_list`(10) / `adj_cmd_get_file_hash`(11) |
| 0x64d0 / 0x6574 / **0x67ec** | 0xa4/0x278/**0x334** | `cmd_mount`(2) / `sens_list_update` / **`adj_cmd_set_firm`(6)** |
| **0x6b20 / 0x6f14** | 0x10c/0x188 | **`cmd_high_capacity_send_file` / `cmd_high_capacity_get_file`**（包装层） |
| 0x7278…0x7c30 | | `CImJiritsu` ctor/sus/res/inact/act/**req**/exit/**init**(0x7394)/**release**(0x7454)/**jit_thread**(0x74b1,size 0x6a0)/run/stop |
| 0x7d00/0x7e68/0x7e78 | | `JiritsuBlog::write` / `::instance` / `jiritsu_logrec` |
| 0x7e9c…0x86c3 | | `DmmMgr` 全套：`sync_alloc_dmm_buffer`、`PhysToLogi`、`dmm_access_mem/dmm_access_dmm`、`dmm_dmm2file/dmm_file2dmm`、**`dmm_dmm2dmm_crypto`**、`dmm_mem2dmm/dmm_dmm2mem`、`dmm_alloc/dmm_free/sync_free_dmm_buffer` |
| 0x86f0…0x87d9 | | `COsalCont::IsOK/Send/Release/CreatePacket/SendPacket`（消息通道对象） |
| 0x87e0 / 0x8a70 / 0x8c38 | | `DetectMedia` / `MountMedia` / `MountMediaErrorString` |
| 0x8ce0…0x9104 | | `UI_GetStatus/UI_Init/UI_SetBackColor/UI_SetString/UI_PrintString/UI_TestExecution/UI_TestFinish`（机内小 UI，`cmd_test_ui_view` 与进度显示用） |
| 0x9104 / 0x9194 | | `libCommuTalk` / `libCommuMD5`（与通信/SCSI 侧共用的库内函数） |

未命名 `.bss` 变量（从用法反推）：`0x32580 g_pImJInst`(CImJiritsu 单例，`jiritsu_init` new 出来)、
`0x32584 g_pDmmMgr`(DmmMgr 实例/NULL，由包装层 `msg[0]==1` 创建、`0x10` 释放)、
`0x32590 g_customPath`(SET_FILE_PATH 存的路径 `char*`，malloc)、`0x32594` 1KB 清零缓冲。
具名全局：`g_cbHandle@0x3258c`、`g_raw_res_size@0x32588`、`g_nPrintStatus@0x32995`。
代码访问这些全局走 **GOT 槽（槽里存的是变量地址）**：`GOT+0x310=&sens_sort`、`+0x314=&jiritsu_thread`、
`+0x318=&g_cbHandle`、`+0x31c=&sens_search`（所以 `jiritsu_init` 传给 `osal_reg_sync_msg_queue_cb` 的第 2 参 = **&g_cbHandle**）。
（重现：`python3 tools/adjtbl.py sym <libJiritsu.so>`）

---

## 2. 【Q1】命令号 → 处理函数：**不是 bsearch；是「osal 同步消息回调 → TBB 跳转表 →（高容量命令再一层 TBB）」**

### 2.1 注册（`jiritsu_init @0x3be4`）
```
0x3c06  ldr r0,[pc,#0xa4]        ; r0 = 0x16f0480           ; 服务/消息 id 常量
0x3c08  ldr r1,[GOT+0x318]                                  ; = &g_cbHandle（GOT 槽存全局地址）
0x3c0a  add r2,pc ==> 0x709d                                ; 回调 = 0x709c(+1)
0x3c0e  blx osal_reg_sync_msg_queue_cb
0x3c30  bl 0x39f4            ; upm_get_boot_factor(osal_valloc_msg_wait/snd_sync_msg, 取回 0x28B)
0x3c42  sys_file_chk('/tmp/jmode') → 日志 'have jmode'/'not jmode'
0x3c68  if (g_pImJInst==NULL) new CImJiritsu(0x58B) → CImJiritsu::init()
```
`CImJiritsu::init @0x7394`：
```
osal_dynamic_id(0x16f, 0x2a) → qid
osal_create_waitable_thread(entry = GOT+0x314 = jiritsu_thread, arg = this+8, name 'jiritsu')
CImJiritsu::req(qid, 1, '/tmp/jiritsu/tmmc.jit'(0x99de), 'MAIN()'(0x28eca), '/tmp/jiritsu/libJit.so'(0x9a0a))
日志 'IMJ_REQ_LOAD issued' / 'IMJ_REQ_LOAD failed'
```
⇒ **整条命令通道 = osal 同步消息队列回调**（一代/二代同一套 osal）；同时 jiritsu 引擎线程在此创建。

### 2.2 一级分发器 @0x709c
```
0x70ae  movs r7,#4 ; strh [msg+0xc]                     ; 写死子类型 4
0x70b2  tbb [pc, r0, lsr #12]                           ; ★跳转表 @0x70b2（tbl.py 解出）
0x70b6  ldrh r0,[msg+0x1a] ; subs r0,#1 ; cmp r0,#0x13 ; blo → 合法命令 1..19
```
**命令号 = `msg[0x1a]`（u16 LE）**；每例先 `jiritsu_cpp_logrech("JIRITSU_XXX")` 再经 PLT 调用处理函数。
`jiritsu_act @0x3e1e`（6 字节空壳）不在此路径；另一处 `ldrh [r0,#0x1a]` 与 0x2b0 相减出现在 `adj_cmd_*` 里（属性/AdjustControl 通道），不参与本表【证据：0x3e1e 邻近；未展开】。

一级全表（`cmd` 编号 = 二代工具白名单同一体系）：

| cmd | 名字串@rodata | 处理函数（地址见 §1） |
|---|---|---|
| 1 | JIRITSU_MODE 0xa0d1 | `cmd_mode`（0x70d6） |
| 2 | JIRITSU_MOUNT 0xa0de | `cmd_mount`（0x70e8） |
| 3 | JIRITSU_FORMAT 0xa0ec | `cmd_format`（0x70fa） |
| 4 | JIRITSU_START 0xa0fb | `cmd_start`（0x710c；读 `/tmp/jmode`→`mode_file_read`，要求 Manual；日志 `cmd_start: DIR_MOUNT_FAIL/DIR_NOTHING/JMODE_OPEN_FAIL/SCR_CREATE_FAIL/SCR_LOAD_FAIL/SO_OPEN_FAIL/SYM_LOAD_FAIL/Thred create fail`） |
| 5 | JIRITSU_DEBUG 0xa109 | `cmd_debug`（0x711e） |
| 6 | JIRITSU_FIRMUP 0xa117 | → `cmd_high_capacity_send_file`（0x7138，二级表 idx0）→ **`adj_cmd_set_firm`** |
| 7 | JIRITSU_SET_FILE 0xa126 | 同上（idx1）`adj_cmd_set_file` |
| 8 | JIRITSU_GET_FILE 0xa137 | → `cmd_high_capacity_get_file`（0x7164，idx0）`adj_cmd_get_file` |
| 9 | **JIRISTU**_FILE_DELETE 0xa148 | `cmd_file_delete`（0x7152，直调） |
| 10 | JIRISTU_GET_FILELIST 0xa15c | → get_file 包装（表 idx2）`adj_cmd_get_file_list` |
| 11 | JIRISTU_GET_FILE_HASH 0xa171 | → get_file 包装（idx3）`adj_cmd_get_file_hash` |
| 12 | JIRITSU_COMPARE_MEDIA 0xa187 | → send_file 包装（idx6）`adj_cmd_compare_media` |
| 13 | JIRISTU_GET_VERSION 0xa19d | → get_file 包装（idx5）`adj_cmd_get_version` |
| 14 | JIRITSU_FACTORY 0xa1b1 | `cmd_factory`（0x7190，内部 `ldrh [msg+0x1c]` 再选子功能） |
| **15** | **JIRITSU_SET_FILE_PATH 0xa1c1** | → **send_file 包装**（`b 0x7132`，二级表 idx9）`adj_cmd_set_file_path` |
| **16** | **JIRITSU_SET_FILE2 0xa1d7** | → send_file 包装（`b 0x7132`，二级表 idx10）`adj_cmd_set_file2` |
| **17** | **JIRITSU_GET_FILE2 0xa1e9** | → get_file 包装（`b 0x715e`，二级表 idx9）`adj_cmd_get_file2` |
| **18** | **JIRISTU_FILE_DELETE2 0xa1fb** | **`cmd_file_delete2`（0x71ba，直调）** |
| 19 | JIRITSU_TEST_UI_VIEW 0xa210 | `cmd_test_ui_view`（0x71cc，`UI_PrintString`） |

> ★ **跳代关键指纹**：名字串表里有拼写错误 **`JIRISTU_FILE_DELETE / JIRISTU_GET_FILELIST / JIRISTU_GET_FILE_HASH / JIRISTU_GET_VERSION / JIRISTU_FILE_DELETE2`**（少一个 T）。如果 A7C II 的 `adjstctl.elf`/libJiritsu 里也有同样的 `JIRISTU_` 错拼，就能确认两代同一条代码线（`grep -a JIRISTU_`）。

> **Q1 答案：A7C II 十进制 15/16/17/18 = 0x0f/0x10/0x11/0x12，在一级 TBB 里都有（case15→0x70d0、16→0x7120、17→0x712a、18→0x7134），语义与 `notes/a7c2-tools.md` §1.5 的推定一致：15=SET_FILE_PATH、16=SET_FILE2、17=GET_FILE2、18=FILE_DELETE2。原推定升级为机器码级确认。**
> 注意 16/17 在二级表里要再跳一次：一级只是选包装层，二级表里 cmd 16 → case idx10（`subs #6`）、cmd 17 → idx9（`subs #8`）。

### 2.3 二级分发（包装层内，同一个 `msg[0x1a]` 再跳）
`cmd_high_capacity_send_file @0x6b20`
```
msg[0]==1 → new DmmMgr(0x98) 存 g_pDmmMgr(0x32584)，返回 0
msg[0]==4 → 进入分发；否则 packet_set_error(msg,0x80)
0x6b6e ldrh r3,[msg+0x1a]; subs #6; cmp #0xa; bhi default        ; 合法 6..16
   6→adj_cmd_set_firm(0x6b8c)   7→adj_cmd_set_file(0x6b98)   12→adj_cmd_compare_media(0x6b9e)
   15→adj_cmd_set_file_path(0x6baa)   16→adj_cmd_set_file2(0x6bb6)
   8,9,10,11,13,14 → 仅走清理（0x6bc4）返 0；不合法 → packet_set_error(msg,0x80)
```
`cmd_high_capacity_get_file @0x6f14`
```
msg[0]==1 → 建 DmmMgr；msg[0]==0x10 → 释放 DmmMgr 并 return 0x12；msg[0]==4 → 分发
0x6f6c tbb → ldrh [msg+0x1a]; subs #8; cmp #9; bhi default        ; 合法 8..0x11
   8→adj_cmd_get_file   0xa→adj_cmd_get_file_list   0xb→adj_cmd_get_file_hash
   0xd→adj_cmd_get_version   0x11→adj_cmd_get_file2   （9,0xc,0xe,0xf,0x10→不处理）
```
### 2.4 返回码 → 协议动作（一级分发器尾部 0x7146-0x718a）
`0`→`packet_set_process_end`；`0x10`→`packet_set_process_req_raw_data(msg,1,[msg+4]-4)`（**请主机上传裸数据**）；
`0x11`→`packet_set_process_res_raw_data(msg,1,0)`（**把数据回给主机**）；`0x12`→`packet_set_fin_del_data(msg,1,[msg+4])`；
其它→`packet_set_error(msg,0x81,code)` 且 `str code,[msg+0x10]`。
**`msg+0x10` = 回包 LE32 状态码**，与各 `adj_cmd_*` 尾部 `str r6,[msg+0x10]` 一致 —— 与二代工具"前 4 字节是 LE32 状态码"完全吻合。

### 2.5 ★旁证：相机自带的“命令描述符表”（`bin/adjstctl.elf` @0x1acc8，19 条，stride 0x48）
每条（stride 0x48，位于 .rodata 0x1acc0 起）= `{u32 qid; u32 chan; char name[64]}`：
```
qid  = 0x016f0480                       chan = ((pfunc<<8 | cmd) << 16) | 0x1001,  pfunc = 0x40
 1 MODE 2 MOUNT 3 FORMAT 4 START 5 DEBUG 6 FIRMUP 7 SET_FILE 8 GET_FILE 9 FILE_DELETE
10 GET_FILELIST 11 GET_FILE_HASH 12 COMPARE_MEDIA 13 GET_VERSION 14 FACTORY
15 SET_FILE_PATH 16 SET_FILE2 17 GET_FILE2 18 FILE_DELETE2  19 TEST_UI_VIEW(chan=0x00131001，pfunc=0)
（第一条 MODE 的 qid 槽读到 0x009302f5，是相邻数据，不影响其余 18 条）
重现：`python3 tools/adjtbl.py adj <adjstctl.elf>`
 1 MODE 2 MOUNT 3 FORMAT 4 START 5 DEBUG 6 FIRMUP 7 SET_FILE 8 GET_FILE 9 FILE_DELETE
10 GET_FILELIST 11 GET_FILE_HASH 12 COMPARE_MEDIA 13 GET_VERSION 14 FACTORY
15 SET_FILE_PATH 16 SET_FILE2 17 GET_FILE2 18 FILE_DELETE2  19 TEST_UI_VIEW(chan=0x00131001，无 0x4000 位)
```
* `qid = 0x016f0480` 与 `jiritsu_init` 里 `osal_reg_sync_msg_queue_cb(0x16f0480, …, 0x709d)` 的常量**完全相同** ⇒ 这张表就是同一通道的发起端描述。
* `chan` 低 16 位 = `0x1001`，高 16 位 = `0x4000|n`（0x4000 = pFunc 0x40 AdjustControl 的体现，19 号没有该位）。
  二代工具发的是 `struct.pack('<HH', 0x1001, cmd)`（cmd = 15/16/17/18）⇒ **编码一致、命令号一致，一代编号 1..19 得到独立确认**（不再靠“字符串等间距”推定）。
* 名字串表在 libJiritsu.so 里有拼写错误 **`JIRISTU_FILE_DELETE / JIRISTU_GET_FILELIST / JIRISTU_GET_FILE_HASH / JIRISTU_GET_VERSION / JIRISTU_FILE_DELETE2`**（少个 T），
  而 adjstctl.elf 里的表拼写正确 ⇒ 拿 `grep -a JIRISTU_` 去 A7C II 固件里比，可以直接判断二代是否同一代码线。

---

## 3. 【Q2】各命令的缓冲/长度字段

已确认的报文（`msg`）公共字段：

| 偏移 | 含义 | 证据 |
|---|---|---|
| +0x00 | u8 通道类型：1=分配 DmmMgr、4=带数据命令、0x10=释放 DmmMgr | 0x6b2c / 0x6f22 |
| +0x04 | u32 包/缓冲总长（`[msg+4]-4` 用于 raw-data 请求长度） | 0x715c |
| +0x0c | u16 = 4（本插件写死） | 0x70ae |
| **+0x10** | **u32 状态码（回包）** | 0x5354 / 0x5df8 / 0x67e6 / 0x7170 |
| **+0x14** | **u32 本命令载荷长度 L（含下面的小头）** | 0x525c / 0x5b1e / 0x6814 / 0x7012 |
| +0x1a | u16 命令号（§2） | 0x70b6 |
| +0x1c… | 命令私有小头（下面逐条） | |

公共约定（重要）：各 `adj_cmd_*` 的 **payload 小头就在 `msg+0x1c`（mode/id/flag 3 字节），数据从 `msg+0x1f`**；
代码里读/写数据用的指针是 `bl 0x3a64`（`this->vtbl[1]()`，DmmMgr **unit 数据缓冲基址**，未导出），
在这两个命令里它的偏移与包内 payload 一致（`set_file_path` 用 `unit+1`、`set_file2` 用 `unit+3`，flag==1 时 `unit+L`）
⇒ **包内 payload 区 = DMM unit 缓冲**（同一块或已被包层复制）【证据：偏移一致；未直接验证同一指针】。
另：`CheckUnitType @0x3a86` 返回的是 DMM **unit type 编号**（不是字节数），`GetUnitHandle @0x3a76 = *(u16*)(this+8)`、`GetUnitType @0x3a7e = *(u32*)(this+0x10)`、`isOK @0x3ac0 = (this+0x18)<=1`。

### 3.1 `adj_cmd_set_file_path`（15）@0x52a8（按符号边界 0x52a8-0x5358 重读，完整）
```
r6 = L = *(u32*)(msg+0x14);  n = L-1
if ((n-1) >= 0x200) → 日志 'Request raw data size error.(max_size:%d)'(r2=0x201) + 状态码 0x10000201
   ⇒ 实际限制 L ≤ 0x201、n ≤ 0x200 = 512 字节（calloc(L,1) 零尾页 ⇒ 串 ≤511 字符）
DmmMgr::dmm_alloc(CheckUnitType(n)) 必须返回 0；失败 → 0x10000015
unit = this->vtbl[1]()  (0x3a64)
if (msg[0x1c] != 0) → 直接完成（只预约 DMM 缓冲、不存路径），状态码 0     ★ mode!=0 的含义
free(g_customPath); buf = calloc(L,1); memcpy(buf, unit+1, n); g_customPath = buf
清洗 @0x5318-0x534a（n 字节）：0x5c('\\') → 0x2f('/')；
   遇 0x0a / 0x0d / 0x2c(',') → free(buf); g_customPath = NULL; 状态码 0x10000201
正常 → 状态码 0；统一 `str r0,[msg+0x10]`
```
* ★ **`..` 完全不拦**（只拦 `\n \r ,`，并把 `\` 转 `/`）。二代工具 `jiritsu(15, b'\0'+path+b'\0')` = mode0 + NUL 结尾路径 ✓（尾 NUL 正好落在 calloc 零尾页）。

### 3.2 `adj_cmd_set_file2`（16）@0x5b00
小头：`msg[0x1c]=mode`、`msg[0x1d]=area id`、`msg[0x1e]=flag(0/1)`；**数据在 `msg+0x1f`，长度 `r6 = L-3`**。
```
mode==1    → 不挂载；把 id 字节改写成 0xff；基目录 '/mnt'（媒体卡）
mode==0    → id==2 → 0x10000201；否则 sys_mount('/dev/nflasha6','/tmp/jiritsu',0)；基目录 '/tmp/jiritsu'
mode==0xff → 完全跳过挂载与路径解析，只做 DMM 缓冲登记（指针写入 DmmMgr+0xc1c/+0x81c/+0x41c + 4*id，见 0x5bb6-0x5c22）【推测：多段/预登记】
path[0x202] = get_access_filename(id, 基目录)      ; ★'.. 见 §6.2
写被拒（0x10000201）：结果 == '/tmp/jiritsu/jit.log' 或 '/tmp/jiritsu/history.txt'
结果 == '/tmp/jiritsu/libJit.so' → 要求 sys_file_chk_exist('/tmp/jbusy') != 0（不存在），否则 0x10000011（'jiritsu running'）
mode==0 → sys_get_dir_size('/tmp/jiritsu',1)，要求 r6 ≤ 0x500000 - 已用，否则 0x1000000f      ★5MiB 配额
sys_dir_create2(path)（自动建父目录；失败 0x1000001c 'directory create error.'）
DmmMgr::dmm_alloc(CheckUnitType(r6*(flag==1?1:2)))；失败 0x10000015
flag==1 → libCommuTalk(buf+3, buf+L, r6)      ; 把 DMM 收到的后半搬到前面
open(path, 0x241, 0600); write(fd, src, r6); fsync; close      ; src = buf+3 或 buf+L
写不满 r6 → 0x10000009
path=='/tmp/jiritsu/libJit.so' → dlopen(path, RTLD_LAZY) 立刻 dlclose；失败 0x10000000   ★ELF 校验
末尾 free(g_customPath)；str 状态码,[msg+0x10]
```
`CheckUnitType @0x3a86` 把尺寸映到 unit type：`<0x500000→0x304`、`<0xf00000→0x3c8`、`<0x3200000→0x288`、`<0x6400000→0x307`、`≥0x6400000→-1(无效)`
⇒ DMM 单次最大 100MiB（4 个档位）；但 **jiritsu 文件写被 5MiB 分区配额卡住**（`cmp r6,#0x500000` / `rsb r0,r0,#0x500000`）。

### 3.3 `adj_cmd_get_file2`（17）@0x5fe8
小头同上（mode/id/flag），第 3 个 C 参数 `r6` = **包内 +0x320 的 u32* 尺寸入/出参**：函数开头 `str 4,[r6]`（先置 4），
每读一段 `*r6 += 实际长度`；`msg[0xc]` 被写 4。
```
mode==1    → sys_media_mount(0x5e74：DetectMedia/sys_media_power，'/dev/ms1'0x9c85 或 '/dev/mmca1'0x9c7a) → 基目录 '/mnt'，
              并把 id 字节强制写成 0xff（所以媒体模式下也是“用自定义路径”）
mode==0    → id = msg[0x1d]；id==0 或 id==2 → 0x10000201；否则 sys_mount('/dev/nflasha6','/tmp/jiritsu') → 基目录 '/tmp/jiritsu'
mode==0xff → 不读文件系统，而是用 DmmMgr 的 per-id 暂存槽（由 set_file2 mode 0xff 登记：[+0x1c+4id]=缓冲 ptr、[+0x81c+4id]=长度）
              → memcpy(unit+4, 缓冲, 长度)，*r6 += 长度（“读回上次 stage 的内容”）
其它 mode  → 0x10000201
然后（mode 0/1）：flag = msg[0x1e] ≤ 1；path(0x202B) = get_access_filename(id, 基目录)；
  __xstat 失败 → 0x10000006（'adj_cmd_get_file: file non-existent'）；OK → dmm_alloc + 读到 unit+4，状态码写 msg+0x10
```
（二代工具 `jiritsu(17,b'\0\xff\0')` = mode0 + id0xff + flag0 ⇒ **先挂 nflasha6，再把 SET_FILE_PATH 存的自定义路径拼到 `/tmp/jiritsu`**。
`/tmp/jiritsu/../../usr/lib/appFw.so` 能读到，是因为 `get_access_filename` 对 `..` 不做任何检查，open 时内核归一化到 `/usr/lib/appFw.so`。）

### 3.4 `cmd_file_delete2`（18）@0x5f18（导出函数，一级经 PLT 直调）
小头 `msg[0x1c]=mode`、`msg[0x1d]=id`；mode==1 → `/mnt` + 内联路径(`msg+0x1f`, 长 `L-3`)；mode==0 → 挂载 nflasha6 + `get_access_filename(id,'/tmp/jiritsu')`；
`sys_file_remove2(path)`（失败 0x1000000b + 'Jiritsu partition mount error.'）；`free(g_customPath)`；状态码写 msg+0x10。
（二代工具 `jiritsu(18,b'\0\xff')` = mode0 + id0xff ✓。）

### 3.5 v1（老命令）对照：`adj_cmd_set_file`(7) @0x56c0 / `adj_cmd_get_file`(8) @0x5468 / `cmd_file_delete`(9) @0x58f8
* set_file：**只按 area id**（`get_jiritsu_area_filename(msg+0x1d)`）；同样拒 jit.log/history.txt；写 libJit.so 需 `/tmp/jbusy` 不存在；
  用 `glob('/tmp/jiritsu/*')` 统计已用并卡 0x500000（`0x1000000f`）；`open(…,0x241,0600)`；写完 dlopen+dlclose。
* get_file：mode `msg[0x1c]`：0 → 挂载 + id 表；1 → `/mnt` + 内联路径 `msg+0x1f`（长度 `L-3`）；2 → 特殊；
  路径缓冲 **0x1000 字节**，`(L-3) > 0x1000 → 0x1000000f`；`flag msg[0x1e] ∈ {0,1}`（1 = 同时 `libCommuTalk`）；
  读长度由第 3 参数（包内 0x320）进出，DMM 缓冲基址 +4；错误 0x10000004/6/8/a/f/15/201。

### 3.6 包装层不是"块大小"，而是通道开关
`msg[0]`=1 建 DmmMgr / =0x10 释放 / =4 才分发；真正的大块搬运靠 §2.4 的 0x10/0x11/0x12 raw-data 返回码 +
`DmmMgr::sync_alloc_dmm_buffer / sync_free_dmm_buffer / dmm_mem2dmm / dmm_dmm2file / dmm_file2dmm`。

---

## 4. 【Q3】`adj_cmd_set_firm @0x67ec`（`JIRITSU_FIRMUP`）

入口：一级 cmd **6** → 包装 `cmd_high_capacity_send_file`（要求 `msg[0]==4`）→ 二级 case **6**。
小头：`msg[0x1c] = mode`（**bit1 = 先做备份**，bit0 = 数据在缓冲第二半）；数据长度 `r6 = L-1`（`L=*(msg+0x14)`）。

1. `L > 0x500000` → **0x1000000f** + 日志 `firm size over` ⇒ 载荷 ≤ 5MiB。
2. `sys_file_chk_exist('/tmp/jbusy')==0`（存在）→ **0x10000011** + `jiritsu running` ⇒ **必须无 jbusy 标志**。
3. `sys_mount('/dev/nflasha6','/tmp/jiritsu',0)`；失败 **0x10000004** + `Jiritsu partition mount error.`。
4. `g_pImJInst==NULL` → **0x10000018** + `adj_cmd_set_firm: g_pImJInst is NULL`。
5. `mode&2`：`sys_tar_compress('/tmp/jiritsu','/tmp/jiritsu.bak.tar')`（= `/bin/tar cf …bak.tar ./ -C /tmp/jiritsu`）
   → `sys_file_md5hash(bak.tar, 栈缓冲)` → `sys_file_create3(缓冲,'/tmp/jiritsu.bak.hash',0x10)`（16B 原文 MD5）。
   失败日志 `Recovery file compress error.`(0x9e22)/`Recovery file hash create error.`(0x9e40)/`Recovery file hash file save error.`(0x9e77)。★**备份整个 jiritsu 区**
6. `DmmMgr::dmm_alloc(CheckUnitType(L*((mode&1)?2:1)))`；失败 0x10000015。
7. `mode&1` → `libCommuTalk(buf+1, buf+L, L-1)`（把 DMM 收到的后半搬到前面）。
8. `ramdisk_mount('/tmp/jiritsu/ramdsk'(0x9ee1),'size=5M')` → `open('/tmp/jiritsu/ramdsk/jiritsu.dat'(0x9efd),0x201,0600)`
   → `write(r6=L-1)` → `ramdisk_umount`；open 失败 0x10000008。
9. **`sys_tar_extract('/tmp/jiritsu/ramdsk/jiritsu.dat','/tmp/jiritsu')`**；失败 **0x10000010**。
   ⇒ **载荷必须是一个 tar 包，解到 nflasha6 挂载点，即整区替换**。
10. `sys_binary_md5hash(载荷缓冲,…)` → `sys_file_create3(…,'/tmp/jiritsu/jiritsu.hash'(0x9eaf),0x10)` = 载荷 tar 的 16B 原文 MD5。
11. `sys_file_remove2('/tmp/jiritsu/jcount'(0x99e2))`；失败 0x10000009 + `Jiritsu count file delete error.`。
12. 若 `/tmp/jiritsu/DIAC.csv` 存在 → `sens_list_update()`；失败 0x10000009 + `DIAC list update error.`。
13. 若做过备份 → `remove(bak.tar)` + `remove(bak.hash)`；失败 0x1000000b。
14. `ramdisk_umount`；状态码写 `msg+0x10`。

**外部调用清单**：`sys_mount/sys_umount`、`ramdisk_mount/ramdisk_umount`、`sys_tar_compress/sys_tar_extract`、
`sys_file_md5hash/sys_binary_md5hash`(→`libCommuMD5`)、`sys_file_create3`、`sys_file_chk_exist`、`sys_file_remove2`、`remove`、
`open/read/write/lseek/close`、`DmmMgr::dmm_alloc/GetLastErrCode`、`libCommuTalk`、`mode_file_read/mode_file_write`、
`glob/globfree`、`qsort/bsearch`、`sys_get_dir_size`、`dlopen/dlclose`（在 set_file2 里）、`UI_PrintString`。

**是否走 `/bin/sh` / 自拼 `/bin/tar`？是。** `sys_tar_process @0x45e0` 拼
`'/bin/tar xpf %s ./ -C %s'`(0x94b3) 或 `'/bin/tar cf %s ./ -C %s'`(0x94cf)，交给
`CShellExecute::ExecShellNew @0x3b78` → `argv = {"/bin/sh"(0x91b4), "-c"(0x91bc), cmd, NULL}` → `stm_system`(PLT 0x36d4) 并取退出码
（非 0 → 0x10000003/0x10000004，stm_system<0 → 0x10000000）。**不是 `system()`，是 uITron 风格的 `stm_system` + `/bin/sh -c`。**

**目的一致、实际目标（来自分区表，一手证据）**：`firmware.tar_unpacked/0300_partconf/partinf.conf` 里官方分区定义就是
```
# /dev/nflasha6   16MB (System Group  **Jiritsu**  /dev/nflasha6)   0x09400000,0x01000000
# /dev/nflasha15  300MB (User Group  usr)   0x2D800000,0x12C00000   ← 本 lib 所在的 /usr
```
⇒ 一代确实有**专用 16MB “Jiritsu” 分区**（代码里的 0x500000 = 5MiB 是**软件配额**，不是分区大小）。

**灌自定义固件可行性（判断 + 强度）**
* 强（机器码级）：cmd 6 用主机 tar **覆盖整个 `/dev/nflasha6`（jiritsu 区）**，并可用 `mode&2` 自动备份。该区内容就是
  `libJit.so`、`tmmc.jit`、`Cam_AdjustGuide_Files/*`、`DIAC.csv`、`jit.log`、`history.txt`、`jcount`。
* 中：cmd 16 允许把任意名字（含 `..`）写进已挂载的 jiritsu 区，并对 `libJit.so` 做 dlopen 校验 —— 二代工具实际用的就是它。
* 弱/不可套用：`set_firm` **不触碰** `nflasha15`（`/usr/lib/appFw.so`、根 fs）或 `nflasha3/5/7`；整个函数里唯一块设备串就是 `/dev/nflasha6`。
* ⇒ 结论：**一代"灌自定义代码" = 换 `libJit.so` + `tmmc.jit`（或整个 tar）**，与二代做法同构、风险最低；
  要改 appFw.so/cpapp 仍需 pwrite 补丁路线（见 `notes/a7c2-tools.md`）。

## 5. 【Q4】`libJit.so` 加载机制、恢复模式与回滚

`libJit.so`(0x9a0a) 的全部引用：`get_jiritsu_area_filename`/`get_access_filename` 里 **area id == 2 → `/tmp/jiritsu/libJit.so`**；
`adj_cmd_set_file @0x5864`、`adj_cmd_set_file2 @0x5da0` 的 **dlopen(RTLD_LAZY)+dlclose 校验**（就是二代笔记里"SET_FILE2 的 native libJit.so dlopen/dlclose path"的一代对应实现，**已证实**）；
`CImJiritsu::init @0x7402` 的请求参数；`jit_thread @0x74b0` 的实际加载。

**`CImJiritsu::jit_thread @0x74b0`（= 导出的 `jiritsu_thread` 的实体）**
```
0x74fa  'jit_thread: begin. qid=0x%08x' ；osal_get_msg / packet_get_message_content
0x7564  包首字节 != 'd' → 0x75b0 'not dir'/'mount dir'
0x75b0  sys_file_chk_exist('/tmp/jiritsu/jinit'(0x28fc0))：
          不存在 → 正常；  **存在 → 上次未干净退出 → 打印 'libJit.so crashed.'(0x28fd3)** + UI_PrintString
0x75d0  sys_file_chk_exist('/tmp/jiritsu.bak.tar')：
          存在 → sb = chk('/tmp/jiritsu.bak.hash')
                  两者都在 → 0x75ec UI_PrintString('Recovery mode execute.'0x28fe6)
                             → 0x7604 sys_tar_extract('/tmp/jiritsu.bak.tar' → '/tmp/jiritsu')   ★回滚
                               失败 → 'Recovery file extract error. '0x28ffd / 'Recovery error.(extract failed)'0x2901b
                             之后 sys_file_remove(bak.tar)+remove(bak.hash)，失败 → 'Recovery file remove error.'0x9fec
                                  + UI 'Recovery error.(backup delete failed)'0x2903b
                  缺 bak.hash → 直接删掉 bak.tar/bak.hash
          不存在 → 0x7654 继续正常加载
0x7666  ramdisk_mount('/tmp/jiritsu/ramdsk_libJit'(0x28f3a), 'size=1M')     失败 → 'RAM_DISK mount error.'0x9f89
0x7684  sys_file_copy( **消息对象里的路径 [r8+4]**, '/tmp/jiritsu/ramdsk_libJit/libJit.so'(0x29069) )
        失败 → 'libJit.so copy error.'
0x769c  dlopen('/tmp/jiritsu/ramdsk_libJit/libJit.so', RTLD_LAZY) → this+0x10 = handle ；失败 → 'dlopen err pErr'
0x76c8  dlsym(h,'CreateScriptI'(0x290b4)) → 0x76ec blx → this+0x14 = 返回的脚本对象；为 0 → 'create fail'
0x7706  dlsym(h,'LoadScriptI'(0x290d6)) ；失败 'sym load err pErr'
0x7a0a  dlsym(h,'RunScriptI'(0x291ef))   （0x775e/0x7772 处还会读 '/tmp/jiritsu/libJit.so' 与 '/tmp/jiritsu/jiritsu.hash'）
```
`CImJiritsu::release @0x7454`：`dlsym(h,'DestroyScriptI')` → 调用（参数 this+0x14）→ `dlclose(h)` → `ramdisk_umount('/tmp/jiritsu/ramdsk_libJit')`。

**结论（Q4）：是 `dlopen`/`dlsym`，不是 `system()`。**
* `libJit.so` 是一个**脚本引擎 DLL**，一代 jiritsu 需要的 4 个导出 C 符号：`CreateScriptI`、`LoadScriptI`、`RunScriptI`、`DestroyScriptI`。
* 实际 dlopen 的是**从分区文件复制到 1MiB ramdisk (`/tmp/jiritsu/ramdsk_libJit`) 的副本**（复制源路径来自消息内容 `[r8+4]`，通常即 `/tmp/jiritsu/libJit.so`）——
  【推测】因为 nflash 挂载点不可执行/不可 dlopen，故先搬到 ramdisk。
* 引擎装载请求：`CImJiritsu::req(qid, 1, '/tmp/jiritsu/tmmc.jit', 'MAIN()', '/tmp/jiritsu/libJit.so')`（日志 `IMJ_REQ_LOAD issued`）。
* **恢复/回滚**：`/tmp/jiritsu/jinit`（运行中标记，残留 = 崩溃）+ `/tmp/jiritsu.bak.tar`/`.hash`（由 set_firm `mode&2` 生成）；
  `jit_thread` 检测到崩溃残留且有备份 → **`tar xpf` 回滚整个 jiritsu 区** → 删除备份 → 继续加载。备份与回滚是一对（`sys_tar_process` 模式 1/0）。

## 6. 【Q5】一代有同样的 `Cam_AdjustGuide_Files` 机制吗？有。

### 6.1 id→路径表（`.data.rel.ro @0x3200c`，34 条 `{u32 id, char*}`，文件偏移 0x2a00c；串本身已是绝对路径）
```
Req_Files（id 0x10-0x23，20 条，前缀 /tmp/jiritsu/Cam_AdjustGuide_Files/Req_Files/）：
 0x10 REQ_CC_AWB32_CHK                 0x11 REQ_CC_AWB58_CHK               0x12 REQ_CC_AWB_ADJ_ND
 0x13 REQ_CC_AWB_CALC_CORR             0x14 REQ_CC_DEVICE_SET_MANUAL_OFF
 0x15 REQ_CC_DEVICE_SET_MANUAL_ON_LM_AWB     0x16 REQ_CC_DEVICE_SET_MANUAL_ON_LM_AWB_KIJUN
 0x17 REQ_CC_DEVICE_SET_MANUAL_ON_ND         0x18 REQ_CC_DEVICE_SET_MANUAL_ON_STRB
 0x19 REQ_CC_GAWAKU_CHK_9CHART         0x1a REQ_CC_HUEGAIN32_CALC_CORR     0x1b REQ_CC_LMAT_ADJ
 0x1c REQ_CC_LMAT_CALC_COLOR_CORR      0x1d REQ_CC_LMAT_GET_COLOR_DATA     0x1e REQ_CC_LMAT_GET_SHD_DATA
 0x1f REQ_CC_STRB                      0x20 REQ_CC_LMAT_CALC_MINIRAW_COLOR_CORR
 0x21 REQ_CC_AWB32_CALC_CORR           0x22 REQ_CC_AWB58_CALC_CORR         0x23 REQ_CC_DEVICE_SET_MANUAL_ON_EQUIP
Res_Files（id 0x30-0x3d，14 条，前缀 …/Res_Files/）：
 0x30 RES_CC_AWB_GET_CORR       0x31 RES_CC_AWB_GET_PARAM      0x32 RES_CC_AWB_GET_PARAM_ND
 0x33 RES_CC_AWB32_CHK_GET_PARAM      0x34 RES_CC_AWB58_CHK_GET_PARAM      0x35 RES_CC_HUEGAIN32_GET_CORR
 0x36 RES_CC_HUEGAIN32_GET_PARAM      0x37 RES_CC_LMAT_GET_COLOR_CORR      0x38 RES_CC_LMAT_GET_PARAM
 0x39 RES_CC_LMAT_GET_PARAM_COLOR     0x3a RES_CC_LMAT_GET_PARAM_SHD
 0x3b RES_CC_LMAT_GET_MINIRAW_COLOR_CORR   0x3c RES_CC_AWB32_GET_CORR      0x3d RES_CC_AWB58_GET_CORR
```
另有 id 特例（`get_jiritsu_area_filename @0x53f8` 的 TBB @0x5404，索引 0..4）：
**0=`/tmp/jiritsu/tmmc.jit`、1=`/tmp/jiritsu/DIAC.csv`、2=`/tmp/jiritsu/libJit.so`、3=`/tmp/jiritsu/jit.log`、4=`/tmp/jiritsu/history.txt`**；
id≥5 → **线性扫 34 条表**（`cmp r3,#0x22` 正好 34 项），未命中 → 空串(0x997d)。
⇒ 写/读 area id 语义：id 0=jit 入口脚本、1=调参校准表 CSV、2=执行体 libJit.so、3/4=日志（**正是 set_file2 拒写的两个**）、≥5=调参步骤文件。
命名语义【推定，证据中】：`REQ_*` = 主机请求相机执行的**调参步骤（脚本）**，`RES_*` = 该步骤的**回参**（AWB / LMAT / HUEGAIN / DEVICE_SET_MANUAL 等产线调参流程），不是色彩查找表数据本身。
与二代工具走的 Backup 属性 key `0x02a400xx`（`0x603/0x40/0x41`）是**两条不同通道**。

### 6.2 三种路径解析方式
1. `get_jiritsu_area_filename @0x53f8`：id<0x10 → 上面 TBB 特例；id≥0x10 → **线性扫 34 条表**命中直接返回表串。
2. `get_access_filename @0x5948`：kind==0xff → 取全局 `g_customPath`；kind==2 → 固定 `/tmp/jiritsu/libJit.so`；否则走 area id 表。
   然后：若自定义串以 dir 开头 → **原样使用**；否则 `dir[0]=='/' ? snprintf('%s%s',dir,path) : snprintf('%s/%s',dir,path)`。
   ★ **没有任何 `..` / 前缀越界检查** ⇒ `/tmp/jiritsu/../../usr/lib/appFw.so` 直接逃逸（内核 open 时归一化）。
3. `mode` 字节（各命令 `msg[0x1c]`）决定基目录：0→`/tmp/jiritsu`(挂 nflasha6)、1→`/mnt`(SD/MS)、2→拒/特例、0xff→(get_file2)挂载后按 id。

### 6.3 读写通道与限制（"能否任意读写"）
* **读**：cmd 8(v1) / 17(v2)。mode 0 会先挂 nflasha6，再用 id（id=0xff 即用 SET_FILE_PATH 存的路径）解析；**`..` 可逃逸到 `/` 以下**（appFw.so 等）。v1 路径缓冲 0x1000B，v2 0x202B。mode 1 则切到媒体卡 `/mnt`。
* **写**：cmd 7(v1) / 16(v2)。只拒 `jit.log`、`history.txt`；写 `libJit.so` 需 `/tmp/jbusy` 不存在；配额 = 目录已用 + 新文件 ≤ `0x500000`（5MiB，仅 mode==0 统计）；`sys_dir_create2` 自动建父目录；`\`→`/`，禁 `\n \r ,`；路径 ≤512（经 cmd 15）。
* 删：cmd 9 / 18；列目录：cmd 10(`adj_cmd_get_file_list @0x641c`)；哈希：cmd 11(`adj_cmd_get_file_hash @0x6c54`)；媒体：mode=1 + `DetectMedia/MountMedia`(`/dev/ms1`、`/dev/mmca1`)。
* 【判断，证据强】**读 = 基本任意**（受挂载/权限限制）；**写 = 名字任意但落点受挂载点与 5MiB 配额限制**，`..` 写越界到别的 fs 未被拒绝（只有配额检查覆盖 `/tmp/jiritsu`）。

### 6.4 `sens_sort/sens_search`（`.rel.dyn` 里 4 个可疑符号的答案）
`sens_list_update @0x6574`（set_firm 第 12 步调用）：读 `/tmp/jiritsu/DIAC.csv`(0x99f4)，按 `#` 分隔 + `strtoul(_,_,16)` 解析，
建 **1715 项 × 8B**（`movw r1,#0x6b3; movs r2,#8`）的 (id,value) 表，
`qsort(base,1715,8, GOT+0x310 = sens_sort)` @0x6632、`bsearch(key,…,1715,8, GOT+0x31c = sens_search)` @0x66b4，
未命中/命中分别 `snprintf(line,0x100,'%s,%08lX\n')`(0x9dc5) / `'%s,0\n'`(0x9dbf) 后 **写回 DIAC.csv**（open/write/fsync/close）。
⇒ DIAC.csv = 1715 行 `<调参项名>,<8位hex>` 的调参校准表；`sens_*` 只是它的排序/二分比较器，**不是命令分发**。
`jiritsu_thread` 只是 `CImJiritsu::jit_thread` 的导出包装（GOT 槽 0x32560）。

## 7. 状态码表（.text 立即数 + 日志串对齐；可补进二代工具的状态字典）
`0`=OK；`0x10000000` dlopen/tar/shell 失败；`0x10000003`/`0x10000004` shell 非零退出码 / DIR_MOUNT_FAIL；
`0x10000005` ramdisk 挂载失败；`0x10000006` 文件不存在；`0x10000007` JMODE_OPEN_FAIL；`0x10000008` open 失败；
`0x10000009` write/删除/更新失败；`0x1000000a` read 失败；`0x1000000b` remove/备份删除失败；
`0x1000000f` 尺寸超限；`0x10000011` 忙（/tmp/jbusy 存在）；`0x10000012` SCR_CREATE_FAIL；
`0x10000015` DmmMgr 分配失败；`0x10000016`(0x7676 分支 0xb/0x10/0x12/0x14/0x15/0x17 是 UI 进度码，不是状态码)；
`0x10000018` g_pImJInst NULL；`0x10000019` 线程创建失败；`0x1000001c` 目录创建失败；
`0x10000101/102/104/105/106` SYM_LOAD / SO_OPEN / SCR_LOAD 类；`0x10000201` 参数/路径非法。

## 8. 搬到一代的结论（判断汇总）
1. **协议/命令层可搬（证据强）**：一级 TBB@0x70b2 确认 1..19；15/16/17/18 语义与二代工具一致；回包状态码在 `msg+0x10` LE32。
2. **文件通道可搬（证据强）**：`get_access_filename` 的"自定义路径 + 无 `..` 检查"在一代同样存在；GET_FILE2(mode0,id0xff) 先把 nflasha6 挂到 `/tmp/jiritsu`，再用 `..` 逃逸路径就能读 `/` 下任意文件。
3. **执行载体可搬（证据强）**：SET_FILE2 写 `/tmp/jiritsu/libJit.so`（dlopen 校验）→ `jit_thread` 复制进 ramdisk → `dlopen` → `CreateScriptI/LoadScriptI/RunScriptI`。
   **注意：一代是 ARM32/Thumb 用户态，worker(`libJit.so`) 必须重编译为 armv7，并导出上述 4 个符号。**
4. **不能照搬**：`set_firm` 只覆盖 `/dev/nflasha6`(jiritsu 区)；不改 `/usr/lib/appFw.so`、`/cp/cpapp-b.bin`；一代无 `/cp` 挂载点（见 `FIRMWARE_MOD.md`）。
5. **实操风险点**：写 libJit 前必须无 `/tmp/jbusy`；`jit.log`/`history.txt` 不可写；jiritsu 区总量 ≤5MiB；`/tmp/jiritsu/jinit` 残留会触发 Recovery（会吃掉 `bak.tar`）——自动化流程要先清 `jinit`、并避免误留 `bak.tar`。

## 9. 未验证 / 需现场确认（诚实标注）
* `msg` 头 +0x00/+0x04/+0x08/+0x0c 的完整语义（只由用法反推）【推定】。
* `jit_thread` 0x7720-0x7ab4 的完整脚本装载序列（`LoadScriptI`/`RunScriptI` 的实参布局未逐条确认）。
* `set_file2 mode==0xff` 的"DMM 槽位登记"（DmmMgr +0xc1c/+0x81c/+0x41c + 4*id）用途【推测：多段/多文件预登记】。
* open flags `0x241`/`0x201` 的 O_* 位定义（按 O_CREAT=0x200、O_TRUNC=0x40 解释）【推定】。
* `cmd_factory @0x519c` 的子功能号表（`ldrh [msg+0x1c]`）、`cmd_mode/cmd_format/cmd_mount` 细节未展开。
* `unit = this->vtbl[1]()`（0x3a64）与 `msg+0x1c` 是否同一指针（包层是否复制 payload）未直接验证；建议现场用一条已知路径回环确认头长（3 字节 vs 1 字节）。

## 暂停点（2025-10-23，真机 L1 第一次连）
状态：**相机可见但一个字节都没读到**（`work/l1/` 空）。用户要装驱动 + 重启 Mac，任务暂停。

已确认（本机实测）：
- 相机以 **`054C:0D29`** 枚举（`ioreg` 里 `idProduct=3369 idVendor=1356`、`kUSBProductString="ILCE-7C"`、`bDeviceClass=0`），USB 模式=Mass Storage，**用户已在 Finder 弹出相机卷**；`diskutil list` 不再出现相机卷。
- `tools/jiritsu_send.py scan` **正常**（已把 0D29/0D28 加进 `MSC_PIDS` 首位并标好模式含义）。
- 失败点（`work/l1_step_mount.log`）：`connect()` → `SonySenserAuthDevice(GenericUsbDriver(UsbBackend(msc)))`（`tools/jiritsu_send.py:341`）
  → `refs/Sony-PMCA-RE/pmca/usb/__init__.py:29 reset()` → `pmca/usb/driver/generic/libusb.py:70`
  `self.dev.is_kernel_driver_active(0)` 为真 → `detach_kernel_driver(0)` → **`usb.core.USBError: [Errno 13] Access denied (insufficient permissions)`**。
  ⇒ **卡在 pmca 的"分离内核驱动"这一步，不是相机不响应、也不是找不到设备。**（pyusb 1.3.1；macOS 上 libusb 的 detach_kernel_driver 基本不可用/EPERM）

重启后按顺序试（不用改相机、不用重装 pyusb）：
0. **补丁已预先改好**（已验证可导入）：`refs/Sony-PMCA-RE/pmca/usb/driver/generic/libusb.py::UsbBackend.reset()`
   改为 `except (NotImplementedError, usb.core.USBError): pass` ⇒ macOS 上跳过 detach。不需要重启 Python 环境。
1. 若仍报 **busy/claim 失败**：先 `diskutil unmountDisk <相机盘>`（别用 Finder），或菜单把 USB 模式切一次再切回 Mass Storage；再试。
3. 通了之后：`mount`（只读探测）→ `l1 --dir work/l1 --twice 2 --dump nflasha1,nflasha6,nflasha7`（EXPECT a1=8,323,072 / a6=16,777,216 / a7=8,388,608）。
4. 回来后还有个**纯离线**任务没跑出结果（被打断，`work/sauu/` 空）：反解 `sauu`/`mf` 里 `SignatureVerification` 的 `RSA_verify` 三参数来源（验的缓冲区/长度、签名指针是否= FDAT 尾 256 B）、公钥来源、验签在流程哪一步、`sauu` 是否写 nflasha1。

注意：鉴权一旦成功，相机会把 USB 从 MSC 切到服务模式（预期 `0x0336/0x02A9`）；若中途掉线先跑 `scan` 看 PID，别盲目重试。

## macOS 上真正的拦路石：interface0 被 `IOUSBMassStorageDriver` 占住（2025-10-23 实测）
诊断（`work/l1_step_mount2.log` + pyusb 直读描述符）：
- 相机 A7C 2.00（**`bcdDevice = 0x200`** ← 固件版本号编进 USB 设备版本，以后可用来确认版本/身份）只暴露 **1 个 configuration、1 个 interface**：
  `iface0 class=0x08 sub=0x06 proto=0x50`（USB Mass Storage / SCSI / Bulk-Only），bulk IN `0x81`、bulk OUT `0x02`、wMaxPacketSize `0x200`(512B)。
  ⇒ pmca/camtool 的 Senser 鉴权就是往这对 bulk 端点发 Sony `AuthPacket`，所以**必须先 claim interface0**。
- macOS 侧：`/dev/disk4`（FAT12 2.1 MB，卷名 **PMHOME**，A7C 空卡槽时 MSC 模式暴露的小卷）。
  `ioreg -c IOUSBMassStorageDriver` 里 ILCE-7C 的驱动链是
  `IOUSBMassStorageDriver → IOSCSILogicalUnitNub@0/@1 → com_sony_driver_dsccamDeviceInfo00 → IOBlockStorageServices/IOBlockStorageDriver`
  —— 注意那个 **`com_sony_driver_dsccamDeviceInfo`**：索尼的 SCSI vendor 处理入口（说明 MSC 模式下相机还走 vendor SCSI 命令，这条以后可能有用）。
- **`diskutil eject disk4` 成功，但 `is_kernel_driver_active(0)` 仍是 True** → `claim_interface(0)` 报 `USBError Errno 13 Access denied`。
  macOS 的 detach_kernel_driver 在 darwin 后端基本不可用（实测 EACCES），所以 **libusb 这条路在 macOS 上被系统 kext 卡死**。
  `kextstat`：`com.apple.iokit.IOUSBMassStorageDriver (280)` 已加载（arm64 / macOS 26.4 / **SIP enabled**）。
- 结论：**不是相机的问题，也不是我们协议的问题**（scan/描述符读取都正常）。要么把 macOS 的存储驱动卸掉/绕过，要么换 Linux 主机。

## MTP 模式能 claim，但服务通道只在 MSC 模式活着（2025-10-23 实测，关键）
把相机切到 **MTP** 之后：
- 枚举成 **`054C:0D2A`**，`iface0 = 06/01/01`（PTP + Still Image），bulk IN `0x81` / OUT `0x02` + intr IN `0x83`。
- **`is_kernel_driver_active(0) = False` → `claim_interface` 成功 ★**（macOS 在 MTP 模式下不绑驱动！）
- 但 `SonySenserAuthDevice.start()` 的那个**厂商控制请求被相机 stall**：
  `ctrl_transfer(0x41, 1, 0x37ff, 0xd7aa)`（StartSenser）→ `Errno 32 Pipe error`；`StopSenser (0xc800/0x2855)` 同样 EPIPE。
  直接往 bulk OUT 写 `AuthPacket` 也是 EPIPE（前面 `mount` 那次）。
⇒ **senser/Jiritsu 服务只在 Mass Storage 模式下存在**；MTP 模式下 claim 虽通，但没有可鉴权的服务面。
⇒ 死结：senser 需要 MSC 模式，而 MSC 模式的接口在 macOS 上被 `com.apple.iokit.IOUSBMassStorageDriver`(280) 占住；
   arm64+SIP 下 `kmutil unload -b com.apple.iokit.IOUSBMassStorageDriver` → `kext is in use or retained (-603946984)`。
- 顺带：`kextunload` 前已 `diskutil unmountDisk disk4`（PMHOME 卷），无效；`diskutil eject` 也无效（`kdriver` 仍 True）。

## macOS 路线判死（arm64：DriverKit 用户态存储驱动 + root 也没用）（2025-10-23 实测）
- `csrutil disable` 之后 `sudo kextunload -b com.apple.iokit.IOUSBMassStorageDriver` **仍失败**：
  `kmutil unload … kext is in use or retained (-603946984)`；相机拔线期间也一样（实例归零也卸不掉）。
- 真实原因：Apple Silicon 上 USB 存储由 **DriverKit 用户态驱动**（ioreg 里能看到 `IOUserBlockStorageDevice`）驱动，
  `kextstat` 里的 `com.apple.iokit.IOUSBMassStorageDriver (280)` 只是内核侧配套 —— 所以"kextunload 让接口空出来"这招在 arm64 上不成立。
- **以 root 跑也一样**：`work/probe_claim.py`（euid=0）→ `claim_interface(0)` 仍 `Errno 13 Access denied`，`is_kernel_driver_active(0)=True`。
  ⇒ **macOS 上没有任何常规手段能把 MSC 接口从系统驱动手里抢过来给 libusb。**
- 官方 App 之所以能连（见上一节）：它走 IOKit + SCSI vendor CDB `0x7a`，不需要 claim。
- 结论：**Jiritsu（senser 服务、FileControl 0xff01 / SET_FILE2 0x4010）只能在非 macOS 主机上跑**，或者等"更新器模式 03E2"这条路（未验证）。
  已经把工具打包好：`dist/a7c-jiritsu-linux.tgz`（70 KB；`tools/jiritsu_send.py` + `refs/Sony-PMCA-RE/pmca` + `run_l1.sh` + README，内含 Linux/Windows 步骤与只读保证）。

## 24. DIAC.csv = 相机侧命令字典（机身 nflasha6 上已删文件里车出来的，2026-10-23）

来源：`work/l1-camera/nflasha6.bin`（机身 dump，双读一致 `b9d759a7…`）里已删的 `DIAC.csv`（89,868 B，
偏移 `0x1d8800`，可打印率 1.000，**尺寸与根目录已删条目完全一致 ⇒ 完整恢复**）。
解析产物：`work/l1-camera/a6_carved/diac_full.csv`、结构化 **1374 条** `work/l1-camera/a6_carved/diac_commands.tsv`（sha `2a06f5b5…`）。
行格式：`idx,len;#组,string;#码,sub,名字,参数1,n1,参数2,n2,tag`。

**组 `#1001` = Jiritsu 通道全表（19 条，tag `016F0480`）** —— 与 `tools/jiritsu_send.py` 里从 libJiritsu 推的
opcode 名表**逐条对上**（独立第二证据源），并**新增参数规格**（这是之前缺的）：
```
4001 MODE P1,2|P4,1      4008 GET_FILE P1V,4|P4V,2    400F SET_FILE_PATH P1V,2|P4,1
4002 MOUNT P1,2|P4,1     4009 FILE_DELETE P1,2|P4,1    4010 SET_FILE2 P1V,4|P4,1
4003 FORMAT P1,1|P4,1    400A GET_FILELIST P1,1|P4V,2  4011 GET_FILE2 P1,3|P4V,2
4004 START P1,1|P4,1     400B GET_FILE_HASH P1V,4|P4V,2 4012 FILE_DELETE2 P1,2|P4,1
4005 DEBUG P1,1|P4,1     400C COMPARE_MEDIA P1V,4|P4,1  0013 TEST_UI_VIEW P4V,2|P4,1
4006 FIRMUP P1V,2|P4,1   400D GET_VERSION -,-|P4V,2
4007 SET_FILE P1V,4|P4,1 400E FACTORY P4V,4|RAW,-
```
要点：`GET_FILE2 = P1,3` ⇒ 路径之外还有 **3 个参数**（我们之前只发 2 个，`/usr/bin/*` 一直 130 可能就是缺参数/语义不对）；
`GET_FILELIST(0x400A)`、`GET_FILE_HASH(0x400B)`、`COMPARE_MEDIA(0x400C)` 是**列目录 / 取相机侧哈希 / 比对介质**——
写后校验不必自己再读一遍整块。

**组 `#0B01` = MPR（媒体/分区，49 条，tag `01150299`）**：`0010 FORMAT`、`0011 MAKE_PARTITION`、`0012 CHECK_MAP`、
`4020/4021 READ/WRITE_DATA_FILE`、`4022 GET_RW_DATA_FILE_STATUS`、`0038 PMBP_WRITE_DATA`、`0039 PMBP_GET_STATUS`、
`003A PMBP_CHECK_DATA`、`0880 SCN_FORMAT`、`0881 SCN_FLASH_BACKUP_INIT`、`404F MSEN_BACKUP_RELOAD`、
`40E0/08E1 SET_FACTORY_MODE(+SCN)`、`00E2 GET_FACTORY_MODE_RESULT`。
其它相关组：`#0307 #0003 TP_FIRMUP`（触屏固件）、`#2B01 #0003 EXEC_REC_FORMAT`、`#2B01 #0007 EXEC_MEDIA_FORMAT`。

**同时车出的 Jit 工具痕迹**（详见 `work/l1-camera/A6_CARVE.md`）：
- worker 本体 `libJit.so` 409,551 B（ARM32 ET_DYN，SONAME `libJit_NB.so`，GCC 4.5.1 "Sony CE Linux 8.2.6.0"），
  入口表 `RunScriptI/LoadScriptI/CreateScriptI/DestroyScriptI/CreateDiAdjCtlI/DestroyDiAdjCtlI/MountMediaI/DetectMediaI/jiritsu_uart_thread`；
  自带字串含 `/tmp/jbusy`、`/tmp/jiritsu/jcount`、`/usr/scenario/`。
- `jit.log` 两段共 3.16 MB（`0x1f0800`+`0x3c8800`）：工厂会话逐条记录（命令 + DIAC 对照 + 返回值），
  出现 `_WRITE_koutei_ID` 95 次、`_WRITE_Jiritsu_ID` 95 次、`_RAM_WRITE` 130 次、`tar` 36 次。
- 推送包名（日志）：`jiritsu_20210402_01_NB_SDPW_AUTO.tar.dat`；hash 清单格式 `<idx>,<文件名>,<时间戳>`。

**路线影响**：Route B 可以**不自己写 worker** —— 把索尼原件放回 `/tmp/jiritsu/libJit.so`，
用它的 DSL 写场景（`define/yank/calc/setenv/mode/sleep/FCTAREA_*/sen_*/WAIT_MSG.<label>`）；
分区级写有官方命令可用（`MAKE_PARTITION`/`FORMAT`/`PMBP_WRITE_DATA`/`WRITE_DATA_FILE`/`SCN_FLASH_BACKUP_INIT`），
比裸 `dd` 风险低【推测，待实测】。下一只读探针应发 `0x400A/0x400B/0x400D/0x4001`。

## 25. ★ FileControl 的 padding bug（我们自己的错，之前"全 130"是假象）+ L2 实测要点

**bug**：`pmca`/我们工具里文件名填充写成 `fn += b'\0' * (4 - len(fn) % 4)` —— 当路径长度已是 4 的倍数时**会多补 4 个 NUL**，
相机把多余 NUL 当路径内容 ⇒ 一律 `file control error 130`。正确：`(-len(fn)) % 4`（已对齐就不补）。
远端已修（备份 `.prepatch.bak`），本机 `tools/jiritsu_send.py`（2 处）与 `dist/a7c-jiritsu-linux.tgz` 同步修好。
**影响**：之前"FileControl 读不到 /usr/bin/*、partinf.conf、mount.conf"的结论**全部作废**。修好后实测可读：
`/version.txt`、`/setting/{kemco.txt,Backup.bin,updater/comp(0B),updater/dat4(00 02)}`、
`/usr/bin/{crypter.elf,udtrbody.bin,up.sh,sen.elf,change_mode.sh,us_remove_modes.sh}`、
`/usr/lib/{libupdater{ufp,talk,ufunc,common,media},libJiritsu,libsencore}.so`、`/tmp/{nsswitch.conf,kikilog.dat,toprc,services,config.spec}`。
仍不可读：`/setting/updater/mode*`、`uincomp/debug/version.txt`、`/setting/{partinf,mount}.conf`（运行系统里确实没有）、
`/boot/* /p1chksum /dat1-4`（在 nflasha1 里）、`/usr/bin/{mf,sauu,…}`（也在 nflasha1 里）、任何**目录**（FileControl 无列目录能力 → 用 DIAC 的 `0x400A GET_FILELIST`）。
另：每条命令前做一次 libusb reset（远端 `~/a7c-jiritsu/wrap2.sh`），否则通道会忙。

**L2 五区 dump（双读，`work/l2-camera/`）**：`a15` 300 MB **12 MB/s / 24.2 s**；双读一致 ✓ 的有 a1/a4/a6/a10/a13/a15/a23；
**a2 唯一不一致**（差 10 字节）：只在 FAT/FSInfo 记账 + 相机自己在写的活动文件 `.hasp/.etools`；按文件抽取比对则其余逐字节一致 ⇒ **a2 备份按文件取**。
- **★ a15（/usr）= 2.00 原厂未改**（我本机复核）：机身前 239,982,592 B 与包内 `0700_part_image/dev/nflasha15` **sha256 同为 `861b38b033c25094…`**，尾部 74,590,208 B **全零**；逐文件 SAME：`crypter.elf/udtrbody.bin/up.sh/sen.elf/change_mode.sh/us_remove_modes.sh/libupdater×5/libJiritsu/libsencore`。⇒ 我们所有写计划的前提成立。
- **a2 无 mode\* 残留**（无 mode6 地雷），只剩 `comp`(0B) + `dat4`；但 FAT 里有**已删**的 `/setting/updater/mode`（2011-01-01 00:11:42 建、00:11:43 删，落在 a13 `update.log` 记的 MODE=3 那次更新窗口内）与 `/setting/mode/` 里被删的 3 字节 `"06\n"`（= `change_mode.sh` 的 dmode）。a13 `update.log` 还显示第一次更新 MODE=1 跑过 **EDISX + PFORMAT**。
- **a4 不是空的**（不是全 0/全 F；开头是 `CMMex` 结构表：`43 4d 4d 65 58 00 58 00 81 00 00 00 00 01 03 ff …`）⇒ **"每次更新必擦 nflasha4"不能当安全垫**，a4 里有真数据（partinf 标的是 `MPR Flash Backup`）。
- `/tmp/jiritsu` 在运行系统里**存在但为空**，无 `/tmp/jbusy` ⇒ 机身上没有任何 Jiritsu worker（我们首次写 `libJit.so` 是全新创建，但也**没有原厂 worker 可备份**）。

## 26. ★更正（待判）：FileControl「padding bug」这条结论**不成立**，`130` 的因果要重做实验
之前记的"补白写错导致一律 130，改 `(-len)%4` 才全线可读"经不起核对：
1. **真机的 FileControl 一直走 pmca 的实现**（`refs/Sony-PMCA-RE/pmca/usb/sony.py:999` = `4 - len%4`），我们只改了 `jiritsu_send.py` 里 **mock 类**和离线 `frames` 的两处 ⇒ 真机行为当时**没有变过**。
2. 同芯片实证的 **camtool 也用 `4 - len%4`**（`refs/Sony-ZVE-10-Camtool/jiritsu_lib.py:155/161/167`），a7c2 研究的 vendored pmca 也一样 ⇒ 这不是我们的笔误，是既有实机语义。
3. 两种写法**只在 `len(path)%4==0` 时分叉**；PROBE2 里"修好才能读"的那些路径几乎都不是 4 的倍数（`/usr/bin/crypter.elf`=21、`/setting/updater/comp`=21、`/tmp/nsswitch.conf`=18 → 两种写法**逐字节相同**），所以那些成功**不能证明**修复有效。唯一能分辨的 `/usr/bin/sen.elf`(16 B) 当时恰好也在"可读"清单里——而那是在 pmca 的**多补 4 NUL** 语义下读到的 ⇒ 反而指向"**多补无害**"。
⇒ 已做：工具里 FileControl 收进单一 `_fc()` 并用 `--pad pmca|aligned` 切换；新增 **`padtest`** 子命令对同一条 16 B 路径各读一次（两次会话，只跑一次别反复）；**L2.5 白名单路径全部改名避开 4 的倍数**（`/tmp/zzprobe1`、`/setting/updater/zzprobe1`、`/tmp/jiritsu/zzprobe1`、`/usr/lib/zzprobe1`），把这条分歧从关键路径上摘掉。判据留在真机：`padtest` + 之后每个探针都以"读回字节数+sha"为准，不再引用"130=padding"作为解释。
