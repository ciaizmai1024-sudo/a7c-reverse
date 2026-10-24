# nflasha6（= /tmp/jiritsu）已删文件车取 + Sony 工厂 Jit 工具链复原

数据来源：机身 dump `work/l1-camera/nflasha6.bin`（16,777,216 B，sha `b9d759a7…`，两次读一致）。
卷：BPB@0x200（设备前 512 B 是别的东西）、512 B/扇区、32 扇区/簇（16 KiB）、FAT12、根目录 512 项。
**根目录 10 条全部 `0xE5`（已删）、FAT[2..] 全零 ⇒ 现在挂载是空卷，但数据还在原地**（详见 `A6_A7_MAP.md`）。

## 1. 车出来的东西（`a6_carved/`）

| 文件 | 偏移 | 长度 | 可打印率 | sha256(前 16) | 判定 |
|---|---|---|---|---|---|
| `diac_full.csv` | `0x1d8800` | **89,868** | 1.000 | `680527ad9bd437d1` | **与已删条目 `DIAC.csv` 尺寸完全一致 ⇒ 完整恢复**（1386 行） |
| `jitlog_part1.bin` | `0x1f0800` | 1,900,544 | 0.995 | `1aa464d8c510b100` | `jit.log`(3,244,032) 的前段 |
| `jitlog_part2.bin` | `0x3c8800` | 1,261,568 | 0.995 | `cbc0f9bbe47e5067` | `jit.log` 的后段（两段共 3.16 MB / 3.24 MB，中间缺 ~31 KB） |
| `region_079200.bin` | `0x079200` | 833,084 | 0.905 | `d11f00a5ccb9874d` | CSV 文本 + 场景脚本混排区（`tmmc.jit` 的碎片在这里） |

`libJit.so`（409,551 B，已删条目 cl=5）已在 `a6_extracted/a6_libJit_recovered.so`（sha `47f614e4…`，见 §3）。
`tmmc.jit`（770,108 B）**没能拼成整块**：场景文本散在 `0x88000–0x91000`（`function ` 出现在 0x888a9/0x88c2c/0x88e6b/…）、`0x2f537d` 也有；FAT 链已丢，簇复用打断了它。

## 2. Sony 工厂会话实际执行过什么（从 `jit.log` 两段统计）

DSL 动词/场景步骤名 TOP：`B0201_APPFWINFRA_INPUT_GETEVENT` 2127、`B0603_FACTORY_256` 1771、`sen_print` 1346、`sleep` 1051、
`define` 817、`setenv` 774、`yank` 762、`calc` 298、`sen_print_flush` 281、**`mode` 261**、`B1001_JIRITSU_FACTORY` 235、
`set_ng_process` 202 / `clr_ng_process` 201、`sen_res_save` 152、`FACTORY_CHECK` 97、`B1001_JIRITSU_MODE` 97、`FCTAREA_COMMON` 75 …
与"写/分区/工厂区"相关的动作：`_RAM_WRITE` 130、**`_WRITE_koutei_ID` 95、`_WRITE_Jiritsu_ID` 95**（工艺 ID / Jiritsu ID 落机）、
`FCTAREA_USE_SYSTEM` 177、`FCTAREA_TRIAL_CODE` 171、`F_RAM_WRITE` 60、`tar` 36。
日志行格式：`NNNN <命令>(参数…) (Gyo:--) (Lap:秒)\n   * <DIAC名>[组:码] 参数… = [返回]` ⇒ **每条动作都有 DIAC 对照与返回值**。

## 3. worker 契约（`a6_extracted/a6_libJit_recovered.so`，我复核过）

ARM32 小端 `ET_DYN`，`e_machine=0x28(40)`，`e_flags=0x5000002`，`entry=0x125b0`，SONAME **`libJit_NB.so`**；
`.comment` = `GCC: (20181205 (Sony CE Linux 8.2.6.0)) 4.5.1`；NEEDed：`libbackup.so libpthread libstdc++ libm libdl libgcc_s libc librt`。
**非 C++ 修饰的定义符号（= 服务进程 dlsym 的入口表）**：
```
RunScriptI  LoadScriptI  CreateScriptI  DestroyScriptI
CreateDiAdjCtlI  DestroyDiAdjCtlI  MountMediaI  DetectMediaI  jiritsu_uart_thread
```
内部类：`CScriptBase/CScriptInt/CScriptExecCall(tag_SCR_INFO,tag_SCR_RECORD)`、`CDiOsal(OsalResponsePacket,PacketHeaderDump)`、
`CDiAdjCtl`、`CMathClass(CALC_TYPE)`、`CYank`、`CScriptBase::sys_tar_compress` … ⇒ **它是一个"脚本解释器 + Diagnostics/OSAL 客户端"**。
自有字串：`/tmp/jbusy`、`/tmp/jiritsu/jcount`、`/usr/scenario/`、`/dev/mem`、`/mnt`、`/proc/tmonitor`、`/proc/sys/vm/drop_caches`。

## 4. ★★ 最大收获：DIAC.csv = 相机侧命令字典（含 Jiritsu 全部 opcode 与参数规格）

`a6_carved/diac_full.csv` 解析成 **1374 条结构化命令**（`a6_carved/diac_commands.tsv`，sha `2a06f5b53be539c6`）。
行格式：`idx,len;#组,string;#码,sub,名字,参数1,n1,参数2,n2,tag`。组 TOP：`0404`=248、`3501`=60、**`0B01`=49**、`0302`=48 …

**组 `#1001` = Jiritsu 通道全表（`tag=016F0480`）**：
```
4001 JIRITSU_MODE         P1,2|P4,1      4008 JIRITSU_GET_FILE       P1V,4|P4V,2
4002 JIRITSU_MOUNT        P1,2|P4,1      4009 JIRITSU_FILE_DELETE    P1,2|P4,1
4003 JIRITSU_FORMAT       P1,1|P4,1      400A JIRITSU_GET_FILELIST   P1,1|P4V,2   ← 列目录
4004 JIRITSU_START        P1,1|P4,1      400B JIRITSU_GET_FILE_HASH  P1V,4|P4V,2  ← 取相机侧哈希
4005 JIRITSU_DEBUG        P1,1|P4,1      400C JIRITSU_COMPARE_MEDIA  P1V,4|P4,1   ← 比对介质
4006 JIRITSU_FIRMUP       P1V,2|P4,1     400D JIRITSU_GET_VERSION    -,-|P4V,2
4007 JIRITSU_SET_FILE     P1V,4|P4,1     400E JIRITSU_FACTORY        P4V,4|RAW,-
400F JIRITSU_SET_FILE_PATH P1V,2|P4,1    4010 JIRITSU_SET_FILE2      P1V,4|P4,1
4011 JIRITSU_GET_FILE2    P1,3|P4V,2     4012 JIRITSU_FILE_DELETE2   P1,2|P4,1
0013 JIRITSU_TEST_UI_VIEW P4V,2|P4,1
```
⇒ **独立确认了 `tools/jiritsu_send.py` 里的 opcode 名字表**（我们早先从 libJiritsu 推的名字全对），
并且**新增参数规格**（P1/P4/P1V/P4V + 个数）——这解释了 `GET_FILE2 = P1,3`（路径 + 2 个参数：mode/偏移 之类）与 `SET_FILE2 = P1V,4`。

**组 `#0B01`(=MPR，媒体/分区操作，49 条，`tag=01150299`) 关键项**：
```
0010 MPR_CMD_FORMAT            0011 MPR_CMD_MAKE_PARTITION     0012 MPR_CMD_CHECK_MAP
4020/4021 MPR_CMD_READ/WRITE_DATA_FILE     4022 GET_RW_DATA_FILE_STATUS
0038 MPR_CMD_PMBP_WRITE_DATA   0039 PMBP_GET_STATUS            003A PMBP_CHECK_DATA
0881 MPR_SCN_FLASH_BACKUP_INIT 404F MPR_CMD_MSEN_BACKUP_RELOAD 0880 MPR_SCN_FORMAT
40E0 MPR_CMD_SET_FACTORY_MODE  08E1 MPR_SCN_SET_FACTORY_MODE   00E2 GET_FACTORY_MODE_RESULT
```
另有 `#0307 #0003 TP_FIRMUP`（触屏固件更新）、`#2B01 #0003 EXEC_REC_FORMAT`、`#2B01 #0007 EXEC_MEDIA_FORMAT`。

## 5. 对写路线的直接影响（把 Route B 升级）

1. **可以不自己写 worker**：索尼自己的 `libJit.so` 已在机身 a6 上完整恢复（409,551 B，入口表见 §3）。
   把它的原件放回 `/tmp/jiritsu/libJit.so` 就能得到**已验证可用的 worker**，我们的动作写成 `.jit` 场景脚本（DSL 已知：`define/yank/calc/setenv/mode/sleep/FCTAREA_*/sen_*` + `WAIT_MSG.<label>`）交给 `LoadScriptI/RunScriptI`。
   【待实测】它的场景解释器是否接受我们手写的场景；`/usr/scenario/` 是否是脚本搜索路径。
2. **写后校验有了官方手段**：`0x400B GET_FILE_HASH`、`0x400C COMPARE_MEDIA`（不用自己算完再比一遍通道）。
3. **分区级写可能不用裸 dd**：`MPR_CMD_MAKE_PARTITION / MPR_CMD_FORMAT / MPR_CMD_PMBP_WRITE_DATA / MPR_SCN_FLASH_BACKUP_INIT` 都是**工厂通道里的正式命令**（PMBP=2 MB 校验校准区，见 nflasha23）。
   【推测】`MPR_CMD_WRITE_DATA_FILE(0x4021)` 与 `PMBP_WRITE_DATA(0x0038)` 可能就是"写校准/数据区"的安全入口，比 dd 写整分区风险低。
4. **下一只读探针该发**（都在这张表里，参数规格已知）：
   `0x400A GET_FILELIST`（列 `/tmp/jiritsu`、`/setting/updater`）、`0x400B GET_FILE_HASH`、`0x400D GET_VERSION`、
   `0x4001 MODE`（查/设模式）、`0x4011 GET_FILE2`（按 `P1,3` 补第三个参数再试 `/usr/bin/*`）、`0x4002/0x4003` 只做 mount 只做读、不要 format。

## 6. 还剩什么

- `tmmc.jit`（770,108）与 `Ver.txt`(454)/`history.txt`(2,158)/`jcount`(4)/`jiritsu.hash`(16) 未拼成整块（FAT 链丢、簇复用）。
- 那个被推送过的包 `jiritsu_20210402_01_NB_SDPW_AUTO.tar.dat`（日志 `setenv[37] JIRITSU_FILE_NAME` 提到）数据未定位。
- DIAC 1374 条里 `#0404`(248)/`#3501`(60)/`#0302`(48) 组还没读意思。
