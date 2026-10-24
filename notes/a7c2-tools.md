# A7C II 商用改功能工具（refs/a7c2-fl23-research）— 通信与写回机制笔记

> 目的：只提取"能搬到 A7C 一代（ILCE-7C, v2.00, 同 SoC CXD90045）"所需事实。
> 参考仓库：`refs/a7c2-fl23-research`（Sony A7C II / ILCE-7CM2，固件 2.01；工具 3.0.2 / FL23 资产 release `0.6.0-preview`）。
> 全程只读，refs/ 未做任何修改。引用格式 `文件:行号`；【推测】/【推定】是我的判断，不是仓库原文。

---

## 0. 要点摘要

1. **两条 USB 身份、两次认证**：普通身份 `054C:0E8A`（USB 海量存储 MSC，接口 class=8/sub=6/proto=0x50）；在 0E8A 上做一次 Senser 认证（vendor request + SHA1/SHA256 挑战）后，相机**自动重枚举**成服务身份 `054C:0336`（"Sony USB Device"），再在 0336 上**第二次认证**，之后才打开数据通道（`src/camera_runtime/transport.py:255-297`）。
2. **文件通道 = Jiritsu AdjustControl 的 4 个命令**：`pFunc=0x40` + `struct.pack('<HH', 0x1001, cmd)`；cmd 白名单只有 **15=SET_FILE_PATH(select)、16=SET_FILE2(write)、17=GET_FILE2(read)、18=FILE_DELETE2(remove)**（`transport.py:322-341`）。绝对路径靠 `select('/tmp/jiritsu/../../usr/lib/appFw.so')` 这种 `..` 逃逸实现（`src/looks/looktool/devicesession.py:101`）。
3. **真正被改的两个"程序载体"**：`/usr/lib/appFw.so`（99,960,744 B）与 `/cp/cpapp-b.bin`（18,090,880 B）（`src/camera_runtime/native/patch_manifest.h:83`）。改法是**固定窗口 pwrite 补丁**（共 40 个窗口，`patch_manifest.h:82`），不刷裸 flash、不换 inode。
4. **机内执行体是相机自己 dlopen 的 `/tmp/jiritsu/libJit.so`**：工具把 AArch64 原生 worker（`installer.c/probe.c/wbi.c/runtime.c`）写成 `libJit.so`，相机端 Jiritsu 的 SET_FILE2 路径会 dlopen/dlclose 它（`src/camera_runtime/native/probe.c:2-4` 注释原文："Loaded by SET_FILE2's native libJit.so dlopen/dlclose path"）。**不使用 `/etc/ld.so.preload`**，看到既有 preload 配置立刻停止（`src/camera_runtime/app.py:54`、`devicesession.py:146,159`）。
5. **设置侧走 Backup(BK4) 属性**：读 `getBackupPresetData`(0x603/5)、写属性 `writeBackup`(0x603/2)、保存 `saveBackup(0x02cf / 0x02a4)`；色彩大单元走 `AdjustControl 0x603/0x40(read)、0x41(write)`，key `0x02a40001`(8192B) / `0x02a4000d`(28672B)（`core.py:19`、`transport.py:342-351`）。FL2/FL3 的"开关"是两个 AP 绑定属性 `0x02cf1287=0x0a`、`0x02cf1289=0x0b`（`app.py:173`，重开后核对在 `app.py:249`）。
6. **机身绑定用 BK4 里的 4 字节序列号属性 `0x00e70003`**（不是 PTP 属性，是 Sony Backup 属性 ID），且必须按老工具做法 **先 hexlify 再 sha256**（`transport.py:197-207`）。新版桌面另外还绑 USB 字符串序列号（`usbidentity.py:4-14`）。
7. **必须"冷启动"才生效**：相机把开机状态存在 WBI（`/sys/power/image_mode == "2"`、`image_dev == "*wbi4"`）。工具用原生 worker 写 `image_drop='1'` → `image_mode='0'` 丢掉快照（`native/wbi.c`），但**仍要求用户拔电池 ≥1 分钟**；核对阶段用 `boot_id` 变化证明真的冷启动过（`direct.py:721`）。
8. **防砖**：写前完整读回原始两文件 + 双份独立备份 + checkpoint zip；写前要求 `/usr` 为 **ro 挂载**、文件类型/大小/inode 不变；worker 内部 mount rw→pwrite→fsync→逐窗口读回→失败**按逆序自动回滚**→最后必恢复 ro；主机侧再整文件读回；结果未知绝不重试（`AGENTS.md:35-36`）。
9. **搬到一代的关键发现**：本仓库现成的一代 `/usr` 解包（`nflasha15_unpacked`）里 **`lib/libJiritsu.so` 本身就带同一整套 Jiritsu 文件命令名（含 SET_FILE_PATH/SET_FILE2/GET_FILE2/FILE_DELETE2）与 `libJit.so` JIT 加载器**（§5.2）；一代更新器里也有 `ud_wbi_drop.elf`。→ **协议/执行层几乎肯定可搬**。不可搬的是二代的**具体文件名、偏移、属性取值**：一代 v2.00 更新包里没有 `appFw.so`、没有 `cpapp-b.bin`、没有 `/cp` 挂载点（与已有 `FIRMWARE_MOD.md:159-160` 结论一致）。
10. **命令号语义（重要推定）**：一代 `libJiritsu.so` 的 JIRITSU 命令名字串表连续等间距排列，按序数到 **15=SET_FILE_PATH、16=SET_FILE2、17=GET_FILE2、18=FILE_DELETE2**，与二代白名单 `[15,16,17,18]` 完全吻合 → §1.5 表，【推定，证据强】。

---

## 1. 协议细节（服务模式 USB）

### 1.1 两个 USB 身份与端点

| 身份 | VID:PID | 何时出现 | 接口/端点 | 证据 |
| --- | --- | --- | --- | --- |
| 普通（Mass Storage） | `054C:0E8A` | 开机 + 菜单选"海量存储" | 接口 class=8/sub=6/**proto=0x50**（BBB），bulk IN/OUT | `transport.py:260`（macOS 校验 `(8,6,0x50)`）；`vendor/pmca/usb/driver/generic/libusb.py:26-32`（proto 0x50 → MscBbbDriver）；README 表（`054C 0E8A` = `ILCE-7CM2`） |
| 服务（Senser） | `054C:0336` | **只在认证之后**出现，屏常显"请检查所连接的设备" | vendor-specific bulk | `vendor/pmca/usb/sony.py:31` `SONY_ID_PRODUCT_SENSER=[0x02a9,0x0336]`；`generic/libusb.py:52` `VendorSpecificContext`；README（`054C 0336` = `Sony USB Device`） |

- 端点查找是通用的"取所有 bulk"：`GenericUsbDriver._findEndpoints`（`generic/__init__.py:84-90`），`epIn[0]`/`epOut[0]` 为第一个 IN/OUT。**仓库没有硬编码端点地址**；测试夹具用 `0x81 / 0x02`（`dev/usb/tests/test_initial_usb_diagnostic.py:30`）——仅测试用。【推测：实机常见 0x81/0x01】
- 0336 与非 0336 在帧层有一处差异：`minSize = 0 if driver.getId()[1]==0x0336 else 0x200`（`sony.py:854`；工具同逻辑 `transport.py:41`）→ **0336 上响应头不做 512 对齐补齐**，只有 MTP/PTP 通道才需要 `SenserMinSize=0x200` 最小包。
- 0336 出现后必须 `time.sleep(2)` 再打开（`transport.py:283`）；macOS 还要先 `claim_camera_interface(self.dev)`（`transport.py:284-286`）。

### 1.2 普通身份（0E8A）上的"信息通道"（不是服务通道）

用途：型号/序列号查询与存储就绪检查，**不写任何东西**。

- SCSI INQUIRY：`MscDevice.getDeviceInfo()`（`vendor/pmca/usb/__init__.py:57`），要求 manufacturer == `Sony`（`transport.py:176-177`）。
- Sony 扩展命令封装在 MSC 厂商操作码：`MSC_OC_ExtCmd = 0x7a`；命令块 = `0x7a + LE32(命令组) + 7×0x00`；busy 时反复重试直到 sense ≠ `(0x09,0x81,0x81)`（`vendor/pmca/usb/sony.py:85-104`）。
- 内层头 `ExtCmdHeader = {dataSize INT32, cmd INT16, direction INT16, 8B 保留}`（`sony.py:190-196`）；命令组/号全表在 `sony.py:151-186`（`DevInfoSender_GetModelInfo=(1,1)`、`ExtBackupCommunicator_ForcePowerOff=(4,5)`、`ScalarExtCmdPlugIn_NotifyScalarDlmode=(5,2)` 等）。
- `getCameraInfo()` 解析：plist → modelName → 5B modelCode → **4B serial（被 hexlify 成文本）**（`sony.py:281-292`）。
- 工具对就绪/busy 的有界化（这是它踩过的坑）：只允许 `TEST UNIT READY`（`bytes(6)`），只接受 sense `(0,0,0)` / `(2,4,1)` / `(6,0x29,0)` / `(6,0x28,0)`，其他立即停（`transport.py:128-146`）；Sony 扩展命令只重试 `MSC_SENSE_DeviceBusy=(9,0x81,0x81)`（`transport.py:148-172`）。允许继续的"已知忙/无卡"情形被枚举成两条错误串（`looktool/usbservice.py:8-13`，含 `sense=02/3a/00`）。

### 1.3 Senser 帧格式（真正的数据通道）

包头（`vendor/pmca/usb/sony.py:821-830`，尺寸常量在 `:833-835`）：

```
struct SenserPacketHeader {         // 共 12 字节，小端
  int32 size;      // 载荷总长度（不是整包长度）
  int16 pFunc;     // 功能类
  int16 sequence;  // 自增，从 1 开始
  int8  version;   // 0
  int8  miconType; // 0
  int8  offsetType;// 0
  int8  response;  // 响应状态，按 pFunc 语义解释
}
SenserMinSize   = 0x200      // 512
SenserChunkSize = 0x8000     // 32K
SenserMaxSize   = 0x100000   // 1M
```

发送（`sony.py:847-858`）：载荷按 1MB 切片，**每片都带同一个 size 头**。
接收（`sony.py:860-875`；工具重写版 `transport.py:33-60`）：
1. 先读 `12 + max(minSize-12, 0)` 字节；
2. 校验 `header.sequence == self._sequence`，否则 `Exception('Wrong senser sequence')`（真实事故中出现过：changelog 3.0.1 "68 个名称已提交…Wrong senser sequence"）；
3. 循环补齐 `min(header.size, SenserMaxSize)`；每当某分片长度是 512 的整数倍，就再读一个 512B "结束/尾包"；
4. **工具的关键修复**：pmca 原版那次结束读无超时，现场日志 31 里最后一个 20992B 包之后尾包永不到来，把整个 180 s 预算耗光。工具换成**最多 1 秒**的可选等待：`END_PACKET_MS=1000`、`_end_packet()` 吞掉 `usb.core.USBTimeoutError`（`transport.py:26-31`）；迟到的包会在下一个响应头被 sequence 检查大声抓出（`transport.py:17-24` 类注释）。

pFunc 取值（`sony.py:940-947`）：

| pFunc | 名称 | 本工具是否使用 |
| --- | --- | --- |
| 0x10 | ProductInfo | 有：`readHasp()`（旧 CLI 要求正好 88 字节，`src/fl23/transport.py:120-123`）、terminal 切换 |
| 0x20 | FirmwareUpdate | 否 |
| 0x30 | MiconAccess | 否 |
| **0x40** | **AdjustControl** | **主力**：Jiritsu 文件命令（0x1001 类）+ Backup/属性（0x603 类） |
| 0xff00 | TestMode | 否 |
| 0xff01 | FileControl | 否（pmca 提供；工具用 Jiritsu 通道代替） |
| 0xff02 | Sonar | 否 |
| 0xff03 | MemoryDump | 否 |

封装：`_sendAdjustControlPacket(block, code, data)` 要求返回 `res == 0`，否则 `Senser adjust control error %d`（`sony.py:990-995`）。命令常量（`sony.py:967-974`）：

| 用途 | block/code |
| --- | --- |
| Backup 读属性 | `0x603, 1` |
| Backup 写属性 | `0x603, 2` |
| Backup 保存子系统 | `0x603, 3`（参数 `dump16le(0x02cf)` 或 `0x02a4`） |
| 预设数据 写/读/状态 | `0x603, 4 / 5 / 6` |
| Backup ID1 | `0x603, 15` |
| Senser terminal mode | `0x601, 0x1f` |
| **Jiritsu 文件命令** | **`0x1001, 15/16/17/18`**（工具自己拼，见 §1.5） |

### 1.4 认证 / 身份握手

`SonySenserAuthDevice`（`vendor/pmca/usb/sony.py:890-937`）：

- 进入 Senser：`vendorRequestOut(request=1, value=0x37ff, index=0xd7aa)`（`sony.py:891,900-905`）；退出：`(1, 0xc800, 0x2855)`（`sony.py:892,906-910`）。控制传输 = `CTRL_OUT|CTRL_TYPE_VENDOR|CTRL_RECIPIENT_OTHER`（`generic/libusb.py:101-105`），异常一律吞掉（`try/except pass`）。
- 报文：`AuthPacket = {cmd INT16, salt INT16, data[0x200]}` **大端**（`sony.py:893-898`）。发送 `cmd = ~cmd & 0xffff`；回包 `ret = (~resp.cmd & 0xffff) - resp.salt`（`sony.py:912-917`）。
- 流程：3 轮 `{ cmd1 → ret∈{2,8} → cmd3 (dump8(1)+hash) → ret==4 }`，最后 `cmd5 → ret==6` 并要求回包首字节 == 1（`sony.py:918-937`）。
- `ret==2` → SHA-1，且是 Sony 的**坏 SHA1**：`sha1(message, len(message) & 0x1f)`（`vendor/pmca/usb/crypto.py:38-40`）；`ret==8` → SHA-256（Cryptodome）。
- 挑战拼接按身份不同：`data = data + keys[i] if self.driver.getId()[1] == 0x0336 else data[:4]`（`sony.py:925`）→ **0E8A 上只用相机返回的前 4 字节**（低强度握手），**0336 上用完整挑战 + 内置 key**。
- 内置 key：`senserKeysSha1` 3 条 / `senserKeysSha256` 3 条（`vendor/pmca/usb/constants.py`，源自 Sony-PMCA-RE，跨机型通用）。

会话时序（`transport.py:247-303`；文档版 `docs/zh-CN/development.md:88-95`）：

```
get_device(0x0e8a)
 → (mac) 卸载相机存储卷 + claim 接口(8,6,0x50)
 → 读 USB 产品字符串 == 'ILCE-7CM2'（只是防呆，不是服务 gate）   [transport.py:263-264]
 → start + authenticate（0E8A，预算 20 s）
 → dispose，等 0336 出现（最多 20 s，期间记录所有见过的 Sony PID）  [transport.py:224-242]
 → sleep(2) → (mac) claim 0336 接口
 → start + authenticate（0336，默认预算 180 s）
 → 建 SonySenserDevice / SonySenserCamera
 → getBackupPresetData(True) 取 BK4 → 绑定机身身份
 → …（写操作）… → auth.stop()（vendor request 0xc800）→ (mac) 等普通身份回来
```

**冷却/重试**（现场日志 28、30 的经验）：`SERVICE_COOLDOWN=30`、`SERVICE_ATTEMPTS=3`、`SERVICE_WAIT=20`（`transport.py:210-212`）；注释指出认证后相机会先跳到 `054C:0D68`、再 `096F`、再回 MSC，**永远不会以 0336 出现**，发生在退出后 12–15 s（`transport.py:207-209`）。若 **0336 出现过但接口打不开** → 直接报错、**不重新认证**（`transport.py:272-273`）。

**RecoverySession**（`transport.py:353-380`）：相机仍停在 0336 时，允许**完全不发 start/authenticate** 直接接管已有会话，只用 BK4 序列号核对机身，再升预算到 180 s；对应中文提示"只读取已有服务会话的机身序列…不重复认证"（`devicesession.py:63-66`）。

### 1.5 Jiritsu 命令号语义（含完整命令表）

工具封装（`transport.py:322-341`；旧 CLI 等价 `src/fl23/transport.py:150-183`）：

```python
def jiritsu(self,cmd,data=b'',missing=False):
    if cmd not in [15,16,17,18]: raise ValueError('不允許此 Jiritsu 命令')
    response,out=self.call(self.channel.sendSenserPacket,0x40,struct.pack('<HH',0x1001,cmd)+data)
    if response or len(out)<4: raise RuntimeError('Jiritsu 回應格式錯誤')
    status=struct.unpack_from('<I',out)[0]
    if missing and status==0x10000006: return None
    if status: raise RuntimeError(f'Jiritsu 狀態 {status:#x}')
    return out[4:]
def select(self,path):
    if not path.startswith('/tmp/jiritsu/') or '\0' in path or len(path)>510: raise ValueError('路徑不符')
    self.jiritsu(15,b'\0'+path.encode('ascii')+b'\0')
def read(self,path,missing=False): self.select(path); return self.jiritsu(17,b'\0\xff\0',missing)
def temp(self,name,data=None,remove=False):
    path='/tmp/jiritsu/'+name; self.select(path)
    if remove: self.jiritsu(18,b'\0\xff')
    elif data:
        if len(data)>65536: raise ValueError('臨時檔過大')
        self.jiritsu(16,b'\0\xff\0'+data)
```

要点：
- 载荷 = `category(0x1001) + command(cmd)` + 命令参数；回包前 4 字节是 **LE32 状态码**，其余是数据。
- **已知状态码只有**：`0x10000006` = 文件不存在（仅在 `missing=True` 时接受为 None）；`0` = 成功；其他一律报错（`transport.py:327-329`）。仓库没有更全的状态字典。
- `select` 必须以 `/tmp/jiritsu/` 开头（≤510 字符、无 NUL），但**允许 `..`**：
  - 读程序：`select('/tmp/jiritsu/../..' + '/usr/lib/appFw.so')`（`app.py:108-110`）
  - 读任意文件：`'/tmp/jiritsu/../../' + path.lstrip('/')`（`devicesession.py:101`）→ 例如 `/etc/ld.so.preload`、`/usr/share/app/…`、`/etc/…`
  - **写只允许 `/tmp/jiritsu/<白名单名>`**（`transport.py:334-341`、`devicesession.py:6-10,102-116`）→ 工具从不通过 Jiritsu 直接写机身任意文件；对 appFw/cpapp 的改写由相机端原生 worker 用 `pwrite` 完成（§3.1）。
- 单文件写上限 **65536 字节**（`transport.py:338-340`）；95MB 的 appFw.so 只走读路径（Senser 1MB 分帧）。

**Jiritsu 命令号对照（从一代固件自身名字表推出，【推定，证据强】）**
一代 `nflasha15_unpacked/lib/libJiritsu.so` 有连续等间距（72B 步长）的命令名字串（文件偏移）：
`JIRITSU_MODE(41169) MOUNT(41182) FORMAT(41196) START(41211) DEBUG(41225) FIRMUP(41239) SET_FILE(41254) GET_FILE(41271) FILE_DELETE GET_FILELIST GET_FILE_HASH COMPARE_MEDIA(41351) GET_VERSION FACTORY(41393) SET_FILE_PATH(41409) SET_FILE2(41431) GET_FILE2(41449) FILE_DELETE2 JIRITSU_TEST_UI_VIEW(41488)`；同一张表带 `@` 前缀出现在 `bin/adjstctl.elf` 偏移 109771–110995。按"表内顺序 = 命令号"：

| cmd | 推定语义 | 一代符号（libJiritsu.so 字符串偏移） |
| --- | --- | --- |
| 1 | MODE | — |
| 2 | MOUNT | — |
| 3 | FORMAT | — |
| 4 | START | `cmd_start`（含 `jmode err not Manual`、`JMODE_OPEN_FAIL`） |
| 5 | DEBUG（会 `date -s` 改时钟；二代刻意不用） | `/bin/date -s %02d%02d%02d%02d%04d.%02d` |
| 6 | FIRMUP | — |
| 7 | SET_FILE | `adj_cmd_set_file` |
| 8 | GET_FILE | `adj_cmd_get_file` |
| 9 | FILE_DELETE | `cmd_file_delete` |
| 10 | GET_FILELIST | `adj_cmd_get_file_list`(7603) |
| 11 | GET_FILE_HASH（md5） | `adj_cmd_get_file_hash`(7801)，"file non-existent"(41014) |
| 12 | COMPARE_MEDIA | — |
| 13 | GET_VERSION | — |
| 14 | FACTORY | — |
| **15** | **SET_FILE_PATH（select）** | `adj_cmd_set_file_path`(7277)，"Request raw data size error.(max_size:%d)"(39228) |
| **16** | **SET_FILE2（write，会建目录）** | `adj_cmd_set_file2`(7492)，"file size over err size = %u"(39861)、"directory create error."(39909) |
| **17** | **GET_FILE2（read）** | `adj_cmd_get_file2`(7556) |
| **18** | **FILE_DELETE2（remove）** | `cmd_file_delete2`(7539) |
| 额外 | 大文件通道（本工具未用） | `cmd_high_capacity_send_file`(7698) / `cmd_high_capacity_get_file`(7823) |

> 结论：一代固件里 15–18 的语义与二代工具白名单高度一致；一代还现成有 10/11/12 与 high-capacity 通道，可能更好用（待实机验证）。

### 1.6 Backup(BK4) 与属性

- `getBackupPresetData(fromMemory)` = `0x603/5 + dump8(1|0)`：**True=RAM 活动设置，False=已保存(FLASH)设置**（`sony.py:1050-1051`）。工具两种都取并分别落盘（`app.py:122,197-198`）。
- `core.backup_records(raw)`：在流里扫 `b'BK4\0'`，要求**恰好 2 份**校验有效的 BK4（chip0=AP / chip1=CP 两个子系统域），用 pmca `BackupFile` 解析（`core.py:43-51`；格式 `vendor/pmca/backup/__init__.py:8-100`：`BackupHeader`（magic/cookie/`revision='BK4\0'`/checksum = 0x20 处存 `sum(data[:0x20]+data[0x24:])` / id1@0x28 / region）、子系统表、属性表；属性 ID = `(subsystem<<16)|index`；`size==0xff` 表示 OversizeProperty）。
- 属性 **`0x00e70003` = chip0 的 4 字节序列号**（`checkpoint.py:84-96`、`transport.py:197-207`）。
- 本工具的写目标白名单：
  - `AP_KEYS=[0x02cf1287,0x02cf1289]`（各 1 字节；原厂 `0x00`，安装后 `0x0a/0x0b`）（`core.py:20`、`app.py:173,249`）→ 把 FL2/FL3 绑到两个保留外观槽。
  - `CP_KEYS=[0x02a40001(8192B), 0x02a4000d(28672B)]` → 外观参数映射 + 色彩记录，走 `AdjustControl 0x603/0x40 read、0x41 write`（`transport.py:342-347`），改动后要 `saveBackup(0x02a4)`（`app.py:190`）。
  - 保存子系统号:`0x02a4`(CP/相机档案类)与 `0x02cf`(AP/外观绑定类)。属性写限制：必须在白名单里、`key>>16==0x02cf`、非空且≤4 字节（`devicesession.py:120-128`；`saveBackup(0x02cf)` 就在 `:128`）。
- 防"顺手改了别的设置"：`core.verify_preservation(before, after, expected)` 要求**除预期项和两类运行时计数器（`0x01070000`、`0x02780000`，增量 ≤1e6）外没有任何属性变化**，否则报"發現額外設定變動"（`core.py:102-113`，计数器容忍函数在 `core.py:93-101`）。

### 1.7 超时 / 重试 / 错误语义

| 机制 | 数值 | 出处 |
| --- | --- | --- |
| 每次 `call()` 重置的总预算 | **180 s**（认证阶段 20 s；RecoverySession 先 30 s 再 180 s） | `transport.py:63,265,287,363,374` |
| 有界超时实现 | `Bounded.timeout()` = 剩余 ms，`max(1,min(left, t or budget*1000))`；耗尽 → `TimeoutError('相機操作超出有界等待時間')` | `transport.py:66-71` |
| 初始化独立后端 | 60 s 预算、单次读写默认 5 s；libusb `backend_error_code==-9`(STALL) → `GenericUsbException('Initial USB endpoint stalled')` | `transport.py:99-119` |
| TUR 就绪 / Sony busy | 30 s / 10 s，轮询 1 s | `transport.py:88-90,132,153` |
| 结束（尾）包等待 | ≤1 s（仅当分片长度是 512 倍数） | `transport.py:26-31` |
| 会话失败后 | `healthy=False` → 后续命令全部拒绝（"會話結果未知，停止後續命令"），绝不重放写 | `transport.py:317-321`；`AGENTS.md:35-36` |
| 允许重试的状态 | TUR 的 becoming-ready/attention sense；Sony `DeviceBusy(9,0x81,0x81)` | `transport.py:137-145,167-170` |
| 已知 USB 陷阱 | 认证后重枚举 0D68/096F；macOS 需先卸卷再 claim；Windows 两个身份都要 WinUSB/libusbK/libusb0 | `transport.py:207-209`、`macos_host.py:99-140`、`platforms/usb_drivers.py:1-4,205-208` |

---

## 2. 身份、握手与主机侧要求

1. **进服务模式不用按键/菜单**：只要 MSC 身份在位，工具在 `0E8A` 上做一次 vendor request + AuthPacket 挑战，相机就换到 `0336`（README："`0336` … 软件认证之后才出现"；`transport.py:265-270`）。相机显示"请检查所连接的设备"属正常。
2. **`SonyExtCmdCamera` 调用链**（只在 0E8A/MSC）：`get_device(0x0e8a) → MscBbbDriver(_InitialBackend) → MscDevice.getDeviceInfo()(SCSI INQUIRY) → SonyExtCmdCamera(SonyMscExtCmdDevice).getCameraInfo() → ExtCmd(1,1)`（`transport.py:173-186`）。它**刻意不作为服务 gate**：`AGENTS.md:43` 原文 "Do not make TUR readiness or getCameraInfo prerequisites, or substitute a HASP hash"。旧 CLI 反而把 `len(camera.readHasp())!=88` 当 gate（`src/fl23/transport.py:120-123`）。
3. **机身绑定两种**：
   - 服务侧：`service_identity()` = BK4 chip0 属性 `0x00e70003` 的 4 字节 raw → `.hex()` → `sha256(ascii)`（`transport.py:197-207`，注释说明是为了兼容老工具已有的按机身备份）。
   - 主机侧（新版桌面）：再读 USB 字符串 `iSerialNumber`（拒绝 `12345678` 等退化值，要求 ≥8 字符、不同字符 ≥2）并 sha256，**在认证之前**比对，防换机身（`usbidentity.py:4-25`、`devicesession.py:56-60`）。
   - `usb_startup_fix` 阶段（`transport.py:82-187`）明确：**只有认证前的信息查询**被加固，`SERVICE_DRIVER_SETUP` 是桌面端专用的可选驱动准备钩子（`transport.py:86-87`），CLI 不设置，也绝不重试认证或固件 I/O。
4. **需要 Windows 驱动配合**（`0E8A` 与 `0336` **都要**）：自动路径下载 libwdi（`WDI_URL` = `wdi-simple.exe`）+ UAC 提权装 WinUSB；已有 WinUSB/libusbK/libusb0 则沿用；卸载只碰 `054C:0E8A/0336`，卸载前备份驱动包（`src/desktopapp/platforms/usb_drivers.py:1-4,23,69-72,181-231,268-290,388-397`）。README 给了 Zadig 手动装 libusbK 的两阶段流程与设备管理器自检点（"libusbK USB Devices / ILCE-7CM2 / Sony USB Device"）。
5. **需要 macOS 配合**（不装驱动，但要 sudo 接管 + 卸卷）：`ioreg` 找相机卷 → `diskutil unmountDisk`（非 force）→ `detach_kernel_driver(0)` + `claim_interface(0)`（`src/camera_runtime/macos_host.py:46-140`）；每次相机动作通过为任务单独生成的终端脚本 `sudo` 以 root 重跑 worker（`docs/zh-CN/development.md:38`）。README：**Mac 实机 USB 尚未验证**。
6. **Linux**：`generic/libusb.py:70-75` 自动 `detach_kernel_driver`；仓库未在 Linux 上验收。

---

## 3. 写回机制（改什么、怎么写）

### 3.1 两个程序载体与读-改-写

- 名单与路径：`PROGRAMS=['appFw.so','cpapp-b.bin']`，映射 `(chip1→/cp/cpapp-b.bin, chip0→/usr/lib/appFw.so)`（`core.py:18`；`app.py:110,161,238`；`looktool/checkpoint.py:15`）。
- 大小：`static const u64 file_sizes[]={99960744UL,18090880UL};`（`native/patch_manifest.h:83`）→ appFw.so ≈95.3 MiB、cpapp-b.bin ≈17.25 MiB。
- 读：`session.read('/tmp/jiritsu/../..'+path)` → Jiritsu cmd15(select)+17(read)，Senser 按 1MB 分帧拉整文件。
- 改（主机离线）：`core.patch_program(original, chip)` 按 `assets/patches.json` 的 `{file_offset, before_hex, after_hex}` 窗口打补丁：要求 `before` 精确匹配、`len(before)==len(after)`、窗口排序后不重叠、总长不变（`core.py:53-71`）。
  - **chip0（appFw.so）8 个窗口**：`0x3528804`(112B "ordinary look to CP mode converter")、`0x4b2ed19`(2B 两个选择能力)、`0x4b3b544/0x4b3b54c`(4B FL2/FL3 factory Fade 默认)、`0x4b4a5e4/0x4b4a5ec`(4B 槽16/17 初始绑定)、`0x59892ca/0x5989382`(2B FL2/FL3 菜单产品标志、live column9)（`src/camera_runtime/assets/patches.json`）。
  - **chip1（cpapp-b.bin）32 个窗口**：`0x20140` initialized-data length、`0x138814/0x13882e`(FL2/FL3 still 参数 55/56)、`0x138832`(26B movie-only gamma 模式归一)、`0x323172/0x323298`(8B movie gamma guard)、`0x3231da/0x3231de`(mode table)、`0x32325c/0x323278`(gamma exclusive upper bound)、`0x32345a/0x323464/0x323d82/0x323d8a/0x323dd0/0x323dd8/0x323eb6/0x323eba`(gamma table 地址高低)、`0x64909e`(matrix parameter bound)、`0x6492f6`(16B strict primary chroma whitelist)、`0x649332`、`0x649652`(26B secondary chroma whitelist)、`0x6496b4`、`0x9cf404/0x9cf436/0x9cf43e`、**`0x1100b80`(3872B 四条适配曲线记录 + gamma rows + mode table)**、`0x148e5e`(142B MakerNote 0xb020 names + ColorMode helper)。
- 写（在相机里执行）：原生 worker `installer.c`，`static const u32 window_count=40;`（`patch_manifest.h:82`）：
  - 全部用 AArch64 `svc` 系统调用（`sc()`；`open=56, close=57, read=63, write=64, mount=40, fdatasync=82, pread=67, pwrite=68, stat=80, geteuid=175, getpid=172, unlink=35`）（`native/installer.c:5-8`）。**没有 libc、没有 shell、没有 reboot**。
  - 前置：`/proc/mounts` 里 **`/dev/nflasha15 /usr ext2 ` 必须是 `ro,`，且只允许出现一条**（否则 `-30`/`-22`）（`installer.c:67-83`）→ 同时证明"这是同一个 /usr"且"相机处于只读挂载的冷启动状态"。
  - `inspect()`：`O_RDONLY` 打开 → `stat` → 必须**普通文件**（`(mode&0170000)==0100000`）且大小完全相等；写阶段重新 stat 并要求 **`st.ino`/`st.dev` 与初始一致**（否则 `-116`）→ 因为用 `pwrite` 原地改，**不换 inode、不 rename**，运行中已 mmap 的引用不会被撕掉（`installer.c:84-92`；两文件路径由 `installer.c:38` 的 `path(i)` 硬编码：`i?"/cp/cpapp-b.bin":"/usr/lib/appFw.so"`）。
  - 事务顺序（`installer.c` 的 `work()`）：`mount_state(1)`（ro）→ inspect → 校验 before（哈希或逐窗口）→ 若 mode=0 直接结束（**零写入预检**）→ `remount(0)`（rw，syscall mount，flags `0xc30`/`MS_REMOUNT`）→ 重新 inspect + inode 核对 → `patch(after)`（逐窗口 `pwrite` + `fdatasync`）→ `verify_windows(after)`；**任何失败 → `patch(..., reverse=1)` 逆序把 before 写回**（`r.rollback` 记录）；`_init` 尾部无论成败都 `remount(1)` 恢复 ro，并把 `r.readonly` 记录，还会 `unlink("/tmp/jiritsu/libJit.so")`（`installer.c:123-153` 的 `work()` + `installer.c:154-165` 的 `_init`，其中 `:157` 就是清理 libJit.so）。
  - 报告 `A7IRP001`：`phase, writes, status, rollback, remount, readonly, cleanup, euid, pid, ap_inode, cp_inode, ap_size, cp_size, before_hash[2][32], after_hash[2][32]`（`installer.c:30-36`）。主机 `core.parse_native('installer', raw, mode)` 断言 mode/`window_writes`/before/after 必须等于 `ORIGINAL`/`FINAL` 常量组（`core.py:13-17,115-156`）。新版编译成 `BYTE_WINDOWS_ONLY` 时 worker 只做逐窗口校验，**整文件读回仍由主机强制**（`installer.c:4-5,111-114` + `app.py:158-170`）。
  - **mode 0 = 只校验（零写）、1 = 安装、2 = 恢复原厂**（`installer.c` 顶部注释；`app.py:147-150,222-228`）。
- 触发方式：先 `temp('<staged>.so', blob)` 写入并读回验证（**提前发现 USB 不稳定**），再 `temp('libJit.so', blob)` —— **写 libJit.so 这一步就是"执行"**，随后 `read('/tmp/jiritsu/<result>')` 取报告（`app.py:32-88`；`looktool/devicesession.py:153-193`）。相机端 SET_FILE2 落 `libJit.so` 后由 Jiritsu 自己 `dlopen`（worker 导出 `_init` 作为入口，跑完 dlclose）。一代同样有这套加载器（§5.2），但入口符号是否也是 `_init` 待实测【推测：一代同区段出现 `MAIN()` 字符串，可能要求 `MAIN`】。

### 3.2 原生 worker 家族（都以 libJit.so 形式在相机里跑）

| worker | 报告 magic | 作用 | 关键前置/后置 |
| --- | --- | --- | --- |
| `installer.c` | `A7IRP001` | 固定窗口原地改两个程序文件（可装/可恢复） | /usr 必须 ro；文件类型/大小/inode 不变；失败逆序回滚；结束恢复 ro；euid 必须 0 |
| `probe.c` | `A7PRB001` | 只读诊断：`/proc/self/{maps,mounts,cmdline}`、**model index**（二代钉死 `16`）、`/usr` 是否 ro | 读截断即报错，不接受部分解析；不改任何东西 |
| `wbi.c` | `A7WBR001` | 要求 `/sys/power/image_mode == "2\n"`、`/sys/power/image_dev == "*wbi4\n"`；mode1 时写 `image_drop='1'` 再 `image_mode='0'`，并从 `/dev/kmsg` 找 `"dropped wbi"` | 只有 euid=0 才写；不 reboot；读回必须 `image_mode=="0\n"`（`wbi.c:39-58,71`） |
| `runtime.c` | `A7RUN001` | 只读比对 6 个 AP 区域在**进程内存**（`/proc/self/mem`，`base+offset`，`offset>=0x51a7718` 再加 `0x10000`）与**磁盘** `/usr/lib/appFw.so` 的字节；另读 `image_mode/image_dev/uptime/boot_id` | 用来证明"新代码确实已加载"和"确实冷启动过" |

6 个 runtime 区域：`offsets={0x3528804,0x4b2ed19,0x59892b8,0x5989370,0x4b4a5e4,0x4b3b544}`，`lengths={112,2,40,40,12,12}`（`native/runtime.c:13-14`）。
WBI（暖启动/休眠镜像）是 Sony 平台机制：一代更新器里就有 `updater.img_unpacked/bin/ud_wbi_drop.elf`（`UPDATER_ANALYSIS.md:108,220` 记录了 `us_mkfs.sh` 调用它）→ 机制同源，sysfs 路径待实机确认【待验】。

### 3.3 LUT / look 表是什么、写到哪里

- **自定义创意外观 1–6 的机内色表**：在 `cpapp-b.bin` 文件偏移 **`TABLE_FILE=0x8000`**，头 `'A7L6'`(MAGIC `0x364c3741`) + `VERSION=0x10006` + 6 个 FNV-32 校验（`TABLE_FILE+8+i*4`），随后 6 段各 **`TABLE_BYTES=1215` 字节**（RAM `PREFIX_VA=0x110000`、`TABLE_VA=0x110020`）（`src/looks/looktool/six.py:9-14, 27-47`）。
- **表怎么被引用**（都在 `appFw.so`）：`0x35287f0:0x3528874` 放"转换器模板"（多选一，来自 `assets/runtime-v1.json` 的 `ap_templates`，掩码决定哪 6 槽走 LUT）；`0x59896f0 + i*0xb8` 写标签 ID（`0x0200ab2c + i`）；`0x1b5cd7c` 标题分支；`0x4c7cf7c` 映射表（`src/looks/looktool/device_layout.py:18-25` 的 `_ap_target`；`device_layout.py:88-104` 的 `structural_ap`）。
- **机内名称（外观显示名）不是程序字节**：是 `/usr/share/app/` 下 **68 个 `string_*_(horizontal|vertical).uxc`** 资源里的条目（`nameworker.filenames()` `nameworker.py:10-14`；读写路径 `checkpointjob.py:93,106`、`devicejob.py:166`、`namespause.py:74`）。原生 names worker 先写 `.a7c2-lut-<16hex>-<名>.original/.stage` 备份再原子替换，并钉死原 owner `uid=57285, gid=1000`（`nameworker.py:44-48`）。已知坑：旧任务残留 68 份副本 >60MB → `/usr` ENOSPC；相机运行时旧资源仍被映射 → 名称写入可能停在 `AWAITING_RESOURCE_RELOAD`（changelog 3.0.1/3.0.2、`direct.py:257-271,467-497`）。
- **FL2/FL3 的颜色来源**：从 **ILCE-FX2 1.01 的 CP 色彩单元**移植（`assets/manifest.json` 的 `colour_donor`），每款 48 个色槽（3 光源端点 × 16 色相扇区，每槽 12B 六系数）+ 3 组 CC1 差分 + 4 条 gamma 记录（`gamma_fill`/`gamma_route`/`gamma_movie_row`）。校验：每个 12B 槽展开后 3x3 行和必须 == 1024，且必须逐字节等于供体 `assets/fx2_fl23_donor.json` 的目标值（`core.py:162-192` 的 `colour_record`、`core.py:157-161` 的 `slot_row_sums`）。写入位置在 CP 色彩单元：`0x02a40001` 的 `0x1200+parameter`（映射）与 `0x1250+slot*64`（64B 色度记录）；`0x02a4000d` 的 `0x196+parameter` 与 `0x1e0+slot*768`（576B 矩阵）（`core.py:72-92,193-224`）。FL2/FL3 用"参数 55/56、色彩槽 23/25"（`COLOUR_SLOTS` `core.py:21`）与 CP mode 19/20（manifest `gamma_route`）。
- **另有一套 "native photo" 曲线族**：`cpapp-b.bin` 偏移 `0xb27590` 起的 gamma/代码区（`photobuild.py:11-19`），把原生 ST 双域表复制到已退休的数组区并追加 Thumb 代码，与 `six.py` 的 0x8000 表并存。

### 3.4 `layout.py` / `backup.py` / `compat.py` 到底是什么（避免误读）

- `src/fl23/layout.py`：**只是主机侧目录约定**（`workdir/<时间戳>-<机身短码>`、`backup/<机身短码>`，会话内含 `original/ candidate/ readback/ evidence/`）——**不是相机内存/分区布局**。相机侧布局在 `assets/patches.json` + `core.patch_program` + `src/looks/looktool/device_layout.py`。
- `src/fl23/backup.py`：**备份库三层校验**（文件文档 1-11 行）：①清单每文件 SHA-256 一致；②两个程序必须等于 `core.ORIGINAL`（原厂 2.01 哈希，`core.py:14-15`）；③设置里没有本工具痕迹（`0x02cf1287/1289` 必须空、FL2/FL3 参数映射与目标色彩槽必须空）。只有三层全过才允许"还原/安装"。
- `src/camera_runtime/compat.py`：对**非本仓库来源**的固件做**指令边界级**兼容判断而非整机哈希白名单：识别 `ap[0x35287f0:0x3528874]` 模板是否在已知 LUT 运行时模板集合内（或等于 `LEGACY_CONVERTER` 常量），据此跳过/替换对应窗口；CP 侧允许历史上发布过的原生 FL23 取值并存（`compat.py:22-63`）。文件头明确警告：**不验证固件来源，非本仓库改过的固件可能与 FL23 冲突，造成相机无法正常启动**（`compat.py:8`）。
- 新版桌面（`looktool/direct.py`）**不再强制完整机身备份**：靠事务日志 + 精确字节读回 + checkpoint zip（两程序 + RAM/saved 设置 + 68 名称资源，`checkpoint.py:15-17,34-55,75-80`）；`AGENTS.md:20-31` 明确"不要把这些 GUI 动作重新塞回备份目录"（`:24`）。旧 CLI（`FL23.cmd`）仍是"必须有已验证备份"的独立契约（`AGENTS.md:62-70`，其中 `:66` 要求两份独立备份）。

### 3.5 哪些改动必须取电池冷重启

- **两个程序文件的任何窗口改动**：必须冷启动。原因：相机用 WBI 暖启动镜像（`image_mode=2`）复用旧 RAM，"内核开机"不等于 CP 内存已换（`AGENTS.md:52`："A kernel boot is not proof ..."）。核对靠 `runtime.c` 比对内存与磁盘 6 区域，不符就报"執行期仍有舊資料；請確認已關機並取出電池後再開機"（`app.py:250-256`）。
- **名称资源 `/usr/share/app/*.uxc`**：也要重开（旧文件仍被映射；可能 ENOSPC/EBUSY → 阶段 `AWAITING_RESOURCE_RELOAD`）。
- **AP/CP 设置（外观绑定、色彩单元）**：`saveBackup` 后需重载才在菜单/拍摄生效；工具仍在同一次安装末尾跑 `wbi mode=1` 丢快照并统一提示断电重开（`app.py:222-231`）。
- **冷启动证明**：`verify_direct` 要求 `boot_id` 变化，原厂恢复还要求 `/usr` 处于 ro 挂载（`direct.py:714-728`）。

---

## 4. 防砖设计

1. **备份了什么**
   - 旧 CLI：`appFw.so.bin`、`cpapp-b.bin.bin`、`backup.private.bin`（BK4 RAM）、两个 `unit-02a4000*.bin` 色彩单元；**写到两个互不包含的独立目录**，每个文件写完立即读回比对（`app.py:90-134`；`src/fl23/layout.py:15-26,32-58`）。备份必须过"原厂性 + 未打补丁"三层校验（§3.4）。
   - 新版：`checkpoint.private.zip`（两程序 + RAM/saved 设置 + 68 个名称资源），写完立即解压读回比对，并再拷一份到第二目录（`checkpoint.py:33-52,75-79`；`app.py:120-128`）。
   - 证据落盘：写前后 BK4（RAM/saved）进 `evidence/`，读回程序进 `readback/`（`app.py:158-170,171-206`）。
2. **写前检查**
   - 只读 `probe`（model index、/usr ro）+ `installer mode=0`（零写入校验）（`app.py:147-150`；`direct.py:426-449`）。
   - 重新核对机身设置没被第三方改动、色彩单元仍等于准备时读到的原厂值（`app.py:110-115,218-221`）。
   - 供电确认：只接受 50–100% 报告值或显式确认（`looktool/power.py:4-10`）。
   - **`/tmp/jiritsu/` 里不允许有遗留临时文件**（worker/request/result 名都在白名单内），有则停止，不盲目重跑（`app.py:48-54`；`devicesession.py:153-159`）。
   - **`/etc/ld.so.preload` 必须不存在**：`session.read('/tmp/jiritsu/../../etc/ld.so.preload', True)`（`app.py:54`；`devicesession.py:146,159`）。原因:本工具**不用 preload**,用的是 Jiritsu SET_FILE2 的原生 `libJit.so` dlopen 入口(`native/probe.c:2-4`;`docs/zh-CN/notices.md:30`:参考项目 `a7c2-service-preload` 用"预载配置或会改时钟的 DEBUG 命令",本工具刻意不用)。preload 是**每次开机都生效的持久配置**,若相机上已存在(别的工具留下的),叠加后下一次开机行为不可预测、且失败直接开不了机 → 停下来而不是继续。清理遗留 probe 报告时也要求“没有 preload”（`devicesession.py:131-147`）。
3. **写后校验**：worker 内 `verify_windows(after)`；主机再**完整读回两个文件逐字节比对候选**（`app.py:159-171`，不符即"停止後續操作"）；设置逐个读回 + `saveBackup` 后再读回（`app.py:171-206`；`saveBackup(0x02a4)` 在 `:190`、`saveBackup(0x02cf)` 在 `:196`）；`verify_preservation()` 证明没有额外属性变化（`core.py:102-113`）。
4. **失败恢复**
   - worker 内部：失败即 `patch(reverse=1)` 逆序回滚 + 强制 remount ro，`r.rollback`/`r.readonly` 单独记录（`installer.c:145-152` 与 `_init` 的 `installer.c:154-165`）。
   - 主机：**结果未知绝不重试**（`AGENTS.md:35-36`；`transport.py:317-321`）；中断后"从相机当前字节重新规划"续接（`direct.py:370+`；README「安装或恢复中途断了：再点同一个按钮」）。
   - 恢复原厂**不需要旧备份**：内置 `src/looks/assets/factory-regions-2.01.json` 只含本项目改过区域的原厂字节（`docs/zh-CN/development.md:86`）；`installer mode=2` 就是内置原厂窗口。
   - 名称写入失败/空间不足有独立续接阶段与清理（`direct.py:257-271,523-571`）。
5. **绝不做的事**（`AGENTS.md:33-60` + 代码约束）：不写裸 flash、不写任意机内文件（Jiritsu 写只限 `/tmp/jiritsu/*`）、不改进程内存、不 spawn shell、不 powerOff/reboot、不删不认识的用户文件、`/usr` 平时保持 ro、不重复结果不明的写。
6. **风险记录**：仓库没有变砖报告；最接近的是 `compat.py:8` 的警告与 `AGENTS.md:57`（撤回过的通知改动、失败的显示/图标方案）、`AGENTS.md:84-95`（离线证据不能证明能安全开机；Mac USB 未验证）。README「验证状态」：只在作者一台 A7C II + Windows 上通过实机写入/读回/重开核对。

---

## 5. 对 A7C 一代（ILCE-7C, v2.00, CXD90045）的可迁移性

### 5.1 映射表

| 项目 | 二代工具里的取值 | 一代可见证据 | 判定 |
| --- | --- | --- | --- |
| Senser 认证（`0x37ff/0xd7aa`、`0xc800/0x2855`；坏 SHA1 / SHA256 + PMCA key；0336 用全 challenge、0E8A 用 `data[:4]`） | `vendor/pmca/usb/sony.py:891-937` | 一代有 `bin/sen.elf`（`SENSER CORE module start/stop failed!`、`senser_usb_mode_start`、`senser_normal_mode_start`、`/var/.sen/.smode`、`/boot/sen/smode`、`/setting/sen/smode`、`/setting/.hasp`，偏移 14059–14683） | **大概率可搬**【推定】；challenge/keys 是 PMCA-RE 跨机型常量 |
| Senser 帧（12B 头 / 1MB 分块 / sequence / 512 尾包 / 0336 的 minSize=0） | `sony.py:823-875` | 一代有 senser 服务端（`sen.elf`） | **大概率可搬**【推定】；尾包与最小包行为需实测 |
| Jiritsu 文件命令 15/16/17/18 | `transport.py:322-341` | 一代 `libJiritsu.so` 有 `adj_cmd_set_file_path`(7277)/`adj_cmd_set_file2`(7492)/`adj_cmd_get_file2`(7556)/`cmd_file_delete2`(7539) + 同一顺序名字表（41409/41431/41449） | **可搬**【推定，证据强】；64KB 上限、状态码 `0x10000006` 待实测 |
| 一代额外命令 | 工具未用 | 10=GET_FILELIST、11=GET_FILE_HASH(md5)、12=COMPARE_MEDIA、`cmd_high_capacity_get/send_file`(7698/7823) | 待验；可能比"读整文件"更好用 |
| `/tmp/jiritsu` 目录 + JIT 加载器 | `/tmp/jiritsu/libJit.so` 执行原生 worker | **一代 `libJiritsu.so` 里就有** `/tmp/jiritsu/libJit.so`(39434)、`/tmp/jiritsu/ramdsk_libJit/libJit.so`(168041)、`/tmp/jiritsu/jit.log`(39457)、`/tmp/jiritsu/tmmc.jit`(39390)、`jit_thread`(6290)、`jit_exit`(167528)、`"libJit.so crashed."`(167891)、`"Recovery mode execute."`(167910)、`dlopen/dlclose/dlsym`(7416/7423/8131) | **可搬**【推定】；入口符号 `_init` vs `MAIN()`(167626) 待实测 |
| `/usr` = `ext2` on `/dev/nflasha15`、写前必须 ro | `installer.c:67-83` | 一代包里有 `0700_part_image/dev/nflasha15`(239,982,592B) 与解包 `/usr` 树；`UPDATER_ANALYSIS.md:41` 列 4 分区（nflasha3/5/7/15） | **同名可用**【推定】；一代 `config/mount.conf`/`partinf.conf` 应核对 |
| 载体 `/usr/lib/appFw.so`（99,960,744 B） | `core.py:18` | 一代 nflasha15 解包（941 文件）里**没有 appFw.so 文件**；只有 libIMDB.so / libObj.so 的字符串引用 `"appFw.so"`（在 raw 镜像偏移 `0x564ee5`、`0x1d2c81c`）；`bin/change_mode.sh` 有 "…→ appFw boot" 层级说明 | **路径名可能同名但不可照搬大小**；要实机用 Jiritsu 枚举确认（一代解包 `/usr` 最大文件是 `libObj.so` 21 MB） |
| 载体 `/cp/cpapp-b.bin`（18,090,880 B） | `core.py:18` | 一代解包里没有 `cpapp-b.bin`，也没有 `/cp` 挂载痕迹；与 `FIRMWARE_MOD.md:159-160,255` 结论一致 | **不可照搬**；需定位等价物（候选 `libObj.so`、`bin/im.elf`、`codec/*`、`kmod`、未在包内的 cpapp 镜像） |
| 全部 40 个补丁窗口偏移 | `assets/patches.json` | 一代固件不同版本/机型编译 | **完全机型专属，必须重新逆向**（可复用本仓 QEMU/Keystone/`tools/`） |
| 属性/槽位取值 `0x02a40001/02a4000d`(8192/28672B)、`0x02cf1287/1289`、参数 55/56、槽 23/25、CP mode 19/20 | `core.py:19-21` | 一代有 `lib/libInfraCameraProfile.so`、`bin/adjstctl.elf`（AdjustControl 客户端，含 `A_ACC_ADJUST`、`@DIAG_READ_ADJUST`） | **机制可搬、取值待重取**；先读 BK4 全属性并 diff |
| BK4 结构 + 序列号属性 `0x00e70003` | `core.py:43-51`、`transport.py:197-207` | 一代有 `kmod/backup.ko`、`bin/bk.elf`，更新器 `ud_keep_backup.elf`/`/setting/Backup.bin`（`UPDATER_ANALYSIS.md:54,108`） | **机制可搬**【推定】；`0x00e70003` 在一代是否仍是序列号，需读 BK4 + 与 USB 序列交叉验证 |
| 名称资源 `/usr/share/app/*.uxc`（68 个） | `nameworker.py:10-14` | 一代确有 `nflasha15_unpacked/share/app/`（302 文件：`color_cmn.uxc`、`image_cmn_43.uxc`、字体等） | **路径可搬、清单/条目数不同**（一代要自己枚举 `string_*.uxc`） |
| 快门声 `/usr/share/avsystemsound/` | `src/shutter_sound/*` | 一代有 `nflasha15_unpacked/share/avsystemsound/` | 路径在，字节补丁需重做 |
| WBI（`/sys/power/image_mode|image_dev|image_drop`） | `native/wbi.c` | **`updater.img_unpacked/bin/ud_wbi_drop.elf` 存在**，`us_mkfs.sh` 会调（`UPDATER_ANALYSIS.md:108,220`） | **机制可搬**【推定】；sysfs 路径/取值待实机确认 |
| 两个 USB 身份 PID | `0E8A`(MSC) / `0336`(Senser) | 一代包里未见 PID 文本常量 | **待验**：先枚举一代 MSC 模式的实际 `054C:xxxx`，再看认证后是否变 `0336`（`0x02a9` 也是 Sony 老 senser PID，`sony.py:31`） |
| Windows 驱动（两身份都要 WinUSB/libusbK）/ macOS sudo+卸卷 | `platforms/usb_drivers.py`、`macos_host.py` | 只与 VID/PID 相关 | **可搬**（改 PID） |

### 5.2 一代固件里 Jiritsu 通道的直接证据（本笔记最有价值的一节）

文件：`firmware.tar_unpacked/0700_part_image/dev/nflasha15_unpacked/lib/libJiritsu.so`（174,816 B；下面是 `strings -a -t d` 的**文件偏移**）

```
7277  adj_cmd_set_file_path      39228 "adj_cmd_set_file_path: Request raw data size error.(max_size:%d)"
7492  adj_cmd_set_file2          39861 "adj_cmd_set_file2: file size over err size = %u"
                                 39909 "adj_cmd_set_file2: directory create error."
                                 40017 "adj_cmd_set_file2: write err fd_mem = %d"
7539  cmd_file_delete2           7556 adj_cmd_get_file2      7603 adj_cmd_get_file_list
7801  adj_cmd_get_file_hash      41014 "…: file non-existent"
7698 / 7823  cmd_high_capacity_send_file / cmd_high_capacity_get_file
7416 / 7423 / 8131  dlopen / dlclose / dlsym
39390 /tmp/jiritsu/tmmc.jit   39434 /tmp/jiritsu/libJit.so   39457 /tmp/jiritsu/jit.log
167528 jit_exit   167778 jit_thread:   167738 /tmp/jiritsu/ramdsk_libJit
167872 /tmp/jiritsu/jinit   167891 "libJit.so crashed."   167910 "Recovery mode execute."
168033 size=1M   168041 /tmp/jiritsu/ramdsk_libJit/libJit.so   167626 MAIN()
41169–41488 JIRITSU_MODE / MOUNT / FORMAT / START / DEBUG / FIRMUP / SET_FILE / GET_FILE /
            FILE_DELETE / GET_FILELIST / GET_FILE_HASH / COMPARE_MEDIA / GET_VERSION /
            FACTORY / SET_FILE_PATH / SET_FILE2 / GET_FILE2 / FILE_DELETE2 / TEST_UI_VIEW
其他文件操作：sys_file_create/create2/create3、sys_file_chk_exist、sys_file_remove(2)、
            sys_file_copy、sys_file_md5hash、mode_file_write、get_jiritsu_area_filename
其他 /tmp/jiritsu 内容：ver.txt、DIAC.csv、history.txt、jcount、ramdsk/jiritsu.dat、
            Cam_AdjustGuide_Files/Req_Files/REQ_*.bin（原厂调参流程）
jmode 相关："cmd_start: jmode err not Manual" / "JMODE_OPEN_FAIL" / "not jmode" / "have jmode"
          → 文件命令要求相机处于 jmode（服务/手工模式）
"/bin/sh"、"/bin/tar xpf %s ./ -C %s"、"/bin/date -s %02d%02d%02d%02d%04d.%02d"
```

另有 `bin/adjstctl.elf`（AdjustControl 命令行客户端；名字表在 109771–110995，含 `@JIRITSU_SET_FILE2 / @JIRITSU_GET_FILE2 / @JIRITSU_FILE_DELETE2 / @JIRITSU_GET_FILELIST / @JIRITSU_GET_VERSION`，以及 `adjust block: 0x%04x, code: 0x%04x OSAL ID: 0x%08lx cmdname: %s` 这个格式串 → 说明 AdjustControl 就是 (block,code) 二元组，与 §1.3 一致）和 `bin/sen.elf`（senser 守护进程）。

**含义**：A7C 一代的机内服务侧**已经实现了与二代工具完全对应的文件命令 + libJit.so 原生代码加载器（甚至带崩溃后 "Recovery mode" 处理）**。移植工作量的大头不是协议，而是：
1. 一代的实际 PID 与握手行为（认证 ret 序列、challenge 长度）；
2. 一代的"程序载体"定位 + 补丁窗口（全新逆向）；
3. 一代 BK4 属性映射（外观绑定、色彩单元、序列号）与 `0x1001` 命令的状态码字典；
4. 一代 `/usr` 空闲空间与名称资源清单（`FIRMWARE_MOD.md:175` 记 300MB /usr、约 56MB 空闲）。

### 5.3 一代可能的额外入口（待验）

- `bin/sen.elf` 里的 `/boot/sen/smode`、`/setting/sen/smode`、`/var/.sen/.smode`、`/setting/.hasp`；`UPDATER_ANALYSIS.md:108` 记录 `us_mkfs.sh` 会写 `/setting/sen/smode = "UU"` → 一代可能用**文件旗标**打开 senser/服务模式（不依赖认证）。
- `libJiritsu.so` 的 `cmd_start: jmode err not Manual` 说明文件命令要求 jmode=Manual；`change_mode.sh` 里还有 `/setting/mode/dmode`、`/setting/mode/preload`（启动层级：kernel → global infra → LIRO → **appFw boot**）→ 一代同样存在 "appFw" 这一层应用进程，只是二进制不在本包里。
- 一代 Jiritsu 自带 `/bin/sh`、`tar`、`date -s`（DEBUG 改时钟）能力 → 若走这些通道要注意时间/副作用（二代工具刻意避开）。

---

## 6. 实机操作清单（README / development.md / changelog）

### 6.1 准备
- 机型/版本硬限制：只支持 `ILCE-7CM2` + 2.01；README:12 明文写“其他机型（包括**初代 A7C**、A7CR、A7R V…）都不能使用，程序会拒绝连接”；代码层 gate 是 `core.py:12-13`（MODEL/VERSION）与 `compat.py:22`。
- 电池 ≥50%，每次写入前弹窗确认供电（README:84；`app.py:215-216`、`looktool/power.py:4-10`）。
- USB 线直连电脑（不经过 Hub/扩展坞，台式机用后置口），一次只连一台（代码要求"有且只有一台"目标 PID，`transport.py:73-80`）。
- 相机菜单 USB = **海量存储 (Mass Storage)**。
- 出现"请检查所连接的设备"、电脑看不到盘符 = 正常，一切以软件日志为准（README）。
- **显示"正在执行"时不要拔线、关机、关软件**；打开软件本身不连接相机（README；`AGENTS.md:38`）。

### 6.2 第 1 步：驱动（Windows）
1. 「连接与驱动」→「检测相机与驱动」应看到 `054C:0E8A`。
2. 「准备两阶段驱动并测试连接」：先给 `0E8A` 装驱动 → 让相机进服务连接 → 等 `0336` 出现 → 给 `0336` 装驱动；会弹 1–2 次 UAC；已有 WinUSB/libusbK/libusb0 会沿用。
3. 日志出现「服务连接成功，驱动准备结束」即完成（**不写相机**）。
4. 推荐先做「检测 USB 连接稳定性（只读）」：**≥120 秒、≥5 轮（上限 60 轮）**，同一会话里反复完整读 `/usr/lib/appFw.so` 与 `/cp/cpapp-b.bin`，每轮与第一轮逐字节比对；速率 <2 MB/s 判失败（USB 1.1/Hub/线材）；读挂住由传输超时兜住判失败（`src/desktopapp/usbcheck.py:14-19,39-58`）。每轮约 112 MB。
5. 驱动出错 → 先「卸载相机驱动，恢复 Windows 默认连接」（只处理 `054C:0E8A/0336`，卸载前备份驱动包）→ 拔线重插 → 回到第 1 步；仍不行用 **Zadig 手动装 libusbK**（两个身份都要装：`List All Devices` → 选 `ILCE-7CM2`(054C 0E8A) 与 `Sony USB Device`(054C 0336) → 驱动选 libusbK（失败改 WinUSB）→ Replace/Install Driver，等 1–2 分钟）→ 然后**拔 USB + 关机 + 取电池约 1 分钟** → 再测一次连接。

### 6.3 第 2 步：装过旧版本 → 先恢复原厂
1. 相机上把创意外观切到 **ST**。
2. 「恢复原厂功能」→「恢复／继续恢复原厂 2.01 功能（无需旧备份）」：内置原厂区域数据，保留机身校准/计数器/无关设置。
3. 写入 + 完整读回后弹窗提示"恢复尚未完成" → 断电重开 → 开机确认能取景。
4. 接回 USB（海量存储）→「重启后核对并完成恢复」；通过后才显示完成并清除旧安装状态。
5. 警告：恢复会把自订 1–6 全部设为 ST，**旧配方找不回**。中途断了再点同一按钮会从当前状态续接；按钮若显示「断电后重试恢复（本次尚未写入）」→ 按提示断电再点。

### 6.4 第 3 步：安装（以 FL2/FL3 页为例，三段式与旧 CLI 一致）
- 旧 CLI 契约：`FL23.cmd` 只有 `prepare / install / verify`（`AGENTS.md:64`；`src/fl23/workflow.py:136` 状态核对、`:303` install、`:345` verify；备份流程 `:152-208`）：
  - `prepare`：备份两程序 + 本机设置 + 色彩单元（两份独立目录）→ 校验备份是原厂未打补丁 → 生成候选 → `probe` → `installer mode=0` → `wbi mode=0`（全部零写入/只读）。
  - `install`：再核对目标设置未变 → `wbi mode=0` → `installer mode=1`（写窗口）→ 整文件读回 → 写 CP/AP 设置并保存 → `wbi mode=1`（丢 WBI）→ 提示"拔线、正常关机，等存取灯熄灭后取出电池 10 秒，再装回开机"（`app.py:222-231`）。
  - `verify`（重开后）：读两程序比对补丁 + 读回设置 + `runtime` 比对内存/磁盘 6 区域。
- 桌面版：「一键安装」→ 确认供电 → 一次合并写入 + 完整读回 → 弹窗「读写已结束」→ 断电重开 → 接回 USB → 「继续安装」（核对新开机与加载状态，不重复写）→ 「安装完成」。
- 若提示"名称已写好，程序尚未写入"（`AWAITING_RESOURCE_RELOAD`）→ 断电重开 → 接回 → 仍点「继续安装」（名称不会重写）。

### 6.5 断电重开（关键，贯穿全流程）
README 原文步骤：①拔 USB 与其他外部供电；②等存取灯停止闪烁；③电源拨到 **OFF**，等屏幕与存取灯完全熄灭；④**取下电池，至少等 1 分钟**；⑤装回电池开机。"只关机再开机不算断电重开"。
（旧版命令行文案是"正常关机后取出电池 10 秒再开机"：`src/fl23/workflow.py:341,394`、`src/camera_runtime/app.py:230`；桌面版统一到 ≥1 分钟 —— 保守取 ≥1 分钟。）

### 6.6 卡住怎么办（README 常见问题 + 代码行为）

| 现象 | 处理 |
| --- | --- |
| 相机显示"请检查所连接的设备" | 正常，看软件日志 |
| 找不到 `054C:0E8A` | 没选海量存储 / 线不能传数据 |
| `0336` 一直不出现 | 软件冷却 30 s 自动重试，最多 3 次（`transport.py:210-212,249-282`）；仍失败 → 卸载/重装驱动或 Zadig |
| 认证后相机跳到回放、`0336` 不出现 | **换电脑 USB 2.0 口或换 USB 2.0 线/Hub**（部分电脑走 USB3 高速时相机不进服务模式） |
| `0336` 出现但接口打不开 | 驱动问题；软件**不会**重新认证（`transport.py:272-273`），人工卸载重装驱动 |
| 安装/恢复中断 | 再点同一个按钮，按相机当前字节续接；已完成部分不重写 |
| "结果未知"/"需要核对" | **不要重试写入**；导出诊断包（`NEEDS_REVIEW` 阶段） |
| 相机仍停在 `0336` | 提示拔 USB、关机、取电池约 1 分钟，再开机选海量存储重连（`devicesession.py:66-70`） |
| 听不到快门声 / 颜色与 DCP 不同 | 检查机内"音频信号"；颜色是拟合近似（README） |

### 6.7 耗时与验收状态
- 单次相机操作预算 180 s（认证 20 s；恢复会话先 30 s）；TUR 就绪 30 s；Sony busy 10 s；服务身份等待 20 s；会话冷却 30 s；Zadig 单次装驱动 1–2 分钟；USB 稳定性检测 ≥2 分钟（每轮约 112 MB）。
- README「验证状态」：FL2/FL3、六款外观安装、恢复原厂已在作者**一台** A7C II + Windows 上通过实机写入/读回/重开核对；自定义外观预览/拍照、临时试听同机测过；持久自定义快门声实机长期验证进行中；竖屏待验收；**macOS USB 未实机验证**。离线测试与字节读回不能证明能安全开机。

---

## 7. 证据索引

### 7.1 参考仓库（`refs/a7c2-fl23-research/`）
- `src/camera_runtime/transport.py`：`17-60` 有界尾包与 Senser 重写；`62-71` Bounded；`73-80` get_device；`82-90` 诊断类与常量；`99-119` 初始后端/STALL(-9) 处理；`121-187` 只读就绪 + Sony ExtCmd（`0x7a`、`(9,0x81,0x81)`）；`189-195` `identity()`；`197-207` `service_identity()`（`00e70003` + hexlified sha256）；`207-212` 0D68/096F 与冷却常量；`216-242` 等待/记录 Sony PID；`244-303` 会话时序；`304-316` 退出；`317-321` 结果未知；`322-341` jiritsu/select/read/temp；`342-351` cp_read/cp_write/ap_write；`353-380` RecoverySession。
- `src/fl23/transport.py:64-133` 旧版会话（`readHasp()==88`）；`150-183` 同一 Jiritsu 白名单。
- `src/camera_runtime/vendor/pmca/usb/sony.py`：`31` senser PIDs；`83-104` MSC ExtCmd `0x7a` + DeviceBusy；`147-196` ExtCmd 命令与头；`268-292` `getCameraInfo`；`821-835` SonySenserDevice 头与尺寸常量；`847-875` 帧收发（`:854` 0336 的 minSize=0）；`890-937` 认证（`:891-892` vendor request、`:925` challenge 差异）；`940-947` pFunc；`967-974` AdjustControl 命令；`990-995` `_sendAdjustControlPacket`；`1038-1056` Backup（`:1041` writeBackup、`:1044` saveBackup、`:1050` getBackupPresetData）。
- `vendor/pmca/usb/constants.py`（senserKeysSha1/Sha256）、`usb/crypto.py:38-40`（`sha1_faulty`）、`usb/__init__.py:32-57`（MscDevice/INQUIRY）、`usb/driver/generic/__init__.py:69-102,104-186`（bulk 端点、MscBbb）、`generic/libusb.py:26-32,63-105`（proto 判定、vendorRequest、detach kernel）。
- `vendor/pmca/backup/__init__.py:8-100`（BK4 头/校验/属性表）。
- `src/camera_runtime/core.py`：`12-23` 机型/版本/ORIGINAL/FINAL/PROGRAMS/KEYS/槽/NATIVE_PATHS；`43-51` BK4；`53-71` patch 窗口；`72-92` 色彩合并；`93-101` 计数器容忍；`102-113` 未变动校验；`115-156` 原生报告解析；`157-192` 色彩记录/行和；`193-224` 色彩写窗口与窗口外一致判定。
- `src/camera_runtime/app.py`：`32-88` worker 暂存/执行（`:48-54` 遗留临时文件与 `ld.so.preload`，`:69` 报告落 `evidence/`）；`90-153` prepare（备份、checkpoint、compat、probe `:147`、installer mode0 `:149`、wbi mode0 `:150`）；`158-170` 完整读回；`171-206` 设置写入与保存（`:173` AP 目标值、`:190` saveBackup(0x02a4)、`:196` saveBackup(0x02cf)）；`207-231` install（`:216` 供电、`:222` wbi0、`:224` installer1、`:228` wbi1、`:230` 10 秒文案）；`232-258` verify（`:249` AP 绑定、`:250` runtime、`:255` 旧资料）；`259-290` CLI。
- `src/camera_runtime/native/`：`installer.c:4-5,30-38,67-83,84-92,93-110,111-122,123-153,154-165`；`probe.c:1-4`（SET_FILE2 → dlopen/dlclose）；`wbi.c:39-58,71`（image_mode/image_dev/drop→mode0 + kmsg "dropped wbi"）；`runtime.c:13-14`（6 区域）；`patch_manifest.h:82-83`（40 窗口、99,960,744 / 18,090,880 B）。
- `src/camera_runtime/assets/`：`patches.json`（40 个 `file_offset/before_hex/after_hex` + purpose）、`manifest.json`（donor/gamma 说明、`hardware_scope`）、`patches`/`colors`/`fx2_fl23_donor.json`。
- `src/looks/looktool/`：`devicesession.py:6-10,101-116,120-128,131-193`；`usbidentity.py:4-25`;`usbservice.py:8-46`;`checkpoint.py:15-21,33-52,75-96`;`nameworker.py:10-14,44-48`;`direct.py:257-271,426-449,467-509,714-728`;`six.py:9-14,27-47`(`0x8000` `'A7L6'` 六表 + FNV);`photobuild.py:11-19`;`device_layout.py:18-25,88-104`;`power.py:3-10`。
- `src/fl23/`：`layout.py:1-7,15-26,32-58`；`backup.py:1-11,89-120`（三层校验）；`workflow.py:85-135,152-208,209-241,242-302,303-344,345-366,367-407`；`core.py:23`（NATIVE_PATHS）。
- `src/desktopapp/usbcheck.py:14-19,39-58`；`src/desktopapp/platforms/usb_drivers.py:1-4,23,69-72,181-231,243-257,268-290,388-397`；`src/camera_runtime/macos_host.py:46-140`。
- `AGENTS.md:33-60`（相机安全；`:35-36` 不重试未知结果、`:41` 服务入口与绑定、`:43` 不把 TUR/getCameraInfo/HASP 当 gate、`:51` 写后全量读回与 inode/mount 检查、`:52` 内核开机不等于 CP 内存、`:57` 已撤回方案）；`AGENTS.md:18-31`（桌面直接操作）；`AGENTS.md:62-83`（旧 CLI 契约）；`AGENTS.md:84-95`（证据与未验收项）。
- `docs/zh-CN/development.md:88-95`（服务入口 5 步 + 30 s 冷却）、`:44-58`（阶段表）、`:86`（内置原厂区域参考）、`:38`（macOS sudo）；`docs/zh-CN/changelog.md`（3.0.0 USB 稳定性；3.0.1 Wrong senser sequence / 30 s 冷却 / Zadig；3.0.2 `/usr/share/app` 名称残留 ENOSPC、单个 probe 报告清理）；`docs/zh-CN/notices.md:30`（参考 `a7c2-service-preload`，本工具不用 preload/DEBUG）；`README.zh-CN.md:9-30`（支持的机型/不支持列表）、`82-101`（开始前必读 + 断电重开）、`117-145`（第 1 步驱动）、`146-164`（卸载重装）、`165-217`（Zadig 手动）、`218-235`（恢复原厂）、`236-261`（一键安装）、`320-336`（常见问题）、`337-348`（验证状态）。

### 7.2 本机一代固件证据（只读检查）
- `firmware.tar_unpacked/0700_part_image/dev/nflasha15_unpacked/lib/libJiritsu.so`：JIRITSU 命令名字表 `41169–41488`；`adj_cmd_set_file_path 7277 / adj_cmd_set_file2 7492 / cmd_file_delete2 7539 / adj_cmd_get_file2 7556 / adj_cmd_get_file_list 7603 / adj_cmd_get_file_hash 7801 / cmd_high_capacity_{send,get}_file 7698/7823`；`dlopen/dlclose/dlsym 7416/7423/8131`；`/tmp/jiritsu/libJit.so 39434`、`jit.log 39457`、`tmmc.jit 39390`、`jit_thread 6290`、`jit_exit 167528`、`/tmp/jiritsu/jinit 167872`、`"libJit.so crashed." 167891`、`"Recovery mode execute." 167910`、`/tmp/jiritsu/ramdsk_libJit/libJit.so 168041`、`MAIN() 167626`。
- `…/nflasha15_unpacked/bin/adjstctl.elf`：`@JIRITSU_*` 名字表 `109771–110995`；`"adjust block: 0x%04x, code: 0x%04x OSAL ID: 0x%08lx cmdname: %s"`。
- `…/nflasha15_unpacked/bin/sen.elf`：`senser_usb_mode_start 14636`、`/var/.sen/.smode 14514`、`/boot/sen/smode 14531`、`/setting/sen/smode 14547`、`/setting/.hasp 14377`。
- `…/nflasha15_unpacked/share/app/`（302 文件）、`share/avsystemsound/` 存在；`lib/` 144 个文件里**没有 appFw.so**；raw `nflasha15` 里 `appFw.so` 仅作为字符串出现于 `0x564ee5`、`0x1d2c81c`。
- `updater.img_unpacked/bin/ud_wbi_drop.elf`（WBI 丢弃工具，`us_mkfs.sh` 调用；见 `UPDATER_ANALYSIS.md:108,220`）。
- 分区事实：`0700_part_image/dev/` 只有 `nflasha3 / nflasha5 / nflasha7 / nflasha15`（`nflasha15` = 239,982,592 B）；见 `UPDATER_ANALYSIS.md:41`、`FIRMWARE_MOD.md:175,222`。

### 7.3 需要在一代实机验证的最小清单
1. MSC 模式 PID；认证（start/auth）后是否出现 `0336`（或 `02a9`）、屏幕提示、重枚举序列。
2. 认证走 SHA1(ret=2) 还是 SHA256(ret=8)；0E8A/0336 上的 challenge 长度是否同样是 `data[:4]` vs 全量。
3. `0x1001` 的 15/16/17/18 是否可用；状态码字典（尤其"文件不存在"是否也是 `0x10000006`）；写单文件上限是否 64KB；`/tmp/jiritsu/../../` 逃逸是否生效。
4. 写 `/tmp/jiritsu/libJit.so` 是否触发 dlopen 执行；入口符号是 `_init` 还是 `MAIN`；是否有 `ramdsk_libJit` 复制与 `jit.log`；崩溃后的 "Recovery mode" 行为。
5. `/proc/mounts` 里 `/usr` 的设备名与 ro/rw；`/sys/power/image_mode`、`image_dev`、`image_drop` 是否存在及取值。
6. BK4（两份？）、属性表 diff、`00e70003` 是否仍是 4 字节序列号。
7. 程序载体路径与大小（appFw.so 在不在 `/usr/lib`、CP 侧等价物在哪），以及一次"改一个窗口 + 完整读回 + 冷启动"的最小闭环。
