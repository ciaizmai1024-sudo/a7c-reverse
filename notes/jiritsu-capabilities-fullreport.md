# Sony A7C（ILCE-7C v2.00）出厂调试命令面 / Jiritsu · SensTALK

对象：ILCE-7C 固件 v2.00，ARM32 Thumb-2，USB `VID 0x054c / PID 0x0336`（服务模式）。
材料：从 `nflasha15.bin`（ext2，不是 FAT）中取出的 `/lib/libsencore.so`、`/lib/libJiritsu.so`、
`/bin/sen.elf`、`/bin/adjstctl.elf` 等模块，以及本目录的静态分析脚本。
方法：静态反汇编 + 字符串 + 动态重定位 + 与已有抓包笔记交叉核对。**没有在真机上执行任何命令。**

本文件回答三件事：**能不能拿任意物理内存读写、能不能执行/加载代码、能不能改寄存器/跑 DMA**，
并把“已证实 / 证据强 / 推测 / 未判定”分开写。完整机器可读命令表在 `commands.tsv`。

---

## 0. 交付物与证据等级

| 文件 | 内容 |
|---|---|
| `README.md` | 本文件：结论、命令表、handler 细节、风险、未判定项 |
| `commands.tsv` | 1746 行完整命令表：1715 条 AdjustControl 白名单 + 19 条 Jiritsu + 12 条 pFunc 层级项 |
| `sencore_tables.py` | 解析 libsencore / libJiritsu 的四张 72 字节命令表 |
| `dump_commands.py` | 生成 `commands.tsv`（含权限位、类别、qid、风险启发式） |
| `elf_arm.py` | ARM32 ELF 小工具：符号、重定位、PLT、反汇编、xref、字符串 |
| `ext2_walk.py` / `imgmap.py` | ext2 镜像遍历、物理偏移→文件映射（证明模块来源） |
| `manifest.tsv` / `manifest.json` | `nflasha15.bin` 全文件清单（路径/大小/inode/哈希） |

证据等级（后文每条结论都标注）：

- **已证实**：反汇编、字符串、调用链三者闭合，地址可复查。
- **证据强**：调用链基本闭合，但缺一个真机运行时验证。
- **推测**：常量/名称/表项吻合，handler 未完整跟完。
- **未判定**：材料不足，或依赖未提取的进程/内核策略。

`commands.tsv` 的 `rw` / `risk` 两列是**按命令名和 block 归属推导的启发式**，不是逐条验证过的行为；
第 5–7 节逐条跟过 handler 的条目才按“已证实”对待。表里 `risk=?` 表示名称无法判定。

---

## 1. 结论：三个能力问题

### 1.1 不改固件，能不能拿到任意物理内存读写？

| 方向 | 结论 | 证据 |
|---|---|---|
| **读** | **代码路径存在，主机可控地址与长度**：`MemoryDump`（pFunc `0xff03`，仅认证等级 A）把主机给的 `{u32 base, u32 size}` 交给 `DeviceIo("/dev/mem", 0x1002)` + `MappedMemory(base, size, prot=3, flags=1)`，按 Senser 包分块回传。 | 已证实（代码）；真机是否被内核 `/dev/mem` 策略拦截 = 未判定 |
| **写** | **存在 `/dev/mem` 写原语，但地址来自对端 OSAL 回复，不是主机直接字段**：回复处理器 `0x13a60` 在模式 0 下把回复数据 `memcpy` 到回复里的 `Adrs`。没有找到一条“主机直接指定物理写地址”的上层命令。 | 原语已证实；主机可控性 = 未判定 |

结论：**“任意物理读”在代码层面成立，但需要服务模式下的完整认证（等级 A）并且内核允许 `/dev/mem`；
“任意物理写”目前只能证明存在一个由对端地址驱动的写原语，不能下结论说主机能任意写。**

### 1.2 有没有命令能执行或加载代码？

**有，而且链条比“上传 shellcode 跳转”更简单：把 `.so` 写到相机文件系统，让既有加载器 `dlopen` 它。**

1. **FileControl（pFunc `0xff01`，等级 A）**：主机在 `FileControlType` 里给路径，`type=1` 时直接
   `WriteDeviceData(path, 0x1241, 0x8000)` —— `0x1241` = `O_WRONLY|O_CREAT|O_TRUNC|O_DSYNC`，
   即**任意路径覆盖写**，无路径清洗。证据：`0x14d54`，字符串 `/dev/` 之外无白名单。
2. **Jiritsu `SET_FILE_PATH`（cmd 15）+ `SET_FILE2`（cmd 16）**：路径由主机给，**没有发现 `..` 过滤**；
   `SET_FILE2` 会自动建父目录。写入 `/tmp/jiritsu/libJit.so` 时，handler **立即 `dlopen` 再 `dlclose`**
   （`0x5d76–0x5db8`，`strcmp(path, "/tmp/jiritsu/libJit.so")` 后 `dlopen(path, RTLD_LAZY)`）。
   也就是说：**只要写这个文件，构造函数就会在 Senser/libJiritsu 进程里执行**，不需要再发 START。
3. **Jiritsu `START`（cmd 4）**：启动脚本引擎，加载 `/tmp/jiritsu/libJit.so` 和 `/tmp/jiritsu/tmmc.jit`，
   `dlsym` 取 `CreateScriptI/LoadScriptI/RunScriptI/DestroyScriptI` 并运行。等于执行主机投放的代码。
4. `0x601 / 0x1f`：用一位数字参数执行**固定路径** `/usr/bin/ulogio.elf`，不是任意程序。

没有发现“把任意机器码写进内存再跳转”的命令；执行链是**落盘 → 既有加载器加载**。

### 1.3 有没有能改寄存器 / 跑 DMA 的？

- **CPU 寄存器读写：没有。**
- **DMA：没有找到 DMA 命令或 DMA 引擎配置命令。**
- **GPIO：有读，也有写**（`0x601/0x21` 读，ioctl `0xc0104700`；`0x0609 GPIO_WRITE`、
  `0x0318 CXS_WRITE_GPIO`、`0x0c0c WRITE_AND_CONFIG_BT_GPIO` 等写）。
- **设备寄存器 / I2C / EEPROM / NVM / 电源轨：有大量写命令**（见 4.2 与第 6 节），
  因此“能显著改变硬件状态”是成立的，只是不是 CPU 核内的寄存器，也不走 DMA。

### 1.4 “不改固件”到底改了什么？

所有能力都是**运行时**的：不刷写引导/系统分区也能完成上面的读、写文件、加载 `.so`。
但注意：`SET_FILE_PATH/SET_FILE2/FILE_DELETE2` 的任意路径写、`FileControl` 的任意路径写，
以及 `/dev/nflasha6` 上的 Jiritsu 分区操作，都会**持久改变相机文件系统内容**；
如果路径逃逸到 `/usr`（nflasha15）且该分区可写，就会改到系统文件。是否可写取决于运行时挂载权限（未判定，见 §8）。

---

## 2. 传输层与认证

### 2.1 SenserPacket

12 字节头（小端）：

| 偏移 | 字段 | 说明 |
|---|---|---|
| +0x00 | `u32 size` | 整包长度 |
| +0x04 | `u16 pFunc` | 顶层功能号（见 §3） |
| +0x06 | `u16 sequence` | 序号 |
| +0x08 | `u8 version` | 协议版本；MemoryDump 要求 ≤1 |
| +0x09 | `u8 miconType` | bit4 影响 MemoryDump 路由 |
| +0x0a | `u8 offsetType` | 分片偏移类型 |
| +0x0b | `u8 response` | 响应标志 |

常量：`SenserMinSize = 0x200`，`ChunkSize = 0x8000`，`MaxSize = 0x100000`（1 MiB）。

### 2.2 认证等级

服务模式握手返回 `result ∈ {1,2,3}`，`WorkerThreadManager::onComplete @0x10a70` 选择
GOT+`0x7f8` / `0x808` / `0x824` 三张 pFunc 表，并把结果字节写到 GOT+`0x840`；
`result == 3` 时把受限标志 GOT+`0x82c` 清 0。

| result | 等级 | 可用 pFunc |
|---|---|---|
| 3 | A（完整） | 全部（含 `0xff01 FileControl`、`0xff03 MemoryDump`） |
| 2 | B | `0x10 / 0x20 / 0x40`，且白名单 code 必须带 `0x8000` |
| 1 | C | 仅 `0x40 AdjustControl`，且 code 必须带 `0x4000` 或 `0x8000` |

Jiritsu 只在服务模式存在；`libJiritsu` 的 0x1001 表全部带 `0x4000` 位，按白名单语义至少需要等级 ≥2，
实际完整文件/脚本能力在等级 A 下使用。

---

## 3. pFunc 顶层命令

三张表位于 `.data`，VA `0x61e30`（A）/ `0x61e78`（B）/ `0x61e98`（C），
条目 8 字节 `{u16 pFunc; u16 pad; u32 handler}`，handler 由 `R_ARM_ABS32` 在 +4 填充。
下表 handler 为去 Thumb 位后的代码地址：

| 等级 | pFunc | 名称 | handler | 读写 | 目标 | 风险 | 证据 |
|---|---|---|---|---|---|---|---|
| A | `0x10` | `ProductInfoFunc` | `0x13834` | R | 产品信息 | 只读 | 已证实 |
| A | `0x20` | `FirmwareUpdateFunc` | `0x13274` | W | 固件更新（8 字节桩） | ? | 已证实 |
| A | `0x30` | `MiconAccessFunc` | `0x1356c` | - | 直接返回 `NoAction 0x80` | 只读 | 已证实 |
| A | `0x40` | `AdjustControlFunc` | `0x14bec` | W | 1715 条白名单总入口 | 高 | 已证实 |
| A | `0xff00` | `TestMode` | `0x137dc` | W | `HostCommunicationCommand` | 中 | 证据强 |
| A | `0xff01` | `FileControl` | `0x14d54` | W | 主机给定路径写文件 | 高 | 已证实 |
| A | `0xff02` | `SonarFunc` | `0x1354c` | - | 空 handler | 只读 | 已证实 |
| A | `0xff03` | `MemoryDump` | `0x14af8` | R | 任意物理内存读（`/dev/mem`） | 只读 | 已证实（代码） |
| B | `0x40` | `AdjustControlFunc` | `0x14bec` | W | 同上（受限白名单） | 高 | 已证实 |
| B | `0x10` | `ProductInfoFunc` | `0x13834` | R | 产品信息 | 只读 | 已证实 |
| B | `0x20` | `FirmwareUpdateFunc` | `0x13274` | W | 固件更新（桩） | ? | 已证实 |
| C | `0x40` | `AdjustControlFunc` | `0x14bec` | W | 同上（仅 `0x4000/0x8000`） | 高 | 已证实 |

`FirmwareUpdateFunc` 只有 8 字节，实际不执行更新；`MiconAccessFunc`、`SonarFunc` 直接返回空动作。
真正的危险面在 `0x40 / 0xff01 / 0xff03` 和 Jiritsu。

---

## 4. AdjustControl 白名单（1715 条）

### 4.1 匹配与权限

调用链：`pFunc 0x40 → AdjustControlFunc @0x14bec → 包装 @0x14a44 →
SubsystemCommunicationCommand::TransactionStart @0x14280`。

白名单在 `libsencore.so` 文件偏移 `0x1a218`，步长 `0x48`，`TransactionStart` 的扫描上界是
`movw r2, #0x6b3`（1715 条，索引 0–1714）。**0x1a218 + 1715×0x48 之后是相邻的只读数据，
不是命令；不要使用第 1715 条以后的内容。**

条目布局：

```c
struct entry {          // 72 bytes
    u16 block;          // +0x00  子系统块号
    u16 code;           // +0x02  命令码 + 权限位 + 类别位
    char name[64];      // +0x04
    u32 qid;            // +0x44  OSAL 目标队列
};
```

匹配规则（`0x14418–0x144b0`）：

1. `entry.block == request.block`（精确相等）。
2. `(entry.code ^ request.code) & 0xff == 0` —— **只有低 8 位参与线上匹配**。
3. 权限位按认证等级过滤（见 §2.2）：`0x8000` 仅 A；`0x4000` 要求 A/B。
4. 类别位 `(code & 0x1800)`：
   - `0x800` → `sb=2`，**场景类**；
   - `0x1000` → `sb=1`，testcmd 类；
   - `0` → `sb=0`，普通 OSAL 命令；
   - 其他 → `sb=0xff`（拒绝）。
5. `sb==0` → 向 `qid` 发 OSAL 消息，负载原样转发。
   `sb!=0` → 走 `testcmd_run_scenario`（`0x16228` 用同一张表再按 block+code 查一次）。
   **场景类表项的 `qid` 字段为 0**（实测 0x306、0x420 全部为 0），说明它们不是直接发队列，
   而是由场景运行器组装请求。

**参数**：对绝大多数白名单条目，`libsencore` 只做匹配和转发，**负载格式由接收 qid 的进程定义**。
本次没有逐个反汇编 100 多个接收进程，因此 `commands.tsv` 对这些条目统一写
“参数=OSAL 负载（接收端 qid 定义）”。只有第 5–7 节列出的子系统做了行为级确认。

### 4.2 block 总览（1715 条）

`commands.tsv` 有每条的 block / code / wire_code / perm / class / qid / name / rw / target / risk / note。
下面是按 block 的归属与“写入时的风险地板”（`高`=持久/固件/校准/分区/电源，`中`=运行态或可恢复，
`低`=瞬时，`只读`=按名称/代码判定）：

| block | 条数 | 归属 | 风险地板 |
|---|---|---|---|
| 0x0101 | 2 | 应用层 testcmd/仿真 | 中 |
| 0x0102 | 11 | 显示/AF 调整/测试 | 中 |
| 0x0103 | 10 | FIFO/配置/日志 | 中 |
| 0x0201 | 6 | 应用基础设施 ILOG/事件 | 中 |
| 0x0202 | 3 | 应用基础设施 指示器 | 低 |
| 0x0203 | 1 | 应用基础设施 热靴 | 中 |
| 0x0204 | 1 | 应用基础设施 触摸 | 中 |
| 0x0205 | 1 | 应用基础设施 错误清除 | 低 |
| 0x0301 | 13 | 面板/EVF 调整 | 中 |
| 0x0302 | 57 | 面板/EVF 调整 | 中 |
| 0x0303 | 29 | 音频/麦克风诊断 | 中 |
| 0x0304 | 2 | 编解码诊断 | 中 |
| 0x0305 | 14 | 编解码诊断数据区 | 中 |
| 0x0306 | 25 | AV 基板场景（SCN） | 中 |
| 0x0307 | 30 | AV 基板诊断 | 中 |
| 0x0308 | 14 | 投影/DPP | 中 |
| 0x0309 | 3 | AD/增益 | 中 |
| 0x030a | 3 | 外部 EVF 检测 | 中 |
| 0x030b | 16 | 外部 EVF OLED/按键 | 中 |
| 0x030c | 2 | SDI | 中 |
| 0x030d | 4 | 副 LCD/背光 | 中 |
| 0x030e | 6 | FURUD 类别存储 | 高 |
| 0x030f | 7 | 热靴/鞋 ID/WiFi 端口 | 高 |
| 0x0310 | 4 | TOKI 类别存储 | 高 |
| 0x0311 | 13 | AV 板电源/信号开关 | 中 |
| 0x0312 | 2 | 回环/视频诊断 | 中 |
| 0x0313 | 2 | FG/风扇 | 中 |
| 0x0314 | 1 | 温度 | 只读 |
| 0x0315 | 2 | 副 LCD/背光 | 中 |
| 0x0316 | 3 | PS/眼感/ALS | 只读 |
| 0x0317 | 1 | 转盘/TPU | 只读 |
| 0x0318 | 25 | CXS 板（固件/GPIO） | 高 |
| 0x0319 | 11 | PLL/时钟 | 中 |
| 0x031a | 1 | 转盘/TPU | 只读 |
| 0x031b | 6 | 音频开关/告警 | 中 |
| 0x031c | 1 | 时间复位 | 低 |
| 0x031d | 1 | MTG 复位 | 中 |
| 0x031e | 3 | TC/IO 开关 | 中 |
| 0x031f | 1 | 手柄注册 | 中 |
| 0x0404 | 248 | 影像 LSI 调整 G_/S_/A_/C_ | 中 |
| 0x0405 / 0x040f / 0x0415 / 0x0418 | 8 | 影像 LSI RAM_READ/RAM_WRITE | 中 |
| 0x0408 | 6 | 影像 LSI 调整 | 中 |
| 0x0420 | 8 | 相机场景（SCN） | 中 |
| 0x0421 | 6 | AF/传感器 store + RAM | 高 |
| 0x0422 | 1 | 人脸信息清除 | 低 |
| 0x0423 | 5 | 竖拍手柄 | 中 |
| 0x0450 | 2 | 短片/省电设置 | 低 |
| 0x0460 | 10 | AWB/IR 调整 | 中 |
| 0x0470 | 21 | 快门/帘幕调整 | 中 |
| 0x0480 | 20 | DFE/CLC 调整 | 中 |
| 0x0490 | 23 | 镜头/曝光调整 | 中 |
| 0x04b0 | 4 | 微距灯/转盘 | 中 |
| 0x04c0 | 73 | 镜头/陀螺/灰尘调整 | 中 |
| 0x04d0 | 3 | 暗电流检查 | 中 |
| 0x04d1 | 35 | 暗电流/偏移调整 | 中 |
| 0x0501 | 11 | 视频/分量调整 | 中 |
| 0x0502 | 5 | AVCE/MP2E 参数 | 中 |
| 0x0503 | 12 | 编解码诊断数据区 | 中 |
| 0x0601 | 19 | ADJCTRL LSI 控制 | 中 |
| 0x0603 | 18 | 微控制器存储/PDT | 高 |
| 0x0604 | 15 | UD 更新/执行 | 中 |
| 0x0608 | 1 | 应用启动状态 | 低 |
| 0x0609 | 6 | PDT/GPIO/TALLY | 高 |
| 0x060a | 3 | ATN 信号 | 中 |
| 0x060b | 7 | NOR/日志 | 高 |
| 0x060c | 3 | 选项卸载/唯一键 | 高 |
| 0x060d | 2 | 时钟预设 | 中 |
| 0x060e | 1 | TALLY LED | 低 |
| 0x0701 | 9 | USB/充电/客户注册表 | 高 |
| 0x0702 | 13 | JET 测速（场景） | 中 |
| 0x0703 | 7 | USB 日志读取/删除 | 中 |
| 0x0704 | 1 | ADB 使能 | 中 |
| 0x0705 | 11 | USB PD/充电 | 高 |
| 0x0801 | 16 | GRM 取景器 | 中 |
| 0x0802 | 4 | GRM 取景器 | 中 |
| 0x0901 | 5 | ADC | 中 |
| 0x0902 | 5 | ADC | 中 |
| 0x0903 | 1 | GPIO | 低 |
| 0x0b01 | 52 | MPR 媒体/分区 | 高 |
| 0x0c01 | 26 | HDMI RX/TX | 中 |
| 0x0c02 | 10 | USB 视频 | 中 |
| 0x0c03 | 13 | HDMI 诊断 | 中 |
| 0x0c04 | 47 | WLAN 固件/测试 | 高 |
| 0x0c05 | 1 | 诊断 | 中 |
| 0x0c06 | 11 | 指南针/加速度调整 | 中 |
| 0x0c07 | 6 | 相机诊断 API | 中 |
| 0x0c08 | 15 | 相机诊断 | 中 |
| 0x0c09 | 3 | I2C/HDCP | 高 |
| 0x0c0a | 3 | NFC | 高 |
| 0x0c0b | 2 | 加速度/陀螺 | 低 |
| 0x0c0c | 7 | 蓝牙固件/GPIO | 高 |
| 0x0c0d | 3 | 有线 LAN MAC | 高 |
| 0x0c0e | 3 | 选项卸载/唯一键 | 高 |
| 0x0c0f | 3 | 寄存器读写 | 中 |
| 0x0d01 | 60 | DD 电源 | 高 |
| 0x0d02 | 84 | DD 通道电源 | 高 |
| 0x0d03 | 40 | IB 电池信息 | 中 |
| 0x0d20 | 53 | I2C 寄存器下载 | 中 |
| 0x0d21 | 38 | 相机/闪光灯状态 | 中 |
| 0x0e01 / 0x0e02 | 3 | DMM 日志 | 中 |
| 0x0f01 | 3 | 音频编解码调整 | 中 |
| 0x1001 | 19 | Jiritsu 调试服务 | 见 §5 |
| 0x1002 | 4 | testcmd 引擎 | 中 |
| 0x1100 | 1 | 系统端口控制 | 中 |
| 0x2009 | 1 | 电源执行 | 中 |
| 0x2012 | 3 | 计时表 | 中 |
| 0x2015 | 1 | 版本读取 | 只读 |
| 0x2101 | 6 | 工厂复位/初始化 | 高 |
| 0x2301 | 15 | 音频/时码控制 | 中 |
| 0x2302 | 1 | 视频输入选择 | 中 |
| 0x2303 | 9 | 输出控制 | 中 |
| 0x2306 | 5 | 音频/彩条/取景器 | 中 |
| 0x2406 | 2 | 测试输出 | 中 |
| 0x2b01 | 8 | 录制/媒体 | 高 |
| 0x2b07 | 3 | 播放控制 | 中 |
| 0x3201 | 8 | 影像检查/备份 | 中 |
| 0x3205 | 27 | 影像自动调整 | 中 |
| 0x3301 | 7 | 信号输出 | 中 |
| 0x3401 | 18 | 音频输入/采样率 | 中 |
| 0x3501 | 61 | FPGA/系统 I2C | 中 |
| 0x3b01 | 7 | NVM | 高 |
| 0x4501 | 8 | LCD/OLED/EEPROM | 高 |
| 0x4b01 | 7 | NVM | 高 |
| 0x9001 | 6 | 库管理 | 高 |
| 0xffff | 1 | 表终止符 `UNKNOWN` | - |
| 0x0402/0x0409–0x040e/0x0411/0x0414/0x0416/0x041e/0x04a0/0x0602/0x0605–0x0607 | 17 | 保留/DUMMY | ? |

### 4.3 场景类（class = scenario，共 40 条）

这些条目的 `code & 0x1800 == 0x800`，`qid` 为 0，进入 `testcmd_run_scenario`。
风险均为“会启动/停止真实硬件路径”，按“中”处理；误操作可导致当前会话卡死或需要断电。

| block | code | wire | 名称 |
|---|---|---|---|
| 0x0306 | 0x0801 | 0x01 | AVBB_SCN_START_VIDEO |
| 0x0306 | 0x0802 | 0x02 | AVBB_SCN_STOP_VIDEO |
| 0x0306 | 0x0803 | 0x03 | AVBB_SCN_START_PANELEVF |
| 0x0306 | 0x0804 | 0x04 | AVBB_SCN_STOP_PANELEVF |
| 0x0306 | 0x0805 | 0x05 | AVBB_SCN_START_HDMI |
| 0x0306 | 0x0806 | 0x06 | AVBB_SCN_STOP_HDMI |
| 0x0306 | 0x0807 | 0x07 | AVBB_SCN_START_AUDIO |
| 0x0306 | 0x0808 | 0x08 | AVBB_SCN_STOP_AUDIO |
| 0x0306 | 0x0809 | 0x09 | AVBB_SCN_START_MIC |
| 0x0306 | 0x080a | 0x0a | AVBB_SCN_STOP_MIC |
| 0x0306 | 0x080b | 0x0b | AVBB_SCN_START_MICSENSE |
| 0x0306 | 0x080c | 0x0c | AVBB_SCN_STOP_MICSENSE |
| 0x0306 | 0x080d | 0x0d | AVBB_SCN_START_HDMI_SUB |
| 0x0306 | 0x080e | 0x0e | AVBB_SCN_L_R_SETTING |
| 0x0306 | 0x080f | 0x0f | AVBB_SCN_L_R_SETTING_PANELEVF |
| 0x0306 | 0x0810 | 0x10 | AVBB_SCN_OPTAXIS_PANELEVF |
| 0x0306 | 0x0811 | 0x11 | AVBB_SCN_START_HDMI_SDI |
| 0x0306 | 0x0812 | 0x12 | AVBB_SCN_START_HDMI_SDI_SUB |
| 0x0306 | 0x0813 | 0x13 | AVBB_SCN_STOP_HDMI_SDI |
| 0x0306 | 0x0814 | 0x14 | AVBB_SCN_START_HDMI_INPUT |
| 0x0306 | 0x0815 | 0x15 | AVBB_SCN_START_HDMI_INPUT_SUB |
| 0x0306 | 0x0816 | 0x16 | AVBB_SCN_STOP_HDMI_INPUT |
| 0x0306 | 0x0817 | 0x17 | AVBB_SCN_START_DP |
| 0x0306 | 0x0818 | 0x18 | AVBB_SCN_START_DP_SUB |
| 0x0306 | 0x0819 | 0x19 | AVBB_SCN_STOP_DP |
| 0x0420 | 0x0801 | 0x01 | CAMERA_SCN_EE_START_STOP |
| 0x0420 | 0x0802 | 0x02 | CAMERA_SCN_EE_SET_PRM |
| 0x0420 | 0x0803 | 0x03 | CAMERA_SCN_SET_ZOOM_DRV |
| 0x0420 | 0x0804 | 0x04 | CAMERA_SCN_MOVIE_REC_START |
| 0x0420 | 0x0805 | 0x05 | CAMERA_SCN_FACE_REC_DATA |
| 0x0420 | 0x0806 | 0x06 | CAMERA_SCN_EXTERNAL_RAW_RECORD |
| 0x0420 | 0x0807 | 0x07 | CAMERA_SCN_EE_SETUP_START_STOP |
| 0x0420 | 0x0808 | 0x08 | CAMERA_SCN_VIDEOLIGHT_SW |
| 0x0601 | 0x88a0 | 0xa0 | ETOOLS_SENSER_SAMPLE |
| 0x0702 | 0x48a0 | 0xa0 | USB_JET_JET_JET_ADJ_SCENARIO |
| 0x0b01 | 0x0880 | 0x80 | MPR_SCN_FORMAT |
| 0x0b01 | 0x0881 | 0x81 | MPR_SCN_FLASH_BACKUP_INIT |
| 0x0b01 | 0x4882 | 0x82 | MPR_SCN_GET_CONTENT_COUNT |
| 0x0b01 | 0x4883 | 0x83 | MPR_SCN_GET_TOTAL_LOG |
| 0x0b01 | 0x08e1 | 0xe1 | MPR_SCN_SET_FACTORY_MODE |

`testcmd_run_scenario` 会按 `block+code` 再查一次同一张 1715 条表，构造 0x124 字节请求并调用场景处理器；
请求最终发往的 qid 与 `scenario.elf` 的具体角色属于后续进程，**未在本模块内闭合**（见 §8）。

---

## 5. Jiritsu 0x1001 表（19 条）

表在 `/lib/libJiritsu.so` 文件偏移 `0x249c0`，步长 `0x48`，格式与 host 表相同：

```c
struct jir_entry { u32 zero; u32 qid; u16 block; u16 code; char name[56]; };
```

注意：`0x24930` 处还有一张相邻表，先是两条 `0x0f01 CODEC_ADJ_MODE_*`，随后才是 0x1001 组；
**0x1001 组从 `0x249c0` 开始，共 19 条**。`0x24f18` 起是 `0x1002 TESTCMD/LOAD/CLOSE/SET_PARAMETER`，
不属于 Jiritsu。

线上命令号 = `code & 0xff`（1–19），与消息 `+0x1a cmd` 对应。消息布局：

```c
// Jiritsu 消息
+0x00 u32 type
+0x04 u32 total_len
+0x0c u16 4
+0x10 u32 status
+0x14 u32 L            // 数据长度
+0x18 u16 block        // 0x1001
+0x1a u8  cmd          // 1..19
+0x1c private header / data
```

| cmd | code | 名称 | handler | 参数 | R/W | 目标 / qid | 风险 | 证据 |
|---|---|---|---|---|---|---|---|---|
| 1 | 0x4001 | JIRITSU_MODE | — | 模式切换（jmode） | W | 0x009302f5 | 低 | 已证实（表） |
| 2 | 0x4002 | JIRITSU_MOUNT | 0x4a.. | 无 | W | `/dev/nflasha6 → /tmp/jiritsu`；0x016f0480 | 低 | 已证实（字符串） |
| 3 | 0x4003 | JIRITSU_FORMAT | `cmd_format @0x48f8` | 无 | W | 仅擦 `/tmp/jiritsu`（nflasha6） | 中 | 已证实 |
| 4 | 0x4004 | JIRITSU_START | `cmd_start @0x4b60` | 无 | **X** | 脚本引擎（libJit.so + tmmc.jit） | **高** | 已证实 |
| 5 | 0x4005 | JIRITSU_DEBUG | `cmd_debug @0x4da8` | 无 | W | RTC 设为 2017-07-04 21:42:26 | 低 | 已证实 |
| 6 | 0x4006 | JIRITSU_FIRMUP | `adj_cmd_set_firm @0x67ec` | 更新包/长度/标志（未完全解析） | W | `/tmp/jiritsu.bak.tar/.hash`、ramdsk、`/dev/nflasha6` | 中 | 证据强 |
| 7 | 0x4007 | JIRITSU_SET_FILE | `adj_cmd_set_file @0x56c0` | 当前路径 + 文件名 + 数据（≤5 MiB） | W | `/tmp/jiritsu/...` | 中 | 已证实 |
| 8 | 0x4008 | JIRITSU_GET_FILE | `adj_cmd_get_file @0x5468` | 路径/文件名 | R | `/tmp/jiritsu/...` | 只读 | 已证实 |
| 9 | 0x4009 | JIRITSU_FILE_DELETE | `cmd_file_delete @0x58f8` | 路径/文件名 | W | `/tmp/jiritsu/...` | 中 | 已证实 |
| 10 | 0x400a | JIRITSU_GET_FILELIST | — | 目录 | R | `/tmp/jiritsu` | 只读 | 证据强 |
| 11 | 0x400b | JIRITSU_GET_FILE_HASH | — | 路径/文件名 | R | 文件 MD5 | 只读 | 证据强 |
| 12 | 0x400c | JIRITSU_COMPARE_MEDIA | `adj_cmd_compare_media` | 外部媒体路径 + 主机数据 | R | `/mnt/.compare`、`/dev/mmca1`、`/dev/ms1` | 低 | 已证实（字符串） |
| 13 | 0x400d | JIRITSU_GET_VERSION | — | 无 | R | `/tmp/jiritsu/ver.txt` | 只读 | 已证实（字符串） |
| 14 | 0x400e | JIRITSU_FACTORY | `cmd_factory @0x519c` | ≤0xf0 字节；低 4 位 0/1，高 4 位 0/0x10/0x20/0x30 | W | 全局消息槽（信号量） | ? | 证据强 |
| 15 | 0x400f | JIRITSU_SET_FILE_PATH | `adj_cmd_set_file_path @0x52a8` | 路径 ≤0x201；拒绝 `\n\r,`；`\`→`/`；**无 `..` 过滤** | W | 任意主机给定路径 | **高** | 已证实 |
| 16 | 0x4010 | JIRITSU_SET_FILE2 | `adj_cmd_set_file2 @0x5b00` | 路径 + 数据（≤5 MiB）；自动建父目录 | W/**X** | 任意路径；写 `libJit.so` 后 `dlopen` | **高** | 已证实 |
| 17 | 0x4011 | JIRITSU_GET_FILE2 | `adj_cmd_get_file2 @0x5fe8` | 路径 | R | 任意主机给定路径 | 中 | 已证实 |
| 18 | 0x4012 | JIRITSU_FILE_DELETE2 | `cmd_file_delete2 @0x5f18` | 路径 | W | 任意主机给定路径 | **高** | 已证实 |
| 19 | 0x0013 | JIRITSU_TEST_UI_VIEW | `cmd_test_ui_view @0x4dd2` | — | - | 桩函数，未实现 | - | 已证实 |

### 5.1 关键 handler

**`cmd_format @0x48f8`**：挂载 `/dev/nflasha6` 到 `/tmp/jiritsu`，`sys_rm_tree("/tmp/jiritsu")`，
删 `/tmp/jbusy`、`/tmp/jmode`，再卸载。字符串 `cmd_format: ...` 与 `/dev/nflasha6` 在 `0x9568`。
**不改 nflasha15 / `/usr`。**

**`cmd_start @0x4b60`**：要求 jmode = Manual；检查 `/tmp/jiritsu` 挂载与 `tmmc.jit`；
`dlopen("/tmp/jiritsu/libJit.so")`，`dlsym` 取 `CreateScriptI / LoadScriptI / RunScriptI /
DestroyScriptI`，加载 `tmmc.jit` 后运行。失败字符串：
`cmd_start: JMODE_OPEN_FAIL / SCR_CREATE_FAIL / SCR_LOAD_FAIL / SO_OPEN_FAIL /
SYM_LOAD_FAIL / RUN_FAIL / RUN_BUSY`（`0x963f` 起）。

**`cmd_debug @0x4da8`**：只调用 `sys_set_timeofday(2017, 7, 4, 21, 42, 26)`（常量在 `0x4dac–0x4dc2`）。
**不执行 shell、不提权。** 之前从 ZVE-10 工具推测的“root 执行”在 A7C 上不成立。

**`adj_cmd_set_file_path @0x52a8`**：长度上限 `0x201`；拒绝换行、回车、逗号；把 `\` 换成 `/`。
`get_access_filename @0x5948` 只做模板拼接/前缀比较，**没有对 `..` 的检查**。因此路径可以逃逸
`/tmp/jiritsu`。这是 `SET_FILE2 / GET_FILE2 / DELETE2` 能写到 `/usr` 等位置的原因（是否真能写取决于权限/挂载，见 §8）。

**`adj_cmd_set_file2 @0x5b00`**：5 MiB 配额（`0x500000`，与 `set_file` 相同）；
写 `/tmp/jiritsu/libJit.so` 需要 `/tmp/jbusy` 不存在；写完若路径等于
`/tmp/jiritsu/libJit.so`，执行 `dlopen(path, RTLD_LAZY)` + `dlclose`（`0x5d76–0x5db8`）。
**这一步会执行恶意 `.so` 的构造函数**，不等 START。

**`adj_cmd_set_firm @0x67ec`**：挂载 nflasha6，检查 Jiritsu 运行状态，压缩 `/tmp/jiritsu` 到
`/tmp/jiritsu.bak.tar`，算 MD5 写 `jiritsu.bak.hash`，`DmmMgr::dmm_alloc`，解包更新包到
ramdisk（`/tmp/jiritsu/ramdsk`、`jiritsu.dat`），更新 DIAC 列表、`jcount`，最后删恢复文件。
字符串：`/tmp/jiritsu.bak.tar`、`/tmp/jiritsu.bak.hash`、`/tmp/jiritsu/jiritsu.hash`、
`ramdsk`、`Tar file extract error`、`DIAC list update error`。**目标仍是 nflasha6。**

**`jit_thread @0x74b0`**：把 `libJit.so` 复制到 1 MiB ramdisk（`/tmp/jiritsu/ramdsk_libJit`），
`dlopen` 后解析 `CreateScriptI / LoadScriptI / RunScriptI / DestroyScriptI`；备份/恢复通过
`/tmp/jiritsu.bak.tar` + `.hash` 与 `/tmp/jiritsu/jinit`。

---

## 6. 关键子系统表（行为级确认过）

### 6.1 block 0x0601 — ADJCTRL（19 条，qid 0x003d025f）

| code | wire | 名称 | 行为 / 参数 | R/W | 风险 | 证据 |
|---|---|---|---|---|---|---|
| 0x0011 | 0x11 | SEN_MODE | Senser 模式切换 | W | 中 | 证据强 |
| 0x0012 | 0x12 | FCT_MODE | 工厂模式 | W | 中 | 证据强 |
| 0x8013 | 0x13 | DBG_MODE | 调试/日志模式（L3） | W | 中 | 证据强 |
| 0x4014 | 0x14 | TST_MODE | 测试模式（L2+） | W | 中 | 证据强 |
| 0x001a | 0x1a | SELECT_LSI | param 必须 0/1（`0x1454c–0x14578`） | W | 中 | 已证实 |
| 0x801f | 0x1f | TERM_MODE | 终止模式；执行 `/usr/bin/ulogio.elf`，参数 `'0'+digit`（L3） | W | 中 | 证据强 |
| 0x0021 | 0x21 | GPIO_READ | ioctl `0xc0104700` 读 GPIO | R | 只读 | 已证实 |
| 0x0022 | 0x22 | TIMER | 定时器操作 | ? | ? | 未判定 |
| 0x4023 | 0x23 | GET_LOG | 取日志 | R | 只读 | 证据强 |
| 0x402f | 0x2f | HASP | 加密狗/许可 | ? | ? | 推测 |
| 0x0031 | 0x31 | SSBI_MK_MODE | SSBI 模式 | W | 中 | 推测 |
| 0x0051 | 0x51 | ILOG_WRITE | 写 ILOG | W | 中 | 证据强 |
| 0x0052 | 0x52 | ILOG_READ | 读 ILOG | R | 只读 | 证据强 |
| 0x0053 | 0x53 | ILOG_DEL | 删 ILOG | W | 中 | 证据强 |
| 0x4061 | 0x61 | XPWR_OFF_DISABLE_PORT_INFO | 读 4 字节备份 `0xf9090f` | R | 只读 | 已证实（调用） |
| 0x4062 | 0x62 | XPWR_OFF_DISABLE_PORT_SET | 读 `0xf90910` + ioctl `0xc0104703` | W | 中 | 已证实（调用） |
| 0x88a0 | 0xa0 | ETOOLS_SENSER_SAMPLE | 场景类 | X | 中 | 已证实（表） |
| 0x00fe | 0xfe | RAM_READ | **特殊本地路径**：LSI 暂存缓冲（≤256 B），不是物理地址 | R | 只读 | 已证实 |
| 0x40ff | 0xff | RAM_WRITE | **特殊本地路径**：LSI 暂存缓冲（≤256 B） | W | 中 | 已证实 |

`0xfe/0xff` 的边界检查（`0x144f2–0x14502`）：`offset ≤ 0xff`、`size ≤ 0x100`、
`offset+size ≤ 0x100`。缓冲区来自 `this+0x154 / this+0x15c`，**没有证据表明主机能指定物理地址**。
`0x603/0x0f` 走同一特殊路径。

### 6.2 block 0x0603 — 微控制器存储 / PDT（18 条，qid 0x003e0166）

PDT = Production Data Table（生产校准数据）。这里的写操作可能覆盖校准/序列号相关数据。

| code | wire | 名称 | R/W | 风险 |
|---|---|---|---|---|
| 0x0001 | 0x01 | READ | R | 只读 |
| 0x0002 | 0x02 | WRITE | W | **高** |
| 0x0003 | 0x03 | SAVE | W | **高** |
| 0x0004 | 0x04 | PDT_WRITE | W | **高** |
| 0x0005 | 0x05 | PDT_READ | R | 只读 |
| 0x0006 | 0x06 | GET_PDT_STAT | R | 只读 |
| 0x0008 | 0x08 | RESET | W | **高** |
| 0x400f | 0x0f | ID1 | R | 只读 |
| 0x0010 | 0x10 | VERSION | R | 只读 |
| 0x0011 | 0x11 | DATA_CMP | R | 只读 |
| 0x0012 | 0x12 | DATA_CHECK | R | 只读 |
| 0x4020 | 0x20 | FACTORY | W | **高** |
| 0x0021 | 0x21 | SERVICE | ? | ? |
| 0x4022 | 0x22 | FACTORY_256 | W | **高** |
| 0x0030 | 0x30 | OFFSET_ACCESS | W | **高** |
| 0x0040 | 0x40 | READ_INTERCHIP | R | 只读 |
| 0x0041 | 0x41 | WRITE_INTERCHIP | W | **高** |
| 0x0042 | 0x42 | OFFSET_ACCESS_INTERCHIP | W | **高** |

参数格式由接收进程定义（`commands.tsv` 中为 OSAL 负载）；PDT 的具体地址空间（I2C/SPI/内部 flash）
未解析，见 §8。

### 6.3 block 0x0421 — AF/传感器 store + RAM（6 条，qid 0x001501f4）

| code | wire | 名称 | R/W | 风险 |
|---|---|---|---|---|
| 0x00e0 | 0xe0 | SAVE_ALL | W | **高**（持久化校准） |
| 0x00e1 | 0xe1 | SAVE_FORCE | W | **高** |
| 0x00e8 | 0xe8 | FROM_SYNC | W | 中 |
| 0x00e9 | 0xe9 | FRAM_SYNC | W | 中 |
| 0x00fe | 0xfe | RAM_READ | ? | 未判定 |
| 0x00ff | 0xff | RAM_WRITE | ? | 未判定 |

该 qid 的 handler 不在已提取的模块里（很可能在传感器/LSI 侧进程），所以 `RAM_READ/RAM_WRITE`
到底读写哪块内存**不能下结论**。

### 6.4 block 0x0b01 — MPR 媒体/分区（52 条，qid 0x01150299）

风险列按“高=可能丢数据/改分区/刷备份，中=运行态，只读=查询”标注：

| code | wire | 名称 | R/W | 风险 |
|---|---|---|---|---|
| 0x0000 | 0x00 | MPR_CMD_CHECK_MEDIA_IF | R | 只读 |
| 0x0001 | 0x01 | MPR_CMD_CHECK_MEDIA_CAPACITY | R | 只读 |
| 0x4002 | 0x02 | MPR_CMD_CHECK_MEDIA_VENDOR | R | 只读 |
| 0x0003 | 0x03 | MPR_CMD_CHECK_MEDIA_SD_WP | R | 只读 |
| 0x4004 | 0x04 | MPR_CMD_CHECK_MEDIA_SECTOR_COUNT | R | 只读 |
| 0x4005 | 0x05 | MPR_CMD_CHECK_MEDIA_FREE_SPACE | R | 只读 |
| 0x0010 | 0x10 | MPR_CMD_FORMAT | W | **高** |
| 0x0011 | 0x11 | MPR_CMD_MAKE_PARTITION | W | **高** |
| 0x0012 | 0x12 | MPR_CMD_CHECK_MAP | R | 只读 |
| 0x4020 | 0x20 | MPR_CMD_READ_DATA_FILE | R | 只读 |
| 0x4021 | 0x21 | MPR_CMD_WRITE_DATA_FILE | W | **高** |
| 0x4022 | 0x22 | MPR_CMD_GET_RW_DATA_FILE_STATUS | R | 只读 |
| 0x4030 | 0x30 | MPR_CMD_JET_TEST_START | W | 中 |
| 0x4031 | 0x31 | MPR_CMD_JET_TEST_STOP | W | 中 |
| 0x4032 | 0x32 | MPR_CMD_JET_TEST_RESULT | R | 只读 |
| 0x4033 | 0x33 | MPR_CMD_JET_AUTO_TEST | W | 中 |
| 0x4034 | 0x34 | MPR_CMD_JET_AUTO_TEST_RESULT | R | 只读 |
| 0x0038 | 0x38 | MPR_CMD_PMBP_WRITE_DATA | W | **高** |
| 0x0039 | 0x39 | MPR_CMD_PMBP_GET_STATUS | R | 只读 |
| 0x003a | 0x3a | MPR_CMD_PMBP_CHECK_DATA | R | 只读 |
| 0x4040 | 0x40 | MPR_CMD_GSENSOR_CHECK | R | 只读 |
| 0x4041 | 0x41 | MPR_CMD_GSENSOR_ADJUST_START | W | 中 |
| 0x4042 | 0x42 | MPR_CMD_GSENSOR_ADJUST_STOP | W | 中 |
| 0x4043 | 0x43 | MPR_CMD_GSENSOR_GET_VALUE | R | 只读 |
| 0x4044 | 0x44 | MPR_CMD_GSENSOR_SET_DROP | W | **高**（校准） |
| 0x4048 | 0x48 | MPR_CMD_MEDIA_TEMP_ADJUST_START | W | 中 |
| 0x4049 | 0x49 | MPR_CMD_MEDIA_TEMP_ADJUST_STOP | W | 中 |
| 0x404a | 0x4a | MPR_CMD_MEDIA_TEMP_GET_VALUE | R | 只读 |
| 0x404b | 0x4b | MPR_CMD_MEDIA_TEMP_SET_VALUE | W | 中 |
| 0x404f | 0x4f | MPR_CMD_MSEN_BACKUP_RELOAD | W | **高** |
| 0x8050 | 0x50 | MPR_CMD_SET_WIFI_TEST_MODE | W | 中 |
| 0x8051 | 0x51 | MPR_CMD_EXEC_WIFI_TEST | W | 中 |
| 0x8052 | 0x52 | MPR_CMD_SET_RF_TEST_MODE | W | 中 |
| 0x0060 | 0x60 | MPR_CMD_CHECK_MEDIA_INSERT_COMMON | R | 只读 |
| 0x0061 | 0x61 | MPR_CMD_CHECK_MEDIA_LED_COMMON | R | 只读 |
| 0x0062 | 0x62 | MPR_CMD_GET_MEDIA_OVERCURRENT_STATUS | R | 只读 |
| 0x0063 | 0x63 | MPR_CMD_START_MEDIA_OVERCURRENT_CHECK | W | 中 |
| 0x0064 | 0x64 | MPR_CMD_STOP_MEDIA_OVERCURRENT_CHECK | W | 中 |
| 0x0065 | 0x65 | MPR_CMD_MEDIADETECT_STOP_INOUT | W | 中 |
| 0x0880 | 0x80 | MPR_SCN_FORMAT | X | **高**（场景格式化） |
| 0x0881 | 0x81 | MPR_SCN_FLASH_BACKUP_INIT | X | 中 |
| 0x4882 | 0x82 | MPR_SCN_GET_CONTENT_COUNT | X | 中 |
| 0x4883 | 0x83 | MPR_SCN_GET_TOTAL_LOG | X | 中 |
| 0x40e0 | 0xe0 | MPR_CMD_SET_FACTORY_MODE | W | **高** |
| 0x08e1 | 0xe1 | MPR_SCN_SET_FACTORY_MODE | X | **高** |
| 0x00e2 | 0xe2 | MPR_CMD_GET_FACTORY_MODE_RESULT | R | 只读 |
| 0x40e3 | 0xe3 | MPR_CMD_CHG_SATA_POWERMODE | W | 中 |
| 0x40e4 | 0xe4 | MPR_CMD_SATA_POWERONOFF | W | 中 |
| 0x00e5 | 0xe5 | MPR_CMD_SAVE_DRIVERLOG | W | 中 |
| 0x00e6 | 0xe6 | MPR_CMD_SET_DEVICE_TEST | W | 中 |
| 0x00e7 | 0xe7 | MPR_CMD_SET_DEVICE_TEST_ENV | W | 中 |
| 0x00e8 | 0xe8 | MPR_CMD_OUTPUT_DEVICE_TEST_RESULT | R | 只读 |

### 6.5 block 0x0c01 — HDMI RX/TX（26 条，qid 0x009a0264）

| code | wire | 名称 | R/W | 风险 |
|---|---|---|---|---|
| 0x8000 | 0x00 | READ | R | 只读 |
| 0x8001 | 0x01 | WRITE | W | 中 |
| 0x4002 | 0x02 | DEFINITION | W | 中 |
| 0x4003 | 0x03 | TMDS | W | 中 |
| 0x4004 | 0x04 | POWER | W | 中 |
| 0x4006 | 0x06 | XVCOLOUR | W | 中 |
| 0x4007 | 0x07 | AUDIO | W | 中 |
| 0x4008 | 0x08 | SRCDEV | W | 中 |
| 0x0009 | 0x09 | CHECK_DDC | R | 只读 |
| 0x000a | 0x0a | SET_3D_FORMAT | W | 低 |
| 0x000b | 0x0b | SUPPRESS_3D_INFOFRAME | W | 低 |
| 0x000c | 0x0c | SWITCH_LEFT_RIGHT | W | 低 |
| 0x000d | 0x0d | RX_BLUE_BACK | W | 低 |
| 0x400e | 0x0e | TX_DEFINITION | W | 中 |
| 0x400f | 0x0f | TX_TMDS_ | W | 中 |
| 0x0010 | 0x10 | RX_HAS_INPUT_SIGNAL | R | 只读 |
| 0x0011 | 0x11 | TX_EXTERNAL_COLOR_BAR | W | 低 |
| 0x0012 | 0x12 | RX_CANCEL_BLUEBACK | W | 低 |
| 0x0013 | 0x13 | TX_HAS_INPUT_SIGNAL | R | 只读 |
| 0x4014 | 0x14 | EXTERNAL_READ | R | 只读 |
| 0x4015 | 0x15 | EXTERNAL_WRITE | W | 中 |
| 0x4016 | 0x16 | TX_EXTERNAL_INFO | W | 低 |
| 0x4017 | 0x17 | SOFTWARE_STATE | R | 只读 |
| 0x0018 | 0x18 | TX_MUSASHI_COLOR_BAR | W | 低 |
| 0x0019 | 0x19 | TX_MUSASHI_GET_HPD | R | 只读 |
| 0x801a | 0x1a | SET_APMODE | W | 中 |

### 6.6 block 0x0702 — JET（13 条，qid 0x00cb03ed）

| code | wire | 名称 | R/W | 风险 |
|---|---|---|---|---|
| 0x4001 | 0x01 | JET_RADIO_LAW | ? | 中 |
| 0x4002 | 0x02 | JET_VELOCIMETRY_START | W | 中 |
| 0x4003 | 0x03 | JET_VELOCIMETRY_STOP | W | 中 |
| 0x4004 | 0x04 | JET_VELOCIMETRY_RESULT | R | 只读 |
| 0x4005 | 0x05 | JET_VELOCIMETRY_AUTO_TEST | W | 中 |
| 0x4006 | 0x06 | JET_VELOCIMETRY_AUTO_RESULT | R | 只读 |
| 0x4007 | 0x07 | JET_AUTHENTICATION | ? | 中 |
| 0x4010 | 0x10 | JET_SCSI_START_STOP | W | 中 |
| 0x4020 | 0x20 | JET_GET_TXGAIN | R | 只读 |
| 0x4021 | 0x21 | JET_GET_OWNUID | R | 只读 |
| 0x4022 | 0x22 | JET_GET_RSSI | R | 只读 |
| 0x4023 | 0x23 | JET_GET_OBEX_TRANSRATE | R | 只读 |
| 0x48a0 | 0xa0 | USB_JET_JET_JET_ADJ_SCENARIO | X | 中 |

---

## 7. 能力边界：逐条

### 7.1 物理内存读 — 已证实（代码）

调用链：

1. 主机包 `pFunc=0xff03`，负载是 `MemoryDumpType { u32 base; u32 size; }`（8 字节）。
2. `MemoryDump @0x14af8`：`Serialize<MemoryDumpType>`，检查 `packet.version ≤ 1`、
   `GetPacketRemains() == size`，然后构造 `MemoryData`（回调式输出）。
3. 输出 worker（`0xffe0` 附近）：
   `DeviceIo("/dev/mem", 0x1002)`（字符串在文件偏移 `0x1908e`），
   `MappedMemory(io, base, size, prot=3, flags=1)`，把映射区按 `ChunkSize=0x8000` 回传。
4. 分片/大小：`SenserMaxSize=0x100000`，单次可回传约 1 MiB；`base` 由主机给，
   因此**循环更换 base 即可覆盖任意物理范围**。

限制/未验证：

- 需要认证等级 A（`0xff03` 只在 A 表）。
- 真机内核是否允许非特权/受限 `/dev/mem` 映射（`CONFIG_STRICT_DEVMEM` 等）**未验证**。
- 读的是物理地址还是被 `MappedMemory` 二次解释（设备内存/缓存属性）未在真机确认。

### 7.2 物理内存写 — 原语已证实，主机可控性未判定

`0x13a60`（OSAL 回复处理器）解析 `{+0 sub-mode (2/8), +1 response, +4 mode, +8 Adrs, +0xc DataSize}`：

- `mode==0`：`DeviceIo("/dev/mem", 0x1002)` + `MappedMemory(Adrs, size, prot=3, flags=1)`，
  然后把回复 payload `memcpy` **进**映射区（写物理内存）。
- `mode==1`：从映射区拷**出**。
- 偏移窗口 ≤ `0x128`。

关键点：**`Adrs` 来自对端（LSI/子系统）的 OSAL 回复，不是 SenserPacket 的直接字段。**
没有找到一条上层命令把“主机给的物理地址”写进这个回复。可能存在“主机先让对端返回受控 Adrs”的间接路径
（例如 `0x601 RAM_READ/RAM_WRITE`、`0x421 RAM_*`），但本次没有证明，列入 §8。

另外两条“看起来像物理写”的路径都被排除为**局部缓冲**：

- `0x601/0xfe/0xff`、`0x603/0x0f`：走 `0x12ce0` 特殊路径，操作 `this+0x154/+0x15c` 的 LSI 暂存缓冲，
  边界 ≤256 B，没有物理地址控制。
- `0x421 RAM_WRITE`：handler 在别的进程，未判定（不是已证实的物理写）。

### 7.3 代码执行 / 加载 — 已证实（链条），真机未验证

三条独立入口：

1. **FileControl `0xff01`（等级 A）**
   `FileControlType`：`u16 type @+0x40`、`u16 path_len @+0x42`、`path @+0x44`。
   `type=1` → `WriteDeviceData(path, 0x1241, 0x8000)`。
   `0x1241` = `O_WRONLY|O_CREAT|O_TRUNC|O_DSYNC`；`0x8000` = 32 KiB 块。
   **路径完全由主机给，无清洗。**
   `type=2/3` 走 `DispatchCommand` 的固定函数指针（`0x14e74/0x14e82`），未解析。

2. **Jiritsu SET_FILE_PATH + SET_FILE2**
   任意路径（无 `..` 过滤），`SET_FILE2` 自动建目录；写 `/tmp/jiritsu/libJit.so` 后
   **立即 `dlopen` + `dlclose`**。`dlopen` 会执行 `.so` 的构造函数，因此这是**单命令代码执行**。

3. **Jiritsu START**
   加载 `libJit.so` + `tmmc.jit`，解析并运行脚本接口；`jit_thread` 还会把 `libJit.so`
   复制到 ramdisk 再加载。

补充：`0x1002 TESTCMD/LOAD/CLOSE/SET_PARAMETER`（qid 0x02e00903）是 testcmd 引擎入口，
`LOAD` 是否加载 ELF/脚本**未判定**；`0x601/0x1f` 只执行固定 `/usr/bin/ulogio.elf`。

### 7.4 寄存器 / GPIO / DMA

| 项 | 结论 | 证据 |
|---|---|---|
| CPU 通用/系统寄存器 | 无读写命令 | 证据强（全表未见） |
| DMA 引擎/描述符 | 无命令 | 证据强（全表未见） |
| GPIO 读 | 有：`0x601/0x21` → ioctl `0xc0104700` | 已证实 |
| GPIO 写 | 有：`0x0609 GPIO_WRITE`、`0x0318 CXS_WRITE_GPIO`、`0x0c0c WRITE_AND_CONFIG_BT_GPIO` | 证据强（名称/表） |
| 设备寄存器 / I2C | 有：`0x0c09 I2C_WRITE`、`0x0c0f REG_WRITE`、`0x0d20 DWN_I2C_REG_WRITE_*`、`0x3501 EXEC_SYS_I2C_WRITE`、`0x4501 EXEC_SYS_I2C_WRITE` | 证据强 |
| EEPROM / NVM | 有：`0x4501 *EEPROM*`、`0x3b01/0x4b01 NVM_*`、`0x060b NOR_WRITE` | 证据强 |
| 电源轨 | 有：`0x0d01/0x0d02 DD_*_SET`（60+84 条） | 证据强；错误值可能损坏硬件 |

“没有 DMA”只针对**已提取的模块**；内核驱动或其他未提取进程是否有 DMA ioctl 不在本次范围。

### 7.5 文件 / 分区写范围

| 路径 | 谁能写 | 范围 |
|---|---|---|
| `/tmp/jiritsu/*`（nflasha6） | Jiritsu SET_FILE/SET_FILE2/FORMAT/FIRMUP | 调试分区；FORMAT 会清空 |
| 任意主机路径 | Jiritsu SET_FILE_PATH + SET_FILE2/DELETE2；FileControl type 1 | 取决于进程权限与挂载；可 `..` 逃逸 |
| `/dev/nflasha15`（`/usr`） | 没有直接的块写入命令；只能通过“任意路径写”落到挂载点 | 是否可写未判定 |
| 外部媒体 `/dev/mmca1`、`/dev/ms1`、`/mnt/.compare` | Jiritsu COMPARE_MEDIA（只读比较） | 只读 |

**`cmd_format` 只擦 nflasha6，不碰 nflasha15；`FIRMUP` 也只作用于 nflasha6。**
没有找到“原始写引导分区/系统分区”的命令。

### 7.6 最高风险命令（不要执行）

以下任意一条误发都可能造成**不可逆**后果（砖、校准丢失、唯一键丢失、分区/数据丢失）：

- `0x060b / 0x02 NOR_WRITE`（NOR 写）
- `0x060c / 0x01–0x03`、`0x0c0e / 0x01–0x03`：`UNINSTALL_OPTION`、`UNINSTALL_ALL_OPTIONS`、
  `CLEAR_DEVICE_UNIQUE_KEY`
- `0x3b01 / *`、`0x4b01 / *`：`NVM_*`（含 `NVM_RECOVERY`、`NVM_FLUSH_PARAMETER`）
- `0x0318 / 0x02 CXS_UPDATE_FW`
- `0x0c04 WLAN_LOAD_FIRMWARE*`、`0x0c0c LOAD_BT_FIRMWARE`、`0x0c0a PROGRAM_UCOMFW`
- `0x2101 / 0x02 EXEC_FACTORY_RESET`
- `0x0b01 / 0x10 MPR_CMD_FORMAT`、`0x0b01 / 0x11 MPR_CMD_MAKE_PARTITION`、
  `0x2b01 / 0x03 EXEC_MEDIA_FORMAT`
- `0x0603` 的 `WRITE/SAVE/PDT_WRITE/FACTORY/FACTORY_256/OFFSET_ACCESS`、
  `0x0609 WRITE/PDT_*`、`0x0421 SAVE_ALL/SAVE_FORCE`
- `0x4501 *EEPROM*`、`0x0d01/0x0d02 DD_*_SET`（电源轨）
- `0x9001 COPY_LIBRARY/DELETE`
- `0x0701 WRITE_CUSTOMER_REGIST_HASH256`、`0x0c0d WIREDLAN_SET_MAC_ADDR`
- `0x1001 / 4 JIRITSU_START`、`0x1001 / 16 JIRITSU_SET_FILE2`（代码执行）

---

## 8. 未判定 / 分不清（不要混进上面的结论）

1. **`/dev/mem` 真机策略**：`MemoryDump` 的映射是否被内核限制、Senser 进程是否 root、`prot=3`
   是否足以读全部物理区。静态代码只能证明“调用了 `MappedMemory`”。
2. **物理写地址来源**：`0x13a60` 的 `Adrs` 来自对端回复。主机能否通过某条命令让对端返回
   受控地址（从而间接任意写）**未证明**。
3. **`0x601 RAM_READ/RAM_WRITE` 语义**：特殊路径只操作 ≤256 B 的 LSI 暂存缓冲；缓冲内容如何与
   真实 LSI 内存对应未解析。
4. **`0x421 RAM_READ/RAM_WRITE`**：qid `0x001501f4` 的 handler 不在已提取模块中，未判定。
5. **`0x603 READ/WRITE` 的地址空间**：PDT 存储是 I2C EEPROM、SPI flash 还是微控制器内部，未解析。
6. **FileControl type 2/3**：`0x14e74/0x14e82` 的 `DispatchCommand` 函数指针未解析。
7. **`0x601/0x1f` ulogio**：只确认执行固定 `/usr/bin/ulogio.elf` 与 `'0'+digit` 参数；
   具体子命令效果未逐条验证。
8. **`scenario.elf` 角色**：`testcmd_run_scenario` 构造 0x124 请求并调用场景处理器，
   但最终执行体（是否 `scenario.elf`、发往 0x00940270 还是 0x803d025f）没有在本模块内闭合。
9. **Jiritsu 消息 `+0x14 L` 与 core `+0x20` 长度字段的差异**：两者在不同 handler 中分别使用，
   是否存在长度混淆未判定。
10. **任意路径写的实际权限**：`SET_FILE2` 能逃逸 `/tmp/jiritsu`，但 Senser 进程对 `/usr`
    （nflasha15）是否有写权限、该分区是 ro 还是 rw，未在真机验证。
11. **`0x1002 LOAD`**：是否加载 ELF/脚本、从哪加载，未判定。
12. **`0x601/0x22 TIMER`、`0x2f HASP`、`0x31 SSBI_MK_MODE`**：只按名称/表项归类，handler 未完整跟。
13. **`0x603 SERVICE/FACTORY/FACTORY_256`**：具体写哪些 PDT 字段、是否有不可逆副作用，未解析。
14. **`0x0c0f REG_WRITE` / `0x0d20 DWN_I2C_*`**：总线号、设备地址、寄存器映射未解析。
15. **`0x030f SET_SHOE_ID`、`0x030e/0x0310 FURUD/TOKI`**：持久化位置（EEPROM/文件/其他）未判定。
16. **`0x9001` 的 `COPY_LIBRARY/DELETE`**：操作哪个库目录、是否可恢复，未解析。
17. **`0x0705` USB PD / `0x2009 EXEC_POWER`**：电源路径的具体效果未验证，误操作可能断电/损坏。
18. **无 DMA 的结论边界**：只覆盖 `libsencore/libJiritsu/sen.elf/adjstctl.elf`；内核驱动或其他
    未提取进程不在范围内。
19. **认证材料**：本次没有分析服务模式握手的具体密钥/挑战，无法判断等级 A 是否可被非官方客户端获得。
20. **`commands.tsv` 的 rw/risk**：对 1715 条中的大多数是名称启发式；只有第 5–7 节逐条跟过
    handler 的才是行为级结论。
21. **`0x0f01` 与 Jiritsu 相邻表**：`0x24930` 的两条 `CODEC_ADJ_MODE_*` + 重复的 `JIRITSU_MODE`
    （qid `0x009302f5`）不属于 0x1001 表；它们的消费者未判定。
22. **`0x1001/1 JIRITSU_MODE` 的 qid 差异**：MODE 的 qid 是 `0x009302f5`，其余文件命令是
    `0x016f0480`；MODE 实际由哪个进程处理未判定。
23. **`0x1001/14 JIRITSU_FACTORY`**：只确认消息槽与信号量；全局槽的消费者和最终效果未判定。
24. **`0x601/0x61/0x62`**：确认调用 `Backup_read_4Byte(0xf9090f/0xf90910)` 与 ioctl
    `0xc0104703`，但备份区语义与写入范围未判定。

---

## 9. 对已有笔记的修正

1. **`nflasha15.bin` 是 ext2，不是 FAT。** 原任务里的“先读 BPB 判断 FAT12/16”不适用；
   `fat12_walk.py` 走不通。实际用 `ext2_walk.py` / `imgmap.py` 遍历，块大小 1 KiB。
2. **`cmd_debug` 只设 RTC**，固定 2017-07-04 21:42:26；不是 root 执行/提权入口。
   ZVE-10 工具里的同名命令行为不能直接套到 A7C。
3. **`cmd_test_ui_view` 是桩**（`0x4dd2` 立即返回），没有 UI 操作。
4. **`cmd_format` 只清 nflasha6 的 `/tmp/jiritsu`**，不碰 nflasha15 / `/usr`。
5. **pFunc 层级 A 的映射修正**：`0x20 = FirmwareUpdateFunc`（不是别的），`0x30 = MiconAccessFunc`
   （返回 `NoAction 0x80`）；`0xff03` 才是 MemoryDump。
6. **FileControl “填充 bug”说法撤回**：type 1 的路径/长度处理是正常的 `vector<char>` + 终止符，
   问题在于**没有路径白名单**，不是缓冲区填充错误。
7. **Jiritsu 表是 19 条，从 `0x249c0` 开始**；`0x24930` 起的相邻表不是 0x1001（含两条 0x0f01）。
8. **场景类实际 40 条**（0x0306×25、0x0420×8、0x0601×1、0x0702×1、0x0b01×5）；
   之前把 class `0x1000` 的 testcmd 条目也算进“场景”是错的，`0x1000` 不进入 `testcmd_run_scenario`。
9. **`0x601` 的 RAM_READ/RAM_WRITE 不是物理内存读写**：是 ≤256 B 的 LSI 暂存缓冲路径。
10. **`0x603` 的 PDT_WRITE 不等于“写固件”**：是生产校准数据；风险高但不是刷写引导区。
11. **`0x0d01/0x0d02` 是电源轨设置**，不是普通寄存器；错误值可能造成硬件损坏，不能当“读状态”命令发。

---

## 10. 操作安全建议

- 只在**你拥有且可恢复**的机器上实验；服务模式本身可能改变启动状态。
- 先只发**只读**命令（`*_READ/GET/CHECK/STATUS/VERSION`）验证链路，再考虑写。
- 不要发 §7.6 列表中的命令；尤其是 `NOR_WRITE`、`NVM_*`、`UNINSTALL_*`、`CLEAR_DEVICE_UNIQUE_KEY`、
  `*_UPDATE_FW`、`*_FORMAT`、`*_MAKE_PARTITION`、`DD_*_SET`、`*EEPROM*`。
- 不要写 `/tmp/jiritsu/libJit.so`，除非你明确要执行自己的代码——写下去就会 `dlopen`。
- `SET_FILE_PATH` 的路径逃逸能力意味着：任何“只写调试目录”的假设都不成立；发之前先固定路径并验证。
- 需要物理内存读时，从低地址、小 size 开始，确认 `/dev/mem` 没有被内核拒绝；不要扫描未知设备区。
- 任何写操作前先断电/恢复方案；相机变砖的恢复通常需要官方固件更新，而本命令面不提供 nflasha15 的原始写。

---

## 11. 复现与脚本

```bash
# 1) 解析四张表（libsencore 的 disp/adj/host，libJiritsu 的 jir）
python3 sencore_tables.py list  out/bin/libsencore.so disp
python3 sencore_tables.py list  out/bin/libJiritsu.so jir

# 2) 生成完整命令表（1746 行）
python3 dump_commands.py --tsv commands.tsv

# 3) 查某个名字在哪些表
python3 sencore_tables.py grep out/bin/libsencore.so 'SET_FILE|NVM|NOR_WRITE'

# 4) 反汇编/符号/重定位
python3 elf_arm.py syms libsencore
python3 elf_arm.py func AdjustControlFunc
python3 elf_arm.py relocs | grep 0x61e
python3 elf_arm.py dis 0x14280 0x14a44

# 5) 镜像遍历与偏移归属（nflasha15 是 ext2）
python3 ext2_walk.py ../a7c-shared/nflasha15.bin --find 'libsencore|libJiritsu'
python3 imgmap.py ../a7c-shared/nflasha15.bin 0x1a218
```

`commands.tsv` 列：

| 列 | 含义 |
|---|---|
| `table` | `disp` / `jir` / `pfunc` |
| `idx` | 表内序号（disp 仅 0–1714 有效） |
| `block` / `code` | 表项原值；`wire_code` = `code & 0xff`（线上命令号） |
| `perm` | `L3`（需 `0x8000`）、`L2+`（需 `0x4000/0x8000`）、`any` |
| `class` | `scenario`（0x800）、`testcmd`（0x1000）、`-` |
| `qid` | OSAL 目标；场景类为 0 |
| `rw` | R / W / X / ?（启发式） |
| `target` | block 归属/目标 |
| `risk` | 只读 / 低 / 中 / 高 / ?（启发式） |
| `note` | 具体说明或“参数=OSAL 负载（接收端 qid 定义）” |

---

## 12. 证据索引

| 事实 | 位置 |
|---|---|
| pFunc 层级表 A/B/C | `libsencore.so` VA `0x61e30 / 0x61e78 / 0x61e98`；重定位在 `0x61e34…` |
| pFunc handler | `ProductInfo 0x13834`、`FirmwareUpdate 0x13274`、`MiconAccess 0x1356c`、`AdjustControl 0x14bec`、`TestMode 0x137dc`、`FileControl 0x14d54`、`Sonar 0x1354c`、`MemoryDump 0x14af8` |
| 认证结果/等级 | `onComplete 0x10a70`；GOT+`0x7f8/0x808/0x824/0x840/0x82c` |
| AdjustControl 入口 | `AdjustControlFunc 0x14bec` → `0x14a44` → `TransactionStart 0x14280` |
| 白名单表 | 文件偏移 `0x1a218`，步长 `0x48`，上界 `0x6b3`（`0x1446c/0x1449e`） |
| 匹配/权限/类别 | `0x14418–0x144b0` |
| 特殊本地路径判定 | `0x12ce0`；`0x601` 的 `0x1a/0xfe/0xff`、`0x603/0x0f` |
| 场景运行器 | `testcmd_run_scenario` 调用 `0x14954/0x16268`；扫描 `0x16228` |
| OSAL 回复 `/dev/mem` 写 | `0x13a60`，映射 `0x13b60–0x13b88`，`memcpy` `0x13c02` |
| MemoryDump | `0x14af8`；worker `0xffe0–0x10012`；`/dev/mem` 字符串 `0x1908e` |
| FileControl | `0x14d54`；`WriteDeviceData(path,0x1241,0x8000)` `0x14e4c–0x14e56` |
| GPIO ioctl | `0x163c0`（`0xc0104700`）、`0x1647a`（`0xc0104703`） |
| Jiritsu 表 | `libJiritsu.so` 文件偏移 `0x249c0`，步长 `0x48`，19 条 |
| Jiritsu TBB | `0x70b2` |
| Jiritsu handler | `format 0x48f8`、`start 0x4b60`、`debug 0x4da8`、`factory 0x519c`、`set_file_path 0x52a8`、`get_file 0x5468`、`set_file 0x56c0`、`delete 0x58f8`、`set_file2 0x5b00`、`delete2 0x5f18`、`get_file2 0x5fe8`、`set_firm 0x67ec`、`jit_thread 0x74b0` |
| dlopen 校验 | `0x5864`（SET_FILE）、`0x5da0`（SET_FILE2，路径 `/tmp/jiritsu/libJit.so`） |
| 路径处理 | `get_access_filename 0x5948`（无 `..` 检查） |
| Jiritsu 字符串 | `0x9000–0xa800`（`/dev/nflasha6` 0x9568、`/tmp/jiritsu` 0x953e、libJit.so 0x9a0a、tmmc.jit 0x99de、bak.tar 0x9e0d） |
| 模块来源 | `manifest.tsv`：`/lib/libsencore.so`、`/lib/libJiritsu.so`、`/bin/sen.elf`、`/bin/adjstctl.elf` |

---

**一句话总结**：A7C 的服务模式在代码层面提供了“任意物理内存读”和“任意文件写 + `dlopen` 代码加载”的
完整原语；物理写只有一个由对端地址驱动的 `/dev/mem` 写原语，主机能否控制地址仍未判定。
不改固件即可完成上述操作，但代价是**持久文件系统改动**和**极高的误操作风险**。
