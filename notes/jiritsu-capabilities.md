# Jiritsu / SensTALK 能力边界（**这条现在是最低风险的入口**）

> 全文报告 `notes/jiritsu-capabilities-fullreport.md`（894 行，MacBook 子代理 `jiritsu-cmds`），完整机器可读命令表 `notes/jiritsu-commands.tsv`（**1,746 条**：1,715 条 AdjustControl 白名单 + 19 条 Jiritsu + 12 条 pFunc）。
> 对象：v2.00，USB **服务模式 PID `0x054c:0x0336`**（日常 MSC 是 `0D29`）。全程静态分析，**没在真机发过命令**。
> 我在本机独立复核：从 a15 取出 `libJiritsu.so` 174,816 B、`libsencore.so` 369,804 B、`sen.elf` 19,164 B、`adjstctl.elf` 129,868 B；前者含 `/dev/mem`、`/dev/nflasha6`、`/tmp/jiritsu`、`/tmp/jiritsu.bak.tar`、`/tmp/jiritsu.bak.hash`、`/tmp/jiritsu/libJit.so`(`0x9a0a`)、`CreateScriptI/DestroyScriptI`、`libJit.so crashed.`、`/tmp/jiritsu/ramdsk_libJit/libJit.so`、`dlopen/dlsym/dlclose/dlerror`；后者含 `/dev/mem`、`/dev/nflasha5`、`/setting`、`/setting/.etools`、`/setting/.hasp`、`/setting/sen/`、`/setting/sen/smode`、`JIRITSU_SET_FILE/_2/_PATH`。

## 三条入口（都不需要签名、不需要刷任何固件分区）

| # | 入口 | 能力 | 证据 |
|---|---|---|---|
| **E-J1** | **pFunc `0xff03 MemoryDump`**（认证等级 A） | **任意物理地址读**：主机给 `{u32 base,u32 size}` → `DeviceIo("/dev/mem",0x1002)` + `MappedMemory(base,size,prot=3,flags=1)`，按 `0x8000` 分片回传（单包 ≤`0x100000`）。换 base 循环即覆盖任意 PA。 | 已证实（代码）；真机 `/dev/mem` 是否被策略拦＝未判定 |
| **E-J2** | **pFunc `0xff01 FileControl`（`type=1`）** + **Jiritsu `SET_FILE_PATH(15)`/`SET_FILE2(16)`** | **任意路径写文件**：`WriteDeviceData(path, 0x1241=O_WRONLY|O_CREAT|O_TRUNC|O_DSYNC, 0x8000)`，**路径由主机给、无清洗、无白名单**；`SET_FILE2` 还自动建父目录，**没发现 `..` 过滤**。⇒ **这就是"往 /setting 写东西"的写通道**（建 `mode/preload`、`env.txt`、改 `ulogio.bin` 都能不刷固件做） | 已证实（代码）；进程权限/挂载 rw＝未判定 |
| **E-J3** | **写 `/tmp/jiritsu/libJit.so` 即 `dlopen`**（`0x5d76–0x5db8`：`strcmp` 该路径后 `dlopen(RTLD_LAZY)`）+ **Jiritsu `START(4)`** 脚本引擎（`CreateScriptI/LoadScriptI/RunScriptI/DestroyScriptI`，还会先复制到 `/tmp/jiritsu/ramdsk_libJit/` 再加载） | **代码执行**：`.so` 的构造函数立刻在 Senser/libJiritsu 进程里跑 ⇒ **不用签名就能在我们自己代码里干活**（自己 mmap `/dev/mem`、自己读写 `/setting`、读 OTP 窗）| 已证实（链条）；真机未验证 |

补充：`0x601/0x1f` 只执行**固定路径** `/usr/bin/ulogio.elf`；没有"把机器码塞进内存跳转"的命令；**没有** CPU 寄存器读写命令、**没有** DMA 命令；GPIO/I2C/EEPROM/NVM/电源轨写命令一大堆（发错会伤硬件）。

## 为什么它比 Telnet/旗标更靠前
1. **不依赖网络**（Telnet 要相机有 IP）；2. **不需要先能写 a2**（它自己就是写通道）；3. **不碰 a1/a15/a3**：Jiritsu 的落盘区是 **a6(`/dev/nflasha6`，`/tmp/jiritsu`) 这个调试分区**，`cmd_format` 只清 a6、`FIRMUP` 也只作用 a6；**没有任何"原始写引导/系统分区"的命令** ⇒ 变砖面极小；4. 拿到代码执行后，Telnet/旗标/OTP 读全都变成我们自己能做的子步骤。
风险点：写文件能 `..` 逃逸到 `/usr`（若 a15 挂载可写＝未判定）；认证等级 A 需要完整握手（我们的 `hashsgetty` 认证链）；`libJit.so` **一写下去就执行**，别手滑。

## 不要发的命令（§7.6，误发不可逆）
`0x060b NOR_WRITE`、`0x060c/0x0c0e UNINSTALL_*`、**`CLEAR_DEVICE_UNIQUE_KEY`**、`0x3b01/0x4b01 NVM_*`（含 `NVM_RECOVERY`、`NVM_FLUSH_PARAMETER`）、`0x0318 CXS_UPDATE_FW`、`0x0c04/0x0c0c/0x0c0a` 各类固件加载、`0x2101 EXEC_FACTORY_RESET`、`0x0b01 MPR_CMD_FORMAT/MAKE_PARTITION`、`0x2b01 EXEC_MEDIA_FORMAT`、`0x0603 PDT_*/FACTORY*`、`0x0421 SAVE_ALL/SAVE_FORCE`、`0x4501 *EEPROM*`、`0x0d01/0x0d02 DD_*_SET`（电源轨，60+84 条）、`0x0701 WRITE_CUSTOMER_REGIST_HASH256`、`0x0c0d WIREDLAN_SET_MAC_ADDR`；`0x1001/4 START`、`0x1001/16 SET_FILE2` 是代码执行本身。

## 它对我笔记的修正（§9，我核过其中可核的）
`a15` 是 ext2；**`cmd_debug` 只设 RTC（固定 2017-07-04 21:42:26），不是提权入口**（ZV-E10 工具同名不能套）；`cmd_test_ui_view` 是桩（`0x4dd2` 立即返回）；`cmd_format` 只清 a6；pFunc 层级修正 `0x20=FirmwareUpdateFunc`、`0x30=MiconAccessFunc`(返回 NoAction 0x80)、`0xff03=MemoryDump`；FileControl 的"填充 bug"说法撤回（真正问题是**无路径白名单**）；Jiritsu 表 **19 条从 `0x249c0`** 起（`0x24930` 那张不是）；场景类实际 **40 条**；**`0x601 RAM_READ/WRITE` 不是物理内存**（≤256 B 的 LSI 暂存缓冲）；`0x603 PDT_WRITE` 是生产校准数据不是刷固件；`0x0d01/0x0d02` 是电源轨不是普通寄存器。

## 下一步要补的空白
**怎么把 A7C 弄进服务模式（PID `0336`）**——Jiritsu 这条链的前置条件只有一个这个。要查：进服务模式的触发（按键组合 / `MODE/SMODE` 旗标 / `SET/网络` 菜单 / 还是必须官方 Service Tool），以及进入后 USB 描述符怎么变。
